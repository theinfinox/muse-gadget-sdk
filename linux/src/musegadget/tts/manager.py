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

"""TTS Manager and background speech dispatcher."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from musegadget.tts.base import AudioOutput, AudioOutputError, TTSError, TTSProvider
from musegadget.tts.config import TTSConfig, create_audio_output, create_tts_provider

log = logging.getLogger(__name__)

# Bounded queue depth: avoid backlog of old responses if flooded
MAX_SPEECH_QUEUE = 4


class TTSManager:
    """Manages text-to-speech lifecycle, queuing, and non-blocking playback."""

    def __init__(
        self,
        config: Optional[TTSConfig] = None,
        provider: Optional[TTSProvider] = None,
        output: Optional[AudioOutput] = None,
    ) -> None:
        self.config = config or TTSConfig.load()
        self.provider = provider or create_tts_provider(self.config)
        self.output = output or create_audio_output(self.config)
        self._queue: Optional[asyncio.Queue[str]] = None
        self._worker_task: Optional[asyncio.Task] = None
        self._running = False

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    @property
    def is_available(self) -> bool:
        return self.provider.is_available() and self.output.is_available()

    async def start(self) -> None:
        """Start the background speech worker task."""
        if self._running:
            return
        self._running = True
        self._queue = asyncio.Queue(maxsize=MAX_SPEECH_QUEUE)
        self._worker_task = asyncio.create_task(self._worker())

    async def stop(self) -> None:
        """Stop the background worker task."""
        self._running = False
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None
        self._queue = None

    def speak(self, text: str) -> None:
        """Enqueue text for background synthesis and playback without blocking.

        Safe to call from the main event loop. If TTS is disabled or text is empty,
        this is a no-op.
        """
        if not self.enabled:
            return
        trimmed = text.strip()
        if not trimmed:
            return

        if not self._running or self._queue is None:
            # Not running in async loop: do nothing or log debug
            log.debug("TTSManager: speak() called but worker is not running")
            return

        if self._queue.full():
            # Drop oldest unplayed item to avoid queue backlog
            try:
                dropped = self._queue.get_nowait()
                self._queue.task_done()
                log.warning("speech queue full; dropped oldest response: %r", dropped[:40])
            except (asyncio.QueueEmpty, ValueError):
                pass

        try:
            self._queue.put_nowait(trimmed)
        except asyncio.QueueFull:
            log.warning("speech queue full; unable to enqueue speech")

    async def _worker(self) -> None:
        """Background worker that sequentially synthesizes and plays speech."""
        while self._running:
            try:
                assert self._queue is not None
                text = await self._queue.get()
            except asyncio.CancelledError:
                break

            try:
                await self._process_one(text)
            except Exception as exc:
                log.warning("TTS processing failed unexpectedly: %s", exc)
            finally:
                if self._queue is not None:
                    self._queue.task_done()

    async def _process_one(self, text: str) -> None:
        if not self.provider.is_available():
            log.warning("TTS provider %r is not available; skipping speech", self.provider.name)
            return

        # 1. Synthesize in thread pool to keep the event loop responsive
        try:
            audio = await asyncio.to_thread(self.provider.synthesize, text)
        except TTSError as exc:
            log.warning("TTS synthesis failed for provider %s: %s", self.provider.name, exc)
            return
        except Exception as exc:
            log.exception("unexpected TTS synthesis error: %s", exc)
            return

        if audio.is_empty:
            return

        # 2. Play audio in thread pool to keep the event loop responsive
        if not self.output.is_available():
            log.warning("audio output %r is not available; skipping playback", self.output.name)
            return

        try:
            await asyncio.to_thread(self.output.play, audio)
        except AudioOutputError as exc:
            log.warning("audio playback failed for %s: %s", self.output.name, exc)
        except Exception as exc:
            log.exception("unexpected audio playback error: %s", exc)

    def speak_sync(self, text: str) -> None:
        """Synchronously synthesize and play text (e.g. for CLI commands).

        Raises:
            TTSError: If synthesis fails.
            AudioOutputError: If playback fails.
        """
        trimmed = text.strip()
        if not trimmed:
            return

        if not self.provider.is_available():
            raise TTSError(f"TTS provider {self.provider.name!r} is not installed or available")
        if not self.output.is_available():
            raise AudioOutputError(f"audio output {self.output.name!r} is not available")

        audio = self.provider.synthesize(trimmed)
        self.output.play(audio)
