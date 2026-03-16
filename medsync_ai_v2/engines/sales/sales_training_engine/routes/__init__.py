"""
Sales Training Engine — consolidated route registry.

Combines all 13 source API routers into 4 files, exposed via a single master router.
"""

from fastapi import APIRouter

from .simulations import simulation_router, scoring_router
from .devices import device_router, workflow_router, ifu_router
from .training import assessment_router, certification_router, qa_router
from .prep import (
    meeting_prep_router,
    dossier_router,
    manager_router,
    rep_router,
    field_intel_router,
)

router = APIRouter()

# Simulations + Scoring
router.include_router(simulation_router)
router.include_router(scoring_router)

# Devices + Workflow + IFU
router.include_router(device_router)
router.include_router(workflow_router)
router.include_router(ifu_router)

# Training (Assessment + Certifications + QA)
router.include_router(assessment_router)
router.include_router(certification_router)
router.include_router(qa_router)

# Prep (Meeting Prep + Dossiers + Manager + Reps + Field Intel)
router.include_router(meeting_prep_router)
router.include_router(dossier_router)
router.include_router(manager_router)
router.include_router(rep_router)
router.include_router(field_intel_router)


@router.get("/sales/health")
async def sales_health():
    """Health check for the sales training engine."""
    return {"status": "ok", "engine": "sales_training"}
