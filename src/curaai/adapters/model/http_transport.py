"""What every HTTPS model service shares: one request with the standard library, retries,
and a backup model. Gemini (gemini_transport.py) and Groq (groq_transport.py) each add only
their own request shape and answer parsing.

  * errors say which kind they are: the service answered with an error (HTTP code plus the
    service's own reason), it never answered in time, or no connection at all
  * "too many requests" (429) and brief outages (500/503) are retried up to MAX_ATTEMPTS
    times, waiting as long as the service asks (Retry-After / Google RetryInfo), at most
    MAX_WAIT_S; a timeout is retried once, without waiting
  * backup model: if the main model is still busy after its retries (429/500/503 or a
    timeout), the same request goes to the backup model once. A bad key or any other error
    never switches models
  * every request names itself (USER_AGENT). Without it urllib sends "Python-urllib/3.x",
    which Cloudflare (in front of Groq's API) blocks as a bot: a bare HTTP 403 "Forbidden"
    on every call, with a valid key
  * standard library only (urllib), so no extra package to install
"""

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from typing import Protocol

from curaai.adapters.model.gateway import VendorReply

DEFAULT_TIMEOUT_S = 60.0                 # per request
USER_AGENT = "CuraAI/0.1 (CS302 prototype)"   # never urllib's default; see the module docstring
RETRYABLE = frozenset({429, 500, 503})   # too many requests, server error, overloaded
MAX_ATTEMPTS = 3
BACKOFF_S = (4.0, 10.0)                  # used when the service doesn't say how long to wait
MAX_WAIT_S = 30.0


class ModelHttpError(RuntimeError):
    """Any failure talking to a model service. The gateway turns it into ModelUnavailable
    (AI off for the case, fixed chart pull continues)."""

    def __init__(self, message: str, status: int | None = None, retry_after_s: float | None = None,
                 timed_out: bool = False) -> None:
        super().__init__(message)
        self.status = status
        self.retry_after_s = retry_after_s
        self.timed_out = timed_out

    @property
    def busy(self) -> bool:
        """Worth retrying or trying the backup model: rate limit, outage, or no answer in time."""
        return self.status in RETRYABLE or self.timed_out


def retry_delay_s(error_body: Mapping, header_value: str | None) -> float | None:
    """Pure: how long the service asked us to wait, from Google's RetryInfo ("17s") or Retry-After."""
    error = error_body.get("error") if isinstance(error_body, Mapping) else None
    for detail in (error.get("details") if isinstance(error, Mapping) else None) or []:
        delay = detail.get("retryDelay") if isinstance(detail, Mapping) else None
        if isinstance(delay, str) and delay.endswith("s"):
            try:
                return float(delay[:-1])
            except ValueError:
                pass
    try:
        return float(header_value) if header_value else None
    except ValueError:
        return None


class JsonPoster(Protocol):
    def post_json(self, url: str, headers: Mapping[str, str], body: Mapping, timeout_s: float) -> Mapping: ...


# ---- humble -----------------------------------------------------------------------------------
class UrllibJsonPoster:
    """One HTTPS request with the standard library; every failure becomes `error` (a ModelHttpError)
    whose message starts with the service name."""

    def __init__(self, service: str = "Model service", error: type[ModelHttpError] = ModelHttpError) -> None:
        self._service = service
        self._error = error

    def post_json(self, url: str, headers: Mapping[str, str], body: Mapping, timeout_s: float) -> Mapping:
        request = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                         headers={"Content-Type": "application/json", "User-Agent": USER_AGENT,
                                                  **headers})
        return self._send(request, timeout_s)

    def get_json(self, url: str, headers: Mapping[str, str], timeout_s: float) -> Mapping:
        return self._send(urllib.request.Request(url, method="GET", headers={"User-Agent": USER_AGENT, **headers}),
                          timeout_s)

    def _send(self, request: urllib.request.Request, timeout_s: float) -> Mapping:
        name, error = self._service, self._error
        try:
            with urllib.request.urlopen(request, timeout=timeout_s) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body: Mapping = {}
            try:
                body = json.loads(exc.read().decode("utf-8"))
            except Exception:
                pass
            err = body.get("error") if isinstance(body, Mapping) else None
            detail = err.get("message", "") if isinstance(err, Mapping) else (err if isinstance(err, str) else "")
            raise error(f"{name} HTTP {exc.code}: {detail or exc.reason}", status=exc.code,
                        retry_after_s=retry_delay_s(body, exc.headers.get("Retry-After"))) from None
        except TimeoutError:
            raise error(f"{name} sent no answer within {timeout_s:.0f} s (timed out)", timed_out=True) from None
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise error(f"{name} sent no answer within {timeout_s:.0f} s (timed out)", timed_out=True) from None
            raise error(f"{name} unreachable: could not connect ({exc.reason})") from None


# ---- the shared loop -------------------------------------------------------------------------------
class HttpModelTransport:
    """VendorTransport base: subclasses say how to build a request and read an answer."""

    error: type[ModelHttpError] = ModelHttpError

    def __init__(self, model: str, *, fallback_model: str | None, poster: JsonPoster, timeout_s: float,
                 sleep: Callable[[float], None]) -> None:
        self._model = model
        self._fallback = fallback_model if fallback_model and fallback_model != model else None
        self._poster = poster
        self._timeout = timeout_s
        self._sleep = sleep

    # subclasses
    def _request(self, model: str, system: str, user: str, max_output_tokens: int) -> tuple[str, dict, dict]:
        raise NotImplementedError                 # (url, headers, body)

    def _parse(self, response: Mapping, model: str) -> VendorReply:
        raise NotImplementedError

    def send(self, system: str, user: str, max_output_tokens: int) -> VendorReply:
        try:
            return self._send_to(self._model, system, user, max_output_tokens)
        except ModelHttpError as exc:
            if not (exc.busy and self._fallback):
                raise
            try:
                return self._send_to(self._fallback, system, user, max_output_tokens)
            except ModelHttpError as backup_exc:
                raise self.error(f"{exc}; backup model {self._fallback}: {backup_exc}", status=backup_exc.status,
                                 timed_out=backup_exc.timed_out) from None

    def _send_to(self, model: str, system: str, user: str, max_output_tokens: int) -> VendorReply:
        url, headers, body = self._request(model, system, user, max_output_tokens)
        timeouts = 0
        for attempt in range(MAX_ATTEMPTS):
            try:
                return self._parse(self._poster.post_json(url, headers, body, self._timeout), model)
            except ModelHttpError as exc:
                timeouts += exc.timed_out
                retry = exc.status in RETRYABLE or (exc.timed_out and timeouts == 1)   # a timeout is retried once
                if not retry or attempt == MAX_ATTEMPTS - 1:
                    raise
                if not exc.timed_out:
                    self._sleep(min(exc.retry_after_s or BACKOFF_S[attempt], MAX_WAIT_S))
        raise self.error("unreachable")   # pragma: no cover
