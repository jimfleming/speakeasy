import json

import pytest

from speakeasy.extract import extract, render


def write(tmp_path, events, name="t.jsonl"):
    p = tmp_path / name
    p.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
    return str(p)


def user(text):
    return {"type": "user", "message": {"content": [{"type": "text", "text": text}]}}


def assistant(text=None, tools=()):
    blocks = []
    if text:
        blocks.append({"type": "text", "text": text})
    blocks += [{"type": "tool_use", "name": n} for n in tools]
    return {"type": "assistant", "message": {"content": blocks}}


def tool_result():
    return {"type": "user", "message": {"content": [{"type": "tool_result", "content": "x"}]}}


def test_tool_results_are_not_user_turns(tmp_path):
    path = write(tmp_path, [user("hi"), assistant(tools=["Bash"]), tool_result(),
                            assistant("done")])
    roles = [r for r, _, _ in extract(path)]
    assert roles == ["User", "Assistant", "Assistant"]


def test_raw_tool_output_is_dropped(tmp_path):
    path = write(tmp_path, [user("hi"), assistant("ok", tools=["Bash", "Bash"])])
    digest = render(extract(path), 10_000)
    assert "[actions: Bashx2]" in digest
    assert "x" not in digest.split("[actions")[0].replace("## ", "")


def test_since_last_user_anchors_on_the_last_answered_ask(tmp_path):
    path = write(tmp_path, [user("first"), assistant("a1"),
                            user("second"), assistant("a2")])
    turns = extract(path, since_last_user=True)
    assert [t[1] for t in turns] == ["second", "a2"]


def test_since_last_user_ignores_an_unanswered_trailing_ask(tmp_path):
    """A user message with no assistant reply after it is not yet a turn."""
    path = write(tmp_path, [user("first"), assistant("a1"), user("second")])
    turns = extract(path, since_last_user=True)
    assert [t[1] for t in turns] == ["first", "a1"]


def test_digest_is_append_only_across_a_refiring_stop_hook(tmp_path):
    """speak.py's continuation feature depends on this; see extract.__doc__."""
    events = [user("q"), assistant("step one", tools=["Bash"])]
    early = render(extract(write(tmp_path, events, "a.jsonl"), since_last_user=True), 10_000)
    events.append(assistant("step two", tools=["Edit"]))
    late = render(extract(write(tmp_path, events, "b.jsonl"), since_last_user=True), 10_000)
    assert late.startswith(early)


def test_render_keeps_the_tail_within_budget(tmp_path):
    path = write(tmp_path, [user("q"), assistant("x" * 5000)])
    out = render(extract(path), 500)
    assert out.startswith("...\n\n")
    assert len(out) == 500 + len("...\n\n")   # budget applies to the tail
    assert out.endswith("x")


def test_malformed_lines_are_skipped(tmp_path):
    p = tmp_path / "bad.jsonl"
    p.write_text('not json\n' + json.dumps(user("hi")) + "\n", encoding="utf-8")
    assert [r for r, _, _ in extract(str(p))] == ["User"]
