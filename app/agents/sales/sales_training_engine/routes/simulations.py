"""
Simulations API router for MedSync AI Sales Simulation Engine.

Provides endpoints for creating, managing, and scoring simulation sessions.
Integrates the SimulationOrchestrator for AI-driven sales call simulations.
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..config import get_settings
from ..models.simulation_state import SimulationMode, SimulationStatus, Turn
from ..prompts.system_prompts import (
    list_physician_profiles,
)
from ..services.data_loader import DataManager, get_data_manager
from ..services.simulation_orchestrator import (
    ACTIVE_SESSIONS,
    SimulationOrchestrator,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/simulations", tags=["simulations"])


# Request/Response Models
class CreateSimulationRequest(BaseModel):
    """Request model for creating a new simulation session."""

    mode: str = Field(
        ...,
        description="Simulation mode",
        pattern="^(competitive_sales_call|product_knowledge|competitor_deep_dive|objection_handling)$",
    )
    physician_profile_id: str = Field(..., description="Physician profile ID (e.g., 'dr_chen')")
    rep_company: str = Field(..., description="Sales rep's company (e.g., 'Stryker', 'Medtronic')")
    rep_name: Optional[str] = Field(None, description="Sales rep's name for personalized interactions")
    difficulty_level: Optional[str] = Field(None, description="Difficulty level: beginner, intermediate, experienced")
    sub_mode: Optional[str] = Field(None, description="Sub-mode: conversational, structured (for product_knowledge)")
    competitor_company: Optional[str] = Field(
        None,
        description="Competitor company (required for competitor_deep_dive mode)",
    )

    class Config:
        """Pydantic config."""

        json_schema_extra = {
            "example": {
                "mode": "competitive_sales_call",
                "physician_profile_id": "dr_chen",
                "rep_company": "Stryker",
                "competitor_company": None,
            }
        }


class TurnRequest(BaseModel):
    """Request model for processing a turn in a simulation."""

    user_message: str = Field(..., description="The sales rep's message")

    class Config:
        """Pydantic config."""

        json_schema_extra = {
            "example": {
                "user_message": "I'd like to discuss our new thrombectomy device and how it could improve your outcomes."
            }
        }


class SimulationResponse(BaseModel):
    """Response model for simulation creation."""

    session_id: str = Field(..., description="Unique session identifier")
    mode: str = Field(..., description="Simulation mode")
    status: str = Field(..., description="Current session status")
    physician: Dict = Field(..., description="Physician profile information")
    rep_company: str = Field(..., description="Sales rep company")
    opening_message: Optional[str] = Field(None, description="AI opening message from physician")

    class Config:
        """Pydantic config."""

        json_schema_extra = {
            "example": {
                "session_id": "sim_a1b2c3d4",
                "mode": "competitive_sales_call",
                "status": "active",
                "physician": {
                    "id": "dr_chen",
                    "name": "Dr. Sarah Chen",
                    "specialty": "Neurointerventional Surgery",
                },
                "rep_company": "Stryker",
            }
        }


class CitationResponse(BaseModel):
    """Response model for citations."""

    citation_type: str = Field(..., description="Type of citation")
    reference: str = Field(..., description="Reference identifier")
    excerpt: str = Field(..., description="Relevant excerpt")
    verified: bool = Field(default=False, description="Whether verified")


class TurnResponse(BaseModel):
    """Response model for a simulation turn."""

    turn_number: int = Field(..., description="Turn number in sequence")
    ai_response: str = Field(..., description="AI-generated response")
    citations: List[Dict] = Field(default_factory=list, description="Citations for claims")
    scores: Optional[Dict[str, float]] = Field(None, description="Dimension scores")
    timestamp: str = Field(..., description="ISO timestamp")
    session_status: str = Field(..., description="Session status after turn")

    class Config:
        """Pydantic config."""

        json_schema_extra = {
            "example": {
                "turn_number": 2,
                "ai_response": "That's an important concern. Our device has been shown to improve reperfusion times...",
                "citations": [
                    {
                        "citation_type": "specs",
                        "reference": "device_spec_123",
                        "excerpt": "Device specifications...",
                    }
                ],
                "scores": {
                    "clinical_accuracy": 0.85,
                    "spec_accuracy": 0.92,
                },
                "timestamp": "2025-03-09T14:30:00Z",
                "session_status": "active",
            }
        }


class SessionListItem(BaseModel):
    """Item in session list."""

    session_id: str
    mode: str
    rep_company: str
    physician_name: str
    turn_count: int
    status: str
    created_at: str


@router.get("/")
async def list_sessions() -> Dict:
    """
    List all active simulation sessions.

    Returns:
        Dictionary with list of active sessions and count
    """
    try:
        sessions = []

        for session in ACTIVE_SESSIONS.values():
            sessions.append({
                "session_id": session.session_id,
                "mode": session.mode.value,
                "rep_company": session.rep_company,
                "physician_name": session.physician_profile.name,
                "turn_count": len(session.turns),
                "status": session.status.value,
                "created_at": session.created_at.isoformat() if hasattr(session.created_at, 'isoformat') else str(session.created_at),
            })

        return {
            "sessions": sessions,
            "total": len(sessions),
        }

    except Exception as e:
        logger.exception("Error listing sessions")
        raise HTTPException(
            status_code=500,
            detail=f"Error listing sessions: {str(e)}"
        )


@router.get("/physicians/available")
async def get_available_physicians() -> Dict:
    """
    Get list of available physician profiles for simulation.

    Returns:
        Dictionary with available physician profiles
    """
    try:
        physicians = list_physician_profiles()

        # Merge dossier physicians as additional options
        try:
            from ..services.dossier_service import get_dossier_service
            dossier_svc = get_dossier_service()
            dossier_summaries = dossier_svc.list_dossiers()
            existing_ids = {p["profile_id"] for p in physicians}
            for d in dossier_summaries:
                if d.id not in existing_ids:
                    physicians.append({
                        "profile_id": d.id,
                        "name": d.name,
                        "specialty": d.specialty or "Neurointerventional Surgery",
                        "hospital_type": d.institution or "",
                        "annual_cases": d.total_procedures or 0,
                        "experience_years": d.years_experience or 0,
                        "source": "dossier",
                    })
        except Exception as e:
            logger.warning(f"Failed to load dossier physicians: {e}")

        return {
            "physicians": physicians,
            "total": len(physicians),
        }

    except Exception as e:
        logger.exception("Error listing physicians")
        raise HTTPException(
            status_code=500,
            detail=f"Error listing physicians: {str(e)}"
        )


@router.post("/create")
async def create_simulation(
    request: CreateSimulationRequest,
    data_mgr: DataManager = Depends(get_data_manager),
) -> SimulationResponse:
    """
    Create a new simulation session.

    Request Body:
        mode: Simulation mode (competitive_sales_call, product_knowledge, etc.)
        physician_profile_id: ID of physician profile
        rep_company: Sales rep's company
        competitor_company: Optional competitor company for deep_dive mode

    Returns:
        SimulationResponse with session_id and physician details
    """
    try:
        # Validate mode
        try:
            SimulationMode(request.mode)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid mode: {request.mode}"
            )

        # Validate physician profile exists (skip for product_knowledge which uses 'examiner')
        if request.physician_profile_id != 'examiner':
            available_profiles = list_physician_profiles()
            profile_ids = [p["profile_id"] for p in available_profiles]
            if request.physician_profile_id not in profile_ids:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unknown physician profile: {request.physician_profile_id}"
                )

        # Create orchestrator and session
        orchestrator = SimulationOrchestrator(data_mgr)
        session = orchestrator.create_session(
            mode=request.mode,
            physician_profile_id=request.physician_profile_id,
            rep_company=request.rep_company,
            rep_name=request.rep_name or "",
            difficulty_level=request.difficulty_level or "intermediate",
            sub_mode=request.sub_mode or "",
        )

        # Store session
        ACTIVE_SESSIONS[session.session_id] = session

        # Generate LLM-powered physician opening message
        try:
            opening_message = await orchestrator.generate_opening(session)
        except Exception as e:
            logger.warning(f"Failed to generate LLM opening, using fallback: {e}")
            rep_greeting = f" {request.rep_name}," if request.rep_name else ","
            opening_message = f"Hello{rep_greeting} I'm Dr. {session.physician_profile.name.split()[-1]}. I'm interested in learning about your {request.rep_company} solutions."

        logger.info(f"Created simulation session: {session.session_id}")

        return SimulationResponse(
            session_id=session.session_id,
            mode=session.mode.value,
            status=session.status.value,
            physician={
                "id": session.physician_profile.id,
                "name": session.physician_profile.name,
                "specialty": session.physician_profile.specialty,
                "institution": session.physician_profile.institution,
                "case_volume": session.physician_profile.case_volume,
            },
            rep_company=request.rep_company,
            opening_message=opening_message,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error creating simulation")
        raise HTTPException(
            status_code=500,
            detail=f"Error creating simulation: {str(e)}"
        )


@router.post("/{session_id}/turn")
async def process_turn(
    session_id: str,
    request: TurnRequest,
    data_mgr: DataManager = Depends(get_data_manager),
) -> TurnResponse:
    """
    Process a turn in an active simulation session.

    Path Parameters:
        session_id: The session ID

    Request Body:
        user_message: The sales rep's message

    Returns:
        TurnResponse with AI response, citations, and scores

    Raises:
        404: If session not found
        400: If session is not active
    """
    try:
        # Get session
        session = ACTIVE_SESSIONS.get(session_id)
        if not session:
            raise HTTPException(
                status_code=404,
                detail=f"Session {session_id} not found"
            )

        # Check turn limit
        if len(session.turns) >= 20:
            raise HTTPException(
                status_code=400,
                detail="Maximum turns reached for session"
            )

        # Process turn through orchestrator (this is async)
        orchestrator = SimulationOrchestrator(data_mgr)
        turn = await orchestrator.process_turn(
            session=session,
            user_message=request.user_message,
        )

        # Get updated session
        session = ACTIVE_SESSIONS[session_id]

        logger.info(f"Processed turn {len(session.turns)} for session {session_id}")

        return TurnResponse(
            turn_number=turn.turn_number,
            ai_response=turn.message,
            citations=[c.model_dump() if hasattr(c, 'model_dump') else c for c in turn.citations],
            scores=turn.scores,
            timestamp=turn.timestamp.isoformat() if hasattr(turn.timestamp, 'isoformat') else str(turn.timestamp),
            session_status=session.status.value,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error processing turn for session {session_id}")
        raise HTTPException(
            status_code=500,
            detail=f"Error processing turn: {str(e)}"
        )


@router.get("/{session_id}")
async def get_session_state(
    session_id: str,
) -> Dict:
    """
    Get full state of a simulation session.

    Path Parameters:
        session_id: The session ID

    Returns:
        Dictionary with complete session state including all turns

    Raises:
        404: If session not found
    """
    try:
        session = ACTIVE_SESSIONS.get(session_id)

        if not session:
            raise HTTPException(
                status_code=404,
                detail=f"Session {session_id} not found"
            )

        # Build response with turn history
        turns_data = []
        for turn in session.turns:
            turns_data.append({
                "turn_number": turn.turn_number,
                "speaker": turn.speaker,
                "message": turn.message,
                "timestamp": turn.timestamp.isoformat() if hasattr(turn.timestamp, 'isoformat') else str(turn.timestamp),
                "citations": [c.model_dump() if hasattr(c, 'model_dump') else c for c in turn.citations],
                "scores": turn.scores,
            })

        return {
            "session_id": session.session_id,
            "mode": session.mode.value,
            "status": session.status.value,
            "physician_profile": {
                "id": session.physician_profile.id,
                "name": session.physician_profile.name,
                "specialty": session.physician_profile.specialty,
            },
            "rep_company": session.rep_company,
            "turns": turns_data,
            "turn_count": len(session.turns),
            "created_at": session.created_at.isoformat() if hasattr(session.created_at, 'isoformat') else str(session.created_at),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error retrieving session {session_id}")
        raise HTTPException(
            status_code=500,
            detail=f"Error retrieving session: {str(e)}"
        )


@router.get("/{session_id}/score")
async def get_session_score(
    session_id: str,
    data_mgr: DataManager = Depends(get_data_manager),
) -> Dict:
    """
    Get scoring summary for a session.

    Path Parameters:
        session_id: The session ID

    Returns:
        Dictionary with dimension scores, overall score, trend, and insights
    """
    try:
        session = ACTIVE_SESSIONS.get(session_id)

        if not session:
            raise HTTPException(
                status_code=404,
                detail=f"Session {session_id} not found"
            )

        # Calculate scores from turns
        orchestrator = SimulationOrchestrator(data_mgr)
        score_summary = await orchestrator.get_session_summary(session)

        return score_summary

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error getting score for session {session_id}")
        raise HTTPException(
            status_code=500,
            detail=f"Error getting scores: {str(e)}"
        )


@router.post("/{session_id}/end")
async def end_session(
    session_id: str,
    data_mgr: DataManager = Depends(get_data_manager),
) -> Dict:
    """
    End a simulation session and get final scores.

    Path Parameters:
        session_id: The session ID

    Returns:
        Dictionary with final session summary and scores
    """
    try:
        session = ACTIVE_SESSIONS.get(session_id)

        if not session:
            raise HTTPException(
                status_code=404,
                detail=f"Session {session_id} not found"
            )

        # Mark as completed
        session.status = SimulationStatus.COMPLETED

        # Get final scores
        orchestrator = SimulationOrchestrator(data_mgr)
        score_summary = await orchestrator.get_session_summary(session)

        logger.info(f"Ended session {session_id}")

        return {
            "session_id": session_id,
            "status": "completed",
            "turn_count": len(session.turns),
            "scores": score_summary,
            "completed_at": datetime.utcnow().isoformat() + "Z",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error ending session {session_id}")
        raise HTTPException(
            status_code=500,
            detail=f"Error ending session: {str(e)}"
        )
