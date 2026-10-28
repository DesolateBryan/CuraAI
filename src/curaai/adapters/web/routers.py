"""FastAPI routes (humble). Each route calls ONE WebController method and returns its result.

All validation, status codes and response shapes live in controller.py, which is
tested without FastAPI. This file only adapts HTTP to those calls, so a smoke test
(tests/unit/adapters/test_routers.py, runs when FastAPI is installed) covers it.
Imported only by app/main.py.

Routes
    POST /api/messages               bridge posts a patient message + FHIR bundle
    GET  /api/outbox                 follow-up questions for the bridge to deliver
    GET  /api/reviews/{case_id}      review as JSON
    GET  /reviews/{case_id}          review as an HTML page (shown to the physician)
    GET  /api/patients/{id}/review   latest case for a patient
    POST /api/sweep                  run the 24-hour timeout sweep now
    GET  /api/health
    GET  /mockchart                  the team's MockChart page with the bridge script added
    GET  /static/curaai-bridge.js
"""

import asyncio
import contextlib
import json

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.concurrency import run_in_threadpool

from curaai.adapters.web.controller import WebController, WebResponse
from curaai.adapters.web.page import inject_bridge


def _respond(r: WebResponse) -> Response:
    if r.media_type == "text/html":
        return HTMLResponse(r.body, status_code=r.status)
    return JSONResponse(r.body, status_code=r.status)


def create_app(controller: WebController, *, page_html: str | None, bridge_js: str,
               sweep_every_s: float | None = 60.0) -> FastAPI:
    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI):
        task = asyncio.create_task(_sweep_forever(controller, sweep_every_s)) if sweep_every_s else None
        yield
        if task:
            task.cancel()

    app = FastAPI(title="CuraAI", version="0.1.0", lifespan=lifespan,
                  description="Clinical Record Triage and Historical Pre-Fetch (prototype, synthetic data only)")
    served_page = inject_bridge(page_html) if page_html else None

    @app.post("/api/messages")
    async def post_message(request: Request) -> Response:
        try:
            body = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            body = None
        return _respond(await run_in_threadpool(controller.post_message, body))

    @app.get("/api/outbox")
    async def outbox(patient_id: str | None = None) -> Response:
        return _respond(await run_in_threadpool(controller.get_outbox, patient_id))

    @app.get("/api/reviews/{case_id}")
    async def review_json(case_id: str) -> Response:
        return _respond(controller.get_review_json(case_id))

    @app.get("/reviews/{case_id}")
    async def review_html(case_id: str) -> Response:
        return _respond(controller.get_review_html(case_id))

    @app.get("/api/patients/{patient_id}/review")
    async def latest_review(patient_id: str) -> Response:
        return _respond(controller.get_latest_for_patient(patient_id))

    @app.post("/api/sweep")
    async def sweep() -> Response:
        return _respond(await run_in_threadpool(controller.sweep))

    @app.get("/api/health")
    async def health() -> Response:
        return _respond(controller.health())

    @app.get("/")
    async def root() -> Response:
        return RedirectResponse("/mockchart" if served_page else "/docs")

    @app.get("/mockchart")
    async def mockchart() -> Response:
        if served_page is None:
            return HTMLResponse("<p>MockChart page not found. Set CURAAI_MOCKCHART_PAGE.</p>", status_code=404)
        return HTMLResponse(served_page)

    @app.get("/static/curaai-bridge.js")
    async def bridge() -> Response:
        return Response(bridge_js, media_type="application/javascript")

    return app


async def _sweep_forever(controller: WebController, every_s: float) -> None:
    while True:
        await asyncio.sleep(every_s)
        with contextlib.suppress(Exception):
            await run_in_threadpool(controller.sweep)
