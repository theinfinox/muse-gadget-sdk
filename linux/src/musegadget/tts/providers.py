# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Concrete TTS engine implementations."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from typing import Optional

from musegadget.tts.base import AudioData, TTSError, TTSProvider

log = logging.getLogger(__name__)

# Max text length to synthesize in one go (safety threshold for memory/CPU)
MAX_SYNTHESIS_TEXT_CHARS = 4096


class EspeakTTSProvider(TTSProvider):
    """Local, offline TTS using espeak-ng or espeak.

    Produces standard WAV audio over stdout with minimal CPU and memory footprint.
    """

    def __init__(
        self,
        executable: Optional[str] = None,
        voice: Optional[str] = None,
        speed: Optional[int] = None,
    ) -> None:
        self._executable = executable or self._find_executable()
        self._voice = voice
        self._speed = speed

    @property
    def name(self) -> str:
        return "espeak"

    @staticmethod
    def _find_executable() -> Optional[str]:
        return shutil.which("espeak-ng") or shutil.which("espeak")

    def is_available(self) -> bool:
        exe = self._executable or self._find_executable()
        return exe is not None and os.access(exe, os.X_OK)

    def synthesize(self, text: str) -> AudioData:
        exe = self._executable or self._find_executable()
        if not exe:
            raise TTSError("espeak/espeak-ng binary not found in PATH")

        trimmed = text.strip()
        if not trimmed:
            return AudioData(data=b"", format="wav")

        if len(trimmed) > MAX_SYNTHESIS_TEXT_CHARS:
            log.warning(
                "truncating long text for TTS (%d chars -> %d)",
                len(trimmed),
                MAX_SYNTHESIS_TEXT_CHARS,
            )
            trimmed = trimmed[:MAX_SYNTHESIS_TEXT_CHARS]

        cmd = [exe, "--stdout"]
        if self._voice:
            cmd.extend(["-v", str(self._voice)])
        if self._speed is not None:
            cmd.extend(["-s", str(self._speed)])
        cmd.append(trimmed)

        try:
            res = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise TTSError(f"espeak synthesis process failed: {exc}") from exc

        if res.returncode != 0:
            err = res.stderr.decode("utf-8", errors="replace").strip()
            raise TTSError(f"espeak exited with code {res.returncode}: {err}")

        return AudioData(data=res.stdout, format="wav")


class DummyTTSProvider(TTSProvider):
    """In-memory mock TTS provider for unit testing and headless validation."""

    def __init__(self, name: str = "dummy", available: bool = True, fail: bool = False) -> None:
        self._name = name
        self._available = available
        self._fail = fail
        self.synthesized: list[str] = []

    @property
    def name(self) -> str:
        return self._name

    def is_available(self) -> bool:
        return self._available

    def synthesize(self, text: str) -> AudioData:
        if self._fail:
            raise TTSError("simulated dummy synthesis failure")
        self.synthesized.append(text)
        # 44-byte minimal RIFF WAV header for dummy audio data
        fake_wav = (
            b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00"
            b"\x01\x00\x01\x00\x22\x56\x00\x00\x44\xac\x00\x00\x02\x00\x10\x00"
            b"data\x00\x00\x00\x00"
        )
        return AudioData(data=fake_wav, format="wav")
