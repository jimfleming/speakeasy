"""Hook entry points invoked by Claude Code and Codex, not by the user."""
import base64
import json
import os
import sys
import urllib.error
import urllib.request

from speakeasy import config

TIMEOUT = 3


def _post(path, body, headers=None):
    url = f"http://127.0.0.1:{config.PORT}{path}"
    req = urllib.request.Request(url, data=body, method="POST", headers=headers or {})
    try:
        urllib.request.urlopen(req, timeout=TIMEOUT)
    except (urllib.error.URLError, OSError):
        pass


def claude_hook():
    """Claude Code Stop hook: ship the transcript tail to /claude-turn."""
    payload = json.loads(sys.stdin.read() or "{}")
    if payload.get("stop_hook_active"):
        return
    transcript_path = payload.get("transcript_path", "")
    if not transcript_path or not os.path.isfile(transcript_path):
        return
    with open(transcript_path, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - 262144))
        raw = f.read()
    last = (payload.get("last_assistant_message") or "").encode()
    _post("/claude-turn", raw, {
        "X-Speakeasy-Session": payload.get("session_id", ""),
        "X-Speakeasy-Project": os.path.basename(payload.get("cwd", "").rstrip("/")),
        "X-Speakeasy-Last": base64.b64encode(last).decode(),
    })


def claude_ask_hook():
    """Claude Code PreToolUse/AskUserQuestion hook: ship the question to /ask."""
    payload = json.loads(sys.stdin.read() or "{}")
    parts = []
    for q in payload.get("tool_input", {}).get("questions", []):
        text = (q.get("question") or "").strip()
        options = [o.get("label", "") for o in q.get("options", [])]
        if text and options:
            text += " Options: " + ", ".join(options) + "."
        if text:
            parts.append(text)
    text = " ".join(parts)
    if not text:
        return
    body = json.dumps({
        "text": text,
        "session": payload.get("session_id", ""),
        "project": os.path.basename(payload.get("cwd", "").rstrip("/")),
    }).encode()
    _post("/ask", body, {"Content-Type": "application/json"})


def codex_notify(argv):
    """Codex `notify` hook: ship the final turn message to /codex-turn.
    argv's last element is the JSON payload."""
    if not argv:
        return
    try:
        payload = json.loads(argv[-1])
    except json.JSONDecodeError:
        return
    text = payload.get("last-assistant-message") or payload.get("last_assistant_message") or ""
    if not text:
        return
    cwd = payload.get("cwd", "")
    body = json.dumps({
        "text": text,
        "session": payload.get("turn-id") or payload.get("thread-id") or "",
        "project": os.path.basename(cwd.rstrip("/")) if cwd else "",
    }).encode()
    _post("/codex-turn", body, {"Content-Type": "application/json"})
