import json

import pytest

from speakeasy import speak


@pytest.mark.parametrize("raw, expected", [
    ("An em dash — here", "An em dash, here"),
    ("Smart “quotes” and ‘apostrophes’", "Smart \"quotes\" and 'apostrophes'"),
    ("ellipsis…", "ellipsis..."),
    ("trailing space , then period .", "trailing space, then period."),
    ("double  spaces   collapse", "double spaces collapse"),
    ("non-ascii éè stripped", "non-ascii stripped"),
])
def test_sanitize(raw, expected):
    assert speak._sanitize(raw) == expected


def test_sanitize_output_is_ascii():
    assert speak._sanitize("café — naïve …").isascii()


def test_spoken_prefix_finds_the_longest_extended_digest():
    records = [
        {"digest": "A", "text": "said A"},
        {"digest": "AB", "text": "said AB"},
        {"digest": "XY", "text": "unrelated"},
        {"digest": "ABC", "text": ""},        # never spoken, must not match
    ]
    assert speak._spoken_prefix("ABCD", records) == "AB"


def test_spoken_prefix_ignores_an_identical_digest():
    assert speak._spoken_prefix("AB", [{"digest": "AB", "text": "said"}]) == ""


def test_spoken_prefix_returns_empty_when_nothing_matches():
    assert speak._spoken_prefix("ZZ", [{"digest": "AB", "text": "said"}]) == ""


def test_trim_turns_caps_records(tmp_path, monkeypatch):
    log = tmp_path / "turns.jsonl"
    monkeypatch.setattr(speak, "TURNS_LOG", log)
    monkeypatch.setattr(speak, "TURNS_CAP", 5)
    log.write_text("".join(json.dumps({"digest": str(i)}) + "\n" for i in range(50)))
    speak._trim_turns()
    lines = log.read_text().splitlines()
    assert len(lines) == 5
    assert json.loads(lines[-1])["digest"] == "49"


def test_trim_turns_caps_total_size(tmp_path, monkeypatch):
    log = tmp_path / "turns.jsonl"
    monkeypatch.setattr(speak, "TURNS_LOG", log)
    monkeypatch.setattr(speak, "TURNS_CAP", 50)
    monkeypatch.setattr(speak, "TURNS_MAX_CHARS", 2000)
    log.write_text("".join(json.dumps({"digest": "x" * 500}) + "\n" for _ in range(50)))
    speak._trim_turns()
    assert len(log.read_text()) <= 2000


def test_project_note_uses_the_configured_pronunciation(monkeypatch):
    monkeypatch.setattr(speak.config, "PRONUNCIATIONS", {"k8s": "kubernetes"})
    assert '"kubernetes"' in speak._project_note("k8s")
    assert "k8s" not in speak._project_note("k8s")


def test_project_note_is_empty_without_a_project():
    assert speak._project_note("") == ""


def test_prompt_reads_the_data_dir_copy(tmp_path, monkeypatch):
    monkeypatch.setattr(speak.config, "PROMPTS_DIR", tmp_path)
    (tmp_path / "speak.md").write_text("my own prompt")
    assert speak._prompt("speak.md") == "my own prompt"


def test_prompt_restores_a_deleted_copy(tmp_path, monkeypatch):
    """Deleting a prompt resets it: the file comes back from the package."""
    monkeypatch.setattr(speak.config, "PROMPTS_DIR", tmp_path)
    dest = tmp_path / "speak.md"
    assert not dest.exists()
    assert speak._prompt("speak.md").startswith("You narrate ONE Claude Code turn")
    assert dest.is_file()
    assert dest.read_text() == (speak.PROMPTS / "speak.md").read_text()


def test_prompt_creates_the_directory_if_it_is_gone(tmp_path, monkeypatch):
    monkeypatch.setattr(speak.config, "PROMPTS_DIR", tmp_path / "nested" / "prompts")
    assert speak._prompt("ask.md").startswith("You turn a pending question")
    assert (tmp_path / "nested" / "prompts" / "ask.md").is_file()


def test_prompt_leaves_no_temp_files_behind(tmp_path, monkeypatch):
    monkeypatch.setattr(speak.config, "PROMPTS_DIR", tmp_path)
    speak._prompt("speak.md")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["speak.md"]


def test_prompt_resolves_per_file(tmp_path, monkeypatch):
    """Editing one prompt must not disturb the other."""
    monkeypatch.setattr(speak.config, "PROMPTS_DIR", tmp_path)
    (tmp_path / "ask.md").write_text("my ask prompt")
    assert speak._prompt("ask.md") == "my ask prompt"
    assert speak._prompt("speak.md").startswith("You narrate ONE Claude Code turn")
    assert speak._prompt("ask.md") == "my ask prompt"
