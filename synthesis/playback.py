"""In-app WAV playback with terminal controls (spec §5).

Space = play/pause, J/L = seek -/+10 s, Enter = done listening.
``sinteractive=False`` and an injected ``stream_factory`` keep the class
testable without an audio device or a keyboard.
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from synthesis.audio_processor import read_wav

SEEK_SECONDS = 10.0


class PlaybackError(Exception):
    """No usable audio output device (the caller falls back to manual listening)."""


class Player:
    def __init__(self, path, stream_factory: Optional[Callable[[], object]] = None,
                 interactive: bool = True):
        data, sample_rate, _bits = read_wav(Path(path))
        if data.ndim == 1:                       # defensive: read_wav is 2-D already
            data = data.reshape(-1, 1)
        if data.shape[1] == 1:                   # mono -> stereo
            data = np.column_stack([data, data])
        self.data = np.ascontiguousarray(data, dtype=np.float32)
        self.samplerate = int(sample_rate)
        self.duration = len(self.data) / self.samplerate
        self.path = str(path)
        self.position = 0                        # frame index
        self.playing = False
        self._lock = threading.Lock()
        self._stream = None
        self._stream_factory = stream_factory or self._default_factory
        self._interactive = interactive

    # ------------------------------------------------------------- stream
    def _default_factory(self):
        try:
            import sounddevice as sd
            return sd.OutputStream(samplerate=self.samplerate, channels=2,
                                   dtype="float32", callback=self.callback)
        except Exception as e:
            raise PlaybackError(f"audio output unavailable: {e}") from e

    def _ensure_stream(self) -> None:
        if self._stream is None:
            stream = self._stream_factory()
            start = getattr(stream, "start", None)
            if callable(start):
                start()
            self._stream = stream

    def callback(self, outdata, frames, time_info=None, status=None) -> None:
        """Pull ``frames`` stereo frames at ``position``; silence when paused/EOF."""
        outdata[:] = 0.0
        with self._lock:
            if not self.playing:
                return
            end = min(self.position + frames, len(self.data))
            n = end - self.position
            if n <= 0:
                self.playing = False
                return
            outdata[:n] = self.data[self.position:end]
            self.position = end
            if self.position >= len(self.data):
                self.playing = False

    # ------------------------------------------------------------- controls
    def play(self) -> None:
        with self._lock:
            if self.position >= len(self.data):  # replay after EOF
                self.position = 0
            self.playing = True
        self._ensure_stream()

    def pause(self) -> None:
        with self._lock:
            self.playing = False

    def toggle(self) -> None:
        (self.pause if self.playing else self.play)()

    def seek(self, seconds: float) -> None:
        with self._lock:
            self.position = int(max(0, min(len(self.data),
                                           self.position + seconds * self.samplerate)))

    def rewind(self) -> None:
        with self._lock:
            self.position = 0

    def stop(self) -> None:
        with self._lock:
            self.playing = False
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass

    # ------------------------------------------------------------- keyboard
    def _read_key(self) -> str:
        if sys.platform == "win32":
            import msvcrt
            key = msvcrt.getch()
            if key in (b"\xe0", b"\x00"):        # swallow arrow-key second byte
                msvcrt.getch()
                return ""
            if key in (b"\r", b"\n"):
                return "\r"
            if key == b" ":
                return " "
            if key in (b"j", b"J"):
                return "j"
            if key in (b"l", b"L"):
                return "l"
            return ""
        import sys as _sys
        import termios
        import tty
        fd = _sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            key = _sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
        if key in ("\r", "\n"):
            return "\r"
        if key == " ":
            return " "
        if key in ("j", "J"):
            return "j"
        if key in ("l", "L"):
            return "l"
        return ""

    def listen(self) -> None:
        """Block until Enter; Space/J/L control playback meanwhile.

        Non-interactive mode returns immediately (tests, headless use).
        Ctrl+C raises KeyboardInterrupt, handled by the caller.
        """
        if not self._interactive:
            return
        self._ensure_stream()
        while True:
            key = self._read_key()
            if key == "\r":
                return
            if key == " ":
                self.toggle()
            elif key == "j":
                self.seek(-SEEK_SECONDS)
            elif key == "l":
                self.seek(SEEK_SECONDS)
