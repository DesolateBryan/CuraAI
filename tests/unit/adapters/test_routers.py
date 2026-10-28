"""Smoke test for the humble FastAPI routes. Runs when FastAPI + httpx are installed
(pip install -e ".[dev,web]"); skipped otherwise. All logic is tested in test_main_and_web.py."""

import tempfile
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from curaai.app.main import Config, build_app, build_container  # noqa: E402
from tests.unit.app.test_main_and_web import body  # noqa: E402


def test_routes_delegate_to_the_controller():
    with tempfile.TemporaryDirectory() as tmp:
        config = Config.from_env({"CURAAI_AUDIT_LOG_PATH": str(Path(tmp) / "a.jsonl"),
                                  "CURAAI_CLOCK_NOW": "2026-10-16T13:00:00-04:00", "CURAAI_SWEEP_SECONDS": "0"})
        with TestClient(build_app(build_container(config), config)) as client:
            health = client.get("/api/health").json()
            assert health["status"] == "ok" and len(health["instance"]) == 12
            r = client.post("/api/messages", json=body("p1"))
            assert r.status_code == 200 and r.json()["outcome"] == "packet_delivered"
            case = r.json()["case_id"]
            assert client.get(f"/api/reviews/{case}").json()["case_id"] == case
            assert "Verify in person" in client.get(f"/reviews/{case}").text
            assert client.post("/api/messages", content=b"not json").status_code == 400
            assert client.get("/api/outbox").json() == {"follow_ups": []}
            assert "curaai-bridge.js" in client.get("/mockchart").text
            assert client.get("/static/curaai-bridge.js").headers["content-type"].startswith("application/javascript")
