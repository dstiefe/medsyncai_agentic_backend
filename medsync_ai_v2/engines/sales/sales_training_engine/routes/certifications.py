"""
Certification and badging API router.

Provides endpoints for certification paths, progress tracking, and badge awards.
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException

from ..config import get_settings
from ..services.persistence_service import PersistenceService, get_persistence_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/certifications", tags=["certifications"])

# Default certification paths
DEFAULT_CERT_PATHS = [
    {
        "cert_id": "evt_specialist",
        "name": "EVT Specialist",
        "description": "Demonstrate mastery of endovascular thrombectomy device knowledge through structured assessments.",
        "company": "all",
        "requirements": [
            {"requirement_type": "assessment_score", "min_score": 0.80, "count": 2},
        ],
        "badge_icon": "trophy",
        "validity_months": 6,
    },
    {
        "cert_id": "aspiration_expert",
        "name": "Aspiration Technique Expert",
        "description": "Prove your expertise in aspiration-first thrombectomy approaches across multiple simulations.",
        "company": "all",
        "requirements": [
            {"requirement_type": "simulation_count", "mode": "competitive_sales_call", "count": 3, "min_score": 0.80},
        ],
        "badge_icon": "star",
        "validity_months": 6,
    },
    {
        "cert_id": "competitive_pro",
        "name": "Competitive Positioning Pro",
        "description": "Show strong competitive knowledge across multiple scored sessions.",
        "company": "all",
        "requirements": [
            {"requirement_type": "dimension_min", "dimension": "competitive_knowledge", "min_score": 0.80, "count": 5},
        ],
        "badge_icon": "shield",
        "validity_months": 6,
    },
    {
        "cert_id": "objection_master",
        "name": "Objection Handling Master",
        "description": "Master evidence-based responses to physician objections.",
        "company": "all",
        "requirements": [
            {"requirement_type": "dimension_min", "dimension": "objection_handling", "min_score": 0.80, "count": 3},
        ],
        "badge_icon": "lightning",
        "validity_months": 6,
    },
    {
        "cert_id": "regulatory_expert",
        "name": "Regulatory Compliance Expert",
        "description": "Demonstrate strong knowledge of IFU boundaries, contraindications, and on-label usage.",
        "company": "all",
        "requirements": [
            {"requirement_type": "dimension_min", "dimension": "regulatory_compliance", "min_score": 0.85, "count": 3},
        ],
        "badge_icon": "check_circle",
        "validity_months": 6,
    },
]


def _get_cert_paths() -> List[dict]:
    """Load certification paths from config or use defaults."""
    settings = get_settings()
    cert_file = settings.data_dir / "certification_paths.json"
    if cert_file.exists():
        try:
            with open(cert_file, "r") as f:
                data = json.load(f)
                return data.get("paths", DEFAULT_CERT_PATHS)
        except (json.JSONDecodeError, IOError):
            pass
    return DEFAULT_CERT_PATHS


@router.get("/paths")
async def list_cert_paths() -> Dict:
    """List all certification paths."""
    paths = _get_cert_paths()
    return {"paths": paths, "total": len(paths)}


@router.get("/{rep_id}")
async def get_rep_certifications(
    rep_id: str,
    persistence: PersistenceService = Depends(get_persistence_service),
) -> Dict:
    """Get certifications earned by a rep."""
    certs = persistence.get_rep_certifications(rep_id)
    return {"certifications": certs, "total": len(certs)}


@router.post("/{rep_id}/check")
async def check_certifications(
    rep_id: str,
    persistence: PersistenceService = Depends(get_persistence_service),
) -> Dict:
    """Check if a rep qualifies for new certifications."""
    paths = _get_cert_paths()
    existing = persistence.get_rep_certifications(rep_id)
    existing_ids = {c.get("cert_id") for c in existing if c.get("status") == "active"}

    activities = persistence.get_rep_activities(rep_id, limit=500)
    scored_activities = [a for a in activities if a.get("scores")]

    newly_earned = []

    for path in paths:
        if path["cert_id"] in existing_ids:
            continue

        qualified = _check_requirements(path["requirements"], scored_activities)
        if qualified:
            now = datetime.utcnow()
            cert = {
                "rep_id": rep_id,
                "cert_id": path["cert_id"],
                "cert_name": path["name"],
                "earned_at": now.isoformat() + "Z",
                "expires_at": (now + timedelta(days=path.get("validity_months", 6) * 30)).isoformat() + "Z",
                "status": "active",
            }
            persistence.save_certification(cert)
            newly_earned.append(cert)

    return {"newly_earned": newly_earned, "total_earned": len(existing) + len(newly_earned)}


@router.get("/{rep_id}/progress")
async def get_cert_progress(
    rep_id: str,
    persistence: PersistenceService = Depends(get_persistence_service),
) -> Dict:
    """Get progress toward each certification for a rep."""
    paths = _get_cert_paths()
    existing = persistence.get_rep_certifications(rep_id)
    existing_map = {c.get("cert_id"): c for c in existing}

    activities = persistence.get_rep_activities(rep_id, limit=500)
    scored_activities = [a for a in activities if a.get("scores")]

    progress = []
    for path in paths:
        cert_id = path["cert_id"]
        earned = existing_map.get(cert_id)

        req_progress = []
        for req in path["requirements"]:
            current, needed = _compute_progress(req, scored_activities)
            req_progress.append({
                "requirement_type": req["requirement_type"],
                "current": current,
                "needed": needed,
                "met": current >= needed,
            })

        progress.append({
            "cert_id": cert_id,
            "name": path["name"],
            "description": path["description"],
            "badge_icon": path.get("badge_icon", ""),
            "earned": earned is not None and earned.get("status") == "active",
            "earned_at": earned.get("earned_at") if earned else None,
            "expires_at": earned.get("expires_at") if earned else None,
            "requirements": req_progress,
            "overall_progress": sum(1 for r in req_progress if r["met"]) / max(len(req_progress), 1),
        })

    return {"progress": progress}


def _check_requirements(requirements: List[dict], scored_activities: List[dict]) -> bool:
    """Check if all requirements for a certification are met."""
    for req in requirements:
        current, needed = _compute_progress(req, scored_activities)
        if current < needed:
            return False
    return True


def _compute_progress(req: dict, scored_activities: List[dict]) -> tuple:
    """Compute (current, needed) for a single requirement."""
    req_type = req.get("requirement_type", "")
    needed = req.get("count", 1)
    min_score = req.get("min_score", 0.80)

    if req_type == "assessment_score":
        qualifying = [
            a for a in scored_activities
            if a.get("activity_type") in ("assessment", "simulation")
            and (a.get("overall_score") or 0) >= min_score
        ]
        return len(qualifying), needed

    elif req_type == "simulation_count":
        mode = req.get("mode")
        qualifying = [
            a for a in scored_activities
            if a.get("activity_type") == "simulation"
            and (not mode or a.get("mode") == mode)
            and (a.get("overall_score") or 0) >= min_score
        ]
        return len(qualifying), needed

    elif req_type == "dimension_min":
        dimension = req.get("dimension", "")
        qualifying = [
            a for a in scored_activities
            if (a.get("scores") or {}).get(dimension, 0) >= min_score
        ]
        return len(qualifying), needed

    return 0, needed
