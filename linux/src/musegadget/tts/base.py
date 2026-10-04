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

"""Base interfaces and data structures for Text-to-Speech and audio playback."""

from __future__ import annotations

import abc
from dataclasses import dataclass


class TTSError(Exception):
    """Base exception for TTS synthesis failures."""


class AudioOutputError(Exception):
    """Base exception for audio playback failures."""


@dataclass(frozen=True)
class AudioData:
    """Raw audio data produced by a TTS engine."""

    data: bytes
    format: str = "wav"  # e.g. "wav", "pcm"
    sample_rate: int = 22050
    channels: int = 1

    def __len__(self) -> int:
        return len(self.data)

    @property
    def is_empty(self) -> bool:
        return len(self.data) == 0


class TTSProvider(abc.ABC):
    """Abstract interface for speech synthesis engines."""

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Identifier for this provider (e.g. 'espeak', 'piper')."""

    @abc.abstractmethod
    def is_available(self) -> bool:
        """Return True if the underlying engine and binaries are usable."""

    @abc.abstractmethod
    def synthesize(self, text: str) -> AudioData:
        """Synthesize text into raw audio data.

        Raises:
            TTSError: If synthesis fails.
        """


class AudioOutput(abc.ABC):
    """Abstract interface for audio playback sinks."""

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Identifier for this audio output (e.g. 'alsa', 'pulse')."""

    @abc.abstractmethod
    def is_available(self) -> bool:
        """Return True if the playback subsystem/utility is usable."""

    @abc.abstractmethod
    def play(self, audio: AudioData) -> None:
        """Play audio data through the speaker.

        Raises:
            AudioOutputError: If playback fails.
        """
