"""GeminiTransport: VendorTransport over Google's Gemini API (generateContent, REST).

CURAAI_MODEL_BACKEND=gemini. Same slot as Bedrock and the local reader: the
ModelGateway still redacts, versions, prices and audits every call, and every
answer still goes through the parsers and the core validator.

    POST https://generativelanguage.googleapis.com/v1beta/models/<model>:generateContent
    header x-goog-api-key: <key>          (never in the URL, so it can't leak into logs)

Choices:
  * responseMimeType "application/json": the model must answer with JSON only
  * thinkingConfig.thinkingLevel "low" by default: these are short classification
    tasks, and thinking tokens count against maxOutputTokens
  * maxOutputTokens has a floor of MIN_OUTPUT_TOKENS so thinking can't cut an answer off
  * no temperature: newer Gemini models ignore it and warn
  * "too many requests" (429) and brief outages (500/503) are retried up to 3 times,
    waiting as long as Google asks (RetryInfo / Retry-After), at most 30 s. Free keys
    have a per-minute limit, and the demo sends six patients at once
  * standard library only (urllib), so no extra package to install

PHI (ADR-006): the Gemini Developer API (a Google AI Studio key) is for SYNTHETIC
data only. Real patient data needs Gemini on Vertex AI under a Google Cloud BAA,
which is a separate decision for the team (ADR-001 names the vendor after review).
"""

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from typing import Protocol
from urllib.parse import quote

from curaai.adapters.model.gateway import VendorReply

BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_MODEL = "gemini-3.8-flash"
MIN_OUTPUT_TOKENS = 2048


RETRYABLE = frozenset({429, 500, 503})   # too many requests, server error, overloaded
MAX_ATTEMPTS = 3
BACKOFF_S = (4.0, 10.0)                  # used when Google doesn't say how long to wait
MAX_WAIT_S = 30.0


class GeminiError(RuntimeError):
    """Any failure talking to Gemini. The gateway turns it into ModelUnavailable (AI off, chart pull continues)."""

    def __init__(self, message: str, status: int | None = None, retry_after_s: float | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.retry_after_s = retry_after_s


def retry_delay_s(error_body: Mapping, header_value: str | None) -> float | None:
    """Pure: how long Google asked us to wait, from RetryInfo ("17s") or the Retry-After header."""
    for detail in (error_body.get("error") or {}).get("details") or []:
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


# ---- pure ------------------------------------------------------------------------------------
def gemini_url(model: str, base_url: str = BASE_URL) -> str:
    return f"{base_url}/models/{quote(model, safe='.-_')}:generateContent"


def gemini_request(system: str, user: str, max_output_tokens: int, thinking_level: str | None = "low") -> dict:
    config: dict = {"responseMimeType": "application/json",
                    "maxOutputTokens": max(max_output_tokens, MIN_OUTPUT_TOKENS)}
    if thinking_level:
        config["thinkingConfig"] = {"thinkingLevel": thinking_level}
    return {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": config,
    }


def parse_gemini_response(response: Mapping, model: str) -> VendorReply:
    candidates = response.get("candidates") or []
    if not candidates:
        reason = (response.get("promptFeedback") or {}).get("blockReason", "no candidates")
        raise GeminiError(f"Gemini returned no answer ({reason})")
    candidate = candidates[0]
    parts = (candidate.get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts if isinstance(p, Mapping) and not p.get("thought"))
    if not text.strip():
        raise GeminiError(f"Gemini returned an empty answer (finishReason={candidate.get('finishReason')})")
    usage = response.get("usageMetadata") or {}
    output_tokens = int(usage.get("candidatesTokenCount", 0)) + int(usage.get("thoughtsTokenCount", 0))
    return VendorReply(text=text, input_tokens=int(usage.get("promptTokenCount", 0)),
                       output_tokens=output_tokens, model=response.get("modelVersion") or model)


# ---- humble -----------------------------------------------------------------------------------
class UrllibJsonPoster:
    """One HTTPS POST with the standard library. HTTP errors become GeminiError with Google's message."""

    def post_json(self, url: str, headers: Mapping[str, str], body: Mapping, timeout_s: float) -> Mapping:
        request = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                         headers={"Content-Type": "application/json", **headers})
        try:
            with urllib.request.urlopen(request, timeout=timeout_s) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body: Mapping = {}
            try:
                body = json.loads(exc.read().decode("utf-8"))
            except Exception:
                pass
            detail = (body.get("error") or {}).get("message", "") if isinstance(body, Mapping) else ""
            raise GeminiError(f"Gemini HTTP {exc.code}: {detail or exc.reason}", status=exc.code,
                              retry_after_s=retry_delay_s(body, exc.headers.get("Retry-After"))) from None
        except (urllib.error.URLError, TimeoutError) as exc:
            raise GeminiError(f"Gemini unreachable: {exc}") from None


class GeminiTransport:
    def __init__(self, api_key: str, model: str = DEFAULT_MODEL, *, thinking_level: str | None = "low",
                 poster: JsonPoster | None = None, base_url: str = BASE_URL, timeout_s: float = 30.0,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        if not api_key:
            raise ValueError("a Gemini API key is required")
        self._key = api_key
        self._model = model
        self._thinking = thinking_level
        self._poster = poster or UrllibJsonPoster()
        self._url = gemini_url(model, base_url)
        self._timeout = timeout_s
        self._sleep = sleep

    def __repr__(self) -> str:
        return f"GeminiTransport(model={self._model!r}, api_key=***)"

    def send(self, system: str, user: str, max_output_tokens: int) -> VendorReply:
        body = gemini_request(system, user, max_output_tokens, self._thinking)
        for attempt in range(MAX_ATTEMPTS):
            try:
                response = self._poster.post_json(self._url, {"x-goog-api-key": self._key}, body, self._timeout)
                return parse_gemini_response(response, self._model)
            except GeminiError as exc:
                if exc.status not in RETRYABLE or attempt == MAX_ATTEMPTS - 1:
                    raise
                self._sleep(min(exc.retry_after_s or BACKOFF_S[attempt], MAX_WAIT_S))
        raise GeminiError("unreachable")   # pragma: no cover
