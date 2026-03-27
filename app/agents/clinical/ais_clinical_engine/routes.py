from __future__ import annotations
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
  POST /clinical/qa/validate         — validate a Q&A answer (thumbs down feedback)
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
    load_evt_rules,
    load_guideline_knowledge,
    load_recommendations,
    load_recommendations_by_id,
)
from .models.clinical import (
    ClinicalDecisionState,
    ClinicalOverrides,
    ParsedVariables,
    QAValidationRequest,
    QAValidationResponse,
)
from .services.decision_engine import DecisionEngine
from .services.nlp_service import NLPService
from .services.qa_service import answer_question, verify_verbatim
from .services.rule_engine import RuleEngine

# ── Router setup ─────────────────────────────────────────────

router = APIRouter(prefix="/clinical", tags=["clinical"])

# Shared service instances (created once, reused across requests)
_nlp_service = NLPService()
_ivt_orchestrator = IVTOrchestrator()
_rule_engine = RuleEngine()
_rule_engine.load_from_dicts(
    recs_list=load_recommendations(),
    rules_list=load_evt_rules(),
)
_decision_engine = DecisionEngine()
_session_manager = SessionManager()


# ── Request / Response models ────────────────────────────────


class ScenarioEvalRequest(BaseModel):
    text: str
    uid: Optional[str] = None
    session_id: Optional[str] = None


class ReEvaluateRequest(BaseModel):
    session_id: str
    uid: Optional[str] = None
    overrides: ClinicalOverrides


class WhatIfRequest(BaseModel):
    session_id: Optional[str] = None
    uid: Optional[str] = None
    baseText: Optional[str] = None
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
    session_state["uid"] = uid
    session_state["session_id"] = session_id
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


# ── Shared normalization helper ───────────────────────────────


def _normalize_parsed_variables(parsed: ParsedVariables) -> None:
    """Normalize parsed variables: clock-time LKW, time sync, sex."""
    # Clock-time LKW → calculate hours from now
    if parsed.lkwClockTime and parsed.lastKnownWellHours is None:
        try:
            from datetime import datetime, timedelta
            now = datetime.now()
            parts = parsed.lkwClockTime.replace(":", "")
            if len(parts) == 4:
                h, m = int(parts[:2]), int(parts[2:])
            else:
                h, m = int(parsed.lkwClockTime.split(":")[0]), int(parsed.lkwClockTime.split(":")[1])
            lkw_today = now.replace(hour=h, minute=m, second=0, microsecond=0)
            if lkw_today > now:
                lkw_today -= timedelta(days=1)
            hours_ago = (now - lkw_today).total_seconds() / 3600
            parsed.lastKnownWellHours = round(hours_ago, 1)
        except Exception:
            pass

    # Bidirectional time normalization
    if parsed.timeHours is None and parsed.lastKnownWellHours is not None:
        parsed.timeHours = parsed.lastKnownWellHours
    if parsed.lastKnownWellHours is None and parsed.timeHours is not None:
        parsed.lastKnownWellHours = parsed.timeHours

    # Sex normalization
    if parsed.sex and parsed.sex.lower() not in ("male", "female"):
        parsed.sex = "male" if parsed.sex.lower() in ("m", "man") else "female"


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

    # EVT eligibility — three-valued logic (met/failed/unknown per clause)
    # This properly returns "pending" when required variables (ASPECTS, mRS, etc.)
    # are missing, instead of prematurely firing "recommended".
    evt_eligibility = _rule_engine.evaluate_evt_eligibility(parsed)
    evt_result["eligibility"] = evt_eligibility

    # Gate all EVT recommendations on eligibility: technique/process recs
    # (stent retrievers, anesthesia, concomitant IVT+EVT) should only show
    # once the patient is confirmed EVT-eligible. Otherwise it's premature.
    if evt_eligibility.get("status") != "eligible":
        evt_result["recommendations"] = {}
        # Preserve notes — they may contain useful clinical context

    # Decision state
    decision_state = _decision_engine.compute_effective_state(
        parsed, ivt_result, evt_result, overrides
    )

    # Combine notes from IVT + EVT + EVT eligibility warnings
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
    # Add notes from EVT eligibility evaluation (e.g. mass effect warnings)
    for note in evt_eligibility.get("notes", []):
        if isinstance(note, dict):
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

    _normalize_parsed_variables(parsed)

    # Run full evaluation (no overrides on initial evaluation)
    result = _run_full_evaluation(parsed)

    # Persist to Firebase for re-evaluate / what-if (only if uid provided)
    session_id = request.session_id
    if request.uid:
        session_id = session_id or _session_manager.create_session(request.uid)
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
        session_id=session_id or "",
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
    # Support both session-based and baseText-based what-if
    if request.session_id and request.uid:
        ctx = await _load_clinical_context(request.uid, request.session_id)
        base_parsed = ctx["parsed_variables"].copy()
        existing_overrides_data = ctx.get("clinician_overrides", {})
        overrides = ClinicalOverrides(**existing_overrides_data) if existing_overrides_data else None
    elif request.baseText:
        parsed_base = await _nlp_service.parse_scenario(request.baseText)
        base_parsed = parsed_base.model_dump()
        overrides = None
    else:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Provide either session_id+uid or baseText")

    # Apply modifications
    base_parsed.update(request.modifications)
    parsed = ParsedVariables(**base_parsed)
    _normalize_parsed_variables(parsed)

    # Re-run full evaluation with modified variables
    result = _run_full_evaluation(parsed, overrides)

    # Persist updated state if session-based
    if request.uid and request.session_id:
        await _save_clinical_context(
            uid=request.uid,
            session_id=request.session_id,
            parsed=parsed,
            ivt_result=result["ivt_result"],
            evt_result=result["evt_result"],
            decision_state=result["decision_state"],
            overrides=overrides,
            scenario_text=request.baseText or "",
        )

    return FullEvalResponse(
        session_id=request.session_id or "",
        parsedVariables=parsed.model_dump(),
        ivtResult=_serialize_ivt_result(result["ivt_result"]),
        evtResult=_serialize_evt_result(result["evt_result"]),
        decisionState=result["decision_state"],
        notes=result["notes"],
        clinicalChecklists=result["checklists"],
    )


@router.post("/qa")
async def clinical_qa(request: QARequest):
    """
    Q&A against guideline recommendations.

    Searches three layers: formal recommendations, RSS evidence, and synopsis/knowledge gaps.
    Uses concept synonym expansion, applicability gating, and LLM summarization.
    """
    recommendations_store = load_recommendations_by_id()
    guideline_knowledge = load_guideline_knowledge()

    result = await answer_question(
        question=request.question,
        recommendations_store=recommendations_store,
        guideline_knowledge=guideline_knowledge,
        rule_engine=_rule_engine,
        nlp_service=_nlp_service,
        context=request.context,
    )

    return result


@router.post("/qa/validate", response_model=QAValidationResponse)
async def validate_qa_answer(request: QAValidationRequest):
    """
    Validate a Q&A answer when a clinician gives thumbs down feedback.

    Runs verbatim check (deterministic) + LLM validation.
    """
    if request.feedback == "thumbs_up":
        return QAValidationResponse()

    guideline_knowledge = load_guideline_knowledge()
    verbatim_mismatches = verify_verbatim(request.answer, guideline_knowledge)

    # Build patient context string
    patient_ctx = ""
    if request.context:
        ctx = request.context
        parts = []
        if ctx.get("age"): parts.append(f"{ctx['age']}y")
        if ctx.get("sex"): parts.append("M" if str(ctx["sex"]).lower() == "male" else "F")
        if ctx.get("nihss") is not None: parts.append(f"NIHSS {ctx['nihss']}")
        if ctx.get("vessel"): parts.append(str(ctx["vessel"]))
        if ctx.get("wakeUp"): parts.append("wake-up stroke")
        elif ctx.get("timeHours") is not None: parts.append(f"{ctx['timeHours']}h from onset")
        if parts:
            patient_ctx = ", ".join(parts)

    llm_result = await _nlp_service.validate_qa_answer(
        question=request.question,
        answer=request.answer,
        summary=request.summary,
        citations=request.citations,
        patient_context=patient_ctx,
    )

    issues = list(llm_result.get("issues", []))
    if verbatim_mismatches:
        issues.extend(verbatim_mismatches)

    for field, label in [
        ("intentExplanation", "Intent"),
        ("relevanceExplanation", "Relevance"),
        ("summaryExplanation", "Summary"),
    ]:
        explanation = llm_result.get(field, "")
        flag_field = field.replace("Explanation", "Correct" if "intent" in field else "Relevant" if "relevance" in field else "Accurate")
        if explanation and not llm_result.get(flag_field, True):
            issues.append(f"{label}: {explanation}")

    return QAValidationResponse(
        intentCorrect=llm_result.get("intentCorrect", True),
        recommendationsRelevant=llm_result.get("recommendationsRelevant", True),
        recommendationsVerbatim=len(verbatim_mismatches) == 0,
        summaryAccurate=llm_result.get("summaryAccurate", True),
        issues=issues,
        suggestedCorrection=llm_result.get("suggestedCorrection", ""),
        verbatimMismatches=verbatim_mismatches,
    )


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


