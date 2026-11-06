"""Composition root (ADR-015). The ONLY module that imports every ring and the vendor SDK.

    Config.from_env()   read settings once (no secrets in the repo, ADR-006)
    build_container()   create and wire every object; one `if` per adapter choice
    build_app()         hand the controller to the FastAPI routes
    main()              start Uvicorn

Nothing imports this module except the app-ring tools beside it (check.py, runlog.py), so
the Dependency Rule still points inward. tests/compose.py is the second composition root;
it wires fakes into the same use cases.

Main is honest (CS302 M3): every object that crosses a ring or the network is created
here, including the HTTP clients the model transports use. Governance configuration is
owned here too, read once from the environment:
    case caps and dollar cap      CURAAI_MAX_MODEL_CALLS / _MAX_LOOKUPS / _MAX_FOLLOW_UPS / _MAX_CASE_COST_USD
    daily budget                  CURAAI_DAILY_BUDGET_USD
    follow-up timeout             CURAAI_FOLLOW_UP_TIMEOUT_HOURS
    HITL approvers                CURAAI_HITL_APPROVERS (who may approve a reply to the patient)
    AI request pacing and scope   CURAAI_AI_MAX_PER_MINUTE, CURAAI_AI_USE_FOR
    audit log location            CURAAI_AUDIT_LOG_PATH (the run log is read from it)

Run the demo:
    pip install -e ".[web]"
    python -m curaai.app.main            # then open http://127.0.0.1:8000/mockchart
"""

import os
import socket
import sys
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from curaai.adapters.clock.fixed_clock import FixedClock
from curaai.adapters.clock.system_clock import SystemClock
from curaai.adapters.drug import MockDrugAdapter, OpenFdaAdapter, UrllibHttpClient, load_mockchart_drugs
from curaai.adapters.ehr import InMemoryBundleSource, MockEpicAdapter
from curaai.adapters.ehr.mock_epic_messaging import (
    InMemoryOutbox, MockEpicMessagingAdapter, MockEpicPhysicianReplyAdapter,
)
from curaai.adapters.model import (
    BedrockConverseTransport, CostGuard, GatewayExtractSymptoms, GatewayMatchFlags, GatewayPickRelevantItems,
    GatewaySelectFollowUp, ModelGateway, ModelPricing,
)
from curaai.adapters.model.gemini_transport import DEFAULT_MODEL as DEFAULT_GEMINI_MODEL
from curaai.adapters.model.gemini_transport import DEFAULT_TIMEOUT_S as DEFAULT_GEMINI_TIMEOUT_S
from curaai.adapters.model.gemini_transport import GeminiTransport
from curaai.adapters.model.gemini_transport import UrllibJsonPoster as GeminiHttp
from curaai.adapters.model.groq_transport import DEFAULT_MODEL as DEFAULT_GROQ_MODEL
from curaai.adapters.model.groq_transport import GroqTransport, groq_poster as groq_http
from curaai.adapters.model.local_rules import LocalRulesTransport
from curaai.adapters.model.no_model_transport import NoModelTransport
from curaai.adapters.model.quota import Pacer, PortRouter, ReplyCache
from curaai.adapters.model.gateway import VendorTransport
from curaai.adapters.observability import (
    LoggedExtractSymptoms, LoggedMatchFlags, LoggedPickRelevantItems, LoggedSelectFollowUp, format_run_log,
)
from curaai.adapters.persistence import InMemoryConversationStore, InMemoryReviewGates, JsonlAuditLog, read_audit_log
from curaai.adapters.presenters import (
    InMemoryReviewSink, ReviewPresenter, gate_view_to_dict, present_gate, render_gate_html, render_review_html,
    review_view_to_dict,
)
from curaai.adapters.web.controller import WebController
from curaai.application.ports.audit_log_port import AuditLogPort
from curaai.application.ports.clock_port import ClockPort
from curaai.application.use_cases import (
    AssembleReviewPacket, PipelineTrigger, PrefetchHistory, RecordPhysicianDecision, RequestFollowUp,
    ScreenSickMessage,
)
from curaai.application.validation import ModelOutputValidator
from curaai.domain.case_budget import CaseLimits
from curaai.domain.follow_up_catalog import DEFAULT_FOLLOW_UP_CATALOG
from curaai.domain.follow_up_timeout import FollowUpTimeout
from curaai.domain.symptom_catalog import DEFAULT_SYMPTOM_CATALOG

BRIDGE_JS = Path(__file__).resolve().parents[1] / "adapters" / "web" / "static" / "curaai-bridge.js"

CHOICES = {
    "ehr_adapter": ("mock_epic",),                 # a real Epic adapter needs SMART on FHIR (deferred, ADR-017)
    "drug_adapter": ("mock", "openfda"),
    "model_backend": ("local", "groq", "gemini", "bedrock", "none"),
    "ai_use_for": ("reading", "all"),           # reading = only the patient's message goes to Groq/Gemini
}


# ---- configuration --------------------------------------------------------------------------
@dataclass(frozen=True)
class Config:
    ehr_adapter: str = "mock_epic"
    drug_adapter: str = "mock"
    model_backend: str = "local"                  # rule-based demo reader; "bedrock" for a real model
    bedrock_model_id: str = ""
    gemini_api_key: str = field(default="", repr=False)   # from .env or the environment; never commit or print it
    gemini_model: str = DEFAULT_GEMINI_MODEL
    gemini_thinking_level: str = "low"             # "" to leave the model default
    gemini_timeout_s: float = DEFAULT_GEMINI_TIMEOUT_S
    gemini_fallback_model: str = ""                # backup model when the main one is overloaded (503)
    groq_api_key: str = field(default="", repr=False)     # from .env or the environment; never commit or print it
    groq_model: str = DEFAULT_GROQ_MODEL
    groq_reasoning_effort: str = "low"             # "" to leave the model default
    groq_timeout_s: float = DEFAULT_GEMINI_TIMEOUT_S
    groq_fallback_model: str = ""                  # backup model when the main one is busy
    ai_use_for: str = "reading"                    # Groq/Gemini: "all" = every model step (about 2x the calls)
    ai_max_per_minute: float = 8.0                 # Groq/Gemini request spacing for free keys; 0 = no limit
    aws_region: str = "us-east-1"
    mock_epic_api_key: str = "mock-curaai-key-0000"
    audit_log_path: str = "./audit.jsonl"
    clinic_tz: str = "America/New_York"
    clock_now: str = ""                            # ISO timestamp; freezes the clock for MockChart demos
    mockchart_page: str = ""                       # path; default = first MockChart*.html in the working dir
    daily_budget_usd: Decimal = Decimal("5.00")
    price_in_per_mtok: Decimal = Decimal("3.00")   # placeholder until the vendor quote
    price_out_per_mtok: Decimal = Decimal("15.00")
    host: str = "127.0.0.1"
    port: int = 8000
    sweep_seconds: float = 60.0
    # governance: owned by Main (Governance ADR 3 HITL, ADR 5 cost control; ADR-011 caps)
    max_model_calls: int = 12                      # team decision 2026-10-26 (ADR-011 proposed 6)
    max_lookups: int = 5
    max_follow_ups: int = 2
    max_case_cost_usd: Decimal = Decimal("0.25")
    follow_up_timeout_hours: float = 24.0
    hitl_approvers: str = "dr-demo"                # comma-separated physician ids allowed to approve a reply

    @property
    def approvers(self) -> tuple[str, ...]:
        return tuple(a.strip() for a in self.hitl_approvers.split(",") if a.strip())

    def case_limits(self) -> CaseLimits:
        return CaseLimits(max_model_calls=self.max_model_calls, max_lookups=self.max_lookups,
                          max_follow_ups=self.max_follow_ups, max_cost_usd=self.max_case_cost_usd)

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "Config":
        def get(name: str, default: str) -> str:
            return env.get(f"CURAAI_{name.upper()}", default).strip()

        d = cls()
        try:
            config = cls(
                ehr_adapter=get("ehr_adapter", d.ehr_adapter), drug_adapter=get("drug_adapter", d.drug_adapter),
                model_backend=get("model_backend", d.model_backend),
                bedrock_model_id=get("bedrock_model_id", ""), aws_region=get("aws_region", d.aws_region),
                gemini_api_key=get("gemini_api_key", "") or env.get("GEMINI_API_KEY", "").strip(),
                gemini_model=get("gemini_model", d.gemini_model),
                gemini_thinking_level=get("gemini_thinking_level", d.gemini_thinking_level),
                gemini_timeout_s=float(get("gemini_timeout_s", str(d.gemini_timeout_s))),
                gemini_fallback_model=get("gemini_fallback_model", d.gemini_fallback_model),
                groq_api_key=get("groq_api_key", "") or env.get("GROQ_API_KEY", "").strip(),
                groq_model=get("groq_model", d.groq_model),
                groq_reasoning_effort=get("groq_reasoning_effort", d.groq_reasoning_effort),
                groq_timeout_s=float(get("groq_timeout_s", str(d.groq_timeout_s))),
                groq_fallback_model=get("groq_fallback_model", d.groq_fallback_model),
                ai_use_for=get("ai_use_for", d.ai_use_for).lower(),
                ai_max_per_minute=float(get("ai_max_per_minute", str(d.ai_max_per_minute))),
                mock_epic_api_key=get("mock_epic_api_key", d.mock_epic_api_key),
                audit_log_path=get("audit_log_path", d.audit_log_path), clinic_tz=get("clinic_tz", d.clinic_tz),
                clock_now=get("clock_now", ""), mockchart_page=get("mockchart_page", ""),
                daily_budget_usd=Decimal(get("daily_budget_usd", str(d.daily_budget_usd))),
                price_in_per_mtok=Decimal(get("price_in_per_mtok", str(d.price_in_per_mtok))),
                price_out_per_mtok=Decimal(get("price_out_per_mtok", str(d.price_out_per_mtok))),
                host=get("host", d.host), port=int(get("port", str(d.port))),
                sweep_seconds=float(get("sweep_seconds", str(d.sweep_seconds))),
                max_model_calls=int(get("max_model_calls", str(d.max_model_calls))),
                max_lookups=int(get("max_lookups", str(d.max_lookups))),
                max_follow_ups=int(get("max_follow_ups", str(d.max_follow_ups))),
                max_case_cost_usd=Decimal(get("max_case_cost_usd", str(d.max_case_cost_usd))),
                follow_up_timeout_hours=float(get("follow_up_timeout_hours", str(d.follow_up_timeout_hours))),
                hitl_approvers=get("hitl_approvers", d.hitl_approvers),
            )
        except (ArithmeticError, ValueError) as exc:
            raise ValueError(f"invalid CuraAI setting: {exc}") from exc
        config.validate()
        return config

    def validate(self) -> None:
        for name, allowed in CHOICES.items():
            if getattr(self, name) not in allowed:
                raise ValueError(f"CURAAI_{name.upper()} must be one of {', '.join(allowed)}")
        if self.model_backend == "bedrock" and not self.bedrock_model_id:
            raise ValueError("CURAAI_BEDROCK_MODEL_ID is required when CURAAI_MODEL_BACKEND=bedrock")
        if self.model_backend == "gemini" and not self.gemini_api_key:
            raise ValueError("CURAAI_GEMINI_API_KEY is required when CURAAI_MODEL_BACKEND=gemini "
                             "(get a free key at https://aistudio.google.com/apikey)")
        if self.model_backend == "groq" and not self.groq_api_key:
            raise ValueError("CURAAI_GROQ_API_KEY is required when CURAAI_MODEL_BACKEND=groq "
                             "(get a free key at https://console.groq.com/keys and paste it into .env, "
                             "or set CURAAI_MODEL_BACKEND=local to run the demo without an AI key)")
        if self.ai_max_per_minute < 0:
            raise ValueError("CURAAI_AI_MAX_PER_MINUTE must be 0 (no limit) or more")
        if not self.mock_epic_api_key:
            raise ValueError("CURAAI_MOCK_EPIC_API_KEY is required")
        if not self.approvers:
            raise ValueError("CURAAI_HITL_APPROVERS needs at least one physician id (who may approve replies)")
        if self.follow_up_timeout_hours <= 0:
            raise ValueError("CURAAI_FOLLOW_UP_TIMEOUT_HOURS must be more than 0")
        self.case_limits()                             # raises if a cap is negative


def load_env_file(path: str | Path) -> dict[str, str]:
    """Minimal .env reader (KEY=VALUE lines, # comments). Real environment variables win."""
    values: dict[str, str] = {}
    p = Path(path)
    if p.is_file():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.split(" #", 1)[0].strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip('"').strip("'")
    return values


# ---- wiring -------------------------------------------------------------------------------------
@dataclass
class Container:
    controller: WebController
    trigger: PipelineTrigger
    audit_log: AuditLogPort
    clock: ClockPort
    bundles: InMemoryBundleSource
    outbox: InMemoryOutbox
    reviews: InMemoryReviewSink
    page_html: str | None
    decisions: RecordPhysicianDecision
    gates: InMemoryReviewGates


def build_clock(config: Config) -> ClockPort:
    try:
        tz = ZoneInfo(config.clinic_tz)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"unknown timezone {config.clinic_tz!r} (on Windows: pip install tzdata)") from exc
    if config.clock_now:
        now = datetime.fromisoformat(config.clock_now.replace("Z", "+00:00"))
        return FixedClock(now if now.tzinfo else now.replace(tzinfo=tz))
    return SystemClock(tz)


def build_http_poster(config: Config) -> object | None:
    """The HTTPS client a hosted model backend uses (created here, not inside the transport)."""
    return {"gemini": GeminiHttp, "groq": groq_http}.get(config.model_backend, lambda: None)()


def build_vendor_transport(config: Config, *, poster: object | None = None, bedrock_client: object | None = None,
                           sleep: Callable[[float], None] = time.sleep) -> VendorTransport:
    """One `if` per model backend. Used by build_container and by the setup check."""
    if config.model_backend == "bedrock":
        if bedrock_client is None:
            import boto3                                   # the only vendor SDK import in the codebase
            bedrock_client = boto3.client("bedrock-runtime", region_name=config.aws_region)
        return BedrockConverseTransport(bedrock_client, config.bedrock_model_id)
    if config.model_backend == "gemini":
        return GeminiTransport(config.gemini_api_key, config.gemini_model,
                               thinking_level=config.gemini_thinking_level or None,
                               poster=poster or build_http_poster(config), timeout_s=config.gemini_timeout_s,
                               fallback_model=config.gemini_fallback_model or None, sleep=sleep)
    if config.model_backend == "groq":
        return GroqTransport(config.groq_api_key, config.groq_model,
                             reasoning_effort=config.groq_reasoning_effort or None,
                             poster=poster or build_http_poster(config), timeout_s=config.groq_timeout_s,
                             fallback_model=config.groq_fallback_model or None, sleep=sleep)
    if config.model_backend == "local":
        return LocalRulesTransport()                       # demo reader, no network, no cost
    return NoModelTransport()                              # ADR-011 fallback only


def build_container(config: Config, *, bedrock_client: object | None = None,
                    gemini_poster: object | None = None,
                    groq_poster: object | None = None,
                    model_sleep: Callable[[float], None] = time.sleep) -> Container:
    clock = build_clock(config)
    audit = JsonlAuditLog(config.audit_log_path)
    limits = config.case_limits()                          # governance config: from Main, never a default
    timeout = FollowUpTimeout(timedelta(hours=config.follow_up_timeout_hours))

    # EHR (read-only) and patient messaging
    bundles = InMemoryBundleSource()
    ehr = MockEpicAdapter(bundles, api_key=config.mock_epic_api_key)
    outbox = InMemoryOutbox()
    messaging = MockEpicMessagingAdapter(outbox)           # catalog questions only (the AI pipeline's port)
    replies = MockEpicPhysicianReplyAdapter(outbox)        # physician-approved replies (HITL use case only)

    # drug database (read-only)
    if config.drug_adapter == "openfda":
        drug_db = OpenFdaAdapter(UrllibHttpClient())
    else:
        drug_db = MockDrugAdapter(load_mockchart_drugs())

    # model: HTTP client -> transport -> pacing/cache -> gateway -> cost guard -> four logged adapters
    transport = build_vendor_transport(config, poster=gemini_poster or groq_poster, bedrock_client=bedrock_client,
                                       sleep=model_sleep)
    pricing = ModelPricing(config.price_in_per_mtok, config.price_out_per_mtok)
    hosted = config.model_backend in ("groq", "gemini")     # free keys: per-minute and daily limits
    if hosted:                                             # quota.py: space requests, never pay twice
        if config.ai_max_per_minute:
            transport = Pacer(transport, config.ai_max_per_minute, sleep=model_sleep)
        transport = ReplyCache(transport)
    gateway = ModelGateway(transport, pricing, audit, clock)
    if hosted and config.ai_use_for == "reading":
        local = ModelGateway(LocalRulesTransport(), pricing, audit, clock)
        gateway = PortRouter(local, {"extract_symptoms": gateway})   # only the patient's message goes out
    client = CostGuard(gateway, limits, config.daily_budget_usd, audit, clock)
    extractor = LoggedExtractSymptoms(GatewayExtractSymptoms(client), audit, clock)
    selector = LoggedSelectFollowUp(GatewaySelectFollowUp(client), audit, clock)
    picker = LoggedPickRelevantItems(GatewayPickRelevantItems(client), audit, clock)
    flagger = LoggedMatchFlags(GatewayMatchFlags(client), audit, clock)

    # review output, HITL gate and state
    reviews = InMemoryReviewSink()
    presenter = ReviewPresenter(reviews)
    store = InMemoryConversationStore()
    gates = InMemoryReviewGates()

    # use cases (Ring 2) receive only ports
    validator = ModelOutputValidator(DEFAULT_SYMPTOM_CATALOG)
    screen = ScreenSickMessage(extractor, validator, DEFAULT_SYMPTOM_CATALOG, audit, clock)
    follow_up = RequestFollowUp(selector, validator, DEFAULT_FOLLOW_UP_CATALOG, messaging, audit, clock)
    prefetch = PrefetchHistory(ehr, drug_db, picker, flagger, validator, audit, clock)
    assemble = AssembleReviewPacket(presenter, gates, DEFAULT_SYMPTOM_CATALOG, audit, clock)
    trigger = PipelineTrigger(store, screen, follow_up, prefetch, assemble, audit, clock,
                              limits=limits, timeout=timeout)
    decisions = RecordPhysicianDecision(gates, replies, frozenset(config.approvers), audit, clock)

    # web: the controller gets ready-made functions, so the web package imports no other adapter
    first_approver = config.approvers[0]
    audit_path = config.audit_log_path
    earlier = len(read_audit_log(audit_path)) if Path(audit_path).is_file() else 0   # run log shows this session
    controller = WebController(
        trigger, bundles, outbox, reviews,
        render_html=lambda view, gate: render_review_html(view, render_gate_html(gate)),
        to_json=review_view_to_dict, decisions=decisions,
        gate_view=lambda review: present_gate(review, first_approver), gate_to_json=gate_view_to_dict,
        run_log=lambda: format_run_log(read_audit_log(audit_path)[earlier:] if Path(audit_path).is_file() else [],
                                       source=f"{audit_path}, this server session"),
        instance_id=uuid.uuid4().hex[:12])
    return Container(controller, trigger, audit, clock, bundles, outbox, reviews, _read_page(config),
                     decisions, gates)


def _read_page(config: Config) -> str | None:
    path = Path(config.mockchart_page) if config.mockchart_page else next(iter(sorted(Path.cwd().glob("MockChart*.html"))), None)
    return path.read_text(encoding="utf-8") if path and path.is_file() else None


def build_app(container: Container, config: Config):
    from curaai.adapters.web.routers import create_app      # FastAPI imported only when serving
    return create_app(container.controller, page_html=container.page_html,
                      bridge_js=BRIDGE_JS.read_text(encoding="utf-8"), sweep_every_s=config.sweep_seconds or None)


def port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def main() -> None:
    import uvicorn
    try:
        config = Config.from_env({**load_env_file(".env"), **os.environ})
    except ValueError as exc:
        sys.exit(f"CuraAI can't start: {exc}\nRun  python -m curaai.app.check  for a full setup check.")
    if port_in_use(config.host, config.port):
        sys.exit(f"CuraAI can't start: something is already running on {config.host}:{config.port}.\n"
                 "An old CuraAI server is probably still open. Close that PowerShell window "
                 "(or press Ctrl+C in it), then start again.")
    container = build_container(config)
    app = build_app(container, config)
    model = config.model_backend
    if config.model_backend in ("groq", "gemini"):
        name, fallback = ((config.groq_model, config.groq_fallback_model) if config.model_backend == "groq"
                          else (config.gemini_model, config.gemini_fallback_model))
        backup = f", backup {fallback}" if fallback else ""
        steps = "reading messages only" if config.ai_use_for == "reading" else "all steps"
        pace = f", max {config.ai_max_per_minute:g}/min" if config.ai_max_per_minute else ""
        model = f"{config.model_backend} ({name}{backup}; {steps}{pace})"
    print(f"CuraAI: model={model} drugs={config.drug_adapter} audit={config.audit_log_path}")
    print(f"HITL approvers: {', '.join(config.approvers)}")
    print(f"Open http://{config.host}:{config.port}/mockchart   (run log: http://{config.host}:{config.port}/runlog)")
    uvicorn.run(app, host=config.host, port=config.port)


if __name__ == "__main__":
    main()
