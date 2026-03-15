"""
REST endpoints for the AIS Clinical Engine.

Exposes the full clinical decision pipeline via REST so the frontend
becomes a thin renderer.

Endpoints:
  POST /clinical/scenarios           — full evaluation: parse → IVT → EVT → DecisionState
  POST /clinical/scenarios/parse     — parse text only
  POST /clinical/scenarios/re-evaluate — apply clinician overrides, recompute DecisionState
  POST /clinical/scenarios/what-if   — modify parsed variables and re-evaluate
  POST /clinical/qa                  — Q&A against guideline recommendations
  GET  /clinical/recommendations     — browse/filter guideline recommendations
  GET  /clinical/health              — engine health check
"""

from typing import Optional
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from medsync_ai_v2.shared.session_state import SessionManager, sanitize_for_firestore

from .agents.ivt_orchestrator import IVTOrchestrator
from .data.loader import (
    get_recommendations_by_category,
    get_recommendations_by_section,
    load_recommendations,
)
from .models.clinical import (
    ClinicalDecisionState,
    ClinicalOverrides,
    ParsedVariables,
)
from .services.decision_engine import DecisionEngine
from .services.nlp_service import NLPService
from .services.rule_engine import RuleEngine

# ── Router setup ─────────────────────────────────────────────

router = APIRouter(prefix="/clinical", tags=["clinical"])

# Shared service instances (created once, reused across requests)
_nlp_service = NLPService()
_ivt_orchestrator = IVTOrchestrator()
_rule_engine = RuleEngine()
_decision_engine = DecisionEngine()
_session_manager = SessionManager()


# ── Request / Response models ────────────────────────────────


class ScenarioEvalRequest(BaseModel):
    text: str
    uid: str
    session_id: Optional[str] = None


class ReEvaluateRequest(BaseModel):
    session_id: str
    uid: str
    overrides: ClinicalOverrides


class WhatIfRequest(BaseModel):
    session_id: str
    uid: str
    modifications: dict = Field(
        description="Fields to override in ParsedVariables (e.g. {'nihss': 22})"
    )


class QARequest(BaseModel):
    question: str
    context: Optional[dict] = None


class FullEvalResponse(BaseModel):
    session_id: str = ""
    parsedVariables: dict
    ivtResult: dict
    evtResult: dict
    decisionState: ClinicalDecisionState
    notes: list = []
    clinicalChecklists: list = []


# ── Session persistence (Firebase via SessionManager) ────────


async def _save_clinical_context(
    uid: str,
    session_id: str,
    parsed: ParsedVariables,
    ivt_result: dict,
    evt_result: dict,
    decision_state: ClinicalDecisionState,
    overrides: Optional[ClinicalOverrides] = None,
    scenario_text: str = "",
) -> None:
    """Persist clinical context to Firebase session for audit trail + re-evaluate."""
    session_state = await _session_manager.get_session(uid, session_id)
    session_state["mode"] = "clinical_guideline"
    session_state.setdefault("conversation_history", [])

    # Append user scenario as a conversation turn (only on first evaluation, not re-evaluate)
    now = datetime.now(timezone.utc).isoformat()
    if scenario_text and not any(
        m.get("content") == scenario_text for m in session_state["conversation_history"]
    ):
        session_state["conversation_history"].append({
            "role": "user",
            "content": scenario_text,
            "timestamp": now,
        })
        session_state["conversation_history"].append({
            "role": "assistant",
            "content": decision_state.headline or "Clinical evaluation complete",
            "type": "clinical_evaluation",
            "timestamp": now,
        })
        session_state["last_message"] = decision_state.headline or "Clinical evaluation complete"

    session_state["clinical_context"] = sanitize_for_firestore({
        "parsed_variables": parsed.model_dump(),
        "ivt_result": _serialize_ivt_result(ivt_result),
        "evt_result": _serialize_evt_result(evt_result),
        "decision_state": decision_state.model_dump(),
        "clinician_overrides": (overrides.model_dump() if overrides else {}),
        "last_scenario_text": scenario_text,
    })
    await _session_manager.save_session(uid, session_id, session_state)


async def _load_clinical_context(uid: str, session_id: str) -> dict:
    """Load clinical context from Firebase session. Raises 404 if not found."""
    session_state = await _session_manager.get_session(uid, session_id)
    ctx = session_state.get("clinical_context")
    if not ctx:
        raise HTTPException(
            status_code=404,
            detail=f"No clinical context found for session '{session_id}'. "
            "Run POST /clinical/scenarios first.",
        )
    return ctx


# ── Shared evaluation helper ─────────────────────────────────


def _run_full_evaluation(
    parsed: ParsedVariables,
    overrides: Optional[ClinicalOverrides] = None,
) -> dict:
    """
    Run IVT + EVT pipelines and compute decision state.

    Returns dict with ivt_result, evt_result, decision_state, notes, checklists.
    """
    # IVT pipeline
    ivt_result = _ivt_orchestrator.evaluate(parsed)

    # EVT rule engine
    evt_result = _rule_engine.evaluate(parsed)

    # Decision state
    decision_state = _decision_engine.compute_effective_state(
        parsed, ivt_result, evt_result, overrides
    )

    # Combine notes from IVT + EVT
    notes = []
    for note in ivt_result.get("notes", []):
        if hasattr(note, "model_dump"):
            notes.append(note.model_dump())
        elif isinstance(note, dict):
            notes.append(note)
    for note in evt_result.get("notes", []):
        if hasattr(note, "model_dump"):
            notes.append(note.model_dump())
        elif isinstance(note, dict):
            notes.append(note)

    return {
        "ivt_result": ivt_result,
        "evt_result": evt_result,
        "decision_state": decision_state,
        "notes": notes,
        "checklists": ivt_result.get("clinicalChecklists", []),
    }


# ── Endpoints ────────────────────────────────────────────────


@router.post("/scenarios", response_model=FullEvalResponse)
async def evaluate_scenario(request: ScenarioEvalRequest):
    """
    Full evaluation: parse → IVT → EVT → DecisionState.

    This is the primary endpoint. Frontend sends patient scenario text,
    gets back everything needed to render the clinical decision display.
    """
    # Parse scenario text → structured variables
    parsed = await _nlp_service.parse_scenario(request.text)

    # Run full evaluation (no overrides on initial evaluation)
    result = _run_full_evaluation(parsed)

    # Persist to Firebase for re-evaluate / what-if
    session_id = request.session_id or _session_manager.create_session(request.uid)
    await _save_clinical_context(
        uid=request.uid,
        session_id=session_id,
        parsed=parsed,
        ivt_result=result["ivt_result"],
        evt_result=result["evt_result"],
        decision_state=result["decision_state"],
        scenario_text=request.text,
    )

    return FullEvalResponse(
        session_id=session_id,
        parsedVariables=parsed.model_dump(),
        ivtResult=_serialize_ivt_result(result["ivt_result"]),
        evtResult=_serialize_evt_result(result["evt_result"]),
        decisionState=result["decision_state"],
        notes=result["notes"],
        clinicalChecklists=result["checklists"],
    )


@router.post("/scenarios/parse")
async def parse_scenario(request: ScenarioEvalRequest):
    """Parse scenario text only — no evaluation."""
    parsed = await _nlp_service.parse_scenario(request.text)
    return {"parsedVariables": parsed.model_dump()}


@router.post("/scenarios/re-evaluate", response_model=FullEvalResponse)
async def re_evaluate_scenario(request: ReEvaluateRequest):
    """
    Re-evaluate with clinician overrides.

    Loads the persisted IVT/EVT results from the initial evaluation,
    then re-runs the DecisionEngine with the provided overrides.
    The IVT/EVT pipelines are NOT re-run — only the decision state changes.
    """
    ctx = await _load_clinical_context(request.uid, request.session_id)
    parsed = ParsedVariables(**ctx["parsed_variables"])
    ivt_result = ctx["ivt_result"]
    evt_result = ctx["evt_result"]

    # Re-compute decision state with overrides
    decision_state = _decision_engine.compute_effective_state(
        parsed, ivt_result, evt_result, request.overrides
    )

    # Persist updated state + overrides (audit trail)
    await _save_clinical_context(
        uid=request.uid,
        session_id=request.session_id,
        parsed=parsed,
        ivt_result=ivt_result,
        evt_result=evt_result,
        decision_state=decision_state,
        overrides=request.overrides,
        scenario_text=ctx.get("last_scenario_text", ""),
    )

    return FullEvalResponse(
        session_id=request.session_id,
        parsedVariables=parsed.model_dump(),
        ivtResult=_serialize_ivt_result(ivt_result),
        evtResult=_serialize_evt_result(evt_result),
        decisionState=decision_state,
        notes=_extract_notes(ivt_result, evt_result),
        clinicalChecklists=ivt_result.get("clinicalChecklists", []),
    )


@router.post("/scenarios/what-if", response_model=FullEvalResponse)
async def what_if_scenario(request: WhatIfRequest):
    """
    Modify parsed variables and re-evaluate the full pipeline.

    Unlike re-evaluate, this re-runs IVT + EVT because the clinical
    variables themselves have changed (e.g. different NIHSS).
    """
    ctx = await _load_clinical_context(request.uid, request.session_id)
    base_parsed = ctx["parsed_variables"].copy()

    # Apply modifications
    base_parsed.update(request.modifications)
    parsed = ParsedVariables(**base_parsed)

    # Preserve existing overrides from the session
    existing_overrides_data = ctx.get("clinician_overrides", {})
    overrides = ClinicalOverrides(**existing_overrides_data) if existing_overrides_data else None

    # Re-run full evaluation with modified variables
    result = _run_full_evaluation(parsed, overrides)

    # Persist updated state
    await _save_clinical_context(
        uid=request.uid,
        session_id=request.session_id,
        parsed=parsed,
        ivt_result=result["ivt_result"],
        evt_result=result["evt_result"],
        decision_state=result["decision_state"],
        overrides=overrides,
        scenario_text=ctx.get("last_scenario_text", ""),
    )

    return FullEvalResponse(
        session_id=request.session_id,
        parsedVariables=parsed.model_dump(),
        ivtResult=_serialize_ivt_result(result["ivt_result"]),
        evtResult=_serialize_evt_result(result["evt_result"]),
        decisionState=result["decision_state"],
        notes=result["notes"],
        clinicalChecklists=result["checklists"],
    )


@router.post("/qa")
async def clinical_qa(request: QARequest):
    """Q&A against guideline recommendations."""
    # Search recommendations for relevant content
    all_recs = load_recommendations()
    question_lower = request.question.lower()

    # Simple keyword relevance scoring
    relevant = []
    for rec in all_recs:
        text = rec.get("text", "").lower()
        section_title = rec.get("sectionTitle", "").lower()
        score = 0
        for word in question_lower.split():
            if len(word) > 3:  # Skip short words
                if word in text:
                    score += 1
                if word in section_title:
                    score += 2
        if score > 0:
            relevant.append((score, rec))

    relevant.sort(key=lambda x: x[0], reverse=True)
    top_recs = [r for _, r in relevant[:5]]

    return {
        "answer": _format_qa_answer(request.question, top_recs),
        "citations": [
            f"Section {r['section']} Rec {r['recNumber']}: {r['text'][:100]}..."
            for r in top_recs
        ],
        "relatedSections": list({r["section"] for r in top_recs}),
    }


@router.get("/recommendations")
async def list_recommendations(
    section: Optional[str] = None,
    category: Optional[str] = None,
):
    """Browse/filter guideline recommendations."""
    if section:
        recs = get_recommendations_by_section(section)
    elif category:
        recs = get_recommendations_by_category(category)
    else:
        recs = load_recommendations()

    return {
        "count": len(recs),
        "recommendations": recs,
    }


@router.get("/health")
async def health_check():
    """Engine health check."""
    try:
        rec_count = len(load_recommendations())
        return {
            "status": "ok",
            "engine": "ais_clinical_engine",
            "recommendations_loaded": rec_count,
            "services": {
                "nlp_service": "ready",
                "ivt_orchestrator": "ready",
                "rule_engine": f"ready ({len(_rule_engine.rules)} rules)",
                "decision_engine": "ready",
            },
        }
    except Exception as e:
        return {"status": "error", "detail": str(e)}


# ── Helpers ──────────────────────────────────────────────────


def _serialize_ivt_result(ivt_result: dict) -> dict:
    """Ensure IVT result is fully serializable (convert Pydantic models)."""
    out = {}
    for key, value in ivt_result.items():
        if hasattr(value, "model_dump"):
            out[key] = value.model_dump()
        elif isinstance(value, list):
            out[key] = [
                item.model_dump() if hasattr(item, "model_dump") else item
                for item in value
            ]
        else:
            out[key] = value
    return out


def _serialize_evt_result(evt_result: dict) -> dict:
    """Ensure EVT result is fully serializable."""
    out = {}
    for key, value in evt_result.items():
        if hasattr(value, "model_dump"):
            out[key] = value.model_dump()
        elif isinstance(value, list):
            out[key] = [
                item.model_dump() if hasattr(item, "model_dump") else item
                for item in value
            ]
        elif isinstance(value, dict):
            serialized = {}
            for k, v in value.items():
                if isinstance(v, list):
                    serialized[k] = [
                        item.model_dump() if hasattr(item, "model_dump") else item
                        for item in v
                    ]
                else:
                    serialized[k] = v
            out[key] = serialized
        else:
            out[key] = value
    return out


def _extract_notes(ivt_result: dict, evt_result: dict) -> list:
    """Extract and serialize notes from both results."""
    notes = []
    for note in ivt_result.get("notes", []):
        if hasattr(note, "model_dump"):
            notes.append(note.model_dump())
        elif isinstance(note, dict):
            notes.append(note)
    for note in evt_result.get("notes", []):
        if hasattr(note, "model_dump"):
            notes.append(note.model_dump())
        elif isinstance(note, dict):
            notes.append(note)
    return notes


def _format_qa_answer(question: str, recs: list) -> str:
    """Format a simple answer from matched recommendations."""
    if not recs:
        return "No relevant recommendations found for this question."

    lines = [f"Based on {len(recs)} relevant guideline recommendation(s):\n"]
    for rec in recs:
        cor = rec.get("cor", "")
        loe = rec.get("loe", "")
        lines.append(
            f"- [{cor}/{loe}] Section {rec['section']}, "
            f"Rec {rec['recNumber']}: {rec['text']}"
        )
    return "\n".join(lines)
