"""
Expert review API (Stage 4), mounted by `create_app`.

If EXPERT_TOKEN is set in the environment, every /api/expert call must send it in the
X-Expert-Token header. Without it the dashboard is open, which is only acceptable on a
local machine.
"""
from __future__ import annotations

import os
import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from src.assistant.sessions import CaseConflict
from src.review.workflow import ReviewError, resolve_case

STATUSES = ("pending", "in_review", "answered", "referred")


def require_expert(x_expert_token: str | None = Header(None)) -> None:
    expected = os.getenv("EXPERT_TOKEN")
    if expected and not secrets.compare_digest(x_expert_token or "", expected):
        raise HTTPException(status_code=401, detail="expert token required")


class ClaimRequest(BaseModel):
    expert: str = Field(..., min_length=1, max_length=80)


class ResolveRequest(BaseModel):
    expert: str = Field(..., min_length=1, max_length=80)
    action: str = Field(..., pattern="^(approve_draft|answer|refer)$")
    answer: str = Field("", max_length=2000)
    note: str = Field("", max_length=500)


def _summary(case: dict) -> dict:
    return {
        "case_id": case["case_id"],
        "created_at": case["created_at"],
        "language": case["language"],
        "original_text": case["original_text"],
        "english_text": case["english_text"],
        "reasons": [r.get("code") for r in case["route_reasons"] if isinstance(r, dict)],
        "status": case["status"],
        "assigned_to": case.get("assigned_to"),
        "resolved_by": case.get("resolved_by"),
        "resolved_at": case.get("resolved_at"),
        "has_draft": bool(case.get("draft")),
    }


def _not_found(case_id: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"case {case_id} not found")


def build_router() -> APIRouter:
    router = APIRouter(prefix="/api/expert", dependencies=[Depends(require_expert)], tags=["expert review"])

    @router.get("/cases")
    def list_cases(request: Request, status: str | None = None, language: str | None = None):
        if status and status not in STATUSES:
            raise HTTPException(status_code=422, detail=f"status must be one of {', '.join(STATUSES)}")
        cases = request.app.state.sessions.list_cases(status=status, language=language)
        return {"cases": [_summary(c) for c in cases]}

    @router.get("/stats")
    def stats(request: Request):
        return request.app.state.sessions.stats()

    @router.get("/cases/{case_id}")
    def case_detail(case_id: str, request: Request):
        store = request.app.state.sessions
        case = store.get_expert_case(case_id)
        if case is None:
            raise _not_found(case_id)
        return {**case, "reasons": _summary(case)["reasons"], "events": store.case_events(case_id),
                "conversation": store.session_turns(case["session_id"])}

    @router.post("/cases/{case_id}/claim")
    def claim(case_id: str, req: ClaimRequest, request: Request):
        try:
            return request.app.state.sessions.claim_case(case_id, req.expert.strip())
        except KeyError:
            raise _not_found(case_id)
        except CaseConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post("/cases/{case_id}/release")
    def release(case_id: str, req: ClaimRequest, request: Request):
        try:
            return request.app.state.sessions.release_case(case_id, req.expert.strip())
        except CaseConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post("/cases/{case_id}/resolve")
    def resolve(case_id: str, req: ResolveRequest, request: Request):
        try:
            result = resolve_case(request.app.state.sessions, case_id, action=req.action, expert=req.expert,
                                  answer=req.answer, note=req.note, graph=request.app.state.review_graph)
            if getattr(request.app.state, "reviewed", None) is not None:
                request.app.state.reviewed.add(result)
            return result
        except KeyError:
            raise _not_found(case_id)
        except CaseConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ReviewError as exc:
            status = 409 if "already" in str(exc) or "reviewed by" in str(exc) else 422
            raise HTTPException(status_code=status, detail=str(exc)) from exc

    return router
