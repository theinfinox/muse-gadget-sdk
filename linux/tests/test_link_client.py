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
import json
import struct

import pytest

from musegadget.link_client import (
    DeviceDescription, LinkSession, MessageDecoder, Outcome, encode_message, noise_url,
)
from musegadget.noise import (
    ApplicationResponse, BodyChunk, NoiseFrameDecoder, NoiseXXResponder, Reset, ServiceFrame,
    encode_noise_frames,
)
from musegadget.noise.transport import decode_request_envelope, encode_response_envelope

DEVICE = DeviceDescription(
    node_id="homelink-abcdef", display_name="pi", version="0.1.0",
    commands={"system.run": {"description": "run", "required": {}, "optional": {}}},
)


class Pipe:
    """One end of an in-memory WebSocket."""

    def __init__(self, inbox: asyncio.Queue, outbox: asyncio.Queue) -> None:
        self._inbox, self._outbox = inbox, outbox

    async def send(self, data) -> None:
        await self._outbox.put(data)

    async def recv(self):
        data = await self._inbox.get()
        if data is None:
            raise ConnectionError("closed")
        return data

    async def close(self) -> None:
        await self._outbox.put(None)


class FakeVm:
    """Just enough of the Muse VM: Noise responder plus the control stream."""

    def __init__(self, ws: Pipe) -> None:
        self.ws = ws
        self.decoder = NoiseFrameDecoder()
        self.messages = MessageDecoder()
        self.stream_id = 0

    async def handshake(self) -> None:
        responder = NoiseXXResponder()
        responder.initialize()
        await self.ws.send(responder.read_message1_and_write_message2(await self.ws.recv()))
        responder.read_message3(await self.ws.recv())
        self.send_cipher, self.recv_cipher = responder.split()

    async def next_frame(self) -> ServiceFrame:
        while True:
            plain = self.recv_cipher.decrypt_with_ad(b"", await self.ws.recv())
            assembled = self.decoder.decode(plain)
            if assembled is not None:
                return decode_request_envelope(assembled)

    async def next_message(self) -> dict:
        while True:
            frame = await self.next_frame()
            assert frame.kind == "body_chunk"
            messages = self.messages.feed(frame.value.data)
            if messages:
                return messages[0]

    async def send_frame(self, frame: ServiceFrame) -> None:
        for chunk in encode_noise_frames(encode_response_envelope(frame)):
            await self.ws.send(self.send_cipher.encrypt_with_ad(b"", chunk))

    async def accept_control_stream(self, status: int = 200) -> ServiceFrame:
        request = await self.next_frame()
        self.stream_id = request.stream_id
        await self.send_frame(ServiceFrame.response(
            self.stream_id, ApplicationResponse(status=status, end_body=status >= 400),
        ))
        return request

    async def send_message(self, message: dict) -> None:
        await self.send_frame(ServiceFrame.body_chunk(
            self.stream_id, BodyChunk(data=encode_message(message)),
        ))


def make_session(run_command, connect_log: list, on_response=None):
    to_device, to_vm = asyncio.Queue(), asyncio.Queue()
    device_ws, vm_ws = Pipe(to_device, to_vm), Pipe(to_vm, to_device)

    async def connect(url, headers):
        connect_log.append((url, headers))
        return device_ws

    session = LinkSession(
        noise_host="gw.example", vm_id="vm 1&x", vm_auth_token="tok",
        device=DEVICE, run_command=run_command, on_response=on_response, connect=connect,
    )
    return session, FakeVm(vm_ws)


def test_register_invoke_result_and_unpair():
    async def scenario():
        calls, connects = [], []

        def run_command(command, params, timeout_ms):
            calls.append((command, params, timeout_ms))
            return {"ok": True, "payload": {"stdout": "hi\n", "exit_code": 0}}

        session, vm = make_session(run_command, connects)
        stop = asyncio.Event()
        task = asyncio.ensure_future(session.run(stop))

        await vm.handshake()
        request = await vm.accept_control_stream()
        assert (request.kind, request.value.verb, request.value.path, request.value.end_body) == (
            "request", "POST", "/link-control", False)

        register = await vm.next_message()
        assert register["method"] == "link.register"
        params = register["params"]
        assert params["node_id"] == "homelink-abcdef"
        assert (params["platform"], params["device_family"]) == ("linux", "homehub")
        assert "system.run" in params["commands_v2"]
        await vm.send_message({"type": "res", "id": register["id"], "ok": True})

        await vm.send_message({
            "method": "link.invoke", "id": "inv-1", "command": "system.run",
            "params": {"command": "echo hi"}, "timeout_ms": 5000,
        })
        result = await vm.next_message()
        assert result == {"method": "link.result", "id": "inv-1", "ok": True,
                          "payload": {"stdout": "hi\n", "exit_code": 0}}
        assert calls == [("system.run", {"command": "echo hi"}, 5000)]
        assert session.registered_at is not None

        await vm.send_message({"type": "evt", "event": "link.unpaired"})
        assert await asyncio.wait_for(task, 2) is Outcome.UNPAIRED
        url, headers = connects[0]
        assert url == "wss://gw.example/v1/noise?vm_id=vm%201%26x"
        assert headers == {"Authorization": "Bearer tok"}

    asyncio.run(scenario())


def test_forbidden_control_stream():
    async def scenario():
        session, vm = make_session(lambda *a: {"ok": True}, [])
        task = asyncio.ensure_future(session.run(asyncio.Event()))
        await vm.handshake()
        await vm.accept_control_stream(status=403)
        assert await asyncio.wait_for(task, 2) is Outcome.FORBIDDEN

    asyncio.run(scenario())


def test_stop_ends_the_session():
    async def scenario():
        session, vm = make_session(lambda *a: {"ok": True}, [])
        stop = asyncio.Event()
        task = asyncio.ensure_future(session.run(stop))
        await vm.handshake()
        await vm.accept_control_stream()
        await vm.next_message()
        stop.set()
        assert await asyncio.wait_for(task, 2) is Outcome.STOPPED

    asyncio.run(scenario())


def test_decoder_handles_split_and_batched_messages():
    data = encode_message({"a": 1}) + encode_message({"b": 2}) + struct.pack("<I", 0)
    decoder = MessageDecoder()
    assert decoder.feed(data[:5]) == []
    assert decoder.feed(data[5:]) == [{"a": 1}, {"b": 2}]


def test_decoder_rejects_oversize_messages():
    with pytest.raises(ValueError):
        MessageDecoder().feed(struct.pack("<I", 1 << 30))


def test_vm_id_is_escaped_like_encode_uri_component():
    assert noise_url("h", "a-b_c.d!~*'()?&=") == "wss://h/v1/noise?vm_id=a-b_c.d!~*'()%3F%26%3D"


def test_send_chat_posts_a_device_attributed_message_on_the_same_session():
    async def scenario():
        session, vm = make_session(lambda *a: {"ok": True}, [])
        task = asyncio.ensure_future(session.run(asyncio.Event()))
        await vm.handshake()
        await vm.accept_control_stream()
        await vm.next_message()  # link.register

        reply = asyncio.ensure_future(session.send_chat("porch light on", "side-1"))
        request = await vm.next_frame()
        assert (request.kind, request.value.verb, request.value.path, request.value.end_body) == (
            "request", "POST", "/chat/stream", True)
        assert json.loads(request.value.body) == {
            "message": "porch light on", "output_modality": "text", "device_id": "homelink-abcdef",
            "session_id": "side-1"}
        headers = {h.key.lower(): h.value for h in request.value.headers}
        assert headers["content-type"] == "application/json"
        await vm.send_frame(ServiceFrame.response(
            request.stream_id,
            ApplicationResponse(status=200, body=b'{"accepted":true}', end_body=True),
        ))
        assert await asyncio.wait_for(reply, 2) == {
            "ok": True, "status": 200, "response": {"accepted": True}}
        task.cancel()

    asyncio.run(scenario())


def test_response_event_triggers_on_response():
    async def scenario():
        responses = []
        session, vm = make_session(lambda *a: {"ok": True}, [], on_response=responses.append)
        task = asyncio.ensure_future(session.run(asyncio.Event()))
        await vm.handshake()
        await vm.accept_control_stream()
        register = await vm.next_message()
        await vm.send_message({"type": "res", "id": register["id"], "ok": True})

        # Send a delta.message_done event
        await vm.send_message({
            "type": "event",
            "event": "delta.message_done",
            "payload": {
                "message_id": "msg-001",
                "display_text": "The garage door is closed.",
                "display_text_ready": True,
            },
        })

        for _ in range(10):
            if responses:
                break
            await asyncio.sleep(0.02)

        assert responses == ["The garage door is closed."]
        task.cancel()

    asyncio.run(scenario())


def test_response_event_deduplicates_by_message_id():
    async def scenario():
        responses = []
        session, vm = make_session(lambda *a: {"ok": True}, [], on_response=responses.append)
        task = asyncio.ensure_future(session.run(asyncio.Event()))
        await vm.handshake()
        await vm.accept_control_stream()
        register = await vm.next_message()
        await vm.send_message({"type": "res", "id": register["id"], "ok": True})

        # Send delta.message_done
        await vm.send_message({
            "type": "event",
            "event": "delta.message_done",
            "payload": {
                "message_id": "msg-dup",
                "display_text": "Hello again",
                "display_text_ready": True,
            },
        })

        # Send message.assistant with same message_id
        await vm.send_message({
            "type": "event",
            "event": "message.assistant",
            "payload": {
                "message_id": "msg-dup",
                "display_text": "Hello again",
                "content": "Hello again",
            },
        })

        await asyncio.sleep(0.05)
        # Should only have been received once due to deduplication
        assert responses == ["Hello again"]
        task.cancel()

    asyncio.run(scenario())


def test_response_event_ignores_not_ready():
    async def scenario():
        responses = []
        session, vm = make_session(lambda *a: {"ok": True}, [], on_response=responses.append)
        task = asyncio.ensure_future(session.run(asyncio.Event()))
        await vm.handshake()
        await vm.accept_control_stream()
        register = await vm.next_message()
        await vm.send_message({"type": "res", "id": register["id"], "ok": True})

        await vm.send_message({
            "type": "event",
            "event": "delta.message_done",
            "payload": {
                "message_id": "msg-notready",
                "display_text": "Partial text",
                "display_text_ready": False,
            },
        })

        await asyncio.sleep(0.05)
        assert responses == []
        task.cancel()

    asyncio.run(scenario())


def test_subscription_request_terminates_body():
    async def scenario():
        responses = []
        session, vm = make_session(lambda *a: {"ok": True}, [], on_response=responses.append)
        task = asyncio.ensure_future(session.run(asyncio.Event()))
        await vm.handshake()
        await vm.accept_control_stream()
        register = await vm.next_message()
        await vm.send_message({"type": "res", "id": register["id"], "ok": True})

        sub_req = await vm.next_frame()
        assert sub_req.kind == "request"
        assert sub_req.value.path == "/chat/subscribe"
        assert sub_req.value.verb == "POST"

        sub_body = await vm.next_frame()
        assert sub_body.kind == "body_chunk"
        assert sub_body.value.data == b"{}\n"
        assert sub_body.value.end_body is True

        task.cancel()

    asyncio.run(scenario())


def test_no_subscription_stream_when_on_response_is_none():
    async def scenario():
        session, vm = make_session(lambda *a: {"ok": True}, [], on_response=None)
        task = asyncio.ensure_future(session.run(asyncio.Event()))
        await vm.handshake()
        await vm.accept_control_stream()
        register = await vm.next_message()
        await vm.send_message({"type": "res", "id": register["id"], "ok": True})

        await asyncio.sleep(0.05)
        assert vm.ws._outbox.empty()
        assert session._sub_stream_id is None

        task.cancel()

    asyncio.run(scenario())


def test_subscription_reset_and_reconnect():
    async def scenario():
        responses = []
        session, vm = make_session(lambda *a: {"ok": True}, [], on_response=responses.append)
        task = asyncio.ensure_future(session.run(asyncio.Event()))
        await vm.handshake()
        await vm.accept_control_stream()
        register = await vm.next_message()
        await vm.send_message({"type": "res", "id": register["id"], "ok": True})

        sub_req1 = await vm.next_frame()
        sub_body1 = await vm.next_frame()
        assert sub_body1.value.end_body is True
        stream_id1 = sub_req1.stream_id

        # VM resets the subscription stream
        await vm.send_frame(ServiceFrame.reset(
            stream_id1, Reset(code=1, reason="stream cancelled"),
        ))

        # Device should detect reset, clear stale stream, and reconnect with new stream id
        sub_req2 = await asyncio.wait_for(vm.next_frame(), timeout=3.0)
        assert sub_req2.kind == "request"
        assert sub_req2.value.path == "/chat/subscribe"
        assert sub_req2.stream_id != stream_id1

        sub_body2 = await vm.next_frame()
        assert sub_body2.value.end_body is True

        chunk_data = (
            b'{"type":"event","event":"delta.message_done","payload":'
            b'{"message_id":"m1","display_text":"hello after reconnect",'
            b'"display_text_ready":true}}\n'
        )
        await vm.send_frame(ServiceFrame.body_chunk(
            sub_req2.stream_id,
            BodyChunk(data=chunk_data),
        ))

        for _ in range(10):
            if responses:
                break
            await asyncio.sleep(0.02)

        assert responses == ["hello after reconnect"]
        task.cancel()

    asyncio.run(scenario())


def test_subscription_clean_shutdown_while_reconnect_pending():
    async def scenario():
        responses = []
        stop_event = asyncio.Event()
        session, vm = make_session(lambda *a: {"ok": True}, [], on_response=responses.append)
        task = asyncio.ensure_future(session.run(stop_event))
        await vm.handshake()
        await vm.accept_control_stream()
        register = await vm.next_message()
        await vm.send_message({"type": "res", "id": register["id"], "ok": True})

        sub_req = await vm.next_frame()
        await vm.next_frame()

        # VM resets subscription stream; reconnect delay is 1.0s
        await vm.send_frame(ServiceFrame.reset(sub_req.stream_id, Reset(code=1, reason="reset")))
        await asyncio.sleep(0.05)

        assert session._sub_reconnect_task is not None
        assert not session._sub_reconnect_task.done()

        # Stop session while reconnect is pending
        stop_event.set()
        outcome = await asyncio.wait_for(task, timeout=2.0)
        assert outcome is Outcome.STOPPED
        assert session._sub_reconnect_task is None

    asyncio.run(scenario())
