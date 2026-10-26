---
tags: [curaai, cs302, team-tokenizer, code]
status: in-progress
repo: https://github.com/DesolateBryan/CuraAI
updated: 2026-10-26
---
# CuraAI: Project Overview

> CS302 team project, **Team Tokenizer**. An AI agent for physicians: **Clinical Record Triage & Historical Pre-Fetch**.

## Pitch
A patient sends a sick message. CuraAI checks it says **when symptoms started** and **whether they are better, worse or the same**. If not, it asks a clinician-approved follow-up question. Then it pulls **3 weeks of chart history + drug info** and shows it to the doctor **verbatim, with a source on every row**. No AI summaries. The doctor makes every decision.

## Team
| Person | Role | Governance steward |
|---|---|---|
| Nicole Hood | Team Lead & Lead Architect | ADR-007 Transparency, ADR-011 Cost Control |
| Bryan Ponce | Reviewer / QA | ADR-009 HITL Gates |
| RJ Peck | Builder / Builder-Director | ADR-008 Observability |
| Downing Nightingale | Builder / Integration | ADR-010 Least Privilege |

Meetings: Wednesdays right after class.

## Links
- Repo: https://github.com/DesolateBryan/CuraAI
- PR #1 (Rings 1-2 core): https://github.com/DesolateBryan/CuraAI/pull/1 (merged)
- PR #2 (EHR adapter): https://github.com/DesolateBryan/CuraAI/pull/2 (merged, reached `main` via #4)
- PR #3 (drug adapters): https://github.com/DesolateBryan/CuraAI/pull/3 (merged, reached `main` via #4)
- PR #4 (drug adapters → `main`): https://github.com/DesolateBryan/CuraAI/pull/4 (merged)
- PR #5 (review presenter): https://github.com/DesolateBryan/CuraAI/pull/5 (merged)
- PR #6 (persistence): https://github.com/DesolateBryan/CuraAI/pull/6 (**open**, targets `main`)
- PR #7 (model side): https://github.com/DesolateBryan/CuraAI/pull/7 (**open**, targets `main`; built on #6, so merge #6 first)
- PR #8 (web app + MockChart bridge): https://github.com/DesolateBryan/CuraAI/pull/8 (**open**, targets `main`; built on #7, so **merge #6 → #7 → #8**)
- Sample doctor's screen: `docs/samples/ellison_review.html`
- This note also lives in the repo at `CuraAI/00 CuraAI - Project Overview.md`; each PR updates both copies
- Structure chart: `docs/architecture/curaai_structure.png` in the repo
- Test EHR: the MockChart HTML page in the repo (exposes `window.MockEpic`)

## Stack
Python 3.12 · FastAPI + Pydantic (outer rings only) · FHIR R4 · ports-and-adapters (Clean Architecture) · pytest · import-linter

## The four rings
| Ring | Folder | What lives there | Status |
|---|---|---|---|
| 1 Entities | `src/curaai/domain` | Pure rules, stdlib only | **Done** |
| 2 Use cases | `src/curaai/application` | Ports, DTOs, validator, 5 use cases | **Done** |
| 3 Adapters | `src/curaai/adapters` | EHR, drug DB, model, presenter, stores, web | **All done**: EHR/drug/presenter on `main`; stores (PR #6); model (PR #7); web controller + FastAPI + bridge (PR #8) |
| 4 Frameworks | `src/curaai/app/main.py` | Composition root, FastAPI, Uvicorn | **Done** (PR #8) |

**Dependency Rule:** imports only point inward. Domain imports nothing, application imports only domain, adapters never import each other, and only `app/main.py` (plus `tests/compose.py`) wires everything.

## Message flow
1. **PipelineTrigger**: runs on every patient message.
2. **ScreenSickMessage**: the model reads *only the patient's words*; the validator rejects anything not in the catalog.
3. **RequestFollowUp**: asks only for what's missing, using catalog text only, max 2 follow-ups.
4. **PrefetchHistory**: fixed chart pull (onset − 21 days → today) + current meds + drug info. Optional AI marks relevant rows/flags; the model sees only ids + short labels.
5. **AssembleReviewPacket**: builds the packet → presenter → doctor.

## Core rules (Ring 1)
- Complete = **onset + trend** present
- Lookback = **onset − 21 days through today**
- Follow-up timeout = **24 hours**
- Caps per case: **12 model calls** (doubled from 6, team decision 2026-10-26), **5 lookups, 2 follow-ups, $0.25**
- Every chart/drug row **must have a source_ref**
- Patient words are always labeled **patient-reported**
- In-person verification banner is **always on**

## Decisions we made (2026-10-26)
- Lookback ends **today**, not at onset (catches same-day labs like a STAT troponin).
- 24 h timeout → hand off **messages only, no chart pull**. Same when follow-ups run out.
- If AI fails or hits a cap → AI off for the case, **fixed chart pull still runs** (ADR-011).
- One rejected extraction turns AI off for the case; nothing is partially trusted.
- EHR DTO named `ChartItemRecord` (avoids clash with the `ChartItem` entity).
- **Stopped meds get a `stopped` flag**: MockChart's FHIR gives `status: stopped` but **no end date**. Stopped = never "current"; not counted as a window change.
- Drug records now carry **boxed warning + contraindications**; boxed warning is shown first.
- openFDA label text is **never truncated** (the page trims to 900 chars; the backend keeps it all).
- openFDA needs an **exact** generic/brand name match, so combination products (e.g. lisinopril + HCTZ) don't sneak in. Chart names are searched as written (no guessing).
- Mock drug list + interaction table are **captured from the MockChart page** so backend and page agree.
- **Presenter owns every display choice**: section order, rows chronological vs onset, "17 days before onset" wording, "Patient-reported" labels, approximate-onset wording, always-on banner, notices. It never edits row text. Current meds show "Since <date>" with no offset.
- The review packet now records the **window it searched**, so the doctor sees the exact range.
- **Audit log = append-only JSONL file** for now (Postgres later). One line per event, fsync'd, schema version, no update/delete. **Patient message text is never written to it**, only ids, counts, reasons.
- **Open cases live in memory**: a restart loses open cases and their 24 h timers. Build a database store when the timeout must survive restarts.
- **Model gateway runs in-process** (ADR-001): redaction, prompt versions, pricing, audit, then a swappable vendor transport (**AWS Bedrock** first). Only `main.py` builds the boto3 client.
- **Redaction** removes emails, phones, SSNs, URLs, 6+ digit IDs (MRNs); **keeps dates and doses**. Names are NOT removed yet (needs an NER model) and that is a gate before real PHI.
- Prompt parsers only reject non-JSON; **the core validator judges every value**, so all rejections are audited in one place.
- **CostGuard** ($0.25/case + daily budget) lives in `adapters/model` (adapters can't import each other). Tripping on a spike of failed validations is deferred until the eval run sets a threshold.
- **Metrics are computed from the audit log** (`case_metrics`), so they always match what auditors see.
- **Web layer**: `WebController` makes every HTTP decision with no framework; FastAPI routes each make one call. Backend serves MockChart at `/mockchart` with a bridge script added (team's HTML never edited).
- Follow-up questions reach MockChart through an **outbox** the bridge polls.
- **Every follow-up is labeled "Automated question from CuraAI"** (decision 2026-10-26). The label is required on every outbound question and set by the core, so no adapter can drop it. In MockChart it goes in front of the unchanged catalog text; real Epic should use its own sender/automation field.
- **Model-call cap doubled 6 → 12** (decision 2026-10-26): Whitaker's 2-follow-up case now uses 7 calls and keeps medication flagging. Record as an amendment to ADR-011.
- **`CURAAI_MODEL_BACKEND=none`** runs the whole demo with no AWS account (fixed chart pull, no AI).
- Trend question reworded to *"Have your symptoms been getting better, getting worse, or staying about the same?"* (old "Since they started…" read like an onset question).
- Re-captured MockChart data after the team added **amlodipine (stopped Aug 18)** + an Aug 18 visit to Ellison; the parity test caught it.

## Open questions for the team
1. **Urgent symptoms**: nothing fast-tracks chest pain (MockChart p5). Add a red-flag rule?
2. Symptom + follow-up **catalogs are drafts**; they need clinician sign-off (ADR-009).
3. A message arriving mid-processing opens a new case. OK?

## How to run
**Demo (no cloud account):** `pip install -e ".[web]"`, copy `.env.example` to `.env`, run `python -m curaai.app.main`, open http://127.0.0.1:8000/mockchart. Use the CuraAI panel (bottom right) → **Open review**.

**Tests:**
```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev,web]"   # web extra lets the FastAPI route test run
pytest          # 174 tests (+1 FastAPI route test with the web extra), offline
lint-imports    # Dependency Rule check
```
Re-capture FHIR test data from the MockChart page: `python tests/fixtures/fhir/capture.py`
Record a real openFDA response (needs internet): `python tests/fixtures/openfda/capture.py lisinopril`
> The openFDA test fixture uses **synthetic** label text. Run the capture once to check against a real label.

## Next steps
- [x] Merge PR #1 → #2 → #3 / #4 (core, EHR, drug adapters are on `main`)
- [x] PR #5 retargeted to `main` and merged
- [ ] Review + merge PR #6 → #7 → #8 (run real `pytest` + `lint-imports` first)
- [x] FastAPI routes + `app/main.py` + MockChart bridge (PR #8)
- [ ] Run the demo on a teammate's machine: `python -m curaai.app.main` → /mockchart
- [x] Model-call cap decided: doubled to 12
- [x] Follow-ups labeled as automated
- [ ] Write the ADR-011 amendment (cap 6 → 12) and an ADR note for the automated label
- [x] EHR adapter: FHIR mapper + `MockEpicAdapter` (PR #2)
- [x] Drug DB adapters: `MockDrugAdapter`, `OpenFdaAdapter` (PR #3)
- [ ] Record one real openFDA response and compare with the synthetic fixture
- [x] `ReviewPresenter` + HTML view (PR #5)
- [x] `JsonlAuditLog`, `InMemoryConversationStore` (PR #6)
- [x] Model adapters + `ModelGateway` + Bedrock transport + `CostGuard` + logging decorators + metrics (PR #7)
- [ ] Pick the Bedrock model id + get real pricing (placeholders in tests)
- [ ] Build the synthetic evaluation set and run it against the real model (ADR-016)
- [ ] Decide the urgent-symptom question

## Dev log
- **2026-10-26**: Planned structure + drew the structure chart. Built Rings 1–2 and tests (PR #1). Built FHIR mapper + MockEpicAdapter on real MockChart FHIR (PR #2). 85 tests passing.
- **2026-10-26 (later)**: Pushed PR #3: `MockDrugAdapter` (page's drug list + interactions) and `OpenFdaAdapter` (exact-match, no truncation, label version in source_ref). Added boxed warning + contraindications to drug records. 97 tests passing.
- **2026-10-26 (later)**: Pushed PR #5: `ReviewPresenter` (pure `present_review`), humble HTML view, sample review for Ellison in `docs/samples/`. Packet now carries the searched window. 113 tests passing. Core, EHR and drug work are merged to `main`.
- **2026-10-26 (later)**: PR #5 merged to `main`. Pushed PR #6: `JsonlAuditLog` (append-only, fsync'd, no patient text) and `InMemoryConversationStore` (thread-safe), with contract tests that run the same checks on the fakes and the real adapters. 125 tests passing.
- **2026-10-26 (later)**: Pushed PR #7 (model side): prompts + parsers for the 4 model ports, in-process `ModelGateway` (redaction, pricing, audit), `BedrockConverseTransport`, `CostGuard`, logging decorators, `case_metrics`. Fixed a redaction bug (an MRN at the end of a sentence slipped through). Full pipeline runs through the real model stack with only the vendor faked. 152 tests passing.
- **2026-10-26 (later)**: Pushed PR #8: framework-free `WebController`, FastAPI routes, `app/main.py` (`Config.from_env`, `build_container`), MockChart bridge + outbox, `none` model mode. Re-captured MockChart data (team added amlodipine). Ran the real page + bridge + backend in a browser: Whitaker got 2 catalog follow-ups, the simulated patient answered, and the review opened inside MockChart. **All four rings are built.** 174 tests passing.
- **2026-10-26 (later)**: Team decisions applied to PR #8: follow-ups labeled "Automated question from CuraAI" (required, set by the core) and the model-call cap doubled to 12. Browser re-check: label shows in MockChart, the simulated patient still answers correctly, and Whitaker's case uses 7 of 12 calls and keeps the sertraline flag. 174 tests passing.
