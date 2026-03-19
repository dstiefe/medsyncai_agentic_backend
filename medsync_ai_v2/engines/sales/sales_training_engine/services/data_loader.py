"""
Data loader service for MedSync AI Sales Simulation Engine.

Manages loading and indexing of all data files (devices, compatibility matrix, competitive intel, documents).
"""

import json
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

from ..config import get_settings
from ..models.device import Device


class DataManager:
    """Manages loading and indexing of all MedSync data."""

    def __init__(self, data_dir: Optional[Path] = None):
        """
        Initialize DataManager and load all data files.

        Args:
            data_dir: Path to data directory. If None, uses config default.
        """
        if data_dir is None:
            data_dir = get_settings().data_dir

        self.data_dir = Path(data_dir)

        # Initialize storage
        self.devices: Dict[int, Device] = {}
        self.compatibility_matrix: Dict = {}
        self.competitive_intel: Dict = {}
        self.document_chunks: List[Dict] = []
        self.chunk_metadata: List[Dict] = []

        # Initialize indexes
        self.manufacturer_to_device_ids: Dict[str, List[int]] = {}
        self.category_to_device_ids: Dict[str, List[int]] = {}
        self.device_name_search_index: Dict[str, int] = {}
        self.chunk_id_to_text: Dict[str, str] = {}

        # Load all data
        self._load_devices()
        self._load_compatibility_matrix()
        self._load_competitive_intel()
        self._load_document_chunks()
        self._load_chunk_metadata()
        self._build_indexes()

    def _load_devices(self) -> None:
        """Load and parse devices.json."""
        devices_path = self.data_dir / "devices.json"
        if not devices_path.exists():
            raise FileNotFoundError(f"Devices file not found: {devices_path}")

        with open(devices_path, "r") as f:
            data = json.load(f)

        # Parse devices from JSON (keys are strings like "177", values have id as int)
        for device_key, device_dict in data["devices"].items():
            try:
                device = Device(**device_dict)
                self.devices[device.id] = device
            except Exception as e:
                raise ValueError(f"Failed to parse device {device_key}: {e}")

    def _load_compatibility_matrix(self) -> None:
        """Load compatibility_matrix.json."""
        matrix_path = self.data_dir / "compatibility_matrix.json"
        if not matrix_path.exists():
            raise FileNotFoundError(f"Compatibility matrix not found: {matrix_path}")

        with open(matrix_path, "r") as f:
            self.compatibility_matrix = json.load(f)

    def _load_competitive_intel(self) -> None:
        """Load competitive_intel.json."""
        intel_path = self.data_dir / "competitive_intel.json"
        if not intel_path.exists():
            raise FileNotFoundError(f"Competitive intel not found: {intel_path}")

        with open(intel_path, "r") as f:
            self.competitive_intel = json.load(f)

    def _load_document_chunks(self) -> None:
        """Load document_chunks.json."""
        chunks_path = self.data_dir / "document_chunks.json"
        if not chunks_path.exists():
            raise FileNotFoundError(f"Document chunks not found: {chunks_path}")

        with open(chunks_path, "r") as f:
            data = json.load(f)

        self.document_chunks = data.get("chunks", [])

        # Build chunk_id to text index
        for chunk in self.document_chunks:
            self.chunk_id_to_text[chunk["chunk_id"]] = chunk.get("text", "")

    def _load_chunk_metadata(self) -> None:
        """Load chunk_metadata.json from vector_index."""
        metadata_path = self.data_dir / "vector_index" / "chunk_metadata.json"
        if not metadata_path.exists():
            raise FileNotFoundError(f"Chunk metadata not found: {metadata_path}")

        with open(metadata_path, "r") as f:
            self.chunk_metadata = json.load(f)

    def _build_indexes(self) -> None:
        """Build search indexes from loaded data."""
        # Build manufacturer and category indexes
        for device_id, device in self.devices.items():
            # Manufacturer index
            if device.manufacturer not in self.manufacturer_to_device_ids:
                self.manufacturer_to_device_ids[device.manufacturer] = []
            self.manufacturer_to_device_ids[device.manufacturer].append(device_id)

            # Category index
            category_key = device.category.key
            if category_key not in self.category_to_device_ids:
                self.category_to_device_ids[category_key] = []
            self.category_to_device_ids[category_key].append(device_id)

            # Device name search index (lowercase for case-insensitive search)
            self.device_name_search_index[device.device_name.lower()] = device_id
            self.device_name_search_index[device.product_name.lower()] = device_id

            # Add aliases to search index
            for alias in device.aliases:
                self.device_name_search_index[alias.lower()] = device_id

    def get_device(self, device_id: int) -> Optional[Device]:
        """
        Get a device by ID.

        Args:
            device_id: The device ID

        Returns:
            The Device object, or None if not found
        """
        return self.devices.get(device_id)

    def get_chunk_text(self, chunk_id: str) -> Optional[str]:
        """
        Get the full text of a document chunk by ID.

        Args:
            chunk_id: The chunk ID

        Returns:
            The chunk text, or None if not found
        """
        return self.chunk_id_to_text.get(chunk_id)

    def get_chunk_metadata(self, chunk_id: str) -> Optional[Dict]:
        """
        Get metadata for a document chunk.

        Args:
            chunk_id: The chunk ID

        Returns:
            The chunk metadata dict, or None if not found
        """
        for metadata in self.chunk_metadata:
            if metadata.get("chunk_id") == chunk_id:
                return metadata
        return None

    def list_manufacturers(self) -> List[str]:
        """Get list of all manufacturers."""
        return sorted(self.manufacturer_to_device_ids.keys())

    def list_categories(self) -> List[str]:
        """Get list of all device category keys."""
        return sorted(self.category_to_device_ids.keys())

    def get_all_devices(self) -> List[Device]:
        """Get all devices."""
        return list(self.devices.values())

    def get_total_device_count(self) -> int:
        """Get total number of devices."""
        return len(self.devices)

    def get_total_chunk_count(self) -> int:
        """Get total number of document chunks."""
        return len(self.document_chunks)


@lru_cache(maxsize=1)
def get_data_manager() -> DataManager:
    """
    Get the singleton DataManager instance.

    Returns:
        DataManager: The data manager instance
    """
    return DataManager()
