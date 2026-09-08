"""Speakeasy's local HTTP listener: rewrite + Kokoro TTS + playback.

  POST /claude-turn  body = raw transcript (jsonl tail). Extracts the last
                 turn, rewrites it, and plays it. Called by the Claude Code
                 Stop hook.

  POST /codex-turn   body = JSON {"text" (Codex's own final assistant
                 message), "session", "project"}. Called by Codex's `notify`
                 hook (agent-turn-complete).

  POST /ask    body = JSON {"text" (the question), "session", "project"}.
                 Phrased into a spoken cue. Called by the AskUserQuestion
                 PreToolUse hook.

  POST /say    body = TEXT (text/plain or JSON {"text", "voice", "session"})
                 -> Kokoro -> play.

  POST /play   body = AUDIO (audio/wav) -> play as-is.

  POST /stop   stop whatever is playing.
  GET  /health -> {"ok": true}

No authentication: anything that can reach the port can make this machine
speak.
"""
import base64
import errno
import hashlib
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
import warnings
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

os.environ.setdefault("HF_HUB_VERBOSITY", "error")

import numpy as np
import soundfile as sf

from speakeasy import config

SR = 24000
BIND_RETRY_SECONDS = 15
HOST = config.BIND
PORT = config.PORT
DEFAULT_VOICE = config.DEFAULT_VOICE

VOICES = ["af_bella", "af_nicole", "af_sarah", "af_sky",
          "am_adam", "am_michael", "am_eric", "am_onyx"]


def voice_for(session):
    """Deterministic session -> voice mapping. Off when voice_rotation is."""
    if not session or not config.VOICE_ROTATION:
        return DEFAULT_VOICE
    h = int(hashlib.md5(session.encode(), usedforsecurity=False).hexdigest(), 16)
    return VOICES[h % len(VOICES)]


@contextmanager
def _quiet():
    """Silence the import- and inference-time chatter from mlx-audio, misaki
    and huggingface_hub."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        warnings.simplefilter("ignore", FutureWarning)
        yield


class Player:
    """Sequential playback via afplay: clips queue and play back-to-back.

    Every queued path is a temp file this module owns, and is deleted once it
    has played (or when the queue is flushed)."""

    def __init__(self):
        self._q = queue.Queue()
        self._lock = threading.Lock()
        self._proc = None
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        while True:
            path = self._q.get()
            try:
                proc = subprocess.Popen(["afplay", path],
                                        stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL)
                with self._lock:
                    self._proc = proc
                proc.wait()
            except Exception as e:
                print(f"[listener] playback failed: {e}", file=sys.stderr)
            finally:
                with self._lock:
                    self._proc = None
                _discard(path)

    def play_file(self, path):
        """Queue `path` to play after anything already playing/queued."""
        if _muted:
            _discard(path)
            return
        self._q.put(path)

    def stop(self):
        """Flush the queue and stop the current clip."""
        try:
            while True:
                _discard(self._q.get_nowait())
        except queue.Empty:
            pass
        with self._lock:
            if self._proc and self._proc.poll() is None:
                self._proc.terminate()
                try:
                    self._proc.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    self._proc.kill()
            self._proc = None


class Kokoro:
    """Kokoro TTS on the Apple-Silicon GPU via mlx-audio. 24 kHz output.

    One reentrant lock guards the lazy load and inference: the model is built
    once, and one synthesis runs at a time."""

    def __init__(self):
        self._model = None
        self._lock = threading.RLock()

    def _m(self):
        with self._lock:
            if self._model is None:
                with _quiet():
                    from mlx_audio.tts.utils import load_model
                    self._model = load_model(config.TTS_MODEL)
            return self._model

    def warm(self):
        self.synth("Ready.", DEFAULT_VOICE)

    def synth(self, text, voice=DEFAULT_VOICE):
        with self._lock, _quiet():
            chunks = [np.asarray(r.audio, dtype=np.float32)
                      for r in self._m().generate(text=text, voice=voice,
                                                  speed=1.0, lang_code="a")]
        return np.concatenate(chunks) if chunks else np.zeros(1, np.float32)


player = Player()
kokoro = Kokoro()

_muted = False
_last = {"text": "", "voice": DEFAULT_VOICE}


def set_muted(value):
    global _muted
    _muted = bool(value)


def say_last():
    """Re-synthesize and play the last spoken line."""
    text = _last["text"]
    if not text or _muted:
        return
    player.play_file(_tmp_wav_from_audio(kokoro.synth(text, _last["voice"])))


def _discard(path):
    """Delete a temp file we created, ignoring an already-gone file."""
    try:
        os.unlink(path)
    except OSError:
        pass


def _tmp_wav_from_audio(audio):
    fd, path = tempfile.mkstemp(suffix=".wav", prefix="speakeasy_")
    os.close(fd)
    sf.write(path, audio, SR)
    return path


def _tmp_wav_from_bytes(raw):
    fd, path = tempfile.mkstemp(suffix=".wav", prefix="speakeasy_recv_")
    with os.fdopen(fd, "wb") as f:
        f.write(raw)
    return path


_child_log = None
_child_log_lock = threading.Lock()


def _log_handle():
    """Shared append handle for detached speak.py children, opened once."""
    global _child_log
    with _child_log_lock:
        if _child_log is None:
            try:
                config.DATA_DIR.mkdir(parents=True, exist_ok=True)
                _child_log = open(config.DATA_DIR / "speakeasy.log", "a")
            except OSError:
                _child_log = open(os.devnull, "a")
        return _child_log


def _spawn_speak(payload, mode=None, session="", project="", last_message=""):
    """Write `payload` to a temp file and run speak.py against it in a
    detached subprocess. `mode` is speak.py's input flag, or None for a raw
    Claude transcript. The child deletes the temp file when it is done."""
    suffix = ".jsonl" if mode is None else ".txt"
    fd, tmp = tempfile.mkstemp(suffix=suffix, prefix="speakeasy_turn_")
    with os.fdopen(fd, "wb") as f:
        f.write(payload if isinstance(payload, bytes) else payload.encode())

    cmd = [sys.executable, "-m", "speakeasy.speak", tmp, "--delete-input"]
    if mode:
        cmd.append(mode)
    if session:
        cmd += ["--session", session]
    if project:
        cmd += ["--project", project]

    env = os.environ.copy()
    env["PYTHONSAFEPATH"] = "1"
    if last_message:
        env["SPEAKEASY_LAST_MESSAGE"] = last_message

    log = _log_handle()
    subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                     start_new_session=True, env=env)


class Handler(BaseHTTPRequestHandler):
    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        sys.stderr.write("[listener] " + (fmt % args) + "\n")

    def do_GET(self):
        if self.path == "/health":
            self._json(200, {"ok": True})
        else:
            self._json(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b""
        if _muted and self.path in ("/claude-turn", "/codex-turn", "/ask", "/say", "/play"):
            self._json(202, {"ok": True, "muted": True,
                             "action": self.path.lstrip("/")})
            return
        try:
            if self.path == "/stop":
                player.stop()
                self._json(200, {"ok": True, "action": "stop"})
            elif self.path == "/claude-turn":
                _spawn_speak(raw,
                             session=self.headers.get("X-Speakeasy-Session", ""),
                             project=self.headers.get("X-Speakeasy-Project", ""),
                             last_message=self._last_message())
                self._json(202, {"ok": True, "action": "claude-turn", "bytes": len(raw)})
            elif self.path in ("/codex-turn", "/ask"):
                action = self.path.lstrip("/")
                mode = "--codex" if action == "codex-turn" else "--ask"
                data = json.loads(raw or b"{}")
                _spawn_speak(data.get("text", ""), mode,
                             session=data.get("session", ""),
                             project=data.get("project", ""))
                self._json(202, {"ok": True, "action": action})
            elif self.path == "/play":
                player.play_file(_tmp_wav_from_bytes(raw))
                self._json(200, {"ok": True, "action": "play", "bytes": len(raw)})
            elif self.path == "/say":
                text, voice = self._parse_say(raw)
                _last["text"], _last["voice"] = text, voice
                player.play_file(_tmp_wav_from_audio(kokoro.synth(text, voice)))
                self._json(200, {"ok": True, "action": "say", "voice": voice,
                                 "chars": len(text)})
            else:
                self._json(404, {"ok": False, "error": "not found"})
        except Exception as e:
            self._json(500, {"ok": False, "error": str(e)})

    def _last_message(self):
        """The Stop hook's last_assistant_message, base64 in a header."""
        enc = self.headers.get("X-Speakeasy-Last", "")
        if not enc:
            return ""
        try:
            return base64.b64decode(enc).decode("utf-8", "replace")
        except Exception:
            return ""

    def _parse_say(self, raw):
        """/say body -> (text, voice). Accepts JSON {text, voice?, session?}
        or plain text."""
        text, voice, session = "", None, ""
        if "application/json" in self.headers.get("Content-Type", ""):
            data = json.loads(raw or b"{}")
            text = data.get("text", "")
            voice = data.get("voice")
            session = data.get("session", "")
        else:
            text = raw.decode("utf-8", "replace")
        session = session or self.headers.get("X-Speakeasy-Session", "")
        return text, (voice or voice_for(session))


def serve():
    """Build the HTTP server and serve forever. Raises OSError if the
    configured bind address cannot be used."""
    deadline = time.monotonic() + BIND_RETRY_SECONDS
    while True:
        try:
            srv = ThreadingHTTPServer((HOST, PORT), Handler)
            break
        except OSError as e:
            if e.errno == errno.EADDRINUSE and time.monotonic() < deadline:
                time.sleep(0.5)      # a previous instance is still shutting down
                continue
            raise OSError(f"cannot bind {HOST}:{PORT} ({e}); "
                          f"check \"bind\" in {config.CONFIG_PATH}") from e
    print(f"[listener] ready on {HOST}:{PORT}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        player.stop()
        srv.shutdown()


def main():
    print("[listener] warming Kokoro...", flush=True)
    kokoro.warm()
    serve()


if __name__ == "__main__":
    main()
