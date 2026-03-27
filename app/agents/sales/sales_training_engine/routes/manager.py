"""
Manager console API router.

Provides endpoints for team overview, rep detail, and training assignments.
"""

import logging
import uuid
from datetime import datetime
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..services.persistence_service import PersistenceService, get_persistence_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/manager", tags=["manager"])


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

@router.get("/team-overview")
async def get_team_overview(
    persistence: PersistenceService = Depends(get_persistence_service),
) -> Dict:
    """Get aggregated team overview."""
    return persistence.get_team_overview()


@router.get("/rep/{rep_id}/detail")
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


@router.post("/assignments")
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


@router.get("/assignments")
async def list_assignments(
    rep_id: Optional[str] = None,
    persistence: PersistenceService = Depends(get_persistence_service),
) -> Dict:
    """List training assignments."""
    assignments = persistence.get_assignments(rep_id)
    return {"assignments": assignments, "total": len(assignments)}


@router.patch("/assignments/{assignment_id}")
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
