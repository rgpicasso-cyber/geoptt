"""Testes do serviço de push (FCM) — sem rede, sem credenciais reais."""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

import pytest

from app.models.enums import Platform
from app.schemas.ws import WsMessageType
from app.services import fcm_service as fcm_module
from app.services.fcm_service import (
    FCM_MAX_DATA_BYTES,
    FcmService,
    SlidingWindowLimiter,
    WakeupResult,
    mask_token,
)


# --------------------------------------------------------------------------- helpers
class FakeClock:
    """Relógio controlável para o rate limiter."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


# --------------------------------------------------------------------------- mask_token
@pytest.mark.parametrize("token", [None, ""])
def test_mask_token_handles_missing_values(token: str | None) -> None:
    assert mask_token(token) == "<none>"


def test_mask_token_never_leaks_full_token() -> None:
    token = "abcdefghijklmnopqrstuvwxyz0123456789"
    masked = mask_token(token)
    assert masked.startswith("abcdef")
    assert token not in masked
    assert "(36b)" in masked


# --------------------------------------------------------------------------- limiter
def test_limiter_allows_up_to_limit() -> None:
    clock = FakeClock()
    limiter = SlidingWindowLimiter(3, window_seconds=60, clock=clock)

    assert [limiter.allow("user-1") for _ in range(4)] == [True, True, True, False]


def test_limiter_is_per_key() -> None:
    clock = FakeClock()
    limiter = SlidingWindowLimiter(1, window_seconds=60, clock=clock)

    assert limiter.allow("user-1") is True
    assert limiter.allow("user-1") is False
    assert limiter.allow("user-2") is True


def test_limiter_window_slides() -> None:
    clock = FakeClock()
    limiter = SlidingWindowLimiter(2, window_seconds=60, clock=clock)

    assert limiter.allow("user-1") is True
    assert limiter.allow("user-1") is True
    assert limiter.allow("user-1") is False

    clock.advance(60)
    assert limiter.allow("user-1") is True


def test_limiter_prunes_when_key_budget_exceeded() -> None:
    clock = FakeClock()
    limiter = SlidingWindowLimiter(1, window_seconds=10, clock=clock, max_keys=2)

    assert limiter.allow("a") is True
    assert limiter.allow("b") is True

    clock.advance(30)  # todas as janelas expiram
    assert limiter.allow("c") is True
    # "a" e "b" foram podados; "c" entra sem estourar o orçamento de chaves.
    assert limiter.allow("d") is True


def test_limiter_rejects_invalid_limit() -> None:
    with pytest.raises(ValueError):
        SlidingWindowLimiter(0)


# --------------------------------------------------------------------------- build_message
def test_build_message_is_data_only_and_high_priority(settings_factory: Any) -> None:
    service = FcmService(settings_factory(fcm_enabled=True))
    channel_id, sender_id, call_id = uuid4(), uuid4(), uuid4()

    message = service.build_message(
        fcm_token="device-token",
        channel_id=channel_id,
        sender_id=sender_id,
        call_id=call_id,
    )

    assert message.token == "device-token"
    assert message.notification is None  # data-only: nunca mostra UI

    data = message.data
    assert data["type"] == str(WsMessageType.PTT_WAKEUP)
    assert data["v"] == "1"
    assert data["channel_id"] == str(channel_id)
    assert data["sender_id"] == str(sender_id)
    assert data["call_id"] == str(call_id)
    assert all(isinstance(value, str) for value in data.values())

    assert message.android is not None
    assert message.android.priority == "high"

    assert message.apns is not None
    assert message.apns.headers["apns-push-type"] == "background"
    assert message.apns.headers["apns-priority"] == "5"
    apns_payload = message.apns.payload
    if isinstance(apns_payload, str):  # o SDK pode serializar o payload
        apns_payload = json.loads(apns_payload)
    assert apns_payload == {"aps": {"content-available": 1}}


def test_build_message_omits_call_id_when_absent(settings_factory: Any) -> None:
    service = FcmService(settings_factory(fcm_enabled=True))
    message = service.build_message(
        fcm_token="device-token",
        channel_id=uuid4(),
        sender_id=uuid4(),
    )
    assert "call_id" not in message.data


def test_build_message_payload_stays_under_fcm_limit(settings_factory: Any) -> None:
    service = FcmService(settings_factory(fcm_enabled=True))
    message = service.build_message(
        fcm_token="device-token",
        channel_id=uuid4(),
        sender_id=uuid4(),
        call_id=uuid4(),
    )
    size = sum(len(key) + len(value) for key, value in message.data.items())
    assert size < FCM_MAX_DATA_BYTES


# --------------------------------------------------------------------------- send_wakeup
async def test_send_wakeup_without_token(settings_factory: Any) -> None:
    service = FcmService(settings_factory(fcm_enabled=True))
    result = await service.send_wakeup(
        user_id=uuid4(),
        fcm_token=None,
        platform=Platform.ANDROID,
        channel_id=uuid4(),
        sender_id=uuid4(),
    )
    assert result == WakeupResult(delivered=False, reason="missing_token")


async def test_send_wakeup_when_fcm_disabled(settings_factory: Any) -> None:
    service = FcmService(settings_factory(fcm_enabled=False))
    result = await service.send_wakeup(
        user_id=uuid4(),
        fcm_token="device-token",
        platform=Platform.IOS,
        channel_id=uuid4(),
        sender_id=uuid4(),
    )
    assert result.delivered is False
    assert result.reason == "fcm_disabled"


async def test_send_wakeup_before_sdk_ready(settings_factory: Any) -> None:
    service = FcmService(settings_factory(fcm_enabled=True))
    result = await service.send_wakeup(
        user_id=uuid4(),
        fcm_token="device-token",
        platform=Platform.ANDROID,
        channel_id=uuid4(),
        sender_id=uuid4(),
    )
    assert result.reason == "not_ready"


async def test_send_wakeup_rate_limited(settings_factory: Any, monkeypatch: Any) -> None:
    clock = FakeClock()
    service = FcmService(
        settings_factory(fcm_enabled=True),
        limiter=SlidingWindowLimiter(1, window_seconds=60, clock=clock),
    )
    service._app = object()  # simula SDK inicializado
    monkeypatch.setattr(fcm_module.messaging, "send", lambda *a, **kw: "ok")

    user_id = uuid4()
    kwargs = {
        "user_id": user_id,
        "fcm_token": "device-token",
        "platform": Platform.ANDROID,
        "channel_id": uuid4(),
        "sender_id": uuid4(),
    }

    assert (await service.send_wakeup(**kwargs)).delivered is True
    second = await service.send_wakeup(**kwargs)
    assert second.delivered is False
    assert second.reason == "rate_limited"


async def test_send_wakeup_success(settings_factory: Any, monkeypatch: Any) -> None:
    service = FcmService(settings_factory(fcm_enabled=True))
    service._app = object()  # simula SDK inicializado
    monkeypatch.setattr(fcm_module.messaging, "send", lambda *a, **kw: "projects/x/messages/1")

    result = await service.send_wakeup(
        user_id=uuid4(),
        fcm_token="device-token",
        platform=Platform.ANDROID,
        channel_id=uuid4(),
        sender_id=uuid4(),
    )
    assert result == WakeupResult(delivered=True)


async def test_send_wakeup_detects_unregistered_token(
    settings_factory: Any, monkeypatch: Any
) -> None:
    service = FcmService(settings_factory(fcm_enabled=True))
    service._app = object()  # simula SDK inicializado

    def boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("Requested entity was not found: registration-token-not-registered")

    monkeypatch.setattr(fcm_module.messaging, "send", boom)

    result = await service.send_wakeup(
        user_id=uuid4(),
        fcm_token="dead-token",
        platform=Platform.ANDROID,
        channel_id=uuid4(),
        sender_id=uuid4(),
    )
    assert result.delivered is False
    assert result.invalid_token is True
    assert result.reason == "unregistered"


async def test_send_wakeup_swallows_transient_errors(
    settings_factory: Any, monkeypatch: Any
) -> None:
    service = FcmService(settings_factory(fcm_enabled=True))
    service._app = object()  # simula SDK inicializado

    def boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("internal server error")

    monkeypatch.setattr(fcm_module.messaging, "send", boom)

    result = await service.send_wakeup(
        user_id=uuid4(),
        fcm_token="device-token",
        platform=Platform.ANDROID,
        channel_id=uuid4(),
        sender_id=uuid4(),
    )
    assert result.delivered is False
    assert result.invalid_token is False
    assert result.reason == "send_failed"


# --------------------------------------------------------------------------- ciclo de vida
async def test_start_is_noop_when_disabled(settings_factory: Any) -> None:
    service = FcmService(settings_factory(fcm_enabled=False))
    await service.start()
    assert service.ready is False
    assert service.enabled is False


async def test_stop_without_start_is_safe(settings_factory: Any) -> None:
    service = FcmService(settings_factory(fcm_enabled=False))
    await service.stop()
    assert service.ready is False
