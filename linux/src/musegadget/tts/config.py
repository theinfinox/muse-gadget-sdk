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

"""Configuration and factory helpers for TTS and audio playback."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional

from musegadget.tts.base import AudioOutput, TTSProvider
from musegadget.tts.playback import AlsaAudioOutput, DummyAudioOutput
from musegadget.tts.providers import DummyTTSProvider, EspeakTTSProvider

log = logging.getLogger(__name__)

ENV_TTS_ENABLED = "MUSEGADGET_TTS_ENABLED"
ENV_TTS_PROVIDER = "MUSEGADGET_TTS_PROVIDER"
ENV_TTS_VOICE = "MUSEGADGET_TTS_VOICE"
ENV_TTS_RATE = "MUSEGADGET_TTS_RATE"
ENV_AUDIO_DEVICE = "MUSEGADGET_AUDIO_DEVICE"


def _parse_bool(val: Optional[str]) -> Optional[bool]:
    if val is None:
        return None
    val = val.strip().lower()
    if val in ("1", "true", "yes", "on"):
        return True
    if val in ("0", "false", "no", "off"):
        return False
    return None


@dataclass
class TTSConfig:
    """Settings for text-to-speech synthesis and audio output."""

    enabled: bool = False
    provider: str = "espeak"  # "espeak", "dummy"
    voice: Optional[str] = None
    rate: Optional[int] = None
    audio_device: Optional[str] = None

    @classmethod
    def load(cls) -> "TTSConfig":
        """Load configuration from environment variables."""
        cfg = cls()

        env_enabled = _parse_bool(os.environ.get(ENV_TTS_ENABLED))
        if env_enabled is not None:
            cfg.enabled = env_enabled

        env_provider = os.environ.get(ENV_TTS_PROVIDER)
        if env_provider:
            cfg.provider = env_provider.strip().lower()

        env_voice = os.environ.get(ENV_TTS_VOICE)
        if env_voice:
            cfg.voice = env_voice.strip()

        env_rate = os.environ.get(ENV_TTS_RATE)
        if env_rate:
            try:
                cfg.rate = int(env_rate.strip())
            except ValueError:
                log.warning("invalid %s value: %r", ENV_TTS_RATE, env_rate)

        env_audio_dev = os.environ.get(ENV_AUDIO_DEVICE)
        if env_audio_dev:
            cfg.audio_device = env_audio_dev.strip()

        return cfg


def create_tts_provider(cfg: TTSConfig) -> TTSProvider:
    """Instantiate a TTSProvider based on configuration."""
    provider_name = (cfg.provider or "espeak").lower()

    if provider_name == "dummy":
        return DummyTTSProvider()

    return EspeakTTSProvider(voice=cfg.voice, speed=cfg.rate)


def create_audio_output(cfg: TTSConfig) -> AudioOutput:
    """Instantiate an AudioOutput based on configuration."""
    if cfg.provider == "dummy":
        return DummyAudioOutput()
    return AlsaAudioOutput(device=cfg.audio_device)
