"""Composition root (ADR-015). The ONLY module that imports every ring and the vendor SDK.

    Config.from_env()   read settings once (no secrets in the repo, ADR-006)
    build_container()   create and wire every object; one `if` per adapter choice
    build_app()         hand the controller to the FastAPI routes
    main()              start Uvicorn

Nothing imports this module, so the Dependency Rule still points inward.
tests/compose.py is the second composition root; it wires fakes into the same use cases.

Run the demo (no cloud account needed; the default backend is the local rule-based reader):
    pip install -e ".[web]"
    python -m curaai.app.main            # then open http://127.0.0.1:8000/mockchart
"""

import os
import socket
import sys
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from curaai.adapters.clock.fixed_clock import FixedClock
from curaai.adapters.clock.system_clock import SystemClock
from curaai.adapters.drug import MockDrugAdapter, OpenFdaAdapter, UrllibHttpClient, load_mockchart_drugs
from curaai.adapters.ehr import InMemoryBundleSource, MockEpicAdapter
from curaai.adapters.ehr.mock_epic_messaging import InMemoryOutbox, MockEpicMessagingAdapter
from curaai.adapters.model import (
    BedrockConverseTransport, CostGuard, GatewayExtractSymptoms, GatewayMatchFlags, GatewayPickRelevantItems,
    GatewaySelectFollowUp, ModelGateway, ModelPricing,
)
from curaai.adapters.model.gemini_transport import DEFAULT_MODEL as DEFAULT_GEMINI_MODEL, GeminiTransport
from curaai.adapters.model.local_rules import LocalRulesTransport
from curaai.adapters.model.no_model_transport import NoModelTransport
from curaai.adapters.observability import (
    LoggedExtractSymptoms, LoggedMatchFlags, LoggedPickRelevantItems, LoggedSelectFollowUp,
)
from curaai.adapters.persistence import InMemoryConversationStore, JsonlAuditLog
from curaai.adapters.presenters import InMemoryReviewSink, ReviewPresenter, render_review_html, review_view_to_dict
from curaai.adapters.web.controller import WebController
from curaai.application.ports.audit_log_port import AuditLogPort
from curaai.application.ports.clock_port import ClockPort
from curaai.application.use_cases import (
    AssembleReviewPacket, PipelineTrigger, PrefetchHistory, RequestFollowUp, ScreenSickMessage,
)
from curaai.application.validation import ModelOutputValidator
from curaai.domain.case_budget import CaseLimits
from curaai.domain.follow_up_catalog import DEFAULT_FOLLOW_UP_CATALOG
from curaai.domain.symptom_catalog import DEFAULT_SYMPTOM_CATALOG

BRIDGE_JS = Path(__file__).resolve().parents[1] / "adapters" / "web" / "static" / "curaai-bridge.js"

CHOICES = {
    "ehr_adapter": ("mock_epic",),                 # a real Epic adapter needs SMART on FHIR (deferred, ADR-017)
    "drug_adapter": ("mock", "openfda"),
    "model_backend": ("local", "gemini", "bedrock", "none"),
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
                mock_epic_api_key=get("mock_epic_api_key", d.mock_epic_api_key),
                audit_log_path=get("audit_log_path", d.audit_log_path), clinic_tz=get("clinic_tz", d.clinic_tz),
                clock_now=get("clock_now", ""), mockchart_page=get("mockchart_page", ""),
                daily_budget_usd=Decimal(get("daily_budget_usd", str(d.daily_budget_usd))),
                price_in_per_mtok=Decimal(get("price_in_per_mtok", str(d.price_in_per_mtok))),
                price_out_per_mtok=Decimal(get("price_out_per_mtok", str(d.price_out_per_mtok))),
                host=get("host", d.host), port=int(get("port", str(d.port))),
                sweep_seconds=float(get("sweep_seconds", str(d.sweep_seconds))),
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
        if not self.mock_epic_api_key:
            raise ValueError("CURAAI_MOCK_EPIC_API_KEY is required")


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


def build_clock(config: Config) -> ClockPort:
    try:
        tz = ZoneInfo(config.clinic_tz)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"unknown timezone {config.clinic_tz!r} (on Windows: pip install tzdata)") from exc
    if config.clock_now:
        now = datetime.fromisoformat(config.clock_now.replace("Z", "+00:00"))
        return FixedClock(now if now.tzinfo else now.replace(tzinfo=tz))
    return SystemClock(tz)


def build_container(config: Config, *, bedrock_client: object | None = None,
                    gemini_poster: object | None = None) -> Container:
    clock = build_clock(config)
    audit = JsonlAuditLog(config.audit_log_path)
    limits = CaseLimits()

    # EHR (read-only) and patient messaging
    bundles = InMemoryBundleSource()
    ehr = MockEpicAdapter(bundles, api_key=config.mock_epic_api_key)
    outbox = InMemoryOutbox()
    messaging = MockEpicMessagingAdapter(outbox)

    # drug database (read-only)
    if config.drug_adapter == "openfda":
        drug_db = OpenFdaAdapter(UrllibHttpClient())
    else:
        drug_db = MockDrugAdapter(load_mockchart_drugs())

    # model: vendor SDK -> transport -> gateway -> cost guard -> four logged adapters
    if config.model_backend == "bedrock":
        if bedrock_client is None:
            import boto3                                   # the only vendor SDK import in the codebase
            bedrock_client = boto3.client("bedrock-runtime", region_name=config.aws_region)
        transport = BedrockConverseTransport(bedrock_client, config.bedrock_model_id)
    elif config.model_backend == "gemini":
        transport = GeminiTransport(config.gemini_api_key, config.gemini_model,
                                    thinking_level=config.gemini_thinking_level or None, poster=gemini_poster)
    elif config.model_backend == "local":
        transport = LocalRulesTransport()                  # demo reader, no network, no cost
    else:
        transport = NoModelTransport()                     # ADR-011 fallback only
    pricing = ModelPricing(config.price_in_per_mtok, config.price_out_per_mtok)
    client = CostGuard(ModelGateway(transport, pricing, audit, clock), limits, config.daily_budget_usd, audit, clock)
    extractor = LoggedExtractSymptoms(GatewayExtractSymptoms(client), audit, clock)
    selector = LoggedSelectFollowUp(GatewaySelectFollowUp(client), audit, clock)
    picker = LoggedPickRelevantItems(GatewayPickRelevantItems(client), audit, clock)
    flagger = LoggedMatchFlags(GatewayMatchFlags(client), audit, clock)

    # review output and state
    reviews = InMemoryReviewSink()
    presenter = ReviewPresenter(reviews)
    store = InMemoryConversationStore()

    # use cases (Ring 2) receive only ports
    validator = ModelOutputValidator(DEFAULT_SYMPTOM_CATALOG)
    screen = ScreenSickMessage(extractor, validator, DEFAULT_SYMPTOM_CATALOG, audit, clock)
    follow_up = RequestFollowUp(selector, validator, DEFAULT_FOLLOW_UP_CATALOG, messaging, audit, clock)
    prefetch = PrefetchHistory(ehr, drug_db, picker, flagger, validator, audit, clock)
    assemble = AssembleReviewPacket(presenter, DEFAULT_SYMPTOM_CATALOG, audit, clock)
    trigger = PipelineTrigger(store, screen, follow_up, prefetch, assemble, audit, clock, limits=limits)

    controller = WebController(trigger, bundles, outbox, reviews, render_review_html, review_view_to_dict,
                               instance_id=uuid.uuid4().hex[:12])
    return Container(controller, trigger, audit, clock, bundles, outbox, reviews, _read_page(config))


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
    model = f"{config.model_backend} ({config.gemini_model})" if config.model_backend == "gemini" else config.model_backend
    print(f"CuraAI: model={model} drugs={config.drug_adapter} audit={config.audit_log_path}")
    print(f"Open http://{config.host}:{config.port}/mockchart")
    uvicorn.run(app, host=config.host, port=config.port)


if __name__ == "__main__":
    main()
