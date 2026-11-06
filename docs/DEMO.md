# CuraAI demo script (3 minutes)

Follow this script live, or use it to record the screen. It shows the primary use case end to end
(patient message → AI decision → physician-ready review), the HITL gate firing, the readable run
log, and the guardrail-failure test.

**Before you start** (once, about 5 minutes; see the README's *Run it in 10 minutes*):

- `.env` has `CURAAI_MODEL_BACKEND=groq` and your `CURAAI_GROQ_API_KEY`.
- `python -m curaai.app.check` shows `[ OK ] Groq connection` and `[ OK ] Groq test call`.
- Delete `audit.jsonl` if it exists, so the run log starts empty.
- Start the server with `python -m curaai.app.main` and leave that window open.

| Time | Do | Point out |
|---|---|---|
| 0:00 | Show the server window. | The first line reads `model=groq (openai/gpt-oss-20b; reading messages only, max 8/min)`, and the next line names the HITL approvers. Main owns all of this configuration. |
| 0:10 | Open **http://127.0.0.1:8000/mockchart**. | MockChart is the team's test EHR with synthetic patients. CuraAI's bridge sends every patient message, with that patient's FHIR record, to the backend. **Input from the world.** |
| 0:20 | Watch the **CuraAI** panel (bottom right). Each patient moves through *Screening… → Waiting for the patient's answer → Review ready, awaiting physician sign-off*. With 8 AI calls a minute, all six take about 2 minutes, so narrate while they run. | **The AI decision:** Groq reads each message and extracts the symptoms, the onset and the trend. Every answer passes the validator (the guardrail) before it is used. |
| 0:40 | Click **Whitaker** in the In Basket. | His first message gave neither the onset nor the trend, so CuraAI sent a clinician-approved question labeled **"Automated question from CuraAI"**. The simulated patient answered, and the case continued. The AI only picks from fixed questions; it never writes text to the patient. |
| 1:00 | In the panel, click **Open review** for **Ellison** (p1). | **The output a business would use:** a physician briefing with symptoms, onset, trend, a chart window 21 days before onset through today, and a medication change (lisinopril increase) flagged for the cough. Every row is verbatim and carries a source reference. |
| 1:20 | Point at the blue **Awaiting physician sign-off (HITL gate)** box. | **The HITL gate fired.** Nothing written for the patient leaves CuraAI until a physician on the approver list decides. |
| 1:30 | Type `nurse-kim` as the physician id, type a reply (e.g. *Please come in Thursday morning so we can check your blood pressure.*) and click **Approve and send reply**. | The gate refuses: *"Not sent: nurse-kim is not on the approver list."* Nothing reached the patient. |
| 1:45 | Change the id to `dr-demo` and click **Approve and send reply**. | The box turns to **Approved by dr-demo** and shows the time and the reply. |
| 1:55 | Close the review and open Ellison's thread. | The reply appears as **"Reply approved by dr-demo: …"**, and the simulated patient answers it. That answer is not treated as a new sick message. |
| 2:10 | Open **http://127.0.0.1:8000/runlog** in a new tab. | **The readable run log** (observability wrapper): one block per case, with each AI call (model, tokens, cost, latency), the guardrail result, the chart pull, the packet, `HITL GATE`, the blocked attempt (`!! HITL BLOCKED: not_an_approver`), and the approval. At the bottom are the off-ramp rate, failed guardrails, follow-ups, cost per case, and the HITL counts. No patient text appears: the log keeps ids and counts only. |
| 2:35 | In a second terminal: `pytest tests/unit/application/test_pipeline.py -k guardrail -v` | **The guardrail-failure test:** a prompt-injected model answer is rejected, the AI switches off for that case (**the off-ramp fires**), and the fixed chart pull still reaches the physician. The suite uses fakes only; `tests/conftest.py` blocks the network, so no test can call a live model. |
| 2:55 | Done. | |

## If something goes wrong during the demo

- **Groq hits its rate or daily limit** (`HTTP 429`): the review says *"AI screening was unavailable"*. The run log shows `!! AI extract_symptoms failed … -> off-ramp`. That case still gets the fixed chart pull and still goes through the HITL gate, which is itself a live demonstration of the off-ramp. To finish the demo without the AI, set `CURAAI_MODEL_BACKEND=local` and restart.
- **The panel shows "Can't reach the CuraAI server"**: the server window was closed. Start it again; the panel reconnects by itself.
- **You need to run the patients again**: click **Re-run** in the panel. Earlier AI answers are reused, so a re-run costs no Groq quota.

## What each step proves (CS302 M3)

| Requirement | Shown at |
|---|---|
| 2. Use case end to end: input → AI decision → business output | 0:10 – 1:20 |
| 4. Observability wrapper with a readable run log | 2:10 |
| 4. HITL gate firing on a consequential path (a reply to the patient) | 1:20 – 2:10 |
| 3. Guardrail-failure test proving the off-ramp | 2:35 |
| 5. Governance configuration owned by Main | 0:00 (start-up lines) |
