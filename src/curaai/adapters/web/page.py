"""inject_bridge: serve the team's MockChart page with the CuraAI bridge script added. Pure.

The team's HTML file is never edited. The backend serves a copy at /mockchart with
one <script> tag appended, so the page and the API share an origin (no CORS) and
the bridge can call window.MockEpic.
"""

BRIDGE_TAG = '<script src="/static/curaai-bridge.js"></script>'


def inject_bridge(page_html: str) -> str:
    if BRIDGE_TAG in page_html:
        return page_html
    marker = page_html.lower().rfind("</body>")
    if marker < 0:
        return page_html + BRIDGE_TAG
    return page_html[:marker] + BRIDGE_TAG + page_html[marker:]
