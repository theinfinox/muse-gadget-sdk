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

"""``musegadget`` command line."""

from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
import time
from typing import Callable

from musegadget import __version__, config, identity, muse_api, network
from musegadget.ble_setup import Credentials, ProvisionFailed, SetupController
from musegadget.pairing import PairingSession

log = logging.getLogger("musegadget")

DEFAULT_SETUP_WINDOW_S = 600
BLE_SHUTDOWN_DELAY_S = 1.5


class _SystemNetwork:
    is_online = staticmethod(network.is_online)
    current_connection_entry = staticmethod(network.current_connection_entry)


def _verify_and_save(
    credentials: Credentials, commit: Callable[[Callable[[], bool]], bool],
) -> None:
    api_url = credentials.api_url if credentials.api_url.startswith("https://") else ""
    api_url_v2 = credentials.api_url_v2 if credentials.api_url_v2.startswith("https://") else ""
    vms, status = muse_api.fetch_vms_with_status(
        credentials.access_token, muse_api.api_root(api_url_v2),
    )
    if not vms:
        log.warning("device token check failed (HTTP %s, %d VMs)", status, len(vms))
        raise ProvisionFailed("auth_failed")

    record = {
        "access_token": credentials.access_token,
        "refresh_token": credentials.refresh_token,
        "token_type": "device",
        "username": credentials.username,
        "api_url": api_url,
        "api_url_v2": api_url_v2,
        "noise_host": credentials.noise_host,
        "access_token_saved_at": int(time.time()),
    }

    def save() -> bool:
        config.save_json(config.PAIRING_FILE, record)
        return True

    if not commit(save):
        raise ProvisionFailed("error_storage")


def cmd_pair(args: argparse.Namespace) -> int:
    from musegadget.ble_server import BleServer

    if config.load_json(config.PAIRING_FILE) and not args.force:
        print("Already paired. Run `musegadget unpair` first, or pass --force.", file=sys.stderr)
        return 1

    try:
        sdk_token = config.sdk_token()
    except ValueError as exc:
        print(f"Can't pair: {exc}.", file=sys.stderr)
        return 1
    if not sdk_token:
        print("No SDK token yet. Get one at gadgets.muse.ai and run "
              "`bash install.sh --sdk-token mgst_…`; gadgets without one will stop pairing.",
              file=sys.stderr)
    ident = identity.load_or_create()
    pairing = PairingSession(
        node_id=ident.node_id,
        device_id=ident.device_id,
        mac=ident.mac,
        firmware_version=__version__,
        sdk_token=sdk_token,
    )
    completed = threading.Event()
    controller: SetupController | None = None

    server = BleServer(
        ident.ble_name,
        on_write=lambda packet: controller.on_write(packet),
        on_disconnect=lambda: controller.on_disconnect(),
    )

    def finish() -> None:
        completed.set()
        threading.Timer(BLE_SHUTDOWN_DELAY_S, server.stop).start()

    controller = SetupController(
        pairing=pairing,
        identity=ident,
        version=__version__,
        transport=server,
        network=_SystemNetwork(),
        provision=_verify_and_save,
        on_complete=finish,
    )
    window = threading.Timer(args.timeout, server.stop)
    window.daemon = True

    print(f"Setup open for {args.timeout // 60} minutes. In the Muse app, add a device")
    print(f"and choose {ident.ble_name}.")
    controller.start()
    window.start()
    try:
        server.run()
    except KeyboardInterrupt:
        pass
    finally:
        window.cancel()
        controller.stop()

    if completed.is_set():
        print("Paired.")
        return 0
    print("Setup window closed without pairing.", file=sys.stderr)
    return 1


def cmd_run(args: argparse.Namespace) -> int:
    from musegadget.executor import Account, Executor
    from musegadget.service import run_service
    from musegadget.tts import TTSConfig, TTSManager

    if os.geteuid() == 0:
        if not args.run_as:
            print("Pass --run-as ACCOUNT (the account whose permissions commands get).",
                  file=sys.stderr)
            return 1
        try:
            account = Account.lookup(args.run_as)
        except KeyError:
            print(f"Account {args.run_as!r} does not exist. Create it, or pass --run-as.",
                  file=sys.stderr)
            return 1
    else:
        account = Account.current()
    try:
        sdk_token = config.sdk_token()
    except ValueError as exc:
        log.warning("running without an SDK token: %s", exc)
        sdk_token = None

    tts_cfg = TTSConfig.load()
    if args.tts is not None:
        tts_cfg.enabled = args.tts
    if getattr(args, "tts_provider", None):
        tts_cfg.provider = args.tts_provider
    tts_manager = TTSManager(config=tts_cfg)

    log.info("musegadget %s: commands run as %s", __version__, account.name)
    if tts_manager.enabled:
        log.info("spoken replies (TTS) enabled with provider %r", tts_manager.provider.name)
    run_service(identity.load_or_create(), Executor(account), sdk_token, tts=tts_manager)
    return 0


def cmd_send_user_msg(args: argparse.Namespace) -> int:
    import json
    import socket

    message = sys.stdin.read() if args.message == ["-"] else " ".join(args.message)
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(90)
            sock.connect(str(config.socket_path()))
            request = {"message": message}
            if args.session_id:
                request["session_id"] = args.session_id
            sock.sendall(json.dumps(request).encode() + b"\n")
            reply = json.loads(sock.makefile("rb").readline())
    except (OSError, ValueError) as exc:
        print(f"Could not reach the musegadget service: {exc}", file=sys.stderr)
        return 1
    if not reply.get("ok"):
        print(f"Not delivered: {reply.get('error') or reply}", file=sys.stderr)
        return 1
    print("Sent to your Muse.")
    return 0


def cmd_say(args: argparse.Namespace) -> int:
    from musegadget.tts import (
        AudioOutputError,
        TTSError,
        TTSConfig,
        TTSManager,
        create_audio_output,
        create_tts_provider,
    )

    message = sys.stdin.read() if args.message == ["-"] else " ".join(args.message)
    if not message.strip():
        print("No text to speak.", file=sys.stderr)
        return 1

    cfg = TTSConfig.load()
    if getattr(args, "provider", None):
        cfg.provider = args.provider
    if getattr(args, "voice", None):
        cfg.voice = args.voice
    if getattr(args, "device", None):
        cfg.audio_device = args.device

    provider = create_tts_provider(cfg)
    output = create_audio_output(cfg)

    if not provider.is_available():
        print(f"TTS provider {provider.name!r} is not installed or available.", file=sys.stderr)
        print("Install it with: sudo apt install espeak-ng", file=sys.stderr)
        return 1

    if not output.is_available():
        print(f"Audio output {output.name!r} is not available.", file=sys.stderr)
        print("Install alsa-utils: sudo apt install alsa-utils", file=sys.stderr)
        return 1

    manager = TTSManager(config=cfg, provider=provider, output=output)
    try:
        manager.speak_sync(message)
    except (TTSError, AudioOutputError) as exc:
        print(f"Failed to speak: {exc}", file=sys.stderr)
        return 1
    return 0


def cmd_info(args: argparse.Namespace) -> int:
    from musegadget.tts import TTSConfig, create_audio_output, create_tts_provider

    ident = identity.load_or_create()
    paired = config.load_json(config.PAIRING_FILE) is not None
    tts_cfg = TTSConfig.load()
    provider = create_tts_provider(tts_cfg)
    output = create_audio_output(tts_cfg)

    print(f"version:   {__version__}")
    print(f"node id:   {ident.node_id}")
    print(f"BLE name:  {ident.ble_name}")
    print(f"paired:    {'yes' if paired else 'no'}")
    prov_status = "available" if provider.is_available() else "not installed"
    audio_status = "available" if output.is_available() else "not available"
    print(f"TTS:       {'enabled' if tts_cfg.enabled else 'disabled'}")
    print(f"provider:  {provider.name} ({prov_status})")
    print(f"audio:     {output.name} ({audio_status})")
    return 0


def cmd_unpair(args: argparse.Namespace) -> int:
    config.delete_json(config.PAIRING_FILE)
    print("Pairing removed. The device identity is kept.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="musegadget")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    pair = sub.add_parser("pair", help="open Bluetooth setup so the Muse app can pair")
    pair.add_argument("--timeout", type=int, default=DEFAULT_SETUP_WINDOW_S,
                      help="seconds to keep setup open (default: %(default)s)")
    pair.add_argument("--force", action="store_true", help="pair even if already paired")
    pair.set_defaults(func=cmd_pair)

    run = sub.add_parser("run", help="stay connected to the Muse and serve its commands")
    run.add_argument(
        "--run-as",
        default=os.environ.get("MUSEGADGET_RUN_AS") or os.environ.get("SUDO_USER"),
        help="account whose permissions commands run with (default: the account that ran sudo)",
    )
    run.add_argument("--tts", dest="tts", action="store_true", default=None,
                     help="enable spoken voice replies (TTS)")
    run.add_argument("--no-tts", dest="tts", action="store_false",
                     help="disable spoken voice replies")
    run.add_argument("--tts-provider", help="TTS provider to use (default: espeak)")
    run.set_defaults(func=cmd_run)

    say = sub.add_parser("say", help="speak text through the configured audio output")
    say.add_argument("message", nargs="+", help="the text to speak, or - to read from stdin")
    say.add_argument("--provider", help="TTS provider (default: espeak)")
    say.add_argument("--voice", help="voice name (e.g. en, en-us)")
    say.add_argument("--device", help="audio output device (e.g. default, hw:0,0)")
    say.set_defaults(func=cmd_say)

    send = sub.add_parser("send-user-msg", help="send a message to your Muse from this device")
    send.add_argument("message", nargs="+", help="the message, or - to read it from stdin")
    send.add_argument(
        "--session-id",
        help="send to this side chat (a new id starts one) instead of the main chat",
    )
    send.set_defaults(func=cmd_send_user_msg)

    sub.add_parser("info", help="show device identity").set_defaults(func=cmd_info)
    sub.add_parser("unpair", help="forget the saved pairing").set_defaults(func=cmd_unpair)

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
