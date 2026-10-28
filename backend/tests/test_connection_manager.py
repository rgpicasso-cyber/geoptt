"""Testes do `ConnectionManager` e do `Connection`.

Cobrem o que realmente pode quebrar em produção:
  * uma única escrita concorrente por socket (writer task);
  * backpressure de áudio (descarte do frame mais antigo);
  * fila de controle cheia derruba a conexão em vez de perder mensagem;
  * registro/desregistro e contagem de presença.
"""

from __future__ import annotations

import asyncio
import json
from uuid import uuid4

import pytest

from app.services.connection_manager import Connection, ConnectionManager
from tests.helpers import FakeWebSocket, wait_until


# --------------------------------------------------------------------------- Connection
async def test_audio_queue_drops_oldest_frame_when_full() -> None:
    ws = FakeWebSocket()
    conn = Connection(user_id=uuid4(), websocket=ws, audio_queue_size=2)  # type: ignore[arg-type]

    # Writer ainda não iniciado: a fila enche de forma determinística.
    assert conn.enqueue_audio(b"frame-1") is True
    assert conn.enqueue_audio(b"frame-2") is True
    assert conn.enqueue_audio(b"frame-3") is True

    assert conn.dropped_audio_frames == 1

    conn.start()
    try:
        await wait_until(lambda: len(ws.sent_bytes) == 2)
        assert ws.sent_bytes == [b"frame-2", b"frame-3"]
    finally:
        await conn.stop()


async def test_control_queue_full_closes_connection() -> None:
    conn = Connection(
        user_id=uuid4(),
        websocket=FakeWebSocket(),  # type: ignore[arg-type]
        control_queue_size=2,
    )
    assert conn.enqueue_json({"type": "PING"}) is True
    assert conn.enqueue_json({"type": "PING"}) is True
    # Terceira mensagem de controle não pode ser descartada silenciosamente.
    assert conn.enqueue_json({"type": "PING"}) is False
    assert conn.closed is True


async def test_enqueue_after_close_is_rejected() -> None:
    conn = Connection(user_id=uuid4(), websocket=FakeWebSocket())  # type: ignore[arg-type]
    conn.closed = True
    assert conn.enqueue_json({"type": "PONG"}) is False
    assert conn.enqueue_audio(b"x") is False


async def test_writer_flushes_text_and_bytes() -> None:
    ws = FakeWebSocket()
    conn = Connection(user_id=uuid4(), websocket=ws)  # type: ignore[arg-type]
    conn.start()
    try:
        assert conn.enqueue_json({"type": "PONG", "v": 1}) is True
        assert conn.enqueue_audio(b"\x00opus") is True

        await wait_until(lambda: len(ws.sent_text) == 1 and len(ws.sent_bytes) == 1)
        assert json.loads(ws.sent_text[0]) == {"type": "PONG", "v": 1}
        assert ws.sent_bytes[0] == b"\x00opus"
    finally:
        await conn.stop()
    assert ws.client_state.name == "DISCONNECTED"


@pytest.mark.parametrize("queue_size", [2, 4, 8])
async def test_audio_queue_respects_configured_size(queue_size: int) -> None:
    ws = FakeWebSocket()
    conn = Connection(
        user_id=uuid4(),
        websocket=ws,  # type: ignore[arg-type]
        audio_queue_size=queue_size,
    )
    for index in range(queue_size + 3):
        conn.enqueue_audio(bytes([index]))

    assert conn.dropped_audio_frames == 3

    conn.start()
    try:
        await wait_until(lambda: len(ws.sent_bytes) == queue_size)
        assert ws.sent_bytes == [bytes([3 + offset]) for offset in range(queue_size)]
    finally:
        await conn.stop()


# --------------------------------------------------------------------------- Manager
async def test_register_and_unregister_tracks_presence() -> None:
    manager = ConnectionManager()
    user_id = uuid4()

    assert manager.is_online(user_id) is False

    conn = await manager.register(FakeWebSocket(), user_id, device_id="pixel-7")  # type: ignore[arg-type]
    try:
        assert manager.is_online(user_id) is True
        assert manager.online_user_ids() == frozenset({user_id})
        assert manager.stats["online_users"] == 1
        assert manager.stats["connections"] == 1
        assert manager.connections_of(user_id) == (conn,)
    finally:
        await manager.unregister(conn)

    assert manager.is_online(user_id) is False
    assert manager.online_user_ids() == frozenset()
    assert manager.connections_of(user_id) == ()


async def test_multiple_devices_for_same_user() -> None:
    manager = ConnectionManager()
    user_id = uuid4()

    first = await manager.register(FakeWebSocket(), user_id, device_id="a")  # type: ignore[arg-type]
    second = await manager.register(FakeWebSocket(), user_id, device_id="b")  # type: ignore[arg-type]
    try:
        assert manager.is_online(user_id) is True
        assert manager.stats["connections"] == 2
        assert len(manager.connections_of(user_id)) == 2
    finally:
        await manager.unregister(first)
        await manager.unregister(second)


async def test_send_to_user_delivers_to_every_device() -> None:
    manager = ConnectionManager()
    user_id = uuid4()
    ws_a, ws_b = FakeWebSocket(), FakeWebSocket()

    await manager.register(ws_a, user_id)  # type: ignore[arg-type]
    await manager.register(ws_b, user_id)  # type: ignore[arg-type]

    payload = {"type": "PTT_SPEAKER_START", "data": {"channel_id": "c1"}}
    assert manager.send_to_user(user_id, payload) == 2

    await wait_until(lambda: len(ws_a.sent_text) == 1 and len(ws_b.sent_text) == 1)
    assert json.loads(ws_a.sent_text[0]) == payload
    assert json.loads(ws_b.sent_text[0]) == payload


async def test_send_to_unknown_user_is_noop() -> None:
    manager = ConnectionManager()
    assert manager.send_to_user(uuid4(), {"type": "PONG"}) == 0
    assert manager.send_audio_to_user(uuid4(), b"x") == 0


async def test_broadcast_counts_sockets_not_users() -> None:
    manager = ConnectionManager()
    user_a, user_b = uuid4(), uuid4()
    await manager.register(FakeWebSocket(), user_a)  # type: ignore[arg-type]
    await manager.register(FakeWebSocket(), user_a)  # type: ignore[arg-type]
    await manager.register(FakeWebSocket(), user_b)  # type: ignore[arg-type]

    assert manager.broadcast([user_a, user_b], {"type": "PING"}) == 3
    assert manager.broadcast_audio([user_a, user_b], b"opus") == 3


async def test_close_all_disconnects_everything() -> None:
    manager = ConnectionManager()
    ws_one, ws_two = FakeWebSocket(), FakeWebSocket()
    await manager.register(ws_one, uuid4())  # type: ignore[arg-type]
    await manager.register(ws_two, uuid4())  # type: ignore[arg-type]

    await manager.close_all()

    assert manager.stats["online_users"] == 0
    assert manager.online_user_ids() == frozenset()
    assert ws_one.client_state.name == "DISCONNECTED"
    assert ws_two.client_state.name == "DISCONNECTED"


async def test_stop_is_idempotent() -> None:
    conn = Connection(user_id=uuid4(), websocket=FakeWebSocket())  # type: ignore[arg-type]
    conn.start()
    await conn.stop()
    await conn.stop()
    assert conn.closed is True


async def test_dropped_audio_is_aggregated_on_unregister() -> None:
    manager = ConnectionManager(audio_queue_size=2)
    conn = await manager.register(FakeWebSocket(), uuid4())  # type: ignore[arg-type]
    conn.dropped_audio_frames = 7
    await manager.unregister(conn)
    assert manager.stats["dropped_audio_frames"] == 7


async def test_concurrent_sends_are_serialized_by_writer() -> None:
    """`send` simultâneo no mesmo socket quebraria o Starlette — o writer evita isso."""
    ws = FakeWebSocket()
    manager = ConnectionManager()
    user_id = uuid4()
    await manager.register(ws, user_id)  # type: ignore[arg-type]

    async def send(index: int) -> None:
        await asyncio.sleep(0)  # força intercalação entre as tarefas
        manager.send_to_user(user_id, {"n": index})

    await asyncio.gather(*(send(index) for index in range(20)))

    await wait_until(lambda: len(ws.sent_text) == 20, timeout=3.0)
    assert sorted(json.loads(item)["n"] for item in ws.sent_text) == list(range(20))
