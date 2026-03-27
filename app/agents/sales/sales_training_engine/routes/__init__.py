"""
Sales Training Engine — route registry.

Mounts all source API routers from medsync-sales-engine.
Source routes use /api/ prefix; we remap to /sales/ for the MedSync backend.
"""

from fastapi import APIRouter

from .simulations import router as simulations_router
from .scoring import router as scoring_router
from .devices import router as devices_router
from .meeting_prep import router as meeting_prep_router
from .knowledge_qa import router as knowledge_qa_router
from .rep_activity import router as rep_activity_router
from .manager import router as manager_router
from .certifications import router as certifications_router
from .field_intel import router as field_intel_router
from .ifu_alerts import router as ifu_alerts_router
from .workflow import router as workflow_router
from .dossiers import router as dossiers_router
from .reimbursement import router as reimbursement_router
from .assessment import router as assessment_router
from .procedure_workflow import router as procedure_workflow_router

router = APIRouter()

# Mount all source routers (each has /api/<name> prefix from source)
router.include_router(simulations_router)
router.include_router(scoring_router)
router.include_router(devices_router)
router.include_router(meeting_prep_router)
router.include_router(knowledge_qa_router)
router.include_router(rep_activity_router)
router.include_router(manager_router)
router.include_router(certifications_router)
router.include_router(field_intel_router)
router.include_router(ifu_alerts_router)
router.include_router(workflow_router)
router.include_router(dossiers_router)
router.include_router(reimbursement_router)
router.include_router(assessment_router)
router.include_router(procedure_workflow_router)


@router.get("/sales/health")
async def sales_health():
    """Health check for the sales training engine."""
    return {"status": "ok", "engine": "sales_training"}
