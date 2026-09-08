"""`speakeasy init` / `speakeasy uninstall`: registers and removes speakeasy's
hooks in Claude Code's settings.json and Codex's config.toml, and seeds
config.json. Idempotent and non-destructive: an existing entry is detected and
left alone, never duplicated or clobbered.
"""
import argparse
import copy
import getpass
import json
import shutil
import sys
from pathlib import Path

from speakeasy import config
from speakeasy.speak import PROMPTS as PACKAGED_PROMPTS

CLAUDE_SETTINGS_PATH = Path.home() / ".claude" / "settings.json"
CODEX_CONFIG_PATH = Path.home() / ".codex" / "config.toml"
CONFIG_PATH = config.CONFIG_PATH

CLAUDE_HOOK_CMD = "speakeasy claude-hook"
CLAUDE_ASK_HOOK_CMD = "speakeasy claude-ask-hook"
CODEX_NOTIFY_LINE = 'notify = ["speakeasy", "codex-notify"]\n'
PROMPT_NAMES = ("speak.md", "ask.md")


# ---------- config.json ----------

def _seed_config(force):
    if CONFIG_PATH.exists() and not force:
        print(f"  {CONFIG_PATH} already exists, leaving it alone (--force to overwrite)")
        return
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    key = ""
    if sys.stdin.isatty():
        key = getpass.getpass(
            "  API key for the rewrite endpoint "
            "(blank to skip, set later in config.json): ").strip()
    cfg = copy.deepcopy(config.DEFAULTS)
    cfg["rewrite"]["api_key"] = key
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    CONFIG_PATH.chmod(0o600)
    print(f"  wrote {CONFIG_PATH}")
    if not key:
        print(f"  (no API key set -- add rewrite.api_key to {CONFIG_PATH} before running)")


def _seed_prompts(force):
    config.PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
    for name in PROMPT_NAMES:
        dest = config.PROMPTS_DIR / name
        if dest.exists() and not force:
            print(f"  {dest.name} already exists, leaving it alone (--force to overwrite)")
            continue
        shutil.copyfile(PACKAGED_PROMPTS / name, dest)
        print(f"  wrote {dest}")


# ---------- ~/.claude/settings.json ----------

def _load_json(path):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"error: {path} has invalid JSON ({e}); fix or remove it first",
                  file=sys.stderr)
            sys.exit(1)
    return {}


def _save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        backup = path.with_suffix(path.suffix + ".bak")
        shutil.copy2(path, backup)
        print(f"  backed up existing {path.name} -> {backup.name}")
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _hook_present(blocks, matcher, needle):
    for block in blocks:
        if matcher is not None and block.get("matcher") != matcher:
            continue
        if any(needle in h.get("command", "") for h in block.get("hooks", [])):
            return True
    return False


def _without_hook(blocks, needle):
    """Drop any block whose commands mention `needle`."""
    return [b for b in blocks
            if not any(needle in h.get("command", "")
                       for h in b.get("hooks", []))]


def _register_claude(force):
    settings = _load_json(CLAUDE_SETTINGS_PATH)
    hooks = settings.setdefault("hooks", {})
    stop_blocks = hooks.setdefault("Stop", [])
    ask_blocks = hooks.setdefault("PreToolUse", [])

    changed = False
    if force or not _hook_present(stop_blocks, None, CLAUDE_HOOK_CMD):
        stop_blocks[:] = _without_hook(stop_blocks, CLAUDE_HOOK_CMD) + [
            {"hooks": [{"type": "command", "command": CLAUDE_HOOK_CMD}]}
        ]
        changed = True
    if force or not _hook_present(ask_blocks, "AskUserQuestion", CLAUDE_ASK_HOOK_CMD):
        ask_blocks[:] = _without_hook(ask_blocks, CLAUDE_ASK_HOOK_CMD) + [
            {"matcher": "AskUserQuestion",
             "hooks": [{"type": "command", "command": CLAUDE_ASK_HOOK_CMD}]}
        ]
        changed = True

    if changed:
        _save_json(CLAUDE_SETTINGS_PATH, settings)
        print(f"  registered Claude Code hooks in {CLAUDE_SETTINGS_PATH}")
    else:
        print("  Claude Code hooks already registered")


def _unregister_claude():
    if not CLAUDE_SETTINGS_PATH.exists():
        return
    settings = _load_json(CLAUDE_SETTINGS_PATH)
    hooks = settings.get("hooks", {})
    changed = False
    for event, needle in (("Stop", CLAUDE_HOOK_CMD), ("PreToolUse", CLAUDE_ASK_HOOK_CMD)):
        blocks = hooks.get(event, [])
        kept = _without_hook(blocks, needle)
        if len(kept) != len(blocks):
            hooks[event] = kept
            changed = True
    if changed:
        _save_json(CLAUDE_SETTINGS_PATH, settings)
        print(f"  removed Claude Code hooks from {CLAUDE_SETTINGS_PATH}")


# ---------- ~/.codex/config.toml ----------

def _is_notify_line(line):
    return line.strip().startswith("notify")


def _register_codex(force):
    if not CODEX_CONFIG_PATH.parent.exists():
        print(f"  {CODEX_CONFIG_PATH.parent} not found -- skipping Codex "
              f"(install Codex, then re-run `speakeasy init`)")
        return
    existing = CODEX_CONFIG_PATH.read_text(encoding="utf-8") if CODEX_CONFIG_PATH.exists() else ""
    lines = existing.splitlines()
    notify_lines = [l for l in lines if _is_notify_line(l)]
    if any("speakeasy" in l for l in notify_lines):
        print("  Codex notify hook already registered")
        return
    if notify_lines and not force:
        print(f"  {CODEX_CONFIG_PATH} already has a `notify` entry -- leaving it alone "
              f"(merge manually: {CODEX_NOTIFY_LINE.strip()}, or re-run with --force)")
        return
    if CODEX_CONFIG_PATH.exists():
        backup = CODEX_CONFIG_PATH.with_suffix(".toml.bak")
        shutil.copy2(CODEX_CONFIG_PATH, backup)
        print(f"  backed up existing config.toml -> {backup.name}")
    body = "\n".join(l for l in lines if not _is_notify_line(l))
    if body:
        body += "\n"
    CODEX_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CODEX_CONFIG_PATH.write_text(CODEX_NOTIFY_LINE + body, encoding="utf-8")
    print(f"  registered Codex notify hook in {CODEX_CONFIG_PATH}")


def _unregister_codex():
    if not CODEX_CONFIG_PATH.exists():
        return
    existing = CODEX_CONFIG_PATH.read_text(encoding="utf-8")
    kept = [l for l in existing.splitlines()
            if not (_is_notify_line(l) and "speakeasy" in l)]
    if len(kept) != len(existing.splitlines()):
        CODEX_CONFIG_PATH.write_text("\n".join(kept) + "\n" if kept else "",
                                     encoding="utf-8")
        print(f"  removed Codex notify hook from {CODEX_CONFIG_PATH}")


# ---------- entry points ----------

def cmd_init(argv):
    ap = argparse.ArgumentParser(prog="speakeasy init")
    ap.add_argument("--force", action="store_true",
                    help="overwrite an existing config.json, prompt or notify entry")
    args = ap.parse_args(argv)

    print("1. Config...")
    _seed_config(args.force)
    print("2. Prompts...")
    _seed_prompts(args.force)
    print("3. Claude Code hooks...")
    _register_claude(args.force)
    print("4. Codex hooks...")
    _register_codex(args.force)
    print("\nDone. Start speakeasy with: brew services start speakeasy")
    print("Restart any running Claude Code / Codex session for the hooks to take effect.")


def cmd_uninstall(argv):
    ap = argparse.ArgumentParser(prog="speakeasy uninstall")
    ap.add_argument("--purge", action="store_true",
                    help="also delete config.json (kept by default)")
    args = ap.parse_args(argv)

    print("Removing Claude Code hooks...")
    _unregister_claude()
    print("Removing Codex hooks...")
    _unregister_codex()
    if args.purge:
        if CONFIG_PATH.exists():
            CONFIG_PATH.unlink()
            print(f"Deleted {CONFIG_PATH}")
        if config.PROMPTS_DIR.is_dir():
            shutil.rmtree(config.PROMPTS_DIR)
            print(f"Deleted {config.PROMPTS_DIR}")
    print("\nDone. Run `brew uninstall speakeasy` to remove the app itself.")
