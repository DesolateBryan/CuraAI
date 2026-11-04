"""Setup checker. Run from the CuraAI folder before starting the demo:

    python -m curaai.app.check

It reads the same settings the server would (.env, then real environment variables)
and reports, in plain words:
  * whether .env was found and what it selects (API keys are never printed)
  * whether the settings are valid
  * whether port 8000 (or CURAAI_PORT) is free, or an old CuraAI server is still running
  * whether the MockChart page was found
  * for Gemini: one tiny test call, so a wrong or expired key shows up here, not mid-demo

Part of Ring 4 (it builds a transport the same way main.py does). Exit code 1 if anything failed.
"""

import importlib.util
import os
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from curaai.adapters.model.gemini_transport import (
    GeminiError, GeminiTransport, UrllibJsonPoster, gemini_model_info,
    gemini_text_models,
)
from curaai.adapters.model.groq_transport import GroqError, GroqTransport, groq_models, groq_poster
from curaai.app.main import Config, load_env_file, port_in_use

OK, WARN, FAIL = "ok", "warn", "fail"


@dataclass(frozen=True)
class Check:
    status: str
    name: str
    detail: str


def mask(secret: str) -> str:
    return f"set (ends in ...{secret[-4:]})" if len(secret) >= 8 else ("set" if secret else "NOT SET")


def run_checks(env_file: Path, environ: Mapping[str, str], *, cwd: Path,
               port_probe: Callable[[str, int], bool] = port_in_use,
               gemini_poster: object | None = None,
               groq_http: object | None = None,
               clock: Callable[[], float] = time.monotonic) -> list[Check]:
    checks: list[Check] = []
    file_values = load_env_file(env_file)
    if env_file.is_file():
        checks.append(Check(OK, ".env file", f"found at {env_file}"))
    else:
        checks.append(Check(WARN, ".env file", f"not found at {env_file}; using defaults. "
                                               "Copy .env.example to .env to change settings."))
    overridden = sorted(k for k in file_values if k in environ and environ[k] != file_values[k])
    if overridden:
        checks.append(Check(WARN, "environment", "these are set in your terminal and override .env: "
                                                 + ", ".join(overridden)))

    try:
        config = Config.from_env({**file_values, **environ})
    except ValueError as exc:
        checks.append(Check(FAIL, "settings", str(exc)))
        return checks
    checks.append(Check(OK, "settings", "valid"))

    model = {"gemini": f"Google Gemini ({config.gemini_model}), key {mask(config.gemini_api_key)}",
             "bedrock": f"AWS Bedrock ({config.bedrock_model_id})",
             "groq": f"Groq ({config.groq_model}), key {mask(config.groq_api_key)}",
             "local": "local rule-based reader (no AI account needed)",
             "none": "none: no reader, chart pull from the message date only"}[config.model_backend]
    checks.append(Check(OK, "model backend", model))
    checks.append(Check(OK, "clock", f"frozen at {config.clock_now}" if config.clock_now else "real time"))

    page = Path(config.mockchart_page) if config.mockchart_page else next(iter(sorted(cwd.glob("MockChart*.html"))), None)
    if page and page.is_file():
        checks.append(Check(OK, "MockChart page", page.name))
    else:
        checks.append(Check(FAIL, "MockChart page", "not found. Run from the CuraAI folder, "
                                                    "or set CURAAI_MOCKCHART_PAGE in .env."))

    if port_probe(config.host, config.port):
        checks.append(Check(WARN, "port", f"something is already running on {config.host}:{config.port}. "
                                          "It may be an old CuraAI server: close that PowerShell window "
                                          "(or press Ctrl+C in it) before starting a new one."))
    else:
        checks.append(Check(OK, "port", f"{config.host}:{config.port} is free"))

    if config.model_backend == "gemini":
        checks.extend(gemini_checks(config, gemini_poster or UrllibJsonPoster(), clock))
    elif config.model_backend == "groq":
        checks.extend(groq_checks(config, groq_http or groq_poster(), clock))
    elif config.model_backend == "bedrock":
        if importlib.util.find_spec("boto3") is not None:   # look, don't import: only main.py imports SDKs
            checks.append(Check(OK, "Bedrock", "boto3 installed; AWS credentials come from your AWS config"))
        else:
            checks.append(Check(FAIL, "Bedrock", 'boto3 not installed: pip install -e ".[web,bedrock]"'))
    return checks


def gemini_checks(config: Config, poster: object, clock: Callable[[], float]) -> list[Check]:
    """Two Gemini tests, fast one first, so the failure says WHICH thing is wrong.

    1. Model lookup (no text generated, normally ~1 s): proves the network reaches Google,
       the key is accepted and the model name exists.
    2. A tiny real answer, with the same timeout the demo uses: proves Gemini answers in time.
    """
    key, model = config.gemini_api_key, config.gemini_model
    started = clock()
    try:
        gemini_model_info(key, model, poster, timeout_s=15)
        checks = [Check(OK, "Gemini connection", f"Google reached, key accepted, model {model} exists "
                                                 f"({clock() - started:.1f} s)")]
    except GeminiError as exc:
        if exc.timed_out or exc.status is None:
            hint = ("this computer can't reach Google's API. Try another network (school and work Wi-Fi "
                    "often block it; a phone hotspot is a quick test), and check any VPN or firewall")
        elif exc.status == 404:
            hint = "the model name is wrong. Remove CURAAI_GEMINI_MODEL from .env, or set it to a model listed in AI Studio"
        elif exc.status in (400, 401, 403):
            hint = "the key was refused. Make a new one at https://aistudio.google.com/apikey and paste it into .env"
        else:
            hint = "Google returned an error; try again in a minute"
        return [Check(FAIL, "Gemini connection", f"{exc}. Next step: {hint}")]
    checks.append(backup_model_check(config, poster))

    started = clock()
    try:
        reply = GeminiTransport(key, model, thinking_level=config.gemini_thinking_level or None, poster=poster,
                                timeout_s=config.gemini_timeout_s).send(
            'Reply with exactly this JSON: {"ok": true}', '{"ping": true}', 20)
        took = clock() - started
        status = OK if took < config.gemini_timeout_s / 2 else WARN
        detail = f"answered in {took:.1f} s ({reply.model})"
        if status == WARN:
            detail += (f". That is slow: the demo waits {config.gemini_timeout_s:.0f} s per call. Raise "
                       "CURAAI_GEMINI_TIMEOUT_S or use a lighter model (CURAAI_GEMINI_MODEL)")
        checks.append(Check(status, "Gemini test call", detail))
    except GeminiError as exc:
        if exc.timed_out:
            hint = (f"Google is reachable but the model did not answer within {config.gemini_timeout_s:.0f} s. "
                    "Set CURAAI_GEMINI_TIMEOUT_S=120 in .env, or try a lighter model with CURAAI_GEMINI_MODEL")
        elif exc.status in (500, 503):
            hint = ("Google's servers are overloaded for this model right now (not your key or code). "
                    "Wait a few minutes, or set CURAAI_GEMINI_FALLBACK_MODEL in .env so CuraAI switches "
                    "to a second model when this happens")
        elif exc.status == 429:
            hint = "the key's per-minute or daily limit is used up; wait a minute (or until tomorrow) and retry"
        else:
            hint = "see the message above"
        checks.append(Check(FAIL, "Gemini test call", f"{exc}. Next step: {hint}"))
    return checks


def backup_model_check(config: Config, poster: object) -> Check:
    """Is a backup model set, and does it exist? If none is set, suggest names this key can use."""
    key, backup = config.gemini_api_key, config.gemini_fallback_model
    if backup:
        try:
            gemini_model_info(key, backup, poster, timeout_s=15)
            return Check(OK, "Gemini backup model", f"{backup} (used if {config.gemini_model} is overloaded)")
        except GeminiError as exc:
            return Check(FAIL, "Gemini backup model", f"{backup}: {exc}. Next step: pick a name from "
                                                      "the list in AI Studio, or remove CURAAI_GEMINI_FALLBACK_MODEL")
    try:
        names = [n for n in gemini_text_models(key, poster) if "flash" in n and n != config.gemini_model]
    except GeminiError:
        names = []
    suggestion = f" Models your key can use: {', '.join(names[:6])}." if names else ""
    return Check(WARN, "Gemini backup model", "none set, so if Google says the model is overloaded (HTTP 503) "
                 f"the case runs without AI. Add CURAAI_GEMINI_FALLBACK_MODEL=<name> to .env.{suggestion}")


def groq_checks(config: Config, poster: object, clock: Callable[[], float]) -> list[Check]:
    """Same two steps as Gemini: a fast model list (network, key, model name), then a timed tiny answer."""
    key, model = config.groq_api_key, config.groq_model
    started = clock()
    try:
        names = groq_models(key, poster)
    except GroqError as exc:
        if exc.timed_out or exc.status is None:
            hint = ("this computer can't reach Groq. Try another network (school and work Wi-Fi often "
                    "block it; a phone hotspot is a quick test), and check any VPN or firewall")
        elif exc.status in (401, 403):
            hint = "the key was refused. Make a new one at https://console.groq.com/keys and paste it into .env"
        else:
            hint = "Groq returned an error; try again in a minute"
        return [Check(FAIL, "Groq connection", f"{exc}. Next step: {hint}")]
    took = clock() - started
    missing = [m for m in (model, config.groq_fallback_model) if m and m not in names]
    if missing:
        chat = [n for n in names if not n.startswith(("whisper", "canopylabs/", "meta-llama/llama-prompt-guard"))]
        return [Check(FAIL, "Groq connection", f"key accepted, but {', '.join(missing)} is not a model this key can "
                      f"use. Next step: set CURAAI_GROQ_MODEL (or CURAAI_GROQ_FALLBACK_MODEL) to one of: "
                      f"{', '.join(chat[:8])}")]
    checks = [Check(OK, "Groq connection", f"Groq reached, key accepted, model {model} available ({took:.1f} s)")]

    started = clock()
    try:
        reply = GroqTransport(key, model, reasoning_effort=config.groq_reasoning_effort or None, poster=poster,
                              timeout_s=config.groq_timeout_s).send(
            'Reply with exactly this JSON: {"ok": true}', '{"ping": true}', 20)
        took = clock() - started
        status = OK if took < config.groq_timeout_s / 2 else WARN
        detail = f"answered in {took:.1f} s ({reply.model}, {reply.input_tokens + reply.output_tokens} tokens)"
        if status == WARN:
            detail += f". That is slow: the demo waits {config.groq_timeout_s:.0f} s per call"
        checks.append(Check(status, "Groq test call", detail))
    except GroqError as exc:
        if exc.status == 429:
            hint = ("the key's per-minute or daily limit is used up. Wait a minute; if it says tokens per day, "
                    "it resets tomorrow. Meanwhile CURAAI_MODEL_BACKEND=local runs the demo without AI")
        elif exc.status == 400:
            hint = ("Groq refused a setting. If you changed CURAAI_GROQ_MODEL, also set "
                    "CURAAI_GROQ_REASONING_EFFORT= (empty) since not every model accepts it")
        elif exc.timed_out:
            hint = f"Groq is reachable but did not answer within {config.groq_timeout_s:.0f} s. Try again, or raise CURAAI_GROQ_TIMEOUT_S"
        else:
            hint = "see the message above"
        checks.append(Check(FAIL, "Groq test call", f"{exc}. Next step: {hint}"))
    return checks


def main() -> int:
    cwd = Path.cwd()
    checks = run_checks(cwd / ".env", os.environ, cwd=cwd)
    marks = {OK: "[ OK ]", WARN: "[WARN]", FAIL: "[FAIL]"}
    print("CuraAI setup check\n")
    for c in checks:
        print(f"{marks[c.status]} {c.name}: {c.detail}")
    failed = any(c.status == FAIL for c in checks)
    print("\n" + ("Fix the [FAIL] lines, then run this again." if failed else
                  "Ready. Start the demo with:  python -m curaai.app.main"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
