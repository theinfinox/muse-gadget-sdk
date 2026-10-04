<!--
Copyright (c) Meta Platforms, Inc. and affiliates.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
-->

# Linux Device SDK

This turns any Linux computer, like a Raspberry Pi, into a Muse gadget.
Install it, pair it with the Muse app, and Muse can run commands and move
files on the machine.

Then make it your own: wire up a sensor, bridge a webhook, or give Muse a new
command.

> **Note:** Built by hackers, for hackers, just for fun. Proceed at your own
> risk! Muse gets the same access to the machine as the account you install it
> for.

## What you need

- **A Raspberry Pi with Bluetooth**: a 3B+, 4, 5 or Zero 2 W. Other Linux
  computers work too, as long as they have Bluetooth LE.
- **Raspberry Pi OS Bullseye or later**, Debian 11 or later, or Ubuntu 22.04
  or later, already on your network. 32-bit and 64-bit both work.
- **An account with sudo** on the machine.
- **An SDK token** from [gadgets.muse.ai](https://gadgets.muse.ai/settings/sdk-tokens)
  (Account > SDK tokens). Every gadget needs one to pair, including ones you
  build for yourself. Read the [Gadget SDK Terms](https://gadgets.muse.ai/sdk-terms)
  before you use it.
- **The Muse app** on your phone, to pair the device.

## Install

On the machine, as the account Muse should use:

```sh
curl -fsSL https://raw.githubusercontent.com/facebookincubator/muse-gadget-sdk/main/linux/install.sh -o install.sh
less install.sh     # read it first
bash install.sh --sdk-token mgst_…
```

The installer checks your system, installs what it needs into
`/opt/musegadget`, and starts the `musegadget` service. Before it gives Muse
your account, it asks, and tells you if that account can use sudo. Then it
opens Bluetooth pairing.

## Set it up with Muse

When the installer says pairing is open, go to the Muse app:

1. Turn on **Settings > Devices > Developer mode**.
2. Add a device (**Settings > Devices > Add Device**, the **+** icon in the
   top right). It shows up as `MuseGadgetXXXXXX`, with the name the
   installer printed.
3. Muse warns that this is a community device. Continue if it's yours.
4. When asked for Wi-Fi, pick the network shown. The machine is already
   online, so no password is needed.

That's it: the device connects to Muse and stays connected, across reboots.
Pairing is open for 10 minutes. To pair again later, run
`sudo musegadget pair`.

Every setup creates a fresh encrypted session, and pairing only opens when you
run the installer or `musegadget pair` on the machine itself. Because these are
community devices, pairing has no manufacturer verification and can't prevent
an active man-in-the-middle attack. Set it up on a network you trust.

## What Muse can do

| Command | What it does |
|---|---|
| `system.run` | Runs a shell command and returns its output and exit code |
| `file.read` | Reads a file, 64 KB at a time |
| `file.write` | Writes a file, 64 KB at a time, replacing it only when complete |
| `device.health` | Reports uptime, load, memory, disk and temperature |

Commands run as the account you installed for, with exactly that account's
permissions. If it can use sudo, so can Muse.

Ask Muse things like:

> What's using all the disk space on my Pi?

> Install Home Assistant on my Pi and tell me how to open it.

> Every morning at 7, check if my Pi's backups ran and tell me if they didn't.

## Hack and extend it

Programs on the machine can send messages to Muse, with no credentials of
their own:

```sh
musegadget send-user-msg "The garage door has been open for an hour."
musegadget send-user-msg --session-id 6f1c2d4e-0b7a-4c3e-9f5d-2a8b1e0c7d93 "Posted to a side chat"
```

`--session-id` posts into a side chat: a new id starts one, and reusing it
keeps later messages there. [`examples/pebble_ring_bridge.py`](examples/pebble_ring_bridge.py)
is a complete example: a webhook listener that sends every note from a Pebble
ring to its own Muse chat.

A few other ways to build on it:

- **Let Muse do it.** Muse can run commands on the machine, so you can ask it to
  set up the rest: "Write a service that tells me when the Pi gets too hot."
- **Add a command.** Commands live in [`src/musegadget/executor.py`](src/musegadget/executor.py):
  add a spec to `COMMAND_SPECS` and a branch in `Executor.run`.
  [`AGENTS.md`](AGENTS.md) walks through it.
- **Change the account.** `bash install.sh --run-as someone` gives Muse a
  different account, such as one without sudo.
- **Change the SDK token.** `bash install.sh --sdk-token mgst_…` replaces it.
  It's saved in `/var/lib/musegadget/sdk_token`, readable only by root.

## Spoken voice replies (TTS)

You can configure your Linux Muse gadget to speak its responses aloud through
its speaker (such as a USB speaker, 3.5mm audio jack, HDMI, or I2S DAC on a Raspberry Pi).

TTS is **optional and disabled by default** to preserve existing silent behavior.

### 1. Hardware

Connect any standard Linux-compatible audio output device to your machine:
- USB speaker or USB DAC
- 3.5mm analog audio jack (Raspberry Pi 3B+/4)
- HDMI audio output
- I2S audio HAT (e.g. HiFiBerry, Adafruit Speaker Bonnet)

Ensure your user account has permission to access the audio subsystem:
```sh
sudo usermod -a -G audio $USER
```

### 2. Install a TTS engine and audio utilities

The easiest offline setup uses `espeak-ng` and standard ALSA playback (`aplay`):

```sh
sudo apt update && sudo apt install -y espeak-ng alsa-utils
```

### 3. Test speech

Verify audio playback and synthesis directly from the command line:

```sh
musegadget say "Hello! Your Muse gadget can speak."
```

### 4. Enable TTS for the service

To enable spoken replies when Muse answers, run the service with `--tts`:

```sh
musegadget run --tts
```

Or set the environment variable:

```sh
export MUSEGADGET_TTS_ENABLED=1
```

### Configuration settings

| Environment Variable | Default | Description |
|---|---|---|
| `MUSEGADGET_TTS_ENABLED` | `0` | Enable or disable spoken replies (`1` or `0`) |
| `MUSEGADGET_TTS_VOICE` | unset | Voice name (e.g. `en`, `en-us`) |
| `MUSEGADGET_TTS_RATE` | unset | Speech speed (words per minute for espeak) |
| `MUSEGADGET_AUDIO_DEVICE` | `default` | ALSA audio device name (e.g. `default`, `hw:0,0`) |

### Troubleshooting

- **`TTS provider 'espeak' is not installed or available`**:
  Install espeak-ng via `sudo apt install espeak-ng`.
- **`Audio output 'alsa' is not available`**:
  Install ALSA playback tools via `sudo apt install alsa-utils`.
- **`No sound heard`**:
  Check speaker volume using `alsamixer`, or test playback with `aplay /usr/share/sounds/alsa/Front_Center.wav`.
- **`Permission denied on audio device`**:
  Add the account to the audio group: `sudo usermod -a -G audio <user>`.

## Manage it

```sh
musegadget info                          # name, node id, pairing and TTS state
sudo systemctl status musegadget         # is it running?
sudo journalctl -u musegadget -f         # follow the log
sudo musegadget pair                     # pair again
bash install.sh --uninstall              # remove it (add --purge to forget the pairing)
```

## Develop

From this directory, with [uv](https://docs.astral.sh/uv/):

```sh
uv run --with pytest --with . pytest
```

The tests run anywhere, with no Bluetooth or Muse needed. To try a change on a
device, copy this directory to it and run `bash install.sh --from .`.

## Community

Meet other hackers who are building and customizing Muse gadgets in our
community [Discord](https://discord.gg/3bhjCkZdd6). Get inspired, support each
other, and share what you make.

## License

Apache 2.0. See [`LICENSE`](../LICENSE).
