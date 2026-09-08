import importlib
import json
from pathlib import Path


def load_config(tmp_path, monkeypatch, data):
    """Re-import speakeasy.config against a freshly written config.json."""
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setenv("SPEAKEASY_CONFIG", str(path))
    import speakeasy.config as cfg
    return importlib.reload(cfg)


def test_defaults_apply_when_the_file_is_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("SPEAKEASY_CONFIG", str(tmp_path / "nope.json"))
    import speakeasy.config as cfg
    c = importlib.reload(cfg)
    assert c.PORT == c.DEFAULTS["port"]
    assert c.VOICE_ROTATION is True


def test_malformed_json_falls_back_to_defaults(tmp_path, monkeypatch, capsys):
    path = tmp_path / "config.json"
    path.write_text("{ not json", encoding="utf-8")
    monkeypatch.setenv("SPEAKEASY_CONFIG", str(path))
    import speakeasy.config as cfg
    c = importlib.reload(cfg)
    assert c.PORT == 8765
    assert "unreadable" in capsys.readouterr().err


def test_a_non_numeric_port_does_not_crash_the_import(tmp_path, monkeypatch, capsys):
    c = load_config(tmp_path, monkeypatch, {"port": "eight thousand"})
    assert c.PORT == 8765
    assert "not a number" in capsys.readouterr().err


def test_voice_rotation_can_be_disabled(tmp_path, monkeypatch):
    assert load_config(tmp_path, monkeypatch, {"voice_rotation": False}).VOICE_ROTATION is False


def test_env_overrides_the_file(tmp_path, monkeypatch):
    monkeypatch.setenv("SPEAKEASY_PORT", "9999")
    assert load_config(tmp_path, monkeypatch, {"port": 8765}).PORT == 9999


def test_base_url_trailing_slash_is_stripped(tmp_path, monkeypatch):
    c = load_config(tmp_path, monkeypatch, {"rewrite": {"base_url": "http://x/v1/"}})
    assert c.BASE_URL == "http://x/v1"


def test_prompts_dir_defaults_beside_the_config(tmp_path, monkeypatch):
    monkeypatch.delenv("SPEAKEASY_PROMPTS_DIR", raising=False)
    c = load_config(tmp_path, monkeypatch, {})
    assert c.PROMPTS_DIR == tmp_path / "prompts"


def test_prompts_dir_can_be_relocated(tmp_path, monkeypatch):
    """Lets a clone iterate on the prompts it ships; see the README."""
    monkeypatch.setenv("SPEAKEASY_PROMPTS_DIR", "speakeasy/prompts")
    c = load_config(tmp_path, monkeypatch, {})
    assert c.PROMPTS_DIR == Path("speakeasy/prompts")
