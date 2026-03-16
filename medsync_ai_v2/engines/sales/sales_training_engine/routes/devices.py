"""
Consolidated Devices + Workflow + IFU Alerts routes for MedSync AI Sales Training Engine.

Migrated from:
  - api/devices.py     -> /sales/devices
  - api/workflow.py    -> /sales/workflow
  - api/ifu_alerts.py  -> /sales/ifu
"""

import hashlib
import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from ..models.device import Device
from ..services.data_loader import DataManager, get_data_manager
from ..services.persistence_service import PersistenceService, get_persistence_service

logger = logging.getLogger(__name__)


# ── Device Router ─────────────────────────────────────────────────────────

device_router = APIRouter(prefix="/sales/devices", tags=["Sales Devices"])


def get_data_manager_dep() -> DataManager:
    """
    Dependency injection for DataManager.

    Returns:
        DataManager: The loaded data manager instance.
    """
    return get_data_manager()


@device_router.get("/")
async def list_devices(
    manufacturer: Optional[str] = Query(None, description="Filter by manufacturer name"),
    category: Optional[str] = Query(None, description="Filter by category key"),
    limit: int = Query(50, ge=1, le=500, description="Maximum number of devices to return"),
    data_mgr: DataManager = Depends(get_data_manager_dep),
) -> Dict:
    """
    List all devices with optional filtering.

    Query Parameters:
        manufacturer: Filter by manufacturer name (case-insensitive)
        category: Filter by category key (e.g., 'guide', 'catheter', 'sheath')
        limit: Maximum number of devices to return (default 50, max 500)

    Returns:
        Dictionary with devices list and total count
    """
    try:
        devices = list(data_mgr.devices.values())

        # Filter by manufacturer
        if manufacturer:
            devices = [
                d for d in devices
                if d.manufacturer.lower() == manufacturer.lower()
            ]

        # Filter by category
        if category:
            devices = [
                d for d in devices
                if d.category.key.lower() == category.lower()
            ]

        # Apply limit
        devices = devices[:limit]

        # Build response with summary specs
        device_summaries = [
            {
                "id": d.id,
                "manufacturer": d.manufacturer,
                "device_name": d.device_name,
                "product_name": d.product_name,
                "category": d.category.display_name,
                "category_key": d.category.key,
                "specs_summary": {
                    "inner_diameter_mm": d.specifications.inner_diameter.mm,
                    "outer_diameter_distal_mm": d.specifications.outer_diameter_distal.mm,
                    "length_cm": d.specifications.length.cm,
                },
            }
            for d in devices
        ]

        return {
            "devices": device_summaries,
            "total": len(device_summaries),
            "filtered": bool(manufacturer or category),
        }

    except Exception as e:
        logger.exception("Error listing devices")
        raise HTTPException(status_code=500, detail=f"Error listing devices: {str(e)}")


@device_router.get("/manufacturers")
async def list_manufacturers(
    data_mgr: DataManager = Depends(get_data_manager_dep),
) -> Dict:
    """
    Get list of all manufacturers with device counts.

    Returns:
        Dictionary with manufacturers and their device statistics
    """
    try:
        manufacturers = {}

        for device in data_mgr.devices.values():
            mfr = device.manufacturer

            if mfr not in manufacturers:
                manufacturers[mfr] = {
                    "name": mfr,
                    "device_count": 0,
                    "categories": set(),
                    "product_count": 0,
                }

            manufacturers[mfr]["device_count"] += 1
            manufacturers[mfr]["categories"].add(device.category.key)
            manufacturers[mfr]["product_count"] += 1

        # Convert sets to lists for JSON serialization
        result = []
        for mfr_data in manufacturers.values():
            result.append({
                "name": mfr_data["name"],
                "device_count": mfr_data["device_count"],
                "categories": sorted(list(mfr_data["categories"])),
                "product_count": mfr_data["product_count"],
            })

        return {
            "manufacturers": sorted(result, key=lambda x: x["name"]),
            "total": len(result),
        }

    except Exception as e:
        logger.exception("Error listing manufacturers")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@device_router.get("/categories")
async def list_categories(
    data_mgr: DataManager = Depends(get_data_manager_dep),
) -> Dict:
    """
    Get list of all device categories with device counts.

    Returns:
        Dictionary with categories and their statistics
    """
    try:
        categories = {}

        for device in data_mgr.devices.values():
            cat_key = device.category.key

            if cat_key not in categories:
                categories[cat_key] = {
                    "key": cat_key,
                    "display_name": device.category.display_name,
                    "group": device.category.group,
                    "role": device.category.role,
                    "device_count": 0,
                }

            categories[cat_key]["device_count"] += 1

        result = list(categories.values())
        result.sort(key=lambda x: x["display_name"])

        return {
            "categories": result,
            "total": len(result),
        }

    except Exception as e:
        logger.exception("Error listing categories")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@device_router.get("/search")
async def search_devices(
    q: str = Query(..., description="Search query (device name, product name, or alias)"),
    manufacturer: Optional[str] = Query(None, description="Filter by manufacturer"),
    limit: int = Query(20, ge=1, le=100, description="Maximum results"),
    data_mgr: DataManager = Depends(get_data_manager_dep),
) -> Dict:
    """
    Search for devices by name or alias.

    Query Parameters:
        q: Search query string
        manufacturer: Optional manufacturer filter
        limit: Maximum number of results

    Returns:
        Dictionary with matching devices and count
    """
    try:
        if not q or len(q.strip()) < 2:
            raise HTTPException(
                status_code=400,
                detail="Search query must be at least 2 characters"
            )

        query_lower = q.lower()
        results = []

        for device in data_mgr.devices.values():
            # Check if query matches device name, product name, or aliases
            if (
                query_lower in device.device_name.lower()
                or query_lower in device.product_name.lower()
                or any(query_lower in alias.lower() for alias in device.aliases)
            ):
                # Apply manufacturer filter if specified
                if manufacturer and device.manufacturer.lower() != manufacturer.lower():
                    continue

                results.append({
                    "id": device.id,
                    "manufacturer": device.manufacturer,
                    "device_name": device.device_name,
                    "product_name": device.product_name,
                    "category": device.category.display_name,
                    "category_key": device.category.key,
                })

        # Apply limit
        results = results[:limit]

        return {
            "results": results,
            "count": len(results),
            "query": q,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error searching devices")
        raise HTTPException(status_code=500, detail=f"Search error: {str(e)}")


@device_router.get("/{device_id}")
async def get_device(
    device_id: int,
    data_mgr: DataManager = Depends(get_data_manager_dep),
) -> Dict:
    """
    Get full details for a specific device.

    Path Parameters:
        device_id: The device ID

    Returns:
        Complete Device object with all specifications and sources

    Raises:
        404: If device not found
    """
    try:
        device = data_mgr.devices.get(device_id)

        if not device:
            raise HTTPException(
                status_code=404,
                detail=f"Device {device_id} not found"
            )

        return device.model_dump()

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error retrieving device {device_id}")
        raise HTTPException(status_code=500, detail=f"Error retrieving device: {str(e)}")


@device_router.get("/{device_id}/compatible")
async def get_compatible_devices(
    device_id: int,
    direction: str = Query("all", pattern="^(fits_inside|accepts|all)$"),
    limit: int = Query(20, ge=1, le=100),
    data_mgr: DataManager = Depends(get_data_manager_dep),
) -> Dict:
    """
    Get devices compatible with the specified device.

    Path Parameters:
        device_id: The reference device ID

    Query Parameters:
        direction: Type of compatibility
            - fits_inside: Find devices that fit inside this device
            - accepts: Find devices this device fits inside
            - all: Return all compatible relationships (default)
        limit: Maximum number of compatible devices to return

    Returns:
        Dictionary with reference device and list of compatible devices
    """
    try:
        device = data_mgr.devices.get(device_id)

        if not device:
            raise HTTPException(
                status_code=404,
                detail=f"Device {device_id} not found"
            )

        # Get compatibility information from compatibility matrix
        compatible_data = data_mgr.compatibility_matrix.get(str(device_id), {})

        compatible_ids = []
        if direction == "fits_inside" or direction == "all":
            compatible_ids.extend(
                compatible_data.get("fits_inside", [])
            )
        if direction == "accepts" or direction == "all":
            compatible_ids.extend(
                compatible_data.get("accepts", [])
            )

        # Remove duplicates while preserving order
        compatible_ids = list(dict.fromkeys(compatible_ids))

        compatible_devices = []
        for comp_id in compatible_ids[:limit]:
            comp_device = data_mgr.devices.get(comp_id)
            if comp_device:
                compatible_devices.append({
                    "device_id": comp_device.id,
                    "device_name": comp_device.device_name,
                    "manufacturer": comp_device.manufacturer,
                    "category": comp_device.category.display_name,
                    "fit_type": direction,
                })

        return {
            "device": {
                "id": device.id,
                "name": device.device_name,
                "manufacturer": device.manufacturer,
            },
            "compatible": compatible_devices,
            "count": len(compatible_devices),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error getting compatible devices for {device_id}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


# ── Workflow Router ───────────────────────────────────────────────────────

workflow_router = APIRouter(prefix="/sales/workflow", tags=["Sales Workflow"])

# Data directory for compatibility matrix — resolve relative to this package
_DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def _load_compatibility_matrix() -> dict:
    """Load the compatibility matrix data."""
    matrix_file = _DATA_DIR / "compatibility_matrix.json"
    if not matrix_file.exists():
        return {"procedural_stacks": [], "fits_inside": []}
    try:
        with open(matrix_file, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {"procedural_stacks": [], "fits_inside": []}


@workflow_router.get("/stacks")
async def list_stacks(
    manufacturer: Optional[str] = None,
    limit: int = Query(default=50, le=200),
    offset: int = 0,
) -> Dict:
    """List procedural stacks, optionally filtered by manufacturer."""
    matrix = _load_compatibility_matrix()
    stacks = matrix.get("procedural_stacks", [])

    if manufacturer:
        stacks = [s for s in stacks if s.get("manufacturer", "").lower() == manufacturer.lower()]

    total = len(stacks)
    paginated = stacks[offset:offset + limit]

    # Enrich with index
    enriched = []
    for i, stack in enumerate(paginated):
        enriched.append({
            "index": offset + i,
            "manufacturer": stack.get("manufacturer", ""),
            "devices": stack.get("devices", []),
        })

    return {"stacks": enriched, "total": total, "offset": offset, "limit": limit}


@workflow_router.get("/stacks/{index}")
async def get_stack(index: int) -> Dict:
    """Get a single procedural stack by index."""
    matrix = _load_compatibility_matrix()
    stacks = matrix.get("procedural_stacks", [])

    if index < 0 or index >= len(stacks):
        raise HTTPException(status_code=404, detail="Stack not found")

    stack = stacks[index]
    return {
        "index": index,
        "manufacturer": stack.get("manufacturer", ""),
        "devices": stack.get("devices", []),
    }


@workflow_router.post("/swap-analysis")
async def swap_analysis(data: dict) -> Dict:
    """
    Analyze the impact of swapping a device in a stack.

    Expects: {stack_index, level, new_device_id}
    Returns: compatibility impact analysis.
    """
    stack_index = data.get("stack_index", 0)
    level = data.get("level", 0)
    new_device_id = data.get("new_device_id", "")

    matrix = _load_compatibility_matrix()
    stacks = matrix.get("procedural_stacks", [])
    fits_data = matrix.get("fits_inside", [])

    if stack_index < 0 or stack_index >= len(stacks):
        raise HTTPException(status_code=404, detail="Stack not found")

    stack = stacks[stack_index]
    devices = stack.get("devices", [])

    # Find the device being replaced
    original_device = None
    for d in devices:
        if d.get("level") == level:
            original_device = d
            break

    # Look up new device info
    data_mgr = get_data_manager()
    new_device_info = data_mgr.devices.get(new_device_id, {})

    # Build compatibility report
    compatible_with = []

    for fit in fits_data:
        if fit.get("inner_device_id") == new_device_id or fit.get("outer_device_id") == new_device_id:
            compatible_with.append({
                "device_id": fit.get("outer_device_id") if fit.get("inner_device_id") == new_device_id else fit.get("inner_device_id"),
                "clearance_mm": fit.get("clearance_mm", 0),
                "fit_type": fit.get("fit_type", ""),
            })

    return {
        "stack_index": stack_index,
        "level": level,
        "original_device": original_device,
        "new_device": {
            "device_id": new_device_id,
            "device_name": new_device_info.get("name", new_device_id),
            "manufacturer": new_device_info.get("manufacturer", ""),
        },
        "compatibility": compatible_with[:10],
        "stack_devices": devices,
    }


@workflow_router.post("/compare")
async def compare_stacks(data: dict) -> Dict:
    """
    Compare two procedural stacks side by side.

    Expects: {stack_a_index, stack_b_index}
    """
    index_a = data.get("stack_a_index", 0)
    index_b = data.get("stack_b_index", 1)

    matrix = _load_compatibility_matrix()
    stacks = matrix.get("procedural_stacks", [])

    if index_a < 0 or index_a >= len(stacks):
        raise HTTPException(status_code=404, detail="Stack A not found")
    if index_b < 0 or index_b >= len(stacks):
        raise HTTPException(status_code=404, detail="Stack B not found")

    stack_a = stacks[index_a]
    stack_b = stacks[index_b]

    # Build level-by-level comparison
    levels_a = {d.get("level"): d for d in stack_a.get("devices", [])}
    levels_b = {d.get("level"): d for d in stack_b.get("devices", [])}

    all_levels = sorted(set(list(levels_a.keys()) + list(levels_b.keys())))

    comparison = []
    for level in all_levels:
        dev_a = levels_a.get(level)
        dev_b = levels_b.get(level)
        comparison.append({
            "level": level,
            "stack_a": dev_a,
            "stack_b": dev_b,
            "same_device": (
                dev_a and dev_b and
                dev_a.get("device_id") == dev_b.get("device_id")
            ),
        })

    return {
        "stack_a": {"index": index_a, "manufacturer": stack_a.get("manufacturer", ""), "devices": stack_a.get("devices", [])},
        "stack_b": {"index": index_b, "manufacturer": stack_b.get("manufacturer", ""), "devices": stack_b.get("devices", [])},
        "comparison": comparison,
    }


@workflow_router.get("/device/{device_id}/fits")
async def get_device_fits(device_id: str) -> Dict:
    """Get what fits inside or outside a specific device."""
    matrix = _load_compatibility_matrix()
    fits_data = matrix.get("fits_inside", [])

    fits_inside = [
        {
            "device_id": f.get("inner_device_id"),
            "device_name": f.get("inner_device_name", ""),
            "clearance_mm": f.get("clearance_mm", 0),
            "fit_type": f.get("fit_type", ""),
        }
        for f in fits_data
        if f.get("outer_device_id") == device_id
    ]

    fits_outside = [
        {
            "device_id": f.get("outer_device_id"),
            "device_name": f.get("outer_device_name", ""),
            "clearance_mm": f.get("clearance_mm", 0),
            "fit_type": f.get("fit_type", ""),
        }
        for f in fits_data
        if f.get("inner_device_id") == device_id
    ]

    return {
        "device_id": device_id,
        "fits_inside": fits_inside,
        "fits_outside": fits_outside,
    }


# ── IFU Alerts Router ────────────────────────────────────────────────────

ifu_router = APIRouter(prefix="/sales/ifu", tags=["Sales IFU Alerts"])


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


@ifu_router.get("/status")
async def get_ifu_status(
    persistence: PersistenceService = Depends(get_persistence_service),
) -> Dict:
    """Get current IFU version tracking status."""
    tracking = persistence.get_ifu_tracking()
    return tracking


@ifu_router.get("/alerts")
async def list_alerts(
    persistence: PersistenceService = Depends(get_persistence_service),
) -> Dict:
    """List all IFU change alerts."""
    tracking = persistence.get_ifu_tracking()
    alerts = tracking.get("alerts", [])
    return {"alerts": alerts, "total": len(alerts)}


@ifu_router.get("/alerts/{rep_id}/pending")
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


@ifu_router.post("/alerts/{alert_id}/acknowledge")
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


@ifu_router.post("/scan")
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
        chunk_file = _DATA_DIR / "document_chunks.json"
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
