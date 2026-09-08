# speakeasy

Hear what a Claude Code or Codex turn did instead of reading it.

- Speaks a one-line summary of each finished turn, so you can look away while it works.
- Announces blocking questions (Claude Code's `AskUserQuestion`) so you know to come back.
- Gives every concurrent session its own voice.
- Lives in the menu bar: left-click mutes, right-click for Speak last again / Open config / Quit.
- Speech is local. Kokoro on the Apple-Silicon GPU, nothing sent anywhere.

## Install

    brew trust --formula jimfleming/speakeasy/speakeasy
    brew tap jimfleming/speakeasy https://github.com/jimfleming/speakeasy
    brew install jimfleming/speakeasy/speakeasy
    speakeasy init                  # wires up Claude Code + Codex, seeds config
                                    # and prompts, and starts the menu-bar app

Recent Homebrew refuses to load formulae from third-party taps until you trust
them, and reports it as `invalid syntax in tap!`, so the `brew trust` line comes
first. Older Homebrew has no `brew trust` and does not need it.

`speakeasy init` backs up whatever it touches and never clobbers an existing
entry. Restart any running Claude Code or Codex session to pick up the hook.
To remove: `speakeasy uninstall`, then `brew uninstall speakeasy`.

If the waveform icon never appears, run `speakeasy doctor`. It checks the
config, the hooks and the listener, and starts the listener if it is down.
`brew services start` can report success while launchd never actually runs the
job, leaving no process and no logs to explain it, so doctor verifies the
listener really answers and falls back to `launchctl kickstart` when it does
not.

## Requirements

macOS 13.5+ on Apple Silicon, and either an OpenRouter key or a local
OpenAI-compatible endpoint. Kokoro (~330 MB) downloads on first use, so the
first line takes a while; the menu-bar icon shows an hourglass until it is ready.

## How it works

A hook ships the finished turn to a local listener, which does two things:

1. **Rewrite** — condenses the turn to a single line with an LLM over an
   OpenAI-compatible API. This defaults to OpenRouter, so **the turn digest
   leaves your machine**: your prompts, the assistant's prose, and the names of
   the tools it called. Raw tool output is stripped first and never sent. Point
   `rewrite.base_url` at Ollama or LM Studio to keep it all local.
2. **Speak** — Kokoro TTS through mlx-audio, on the GPU. Always local.

The last 50 turns are kept in the data dir, as the verbatim digests that were
sent, so a repeated or continued turn is not narrated twice.

## Configuration

Edit `~/Library/Application Support/Speakeasy/config.json`, or use the menu's
"Open config". Every key is optional; these are the defaults.

    {
      "rewrite": {
        "base_url": "https://openrouter.ai/api/v1",
        "model": "inception/mercury-2",
        "api_key": ""
      },
      "default_voice": "af_bella",
      "voice_rotation": true,
      "tts_model": "mlx-community/Kokoro-82M-bf16",
      "bind": "127.0.0.1",
      "port": 8765,
      "pronunciations": {}
    }

- **`rewrite`** — any OpenAI-compatible chat endpoint, and the only part of
  speakeasy that touches the network. `api_key` also reads from
  `OPENROUTER_API_KEY`.
- **`voice_rotation`** — per-session voices, so you can tell sessions apart by
  ear. Set `false` to use `default_voice` (any Kokoro voice) everywhere.
- **`pronunciations`** — maps a written name to how it should be said, e.g.
  `{"k8s": "kubernetes"}`. For names TTS would otherwise spell out.
- **`bind` / `port`** — **the listener has no authentication.** Anything that
  can reach the port can make this machine speak. Only move it off `127.0.0.1`
  on a network you trust.

Any key can be overridden for one run with a `SPEAKEASY_` environment variable
(`SPEAKEASY_MODEL`, `SPEAKEASY_PORT`, `SPEAKEASY_CONFIG`, and so on).

`speakeasy init` also drops the two prompts that shape the spoken line next to
`config.json`, as plain Markdown. They are the main thing worth tuning, and
they are read from there, so edits stick across upgrades. Delete one and it is
restored from the packaged copy on the next turn, which is how you reset it;
`speakeasy init --force` resets both at once.

## Development

    git clone https://github.com/jimfleming/speakeasy.git
    cd speakeasy
    brew install espeak-ng
    uv run speakeasy app        # menu-bar app; also: init / listener / speak
    uv run pytest

A clone behaves identically to the Homebrew install, prompts included: both
read them from the data dir. To work on the prompts this repo ships, point
`SPEAKEASY_PROMPTS_DIR` back at the clone so your edits are the ones used, and
`--no-play` to print the line instead of speaking it:

    SPEAKEASY_PROMPTS_DIR=speakeasy/prompts \
        uv run speakeasy speak ~/.claude/projects/<project>/<session>.jsonl --no-play

Without that variable you are editing the copy in the data dir, which is what
a user edits.
