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
  * timeouts, retries (429/500/503, honoring Google's RetryInfo) and the backup model
    (CURAAI_GEMINI_FALLBACK_MODEL) come from http_transport.py, shared with Groq.
    503 "model overloaded" is Google's side and often lasts minutes; free-tier limits are
    per model, so a backup model also helps with 429

PHI (ADR-006): the Gemini Developer API (a Google AI Studio key) is for SYNTHETIC
data only. Real patient data needs Gemini on Vertex AI under a Google Cloud BAA,
which is a separate decision for the team (ADR-001 names the vendor after review).
"""

import time
from collections.abc import Callable, Mapping
from urllib.parse import quote

from curaai.adapters.model.gateway import VendorReply
from curaai.adapters.model.http_transport import (  # noqa: F401  (re-exported for callers and tests)
    BACKOFF_S, DEFAULT_TIMEOUT_S, MAX_ATTEMPTS, MAX_WAIT_S, RETRYABLE, HttpModelTransport, JsonPoster,
    ModelHttpError, retry_delay_s,
)
from curaai.adapters.model.http_transport import UrllibJsonPoster as _UrllibJsonPoster

BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_MODEL = "gemini-3.8-flash"
MIN_OUTPUT_TOKENS = 2048


class GeminiError(ModelHttpError):
    """Any failure talking to Gemini. The gateway turns it into ModelUnavailable (AI off, chart pull continues)."""


class UrllibJsonPoster(_UrllibJsonPoster):
    def __init__(self) -> None:
        super().__init__("Gemini", GeminiError)


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
class GeminiTransport(HttpModelTransport):
    error = GeminiError

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL, *, thinking_level: str | None = "low",
                 poster: JsonPoster, base_url: str = BASE_URL, timeout_s: float = DEFAULT_TIMEOUT_S,
                 sleep: Callable[[float], None] = time.sleep, fallback_model: str | None = None) -> None:
        if not api_key:
            raise ValueError("a Gemini API key is required")
        super().__init__(model, fallback_model=fallback_model, poster=poster,
                         timeout_s=timeout_s, sleep=sleep)
        self._key = api_key
        self._thinking = thinking_level
        self._base_url = base_url

    def __repr__(self) -> str:
        return f"GeminiTransport(model={self._model!r}, fallback={self._fallback!r}, api_key=***)"

    def _request(self, model: str, system: str, user: str, max_output_tokens: int) -> tuple[str, dict, dict]:
        return (gemini_url(model, self._base_url), {"x-goog-api-key": self._key},
                gemini_request(system, user, max_output_tokens, self._thinking))

    def _parse(self, response: Mapping, model: str) -> VendorReply:
        return parse_gemini_response(response, model)


def gemini_model_info(api_key: str, model: str, getter: object, timeout_s: float = 15.0,
                      base_url: str = BASE_URL) -> Mapping:
    """Fast check used by `python -m curaai.app.check`: ask Google for the model's details.

    No text is generated, so Google answers in about a second. If even this times out, the
    network (not Gemini) is the problem. A 404 means the model name is wrong; 400/403 the key.
    """
    url = f"{base_url}/models/{quote(model, safe='.-_')}"
    return getter.get_json(url, {"x-goog-api-key": api_key}, timeout_s)


def gemini_text_models(api_key: str, getter: object, timeout_s: float = 15.0, base_url: str = BASE_URL) -> list[str]:
    """Names of the models this key can generate text with (for the setup check's backup-model hint)."""
    reply = getter.get_json(f"{base_url}/models?pageSize=1000", {"x-goog-api-key": api_key}, timeout_s)
    names = []
    for m in reply.get("models") or []:
        if isinstance(m, Mapping) and "generateContent" in (m.get("supportedGenerationMethods") or []):
            names.append(str(m.get("name", "")).removeprefix("models/"))
    return sorted(n for n in names if n)
