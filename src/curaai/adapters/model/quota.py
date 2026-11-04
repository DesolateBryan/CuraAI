"""Spending less of a model's quota: fewer calls, spaced out, never paid for twice.

Free Groq and Gemini keys have a per-minute limit (requests and tokens) and a daily
token limit. The demo sends six patients at once and each case can make up to 12 calls,
so a free key runs out ("too much traffic, not enough tokens"). Three small pieces,
wired in app/main.py for the hosted backends (groq, gemini):

  * PortRouter (a GatewayClient): sends each model port to its own client. With
    CURAAI_AI_USE_FOR=reading (the default) only extract_symptoms, reading the
    patient's message, goes to the hosted model; choosing a follow-up, picking chart
    items and matching drug flags use the local reader. A full six-patient demo run
    makes 16 hosted calls instead of 30.
  * ReplyCache (a VendorTransport): the same request gets the same answer without a
    new call, so page reloads, Reset and Re-run are free. A cached answer reports
    0 tokens (no cost) and its model as "<model> (cached)" in the audit log.
  * Pacer (a VendorTransport): starts at most N requests per minute
    (CURAAI_AI_MAX_PER_MINUTE, default 8), waiting instead of being refused with HTTP 429.

The gateway still redacts, audits and prices every call, and every answer still goes
through the parsers and the core validator, whichever client or cache produced it.
"""

import hashlib
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping

from curaai.adapters.model.gateway import VendorReply, VendorTransport
from curaai.adapters.model.gateway_client import GatewayClient, GatewayReply, Prompt


class PortRouter:
    """GatewayClient that picks a client by Prompt.port, with a default for the rest."""

    def __init__(self, default: GatewayClient, routes: Mapping[str, GatewayClient]) -> None:
        self._default = default
        self._routes = dict(routes)

    def complete(self, prompt: Prompt) -> GatewayReply:
        return self._routes.get(prompt.port, self._default).complete(prompt)


class ReplyCache:
    """VendorTransport decorator: identical (system, user, max tokens) -> the earlier answer."""

    def __init__(self, inner: VendorTransport, max_entries: int = 500) -> None:
        self._inner = inner
        self._max = max_entries
        self._replies: OrderedDict[str, VendorReply] = OrderedDict()
        self._lock = threading.Lock()

    def send(self, system: str, user: str, max_output_tokens: int) -> VendorReply:
        key = hashlib.sha256(f"{max_output_tokens}\x00{system}\x00{user}".encode("utf-8")).hexdigest()
        with self._lock:
            hit = self._replies.get(key)
            if hit is not None:
                self._replies.move_to_end(key)
                return VendorReply(hit.text, 0, 0, f"{hit.model} (cached)")
        reply = self._inner.send(system, user, max_output_tokens)   # failures are never cached
        with self._lock:
            self._replies[key] = reply
            while len(self._replies) > self._max:
                self._replies.popitem(last=False)
        return reply


class Pacer:
    """VendorTransport decorator: request starts are at least 60/N seconds apart (thread-safe)."""

    def __init__(self, inner: VendorTransport, max_per_minute: float,
                 clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep) -> None:
        if max_per_minute <= 0:
            raise ValueError("max_per_minute must be positive")
        self._inner = inner
        self._gap = 60.0 / max_per_minute
        self._clock = clock
        self._sleep = sleep
        self._next_start = 0.0
        self._lock = threading.Lock()

    def send(self, system: str, user: str, max_output_tokens: int) -> VendorReply:
        with self._lock:                                   # book a start slot, then wait outside the lock
            now = self._clock()
            start = max(now, self._next_start)
            self._next_start = start + self._gap
        if start > now:
            self._sleep(start - now)
        return self._inner.send(system, user, max_output_tokens)
