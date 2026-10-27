"""
FastAPI app: triage endpoint plus the operator console page.

    uvicorn src.api.app:app --port 8000

The engine (model, index, classifiers) loads once at start-up, about 20-40 s.
Tests inject a fake engine through `create_app(engine=...)`.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src.triage.config import CONFIG_DIR

STATIC_DIR = Path(__file__).parent / "static"


class TriageRequest(BaseModel):
    text: str = Field(..., max_length=1000, description="The farmer's question (any language).")
    district: str | None = Field(None, description="district_clean value from the caller profile.")
    crop: str | None = Field(None, description="Crop from the caller profile, if known.")
    month: int | None = Field(None, ge=1, le=12, description="Month of the call (season is derived).")


def _examples(engine) -> list[dict]:
    """Probe questions with the route the engine actually gives (run once at start-up)."""
    probes = pd.read_csv(CONFIG_DIR / "gate_probes.csv", dtype=str, keep_default_na=False)
    return [
        {"text": p.text, "lang": p.lang, "crop": p.profile_crop or None, "expected": p.expected_route,
         "route": engine.triage(p.text, crop=p.profile_crop or None)["route"]}
        for p in probes.itertuples()
    ]


def create_app(engine=None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if engine is None:
            from src.triage.engine import TriageEngine

            app.state.engine = TriageEngine.load()
        else:
            app.state.engine = engine
        app.state.examples = _examples(app.state.engine)
        yield

    app = FastAPI(title="KCC Farmer Helpline - Triage API", version="0.2.0", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def console():
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/health")
    def health(request: Request):
        eng = request.app.state.engine
        return {"status": "ok", "kb_records": len(eng.retriever)}

    @app.get("/api/meta")
    def meta(request: Request):
        return {**request.app.state.engine.meta(), "examples": request.app.state.examples}

    @app.post("/api/triage")
    def triage(req: TriageRequest, request: Request):
        if not req.text.strip():
            raise HTTPException(status_code=422, detail="text must not be empty")
        return request.app.state.engine.triage(req.text, district=req.district, crop=req.crop, month=req.month)

    return app


app = create_app()
