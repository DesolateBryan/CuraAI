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
- PR #1 (Rings 1-2 core): https://github.com/DesolateBryan/CuraAI/pull/1
- PR #2 (EHR adapter, stacked on #1): https://github.com/DesolateBryan/CuraAI/pull/2
- Structure chart: `docs/architecture/curaai_structure.png` in the repo
- Test EHR: the MockChart HTML page in the repo (exposes `window.MockEpic`)

## Stack
Python 3.12 · FastAPI + Pydantic (outer rings only) · FHIR R4 · ports-and-adapters (Clean Architecture) · pytest · import-linter

## The four rings
| Ring | Folder | What lives there | Status |
|---|---|---|---|
| 1 Entities | `src/curaai/domain` | Pure rules, stdlib only | **Done** |
| 2 Use cases | `src/curaai/application` | Ports, DTOs, validator, 5 use cases | **Done** |
| 3 Adapters | `src/curaai/adapters` | EHR, drug DB, model, presenter, stores | EHR **done**, rest stubs |
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

## Open questions for the team
1. **Urgent symptoms**: nothing fast-tracks chest pain (MockChart p5). Add a red-flag rule?
2. Symptom + follow-up **catalogs are drafts**; they need clinician sign-off (ADR-009).
3. A message arriving mid-processing opens a new case. OK?

## How to run
```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
pytest          # 85 tests, offline, fakes + fixed clock
lint-imports    # Dependency Rule check
```
Re-capture FHIR test data from the MockChart page: `python tests/fixtures/fhir/capture.py`

## Next steps
- [ ] Merge PR #1, then PR #2 (confirm with real `pytest` + `lint-imports` first)
- [ ] Drug DB adapters: `MockDrugAdapter`, `OpenFdaAdapter`
- [ ] `ReviewPresenter` (formats dates, labels, banner, section order)
- [ ] `JsonlAuditLog`, `InMemoryConversationStore`
- [ ] Model adapters + `GatewayClient` + logging / `CostGuard` decorators
- [ ] FastAPI router → `app/main.py` → MockChart page bridge
- [ ] Decide the urgent-symptom question

## Dev log
- **2026-10-26**: Planned structure + drew the structure chart. Built Rings 1–2 and tests (PR #1). Built FHIR mapper + MockEpicAdapter on real MockChart FHIR (PR #2). 85 tests passing.
