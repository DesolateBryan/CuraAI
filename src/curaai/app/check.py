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
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from curaai.adapters.model.gemini_transport import GeminiError, GeminiTransport
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
               gemini_poster: object | None = None) -> list[Check]:
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
        try:
            reply = GeminiTransport(config.gemini_api_key, config.gemini_model,
                                    thinking_level=config.gemini_thinking_level or None,
                                    poster=gemini_poster, timeout_s=20).send(
                'Reply with exactly this JSON: {"ok": true}', '{"ping": true}', 20)
            checks.append(Check(OK, "Gemini test call", f"answered ({reply.model})"))
        except GeminiError as exc:
            hint = ("check your internet connection" if "unreachable" in str(exc)
                    else "check the key at https://aistudio.google.com/apikey")
            checks.append(Check(FAIL, "Gemini test call", f"{exc}. Next step: {hint}"))
    elif config.model_backend == "bedrock":
        if importlib.util.find_spec("boto3") is not None:   # look, don't import: only main.py imports SDKs
            checks.append(Check(OK, "Bedrock", "boto3 installed; AWS credentials come from your AWS config"))
        else:
            checks.append(Check(FAIL, "Bedrock", 'boto3 not installed: pip install -e ".[web,bedrock]"'))
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
