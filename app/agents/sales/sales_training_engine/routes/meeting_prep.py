"""
Meeting Prep API router for MedSync AI Sales Simulation Engine.

Provides endpoints for generating intelligence briefs, managing meeting prep
sessions, and launching rehearsal simulations.
"""

import logging
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException

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
from ..prompts.mode_meeting_prep import get_rehearsal_prompt
from ..services.data_loader import DataManager, get_data_manager
from ..services.meeting_prep_service import ACTIVE_PREPS, MeetingPrepService
from ..services.simulation_orchestrator import ACTIVE_SESSIONS

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/meeting-prep", tags=["meeting-prep"])


@router.post("/generate")
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


@router.get("/{prep_id}/brief")
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


@router.post("/{prep_id}/rehearse")
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
        import uuid
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
            "note": "Use /api/simulations/{session_id}/turn to send messages",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error starting rehearsal for prep {prep_id}")
        raise HTTPException(
            status_code=500,
            detail=f"Error starting rehearsal: {str(e)}"
        )


@router.get("/")
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
