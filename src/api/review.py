"""
Expert review API (Stage 4), mounted by `create_app`.

Access, strongest first:
- EXPERT_ACCOUNTS="Dr Patil:<token>,Dr Shinde:<token>": one personal token per expert,
  sent in the X-Expert-Token header. The server knows who is acting, so the name in a
  request body is ignored and every claim, answer and event is attributed to the
  account. Create a token with `python -m src.api.review add "Dr Patil"`.
- EXPERT_TOKEN=<token>: one shared token; experts type their own name (Stage 4).
- Neither: the desk is open, which is only acceptable on a local machine.
"""
from __future__ import annotations

import os
import secrets
import sys

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from src.assistant.sessions import CaseConflict
from src.review.workflow import ReviewError, resolve_case

STATUSES = ("pending", "in_review", "answered", "referred")


def expert_accounts() -> dict[str, str]:
    """token -> expert name, from EXPERT_ACCOUNTS ("Name:token,Name:token")."""
    accounts = {}
    for entry in os.getenv("EXPERT_ACCOUNTS", "").split(","):
        name, sep, token = entry.strip().rpartition(":")
        if sep and name.strip() and token.strip():
            accounts[token.strip()] = name.strip()
    return accounts


def require_expert(x_expert_token: str | None = Header(None)) -> str | None:
    """The signed-in expert's name with personal accounts, else None (name comes from the request)."""
    accounts = expert_accounts()
    if accounts:
        sent = x_expert_token or ""
        # Compare against every token so the time taken does not reveal which one matched.
        matches = [name for token, name in accounts.items() if secrets.compare_digest(sent, token)]
        if not matches:
            raise HTTPException(status_code=401, detail="expert token required")
        return matches[0]
    expected = os.getenv("EXPERT_TOKEN")
    if expected and not secrets.compare_digest(x_expert_token or "", expected):
        raise HTTPException(status_code=401, detail="expert token required")
    return None


def acting_expert(identity: str | None, claimed: str) -> str:
    """The account's name when there is one; otherwise the name the expert typed."""
    name = identity or claimed.strip()
    if not name:
        raise HTTPException(status_code=422, detail="expert name required")
    return name


class ClaimRequest(BaseModel):
    expert: str = Field("", max_length=80)


class ResolveRequest(BaseModel):
    expert: str = Field("", max_length=80)
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

    @router.get("/me")
    def me(identity: str | None = Depends(require_expert)):
        return {"expert": identity, "personal_accounts": bool(expert_accounts())}

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
    def claim(case_id: str, req: ClaimRequest, request: Request,
              identity: str | None = Depends(require_expert)):
        try:
            return request.app.state.sessions.claim_case(case_id, acting_expert(identity, req.expert))
        except KeyError:
            raise _not_found(case_id)
        except CaseConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post("/cases/{case_id}/release")
    def release(case_id: str, req: ClaimRequest, request: Request,
              identity: str | None = Depends(require_expert)):
        try:
            return request.app.state.sessions.release_case(case_id, acting_expert(identity, req.expert))
        except CaseConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post("/cases/{case_id}/retire")
    def retire(case_id: str, req: ClaimRequest, request: Request,
               identity: str | None = Depends(require_expert)):
        """Stop reusing this answer for new farmers (it stays sent to the original farmer)."""
        try:
            result = request.app.state.sessions.retire_answer(case_id, acting_expert(identity, req.expert))
        except CaseConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if getattr(request.app.state, "reviewed", None) is not None:
            request.app.state.reviewed.remove(case_id)
        return result

    @router.post("/cases/{case_id}/resolve")
    def resolve(case_id: str, req: ResolveRequest, request: Request,
                identity: str | None = Depends(require_expert)):
        expert = acting_expert(identity, req.expert)
        try:
            result = resolve_case(request.app.state.sessions, case_id, action=req.action, expert=expert,
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


def main(argv: list[str]) -> None:
    """python -m src.api.review add "Dr Patil": print a new personal token for EXPERT_ACCOUNTS."""
    if len(argv) != 2 or argv[0] != "add" or ":" in argv[1] or "," in argv[1]:
        raise SystemExit('usage: python -m src.api.review add "Expert Name"   (no ":" or "," in the name)')
    token = secrets.token_urlsafe(24)
    existing = os.getenv("EXPERT_ACCOUNTS", "")
    entry = f"{argv[1]}:{token}"
    print(f"Token for {argv[1]} (give it to them privately): {token}")
    print(f"Add to .env:  EXPERT_ACCOUNTS={existing + ',' if existing else ''}{entry}")


if __name__ == "__main__":
    main(sys.argv[1:])
