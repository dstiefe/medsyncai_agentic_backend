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

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.shared.auth import require_auth

from app.shared.session_state import SessionManager, sanitize_for_firestore

import logging

from .agents.ivt_orchestrator import IVTOrchestrator
from .agents.qa_v6 import QAOrchestrator
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
from .services.gate_satisfaction import (
    advanced_imaging_gate_status,
    contraindication_review_gate_status,
    disabling_deficit_gate_status,
    evt_availability_gate_status,
    lkw_within_24h_gate_status,
    m2_dominance_gate_status,
    symptom_recognition_gate_status,
    wakeup_time_gate_status,
)
from .services.nlp_service import NLPService
from .services.qa_service import verify_verbatim
from .services.rule_engine import RuleEngine

logger = logging.getLogger(__name__)

# ── Router setup ─────────────────────────────────────────────

router = APIRouter(prefix="/clinical", tags=["clinical"], dependencies=[Depends(require_auth)])

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

# Multi-agent Q&A pipeline.
# Semantic embeddings live in the unified v5 atoms file and are
# loaded lazily by semantic_service — no separate embedding_store needed.
_qa_orchestrator = QAOrchestrator(
    recommendations_store=load_recommendations_by_id(),
    guideline_knowledge=load_guideline_knowledge(),
    rule_engine=_rule_engine,
    nlp_service=_nlp_service,
)


# ── Request / Response models ────────────────────────────────


class ScenarioEvalRequest(BaseModel):
    uid: str
    text: str
    session_id: Optional[str] = None


class ReEvaluateRequest(BaseModel):
    uid: str
    session_id: str
    overrides: ClinicalOverrides


class WhatIfRequest(BaseModel):
    uid: str
    session_id: Optional[str] = None
    baseText: Optional[str] = None
    modifications: dict = Field(
        description="Fields to override in ParsedVariables (e.g. {'nihss': 22})"
    )


class QARequest(BaseModel):
    uid: str
    session_id: Optional[str] = None
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
    # Per-gate satisfaction status keyed by gate name. Populated by
    # services/gate_satisfaction.py from extracted ParsedVariables.
    # Frontend uses this to decide whether to render a gate as
    # "needed" (open) or auto-close it. Empty dict for legacy callers.
    gateStatus: dict = {}


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
) -> bool:
    """Persist clinical context to Firebase session for audit trail + re-evaluate.

    Returns True if saved successfully, False if Firebase is unavailable.
    Never raises — clinical results must always be returned to the caller.
    """
    try:
        session_state = await _session_manager.get_session(uid, session_id)
    except Exception as e:
        print(f"⚠ Firebase unavailable — skipping session persistence: {e}")
        return False

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

    try:
        await _session_manager.save_session(uid, session_id, session_state)
    except Exception as e:
        print(f"⚠ Firebase save failed — clinical results still returned: {e}")
        return False

    return True


async def _load_clinical_context(uid: str, session_id: str) -> dict:
    """Load clinical context from Firebase session. Raises 404 if not found."""
    try:
        session_state = await _session_manager.get_session(uid, session_id)
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"Session storage unavailable: {e}. "
            "Re-evaluate and what-if require a persisted session from the initial evaluation.",
        )
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
    """Normalize parsed variables: time sync, sex.

    LKW clock-time → hours is the LLM's job. The extraction prompt
    explicitly tells the LLM to compute lastKnownWellHours ONLY when
    BOTH the LKW clock time AND an explicit evaluation time
    ("it is now X", "presents at Y", "arriving at ED at Z") are
    given. When only the LKW clock is stated, the LLM leaves
    lastKnownWellHours null and the LKW / wake-up time gate prompts
    the clinician.

    A previous version of this normalizer fell back to datetime.now()
    (the host machine's real-world wall clock) whenever lkwClockTime
    was present and lastKnownWellHours was null — but the LLM's
    instruction is "Never use real-world wall-clock time", and the
    fallback violated it. Symptoms:
      - same scenario produced different LKW values depending on
        what time of day the case was entered (8 am → 9h, midnight
        → 25h "out of window"). Reproducibility broken.
      - "found at 7 am, last seen well at 11 pm" wake-up cases that
        slipped past the wake-up classifier (parsed.wakeUp != True)
        got a real-world LKW that was not the right clock at all
        (the relevant clocks for wake-up are sleep midpoint and
        symptom recognition, not LKW-to-now).
    The fallback is removed. If the LLM didn't compute hours, that's
    the right answer — surface the gate.
    """
    # Sex normalization
    if parsed.sex and parsed.sex.lower() not in ("male", "female"):
        parsed.sex = "male" if parsed.sex.lower() in ("m", "man") else "female"

    # LKW is the primary clinical time anchor. timeHours (symptom recognition)
    # is only used as a fallback when LKW is unknown (Section 4.6.3).
    # Do NOT sync one into the other — effectiveTimeHours handles the fallback.


# ── Shared evaluation helper ─────────────────────────────────


def _run_full_evaluation(
    parsed: ParsedVariables,
    overrides: Optional[ClinicalOverrides] = None,
) -> dict:
    """
    Run IVT + EVT pipelines and compute decision state.

    Returns dict with ivt_result, evt_result, decision_state, notes, checklists.
    """
    # EVT rule engine — run first so the IVT pipeline can see whether the
    # engine excluded EVT. Per Section 4.6.3 Rec 3, "cannot receive EVT"
    # includes engine-determined ineligibility (e.g. ASPECTS too low, time
    # out of window), not just clinician-marked unavailability.
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

    # IVT pipeline — pass the engine's EVT verdict so the rec-4.6.3-003
    # pathway ("LVO + penumbra + cannot receive EVT") can fire when EVT
    # was excluded clinically even if the EVT-availability gate is unset.
    evt_excluded_by_engine = evt_eligibility.get("status") == "excluded"
    ivt_result = _ivt_orchestrator.evaluate(parsed, evt_excluded_by_engine)

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

    # Per-gate satisfaction — deterministic from extracted ParsedVariables.
    # Gate closes only when every strict criterion is explicitly stated.
    # Per the safety principle: "if it's not clear from what the user wrote,
    # leave the gate unanswered."
    imaging_status = advanced_imaging_gate_status(parsed, evt_excluded_by_engine)
    sx_status = symptom_recognition_gate_status(parsed)
    wake_status = wakeup_time_gate_status(parsed)
    evt_avail_status = evt_availability_gate_status(parsed)
    lkw_status = lkw_within_24h_gate_status(parsed)
    m2_status = m2_dominance_gate_status(parsed)
    deficit_status = disabling_deficit_gate_status(parsed)
    contra_status = contraindication_review_gate_status(parsed)
    gate_status = {
        "advanced_imaging": {
            "status": imaging_status.status,
            "matched_rec_id": imaging_status.matched_rec_id,
            "missing_criteria": imaging_status.missing_criteria,
            "rec_statuses": [
                {
                    "rec_id": rs.rec_id,
                    "evaluable": rs.evaluable,
                    "meets": rs.meets,
                    "missing_criteria": rs.missing_criteria,
                }
                for rs in imaging_status.rec_statuses
            ],
        },
        "symptom_recognition": {"status": sx_status.status, "detail": sx_status.detail},
        "wakeup_time": {"status": wake_status.status, "detail": wake_status.detail},
        "evt_availability": {"status": evt_avail_status.status, "detail": evt_avail_status.detail},
        "lkw_within_24h": {"status": lkw_status.status, "detail": lkw_status.detail},
        "m2_dominance": {"status": m2_status.status, "detail": m2_status.detail},
        "disabling_deficit": {"status": deficit_status.status, "detail": deficit_status.detail},
        "contraindication_review": {"status": contra_status.status, "detail": contra_status.detail},
    }

    return {
        "ivt_result": ivt_result,
        "evt_result": evt_result,
        "decision_state": decision_state,
        "notes": notes,
        "checklists": ivt_result.get("clinicalChecklists", []),
        "gate_status": gate_status,
    }


# ── Endpoints ────────────────────────────────────────────────


@router.post("/scenarios", response_model=FullEvalResponse)
async def evaluate_scenario(request: ScenarioEvalRequest, http_request: Request):
    """
    Full evaluation: parse → IVT → EVT → DecisionState.

    This is the primary endpoint. Frontend sends patient scenario text,
    gets back everything needed to render the clinical decision display.
    """
    session_id = http_request.state.session_id

    # Parse scenario text → structured variables
    parsed = await _nlp_service.parse_scenario(request.text)

    _normalize_parsed_variables(parsed)

    # Run full evaluation (no overrides on initial evaluation)
    result = _run_full_evaluation(parsed)

    # Persist to Firebase for re-evaluate / what-if
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
        gateStatus=result.get("gate_status", {}),
    )


@router.post("/scenarios/parse")
async def parse_scenario(request: ScenarioEvalRequest, http_request: Request):
    """Parse scenario text only — no evaluation."""
    parsed = await _nlp_service.parse_scenario(request.text)
    return {"session_id": http_request.state.session_id, "parsedVariables": parsed.model_dump()}


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

    # Re-evaluate path doesn't go through _run_full_evaluation — compute gate
    # status directly from the parsed variables for consistency with /scenarios.
    # Derive evt_excluded_by_engine from the persisted EVT result so the
    # imaging gate's Rec 4.6.3-003 candidacy reflects the same EVT verdict.
    re_eval_evt_eligibility = (evt_result or {}).get("eligibility") or {}
    re_eval_evt_excluded = re_eval_evt_eligibility.get("status") == "excluded"
    imaging_status = advanced_imaging_gate_status(parsed, re_eval_evt_excluded)
    sx_status = symptom_recognition_gate_status(parsed)
    wake_status = wakeup_time_gate_status(parsed)
    evt_avail_status = evt_availability_gate_status(parsed)
    lkw_status = lkw_within_24h_gate_status(parsed)
    m2_status = m2_dominance_gate_status(parsed)
    deficit_status = disabling_deficit_gate_status(parsed)
    contra_status = contraindication_review_gate_status(parsed)
    return FullEvalResponse(
        session_id=request.session_id,
        parsedVariables=parsed.model_dump(),
        ivtResult=_serialize_ivt_result(ivt_result),
        evtResult=_serialize_evt_result(evt_result),
        decisionState=decision_state,
        notes=_extract_notes(ivt_result, evt_result),
        clinicalChecklists=ivt_result.get("clinicalChecklists", []),
        gateStatus={
            "advanced_imaging": {
                "status": imaging_status.status,
                "matched_rec_id": imaging_status.matched_rec_id,
                "missing_criteria": imaging_status.missing_criteria,
                "rec_statuses": [
                    {"rec_id": rs.rec_id, "evaluable": rs.evaluable, "meets": rs.meets, "missing_criteria": rs.missing_criteria}
                    for rs in imaging_status.rec_statuses
                ],
            },
            "symptom_recognition": {"status": sx_status.status, "detail": sx_status.detail},
            "wakeup_time": {"status": wake_status.status, "detail": wake_status.detail},
            "evt_availability": {"status": evt_avail_status.status, "detail": evt_avail_status.detail},
            "lkw_within_24h": {"status": lkw_status.status, "detail": lkw_status.detail},
            "m2_dominance": {"status": m2_status.status, "detail": m2_status.detail},
            "disabling_deficit": {"status": deficit_status.status, "detail": deficit_status.detail},
            "contraindication_review": {"status": contra_status.status, "detail": contra_status.detail},
        },
    )


@router.post("/scenarios/what-if", response_model=FullEvalResponse)
async def what_if_scenario(request: WhatIfRequest, http_request: Request):
    """
    Modify parsed variables and re-evaluate the full pipeline.

    Unlike re-evaluate, this re-runs IVT + EVT because the clinical
    variables themselves have changed (e.g. different NIHSS).
    """
    # Support both session-based and baseText-based what-if. Prefer
    # session (it preserves prior overrides), but fall back to baseText
    # whenever the session can't be loaded — dev environments without
    # Firebase configured, expired sessions, or new sessions that haven't
    # persisted yet. The fallback re-parses from text so what-if always
    # works as long as baseText is present.
    base_parsed = None
    overrides = None
    if request.session_id and request.uid:
        try:
            ctx = await _load_clinical_context(request.uid, request.session_id)
            base_parsed = ctx["parsed_variables"].copy()
            existing_overrides_data = ctx.get("clinician_overrides", {})
            overrides = ClinicalOverrides(**existing_overrides_data) if existing_overrides_data else None
        except HTTPException as e:
            # Session unavailable (503 = backend storage down, 404 =
            # session not found). If we have baseText, fall through to
            # the re-parse path; otherwise propagate the original error.
            if e.status_code in (503, 404) and request.baseText:
                base_parsed = None  # re-parse below
            else:
                raise
    if base_parsed is None and request.baseText:
        parsed_base = await _nlp_service.parse_scenario(request.baseText)
        base_parsed = parsed_base.model_dump()
    if base_parsed is None:
        raise HTTPException(status_code=400, detail="Provide either session_id+uid or baseText")

    # Apply modifications
    mods = request.modifications

    # If either time field is explicitly set to null, clear both time fields
    # and mark onset as unknown. This prevents the bidirectional sync in
    # _normalize_parsed_variables from copying the old value back.
    time_fields = ("timeHours", "lastKnownWellHours", "lkwClockTime")
    time_nulled = any(k in mods and mods[k] is None for k in time_fields)
    if time_nulled:
        for f in time_fields:
            if f not in mods:
                mods[f] = None
        # If no explicit timeWindow was provided, mark as unknown
        if "timeWindow" not in mods and not mods.get("wakeUp"):
            mods["timeWindow"] = "unknown"

    base_parsed.update(mods)
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
        session_id=http_request.state.session_id,
        parsedVariables=parsed.model_dump(),
        ivtResult=_serialize_ivt_result(result["ivt_result"]),
        evtResult=_serialize_evt_result(result["evt_result"]),
        decisionState=result["decision_state"],
        notes=result["notes"],
        clinicalChecklists=result["checklists"],
        gateStatus=result.get("gate_status", {}),
    )


@router.post("/qa")
async def clinical_qa(request: QARequest, http_request: Request):
    """
    Q&A against guideline recommendations.

    Uses the multi-agent pipeline:
    IntentAgent → RecommendationAgent + SupportiveTextAgent + KnowledgeGapAgent → AssemblyAgent

    Recommendations are returned VERBATIM (never paraphrased).
    Supportive text and knowledge gaps may be summarized.
    Includes audit trail, scope gate, and clarification detection.

    Session-aware: loads prior Q&A turns so follow-up questions have context.
    """
    uid = request.uid
    session_id = http_request.state.session_id

    # ── Load conversation history for this session ──────────────
    conversation_history = []
    try:
        session_state = await _session_manager.get_session(uid, session_id)
        conversation_history = session_state.get("qa_history", [])
    except Exception as e:
        logger.warning("Failed to load session for QA history: %s", e)

    try:
        result = await _qa_orchestrator.answer(
            question=request.question,
            context=request.context,
            conversation_history=conversation_history,
        )
    except Exception as e:
        logger.error("QA orchestrator failed: %s", e)
        result = {
            "answer": "I'm sorry, I encountered an error processing your question. Please try again.",
            "summary": "",
            "citations": [],
            "relatedSections": [],
            "referencedTrials": [],
        }

    # ── Save this Q&A turn to session history ───────────────────
    # Keep last 10 turns (5 exchanges) to bound memory usage
    try:
        conversation_history.append({"role": "user", "content": request.question})
        answer_text = result.get("summary") or result.get("answer", "")
        if answer_text:
            turn_type = "clarification" if result.get("needsClarification") else "answer"
            conversation_history.append({"role": "assistant", "content": answer_text, "type": turn_type})
        # Trim to last 10 entries
        conversation_history = conversation_history[-10:]

        session_state = await _session_manager.get_session(uid, session_id)
        session_state["qa_history"] = conversation_history
        await _session_manager.save_session(uid, session_id, session_state)
    except Exception as e:
        logger.warning("Failed to save QA history: %s", e)

    result["session_id"] = session_id
    return result


@router.post("/qa/validate", response_model=QAValidationResponse)
async def validate_qa_answer(request: QAValidationRequest, http_request: Request):
    """
    Validate a Q&A answer when a clinician gives thumbs down feedback.

    Runs verbatim check (deterministic) + LLM validation.
    """
    if request.feedback == "thumbs_up":
        return QAValidationResponse(session_id=http_request.state.session_id)

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
        elif ctx.get("lastKnownWellHours") is not None: parts.append(f"LKW {ctx['lastKnownWellHours']}h")
        elif ctx.get("timeHours") is not None: parts.append(f"{ctx['timeHours']}h from symptom recognition")
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
        session_id=http_request.state.session_id,
        intentCorrect=llm_result.get("intentCorrect", True),
        recommendationsRelevant=llm_result.get("recommendationsRelevant", True),
        recommendationsVerbatim=len(verbatim_mismatches) == 0,
        summaryAccurate=llm_result.get("summaryAccurate", True),
        issues=issues,
        suggestedCorrection=llm_result.get("suggestedCorrection", ""),
        verbatimMismatches=verbatim_mismatches,
    )


class RecommendationsRequest(BaseModel):
    uid: str
    session_id: Optional[str] = None
    section: Optional[str] = None
    category: Optional[str] = None


@router.post("/recommendations")
async def list_recommendations(request: RecommendationsRequest, http_request: Request):
    """Browse/filter guideline recommendations."""
    if request.section:
        recs = get_recommendations_by_section(request.section)
    elif request.category:
        recs = get_recommendations_by_category(request.category)
    else:
        recs = load_recommendations()

    return {
        "session_id": http_request.state.session_id,
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


