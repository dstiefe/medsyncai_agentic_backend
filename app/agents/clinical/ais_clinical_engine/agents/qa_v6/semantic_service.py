"""
qa_v6 semantic service.

Reads the unified v5 atoms file — ONE source of truth for all content.
Every atom has text + embedding + metadata (anchor_terms,
intent_affinity, category, parent_section, etc.).

Exposes:
  embed_query(text) -> np.ndarray
  score_all_atoms(query_embedding) -> List[Tuple[atom, cosine_score]]
  get_atom(atom_id) -> atom dict
  get_recommendation_store() -> Dict[rec_id, atom]
  is_available() -> bool

Pure Python + numpy. No LLM. Deterministic.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

_DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data",
)
_ATOMS_PATH = os.path.join(_DATA_DIR, "guideline_knowledge.atomized.v5.json")

_MODEL_NAME = "BAAI/bge-base-en-v1.5"
_EMBEDDING_DIM = 768  # bge-base is 768-dim; all-MiniLM-L6-v2 was 384-dim

# Module-level caches (lazy-loaded once per process)
_model = None
_all_atoms: Optional[List[Dict[str, Any]]] = None
_all_embeddings: Optional[np.ndarray] = None
_atom_id_to_idx: Optional[Dict[str, int]] = None
_atom_indexes_by_type: Optional[Dict[str, List[int]]] = None
_rec_store_cache: Optional[Dict[str, Dict[str, Any]]] = None


def _get_model():
    """Lazy-load the sentence-transformer model."""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        logger.info("semantic_service: loading model %s", _MODEL_NAME)
        _model = SentenceTransformer(_MODEL_NAME)
    return _model


def _load_atoms() -> bool:
    """Load unified atoms file and build indexes. Return True on success."""
    global _all_atoms, _all_embeddings, _atom_id_to_idx, _atom_indexes_by_type
    if _all_atoms is not None:
        return True

    if not os.path.exists(_ATOMS_PATH):
        logger.warning(
            "semantic_service: atoms file missing at %s", _ATOMS_PATH,
        )
        return False

    with open(_ATOMS_PATH, "r") as f:
        data = json.load(f)

    atoms = data.get("atoms", [])
    if not atoms:
        logger.warning("semantic_service: no atoms in file")
        return False

    # Extract embeddings, filter out malformed / wrong-dim.
    valid_atoms: List[Dict[str, Any]] = []
    emb_list: List[List[float]] = []
    for atom in atoms:
        emb = atom.get("embedding", [])
        if not emb or len(emb) != _EMBEDDING_DIM:
            logger.warning(
                "semantic_service: dropping atom %s (embedding "
                "dim %d, expected %d)",
                atom.get("atom_id", "?"),
                len(emb) if emb else 0, _EMBEDDING_DIM,
            )
            continue
        valid_atoms.append(atom)
        emb_list.append(emb)

    embeddings = np.asarray(emb_list, dtype=np.float32)
    # Ensure L2-normalized (belt-and-suspenders)
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    embeddings = embeddings / norms

    # Build indexes
    atom_id_to_idx = {a["atom_id"]: i for i, a in enumerate(valid_atoms)}
    indexes_by_type: Dict[str, List[int]] = {}
    for i, a in enumerate(valid_atoms):
        t = a.get("atom_type", "")
        indexes_by_type.setdefault(t, []).append(i)

    _all_atoms = valid_atoms
    _all_embeddings = embeddings
    _atom_id_to_idx = atom_id_to_idx
    _atom_indexes_by_type = indexes_by_type

    logger.info(
        "semantic_service: loaded %d atoms across types: %s",
        len(valid_atoms),
        {t: len(ids) for t, ids in indexes_by_type.items()},
    )
    return True


def is_available() -> bool:
    return _load_atoms()


def embed_query(text: str) -> np.ndarray:
    """Embed a query string, L2-normalized, float32."""
    model = _get_model()
    return model.encode(text, normalize_embeddings=True).astype(np.float32)


def get_atom(atom_id: str) -> Optional[Dict[str, Any]]:
    if not _load_atoms():
        return None
    idx = _atom_id_to_idx.get(atom_id)
    if idx is None:
        return None
    return _all_atoms[idx]


def score_all_atoms(
    query_embedding: np.ndarray,
) -> List[Tuple[Dict[str, Any], float]]:
    """Cosine similarity of the query against every atom.

    Returns list of (atom, cosine_score) in atom file order.
    Negative similarities are clipped to 0.
    """
    if not _load_atoms():
        return []
    scores = _all_embeddings @ query_embedding
    scores = np.maximum(scores, 0.0)
    return [(_all_atoms[i], float(scores[i])) for i in range(len(_all_atoms))]


def get_recommendation_store() -> Dict[str, Dict[str, Any]]:
    """Return {rec_id: atom} for every recommendation atom, cached.

    Key format strips the atom_id's "atom-" prefix so keys align with
    the CMI criteria file's composite IDs (e.g. "rec-2.1-001"). Built
    once per process.
    """
    global _rec_store_cache
    if _rec_store_cache is not None:
        return _rec_store_cache
    if not _load_atoms():
        _rec_store_cache = {}
        return _rec_store_cache

    store: Dict[str, Dict[str, Any]] = {}
    for atom in _all_atoms:
        if atom.get("atom_type") != "recommendation":
            continue
        atom_id = atom.get("atom_id", "")
        if atom_id.startswith("atom-"):
            rec_id = atom_id[len("atom-"):]
        else:
            rec_id = atom_id
        if rec_id:
            store[rec_id] = atom

    _rec_store_cache = store
    logger.info(
        "semantic_service: cached recommendation store (%d recs)",
        len(store),
    )
    return store


