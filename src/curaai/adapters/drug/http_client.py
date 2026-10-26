"""UrllibHttpClient: the HttpClient OpenFdaAdapter uses in production. Standard library only.

Humble: one GET, decode JSON, map 404 to HttpNotFound. Constructed in app/main.py.
"""

import json
import urllib.error
import urllib.request
from collections.abc import Mapping

from curaai.adapters.drug.openfda_adapter import HttpNotFound


class UrllibHttpClient:
    def __init__(self, user_agent: str = "CuraAI/0.1 (CS302 prototype)") -> None:
        self._headers = {"User-Agent": user_agent, "Accept": "application/json"}

    def get_json(self, url: str, timeout_s: float) -> Mapping:
        request = urllib.request.Request(url, headers=self._headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout_s) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise HttpNotFound(url) from exc
            raise
