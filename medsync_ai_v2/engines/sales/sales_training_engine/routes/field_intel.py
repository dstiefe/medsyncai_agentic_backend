"""
Field Intelligence API router.

Provides endpoints for capturing meeting debriefs and viewing competitive intelligence.
"""

import logging
import uuid
from datetime import datetime
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..services.persistence_service import PersistenceService, get_persistence_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/field-intel", tags=["field_intel"])


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

@router.post("/debrief")
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


@router.get("/debriefs")
async def list_debriefs(
    rep_id: Optional[str] = None,
    limit: int = 50,
    persistence: PersistenceService = Depends(get_persistence_service),
) -> Dict:
    """List field debriefs."""
    debriefs = persistence.get_field_debriefs(rep_id=rep_id, limit=limit)
    return {"debriefs": debriefs, "total": len(debriefs)}


@router.get("/trends")
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


@router.get("/win-loss")
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
