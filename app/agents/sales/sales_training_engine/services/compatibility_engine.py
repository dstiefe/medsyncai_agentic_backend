"""
Compatibility engine for MedSync AI Sales Simulation Engine.

Provides methods for checking device compatibility and building procedural stacks.
"""

from typing import Dict, List, Optional

from ..models.device import Device
from .data_loader import DataManager
from .device_service import DeviceService


class CompatibilityEngine:
    """Engine for checking device compatibility and managing procedural stacks."""

    def __init__(self, data_manager: DataManager):
        """
        Initialize CompatibilityEngine.

        Args:
            data_manager: The DataManager instance
        """
        self.data_manager = data_manager
        self.device_service = DeviceService(data_manager)

    def get_fits_inside(self, device_id: int) -> List[Dict]:
        """
        Get devices that this device can fit inside (outer devices).

        Args:
            device_id: The device ID

        Returns:
            List of compatibility entries with outer devices
        """
        device = self.device_service.get_device(device_id)
        if not device:
            return []

        # Look up in compatibility matrix fits_inside
        fits_inside_data = self.data_manager.compatibility_matrix.get(
            "fits_inside", {}
        )

        device_key = str(device_id)
        return fits_inside_data.get(device_key, [])

    def get_accepts(self, device_id: int) -> List[Dict]:
        """
        Get devices that this device can accept inside it (inner devices).

        Args:
            device_id: The device ID

        Returns:
            List of compatibility entries with inner devices
        """
        device = self.device_service.get_device(device_id)
        if not device:
            return []

        # Look up in compatibility matrix accepts
        accepts_data = self.data_manager.compatibility_matrix.get("accepts", {})

        device_key = str(device_id)
        return accepts_data.get(device_key, [])

    def check_compatibility(
        self, inner_id: int, outer_id: int
    ) -> Dict:
        """
        Check if an inner device can fit inside an outer device.

        Args:
            inner_id: The inner device ID
            outer_id: The outer device ID

        Returns:
            Dict with: compatible (bool), clearance_mm (float), fit_type (str), explanation (str)
        """
        inner_device = self.device_service.get_device(inner_id)
        outer_device = self.device_service.get_device(outer_id)

        if not inner_device or not outer_device:
            return {
                "compatible": False,
                "clearance_mm": None,
                "fit_type": None,
                "explanation": "Device not found",
            }

        # Check fits_inside entries for inner_id
        fits_inside = self.get_fits_inside(inner_id)

        for entry in fits_inside:
            if entry.get("outer_device_id") == outer_id:
                return {
                    "compatible": True,
                    "clearance_mm": entry.get("clearance_mm"),
                    "fit_type": entry.get("fit_type"),
                    "explanation": f"{inner_device.device_name} can fit inside {outer_device.device_name} ({entry.get('fit_type')} fit)",
                }

        return {
            "compatible": False,
            "clearance_mm": None,
            "fit_type": None,
            "explanation": f"{inner_device.device_name} cannot fit inside {outer_device.device_name}",
        }

    def get_procedural_stacks(
        self, manufacturer: Optional[str] = None
    ) -> List[Dict]:
        """
        Get common procedural device stacks.

        Args:
            manufacturer: Filter by manufacturer (optional)

        Returns:
            List of procedural stack configurations
        """
        stacks_data = self.data_manager.compatibility_matrix.get(
            "procedural_stacks", []
        )

        if not manufacturer:
            return stacks_data

        # Filter stacks that contain devices from the specified manufacturer
        filtered_stacks = []
        for stack in stacks_data:
            device_ids = stack.get("device_ids", [])
            has_mfg = False

            for did in device_ids:
                device = self.device_service.get_device(did)
                if device and device.manufacturer == manufacturer:
                    has_mfg = True
                    break

            if has_mfg:
                filtered_stacks.append(stack)

        return filtered_stacks

    def get_cross_manufacturer_compatibility(self, device_id: int) -> List[Dict]:
        """
        Get competitor devices that are physically compatible with the given device.

        Args:
            device_id: The device ID

        Returns:
            List of compatible devices from other manufacturers
        """
        device = self.device_service.get_device(device_id)
        if not device:
            return []

        # Get devices that can fit inside this one
        compatible_inner = []
        for entry in self.get_accepts(device_id):
            inner_id = entry.get("inner_device_id")
            if inner_id:
                inner_device = self.device_service.get_device(inner_id)
                if (
                    inner_device
                    and inner_device.manufacturer != device.manufacturer
                ):
                    compatible_inner.append(
                        {
                            "device_id": inner_id,
                            "device_name": inner_device.device_name,
                            "manufacturer": inner_device.manufacturer,
                            "fit_type": entry.get("fit_type"),
                            "clearance_mm": entry.get("clearance_mm"),
                        }
                    )

        # Get devices this one can fit inside
        compatible_outer = []
        for entry in self.get_fits_inside(device_id):
            outer_id = entry.get("outer_device_id")
            if outer_id:
                outer_device = self.device_service.get_device(outer_id)
                if (
                    outer_device
                    and outer_device.manufacturer != device.manufacturer
                ):
                    compatible_outer.append(
                        {
                            "device_id": outer_id,
                            "device_name": outer_device.device_name,
                            "manufacturer": outer_device.manufacturer,
                            "fit_type": entry.get("fit_type"),
                            "clearance_mm": entry.get("clearance_mm"),
                        }
                    )

        return compatible_inner + compatible_outer

    def build_custom_stack(self, device_ids: List[int]) -> Dict:
        """
        Validate a proposed procedural stack by checking all compatibility pairs.

        Args:
            device_ids: List of device IDs in proposed order (inner to outer)

        Returns:
            Dict with: valid (bool), errors (List[str]), compatibility_checks (List[Dict])
        """
        if not device_ids:
            return {"valid": False, "errors": ["Empty device stack"], "compatibility_checks": []}

        # Get all devices
        devices = []
        for did in device_ids:
            device = self.device_service.get_device(did)
            if not device:
                return {
                    "valid": False,
                    "errors": [f"Device {did} not found"],
                    "compatibility_checks": [],
                }
            devices.append(device)

        # Check compatibility between consecutive devices
        errors = []
        compatibility_checks = []

        for i in range(len(devices) - 1):
            inner_device = devices[i]
            outer_device = devices[i + 1]

            compat = self.check_compatibility(inner_device.id, outer_device.id)
            compatibility_checks.append(
                {
                    "position": i,
                    "inner_id": inner_device.id,
                    "inner_name": inner_device.device_name,
                    "outer_id": outer_device.id,
                    "outer_name": outer_device.device_name,
                    "compatible": compat["compatible"],
                    "clearance_mm": compat.get("clearance_mm"),
                    "fit_type": compat.get("fit_type"),
                }
            )

            if not compat["compatible"]:
                errors.append(compat["explanation"])

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "compatibility_checks": compatibility_checks,
        }
