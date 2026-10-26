"""Re-capture tests/fixtures/fhir/mockchart_bundles.json from the MockChart page.

Run from the repo root:  python tests/fixtures/fhir/capture.py
Needs Python Playwright with Chromium (pip install playwright && playwright install chromium).
"""

import json
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[3]
PAGE = next(ROOT.glob("MockChart*.html"))
OUT = Path(__file__).with_name("mockchart_bundles.json")

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.goto(PAGE.as_uri())
    data = page.evaluate("""() => {
        const api = window.MockEpic.connect(window.MockEpic.devKey);
        return {today: api.today, patients: api.patients(),
                bundles: Object.fromEntries(api.patients().map(p => [p.id, api.fhir(p.id)]))};
    }""")
    browser.close()

OUT.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
print(f"wrote {OUT} ({len(data['bundles'])} patients, today={data['today']})")
