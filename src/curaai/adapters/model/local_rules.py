"""LocalRulesTransport: a rule-based stand-in for the model, for demos with no cloud account.

CURAAI_MODEL_BACKEND=local. It sits exactly where Bedrock sits (a VendorTransport
behind the ModelGateway), so it receives the same redacted JSON requests, answers
with the same JSON shapes, and every answer still goes through the parsers, the
audit log and the core's ModelOutputValidator. Nothing else in the system knows
which backend is running.

What it does, all with plain pattern rules (pure functions below):
  * extract_symptoms  catalog symptoms named in the message, skipping negated
                      ones ("No fever"); the onset date ("around October 9th",
                      "since last Friday", "about an hour ago"); approximate
                      wording; the trend ("getting worse", "about the same")
  * follow-up choice  the catalog question that covers every missing detail
  * relevant items    medications whose known side effects match the symptoms,
                      and labs commonly checked for them
  * flags             possible adverse effect / possible interaction

It is NOT the product's model. ADR-002 rejected rule-based screening for
production (option 4: poor handling of free text). It exists so the demo can
read messages and pull the right chart window without AWS, and it gives the
evaluation set (ADR-016) a deterministic baseline to compare the real model with.
The side-effect table is demo knowledge taken from MockChart's synthetic drug
list, not clinical reference data. Like a real model, it sees only what the
request carries: patient words, ids and short labels, never chart text.
"""

import json
import re
from datetime import date, timedelta

from curaai.adapters.model.gateway import VendorReply

MODEL_NAME = "local-rules-v1"

# ---- symptom vocabulary (catalog id -> patterns) ------------------------------------------
SYMPTOM_PATTERNS: dict[str, tuple[str, ...]] = {
    "cough": (r"\bcough",),
    "fever": (r"\bfever", r"\bfeverish", r"\b10[0-4](?:\.\d)?\s*(?:°|degrees|f\b)?"),
    "sore_throat": (r"\bsore throat",),
    "hoarseness": (r"\bhoarse",),
    "shortness_of_breath": (r"\bshort(?:ness)? of breath", r"\btrouble breathing", r"\bcan'?t breathe"),
    "wheezing": (r"\bwheez",),
    "chest_pain": (r"\bchest (?:pain|tight|pressure|discomfort)",),
    "palpitations": (r"\bheart (?:has been |is |was |keeps )?(?:racing|pounding|fluttering)", r"\bpalpitation"),
    "tremor": (r"\bshak(?:y|iness|ing)\b", r"\btremor", r"\btrembl"),
    "dizziness": (r"\bdizz",),
    "lightheadedness": (r"\blight-?headed",),
    "nausea": (r"\bnause",),
    "vomiting": (r"\bvomit", r"\bthrowing up"),
    "diarrhea": (r"\bdiarrh",),
    "abdominal_pain": (r"\b(?:stomach|abdominal|belly) (?:pain|ache|cramp)", r"\bstomachache"),
    "headache": (r"\bheadache", r"\bmigraine"),
    "vision_change": (r"\bblurr", r"\bvision (?:change|problem|loss)"),
    "weakness": (r"\bweak(?:ness)?\b",),
    "fatigue": (r"\btired", r"\bfatigue", r"\bexhausted"),
    "rash": (r"\brash", r"\bhives"),
    "sweating": (r"\bsweat",),
    "insomnia": (r"\binsomnia", r"\bcan'?t sleep", r"\btrouble sleeping", r"\bkeeps? me up"),
}
NEGATION = re.compile(r"\b(?:no|not|without|denies|never|haven'?t had)\b[^.!?;,]*$", re.IGNORECASE)

# ---- onset ------------------------------------------------------------------------------------
MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
     "november", "december"], start=1)}
MONTHS.update({m[:3]: i for m, i in list(MONTHS.items())})
MONTHS["sept"] = 9
WEEKDAYS = {d: i for i, d in enumerate(["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"])}
NUMBER_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
                "a couple": 2, "a couple of": 2, "couple": 2, "a few": 3, "few": 3, "several": 4}
# Relative phrases ("today", "Wednesday", "a week") only count as an onset when the text
# talks about starting, so "slightly better today" is not read as a start date.
START_CUE = re.compile(r"\b(?:start\w*|began|begun|beginning|came on|since|ago|first noticed|been going on)\b",
                       re.IGNORECASE)
APPROX = re.compile(r"\b(?:around|about|roughly|approximately|maybe|i think|probably|or so|a few|a couple|ish)\b",
                    re.IGNORECASE)

# ---- trend ------------------------------------------------------------------------------------
TREND_RULES = (   # first match wins
    ("unchanged", r"\b(?:about|pretty much|more or less|stayed|staying) the same\b|\bunchanged\b|\bno change\b"),
    ("worsening", r"\b(?:getting|got|gotten|feels?|is|are|been)?\s*(?:a (?:bit|little) |much |even |definitely )?worse\b"
                  r"|\bworsening\b|\bmore (?:frequent|often|severe)\b|\bhasn'?t let up\b"),
    ("improving", r"\b(?:getting|got|gotten|feels?|been)\s*(?:a (?:bit|little) |much )?better\b|\bimproving\b"),
)

# ---- demo knowledge: synthetic, from MockChart's drug list, not clinical reference --------------
SIDE_EFFECTS: dict[str, frozenset[str]] = {
    "lisinopril": frozenset({"cough", "dizziness", "lightheadedness"}),
    "amlodipine": frozenset({"dizziness"}),
    "metformin": frozenset({"nausea", "diarrhea", "abdominal_pain"}),
    "sertraline": frozenset({"nausea", "dizziness", "tremor", "sweating", "insomnia"}),
    "cyclobenzaprine": frozenset({"dizziness", "fatigue"}),
    "ibuprofen": frozenset({"abdominal_pain", "nausea"}),
    "omeprazole": frozenset({"headache"}),
    "levothyroxine": frozenset({"palpitations", "tremor", "insomnia", "sweating"}),
    "albuterol": frozenset({"tremor", "palpitations"}),
    "fluticasone": frozenset({"hoarseness"}),
    "ferrous": frozenset({"nausea", "abdominal_pain"}),
    "metoprolol": frozenset({"fatigue", "dizziness"}),
    "sumatriptan": frozenset({"chest_pain"}),
    "contraceptive": frozenset({"headache", "nausea"}),
    "spironolactone": frozenset({"dizziness"}),
    "cetirizine": frozenset({"fatigue"}),
}
INTERACTIONS: tuple[tuple[str, str, frozenset[str]], ...] = (
    ("sertraline", "cyclobenzaprine", frozenset({"dizziness", "nausea", "tremor", "sweating", "palpitations"})),
    ("sertraline", "sumatriptan", frozenset({"dizziness", "nausea", "tremor", "sweating", "palpitations"})),
    ("lisinopril", "spironolactone", frozenset({"weakness", "palpitations"})),
)
LABS_FOR: dict[str, tuple[str, ...]] = {
    "palpitations": ("tsh", "free t4", "potassium"),
    "tremor": ("tsh", "free t4"),
    "dizziness": ("sodium", "potassium"),
    "lightheadedness": ("sodium", "hemoglobin"),
    "nausea": ("sodium",),
    "chest_pain": ("troponin", "ecg"),
    "shortness_of_breath": ("troponin", "ecg", "peak flow"),
    "fatigue": ("hemoglobin", "ferritin", "tsh", "a1c"),
    "cough": ("potassium",),
    "wheezing": ("peak flow",),
}


# ---- pure rules ----------------------------------------------------------------------------------
def find_symptoms(text: str, allowed: set[str]) -> list[str]:
    lowered = text.lower()
    found = []
    for symptom, patterns in SYMPTOM_PATTERNS.items():
        if symptom not in allowed:
            continue
        for pattern in patterns:
            match = next((m for m in re.finditer(pattern, lowered) if not _negated(lowered, m.start())), None)
            if match:
                found.append(symptom)
                break
    return found


def _negated(text: str, start: int) -> bool:
    clause_start = max(text.rfind(c, 0, start) for c in ".!?;") + 1
    return bool(NEGATION.search(text[clause_start:start]))


def find_onset(text: str, reference: date) -> tuple[date | None, bool]:
    """(onset date, is_approximate). Explicit dates win; relative phrases need a start cue."""
    lowered = text.lower()
    approx = bool(APPROX.search(lowered))
    month_names = "|".join(sorted(MONTHS, key=len, reverse=True))

    m = re.search(rf"\b({month_names})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b", lowered)
    if m:
        return _in_past_year(MONTHS[m.group(1)], int(m.group(2)), reference), approx
    m = re.search(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", lowered)
    if m:
        year = int(m.group(3)) + (2000 if m.group(3) and len(m.group(3)) == 2 else 0) if m.group(3) else None
        day = _safe_date(year, int(m.group(1)), int(m.group(2))) if year else \
            _in_past_year(int(m.group(1)), int(m.group(2)), reference)
        return day, approx

    if not START_CUE.search(lowered):
        return None, False
    m = re.search(r"\b(last\s+)?(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", lowered)
    if m:
        back = (reference.weekday() - WEEKDAYS[m.group(2)]) % 7 or 7
        return reference - timedelta(days=back), approx
    if re.search(r"\b(?:today|this morning|this afternoon|tonight|an? (?:few )?hours? ago|\d+ hours? ago|just now)\b", lowered):
        return reference, approx
    if re.search(r"\byesterday\b", lowered):
        return reference - timedelta(days=1), approx
    number = "|".join(sorted((re.escape(k) for k in NUMBER_WORDS), key=len, reverse=True))
    m = re.search(rf"\b(\d+|{number})\s+(day|week|month)s?\s+ago\b", lowered)
    if m:
        n = int(m.group(1)) if m.group(1).isdigit() else NUMBER_WORDS[m.group(1)]
        days = {"day": 1, "week": 7, "month": 30}[m.group(2)] * n
        return reference - timedelta(days=days), approx or not m.group(1).isdigit()
    if re.search(r"\b(?:last|a|one) week\b", lowered):
        return reference - timedelta(days=7), True
    return None, False


def _in_past_year(month: int, day: int, reference: date) -> date | None:
    candidate = _safe_date(reference.year, month, day)
    if candidate and candidate > reference:
        candidate = _safe_date(reference.year - 1, month, day)
    return candidate


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def find_trend(text: str) -> str | None:
    lowered = text.lower()
    for trend, pattern in TREND_RULES:
        if re.search(pattern, lowered):
            return trend
    return None


def drug_key(label: str) -> str | None:
    lowered = label.lower()
    return next((k for k in SIDE_EFFECTS if k in lowered), None)


def relevant_item_ids(symptoms: set[str], items: list[dict]) -> list[str]:
    wanted_labs = {lab for s in symptoms for lab in LABS_FOR.get(s, ())}
    picked = []
    for item in items:
        label = item.get("label", "").lower()
        key = drug_key(label)
        if (key and SIDE_EFFECTS[key] & symptoms) or any(lab in label for lab in wanted_labs):
            picked.append(item["item_id"])
    return picked


def flag_matches(symptoms: set[str], medications: list[dict], allowed_flags: set[str]) -> list[dict]:
    keys = {m["item_id"]: drug_key(m.get("label", "")) for m in medications}
    present = set(keys.values())
    matches = []
    for item_id, key in keys.items():
        if key is None:
            continue
        if "possible_adverse_effect" in allowed_flags and SIDE_EFFECTS[key] & symptoms:
            matches.append({"item_id": item_id, "flag_id": "possible_adverse_effect"})
        if "possible_interaction" in allowed_flags and any(
                key in (a, b) and {a, b} <= present and caused & symptoms for a, b, caused in INTERACTIONS):
            matches.append({"item_id": item_id, "flag_id": "possible_interaction"})
    return matches


def answer(user_json: str) -> str:
    """One request (as the gateway sends it) -> one JSON reply (as a model would write it)."""
    data = json.loads(user_json)
    if "patient_message" in data:
        text, reference = data["patient_message"], date.fromisoformat(data["message_date"])
        onset, approx = find_onset(text, reference)
        return json.dumps({
            "symptom_ids": find_symptoms(text, set(data.get("allowed_symptom_ids", ()))),
            "onset": onset.isoformat() if onset else None,
            "onset_is_approx": bool(onset) and approx,
            "trend": find_trend(text),
        })
    if "candidate_question_ids" in data:
        candidates = sorted(data["candidate_question_ids"])
        preferred = "ask_onset_and_trend" if "ask_onset_and_trend" in candidates else None
        return json.dumps({"question_id": preferred or candidates[0]})
    if "medications" in data:
        return json.dumps({"matches": flag_matches(set(data["symptom_ids"]), data["medications"], set(data["flag_ids"]))})
    if "items" in data:
        return json.dumps({"item_ids": relevant_item_ids(set(data["symptom_ids"]), data["items"])})
    return "{}"


class LocalRulesTransport:
    """VendorTransport with no network and no cost: the rules above answer every request."""

    def send(self, system: str, user: str, max_output_tokens: int) -> VendorReply:
        return VendorReply(text=answer(user), input_tokens=0, output_tokens=0, model=MODEL_NAME)
