# CuraAI

CuraAI is a healthcare AI agent designed to alleviate the heavy administrative burden on physicians, who spend an estimated 5.8 hours per shift manually navigating Electronic Health Records (EHR) to cross-reference patient data. Integrated with existing systems like Epic, CuraAI screens inbound patient sick messages for missing clinical details, prompts patients for clarification, and aggregates relevant three-week historical chart data alongside pharmaceutical database information. To eliminate the risk of dangerous AI hallucinations, the system presents exact documented findings verbatim rather than generating narrative summaries. Built using a clean ports-and-adapters architecture in Python (FastAPI), CuraAI separates pure business rules from external I/O. Its core use case is Clinical Record Triage and Historical Pre-Fetch ensuring that human clinicians remain in complete control of all clinical decisions and patient communications. Key architectural choices have been formalized through project ADRs: ADR-001 routes queries through a HIPAA-eligible cloud provider behind an internal model gateway for PII redaction and logging; ADR-002 enforces a deterministic chart pull while limiting the LLM to screening and validated symptom lookups; ADR-003 establishes the Python/FastAPI ports-and-adapters foundation with an append-only PostgreSQL audit log; and  ADR-004 mandates the verbatim display of source records on a symptom-onset timeline to guarantee safety, compliance, and effortless physician verification.

**Clinical Record Triage and Historical Pre-Fetch**, CS302 Team Tokenizer.

When a patient sends a sick message, CuraAI checks that it says **when symptoms
started** and **whether they are getting better, worse or staying the same**. If
either detail is missing, it asks the patient a clinician-approved follow-up
question. Once both are known, it pulls three weeks of chart history and drug
information for the physician, shown **verbatim** with a source on every row.
The physician makes every clinical decision.

![Structure](docs/architecture/curaai_structure.png)

## Status

| Ring | Package | This pass |
|---|---|---|
| 1 Entities | `src/curaai/domain` | **Built and tested** |
| 2 Use cases, ports, DTOs | `src/curaai/application` | **Built and tested** |
| 3 Interface adapters | `src/curaai/adapters` | **Built and tested**: EHR (`MockEpicAdapter`), drug DB (`MockDrugAdapter`, `OpenFdaAdapter`), model (`ModelGateway`, Bedrock transport, `CostGuard`, four adapters), observability, presenter, persistence, web controller + FastAPI routes + page bridge |
| 4 Frameworks, composition root | `src/curaai/app/main.py` | **Built**: `Config.from_env`, `build_container`, `build_app`, Uvicorn |

## Quick start

Requires **Python 3.12+**. Rings 1–2 have no third-party dependencies.

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest                               # unit tests, all offline, fixed clock, fakes only
lint-imports                         # Dependency Rule contracts (pyproject.toml)
```

No environment variables are needed for the tests. The FastAPI route test is skipped
unless the `web` extra is installed (`pip install -e ".[dev,web]"`).

## Run the demo with MockChart

No cloud account is needed. With no model backend, CuraAI runs its ADR-011 fallback:
it still pulls the fixed 3-week chart history, and the review says AI screening was unavailable.

```bash
pip install -e ".[web]"
cp .env.example .env                 # Windows: copy .env.example .env
python -m curaai.app.main
```

Then open **http://127.0.0.1:8000/mockchart**. The backend serves the team's MockChart
page with a small bridge script added (the HTML file itself is never edited). The bridge:

1. sends every patient message, with that patient's FHIR bundle, to CuraAI,
2. delivers CuraAI's follow-up questions into the patient's thread, where MockChart's
   simulated patient answers them,
3. shows a **CuraAI** panel (bottom right) with an **Open review** button per patient.

To use a real model, set `CURAAI_MODEL_BACKEND=bedrock` and `CURAAI_BEDROCK_MODEL_ID`, then
`pip install -e ".[web,bedrock]"`. AWS credentials come from your normal AWS configuration.
**Synthetic data only** until the BAA and retention policy exist (ADR-006).

![Follow-up thread](docs/samples/mockchart_follow_up_thread.png)
![Review inside MockChart](docs/samples/mockchart_review_overlay.png)

Never commit a real `.env`.

## Layout

```
src/curaai/
  domain/                 Ring 1, standard library only
    values.py             ids + enums (Trend, Origin, ChartItemKind, MissingField, Flag)
    symptom_catalog.py    fixed symptom ids the model must choose from        (DRAFT)
    follow_up_catalog.py  the only questions CuraAI may send a patient         (DRAFT)
    completeness.py       onset + trend present?
    lookback.py           onset - 21 days .. today
    follow_up_timeout.py  24 hours
    case_budget.py        per-case caps: 6 model calls, 5 lookups, 2 follow-ups, $0.25
    sick_message.py, symptom_report.py, chart_item.py, drug_info.py
    conversation.py       case state machine
    timeline.py           TimelineEntry, ReviewPacket
  application/            Ring 2, imports only domain
    dto/                  one module per boundary (M2 "Crossing of Each Line")
    ports/                abstract interfaces this ring owns
    validation/           ModelOutputValidator
    mapping.py            DTO <-> entity mappers (pure)
    use_cases/            PipelineTrigger, ScreenSickMessage, RequestFollowUp,
                          PrefetchHistory, AssembleReviewPacket
  adapters/               Ring 3 stubs: model, ehr, drug, presenters, persistence,
                          clock, observability, web
  app/main.py             Ring 4 composition root stub
tests/
  compose.py              test composition root (fakes + fixed clock)
  fakes/                  fake EHR, drug DB, 4 model ports, messaging, stores, clock
  fixtures/mockchart.py   synthetic MockChart patients (no real PHI)
  fixtures/fhir/          FHIR bundles captured from the real MockChart page (+ capture.py)
  fixtures/openfda/       openFDA-shaped response with SYNTHETIC label text (+ capture.py for a real one)
  unit/                   domain, application, dependency-rule tests
```

## How a message flows

1. **PipelineTrigger** runs on every patient message. There is no model gate.
2. **ScreenSickMessage** sends only the patient's words to `ExtractSymptomsPort`.
   `ModelOutputValidator` rejects any symptom id outside the catalog, any trend
   outside the enum, and any onset after the message or more than a year old.
3. If onset or trend is missing, **RequestFollowUp** sends one catalog question
   that asks only for what is missing. The model may choose which question,
   never the wording. At most 2 follow-ups per case.
4. Once complete, **PrefetchHistory** runs the fixed pull:
   - medication changes, labs and visits from onset − 21 days through today
   - the current medication list
   - drug-database text for every medication changed in the window

   Optional AI help comes next. The model sees only item ids and short labels.
   It can mark relevant rows, flag medications, and add up to 5 extra drug
   lookups, which go in a separately labeled section.
5. **AssembleReviewPacket** builds the packet and passes a plain DTO to
   `ReviewOutputPort`. **ReviewPresenter** turns it into a `ReviewView` of
   display-ready strings. The view only loops, escapes and fills slots.

Example of the physician's screen (synthetic MockChart patient):
[`docs/samples/ellison_review.html`](docs/samples/ellison_review.html)

![Sample review](docs/samples/ellison_review.png)

If the model fails, goes over its cap, or gives an answer the validator
rejects, AI switches off for that case and the fixed pull still runs.

## Decisions made in this pass

These came from team Q&A on 2026-10-26, or from gaps in the briefs. Review them at the next meeting.

- **Lookback window ends today, not at onset.** Results after onset, like a same-day troponin, are included.
- **24-hour timeout hands off messages only.** No chart pull runs. Running out of follow-ups is handled the same way.
- **The AI fallback still runs the fixed pull** (ADR-011). When onset is unknown, the window is anchored to the first message date, and the packet says so (`incomplete_reason = ai_unavailable`).
- **One bad extraction switches AI off for the case.** A rejected extraction is never partly used. A rejected follow-up choice just falls back to the catalog's default question.
- **`ChartItemRecord` is the DTO name.** The M2 table calls the EHR DTO `ChartItem`, which clashes with the Ring 1 entity. This mirrors the existing `DrugRecord` / `DrugInfo` pair.
- **Current medications are always pulled,** as well as changes inside the window, so interactions can be checked.
- **Records that fail a check are dropped, audited and counted.** This covers records with no source and records outside the window. The physician sees `rejected_item_count`.
- **Stopped medications carry a `stopped` flag.** MockChart's FHIR marks a discontinued med `status: "stopped"` but gives no end date. A stopped med is never treated as current. Because its stop date is unknown, it doesn't count as a change in the window either; the new dose's own row shows the change. This is one of the gaps ADR-005 says to watch for, and real Epic data should give end dates.
- **The FHIR mapper never hides a bad record.** A resource with no `id` gets an empty `source_ref`, so the core rejects it and counts it. Other patients' resources and `entered-in-error` entries are dropped at the adapter.
- **Drug records carry the boxed warning and contraindications**, as well as class, adverse reactions and interactions. A boxed warning is listed first.
- **openFDA text is never truncated.** The MockChart page trims labels to 900 characters for display; the backend keeps the whole label, and the presenter decides layout.
- **openFDA must match the drug name exactly** (generic or brand). Phrase search also returns combination products, so a near miss counts as "not found". Chart names like "Albuterol HFA" are searched as written; mapping them to canonical names is terminology work (deferred).
- **The mock drug list is captured from the page** (`adapters/drug/mockchart_drugs.json`), including its interaction table, so the backend and the page agree.
- **The presenter owns every display choice.** It fixes the section order; rows run chronologically against onset; and it does the date and offset wording ("17 days before onset"), the "Patient-reported" labels, the approximate-onset wording and the always-on banner. It also writes the notices for incomplete cases, the AI fallback and withheld records. It never edits row text. Current medications show "Since <date>" without an offset.
- **The review packet records the window it searched**, so the doctor sees the exact range rather than the presenter recomputing a business rule.
- **The audit log is an append-only JSONL file for the prototype** (Postgres later, ADR-017). One JSON line per event, flushed and fsync'd, with a schema version; there is no update or delete. Patient message text is never written to it, only ids, counts and reasons.
- **Open cases are kept in memory.** A restart loses open cases and their 24-hour timers. The trigger for building a database-backed store is "the timeout must survive a restart".
- **The model gateway runs in-process for now** (ADR-001). It does the PII redaction, prompt versioning, pricing and audit, and hands off to a swappable vendor transport. Bedrock's Converse API is the first transport. The boto3 client is built only in `app/main.py`, so nothing else imports a vendor SDK.
- **Redaction removes** emails, phone numbers, SSNs, URLs and 6+ digit IDs (MRNs) before anything leaves. It **keeps** dates and doses, which the model has to read. Names are not removed yet: that needs an NER model, and it is a gate before any real PHI (ADR-006).
- **Parsers don't judge values.** A prompt parser only refuses text that isn't a JSON object. Wrong types, unknown ids and injected text pass through to the core's `ModelOutputValidator`, so every rejection is decided and audited in one place.
- **`CostGuard` lives in `adapters/model`**, not observability, because it wraps `GatewayClient` and adapter packages never import each other. It enforces the per-case dollar cap and a daily budget. Ring 2 already enforces the call, lookup and follow-up caps. Tripping on a spike in failed validations is deferred until the evaluation run gives a threshold.
- **Metrics come from the audit log** (`case_metrics`, ADR-008), so the numbers can never disagree with what auditors see.
- **Model-call cap doubled from 6 to 12 per case** (team decision, 2026-10-26). In the MockChart run, a two-follow-up case used all 6 and lost medication flagging; with 12 the same case uses 7 and keeps it. The lookup, follow-up and $0.25 caps are still the ADR-011 proposals. Record this as an amendment to ADR-011.
- **The web layer is split for testing.** `WebController` makes every HTTP decision (request checks, status codes, response shapes) with no framework imported. The FastAPI routes each make one call to it. Collaborators are injected as small Protocols, so the web package imports no other adapter.
- **The backend serves MockChart at `/mockchart` with the bridge added**, so the page and API share an origin (no CORS) and the team's HTML file stays untouched. The raw FHIR bundle stops at the EHR adapter's bundle source.
- **Follow-up questions reach the page through an outbox** that the bridge polls.
- **Every follow-up is labeled as automated** (team decision, 2026-10-26). `OutboundFollowUp.sender_label` is required and set by the core from `AUTOMATED_SENDER_LABEL` ("Automated question from CuraAI"), so no adapter can drop it. MockChart can only post as the doctor, so the label goes in front of the unchanged catalog text. A real Epic adapter should use Epic's own sender or automation field.
- **`CURAAI_MODEL_BACKEND=none` is a supported mode.** Every model call fails cleanly and the fixed chart pull still runs, so the demo needs no AWS account.
- **The trend question was reworded** to "Have your symptoms been getting better, getting worse, or staying about the same?". The old wording began "Since they started…", which reads like an onset question on its own (MockChart's simulated patient answered it as one).
- **MockChart test data was re-captured** after the team added amlodipine (stopped Aug 18) and an Aug 18 visit to Ellison. The parity test caught the drift.
- **Rings 1–2 use frozen standard-library dataclasses.** Pydantic is only for the FastAPI edge (Ring 3/4).

## Open questions for the team

1. **Urgent symptoms.** Nothing in the briefs fast-tracks something like chest pain radiating to the arm (MockChart patient p5). Today that message would be screened like any other. Do we need a red-flag rule that skips follow-ups and alerts the physician right away?
2. **Catalog sign-off.** Both catalogs are drafts and need a clinician to approve them (ADR-009).
3. **A message that arrives while a case is being processed** opens a new case. Is that acceptable?

## Remaining work

All four rings are built. What's left before a pilot:

- **Real model:** choose the Bedrock model id and get pricing; build the synthetic evaluation set and run it (ADR-001, ADR-016).
- **Name redaction:** add an NER step to the gateway before any real PHI (ADR-006).
- **Persistence:** a database-backed conversation store so the 24-hour timeout survives restarts, and the Postgres audit store (ADR-017).
- **Real Epic:** SMART on FHIR launch and an `EpicEhrAdapter` (ADR-017).
- **Decisions:** the open questions above, starting with urgent symptoms.
