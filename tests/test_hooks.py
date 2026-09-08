import base64
import json

from speakeasy import hooks, listener


def capture(monkeypatch):
    sent = {}
    monkeypatch.setattr(hooks, "_post",
                        lambda path, body, headers=None: sent.update(
                            path=path, body=body, headers=headers or {}))
    return sent


def test_claude_hook_ships_the_transcript_tail(tmp_path, monkeypatch):
    transcript = tmp_path / "t.jsonl"
    transcript.write_text("line one\nline two\n")
    sent = capture(monkeypatch)
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(json.dumps({
        "transcript_path": str(transcript), "session_id": "s1",
        "cwd": "/Users/x/Projects/demo/", "last_assistant_message": "all done",
    })))
    hooks.claude_hook()
    assert sent["path"] == "/claude-turn"
    assert sent["body"] == b"line one\nline two\n"
    assert sent["headers"]["X-Speakeasy-Project"] == "demo"
    assert base64.b64decode(sent["headers"]["X-Speakeasy-Last"]) == b"all done"


def test_claude_hook_ignores_a_reentrant_stop(tmp_path, monkeypatch):
    sent = capture(monkeypatch)
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(
        json.dumps({"stop_hook_active": True, "transcript_path": "/nope"})))
    hooks.claude_hook()
    assert sent == {}


def test_ask_hook_flattens_questions_and_options(monkeypatch):
    sent = capture(monkeypatch)
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(json.dumps({
        "session_id": "s1", "cwd": "/x/demo",
        "tool_input": {"questions": [
            {"question": "Which voice?", "options": [{"label": "bella"}, {"label": "adam"}]}]},
    })))
    hooks.claude_ask_hook()
    assert json.loads(sent["body"])["text"] == "Which voice? Options: bella, adam."


def test_ask_hook_skips_an_empty_payload(monkeypatch):
    sent = capture(monkeypatch)
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO("{}"))
    hooks.claude_ask_hook()
    assert sent == {}


def test_codex_notify_accepts_either_key_spelling(monkeypatch):
    sent = capture(monkeypatch)
    hooks.codex_notify([json.dumps(
        {"last-assistant-message": "done", "cwd": "/x/demo", "turn-id": "t1"})])
    assert json.loads(sent["body"]) == {"text": "done", "session": "t1", "project": "demo"}


def test_codex_notify_ignores_malformed_input(monkeypatch):
    sent = capture(monkeypatch)
    hooks.codex_notify(["not json"])
    hooks.codex_notify([])
    assert sent == {}


def test_voice_rotation_is_deterministic_and_spreads(monkeypatch):
    monkeypatch.setattr(listener.config, "VOICE_ROTATION", True)
    assert listener.voice_for("abc") == listener.voice_for("abc")
    voices = {listener.voice_for(f"session-{i}") for i in range(200)}
    assert voices == set(listener.VOICES)


def test_voice_rotation_falls_back_without_a_session(monkeypatch):
    monkeypatch.setattr(listener.config, "VOICE_ROTATION", True)
    assert listener.voice_for("") == listener.DEFAULT_VOICE


def test_default_voice_wins_when_rotation_is_off(monkeypatch):
    monkeypatch.setattr(listener.config, "VOICE_ROTATION", False)
    assert {listener.voice_for(f"s{i}") for i in range(50)} == {listener.DEFAULT_VOICE}


def test_serve_reports_an_unusable_bind_address(monkeypatch):
    """A bad `bind` must raise with the config path, not die silently."""
    import pytest
    monkeypatch.setattr(listener, "HOST", "no-such-host.invalid")
    with pytest.raises(OSError) as exc:
        listener.serve()
    assert "cannot bind" in str(exc.value)
    assert "config.json" in str(exc.value)


def test_serve_retries_a_port_still_held_by_a_restarting_instance(monkeypatch):
    """launchd restarts can overlap; a transient EADDRINUSE must not be fatal."""
    import errno
    attempts = []

    class Boom(OSError):
        pass

    def flaky(addr, handler):
        attempts.append(addr)
        if len(attempts) < 3:
            e = OSError(errno.EADDRINUSE, "Address already in use")
            e.errno = errno.EADDRINUSE
            raise e
        raise KeyboardInterrupt          # bound; bail out of serve_forever

    monkeypatch.setattr(listener, "ThreadingHTTPServer", flaky)
    monkeypatch.setattr(listener.time, "sleep", lambda s: None)
    try:
        listener.serve()
    except KeyboardInterrupt:
        pass
    assert len(attempts) == 3


def test_app_runs_as_an_accessory_so_no_dock_icon(monkeypatch):
    """The framework interpreter defaults to Regular, which shows a Dock icon."""
    from speakeasy import app as app_mod
    calls = []

    class FakeNSApplication:
        @staticmethod
        def sharedApplication():
            class _App:
                def setActivationPolicy_(self, p): calls.append(p)
            return _App()

    monkeypatch.setattr(app_mod, "NSApplication", FakeNSApplication)
    monkeypatch.setattr(app_mod.rumps.App, "run", lambda self: None)
    monkeypatch.setattr(app_mod.rumps.events.before_start, "register", lambda f: None)
    app_mod.SpeakeasyApp.run(object.__new__(app_mod.SpeakeasyApp))
    assert calls == [app_mod.NSApplicationActivationPolicyAccessory]
