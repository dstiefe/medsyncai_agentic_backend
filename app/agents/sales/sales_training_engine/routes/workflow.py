"""
Procedure Workflow API router.

Provides endpoints for browsing procedural stacks, swap analysis, and comparisons.
Data source: compatibility_matrix.json with 413 procedural stacks.
"""

import json
import logging
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from ..config import get_settings
from ..services.data_loader import get_data_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/workflow", tags=["workflow"])


def _load_compatibility_matrix() -> dict:
    """Load the compatibility matrix data."""
    settings = get_settings()
    matrix_file = settings.data_dir / "compatibility_matrix.json"
    if not matrix_file.exists():
        return {"procedural_stacks": [], "fits_inside": []}
    try:
        with open(matrix_file, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {"procedural_stacks": [], "fits_inside": []}


@router.get("/stacks")
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


@router.get("/stacks/{index}")
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


@router.post("/swap-analysis")
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
    # Check fits_inside relationships for the new device
    compatible_with = []
    incompatible_with = []

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


@router.post("/compare")
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


@router.get("/device/{device_id}/fits")
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
