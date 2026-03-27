"""
Device service for MedSync AI Sales Simulation Engine.

Provides methods for searching, filtering, and retrieving device information.
"""

from typing import Dict, List, Optional

from ..models.device import Device
from .data_loader import DataManager


class DeviceService:
    """Service for device operations and queries."""

    def __init__(self, data_manager: DataManager):
        """
        Initialize DeviceService.

        Args:
            data_manager: The DataManager instance
        """
        self.data_manager = data_manager

    def get_device(self, device_id: int) -> Optional[Device]:
        """
        Get a device by ID.

        Args:
            device_id: The device ID

        Returns:
            The Device object, or None if not found
        """
        return self.data_manager.get_device(device_id)

    def search_devices(
        self,
        query: str,
        manufacturer: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 20,
    ) -> List[Device]:
        """
        Search for devices by name, product name, or aliases.

        Args:
            query: Search query string (case-insensitive)
            manufacturer: Filter by manufacturer (optional)
            category: Filter by category key (optional)
            limit: Maximum number of results

        Returns:
            List of matching devices
        """
        query_lower = query.lower()
        results = []

        # Get candidate device IDs based on filters
        candidate_ids = set(self.data_manager.devices.keys())

        if manufacturer:
            mfg_devices = self.data_manager.manufacturer_to_device_ids.get(
                manufacturer, []
            )
            candidate_ids &= set(mfg_devices)

        if category:
            cat_devices = self.data_manager.category_to_device_ids.get(category, [])
            candidate_ids &= set(cat_devices)

        # Search within candidates
        for device_id in candidate_ids:
            device = self.data_manager.get_device(device_id)
            if not device:
                continue

            # Check if query matches device_name, product_name, or aliases
            if query_lower in device.device_name.lower():
                results.append(device)
            elif query_lower in device.product_name.lower():
                results.append(device)
            elif any(query_lower in alias.lower() for alias in device.aliases):
                results.append(device)

        # Return limited results
        return results[:limit]

    def get_by_manufacturer(self, manufacturer: str) -> List[Device]:
        """
        Get all devices from a specific manufacturer.

        Args:
            manufacturer: Manufacturer name

        Returns:
            List of devices from that manufacturer
        """
        device_ids = self.data_manager.manufacturer_to_device_ids.get(
            manufacturer, []
        )
        return [
            device for device in [self.data_manager.get_device(did) for did in device_ids]
            if device is not None
        ]

    def get_by_category(self, category_key: str) -> List[Device]:
        """
        Get all devices in a specific category.

        Args:
            category_key: Category key (e.g., 'sheath', 'guide_catheter')

        Returns:
            List of devices in that category
        """
        device_ids = self.data_manager.category_to_device_ids.get(category_key, [])
        return [
            device for device in [self.data_manager.get_device(did) for did in device_ids]
            if device is not None
        ]

    def get_manufacturers(self) -> List[Dict]:
        """
        Get all manufacturers with summary information.

        Returns:
            List of manufacturer dicts with: name, device_count, categories, products
        """
        manufacturers = []

        for mfg_name in self.data_manager.list_manufacturers():
            mfg_devices = self.get_by_manufacturer(mfg_name)

            # Count categories and collect products
            categories = {}
            products = set()
            for device in mfg_devices:
                cat_key = device.category.key
                categories[cat_key] = categories.get(cat_key, 0) + 1
                products.add(device.product_name)

            manufacturers.append(
                {
                    "name": mfg_name,
                    "device_count": len(mfg_devices),
                    "categories": categories,
                    "products": sorted(list(products)),
                }
            )

        return manufacturers

    def get_categories(self) -> List[Dict]:
        """
        Get all device categories with summary information.

        Returns:
            List of category dicts
        """
        categories = []

        for cat_key in self.data_manager.list_categories():
            cat_devices = self.get_by_category(cat_key)
            if not cat_devices:
                continue

            # Use first device's category info as template
            cat_info = cat_devices[0].category

            categories.append(
                {
                    "key": cat_key,
                    "display_name": cat_info.display_name,
                    "group": cat_info.group,
                    "role": cat_info.role,
                    "device_count": len(cat_devices),
                    "manufacturers": list(
                        set(d.manufacturer for d in cat_devices)
                    ),
                }
            )

        return categories

    def get_portfolio(self, company: str) -> List[Device]:
        """
        Get all devices in a company's portfolio.

        This is an alias for get_by_manufacturer.

        Args:
            company: Company/manufacturer name

        Returns:
            List of devices in the portfolio
        """
        return self.get_by_manufacturer(company)

    def get_device_by_name(self, device_name: str) -> Optional[Device]:
        """
        Get a device by searching device name (case-insensitive).

        Args:
            device_name: The device name

        Returns:
            The Device object, or None if not found
        """
        results = self.search_devices(device_name, limit=1)
        return results[0] if results else None
