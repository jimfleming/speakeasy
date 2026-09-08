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
