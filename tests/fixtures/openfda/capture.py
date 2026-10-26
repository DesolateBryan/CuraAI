"""Record a REAL openFDA response for one drug, to compare against the synthetic fixture.

Run from the repo root on a machine with internet access:
    python tests/fixtures/openfda/capture.py lisinopril
Writes tests/fixtures/openfda/real_<drug>.json. Only the drug name is sent.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from curaai.adapters.drug import UrllibHttpClient, build_label_url  # noqa: E402

drug = sys.argv[1] if len(sys.argv) > 1 else "lisinopril"
payload = UrllibHttpClient().get_json(build_label_url(drug), timeout_s=15)
out = Path(__file__).with_name(f"real_{drug.replace(' ', '_')}.json")
out.write_text(json.dumps(payload, indent=1), encoding="utf-8")
print(f"wrote {out}: {len(payload.get('results', []))} result(s)")
