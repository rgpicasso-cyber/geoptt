"""Rate limit em memória por chave (janela deslizante).

Usado em dois pontos com semânticas diferentes:

* **FCM** (`FcmService`) — evita *push bombing*: um cliente malicioso não deve
  conseguir forçar o servidor a disparar milhares de pushes para a mesma vítima.
* **HTTP** (`/auth/register`, `/auth/login`) — evita *credential stuffing* e
  criação massiva de contas: 5 requisições por minuto por IP.

A implementação é single-node (como o hub WebSocket). Escala horizontal exige
estado compartilhado — ver ADR-001.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable, Hashable
from typing import Final

# Limite de `/auth/register` e `/auth/login` por IP.
AUTH_RATE_LIMIT_PER_MINUTE: Final = 5


class SlidingWindowLimiter:
    """Permite no máximo `limit` eventos por chave dentro de `window_seconds`."""

    def __init__(
        self,
        limit: int,
        *,
        window_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
        max_keys: int = 10_000,
    ) -> None:
        if limit < 1:
            msg = "limit deve ser >= 1"
            raise ValueError(msg)
        self._limit = limit
        self._window = window_seconds
        self._clock = clock
        self._max_keys = max_keys
        self._buckets: dict[Hashable, deque[float]] = {}

    def allow(self, key: Hashable) -> bool:
        """Registra a tentativa e informa se ela é permitida."""
        now = self._clock()
        bucket = self._buckets.get(key)
        if bucket is None:
            if len(self._buckets) >= self._max_keys:
                self._prune(now)
            bucket = deque()
            self._buckets[key] = bucket

        while bucket and now - bucket[0] >= self._window:
            bucket.popleft()

        if len(bucket) >= self._limit:
            return False

        bucket.append(now)
        return True

    def retry_after_seconds(self, key: Hashable) -> int:
        """Segundos até a próxima tentativa ser aceita (mínimo 1)."""
        bucket = self._buckets.get(key)
        if not bucket:
            return 0
        remaining = self._window - (self._clock() - bucket[0])
        return max(1, int(remaining) + 1)

    def reset(self, key: Hashable | None = None) -> None:
        """Limpa o estado — útil em testes."""
        if key is None:
            self._buckets.clear()
        else:
            self._buckets.pop(key, None)

    def _prune(self, now: float) -> None:
        expired = [
            key
            for key, bucket in self._buckets.items()
            if not bucket or now - bucket[-1] >= self._window
        ]
        for key in expired:
            self._buckets.pop(key, None)
