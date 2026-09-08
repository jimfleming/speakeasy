"""Turn a Claude Code .jsonl transcript into a digest: user asks, assistant
prose, and compact tool-action summaries, with raw tool I/O stripped out.

  uv run -m speakeasy.extract SESSION.jsonl [--last-turn] [--max-chars N]

Prints the digest to stdout, keeping the tail under the char budget.

Invariant: for a fixed anchor the digest is append-only. When the Stop hook
fires twice inside one user turn, the second digest starts with the first.
speak.py's _spoken_prefix depends on it.
"""
import argparse
import json
import sys


def _text_blocks(content):
    """Return (text, tool_counts) from a message.content (str or list)."""
    if isinstance(content, str):
        return content.strip(), {}
    texts, tools = [], {}
    for block in content or []:
        if not isinstance(block, dict):
            continue
        t = block.get("type")
        if t == "text":
            txt = block.get("text", "").strip()
            if txt:
                texts.append(txt)
        elif t == "tool_use":
            name = block.get("name", "tool")
            tools[name] = tools.get(name, 0) + 1
        # tool_result blocks (raw output) are intentionally dropped
    return "\n".join(texts).strip(), tools


def _is_tool_result(content):
    if isinstance(content, list):
        return any(isinstance(b, dict) and b.get("type") == "tool_result"
                   for b in content)
    return False


def extract(path, last_turns=None, since_last_user=False, final_message=None):
    turns = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            etype = ev.get("type")
            msg = ev.get("message") or {}
            content = msg.get("content")
            if etype == "user":
                if _is_tool_result(content):
                    continue  # tool output coming back, not a human turn
                text, _ = _text_blocks(content)
                if text and not text.startswith("<"):  # skip system-reminder-ish
                    turns.append(("User", text, {}))
            elif etype == "assistant":
                text, tools = _text_blocks(content)
                if text or tools:
                    turns.append(("Assistant", text, tools))

    if final_message:
        fm = final_message.strip()
        last_asst = next((t for t in reversed(turns) if t[0] == "Assistant"), None)
        if fm and not (last_asst and last_asst[1].strip().endswith(fm)):
            turns.append(("Assistant", fm, {}))

    if since_last_user:
        # Latest complete exchange: the last user turn with an assistant reply
        # after it, through the last assistant turn.
        anchor = 0
        for i in (j for j, t in enumerate(turns) if t[0] == "User"):
            if any(r == "Assistant" and (txt or tools)
                   for r, txt, tools in turns[i + 1:]):
                anchor = i
        last_asst = max((j for j, t in enumerate(turns)
                         if t[0] == "Assistant" and (t[1] or t[2])),
                        default=len(turns) - 1)
        turns = turns[anchor:last_asst + 1]
    if last_turns:
        turns = turns[-last_turns:]
    return turns


def render(turns, max_chars):
    blocks = []
    for role, text, tools in turns:
        head = f"## {role}"
        if tools:
            summary = ", ".join(f"{n}x{c}" for n, c in sorted(tools.items()))
            head += f"  [actions: {summary}]"
        blocks.append(f"{head}\n{text}" if text else head)
    out = "\n\n".join(blocks)
    if len(out) > max_chars:                      # keep the tail
        out = "...\n\n" + out[-max_chars:]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("jsonl")
    ap.add_argument("--max-chars", type=int, default=24000)
    ap.add_argument("--last-turns", type=int, default=None)
    ap.add_argument("--last-turn", action="store_true",
                    help="only the latest exchange (since the last user message)")
    args = ap.parse_args()
    turns = extract(args.jsonl, last_turns=args.last_turns,
                    since_last_user=args.last_turn)
    sys.stdout.write(render(turns, args.max_chars))


if __name__ == "__main__":
    main()
