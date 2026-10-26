"""OpenFdaAdapter: DrugDbPort over the openFDA drug label API (api.fda.gov/drug/label.json).

Humble object split (ADR-014):
  * build_label_url and openfda_to_drug_record are pure functions, tested with fixed JSON
  * OpenFdaAdapter makes ONE GET through an injected HttpClient and passes the JSON on

Rules:
  * only the drug name is sent, never patient data (ADR-010)
  * label text is copied verbatim and NEVER truncated (ADR-004). MockChart's page
    trims to 900 characters for display; the backend keeps the whole label and
    leaves layout to the presenter
  * the label used must name EXACTLY the drug we asked for (generic or brand name).
    openFDA phrase search also returns combination products ("lisinopril and
    hydrochlorothiazide"), so we ask for a few results and take the first exact
    match, or None. A loose match is worse than "not found"
  * source_ref = "openfda:spl/<set_id>@<effective_time>", so the physician can
    open the exact label version that was shown
  * no name guessing: "Albuterol HFA" is searched as written. Mapping chart names to
    canonical drug names is terminology work, deferred (ADR-017)
"""

from collections.abc import Mapping
from typing import Protocol
from urllib.parse import quote

from curaai.application.dto.drug import DrugQuery, DrugRecord
from curaai.application.errors import ExternalSourceUnavailable
from curaai.application.ports.drug_db_port import DrugDbPort

BASE_URL = "https://api.fda.gov/drug/label.json"
JOIN = "\n\n"
RESULT_LIMIT = 5


class HttpNotFound(Exception):
    """The HTTP client raises this for a 404. openFDA answers 404 when nothing matches."""


class HttpClient(Protocol):
    def get_json(self, url: str, timeout_s: float) -> Mapping: ...


# ---- pure functions -------------------------------------------------------------
def build_label_url(drug_name: str, base_url: str = BASE_URL) -> str:
    phrase = quote(f'"{drug_name.strip()}"', safe="")
    return f"{base_url}?search=openfda.generic_name:{phrase}+openfda.brand_name:{phrase}&limit={RESULT_LIMIT}"


def openfda_to_drug_record(payload: Mapping, query: DrugQuery) -> DrugRecord | None:
    results = payload.get("results") if isinstance(payload, Mapping) else None
    if not isinstance(results, list):
        return None
    wanted = query.drug_name.strip().casefold()
    label = next((r for r in results if isinstance(r, Mapping) and wanted in _names(r)), None)
    if label is None:
        return None
    names = label.get("openfda") or {}

    set_id = label.get("set_id") or label.get("id")
    version = label.get("effective_time")
    source_ref = f"openfda:spl/{set_id}@{version}" if set_id and version else (f"openfda:spl/{set_id}" if set_id else "")
    return DrugRecord(
        drug_name=(names.get("generic_name") or [query.drug_name])[0],
        source_ref=source_ref,
        class_text=_text(names.get("pharm_class_epc"), sep="; "),
        adverse_text=_text(label.get("adverse_reactions")),
        interactions_text=_text(label.get("drug_interactions")),
        boxed_warning_text=_text(label.get("boxed_warning")),
        contraindications_text=_text(label.get("contraindications")),
    )


def _names(label: Mapping) -> set[str]:
    names = label.get("openfda") or {}
    return {n.strip().casefold() for n in (names.get("generic_name") or []) + (names.get("brand_name") or [])
            if isinstance(n, str)}


def _text(value: object, sep: str = JOIN) -> str | None:
    if isinstance(value, str):
        return value or None
    if isinstance(value, list):
        joined = sep.join(v for v in value if isinstance(v, str) and v)
        return joined or None
    return None


# ---- humble adapter ---------------------------------------------------------------
class OpenFdaAdapter(DrugDbPort):
    def __init__(self, http: HttpClient, base_url: str = BASE_URL, timeout_s: float = 8.0) -> None:
        self._http = http
        self._base_url = base_url
        self._timeout = timeout_s

    def lookup(self, query: DrugQuery) -> DrugRecord | None:
        url = build_label_url(query.drug_name, self._base_url)
        try:
            payload = self._http.get_json(url, self._timeout)
        except HttpNotFound:
            return None
        except Exception as exc:                     # network, TLS, rate limit, bad JSON
            raise ExternalSourceUnavailable(f"openFDA lookup failed for {query.drug_name!r}: {exc}") from exc
        return openfda_to_drug_record(payload, query)
