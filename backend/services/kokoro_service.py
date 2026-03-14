"""
Custom manim-voiceover SpeechService backed by the local Kokoro TTS server.

The kokoro_server.mjs Node.js process must be running on port 8001 before
Manim renders. backend/main.py starts it automatically on FastAPI startup.
"""
from __future__ import annotations

import hashlib
import logging
import os
import shutil
import subprocess
import urllib.error
import urllib.request
import json as _json

from manim_voiceover.services.base import SpeechService

logger = logging.getLogger(__name__)

KOKORO_URL = os.environ.get("KOKORO_URL", "http://127.0.0.1:8001")

# sox lives in Homebrew on macOS; fall back to PATH lookup
_SOX = shutil.which("sox") or "/opt/homebrew/bin/sox"


class KokoroService(SpeechService):
    """Sends TTS requests to the local Kokoro Node.js server."""

    def __init__(self, voice: str = "af_heart", **kwargs):
        self.voice = voice
        super().__init__(**kwargs)

    def generate_from_text(
        self,
        text: str,
        cache_dir: str | None = None,
        path: str | None = None,
        **kwargs,
    ) -> dict:
        if cache_dir is None:
            cache_dir = self.cache_dir or "/tmp/kokoro_cache"
        os.makedirs(str(cache_dir), exist_ok=True)

        slug = hashlib.md5(text.encode()).hexdigest()[:16]
        wav_path = os.path.join(str(cache_dir), f"{slug}.wav")
        mp3_path = os.path.join(str(cache_dir), f"{slug}.mp3")
        mp3_rel  = f"{slug}.mp3"  # relative to cache_dir (what manim-voiceover expects)

        if not os.path.exists(mp3_path):
            # 1. Generate WAV via Kokoro Node.js server
            payload = _json.dumps({"text": text, "output_path": wav_path}).encode()
            req = urllib.request.Request(
                f"{KOKORO_URL}/tts",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    result = _json.loads(resp.read())
            except urllib.error.URLError as exc:
                raise RuntimeError(
                    f"Kokoro TTS server unreachable at {KOKORO_URL}. "
                    "Make sure kokoro_server.mjs is running."
                ) from exc

            if "error" in result:
                raise RuntimeError(f"Kokoro TTS error: {result['error']}")

            # 2. Convert WAV → MP3 using sox (mutagen-voiceover requires MP3)
            subprocess.run(
                [_SOX, wav_path, mp3_path],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            os.remove(wav_path)

        # Return relative path — manim-voiceover joins it with cache_dir internally
        return {"original_audio": mp3_rel}
