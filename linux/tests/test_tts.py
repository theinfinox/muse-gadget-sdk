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

from __future__ import annotations

import asyncio

import pytest

from musegadget.link_client import Outcome
from musegadget.tts import (
    AudioData,
    AudioOutputError,
    DummyAudioOutput,
    DummyTTSProvider,
    EspeakTTSProvider,
    TTSConfig,
    TTSError,
    TTSManager,
    create_audio_output,
    create_tts_provider,
)


def test_audio_data_basics():
    empty = AudioData(data=b"")
    assert empty.is_empty
    assert len(empty) == 0

    audio = AudioData(data=b"RIFF1234", format="wav", sample_rate=22050, channels=1)
    assert not audio.is_empty
    assert len(audio) == 8
    assert audio.format == "wav"


def test_tts_config_defaults_and_env(monkeypatch):
    monkeypatch.delenv("MUSEGADGET_TTS_ENABLED", raising=False)
    monkeypatch.delenv("MUSEGADGET_TTS_PROVIDER", raising=False)
    monkeypatch.delenv("MUSEGADGET_TTS_VOICE", raising=False)
    monkeypatch.delenv("MUSEGADGET_TTS_RATE", raising=False)
    monkeypatch.delenv("MUSEGADGET_AUDIO_DEVICE", raising=False)

    cfg = TTSConfig.load()
    assert cfg.enabled is False
    assert cfg.provider == "espeak"

    monkeypatch.setenv("MUSEGADGET_TTS_ENABLED", "1")
    monkeypatch.setenv("MUSEGADGET_TTS_PROVIDER", "dummy")
    monkeypatch.setenv("MUSEGADGET_TTS_VOICE", "en-us")
    monkeypatch.setenv("MUSEGADGET_TTS_RATE", "175")
    monkeypatch.setenv("MUSEGADGET_AUDIO_DEVICE", "hw:0,0")

    loaded = TTSConfig.load()
    assert loaded.enabled is True
    assert loaded.provider == "dummy"
    assert loaded.voice == "en-us"
    assert loaded.rate == 175
    assert loaded.audio_device == "hw:0,0"


def test_factory_creation():
    cfg = TTSConfig(provider="dummy")
    provider = create_tts_provider(cfg)
    output = create_audio_output(cfg)
    assert isinstance(provider, DummyTTSProvider)
    assert isinstance(output, DummyAudioOutput)

    cfg_espeak = TTSConfig(provider="espeak", voice="en-us", rate=150)
    espeak_provider = create_tts_provider(cfg_espeak)
    assert isinstance(espeak_provider, EspeakTTSProvider)


# --- 1. TTS disabled -> existing behavior remains unchanged ---
def test_tts_disabled_does_not_synthesize_or_play():
    provider = DummyTTSProvider()
    output = DummyAudioOutput()
    cfg = TTSConfig(enabled=False)
    manager = TTSManager(config=cfg, provider=provider, output=output)

    async def scenario():
        await manager.start()
        manager.speak("Hello, Muse!")
        await asyncio.sleep(0.05)
        await manager.stop()

    asyncio.run(scenario())
    assert provider.synthesized == []
    assert output.played == []


# --- 2. TTS enabled -> response is dispatched to provider and played ---
def test_tts_enabled_synthesizes_and_plays():
    provider = DummyTTSProvider()
    output = DummyAudioOutput()
    cfg = TTSConfig(enabled=True)
    manager = TTSManager(config=cfg, provider=provider, output=output)

    async def scenario():
        await manager.start()
        manager.speak("Hello, Muse!")
        for _ in range(10):
            if output.played:
                break
            await asyncio.sleep(0.02)
        await manager.stop()

    asyncio.run(scenario())
    assert provider.synthesized == ["Hello, Muse!"]
    assert len(output.played) == 1
    assert not output.played[0].is_empty


# --- 3. Empty response -> no TTS call ---
def test_empty_response_ignored():
    provider = DummyTTSProvider()
    output = DummyAudioOutput()
    cfg = TTSConfig(enabled=True)
    manager = TTSManager(config=cfg, provider=provider, output=output)

    async def scenario():
        await manager.start()
        manager.speak("")
        manager.speak("   ")
        manager.speak("\n\t  ")
        await asyncio.sleep(0.05)
        await manager.stop()

    asyncio.run(scenario())
    assert provider.synthesized == []
    assert output.played == []


# --- 4. TTS provider unavailable -> graceful failure ---
def test_tts_provider_unavailable_handled_gracefully():
    provider = DummyTTSProvider(available=False)
    output = DummyAudioOutput()
    cfg = TTSConfig(enabled=True)
    manager = TTSManager(config=cfg, provider=provider, output=output)

    async def scenario():
        await manager.start()
        manager.speak("This should be skipped cleanly")
        await asyncio.sleep(0.05)
        await manager.stop()

    asyncio.run(scenario())
    assert provider.synthesized == []
    assert output.played == []


# --- 5. TTS synthesis failure -> does not crash the gadget ---
def test_tts_synthesis_failure_does_not_crash():
    provider = DummyTTSProvider(fail=True)
    output = DummyAudioOutput()
    cfg = TTSConfig(enabled=True)
    manager = TTSManager(config=cfg, provider=provider, output=output)

    async def scenario():
        await manager.start()
        manager.speak("This synthesis will fail")
        await asyncio.sleep(0.05)
        manager.speak("Another message")
        await asyncio.sleep(0.05)
        await manager.stop()

    asyncio.run(scenario())
    assert output.played == []


# --- 6. Audio playback failure -> does not crash the gadget ---
def test_audio_playback_failure_does_not_crash():
    provider = DummyTTSProvider()
    output = DummyAudioOutput(fail=True)
    cfg = TTSConfig(enabled=True)
    manager = TTSManager(config=cfg, provider=provider, output=output)

    async def scenario():
        await manager.start()
        manager.speak("This playback will fail")
        await asyncio.sleep(0.05)
        await manager.stop()

    asyncio.run(scenario())
    assert provider.synthesized == ["This playback will fail"]


# --- 7. Long response handling ---
def test_long_response_handled_gracefully():
    provider = DummyTTSProvider()
    output = DummyAudioOutput()
    cfg = TTSConfig(enabled=True)
    manager = TTSManager(config=cfg, provider=provider, output=output)

    long_text = "The quick brown fox jumps over the lazy dog. " * 200

    async def scenario():
        await manager.start()
        manager.speak(long_text)
        for _ in range(10):
            if output.played:
                break
            await asyncio.sleep(0.02)
        await manager.stop()

    asyncio.run(scenario())
    assert len(provider.synthesized) == 1
    assert len(output.played) == 1


# --- 8. Concurrent responses -> sequential queueing ---
def test_concurrent_multiple_responses_queued_sequentially():
    provider = DummyTTSProvider()
    output = DummyAudioOutput()
    cfg = TTSConfig(enabled=True)
    manager = TTSManager(config=cfg, provider=provider, output=output)

    async def scenario():
        await manager.start()
        manager.speak("Message 1")
        manager.speak("Message 2")
        manager.speak("Message 3")

        for _ in range(25):
            if len(output.played) >= 3:
                break
            await asyncio.sleep(0.02)
        await manager.stop()

    asyncio.run(scenario())
    assert provider.synthesized == ["Message 1", "Message 2", "Message 3"]
    assert len(output.played) == 3


def test_speak_sync_success_and_errors():
    provider = DummyTTSProvider()
    output = DummyAudioOutput()
    cfg = TTSConfig(enabled=True)
    manager = TTSManager(config=cfg, provider=provider, output=output)

    manager.speak_sync("Direct speech")
    assert provider.synthesized == ["Direct speech"]
    assert len(output.played) == 1

    # Empty string is ignored
    manager.speak_sync("")
    assert len(output.played) == 1

    # Provider failure raises TTSError
    fail_provider = DummyTTSProvider(fail=True)
    bad_manager = TTSManager(config=cfg, provider=fail_provider, output=output)
    with pytest.raises(TTSError):
        bad_manager.speak_sync("fail text")

    # Output failure raises AudioOutputError
    fail_output = DummyAudioOutput(fail=True)
    bad_audio_manager = TTSManager(config=cfg, provider=provider, output=fail_output)
    with pytest.raises(AudioOutputError):
        bad_audio_manager.speak_sync("play fail")


def test_cli_info_displays_tts_status(capsys, monkeypatch):
    import argparse
    from musegadget.cli import cmd_info

    monkeypatch.setenv("MUSEGADGET_TTS_ENABLED", "0")
    args = argparse.Namespace()
    cmd_info(args)
    captured = capsys.readouterr()
    assert "TTS:       disabled" in captured.out
    assert "provider:  espeak" in captured.out

    monkeypatch.setenv("MUSEGADGET_TTS_ENABLED", "1")
    cmd_info(args)
    captured = capsys.readouterr()
    assert "TTS:       enabled" in captured.out


def test_cli_say_command(monkeypatch):
    import argparse
    from musegadget.cli import cmd_say

    monkeypatch.setenv("MUSEGADGET_TTS_PROVIDER", "dummy")
    args = argparse.Namespace(
        message=["Hello", "world"],
        provider="dummy",
        voice=None,
        device=None,
    )
    ret = cmd_say(args)
    assert ret == 0


def test_service_on_response_dispatches_to_tts():
    from musegadget.service import Service
    from musegadget.identity import Identity
    from musegadget.executor import Account, Executor

    provider = DummyTTSProvider()
    output = DummyAudioOutput()
    cfg = TTSConfig(enabled=True)
    manager = TTSManager(config=cfg, provider=provider, output=output)

    account = Account("user", 1000, 1000, "/home/user")
    service = Service(
        identity=Identity("02:00:00:00:00:01"),
        executor=Executor(account),
        tts=manager,
    )

    async def scenario():
        await manager.start()
        service._on_response("Spoken text from Muse")
        for _ in range(10):
            if output.played:
                break
            await asyncio.sleep(0.02)
        await manager.stop()

    asyncio.run(scenario())
    assert provider.synthesized == ["Spoken text from Muse"]
    assert len(output.played) == 1


def test_service_on_response_ignores_when_tts_disabled():
    from musegadget.service import Service
    from musegadget.identity import Identity
    from musegadget.executor import Account, Executor

    provider = DummyTTSProvider()
    output = DummyAudioOutput()
    cfg = TTSConfig(enabled=False)
    manager = TTSManager(config=cfg, provider=provider, output=output)

    account = Account("user", 1000, 1000, "/home/user")
    service = Service(
        identity=Identity("02:00:00:00:00:01"),
        executor=Executor(account),
        tts=manager,
    )

    async def scenario():
        await manager.start()
        service._on_response("This should not be spoken")
        await asyncio.sleep(0.05)
        await manager.stop()

    asyncio.run(scenario())
    assert provider.synthesized == []
    assert output.played == []


def test_service_session_on_response_wiring(monkeypatch):
    """Regression test: verifies on_response is None when TTS is disabled,

    ensuring /chat/subscribe is NEVER opened when TTS is disabled.
    """
    from musegadget.service import Service
    from musegadget.identity import Identity
    from musegadget.executor import Account, Executor

    created_sessions = []

    class DummyLinkSession:
        def __init__(self, *args, **kwargs):
            created_sessions.append(kwargs)
            self.registered_at = None

        async def run(self, stop):
            return Outcome.STOPPED

    monkeypatch.setattr("musegadget.service.LinkSession", DummyLinkSession)

    account = Account("user", 1000, 1000, "/home/user")

    # 1. TTS disabled -> on_response is None (Priority 1 fix)
    cfg_disabled = TTSConfig(enabled=False)
    service_disabled = Service(
        identity=Identity("02:00:00:00:00:01"),
        executor=Executor(account),
        tts=TTSManager(config=cfg_disabled),
    )
    asyncio.run(service_disabled._session(
        {"vm_id": "v1", "vm_name": "vm", "vm_auth_token": "tok"}, {},
    ))
    assert created_sessions[-1]["on_response"] is None

    # 2. TTS enabled -> on_response is set
    cfg_enabled = TTSConfig(enabled=True)
    service_enabled = Service(
        identity=Identity("02:00:00:00:00:01"),
        executor=Executor(account),
        tts=TTSManager(config=cfg_enabled),
    )
    asyncio.run(service_enabled._session(
        {"vm_id": "v1", "vm_name": "vm", "vm_auth_token": "tok"}, {},
    ))
    assert created_sessions[-1]["on_response"] == service_enabled._on_response
