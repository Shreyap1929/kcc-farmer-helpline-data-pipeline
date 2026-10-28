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
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src.assistant.clarification import apply_followup, remember_if_clarifying
from src.assistant.composer import compose_reply
from src.assistant.language import reply_language
from src.assistant.sessions import SessionStore
from src.assistant.stt import transcribe_audio, translate_audio
from src.assistant.translate import AssistantUnavailable, translate_to_english
from src.assistant.tts import synthesize

from src.api.review import build_router as build_review_router
from src.review.reviewed_answers import ReviewedAnswers, delivered_text
from src.review.workflow import build_review_graph
from src.triage.config import CONFIG_DIR

STATIC_DIR = Path(__file__).parent / "static"


class TriageRequest(BaseModel):
    text: str = Field(..., max_length=1000, description="The farmer's question (any language).")
    district: str | None = Field(None, description="district_clean value from the caller profile.")
    crop: str | None = Field(None, description="Crop from the caller profile, if known.")
    month: int | None = Field(None, ge=1, le=12, description="Month of the call (season is derived).")


class ChatMessage(BaseModel):
    session_id: str
    text: str = Field(..., min_length=1, max_length=1000)


class SessionRequest(BaseModel):
    district: str | None = None
    month: int | None = Field(None, ge=1, le=12)
    crop: str | None = None
    language: str | None = Field(None, pattern="^(en|mr|hi)$")


def _examples(engine) -> list[dict]:
    """Probe questions with the route the engine actually gives (run once at start-up)."""
    probes = pd.read_csv(CONFIG_DIR / "gate_probes.csv", dtype=str, keep_default_na=False)
    return [
        {"text": p.text, "lang": p.lang, "crop": p.profile_crop or None, "expected": p.expected_route,
         "route": engine.triage(p.text, crop=p.profile_crop or None)["route"]}
        for p in probes.itertuples()
    ]


def create_app(engine=None, *, session_store=None, transcriber=None, audio_translator=None, tts=None,
               review_translator=None, reviewed_embed=None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if engine is None:
            from src.triage.engine import TriageEngine

            app.state.engine = TriageEngine.load()
        else:
            app.state.engine = engine
        app.state.sessions = session_store or SessionStore()
        app.state.transcriber = transcriber or transcribe_audio
        app.state.audio_translator = audio_translator or translate_audio
        app.state.tts = tts or synthesize
        app.state.audio = {}
        app.state.review_graph = build_review_graph(app.state.sessions, review_translator)
        # Expert answers reused for repeat questions; needs the engine's sentence model.
        embed = reviewed_embed or getattr(app.state.engine, "embed", None)
        app.state.reviewed = ReviewedAnswers(app.state.sessions, embed) if embed else None
        app.state.examples = _examples(app.state.engine)
        yield

    app = FastAPI(title="KCC Farmer Helpline - Triage API", version="0.3.0", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(build_review_router())

    @app.get("/", include_in_schema=False)
    def console():
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/chat", include_in_schema=False)
    def farmer_chat():
        return FileResponse(STATIC_DIR / "chat.html")

    @app.get("/expert", include_in_schema=False)
    def expert_dashboard():
        return FileResponse(STATIC_DIR / "expert.html")

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

    def _chat(req: ChatMessage, request: Request, *, language_override: str | None = None,
              english_fallback=None):
        store = request.app.state.sessions
        session = store.get_session(req.session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="session not found")
        started = __import__("time").perf_counter()
        language = language_override or reply_language(req.text, session.get("language"))
        clarified = apply_followup(store, req.session_id, req.text)
        profile_crop = clarified.crop or session.get("crop")
        decision = request.app.state.engine.triage(
            clarified.text, district=session.get("district"), crop=profile_crop, month=session.get("month")
        )
        reviewed = request.app.state.reviewed
        match = reviewed.match(clarified.text, language, decision) if reviewed is not None else None
        if match is not None:
            decision = {**decision, "route": "ANSWER", "reply": delivered_text(match), "reviewed_case": match,
                        "reasons": [{"code": "REVIEWED_MATCH", "detail": (
                            f"Same question as expert case {match['case_id']} "
                            f"(similarity {match['similarity']:.3f})")}]}
            store.record_reuse(match["case_id"], req.session_id, match["similarity"])
        case_id = None
        if decision.get("route") == "EXPERT_REVIEW":
            # The English version is only for the expert, so only expert cases pay for it.
            try:
                english = translate_to_english(clarified.text, language)
            except (AssistantUnavailable, ValueError):
                english = None
            if english is None and english_fallback is not None:
                try:
                    english = english_fallback()
                except Exception:
                    english = None
            english = english or clarified.text
            case_id = store.save_expert_case(
                session_id=req.session_id, original_text=req.text, english_text=english, language=language,
                reasons=decision.get("reasons") or [], draft=decision.get("draft_for_expert"),
                sources=decision.get("sources") or [],
            )
        reply = compose_reply(decision, language, case_id=case_id)
        remember_if_clarifying(store, req.session_id, clarified.text, decision)
        elapsed = round((__import__("time").perf_counter() - started) * 1000, 1)
        store.add_turn(req.session_id, req.text, decision.get("route", "EXPERT_REVIEW"), elapsed)
        payload = {"session_id": req.session_id, "route": decision.get("route"), "reply": reply,
                   "language": language, "case_id": case_id, "latency_ms": elapsed}
        if match is not None:
            payload["reviewed_case_id"] = match["case_id"]
        return payload

    def _cache_audio(request: Request, audio: bytes) -> str:
        from uuid import uuid4
        audio_id = uuid4().hex
        request.app.state.audio[audio_id] = audio
        # Keep only a small in-memory reply cache; farmer uploads are never saved.
        if len(request.app.state.audio) > 32:
            request.app.state.audio.pop(next(iter(request.app.state.audio)))
        return f"/api/chat/audio/{audio_id}"

    @app.post("/api/chat/session")
    def create_chat_session(req: SessionRequest, request: Request):
        return request.app.state.sessions.create_session(
            district=req.district, month=req.month, crop=req.crop, language=req.language
        )

    @app.post("/api/chat/message")
    def chat_message(req: ChatMessage, request: Request):
        if not req.text.strip():
            raise HTTPException(status_code=422, detail="text must not be empty")
        return _chat(req, request)

    @app.post("/api/chat/voice")
    async def chat_voice(request: Request, session_id: str = Form(...), audio: UploadFile = File(...)):
        try:
            contents = await audio.read(10 * 1024 * 1024 + 1)
            transcript = request.app.state.transcriber(contents, audio.filename or "recording.webm",
                                                       audio.content_type or "audio/webm")
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except AssistantUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=503, detail="voice unavailable") from exc
        req = ChatMessage(session_id=session_id, text=transcript["text"])
        session = request.app.state.sessions.get_session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="session not found")
        # Whisper names the language ("Marathi", "marathi" or "mr" depending on version) and
        # often hears Marathi as Hindi, so the transcript's own words decide and Whisper
        # only breaks a tie.
        heard = str(transcript.get("language") or "").strip().lower()
        heard = {"marathi": "mr", "hindi": "hi", "english": "en"}.get(heard, heard)
        language = reply_language(req.text, heard if heard in {"en", "mr", "hi"} else session.get("language"))
        # The expert's English copy comes from translating the transcript as text. Whisper's
        # own audio translation turned "whitefly on cotton" into "a Pannari fish on my plate"
        # in a live test, so it is only the fallback, and only paid for on expert cases.
        def whisper_translation():
            return request.app.state.audio_translator(contents, audio.filename or "recording.webm",
                                                      audio.content_type or "audio/webm")

        result = _chat(req, request, language_override=language, english_fallback=whisper_translation)
        result["transcript"] = req.text
        try:
            audio_reply = await request.app.state.tts(result["reply"], result["language"])
        except Exception:
            audio_reply = None
        if audio_reply:
            result["audio_url"] = _cache_audio(request, audio_reply)
        else:
            result["voice_unavailable"] = True
        return result

    @app.get("/api/chat/session/{session_id}/updates")
    async def chat_updates(session_id: str, request: Request):
        """Expert answers that arrived since the farmer last asked (each is delivered once)."""
        store = request.app.state.sessions
        if store.get_session(session_id) is None:
            raise HTTPException(status_code=404, detail="session not found")
        updates = []
        for item in store.take_updates(session_id):
            update = {"case_id": item["case_id"], "status": item["status"], "reply": item["farmer_reply"]}
            try:
                audio_reply = await request.app.state.tts(item["farmer_reply"], item["language"])
            except Exception:
                audio_reply = None
            if audio_reply:
                update["audio_url"] = _cache_audio(request, audio_reply)
            updates.append(update)
        return {"updates": updates}

    @app.get("/api/chat/audio/{audio_id}")
    def chat_audio(audio_id: str, request: Request):
        audio = request.app.state.audio.get(audio_id)
        if audio is None:
            raise HTTPException(status_code=404, detail="audio not found or expired")
        return Response(content=audio, media_type="audio/mpeg", headers={"Cache-Control": "no-store"})

    return app


app = create_app()
