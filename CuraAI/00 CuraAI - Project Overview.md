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
- PR #6 (persistence): see the PR list (**open**, targets `main`)
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
| 3 Adapters | `src/curaai/adapters` | EHR, drug DB, model, presenter, stores | EHR, drug, presenter **done** (on `main`); audit log + conversation store **done** (PR #6); model adapters + web still stubs |
| 4 Frameworks | `src/curaai/app/main.py` | Composition root, FastAPI, Uvicorn | Stub |

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
- Caps per case: **6 model calls, 5 lookups, 2 follow-ups, $0.25**
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

## Open questions for the team
1. **Urgent symptoms**: nothing fast-tracks chest pain (MockChart p5). Add a red-flag rule?
2. Symptom + follow-up **catalogs are drafts**; they need clinician sign-off (ADR-009).
3. A message arriving mid-processing opens a new case. OK?

## How to run
```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
pytest          # 125 tests, offline, fakes + fixed clock
lint-imports    # Dependency Rule check
```
Re-capture FHIR test data from the MockChart page: `python tests/fixtures/fhir/capture.py`
Record a real openFDA response (needs internet): `python tests/fixtures/openfda/capture.py lisinopril`
> The openFDA test fixture uses **synthetic** label text. Run the capture once to check against a real label.

## Next steps
- [x] Merge PR #1 → #2 → #3 / #4 (core, EHR, drug adapters are on `main`)
- [x] PR #5 retargeted to `main` and merged
- [ ] Review + merge PR #6 (run real `pytest` + `lint-imports` first)
- [x] EHR adapter: FHIR mapper + `MockEpicAdapter` (PR #2)
- [x] Drug DB adapters: `MockDrugAdapter`, `OpenFdaAdapter` (PR #3)
- [ ] Record one real openFDA response and compare with the synthetic fixture
- [x] `ReviewPresenter` + HTML view (PR #5)
- [x] `JsonlAuditLog`, `InMemoryConversationStore` (PR #6)
- [ ] Model adapters + `GatewayClient` + logging / `CostGuard` decorators
- [ ] FastAPI router → `app/main.py` → MockChart page bridge
- [ ] Decide the urgent-symptom question

## Dev log
- **2026-10-26**: Planned structure + drew the structure chart. Built Rings 1–2 and tests (PR #1). Built FHIR mapper + MockEpicAdapter on real MockChart FHIR (PR #2). 85 tests passing.
- **2026-10-26 (later)**: Pushed PR #3: `MockDrugAdapter` (page's drug list + interactions) and `OpenFdaAdapter` (exact-match, no truncation, label version in source_ref). Added boxed warning + contraindications to drug records. 97 tests passing.
- **2026-10-26 (later)**: Pushed PR #5: `ReviewPresenter` (pure `present_review`), humble HTML view, sample review for Ellison in `docs/samples/`. Packet now carries the searched window. 113 tests passing. Core, EHR and drug work are merged to `main`.
- **2026-10-26 (later)**: PR #5 merged to `main`. Pushed PR #6: `JsonlAuditLog` (append-only, fsync'd, no patient text) and `InMemoryConversationStore` (thread-safe), with contract tests that run the same checks on the fakes and the real adapters. 125 tests passing.
