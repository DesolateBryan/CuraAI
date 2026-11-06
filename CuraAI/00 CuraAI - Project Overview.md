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
- PR #6 (persistence): https://github.com/DesolateBryan/CuraAI/pull/6 (merged)
- PR #7 (model side): https://github.com/DesolateBryan/CuraAI/pull/7 (merged)
- PR #8 (web app + MockChart bridge): https://github.com/DesolateBryan/CuraAI/pull/8 (merged; note: the automated-label + cap change missed this merge and ships in PR #9)
- PR #9 (local reader + missed label/cap change): https://github.com/DesolateBryan/CuraAI/pull/9 (merged)
- PR #10 (Google Gemini backend): https://github.com/DesolateBryan/CuraAI/pull/10 (merged)
- PR #11 (demo fix: stuck panel + setup check): https://github.com/DesolateBryan/CuraAI/pull/11 (merged)
- PR #12 (why "AI screening was unavailable": logging, Gemini retries, format normalizing): https://github.com/DesolateBryan/CuraAI/pull/12 (merged)
- PR #13 (Gemini timeouts: 60 s adjustable wait, retry once, two-step setup check): https://github.com/DesolateBryan/CuraAI/pull/13 (merged)
- PR #14 (Gemini 503 "model overloaded": optional backup model): https://github.com/DesolateBryan/CuraAI/pull/14 (merged)
- PR #15 (**Groq** backend + quota savers for free keys): https://github.com/DesolateBryan/CuraAI/pull/15 (merged)
- PR #16 (fix Groq HTTP 403: send a CuraAI User-Agent): https://github.com/DesolateBryan/CuraAI/pull/16 (merged)
- PR #17 (**M3 readiness**: HITL gate, run log, honest Main, no-live-model guard, README + demo script): https://github.com/DesolateBryan/CuraAI/pull/17 (**open**, targets `main`)
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
- **Default demo reader is `local`** (rule-based, `adapters/model/local_rules.py`). Without it the demo never read the message, so the chart window started at the message date and **missed Ellison's lisinopril increase and Raman's levothyroxine increase**. It plugs in where Bedrock does (same gateway, audit, validator), sees only words/ids/labels, and is a demo stand-in + eval baseline, **not** the product model. Review tags still say "AI" when it produced them.
- **Google Gemini backend** (`CURAAI_MODEL_BACKEND=gemini`), requested by the group so the agent runs on a real AI model. Free key from https://aistudio.google.com/apikey → put `CURAAI_GEMINI_API_KEY=...` in `.env` (never committed). Default model `gemini-3.8-flash`, thinking `low`, JSON-only answers, stdlib HTTP (nothing extra to install). Same gateway/audit/validator; if Gemini fails → fixed chart pull fallback.
- **AI Studio key = synthetic data only.** Real PHI would need Gemini on Vertex AI under a Google Cloud BAA → write an ADR-001 amendment for the vendor choice.
- `CURAAI_MODEL_BACKEND=none` still exists (ADR-011 fallback: chart pull from message date).
- **"AI screening was unavailable"** = reading the message failed for that case → AI off, plain chart pull from message date. Causes: backend `none`; Gemini refused (bad key, **free-tier per-minute limit**, no internet); Gemini's answer failed the safety check; cost cap. PR #12: gateway now logs the service's real error message; Gemini 429/500/503 retried up to 3× honoring Google's delay; harmless format differences ("Cough", ISO timestamps, "true") normalized before the strict validator. Find the reason: `Select-String -Path audit.jsonl -Pattern 'model_gateway_error|model_output_rejected|cost_guard_tripped' | Select-Object -Last 3`
- **Gemini timeouts** (RJ, 2026-11-02: `Gemini unreachable: The read operation timed out`, ~30 s): not a bad key (instant 400) or wrong model (instant 404); either the network stalls Google's API or the model is slow. PR #13: wait 60 s (`CURAAI_GEMINI_TIMEOUT_S`), retry a timeout once, messages say "timed out" vs "could not connect". `python -m curaai.app.check` now does a fast model lookup first (blocked network / bad key / wrong model) then times a real answer (slow → raise timeout or lighter model via `CURAAI_GEMINI_MODEL`).
- **Gemini 503** = "model overloaded", Google's side (not key/code), often clears in minutes. Retried 3×. PR #14: `CURAAI_GEMINI_FALLBACK_MODEL` backup model, used when the main one is still busy after retries (503/500/429/timeout); never on bad key. Setup check lists models the key can use and verifies the backup. Audit `model` field shows which answered.
- **2026-11-04: switched to Groq.** "Too much traffic and not enough tokens" on the free Gemini key → team chose Groq (`CURAAI_MODEL_BACKEND=groq`, `CURAAI_GROQ_API_KEY` from https://console.groq.com/keys, default model `openai/gpt-oss-20b`, low reasoning). Free tier ~30 req/min, 8K tokens/min, 200K tokens/day. Quota savers for Groq and Gemini: `CURAAI_AI_USE_FOR=reading` (only message reading uses the AI; full demo 30 → 16 calls), `CURAAI_AI_MAX_PER_MINUTE=8`, reply cache (reloads/Reset/Re-run free). Gemini + Groq share `http_transport.py` (retries, timeouts, backup model).
- **Groq HTTP 403: Forbidden** on every call (first real Groq run, 2026-11-04) = Cloudflare blocking urllib's default `Python-urllib/3.x` User-Agent, not the key (bad key = 401). PR #16: every model request sends `User-Agent: CuraAI/0.1 (CS302 prototype)`; setup check no longer calls 403 a bad key.
- **M3 rubric (2026-11-06)** → PR #17. Where each requirement lives: README "CS302 M3 requirements" table. Run: clone → `pip install -e ".[web,dev]"` → `copy .env.example .env` → paste `CURAAI_GROQ_API_KEY` → `python -m curaai.app.check` → `pytest` → `python -m curaai.app.main`. Demo script: `docs/DEMO.md` (3 min). **HITL gate**: every review packet opens one; only `CURAAI_HITL_APPROVERS` (default `dr-demo`) can approve a reply (sent as "Reply approved by dr-demo") or return the case; others → `hitl_blocked`. **Run log**: `/runlog` (this server session) or `python -m curaai.app.runlog`. **Main honest**: governance config in Main (`CURAAI_MAX_MODEL_CALLS/_LOOKUPS/_FOLLOW_UPS/_CASE_COST_USD`, `CURAAI_FOLLOW_UP_TIMEOUT_HOURS`, `CURAAI_HITL_APPROVERS`); transports get their HTTP client from Main. **Tests**: `tests/conftest.py` blocks the network; guardrail-failure test = `test_guardrail_failure_prompt_injection_disables_ai_and_fixed_pull_still_runs`.
- A **307** in the server window (`GET / 307 Temporary Redirect`) is normal: `/` forwards to `/mockchart`.
- **Stuck "Watching the In Basket…" fixed (PR #11)**: panel now restores each patient's status from the server on reload; MockChart **Reset test data** and a new **Re-run** button re-screen patients; panel says "Can't reach the CuraAI server" when it's down; server refuses to start with a plain message if port 8000 is taken (old server still open) or a setting is wrong.
- Bridge **resends after a server restart** (server instance id at `/api/health`); a normal reload still sends nothing twice.
- Trend question reworded to *"Have your symptoms been getting better, getting worse, or staying about the same?"* (old "Since they started…" read like an onset question).
- Re-captured MockChart data after the team added **amlodipine (stopped Aug 18)** + an Aug 18 visit to Ellison; the parity test caught it.

## Open questions for the team
1. **Urgent symptoms**: nothing fast-tracks chest pain (MockChart p5). Add a red-flag rule?
2. Symptom + follow-up **catalogs are drafts**; they need clinician sign-off (ADR-009).
3. A message arriving mid-processing opens a new case. OK?

## How to run
**If it's not working:** run `python -m curaai.app.check` first (shows `.env` settings with keys hidden, port in use, page found, Gemini test call).

**Demo (no cloud account; uses the local reader by default):** `pip install -e ".[web]"`, copy `.env.example` to `.env`, run `python -m curaai.app.main`, open http://127.0.0.1:8000/mockchart. Use the CuraAI panel (bottom right) → **Open review**.

**Tests:**
```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev,web]"   # web extra lets the FastAPI route test run
pytest          # 231 tests (+1 FastAPI route test with the web extra), offline
lint-imports    # Dependency Rule check
```
Re-capture FHIR test data from the MockChart page: `python tests/fixtures/fhir/capture.py`
Record a real openFDA response (needs internet): `python tests/fixtures/openfda/capture.py lisinopril`
> The openFDA test fixture uses **synthetic** label text. Run the capture once to check against a real label.

## Next steps
- [x] Merge PR #1 → #2 → #3 / #4 (core, EHR, drug adapters are on `main`)
- [x] PR #5 retargeted to `main` and merged
- [x] PR #6 → #7 → #8 merged
- [x] PR #9 merged
- [x] PR #10 merged (Gemini)
- [x] PR #11 merged
- [x] PR #12 merged
- [x] PR #13 merged
- [x] PR #14 + #15 merged
- [x] PR #16 merged
- [ ] Merge PR #17 (M3 readiness), everyone `git pull`
- [ ] Record the 3-minute demo (or rehearse it live) with Groq, following `docs/DEMO.md`
- [ ] Each teammate: `.env` from the new `.env.example` (now defaults to Groq + governance settings)
- [ ] Each teammate: Groq key → `.env` (`CURAAI_MODEL_BACKEND=groq`, `CURAAI_GROQ_API_KEY`) → `python -m curaai.app.check` (first real Groq run)
- [ ] ADR-001 amendment: add Groq (synthetic data only; BAA before real PHI)
- [ ] Pick a backup model from the setup check's list and add `CURAAI_GEMINI_FALLBACK_MODEL` to each `.env`
- [ ] RJ: pull, run `python -m curaai.app.check`, follow the `[FAIL]`/`[WARN]` line, re-run the demo
- [ ] Someone gets a Gemini key and runs the demo with `CURAAI_MODEL_BACKEND=gemini` (first real model run)
- [ ] ADR-001 amendment: Gemini (AI Studio for synthetic data; Vertex AI + BAA before real PHI)
- [x] Demo reads messages and pulls the onset-based chart window with no AWS account (local reader)
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
- **2026-10-27**: The demo wasn't really reading charts: with no AI backend it couldn't read messages, so the chart window started at the message date and missed the key history. Added the **local rule-based reader** as the default backend; all six MockChart patients now go end to end in the browser with the right windows (e.g. Ellison Sep 18 → Oct 16 incl. lisinopril increase, flagged for dry cough). Found that the automated-label + 12-call cap change had missed PR #8's merge; brought it into PR #9. Bridge now resends after a server restart. 203 tests passing.
- **2026-10-27 (later)**: Group asked for a real AI model. Added **Google Gemini** as a model backend (PR #10): `generateContent` REST, key in a header from `.env`, JSON answers, low thinking, falls back cleanly on any Gemini error. Tested with a fake HTTP client end to end through `main.py` (Whitaker case); the first real call needs a teammate's key on their machine. 214 tests passing.
- **2026-10-28**: Team reported the panel stuck on "Watching the In Basket…" (worked the night before). Reproduced it: on reload with the same server, or after MockChart's Reset, the bridge skipped already-sent messages and showed nothing. Nobody changed `.env` in GitHub (it's never committed). Fixed in PR #11: status restored from the server, Reset/Re-run re-screen, clear server-down message, friendly start-up errors, and `python -m curaai.app.check`. Verified in a browser (fresh, reload, reset, re-run, server down). 222 tests passing.
- **2026-10-28 (later)**: Asked why reviews say "AI screening was unavailable". Gap found: the audit log kept only the error type, not Gemini's reason. PR #12: log the real (scrubbed) message, retry Gemini rate limits/outages with Google's delay, normalize harmless answer formats. Likely cause on the demo: six patients at once exceed a free key's per-minute limit. 231 tests passing.
- **2026-11-02**: RJ's audit log showed Gemini `extract_symptoms` timing out at ~30 s. PR #13: 60 s adjustable timeout, one retry on timeout, clearer error wording, two-step Gemini check (fast model lookup, then a timed answer) with hints for blocked network vs slow model. 241 tests passing.
- **2026-11-02 (later)**: PR #13 merged. Asked how to fix error 503: it's Gemini's "model overloaded" (Google-side). PR #14: optional backup model (`CURAAI_GEMINI_FALLBACK_MODEL`) after the main model's retries, 503-specific hint in the setup check, backup-model check that lists usable model names. 248 tests passing.
- **2026-11-04**: Team hit free-tier limits ("too much traffic, not enough tokens") and chose Groq as the new API. PR #15: `GroqTransport`, shared `http_transport.py` (Gemini refactored onto it, behavior unchanged), quota savers (reading-only mode, 8/min pacing, reply cache), Groq setup check. 275 tests passing. Not yet run against real Groq (sandbox can't reach it).
- **2026-11-04 (later)**: First real Groq run: server and key OK, but every Groq call returned a bare `HTTP 403: Forbidden`. Cause: urllib's default User-Agent blocked by Cloudflare. PR #16 sends a CuraAI User-Agent on all model requests, plus a clearer 403 hint. 277 tests passing.
- **2026-11-06**: Checked the repo against the five M3 requirements and the M2 Governance Appendix. Gaps: HITL gate only structural (nothing fired), no readable run log, default caps in Ring 2, transports building their own HTTP clients, no proof tests can't hit the network, README not grader-shaped. PR #17 closes all of them: HITL sign-off gate (domain rule + use case + review panel + bridge), run log, governance config in Main, network guard, README "Run it in 10 minutes" + requirements map + governance table, docs/DEMO.md. Ran real pytest + FastAPI for the first time (pip via proxy): 318 passed, 3/3 import contracts. Verified from a fresh GitHub clone (install 7 s) and walked the demo in Chromium (local reader, and Groq unreachable → off-ramp on every case, still gated).
