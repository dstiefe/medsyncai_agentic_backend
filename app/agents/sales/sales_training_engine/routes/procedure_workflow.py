"""
Procedure Workflow API router for MedSync AI Sales Training Engine.

Provides endpoints for browsing step-by-step procedure workflows,
comparing devices within a procedure, and searching across workflows.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..services.procedure_workflow_service import (
    ProcedureWorkflowService,
    get_procedure_workflow_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/procedure-workflows", tags=["procedure-workflows"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------

class SearchRequest(BaseModel):
    """Request body for the workflow search endpoint."""

    query: str = Field(..., min_length=2, description="Search query string")


# ---------------------------------------------------------------------------
# Dependency
# ---------------------------------------------------------------------------

def _get_service() -> ProcedureWorkflowService:
    return get_procedure_workflow_service()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/")
async def list_workflows(
    service: ProcedureWorkflowService = Depends(_get_service),
) -> Dict:
    """
    List all available procedure workflows.

    Returns:
        Dictionary with workflows list and total count.
    """
    try:
        summaries = service.get_workflows()
        return {
            "workflows": [s.model_dump() for s in summaries],
            "total": len(summaries),
        }
    except Exception as exc:
        logger.exception("Error listing procedure workflows")
        raise HTTPException(status_code=500, detail=f"Error listing workflows: {exc}")


@router.get("/{procedure_id}")
async def get_workflow(
    procedure_id: str,
    service: ProcedureWorkflowService = Depends(_get_service),
) -> Dict:
    """
    Get a full procedure workflow by ID, including all steps and device mappings.

    Path Parameters:
        procedure_id: The procedure identifier (e.g. 'mechanical-thrombectomy').

    Raises:
        404: If the procedure workflow is not found.
    """
    workflow = service.get_workflow(procedure_id)
    if workflow is None:
        raise HTTPException(
            status_code=404,
            detail=f"Procedure workflow '{procedure_id}' not found",
        )
    return workflow.model_dump()


@router.get("/{procedure_id}/compare")
async def compare_devices(
    procedure_id: str,
    deviceA: str = Query(..., description="Name (or partial name) of the first device"),
    deviceB: str = Query(..., description="Name (or partial name) of the second device"),
    service: ProcedureWorkflowService = Depends(_get_service),
) -> Dict:
    """
    Compare two devices within a procedure workflow.

    Returns side-by-side device mappings including manufacturer notes
    and differentiators, plus the shared step context if both devices
    appear in the same procedure step.

    Path Parameters:
        procedure_id: The procedure identifier.

    Query Parameters:
        deviceA: Name or partial name of the first device.
        deviceB: Name or partial name of the second device.

    Raises:
        404: If the procedure workflow is not found.
    """
    result = service.compare_devices(procedure_id, deviceA, deviceB)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"Procedure workflow '{procedure_id}' not found",
        )
    return result.model_dump()


@router.post("/search")
async def search_workflows(
    body: SearchRequest,
    service: ProcedureWorkflowService = Depends(_get_service),
) -> Dict:
    """
    Search across all procedure workflows by procedure name or device name.

    Request Body:
        query: Search string (minimum 2 characters).

    Returns:
        Dictionary with matching results and count.
    """
    try:
        results = service.search_workflows(body.query)
        return {
            "results": results,
            "count": len(results),
            "query": body.query,
        }
    except Exception as exc:
        logger.exception("Error searching procedure workflows")
        raise HTTPException(status_code=500, detail=f"Search error: {exc}")
