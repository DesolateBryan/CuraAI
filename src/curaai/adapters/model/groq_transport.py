"""GroqTransport: VendorTransport over Groq's OpenAI-compatible chat completions API.

CURAAI_MODEL_BACKEND=groq. Same slot as Gemini, Bedrock and the local reader: the
ModelGateway still redacts, versions, prices and audits every call, and every answer
still goes through the parsers and the core validator.

    POST https://api.groq.com/openai/v1/chat/completions
    header Authorization: Bearer <key>     (never in the URL, so it can't leak into logs)

Choices:
  * response_format json_object: the answer must be valid JSON. Groq requires the prompt
    to mention JSON; every CuraAI prompt says "Reply with ONE JSON object"
  * default model openai/gpt-oss-20b: fast, free tier, JSON mode (CURAAI_GROQ_MODEL)
  * reasoning_effort "low" by default: these are short classification tasks, and reasoning
    tokens count against max_completion_tokens and the per-minute token limit.
    "" leaves the model default. Accepted values differ per model (gpt-oss: low/medium/high)
  * include_reasoning false on gpt-oss models: only the answer comes back
  * max_completion_tokens has a floor of MIN_OUTPUT_TOKENS so reasoning can't cut an answer off
  * timeouts, retries (429 honoring retry-after, 500/503) and the backup model
    (CURAAI_GROQ_FALLBACK_MODEL) come from http_transport.py, shared with Gemini
  * free-tier limits (Groq console, per model): about 30 requests/minute, 8K tokens/minute,
    200K tokens/day. The tokens-per-minute limit is the one the demo hits first, which is
    why quota.py paces requests and sends only message reading to the model by default

PHI (ADR-006): a Groq console key is for SYNTHETIC data only. Real patient data needs a
vendor agreement (BAA) first; that is a team decision recorded in ADR-001.
"""

import time
from collections.abc import Callable, Mapping

from curaai.adapters.model.gateway import VendorReply
from curaai.adapters.model.http_transport import (
    DEFAULT_TIMEOUT_S, HttpModelTransport, JsonPoster, ModelHttpError, UrllibJsonPoster,
)

BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_MODEL = "openai/gpt-oss-20b"
MIN_OUTPUT_TOKENS = 1024


class GroqError(ModelHttpError):
    """Any failure talking to Groq. The gateway turns it into ModelUnavailable (AI off, chart pull continues)."""


def groq_poster() -> UrllibJsonPoster:
    return UrllibJsonPoster("Groq", GroqError)


# ---- pure ------------------------------------------------------------------------------------
def groq_request(model: str, system: str, user: str, max_output_tokens: int,
                 reasoning_effort: str | None = "low") -> dict:
    body: dict = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "response_format": {"type": "json_object"},
        "max_completion_tokens": max(max_output_tokens, MIN_OUTPUT_TOKENS),
    }
    if reasoning_effort:
        body["reasoning_effort"] = reasoning_effort
    if model.startswith("openai/gpt-oss"):
        body["include_reasoning"] = False
    return body


def parse_groq_response(response: Mapping, model: str) -> VendorReply:
    choices = response.get("choices") or []
    if not choices:
        raise GroqError("Groq returned no answer (no choices)")
    choice = choices[0] if isinstance(choices[0], Mapping) else {}
    text = (choice.get("message") or {}).get("content") or ""
    if not isinstance(text, str) or not text.strip():
        raise GroqError(f"Groq returned an empty answer (finish_reason={choice.get('finish_reason')})")
    usage = response.get("usage") or {}
    return VendorReply(text=text, input_tokens=int(usage.get("prompt_tokens", 0) or 0),
                       output_tokens=int(usage.get("completion_tokens", 0) or 0),
                       model=response.get("model") or model)


# ---- humble -----------------------------------------------------------------------------------
class GroqTransport(HttpModelTransport):
    error = GroqError

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL, *, reasoning_effort: str | None = "low",
                 poster: JsonPoster, base_url: str = BASE_URL, timeout_s: float = DEFAULT_TIMEOUT_S,
                 sleep: Callable[[float], None] = time.sleep, fallback_model: str | None = None) -> None:
        if not api_key:
            raise ValueError("a Groq API key is required")
        super().__init__(model, fallback_model=fallback_model, poster=poster,
                         timeout_s=timeout_s, sleep=sleep)
        self._key = api_key
        self._effort = reasoning_effort
        self._url = f"{base_url}/chat/completions"

    def __repr__(self) -> str:
        return f"GroqTransport(model={self._model!r}, fallback={self._fallback!r}, api_key=***)"

    def _request(self, model: str, system: str, user: str, max_output_tokens: int) -> tuple[str, dict, dict]:
        return (self._url, {"Authorization": f"Bearer {self._key}"},
                groq_request(model, system, user, max_output_tokens, self._effort))

    def _parse(self, response: Mapping, model: str) -> VendorReply:
        return parse_groq_response(response, model)


def groq_models(api_key: str, getter: object, timeout_s: float = 15.0, base_url: str = BASE_URL) -> list[str]:
    """Fast check for `python -m curaai.app.check`: the model ids this key can use (no text generated).
    A 401 means the key was refused; a timeout means the network can't reach Groq."""
    reply = getter.get_json(f"{base_url}/models", {"Authorization": f"Bearer {api_key}"}, timeout_s)
    return sorted(str(m.get("id")) for m in reply.get("data") or [] if isinstance(m, Mapping) and m.get("id"))
