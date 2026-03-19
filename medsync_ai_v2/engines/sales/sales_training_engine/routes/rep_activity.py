"""
Rep profile and activity tracking API router.

Provides endpoints for rep registration, activity logging, and dashboard data.
"""

import logging
import uuid
from datetime import datetime
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..models.rep_profile import ActivityLogEntry, RepProfile
from ..services.persistence_service import PersistenceService, get_persistence_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/reps", tags=["rep_activity"])


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

@router.post("/register")
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


@router.get("/{rep_id}")
async def get_rep_profile(
    rep_id: str,
    persistence: PersistenceService = Depends(get_persistence_service),
) -> Dict:
    """Get a rep's profile."""
    profile = persistence.get_rep_profile(rep_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Rep not found")
    return profile


@router.get("/")
async def list_reps(
    persistence: PersistenceService = Depends(get_persistence_service),
) -> Dict:
    """List all registered reps."""
    profiles = persistence.get_all_rep_profiles()
    return {"reps": profiles, "total": len(profiles)}


@router.post("/{rep_id}/activity")
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


@router.get("/{rep_id}/activity")
async def get_rep_activity(
    rep_id: str,
    limit: int = 50,
    activity_type: Optional[str] = None,
    persistence: PersistenceService = Depends(get_persistence_service),
) -> Dict:
    """Get activity log for a rep."""
    activities = persistence.get_rep_activities(rep_id, limit=limit, activity_type=activity_type)
    return {"activities": activities, "total": len(activities)}


@router.get("/{rep_id}/dashboard")
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


@router.get("/{rep_id}/scores/summary")
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
