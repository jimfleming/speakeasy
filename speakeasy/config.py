"""Speakeasy configuration: one JSON file, with env overrides for dev.

    ~/Library/Application Support/Speakeasy/config.json

Every key below has a built-in default, so a missing or partial file is fine.
Precedence per value: env var > config.json > built-in default. The env var
for a key is its uppercased name prefixed with SPEAKEASY_ (nested keys under
"rewrite" drop the prefix, e.g. rewrite.base_url -> SPEAKEASY_BASE_URL).

SPEAKEASY_CONFIG and SPEAKEASY_PROMPTS_DIR relocate the config file and the
prompt directory themselves.
"""
import json
import os
import sys
from pathlib import Path

CONFIG_PATH = Path(os.environ.get(
    "SPEAKEASY_CONFIG",
    Path.home() / "Library" / "Application Support" / "Speakeasy" / "config.json",
))
# Runtime state (the rolling turn log) lives next to config.json.
DATA_DIR = CONFIG_PATH.parent
# Where the rewrite prompts are read from, seeded by `speakeasy init`.
PROMPTS_DIR = Path(os.environ.get("SPEAKEASY_PROMPTS_DIR", DATA_DIR / "prompts"))

DEFAULTS = {
    "rewrite": {
        "base_url": "https://openrouter.ai/api/v1",
        "model": "inception/mercury-2",
        "api_key": "",
    },
    "default_voice": "af_bella",
    # Per-session voice instead of default_voice for everything.
    "voice_rotation": True,
    "tts_model": "mlx-community/Kokoro-82M-bf16",
    "bind": "127.0.0.1",
    "port": 8765,
    # Maps a written name to its spoken form, e.g. {"k8s": "kubernetes"}.
    "pronunciations": {},
}


def _load_file():
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception as e:                              # malformed JSON, bad perms
        print(f"[config] {CONFIG_PATH} unreadable, using defaults: {e}",
              file=sys.stderr)
        return {}


_file = _load_file()


def _get(path, env, default):
    """env override > config.json (nested `path`) > default."""
    if env and os.environ.get(env):
        return os.environ[env]
    cur = _file
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur if cur not in (None, "") else default


def _get_int(path, env, default):
    """As _get, coercing to int. Falls back to `default` on a bad value."""
    value = _get(path, env, default)
    try:
        return int(value)
    except (TypeError, ValueError):
        print(f"[config] {'.'.join(path)}={value!r} is not a number, "
              f"using {default}", file=sys.stderr)
        return default


def _get_bool(path, env, default):
    """As _get, accepting JSON booleans and the usual env-var spellings."""
    value = _get(path, env, default)
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


BASE_URL = _get(["rewrite", "base_url"], "SPEAKEASY_BASE_URL",
                DEFAULTS["rewrite"]["base_url"]).rstrip("/")
MODEL = _get(["rewrite", "model"], "SPEAKEASY_MODEL", DEFAULTS["rewrite"]["model"])
API_KEY = (_get(["rewrite", "api_key"], "SPEAKEASY_API_KEY", "")
           or os.environ.get("OPENROUTER_API_KEY", ""))
DEFAULT_VOICE = _get(["default_voice"], "SPEAKEASY_DEFAULT_VOICE",
                     DEFAULTS["default_voice"])
VOICE_ROTATION = _get_bool(["voice_rotation"], "SPEAKEASY_VOICE_ROTATION",
                           DEFAULTS["voice_rotation"])
TTS_MODEL = _get(["tts_model"], "SPEAKEASY_TTS_MODEL", DEFAULTS["tts_model"])
BIND = _get(["bind"], "SPEAKEASY_BIND", DEFAULTS["bind"])
PORT = _get_int(["port"], "SPEAKEASY_PORT", DEFAULTS["port"])
PRONUNCIATIONS = _get(["pronunciations"], None, DEFAULTS["pronunciations"])
