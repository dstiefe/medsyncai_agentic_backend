"""
API router for physician dossiers.

Provides CRUD endpoints for managing physician dossiers with
real CMS Medicare Provider Utilization data.
"""

import logging
from typing import Dict

from fastapi import APIRouter, HTTPException

from ..models.physician_dossier import Interaction, PhysicianDossier
from ..services.dossier_service import get_dossier_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dossiers", tags=["dossiers"])


@router.get("/")
async def list_dossiers() -> dict:
    """List all physician dossiers (summary view)."""
    svc = get_dossier_service()
    summaries = svc.list_dossiers()
    return {"dossiers": [s.model_dump() for s in summaries]}


@router.get("/{physician_id}")
async def get_dossier(physician_id: str) -> dict:
    """Get a full physician dossier by ID."""
    svc = get_dossier_service()
    dossier = svc.get_dossier(physician_id)
    if not dossier:
        raise HTTPException(status_code=404, detail=f"Dossier not found: {physician_id}")
    return dossier.model_dump()


@router.post("/")
async def create_dossier(dossier: PhysicianDossier) -> dict:
    """Create a new physician dossier."""
    svc = get_dossier_service()
    existing = svc.get_dossier(dossier.id)
    if existing:
        raise HTTPException(status_code=409, detail=f"Dossier already exists: {dossier.id}")
    created = svc.create_dossier(dossier)
    return created.model_dump()


@router.put("/{physician_id}")
async def update_dossier(physician_id: str, updates: Dict) -> dict:
    """Full update of a physician dossier."""
    svc = get_dossier_service()
    updated = svc.update_dossier(physician_id, updates)
    if not updated:
        raise HTTPException(status_code=404, detail=f"Dossier not found: {physician_id}")
    return updated.model_dump()


@router.patch("/{physician_id}/{section}")
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


@router.delete("/{physician_id}")
async def delete_dossier(physician_id: str) -> dict:
    """Delete a physician dossier."""
    svc = get_dossier_service()
    deleted = svc.delete_dossier(physician_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Dossier not found: {physician_id}")
    return {"status": "deleted", "physician_id": physician_id}


@router.post("/{physician_id}/interactions")
async def add_interaction(physician_id: str, interaction: Interaction) -> dict:
    """Add a new interaction to a physician's relationship tracking."""
    svc = get_dossier_service()
    updated = svc.add_interaction(physician_id, interaction)
    if not updated:
        raise HTTPException(status_code=404, detail=f"Dossier not found: {physician_id}")
    return updated.model_dump()


@router.post("/{physician_id}/generate-payer-intelligence")
async def generate_payer_intelligence(physician_id: str) -> dict:
    """Generate AI-synthesized payer intelligence from all CMS data sources."""
    svc = get_dossier_service()
    dossier = svc.get_dossier(physician_id)
    if not dossier:
        raise HTTPException(status_code=404, detail=f"Dossier not found: {physician_id}")

    try:
        updated = await svc.generate_payer_intelligence(physician_id)
        if not updated:
            raise HTTPException(status_code=500, detail="Failed to generate intelligence")
        return updated.model_dump()
    except Exception as e:
        logger.exception(f"Error generating payer intelligence for {physician_id}")
        raise HTTPException(status_code=500, detail=f"Error generating intelligence: {str(e)}")


@router.get("/{physician_id}/prompt-summary")
async def get_prompt_summary(physician_id: str) -> dict:
    """Get LLM-ready text summary for a physician dossier."""
    svc = get_dossier_service()
    summary = svc.get_prompt_summary(physician_id)
    if summary is None:
        raise HTTPException(status_code=404, detail=f"Dossier not found: {physician_id}")
    return {"physician_id": physician_id, "summary": summary}
