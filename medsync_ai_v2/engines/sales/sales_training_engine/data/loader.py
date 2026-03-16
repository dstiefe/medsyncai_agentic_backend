"""
LRU-cached data loading for the Sales Training Engine.

Loads JSON data files and FAISS index lazily on first access.
All files live in this directory (data/).
"""

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent


def _load_json(filename: str) -> dict | list:
    """Load a JSON file from the data directory."""
    path = DATA_DIR / filename
    if not path.exists():
        logger.warning("Data file not found: %s", path)
        return {} if filename.endswith(".json") else []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def load_devices() -> list:
    """Load devices.json (702 KB, ~224 devices)."""
    data = _load_json("devices.json")
    if isinstance(data, dict):
        return data.get("devices", [])
    return data


@lru_cache(maxsize=1)
def load_compatibility_matrix() -> dict:
    """Load compatibility_matrix.json (4.5 MB, 413 procedural stacks)."""
    return _load_json("compatibility_matrix.json")


@lru_cache(maxsize=1)
def load_competitive_intel() -> dict:
    """Load competitive_intel.json (1.1 MB)."""
    return _load_json("competitive_intel.json")


@lru_cache(maxsize=1)
def load_document_chunks() -> list:
    """Load document_chunks.json (5.3 MB, 2,243 chunks)."""
    data = _load_json("document_chunks.json")
    if isinstance(data, dict):
        return data.get("chunks", data.get("documents", []))
    return data


@lru_cache(maxsize=1)
def load_physician_dossiers() -> dict:
    """Load physician_dossiers.json."""
    return _load_json("physician_dossiers.json")


@lru_cache(maxsize=1)
def load_chunk_metadata() -> dict:
    """Load vector_index/chunk_metadata.json."""
    path = DATA_DIR / "vector_index" / "chunk_metadata.json"
    if not path.exists():
        logger.warning("Chunk metadata not found: %s", path)
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_faiss_index_path() -> Optional[Path]:
    """Return path to FAISS index binary, or None if missing."""
    path = DATA_DIR / "vector_index" / "faiss_index.bin"
    return path if path.exists() else None
