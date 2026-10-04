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

"""Text-to-speech and audio output support for Linux Muse gadgets."""

from musegadget.tts.base import AudioData, AudioOutput, AudioOutputError, TTSError, TTSProvider
from musegadget.tts.config import TTSConfig, create_audio_output, create_tts_provider
from musegadget.tts.manager import TTSManager
from musegadget.tts.playback import AlsaAudioOutput, DummyAudioOutput
from musegadget.tts.providers import DummyTTSProvider, EspeakTTSProvider

__all__ = [
    "AudioData",
    "AudioOutput",
    "AudioOutputError",
    "TTSError",
    "TTSProvider",
    "TTSConfig",
    "TTSManager",
    "AlsaAudioOutput",
    "DummyAudioOutput",
    "DummyTTSProvider",
    "EspeakTTSProvider",
    "create_audio_output",
    "create_tts_provider",
]
