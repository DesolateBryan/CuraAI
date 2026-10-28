"""Synthetic MockChart data (no real PHI), copied from the MockChart HTML test EHR.

Shapes mirror the page's `P` array so the fixture is easy to keep in sync.
source_ref values match the ids the page's FHIR tab produces
(MedicationRequest/p1-mr0, Observation/p1-ob0, Encounter/p1-en0, ...).
"""

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from curaai.application.dto.drug import DrugRecord
from curaai.application.dto.ehr import ChartItemRecord
from curaai.application.dto.messaging import InboundMessage

CLINIC_TZ = timezone(timedelta(hours=-4))          # America/New_York in October (EDT)
TODAY = date(2026, 10, 16)                         # MockChart's fixed "today"
NOW = datetime(2026, 10, 16, 13, 0, tzinfo=CLINIC_TZ)

# meds: [name, sig, start, end, note, prescriber]
# labs: [date, component, value, range, flag, source]
# visits: [date, type, provider, note]
PATIENTS = {
    "p1": {
        "name": "Ellison, Margaret R.",
        "meds": [["Lisinopril", "20 mg PO daily", "2025-02-10", "2026-09-22", "Dose increased: home BP log elevated", "Dr. S. Whitfield"],
                 ["Lisinopril", "40 mg PO daily", "2026-09-22", None, "Increased from 20 mg", "Dr. S. Whitfield"],
                 ["Metformin", "1000 mg PO BID", "2024-06-03", None, "", "Dr. S. Whitfield"],
                 ["Atorvastatin", "40 mg PO nightly", "2025-02-10", None, "", "Dr. S. Whitfield"],
                 ["Amlodipine", "5 mg PO daily", "2025-02-10", "2026-08-18", "Discontinued: ankle swelling", "Dr. S. Whitfield"]],
        "labs": [["2026-09-22", "Hemoglobin A1c", "7.4 %", "4.0–5.6", "H", "Quest Diagnostics"],
                 ["2026-09-22", "Potassium", "4.6 mmol/L", "3.5–5.1", "", "Quest Diagnostics"],
                 ["2026-09-22", "Creatinine", "0.92 mg/dL", "0.60–1.10", "", "Quest Diagnostics"],
                 ["2026-07-14", "LDL cholesterol", "88 mg/dL", "<100", "", "Quest Diagnostics"]],
        "visits": [["2026-09-29", "Ophthalmology", "Dr. L. Okafor", "Diabetic eye exam. No retinopathy. Return 12 months."],
                   ["2026-09-22", "Office visit – Primary Care", "Dr. S. Whitfield", "BP 148/92, home log elevated. Increase lisinopril to 40 mg daily. Recheck BMP in 2 weeks."],
                   ["2026-08-18", "Office visit – Primary Care", "Dr. S. Whitfield", "Bilateral ankle swelling attributed to amlodipine. Discontinue amlodipine 5 mg. Continue lisinopril 20 mg."],
                   ["2026-06-10", "Cardiology", "Dr. P. Anand", "Stable HTN. Continue current regimen. Echo normal."]],
        "message": ("2026-10-16T07:42:00", "Hi Dr. Whitfield, I've had a dry, tickly cough that started around October 9th. It was mild at first but it's getting worse, especially at night. No fever. Should I be worried?"),
    },
    "p2": {
        "name": "Whitaker, Darnell J.",
        "meds": [["Sertraline", "50 mg PO daily", "2025-11-04", "2026-10-01", "Partial response; increased", "Dr. M. Castellano"],
                 ["Sertraline", "100 mg PO daily", "2026-10-01", None, "Increased from 50 mg", "Dr. M. Castellano"],
                 ["Omeprazole", "20 mg PO daily", "2024-03-18", None, "", "Dr. S. Whitfield"],
                 ["Cyclobenzaprine", "10 mg PO TID PRN spasm", "2026-09-28", None, "Lumbar flare", "Dr. K. Brandt"],
                 ["Ibuprofen", "600 mg PO q8h PRN pain", "2026-09-28", None, "Take with food", "Dr. K. Brandt"]],
        "labs": [["2026-10-08", "Sodium", "134 mmol/L", "135–145", "L", "Quest Diagnostics"],
                 ["2026-09-14", "Sodium", "139 mmol/L", "135–145", "", "Quest Diagnostics"],
                 ["2026-09-14", "Creatinine", "1.0 mg/dL", "0.7–1.3", "", "Quest Diagnostics"]],
        "visits": [["2026-10-01", "Psychiatry", "Dr. M. Castellano", "GAD, partial response to sertraline 50 mg. Increase to 100 mg daily. Follow up in 4 weeks."],
                   ["2026-09-28", "Orthopedics", "Dr. K. Brandt", "Lumbar radiculopathy flare. Start cyclobenzaprine 10 mg TID PRN and ibuprofen 600 mg PRN. PT referral placed."]],
        "message": ("2026-10-16T08:15:00", "I've been feeling dizzy and kind of nauseous lately. Can you tell me what's going on?"),
        "reply": "I think it started around October 5th, a few days after my back appointment. About the same most days, maybe a little worse in the mornings.",
    },
    "p5": {
        "name": "Boateng, Kwame O.",
        "meds": [["Clopidogrel", "75 mg PO daily", "2025-05-02", None, "Post-stent, continue 12 months minimum", "Dr. P. Anand"],
                 ["Metoprolol succinate", "50 mg PO daily", "2025-05-02", None, "", "Dr. P. Anand"],
                 ["Atorvastatin", "80 mg PO nightly", "2025-05-02", None, "High intensity post-ACS", "Dr. P. Anand"],
                 ["Metformin", "500 mg PO BID", "2023-01-15", None, "", "Dr. S. Whitfield"]],
        "labs": [["2026-10-16", "Troponin I", "0.08 ng/mL", "<0.04", "H", "STAT – hospital lab"],
                 ["2026-10-16", "ECG", "Sinus tachycardia, no acute ST changes", "", "", "Office 12-lead"],
                 ["2026-09-02", "LDL cholesterol", "62 mg/dL", "<70", "", "Quest Diagnostics"]],
        "visits": [["2026-05-02", "Cardiology – PCI with drug-eluting stent, LAD", "Dr. P. Anand", "Successful PCI for 90% LAD stenosis. Dual antiplatelet therapy started."],
                   ["2026-09-02", "Office visit – Primary Care", "Dr. S. Whitfield", "Stable post-stent. Continue current regimen. A1c 6.8%."]],
        "message": ("2026-10-16T11:20:00", "I'm having chest tightness and pressure that started about an hour ago, radiating to my left arm. I feel short of breath and a little sweaty. I have my stent history. Should I call 911?"),
    },
}

# MockChart's built-in drug list: key -> (class, adverse effects)
MOCK_DRUG_DB = {
    "lisinopril": ("ACE inhibitor", "Dry cough, hyperkalemia, angioedema, dizziness"),
    "metformin": ("Biguanide", "GI upset, B12 deficiency, lactic acidosis (rare)"),
    "atorvastatin": ("Statin", "Muscle aches, raised liver enzymes"),
    "sertraline": ("SSRI", "Nausea, dizziness, low sodium, serotonin syndrome"),
    "omeprazole": ("Proton pump inhibitor", "Headache, low magnesium with long-term use"),
    "cyclobenzaprine": ("Muscle relaxant", "Drowsiness, dizziness, dry mouth, serotonin syndrome risk"),
    "ibuprofen": ("NSAID", "GI bleeding, kidney injury, raised BP"),
    "clopidogrel": ("P2Y12 inhibitor", "Bleeding, bruising"),
    "metoprolol": ("Beta-blocker", "Fatigue, slow heart rate"),
    "amlodipine": ("Calcium channel blocker", "Ankle swelling, flushing, dizziness"),
}


def _d(s: str | None) -> date | None:
    return date.fromisoformat(s) if s else None


def chart_records(patient_id: str) -> tuple[ChartItemRecord, ...]:
    p = PATIENTS[patient_id]
    records = []
    for i, (name, sig, start, end, note, who) in enumerate(p["meds"]):
        records.append(ChartItemRecord(
            item_id=f"{patient_id}-mr{i}", kind="medication", date=_d(start), end_date=_d(end),
            title=name, detail=f"{sig} · {note}" if note else sig,
            source_ref=f"MedicationRequest/{patient_id}-mr{i}", author=who, stopped=end is not None))
    for i, (day, component, value, ref, flag, source) in enumerate(p["labs"]):
        records.append(ChartItemRecord(
            item_id=f"{patient_id}-ob{i}", kind="lab", date=_d(day), title=component,
            detail=f"{value} (ref {ref})" if ref else value, flag=flag or None,
            source_ref=f"Observation/{patient_id}-ob{i}", author=source))
    for i, (day, kind, provider, note) in enumerate(p["visits"]):
        records.append(ChartItemRecord(
            item_id=f"{patient_id}-en{i}", kind="encounter", date=_d(day), title=kind,
            detail=note, source_ref=f"Encounter/{patient_id}-en{i}", author=provider))
    return tuple(records)


def drug_records() -> dict[str, DrugRecord]:
    return {key: DrugRecord(drug_name=key, source_ref=f"mockdrug:{key}", class_text=cls, adverse_text=adverse)
            for key, (cls, adverse) in MOCK_DRUG_DB.items()}


def inbound(patient_id: str, text: str | None = None, sent_at: datetime | None = None,
            message_id: str | None = None) -> InboundMessage:
    stamp, default_text = PATIENTS[patient_id]["message"]
    sent = sent_at or datetime.fromisoformat(stamp).replace(tzinfo=CLINIC_TZ)
    return InboundMessage(message_id=message_id or f"{patient_id}-m-{sent:%H%M%S}",
                          patient_id=patient_id, sent_at=sent, text=text or default_text)


def all_chart_text(patient_id: str) -> set[str]:
    """Every verbatim detail string, so tests can prove none of it reached the model."""
    return {r.detail for r in chart_records(patient_id)}


FHIR_CAPTURE = Path(__file__).parent / "fhir" / "mockchart_bundles.json"


def fhir_bundles() -> dict[str, dict]:
    """FHIR R4 bundles captured from the real MockChart page (window.MockEpic.connect(key).fhir(id)).

    Regenerate with: python tests/fixtures/fhir/capture.py  (needs Node + Playwright)
    """
    return json.loads(FHIR_CAPTURE.read_text(encoding="utf-8"))["bundles"]

# MockChart's simulated patient: what it answers to an onset question and to a trend question.
# Copied from the page's `reply` objects (p1..p6, in page order).
SCRIPTED_REPLIES = {
    "p1": {"onset": 'It started October 9th, so about a week ago.', "trend": "It's definitely getting worse. It keeps me up at night now."},
    "p2": {"onset": 'I think it started around October 5th, a few days after my back appointment.', "trend": 'About the same most days, maybe a little worse in the mornings.'},
    "p3": {"onset": 'Last Friday, October 9th.', "trend": "It's getting a bit worse. Episodes are more frequent now, maybe 3–4 times a day."},
    "p4": {"onset": 'It started Wednesday, so October 14th.', "trend": 'About the same, maybe slightly better today. The barky cough is still there at night.'},
    "p5": {"onset": 'About an hour ago, it came on while I was resting.', "trend": "If anything it feels a bit worse, the pressure hasn't let up."},
    "p6": {"onset": 'They started around October 2nd, a couple weeks ago now.', "trend": "They've been getting more frequent, almost every other day now instead of once a week."},
}
