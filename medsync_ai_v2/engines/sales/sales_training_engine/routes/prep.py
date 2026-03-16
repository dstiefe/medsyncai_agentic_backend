"""
Consolidated Prep routes for MedSync AI Sales Training Engine.

Migrated from:
  - api/meeting_prep.py  -> /sales/meeting-prep
  - api/dossiers.py      -> /sales/dossiers
  - api/manager.py       -> /sales/manager
  - api/rep_activity.py  -> /sales/reps
  - api/field_intel.py   -> /sales/field-intel
"""

import logging
import uuid
from datetime import datetime
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..models.meeting_prep import (
    MeetingPrepRequest,
    MeetingPrepSession,
    IntelligenceBrief,
)
from ..models.simulation_state import (
    SimulationMode,
    SimulationSession,
    SimulationStatus,
)
from ..models.physician_dossier import Interaction, PhysicianDossier
from ..models.rep_profile import ActivityLogEntry, RepProfile
from ..services.data_loader import DataManager, get_data_manager
from ..services.meeting_prep_service import ACTIVE_PREPS, MeetingPrepService
from ..services.simulation_orchestrator import ACTIVE_SESSIONS
from ..services.persistence_service import PersistenceService, get_persistence_service
from ..services.dossier_service import get_dossier_service
from ..services.system_prompts import get_rehearsal_prompt

logger = logging.getLogger(__name__)


# ── Meeting Prep Router ───────────────────────────────────────────────────

meeting_prep_router = APIRouter(prefix="/sales/meeting-prep", tags=["Sales Meeting Prep"])


@meeting_prep_router.post("/generate")
async def generate_brief(
    request: MeetingPrepRequest,
    data_mgr: DataManager = Depends(get_data_manager),
) -> Dict:
    """
    Generate a pre-call intelligence brief from meeting details.

    Request Body:
        physician_name: Name of the physician
        physician_device_ids: List of device IDs they currently use
        physician_specialty: Their specialty
        hospital_type: Type of institution
        rep_company: Sales rep's company
        (plus optional fields: annual_case_volume, products_to_pitch,
         known_objections, meeting_context)

    Returns:
        Dictionary with prep_id and the complete intelligence brief
    """
    try:
        service = MeetingPrepService(data_mgr)
        prep_session = service.generate_brief(request)

        brief = prep_session.brief

        return {
            "prep_id": prep_session.prep_id,
            "status": prep_session.status,
            "brief": {
                "brief_id": brief.brief_id,
                "physician_name": brief.physician_name,
                "physician_specialty": brief.physician_specialty,
                "hospital_type": brief.hospital_type,
                "annual_case_volume": brief.annual_case_volume,
                "inferred_approach": brief.inferred_approach,
                "current_stack": brief.current_stack_summary,
                "device_comparisons": [
                    {
                        "physician_device": comp.physician_device_name,
                        "physician_manufacturer": comp.physician_manufacturer,
                        "rep_device": comp.rep_device_name,
                        "rep_manufacturer": comp.rep_manufacturer,
                        "advantages": comp.spec_advantages,
                        "disadvantages": comp.spec_disadvantages,
                    }
                    for comp in brief.device_comparisons
                ],
                "competitive_claims": brief.competitive_claims,
                "compatibility_insights": [
                    {
                        "rep_device": ci.rep_device_name,
                        "physician_device": ci.physician_device_name,
                        "compatible": ci.compatible,
                        "explanation": ci.explanation,
                    }
                    for ci in brief.compatibility_insights
                ],
                "migration_path": [
                    {
                        "step": step.order,
                        "action": step.action,
                        "rationale": step.rationale,
                        "disruption": step.disruption_level,
                    }
                    for step in brief.migration_path
                ],
                "talking_points": [
                    {
                        "headline": tp.headline,
                        "detail": tp.detail,
                        "evidence_type": tp.evidence_type,
                        "citations": tp.citations,
                    }
                    for tp in brief.talking_points
                ],
                "objection_playbook": [
                    {
                        "objection": obj.objection,
                        "likelihood": obj.likelihood,
                        "recommended_response": obj.recommended_response,
                        "supporting_data": obj.supporting_data,
                    }
                    for obj in brief.objection_playbook
                ],
                "data_sources_used": brief.data_sources_used,
            },
        }

    except Exception as e:
        logger.exception("Error generating intelligence brief")
        raise HTTPException(
            status_code=500,
            detail=f"Error generating brief: {str(e)}"
        )


@meeting_prep_router.get("/{prep_id}/brief")
async def get_brief(prep_id: str) -> Dict:
    """
    Retrieve a previously generated intelligence brief.

    Path Parameters:
        prep_id: The meeting prep session ID

    Returns:
        The intelligence brief data

    Raises:
        404: If prep session not found
    """
    try:
        prep_session = ACTIVE_PREPS.get(prep_id)
        if not prep_session:
            raise HTTPException(
                status_code=404,
                detail=f"Meeting prep session {prep_id} not found"
            )

        brief = prep_session.brief
        return {
            "prep_id": prep_id,
            "status": prep_session.status,
            "brief": brief.model_dump(),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error retrieving brief {prep_id}")
        raise HTTPException(
            status_code=500,
            detail=f"Error retrieving brief: {str(e)}"
        )


@meeting_prep_router.post("/{prep_id}/rehearse")
async def start_rehearsal(
    prep_id: str,
    data_mgr: DataManager = Depends(get_data_manager),
) -> Dict:
    """
    Start a rehearsal simulation based on a meeting prep brief.

    Creates a customized simulation session where the AI plays the target
    physician with their actual device stack, predicted objections, and
    personality traits.

    Path Parameters:
        prep_id: The meeting prep session ID

    Returns:
        Simulation session details with session_id for sending turns

    Raises:
        404: If prep session not found
    """
    try:
        prep_session = ACTIVE_PREPS.get(prep_id)
        if not prep_session:
            raise HTTPException(
                status_code=404,
                detail=f"Meeting prep session {prep_id} not found"
            )

        # Create dynamic physician profile from brief
        service = MeetingPrepService(data_mgr)
        physician_profile = service.create_rehearsal_profile(prep_session)

        # Create a simulation session
        session_id = f"rehearsal_{uuid.uuid4().hex[:8]}"

        request = prep_session.request
        brief = prep_session.brief

        # Get rep portfolio device IDs
        rep_portfolio = []
        if request.products_to_pitch:
            rep_portfolio = request.products_to_pitch
        else:
            for d in data_mgr.get_all_devices():
                if d.manufacturer.lower() == request.rep_company.lower():
                    rep_portfolio.append(d.id)

        session = SimulationSession(
            session_id=session_id,
            mode=SimulationMode.COMPETITIVE_SALES_CALL,
            status=SimulationStatus.ACTIVE,
            physician_profile=physician_profile,
            rep_company=request.rep_company,
            rep_portfolio_ids=rep_portfolio[:50],
            scenario_context={
                "meeting_prep_id": prep_id,
                "meeting_context": request.meeting_context,
                "physician_devices": request.physician_device_ids,
                "inferred_approach": brief.inferred_approach,
                "rehearsal": True,
            },
        )

        # Store the session
        ACTIVE_SESSIONS[session_id] = session

        # Link rehearsal to prep session
        prep_session.rehearsal_session_id = session_id
        prep_session.status = "rehearsing"

        # Generate opening message
        opening = (
            f"Hello, I'm {physician_profile.name}. I've got a few minutes — "
            f"what would you like to discuss about your {request.rep_company} products?"
        )

        logger.info(f"Started rehearsal {session_id} for prep {prep_id}")

        return {
            "session_id": session_id,
            "prep_id": prep_id,
            "mode": "competitive_sales_call",
            "status": "active",
            "physician": {
                "name": physician_profile.name,
                "specialty": physician_profile.specialty,
                "institution": physician_profile.institution,
                "case_volume": physician_profile.case_volume,
                "technique_preference": physician_profile.technique_preference,
            },
            "rep_company": request.rep_company,
            "opening_message": opening,
            "note": "Use /sales/simulations/{session_id}/turn to send messages",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error starting rehearsal for prep {prep_id}")
        raise HTTPException(
            status_code=500,
            detail=f"Error starting rehearsal: {str(e)}"
        )


@meeting_prep_router.get("/")
async def list_preps() -> Dict:
    """
    List all meeting prep sessions.

    Returns:
        Dictionary with list of prep sessions and count
    """
    try:
        preps = []
        for prep in ACTIVE_PREPS.values():
            preps.append({
                "prep_id": prep.prep_id,
                "physician_name": prep.brief.physician_name,
                "rep_company": prep.brief.rep_company,
                "status": prep.status,
                "rehearsal_session_id": prep.rehearsal_session_id,
                "created_at": prep.created_at.isoformat(),
            })

        return {
            "preps": preps,
            "total": len(preps),
        }

    except Exception as e:
        logger.exception("Error listing preps")
        raise HTTPException(
            status_code=500,
            detail=f"Error listing preps: {str(e)}"
        )


# ── Dossier Router ────────────────────────────────────────────────────────

dossier_router = APIRouter(prefix="/sales/dossiers", tags=["Sales Dossiers"])


@dossier_router.get("/")
async def list_dossiers() -> dict:
    """List all physician dossiers (summary view)."""
    svc = get_dossier_service()
    summaries = svc.list_dossiers()
    return {"dossiers": [s.model_dump() for s in summaries]}


@dossier_router.get("/{physician_id}")
async def get_dossier(physician_id: str) -> dict:
    """Get a full physician dossier by ID."""
    svc = get_dossier_service()
    dossier = svc.get_dossier(physician_id)
    if not dossier:
        raise HTTPException(status_code=404, detail=f"Dossier not found: {physician_id}")
    return dossier.model_dump()


@dossier_router.post("/")
async def create_dossier(dossier: PhysicianDossier) -> dict:
    """Create a new physician dossier."""
    svc = get_dossier_service()
    existing = svc.get_dossier(dossier.id)
    if existing:
        raise HTTPException(status_code=409, detail=f"Dossier already exists: {dossier.id}")
    created = svc.create_dossier(dossier)
    return created.model_dump()


@dossier_router.put("/{physician_id}")
async def update_dossier(physician_id: str, updates: Dict) -> dict:
    """Full update of a physician dossier."""
    svc = get_dossier_service()
    updated = svc.update_dossier(physician_id, updates)
    if not updated:
        raise HTTPException(status_code=404, detail=f"Dossier not found: {physician_id}")
    return updated.model_dump()


@dossier_router.patch("/{physician_id}/{section}")
async def update_section(physician_id: str, section: str, data: Dict) -> dict:
    """Partial update of a specific dossier section."""
    svc = get_dossier_service()
    updated = svc.update_section(physician_id, section, data)
    if not updated:
        raise HTTPException(
            status_code=404,
            detail=f"Dossier not found or invalid section: {physician_id}/{section}",
        )
    return updated.model_dump()


@dossier_router.delete("/{physician_id}")
async def delete_dossier(physician_id: str) -> dict:
    """Delete a physician dossier."""
    svc = get_dossier_service()
    deleted = svc.delete_dossier(physician_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Dossier not found: {physician_id}")
    return {"status": "deleted", "physician_id": physician_id}


@dossier_router.post("/{physician_id}/interactions")
async def add_interaction(physician_id: str, interaction: Interaction) -> dict:
    """Add a new interaction to a physician's relationship tracking."""
    svc = get_dossier_service()
    updated = svc.add_interaction(physician_id, interaction)
    if not updated:
        raise HTTPException(status_code=404, detail=f"Dossier not found: {physician_id}")
    return updated.model_dump()


@dossier_router.get("/{physician_id}/prompt-summary")
async def get_prompt_summary(physician_id: str) -> dict:
    """Get LLM-ready text summary for a physician dossier."""
    svc = get_dossier_service()
    summary = svc.get_prompt_summary(physician_id)
    if summary is None:
        raise HTTPException(status_code=404, detail=f"Dossier not found: {physician_id}")
    return {"physician_id": physician_id, "summary": summary}


# ── Manager Router ────────────────────────────────────────────────────────

manager_router = APIRouter(prefix="/sales/manager", tags=["Sales Manager"])


# --- Request/Response Models ---

class CreateAssignmentRequest(BaseModel):
    assigned_by: str
    assigned_to: str
    assignment_type: str = Field(..., description="simulation, assessment, certification")
    description: str = ""
    mode: Optional[str] = None
    due_date: Optional[str] = None


class UpdateAssignmentRequest(BaseModel):
    status: Optional[str] = None
    description: Optional[str] = None


# --- Endpoints ---

@manager_router.get("/team-overview")
async def get_team_overview(
    persistence: PersistenceService = Depends(get_persistence_service),
) -> Dict:
    """Get aggregated team overview."""
    return persistence.get_team_overview()


@manager_router.get("/rep/{rep_id}/detail")
async def get_rep_detail(
    rep_id: str,
    persistence: PersistenceService = Depends(get_persistence_service),
) -> Dict:
    """Get full detail for one rep."""
    profile = persistence.get_rep_profile(rep_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Rep not found")

    dashboard = persistence.get_rep_dashboard_data(rep_id)
    dashboard["profile"] = profile
    return dashboard


@manager_router.post("/assignments")
async def create_assignment(
    request: CreateAssignmentRequest,
    persistence: PersistenceService = Depends(get_persistence_service),
) -> Dict:
    """Create a training assignment."""
    assignment = {
        "assignment_id": uuid.uuid4().hex[:12],
        "assigned_by": request.assigned_by,
        "assigned_to": request.assigned_to,
        "assignment_type": request.assignment_type,
        "description": request.description,
        "mode": request.mode,
        "due_date": request.due_date,
        "status": "pending",
        "created_at": datetime.utcnow().isoformat() + "Z",
    }
    persistence.save_assignment(assignment)
    return {"status": "ok", "assignment": assignment}


@manager_router.get("/assignments")
async def list_assignments(
    rep_id: Optional[str] = None,
    persistence: PersistenceService = Depends(get_persistence_service),
) -> Dict:
    """List training assignments."""
    assignments = persistence.get_assignments(rep_id)
    return {"assignments": assignments, "total": len(assignments)}


@manager_router.patch("/assignments/{assignment_id}")
async def update_assignment(
    assignment_id: str,
    request: UpdateAssignmentRequest,
    persistence: PersistenceService = Depends(get_persistence_service),
) -> Dict:
    """Update an assignment."""
    updates = {}
    if request.status:
        updates["status"] = request.status
    if request.description:
        updates["description"] = request.description

    success = persistence.update_assignment(assignment_id, updates)
    if not success:
        raise HTTPException(status_code=404, detail="Assignment not found")
    return {"status": "ok"}


# ── Rep Activity Router ──────────────────────────────────────────────────

rep_router = APIRouter(prefix="/sales/reps", tags=["Sales Rep Activity"])


# --- Request/Response Models ---

class RegisterRepRequest(BaseModel):
    rep_id: str = Field(..., description="Client-generated UUID for the rep")
    name: str = Field(..., description="Rep's full name")
    company: str = Field(..., description="Rep's company")
    role: str = Field(default="rep", description="Role: rep or manager")


class LogActivityRequest(BaseModel):
    activity_type: str = Field(..., description="Type: simulation, assessment, qa_session, meeting_prep, field_debrief")
    mode: Optional[str] = None
    session_id: Optional[str] = None
    physician_id: Optional[str] = None
    physician_name: Optional[str] = None
    company: str = ""
    duration_seconds: Optional[int] = None
    scores: Optional[Dict[str, float]] = None
    overall_score: Optional[float] = None
    metadata: Dict = {}


# --- Endpoints ---

@rep_router.post("/register")
async def register_rep(
    request: RegisterRepRequest,
    persistence: PersistenceService = Depends(get_persistence_service),
) -> Dict:
    """Register or update a rep profile."""
    try:
        now = datetime.utcnow().isoformat() + "Z"

        # Check if rep already exists
        existing = persistence.get_rep_profile(request.rep_id)

        profile = RepProfile(
            rep_id=request.rep_id,
            name=request.name,
            company=request.company,
            role=request.role,
            created_at=existing["created_at"] if existing else now,
            last_active=now,
        )

        persistence.save_rep_profile(profile)
        logger.info(f"Registered rep: {request.name} ({request.rep_id})")

        return {"status": "ok", "rep_id": request.rep_id, "profile": profile.model_dump()}

    except Exception as e:
        logger.exception("Error registering rep")
        raise HTTPException(status_code=500, detail=str(e))


@rep_router.get("/{rep_id}")
async def get_rep_profile(
    rep_id: str,
    persistence: PersistenceService = Depends(get_persistence_service),
) -> Dict:
    """Get a rep's profile."""
    profile = persistence.get_rep_profile(rep_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Rep not found")
    return profile


@rep_router.get("/")
async def list_reps(
    persistence: PersistenceService = Depends(get_persistence_service),
) -> Dict:
    """List all registered reps."""
    profiles = persistence.get_all_rep_profiles()
    return {"reps": profiles, "total": len(profiles)}


@rep_router.post("/{rep_id}/activity")
async def log_activity(
    rep_id: str,
    request: LogActivityRequest,
    persistence: PersistenceService = Depends(get_persistence_service),
) -> Dict:
    """Log an activity for a rep."""
    try:
        entry = ActivityLogEntry(
            entry_id=uuid.uuid4().hex[:12],
            rep_id=rep_id,
            activity_type=request.activity_type,
            mode=request.mode,
            session_id=request.session_id,
            physician_id=request.physician_id,
            physician_name=request.physician_name,
            company=request.company,
            timestamp=datetime.utcnow().isoformat() + "Z",
            duration_seconds=request.duration_seconds,
            scores=request.scores,
            overall_score=request.overall_score,
            metadata=request.metadata,
        )

        persistence.log_activity(entry)
        logger.info(f"Logged activity for rep {rep_id}: {request.activity_type}")

        return {"status": "ok", "entry_id": entry.entry_id}

    except Exception as e:
        logger.exception("Error logging activity")
        raise HTTPException(status_code=500, detail=str(e))


@rep_router.get("/{rep_id}/activity")
async def get_rep_activity(
    rep_id: str,
    limit: int = 50,
    activity_type: Optional[str] = None,
    persistence: PersistenceService = Depends(get_persistence_service),
) -> Dict:
    """Get activity log for a rep."""
    activities = persistence.get_rep_activities(rep_id, limit=limit, activity_type=activity_type)
    return {"activities": activities, "total": len(activities)}


@rep_router.get("/{rep_id}/dashboard")
async def get_dashboard(
    rep_id: str,
    persistence: PersistenceService = Depends(get_persistence_service),
) -> Dict:
    """Get aggregated dashboard data for a rep."""
    try:
        profile = persistence.get_rep_profile(rep_id)
        if not profile:
            raise HTTPException(status_code=404, detail="Rep not found")

        dashboard = persistence.get_rep_dashboard_data(rep_id)
        dashboard["profile"] = profile

        return dashboard

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error getting dashboard")
        raise HTTPException(status_code=500, detail=str(e))


@rep_router.get("/{rep_id}/scores/summary")
async def get_scores_summary(
    rep_id: str,
    persistence: PersistenceService = Depends(get_persistence_service),
) -> Dict:
    """Get aggregated score summary for a rep."""
    dashboard = persistence.get_rep_dashboard_data(rep_id)
    return {
        "dimension_averages": dashboard.get("dimension_averages", {}),
        "score_history": dashboard.get("score_history", []),
        "total_scored_sessions": len(dashboard.get("score_history", [])),
    }


# ── Field Intel Router ───────────────────────────────────────────────────

field_intel_router = APIRouter(prefix="/sales/field-intel", tags=["Sales Field Intel"])


# --- Request Models ---

class SubmitDebriefRequest(BaseModel):
    rep_id: str
    physician_name: str
    physician_id: Optional[str] = None
    hospital: Optional[str] = None
    meeting_type: str = "office_visit"
    devices_discussed: List[str] = []
    competitor_devices_mentioned: List[str] = []
    objections_encountered: List[str] = []
    physician_feedback: str = ""
    outcome: str = "follow_up_needed"
    next_steps: str = ""
    confidence_level: int = 5
    notes: str = ""


# --- Endpoints ---

@field_intel_router.post("/debrief")
async def submit_debrief(
    request: SubmitDebriefRequest,
    persistence: PersistenceService = Depends(get_persistence_service),
) -> Dict:
    """Submit a field meeting debrief."""
    debrief = {
        "debrief_id": uuid.uuid4().hex[:12],
        "rep_id": request.rep_id,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "physician_name": request.physician_name,
        "physician_id": request.physician_id,
        "hospital": request.hospital,
        "meeting_type": request.meeting_type,
        "devices_discussed": request.devices_discussed,
        "competitor_devices_mentioned": request.competitor_devices_mentioned,
        "objections_encountered": request.objections_encountered,
        "physician_feedback": request.physician_feedback,
        "outcome": request.outcome,
        "next_steps": request.next_steps,
        "confidence_level": request.confidence_level,
        "notes": request.notes,
    }

    persistence.save_field_debrief(debrief)
    logger.info(f"Field debrief submitted by {request.rep_id}: {request.physician_name}")

    return {"status": "ok", "debrief_id": debrief["debrief_id"]}


@field_intel_router.get("/debriefs")
async def list_debriefs(
    rep_id: Optional[str] = None,
    limit: int = 50,
    persistence: PersistenceService = Depends(get_persistence_service),
) -> Dict:
    """List field debriefs."""
    debriefs = persistence.get_field_debriefs(rep_id=rep_id, limit=limit)
    return {"debriefs": debriefs, "total": len(debriefs)}


@field_intel_router.get("/trends")
async def get_trends(
    persistence: PersistenceService = Depends(get_persistence_service),
) -> Dict:
    """Get aggregated competitive intelligence trends from debriefs."""
    debriefs = persistence.get_field_debriefs(limit=200)

    # Aggregate competitor device mentions
    competitor_counts: Dict[str, int] = {}
    objection_counts: Dict[str, int] = {}
    outcome_counts: Dict[str, int] = {"win": 0, "loss": 0, "deferred": 0, "follow_up_needed": 0}

    for d in debriefs:
        for device in d.get("competitor_devices_mentioned", []):
            competitor_counts[device] = competitor_counts.get(device, 0) + 1
        for obj in d.get("objections_encountered", []):
            objection_counts[obj] = objection_counts.get(obj, 0) + 1
        outcome = d.get("outcome", "")
        if outcome in outcome_counts:
            outcome_counts[outcome] += 1

    return {
        "total_debriefs": len(debriefs),
        "top_competitor_devices": sorted(competitor_counts.items(), key=lambda x: x[1], reverse=True)[:10],
        "top_objections": sorted(objection_counts.items(), key=lambda x: x[1], reverse=True)[:10],
        "outcome_distribution": outcome_counts,
    }


@field_intel_router.get("/win-loss")
async def get_win_loss(
    rep_id: Optional[str] = None,
    persistence: PersistenceService = Depends(get_persistence_service),
) -> Dict:
    """Get win/loss tracking summary."""
    debriefs = persistence.get_field_debriefs(rep_id=rep_id, limit=500)

    wins = len([d for d in debriefs if d.get("outcome") == "win"])
    losses = len([d for d in debriefs if d.get("outcome") == "loss"])
    deferred = len([d for d in debriefs if d.get("outcome") == "deferred"])
    follow_ups = len([d for d in debriefs if d.get("outcome") == "follow_up_needed"])

    return {
        "total": len(debriefs),
        "wins": wins,
        "losses": losses,
        "deferred": deferred,
        "follow_up_needed": follow_ups,
        "win_rate": round(wins / max(wins + losses, 1) * 100, 1),
    }
