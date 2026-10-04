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

"""Audio output implementations for Linux and Raspberry Pi."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from typing import Optional

from musegadget.tts.base import AudioData, AudioOutput, AudioOutputError

log = logging.getLogger(__name__)


class AlsaAudioOutput(AudioOutput):
    """Audio output using aplay (ALSA).

    aplay is part of alsa-utils and is pre-installed on virtually all Linux
    and Raspberry Pi OS distributions. It natively plays standard WAV streams
    over stdin and routes through ALSA, PipeWire-ALSA, or PulseAudio-ALSA.
    """

    def __init__(
        self,
        executable: Optional[str] = None,
        device: Optional[str] = None,
    ) -> None:
        self._executable = executable or self._find_executable()
        self._device = device

    @property
    def name(self) -> str:
        return "alsa"

    @staticmethod
    def _find_executable() -> Optional[str]:
        return shutil.which("aplay") or shutil.which("paplay") or shutil.which("pw-play")

    def is_available(self) -> bool:
        exe = self._executable or self._find_executable()
        return exe is not None and os.access(exe, os.X_OK)

    def play(self, audio: AudioData) -> None:
        if audio.is_empty:
            return

        exe = self._executable or self._find_executable()
        if not exe:
            raise AudioOutputError("no audio player found (aplay, paplay, pw-play not in PATH)")

        cmd = [exe]
        exe_basename = os.path.basename(exe)
        if "aplay" in exe_basename:
            cmd.append("-q")
            if self._device:
                cmd.extend(["-D", self._device])
        elif "paplay" in exe_basename and self._device:
            cmd.extend(["-d", self._device])
        elif "pw-play" in exe_basename and self._device:
            cmd.extend(["--target", self._device])

        try:
            res = subprocess.run(
                cmd,
                input=audio.data,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=60,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise AudioOutputError(f"audio playback process failed: {exc}") from exc

        if res.returncode != 0:
            err = res.stderr.decode("utf-8", errors="replace").strip()
            raise AudioOutputError(f"{exe_basename} exited with code {res.returncode}: {err}")


class DummyAudioOutput(AudioOutput):
    """In-memory mock audio sink for testing without physical sound hardware."""

    def __init__(self, name: str = "dummy", available: bool = True, fail: bool = False) -> None:
        self._name = name
        self._available = available
        self._fail = fail
        self.played: list[AudioData] = []

    @property
    def name(self) -> str:
        return self._name

    def is_available(self) -> bool:
        return self._available

    def play(self, audio: AudioData) -> None:
        if self._fail:
            raise AudioOutputError("simulated audio playback failure")
        if not audio.is_empty:
            self.played.append(audio)
