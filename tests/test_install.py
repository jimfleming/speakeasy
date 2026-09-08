import json

import pytest

from speakeasy import install


@pytest.fixture
def paths(tmp_path, monkeypatch):
    monkeypatch.setattr(install, "CLAUDE_SETTINGS_PATH", tmp_path / "settings.json")
    monkeypatch.setattr(install, "CODEX_CONFIG_PATH", tmp_path / "codex" / "config.toml")
    (tmp_path / "codex").mkdir()
    return tmp_path


def claude(paths):
    return json.loads((paths / "settings.json").read_text())


def test_register_claude_is_idempotent(paths, capsys):
    install._register_claude(False)
    first = claude(paths)
    install._register_claude(False)
    assert "already registered" in capsys.readouterr().out
    assert claude(paths) == first
    assert len(first["hooks"]["Stop"]) == 1
    assert len(first["hooks"]["PreToolUse"]) == 1


def test_register_claude_preserves_unrelated_hooks(paths):
    (paths / "settings.json").write_text(json.dumps({
        "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "say hi"}]}]},
        "model": "opus",
    }))
    install._register_claude(False)
    settings = claude(paths)
    assert settings["model"] == "opus"
    commands = [h["command"] for b in settings["hooks"]["Stop"] for h in b["hooks"]]
    assert commands == ["say hi", install.CLAUDE_HOOK_CMD]


def test_uninstall_removes_only_our_hooks(paths):
    (paths / "settings.json").write_text(json.dumps({
        "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "say hi"}]}]}}))
    install._register_claude(False)
    install._unregister_claude()
    commands = [h["command"] for b in claude(paths)["hooks"]["Stop"] for h in b["hooks"]]
    assert commands == ["say hi"]


def test_codex_notify_is_written_before_any_table(paths):
    install.CODEX_CONFIG_PATH.write_text('model = "gpt-5"\n\n[tui]\nx = 1\n')
    install._register_codex(False)
    body = install.CODEX_CONFIG_PATH.read_text()
    assert body.splitlines()[0] == install.CODEX_NOTIFY_LINE.strip()
    assert body.index("notify") < body.index("[tui]")
    assert 'model = "gpt-5"' in body


def test_codex_registration_is_idempotent_wherever_the_line_sits(paths, capsys):
    """The check is semantic, not positional: our line need not be first."""
    install.CODEX_CONFIG_PATH.write_text(
        '[tui]\nx = 1\n' + install.CODEX_NOTIFY_LINE)
    install._register_codex(False)
    assert "already registered" in capsys.readouterr().out


def test_codex_leaves_a_foreign_notify_entry_alone(paths, capsys):
    original = 'notify = ["some-other-tool"]\n'
    install.CODEX_CONFIG_PATH.write_text(original)
    install._register_codex(False)
    assert "leaving it alone" in capsys.readouterr().out
    assert install.CODEX_CONFIG_PATH.read_text() == original


def test_codex_unregister_keeps_a_foreign_notify_entry(paths):
    install.CODEX_CONFIG_PATH.write_text(
        'notify = ["some-other-tool"]\n' + install.CODEX_NOTIFY_LINE)
    install._unregister_codex()
    assert install.CODEX_CONFIG_PATH.read_text() == 'notify = ["some-other-tool"]\n'


def test_seed_config_is_private_and_complete(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    monkeypatch.setattr(install, "CONFIG_PATH", path)
    monkeypatch.setattr(install.sys.stdin, "isatty", lambda: False)
    install._seed_config(False)
    assert path.stat().st_mode & 0o777 == 0o600
    assert set(json.loads(path.read_text())) == set(install.config.DEFAULTS)


def test_init_seeds_both_prompts(tmp_path, monkeypatch):
    monkeypatch.setattr(install.config, "PROMPTS_DIR", tmp_path / "prompts")
    install._seed_prompts(False)
    speak = tmp_path / "prompts" / "speak.md"
    assert speak.read_text() == (install.PACKAGED_PROMPTS / "speak.md").read_text()
    assert (tmp_path / "prompts" / "ask.md").exists()


def test_reinit_never_clobbers_an_edited_prompt(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(install.config, "PROMPTS_DIR", tmp_path / "prompts")
    install._seed_prompts(False)
    speak = tmp_path / "prompts" / "speak.md"
    speak.write_text("my edit")
    install._seed_prompts(False)
    assert "leaving it alone" in capsys.readouterr().out
    assert speak.read_text() == "my edit"


def test_force_reseeds_the_packaged_prompt(tmp_path, monkeypatch):
    monkeypatch.setattr(install.config, "PROMPTS_DIR", tmp_path / "prompts")
    install._seed_prompts(False)
    speak = tmp_path / "prompts" / "speak.md"
    speak.write_text("my edit")
    install._seed_prompts(True)
    assert speak.read_text().startswith("You narrate ONE Claude Code turn")


def test_purge_removes_prompt_overrides(tmp_path, monkeypatch):
    monkeypatch.setattr(install, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(install.config, "PROMPTS_DIR", tmp_path / "prompts")
    monkeypatch.setattr(install, "_unregister_claude", lambda: None)
    monkeypatch.setattr(install, "_unregister_codex", lambda: None)
    install._seed_prompts(False)
    install.cmd_uninstall(["--purge"])
    assert not (tmp_path / "prompts").exists()


def test_uninstall_without_purge_keeps_prompt_overrides(tmp_path, monkeypatch):
    monkeypatch.setattr(install, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(install.config, "PROMPTS_DIR", tmp_path / "prompts")
    monkeypatch.setattr(install, "_unregister_claude", lambda: None)
    monkeypatch.setattr(install, "_unregister_codex", lambda: None)
    install._seed_prompts(False)
    install.cmd_uninstall([])
    assert (tmp_path / "prompts" / "speak.md").exists()


def test_healthy_is_false_when_nothing_is_listening(monkeypatch):
    monkeypatch.setattr(install.config, "PORT", 1)     # nothing listens on port 1
    assert install._healthy(timeout=1) is False


def test_healthy_parses_the_health_payload(monkeypatch):
    import contextlib, io

    @contextlib.contextmanager
    def fake_urlopen(url, timeout=None):
        yield io.BytesIO(b'{"ok": true}')
    monkeypatch.setattr(install.urllib.request, "urlopen", fake_urlopen)
    assert install._healthy() is True


def test_doctor_reports_a_down_listener_without_starting_it(monkeypatch, capsys):
    monkeypatch.setattr(install, "_healthy", lambda *a, **k: False)
    monkeypatch.setattr(install, "_start_service",
                        lambda: pytest.fail("--no-start must not start anything"))
    assert install.cmd_doctor(["--no-start"]) == 1
    out = capsys.readouterr().out
    assert "listener" in out and "FAIL" in out
    assert "needs attention" in out


def test_doctor_passes_when_everything_is_up(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(install, "CONFIG_PATH", tmp_path / "config.json")
    (tmp_path / "config.json").write_text("{}")
    monkeypatch.setattr(install.config, "API_KEY", "sk-test")
    monkeypatch.setattr(install, "_healthy", lambda *a, **k: True)
    monkeypatch.setattr(install, "_hook_present", lambda *a, **k: True)
    assert install.cmd_doctor([]) == 0
    assert "All good" in capsys.readouterr().out


def test_start_service_owns_the_agent_end_to_end(tmp_path, monkeypatch, capsys):
    """bootout both labels, wait for the port, bootstrap, kickstart."""
    agent = tmp_path / "com.jimfleming.speakeasy.plist"
    monkeypatch.setattr(install, "AGENT_PATH", agent)
    monkeypatch.setattr(install.config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(install, "_wait_healthy", lambda s: True)
    monkeypatch.setattr(install, "_wait_down", lambda s: True)
    monkeypatch.setattr(install.shutil, "which", lambda _: "/opt/homebrew/bin/speakeasy")
    calls = []
    monkeypatch.setattr(install, "_run", lambda cmd: (calls.append(cmd), (True, ""))[1])

    assert install._start_service() is True
    verbs = [c[1] for c in calls]
    assert verbs == ["bootout", "bootout", "bootstrap", "kickstart"]
    assert install.BREW_LABEL in calls[0][2]      # brew's label is evicted first
    assert install.LABEL in calls[1][2]

    plist = agent.read_text()
    assert "<string>/opt/homebrew/bin/speakeasy</string>" in plist
    assert "<string>app</string>" in plist
    assert "<key>RunAtLoad</key><true/>" in plist
    assert "<key>LimitLoadToSessionType</key><string>Aqua</string>" in plist


def test_agent_program_prefers_the_console_script(monkeypatch):
    """A Cellar path would break on upgrade; the PATH symlink survives."""
    monkeypatch.setattr(install.shutil, "which", lambda _: "/opt/homebrew/bin/speakeasy")
    assert install._agent_program() == ["/opt/homebrew/bin/speakeasy", "app"]


def test_agent_program_falls_back_without_a_console_script(monkeypatch):
    monkeypatch.setattr(install.shutil, "which", lambda _: None)
    prog = install._agent_program()
    assert prog[1:] == ["-m", "speakeasy.cli", "app"]


def test_uninstall_removes_the_agent(tmp_path, monkeypatch):
    agent = tmp_path / "agent.plist"; agent.write_text("<plist/>")
    monkeypatch.setattr(install, "AGENT_PATH", agent)
    monkeypatch.setattr(install, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(install, "_run", lambda cmd: (True, ""))
    monkeypatch.setattr(install, "_unregister_claude", lambda: None)
    monkeypatch.setattr(install, "_unregister_codex", lambda: None)
    install.cmd_uninstall([])
    assert not agent.exists()
