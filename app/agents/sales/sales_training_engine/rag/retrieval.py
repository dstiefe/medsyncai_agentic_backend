"""
Vector-based retrieval module for MedSync AI Sales Simulation Engine.

Provides RAG (Retrieval-Augmented Generation) capabilities using FAISS for semantic search.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

from ..config import get_settings
from ..models.simulation_state import RetrievalResult
from ..services.data_loader import DataManager


class VectorRetriever:
    """Retrieves relevant document chunks using semantic similarity search."""

    def __init__(
        self,
        data_manager: DataManager,
        model_name: str = "all-MiniLM-L6-v2",
        data_dir: Optional[Path] = None,
    ):
        """
        Initialize VectorRetriever with FAISS index and embedding model.

        Args:
            data_manager: The DataManager instance containing document chunks
            model_name: Name of the embedding model (default: all-MiniLM-L6-v2)
            data_dir: Path to data directory. If None, uses config default.
        """
        if data_dir is None:
            data_dir = get_settings().data_dir

        self.data_dir = Path(data_dir)
        self.data_manager = data_manager

        # Load embedding model
        self.model = SentenceTransformer(model_name)
        self.embedding_dim = 384

        # Load FAISS index
        self.index_path = self.data_dir / "vector_index" / "faiss_index.bin"
        if not self.index_path.exists():
            raise FileNotFoundError(f"FAISS index not found: {self.index_path}")

        # Read the binary FAISS index
        self.faiss_index = faiss.read_index(str(self.index_path))

        # Load chunk metadata
        self.chunk_metadata_path = (
            self.data_dir / "vector_index" / "chunk_metadata.json"
        )
        if not self.chunk_metadata_path.exists():
            raise FileNotFoundError(
                f"Chunk metadata not found: {self.chunk_metadata_path}"
            )

        with open(self.chunk_metadata_path, "r") as f:
            self.chunk_metadata_list: List[Dict] = json.load(f)

        # Build metadata lookup by chunk_id
        self.metadata_by_chunk_id: Dict[str, Dict] = {
            chunk["chunk_id"]: chunk for chunk in self.chunk_metadata_list
        }

    def retrieve(
        self,
        query: str,
        k: int = 8,
        filters: Optional[Dict] = None,
    ) -> List[RetrievalResult]:
        """
        Retrieve relevant document chunks for a query.

        Performs semantic search using FAISS index and returns top-k results
        after applying optional filters.

        Args:
            query: The search query text
            k: Number of results to return (default: 8)
            filters: Optional filtering criteria. Supported keys:
                - manufacturer (str): Filter by device manufacturer
                - source_type (str): Filter by source type (ifu, webpage_text, etc.)
                - section_hint (str): Filter by document section
                - device_names (List[str]): Filter by device names

        Returns:
            List of RetrievalResult objects, sorted by relevance score
        """
        # Encode query to embedding
        query_embedding = self.model.encode(query, convert_to_numpy=True)

        # Normalize for cosine similarity
        query_embedding = query_embedding / (
            np.linalg.norm(query_embedding) + 1e-10
        )
        query_embedding = query_embedding.reshape(1, -1).astype("float32")

        # Over-fetch to account for filtering
        over_fetch_k = max(k * 3, 50)

        # Search FAISS index
        distances, indices = self.faiss_index.search(query_embedding, over_fetch_k)

        # Convert to results with filtering
        results = []
        for i, idx in enumerate(indices[0]):
            if idx < 0 or idx >= len(self.chunk_metadata_list):
                continue

            # Get metadata for this chunk
            metadata = self.chunk_metadata_list[idx]
            chunk_id = metadata.get("chunk_id", "")

            # Apply filters
            if filters:
                if not self._matches_filters(metadata, filters):
                    continue

            # Get full text from data_manager
            text = self.data_manager.get_chunk_text(chunk_id) or ""

            # Create result
            score = float(distances[0][i])

            result = RetrievalResult(
                chunk_id=chunk_id,
                score=score,
                source_type=metadata.get("source_type", "unknown"),
                manufacturer=metadata.get("manufacturer", ""),
                device_names=metadata.get("device_names", []),
                file_name=metadata.get("file_name", ""),
                section_hint=metadata.get("section_hint", ""),
                text=text,
            )
            results.append(result)

            if len(results) >= k:
                break

        return results

    def retrieve_for_devices(
        self, device_names: List[str], k: int = 5
    ) -> List[RetrievalResult]:
        """
        Retrieve chunks relevant to specific devices.

        Args:
            device_names: List of device names to match
            k: Number of results to return

        Returns:
            List of RetrievalResult objects
        """
        device_names_lower = [d.lower() for d in device_names]
        results = []

        for metadata in self.chunk_metadata_list:
            chunk_device_names = metadata.get("device_names", [])

            # Check if any device name matches
            if any(
                any(d in device.lower() for d in device_names_lower)
                for device in chunk_device_names
            ):
                chunk_id = metadata.get("chunk_id", "")
                text = self.data_manager.get_chunk_text(chunk_id) or ""

                result = RetrievalResult(
                    chunk_id=chunk_id,
                    score=1.0,  # No score for device-based retrieval
                    source_type=metadata.get("source_type", "unknown"),
                    manufacturer=metadata.get("manufacturer", ""),
                    device_names=metadata.get("device_names", []),
                    file_name=metadata.get("file_name", ""),
                    section_hint=metadata.get("section_hint", ""),
                    text=text,
                )
                results.append(result)

                if len(results) >= k:
                    break

        return results

    def retrieve_by_section(
        self, query: str, section: str, k: int = 5
    ) -> List[RetrievalResult]:
        """
        Retrieve chunks from a specific section matching a query.

        Args:
            query: The search query text
            section: The section hint to filter by (e.g., 'adverse_events', 'specifications')
            k: Number of results to return

        Returns:
            List of RetrievalResult objects
        """
        filters = {"section_hint": section}
        return self.retrieve(query, k=k, filters=filters)

    def _matches_filters(self, metadata: Dict, filters: Dict) -> bool:
        """
        Check if metadata matches all provided filters.

        Args:
            metadata: Chunk metadata dictionary
            filters: Filter criteria dictionary

        Returns:
            True if metadata matches all filters, False otherwise
        """
        if "manufacturer" in filters:
            if metadata.get("manufacturer") != filters["manufacturer"]:
                return False

        if "source_type" in filters:
            if metadata.get("source_type") != filters["source_type"]:
                return False

        if "section_hint" in filters:
            if metadata.get("section_hint") != filters["section_hint"]:
                return False

        if "device_names" in filters:
            filter_devices = [d.lower() for d in filters["device_names"]]
            metadata_devices = [d.lower() for d in metadata.get("device_names", [])]

            # Check if any device name matches
            if not any(
                any(fd in md for md in metadata_devices) for fd in filter_devices
            ):
                return False

        return True
