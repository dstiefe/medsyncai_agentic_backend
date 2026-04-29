"""
IFU Change Alerts API router.

Provides endpoints for IFU version tracking, change alerts, and acknowledgments.
For beta: seeds simulated alerts to demonstrate the workflow.
"""

import hashlib
import json
import logging
import uuid
from datetime import datetime
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..config import get_settings
from ..services.persistence_service import PersistenceService, get_persistence_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ifu", tags=["ifu_alerts"])


class AcknowledgeRequest(BaseModel):
    rep_id: str


# Simulated alerts for beta demo
SEED_ALERTS = [
    {
        "alert_id": "ifu_alert_001",
        "device_id": "ace_68",
        "device_name": "ACE 68",
        "manufacturer": "Penumbra",
        "change_type": "contraindication_update",
        "sections_affected": ["contraindications", "warnings"],
        "summary": "New contraindication added for patients with severe vessel tortuosity (greater than 90-degree angulation at the ICA). Updated warning about catheter tip positioning during aspiration.",
        "detected_at": "2026-03-10T14:30:00Z",
        "severity": "critical",
    },
    {
        "alert_id": "ifu_alert_002",
        "device_id": "solitaire_x",
        "device_name": "Solitaire X",
        "manufacturer": "Medtronic",
        "change_type": "compatibility_update",
        "sections_affected": ["compatibility", "procedure"],
        "summary": "Updated compatibility table for new generation microcatheters. Added clearance data for Phenom 27 delivery.",
        "detected_at": "2026-03-08T09:15:00Z",
        "severity": "important",
    },
    {
        "alert_id": "ifu_alert_003",
        "device_id": "sofia_plus",
        "device_name": "SOFIA Plus",
        "manufacturer": "MicroVention",
        "change_type": "procedure_update",
        "sections_affected": ["procedure", "indications"],
        "summary": "Expanded indications to include posterior circulation use. Added procedural guidance for basilar artery thrombectomy.",
        "detected_at": "2026-03-05T16:00:00Z",
        "severity": "info",
    },
    {
        "alert_id": "ifu_alert_004",
        "device_id": "trevo_xp",
        "device_name": "Trevo XP ProVue",
        "manufacturer": "Stryker",
        "change_type": "adverse_event_update",
        "sections_affected": ["adverse_events", "warnings"],
        "summary": "Updated adverse event reporting section with post-market surveillance data. New guidance on managing vessel perforation events.",
        "detected_at": "2026-03-01T11:00:00Z",
        "severity": "important",
    },
]


@router.get("/status")
async def get_ifu_status(
    persistence: PersistenceService = Depends(get_persistence_service),
) -> Dict:
    """Get current IFU version tracking status."""
    tracking = persistence.get_ifu_tracking()
    return tracking


@router.get("/alerts")
async def list_alerts(
    persistence: PersistenceService = Depends(get_persistence_service),
) -> Dict:
    """List all IFU change alerts."""
    tracking = persistence.get_ifu_tracking()
    alerts = tracking.get("alerts", [])
    return {"alerts": alerts, "total": len(alerts)}


@router.get("/alerts/{rep_id}/pending")
async def get_pending_alerts(
    rep_id: str,
    persistence: PersistenceService = Depends(get_persistence_service),
) -> Dict:
    """Get unacknowledged alerts for a rep."""
    tracking = persistence.get_ifu_tracking()
    alerts = tracking.get("alerts", [])
    acknowledgments = tracking.get("acknowledgments", [])

    # Get alert IDs acknowledged by this rep
    acked_ids = {
        a["alert_id"]
        for a in acknowledgments
        if a.get("rep_id") == rep_id
    }

    pending = [a for a in alerts if a["alert_id"] not in acked_ids]
    return {"alerts": pending, "total": len(pending)}


@router.post("/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(
    alert_id: str,
    request: AcknowledgeRequest,
    persistence: PersistenceService = Depends(get_persistence_service),
) -> Dict:
    """Acknowledge an IFU alert."""
    tracking = persistence.get_ifu_tracking()

    # Verify alert exists
    alerts = tracking.get("alerts", [])
    if not any(a["alert_id"] == alert_id for a in alerts):
        raise HTTPException(status_code=404, detail="Alert not found")

    if "acknowledgments" not in tracking:
        tracking["acknowledgments"] = []

    tracking["acknowledgments"].append({
        "alert_id": alert_id,
        "rep_id": request.rep_id,
        "acknowledged_at": datetime.utcnow().isoformat() + "Z",
    })

    persistence.save_ifu_tracking(tracking)
    return {"status": "ok"}


@router.post("/scan")
async def scan_ifu(
    persistence: PersistenceService = Depends(get_persistence_service),
) -> Dict:
    """
    Trigger IFU scan. For beta: seeds simulated alerts if none exist.
    In production, this would compare current IFU document hashes against stored versions.
    """
    tracking = persistence.get_ifu_tracking()

    if not tracking.get("alerts"):
        # Seed with demo alerts
        tracking["alerts"] = SEED_ALERTS
        tracking["last_scan"] = datetime.utcnow().isoformat() + "Z"
        tracking["scan_count"] = tracking.get("scan_count", 0) + 1

        # Build device status from document chunks
        settings = get_settings()
        chunk_file = settings.data_dir / "document_chunks.json"
        devices_status = {}

        if chunk_file.exists():
            try:
                with open(chunk_file, "r") as f:
                    chunks = json.load(f)

                ifu_chunks = [c for c in chunks if c.get("source_type") == "ifu"]
                for chunk in ifu_chunks:
                    device_id = chunk.get("device_id", "unknown")
                    if device_id not in devices_status:
                        devices_status[device_id] = {
                            "device_name": chunk.get("device_name", device_id),
                            "manufacturer": chunk.get("manufacturer", ""),
                            "chunk_count": 0,
                            "sections": set(),
                        }
                    devices_status[device_id]["chunk_count"] += 1
                    section = chunk.get("section_hint", "")
                    if section:
                        devices_status[device_id]["sections"].add(section)

                # Convert sets to lists for JSON serialization
                for d in devices_status.values():
                    d["sections"] = list(d["sections"])

            except (json.JSONDecodeError, IOError):
                pass

        tracking["devices"] = devices_status
        if "acknowledgments" not in tracking:
            tracking["acknowledgments"] = []

        persistence.save_ifu_tracking(tracking)

        return {
            "status": "ok",
            "new_alerts": len(SEED_ALERTS),
            "message": "IFU scan complete. Found simulated changes for demo.",
        }

    tracking["last_scan"] = datetime.utcnow().isoformat() + "Z"
    tracking["scan_count"] = tracking.get("scan_count", 0) + 1
    persistence.save_ifu_tracking(tracking)

    return {
        "status": "ok",
        "new_alerts": 0,
        "message": "IFU scan complete. No new changes detected.",
    }
