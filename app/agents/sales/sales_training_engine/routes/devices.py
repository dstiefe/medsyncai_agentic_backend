"""
Devices API router for MedSync AI Sales Simulation Engine.

Provides endpoints for browsing, searching, and querying medical devices,
manufacturers, categories, and compatibility information.
"""

import logging
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from ..models.device import Device
from ..services.data_loader import DataManager, get_data_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/devices", tags=["devices"])


def get_data_manager_dep() -> DataManager:
    """
    Dependency injection for DataManager.

    Returns:
        DataManager: The loaded data manager instance.
    """
    return get_data_manager()


@router.get("/")
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


@router.get("/manufacturers")
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


@router.get("/categories")
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


@router.get("/search")
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


@router.get("/{device_id}")
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


@router.get("/{device_id}/compatible")
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
        # Look up in the compatibility matrix based on device_id
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
