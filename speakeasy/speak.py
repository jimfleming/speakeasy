"""Rewrite a Claude Code or Codex turn into one short spoken line and play it.

  extract the last turn from the transcript (or take a message directly)
  → one chat completion against an OpenAI-compatible endpoint
  → POST the text to the local Kokoro listener, which synthesizes and plays it

  uv run -m speakeasy.speak SESSION.jsonl --no-play

The completion step sends the turn digest -- user prompts, assistant prose and
tool names, with raw tool output stripped -- to the configured `rewrite`
endpoint.
"""
import argparse
import json
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

from speakeasy import config
from speakeasy.extract import extract, render

PROMPTS = Path(__file__).parent.resolve() / "prompts"
OUT = config.DATA_DIR
TURNS_LOG = OUT / "turns.jsonl"
TURNS_CAP = 50
TURNS_MAX_CHARS = 1_000_000
DIGEST_CHARS = 16000
LISTENER = os.environ.get(
    "SPEAKEASY_LISTENER", f"http://{config.BIND}:{config.PORT}").rstrip("/")
VOICE = os.environ.get("SPEAKEASY_VOICE")
BASE_URL = config.BASE_URL
MODEL = config.MODEL
API_KEY = config.API_KEY
ATTEMPTS = 3
TIMEOUT = 75


def _log_turn(digest, text, skipped=None):
    """Append one (input digest, spoken text) record to turns.jsonl."""
    try:
        OUT.mkdir(parents=True, exist_ok=True)
        rec = {"time": datetime.now().isoformat(timespec="seconds"),
               "model": MODEL, "digest": digest, "text": text}
        if skipped:
            rec["skipped"] = skipped
        with TURNS_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        _trim_turns()
    except Exception as e:
        print(f"[speak] log_turn failed: {e}", file=sys.stderr)


def _trim_turns():
    """Cap turns.jsonl to the last TURNS_CAP records and TURNS_MAX_CHARS."""
    try:
        lines = _log_lines()
        kept = lines[-TURNS_CAP:]
        while len(kept) > 1 and sum(len(l) + 1 for l in kept) > TURNS_MAX_CHARS:
            kept.pop(0)
        if len(kept) != len(lines):
            TURNS_LOG.write_text("".join(l + "\n" for l in kept), encoding="utf-8")
    except Exception as e:
        print(f"[speak] trim_turns failed: {e}", file=sys.stderr)


def _log_lines():
    return [l for l in TURNS_LOG.read_text(encoding="utf-8").splitlines() if l.strip()]


def _recent_records(k=8):
    """Return the last k logged turn records."""
    try:
        if not TURNS_LOG.exists():
            return []
        out = []
        for l in _log_lines()[-k:]:
            try:
                out.append(json.loads(l))
            except Exception:
                pass
        return out
    except Exception:
        return []


def _spoken_prefix(current, records):
    """Return the longest previously-spoken digest that `current` extends,
    or "" if none."""
    best = ""
    for r in records:
        d = r.get("digest")
        if (r.get("text") and d and d != current
                and current.startswith(d) and len(d) > len(best)):
            best = d
    return best


_ASCII_MAP = {
    "—": ", ", "–": ", ",
    "‒": "-", "‑": "-", "‐": "-",
    "‘": "'", "’": "'",
    "“": '"', "”": '"',
    "…": "...",
    " ": " ",
}


def _sanitize(text):
    """Convert rewrite output to plain speakable ASCII."""
    for k, v in _ASCII_MAP.items():
        text = text.replace(k, v)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"([,;:])(\s*[,;:])+", r"\1", text)
    text = re.sub(r" {2,}", " ", text)
    return text.strip()


def _prompt(name):
    """The copy in the data dir, restored from the packaged one if missing."""
    dest = config.PROMPTS_DIR / name
    if not dest.is_file():
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(f".{os.getpid()}.tmp")
        shutil.copyfile(PROMPTS / name, tmp)
        os.replace(tmp, dest)
    return dest.read_text(encoding="utf-8")


def _project_note(project):
    """Prompt fragment naming the project, in its configured spoken form."""
    if not project:
        return ""
    spoken = config.PRONUNCIATIONS.get(project, project)
    return (f'\n\nThis is from the project named "{spoken}". Name the project '
            "naturally as part of your first sentence so the listener knows which "
            "session is speaking; do not tack it on as a bare label.")


def _pronunciation_note():
    """Prompt fragment giving the spoken form of configured pronunciations."""
    pron = config.PRONUNCIATIONS
    if not pron:
        return ""
    pairs = "; ".join(f'"{k}" is said "{v}"' for k, v in pron.items())
    return ("\n\nPronunciation: if any of these names appear, say them as their "
            "spoken form, never spelled out letter by letter or with the "
            f"punctuation read aloud -- {pairs}.")


def _continues_note():
    """Prompt fragment for narrating only the new tail of a continued turn."""
    return ("\n\nThis continues a turn whose earlier work was already spoken in a "
            "previous line. Below you get that earlier work as CONTEXT ONLY, then "
            "the NEW work. Narrate ONLY the new work, and keep it to ONE short "
            "sentence -- just the new development, like \"Task one of three is "
            "done, reviewing now.\" Use the context only to understand the thread; "
            "do not recap or repeat any of it, and do not re-introduce the project "
            "by name.")


def _complete(prompt):
    """One chat completion against the configured OpenAI-compatible endpoint,
    retried on transient failure. Returns the stripped reply text."""
    url = f"{BASE_URL}/chat/completions"
    body = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    headers = {"Content-Type": "application/json"}
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"
    for attempt in range(ATTEMPTS):
        try:
            req = urllib.request.Request(url, data=body, method="POST", headers=headers)
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                data = json.loads(r.read().decode("utf-8", "replace"))
            text = ((data.get("choices") or [{}])[0]
                    .get("message", {}).get("content") or "").strip()
            if text:
                return text
            err = f"no content in response: {json.dumps(data)[:300]}"
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300] if e.fp else ""
            err = f"HTTP {e.code}: {detail}"
        except (urllib.error.URLError, TimeoutError) as e:
            err = f"request failed: {e}"
        except Exception as e:
            err = f"unexpected: {e}"
        print(f"[speak] attempt {attempt + 1}/{ATTEMPTS} ({MODEL}): {err}",
              file=sys.stderr)
        if attempt + 1 < ATTEMPTS:
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"completion produced no output after {ATTEMPTS} tries")


def _narrate(digest, project="", continuation=True):
    """Dedup `digest` against recent turns, rewrite it into a spoken line, log
    and return it. With `continuation`, a digest that extends an already-spoken
    one is narrated as just its new tail."""
    records = _recent_records()
    if digest in {r.get("digest") for r in records}:
        print("[speak] already recapped this exchange, nothing new to say", file=sys.stderr)
        return ""
    prior = _spoken_prefix(digest, records) if continuation else ""
    if prior:
        new_tail = digest[len(prior):].lstrip("\n")
        note = _continues_note()
        body = (f"\n\nAlready spoken earlier in this turn (CONTEXT ONLY -- do not "
                f"narrate or repeat this):\n\n{prior}\n\n"
                f"The NEW work to narrate now:\n\n{new_tail}")
    else:
        note = _project_note(project)
        body = f"\n\nHere is the turn:\n\n{digest}"
    text = _sanitize(_complete(f"{_prompt('speak.md')}{note}{_pronunciation_note()}{body}"))
    _log_turn(digest, text)
    return text


def rewrite(jsonl, project="", final_message=None):
    """Narrate the last turn of the transcript at `jsonl`. `final_message`, if
    given, overrides the transcript's own tail as the turn's final assistant
    text."""
    turns = extract(jsonl, since_last_user=True, final_message=final_message)
    digest = render(turns, DIGEST_CHARS)
    if not any(role == "Assistant" and (text or tools) for role, text, tools in turns):
        print("[speak] no assistant content in turn, nothing to recap", file=sys.stderr)
        _log_turn(digest, "", skipped="no assistant content")
        return ""
    return _narrate(digest, project)


def rewrite_text(message, project=""):
    """Narrate a final turn message given directly instead of extracted from a
    transcript (Codex reports its own)."""
    digest = message.strip()
    if not digest:
        print("[speak] empty message, nothing to recap", file=sys.stderr)
        return ""
    return _narrate(digest, project, continuation=False)


def speak_question(question, project=""):
    """Turn a pending question into a short spoken cue."""
    prompt = (f"{_prompt('ask.md')}{_project_note(project)}"
              f"{_pronunciation_note()}\n\nThe pending question:\n\n{question}")
    return _sanitize(_complete(prompt))


def say(text, session=""):
    payload = {"text": text, "session": session}
    if VOICE:
        payload["voice"] = VOICE
    data = json.dumps(payload).encode()
    req = urllib.request.Request(LISTENER + "/say", data=data, method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input", help="transcript .jsonl, or a text file with --ask/--codex")
    ap.add_argument("--ask", action="store_true",
                    help="treat input as a pending question to announce, not a transcript")
    ap.add_argument("--codex", action="store_true",
                    help="treat input as Codex's own final turn message, not a transcript")
    ap.add_argument("--no-play", action="store_true")
    ap.add_argument("--session", default="")
    ap.add_argument("--project", default="")
    ap.add_argument("--delete-input", action="store_true",
                    help="delete the input file when done")
    args = ap.parse_args()

    try:
        if args.ask:
            text = speak_question(Path(args.input).read_text(), args.project)
        elif args.codex:
            text = rewrite_text(Path(args.input).read_text(), args.project)
        else:
            text = rewrite(args.input, args.project,
                           os.environ.get("SPEAKEASY_LAST_MESSAGE") or None)
    finally:
        if args.delete_input:
            try:
                os.unlink(args.input)
            except OSError:
                pass

    if not text:
        print("[speak] empty rewrite, nothing to say", file=sys.stderr)
        return
    if args.no_play:
        print(text)
        return
    print(f"[speak] say: {say(text, args.session)}", file=sys.stderr)


if __name__ == "__main__":
    main()
