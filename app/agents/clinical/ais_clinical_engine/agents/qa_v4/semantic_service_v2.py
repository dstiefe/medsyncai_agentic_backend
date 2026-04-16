"""
Semantic scoring service v2 — reads the unified atoms file.

Replaces the v1 service which read from 3 separate files
(recommendation_embeddings.npz, concept_section_embeddings.npz, and
inline atom embeddings in guideline_knowledge.atomized.json).

Now one source of truth: guideline_knowledge.atomized.v2.json
contains every atom (rec, RSS, synopsis, KG, table_row, figure,
concept_section) with text + metadata + embedding.

API (same signatures as v1 for drop-in replacement):
  embed_query(text) -> np.ndarray
  score_concept_sections(q_emb) -> {concept_id: score}
  score_recs(q_emb, rec_ids=None) -> {rec_id: score}
  is_available() -> bool

New APIs for unified retrieval:
  score_atoms(q_emb, atom_type=None, filters=None) -> [(atom, score), ...]
  get_atom(atom_id) -> atom dict

All embeddings use all-MiniLM-L6-v2 (384 dims, L2-normalized).
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
_ATOMS_PATH = os.path.join(_DATA_DIR, "guideline_knowledge.atomized.v2.json")

_MODEL_NAME = "all-MiniLM-L6-v2"

# Module-level caches (lazy-loaded once per process)
_model = None
_all_atoms: Optional[List[Dict[str, Any]]] = None
_all_embeddings: Optional[np.ndarray] = None
_atom_id_to_idx: Optional[Dict[str, int]] = None
_atom_ids_by_type: Optional[Dict[str, List[str]]] = None


def _get_model():
    """Lazy-load the sentence-transformer model."""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        logger.info("semantic_service: loading model %s", _MODEL_NAME)
        _model = SentenceTransformer(_MODEL_NAME)
    return _model


def _load_atoms() -> bool:
    """Load the unified atoms file into caches. Return True on success."""
    global _all_atoms, _all_embeddings, _atom_id_to_idx, _atom_ids_by_type
    if _all_atoms is not None:
        return True

    if not os.path.exists(_ATOMS_PATH):
        logger.warning(
            "semantic_service: unified atoms file not found at %s",
            _ATOMS_PATH,
        )
        return False

    with open(_ATOMS_PATH, "r") as f:
        data = json.load(f)

    atoms = data.get("atoms", [])
    if not atoms:
        logger.warning("semantic_service: atoms file is empty")
        return False

    # Build embedding matrix
    emb_list = []
    for atom in atoms:
        emb = atom.get("embedding", [])
        if not emb or len(emb) != 384:
            logger.warning(
                "semantic_service: atom %s has bad embedding (len=%d)",
                atom.get("atom_id", "?"),
                len(emb) if emb else 0,
            )
            emb = [0.0] * 384
        emb_list.append(emb)

    embeddings = np.asarray(emb_list, dtype=np.float32)
    # Ensure L2-normalized
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    embeddings = embeddings / norms

    # Build indexes
    atom_id_to_idx = {a["atom_id"]: i for i, a in enumerate(atoms)}
    by_type: Dict[str, List[str]] = {}
    for a in atoms:
        t = a.get("atom_type", "")
        by_type.setdefault(t, []).append(a["atom_id"])

    _all_atoms = atoms
    _all_embeddings = embeddings
    _atom_id_to_idx = atom_id_to_idx
    _atom_ids_by_type = by_type

    logger.info(
        "semantic_service: loaded %d atoms across types: %s",
        len(atoms),
        {t: len(ids) for t, ids in by_type.items()},
    )
    return True


def embed_query(text: str) -> np.ndarray:
    """Embed a query string with the same model, L2-normalized."""
    model = _get_model()
    return model.encode(text, normalize_embeddings=True).astype(np.float32)


def is_available() -> bool:
    """True if the unified atoms file is loaded and has atoms."""
    return _load_atoms()


def get_atom(atom_id: str) -> Optional[Dict[str, Any]]:
    """Look up an atom by atom_id. Returns None if not found."""
    if not _load_atoms():
        return None
    idx = _atom_id_to_idx.get(atom_id)
    if idx is None:
        return None
    return _all_atoms[idx]


def score_atoms(
    query_embedding: np.ndarray,
    atom_type: Optional[str] = None,
    parent_section: Optional[str] = None,
    category: Optional[str] = None,
) -> List[Tuple[Dict[str, Any], float]]:
    """Score atoms against a query embedding.

    Args:
        query_embedding: query vector (384-dim, L2-normalized)
        atom_type: if set, only score atoms of this type
        parent_section: if set, only score atoms from this section
        category: if set, only score atoms with this category

    Returns list of (atom_dict, cosine_score) sorted by score descending.
    """
    if not _load_atoms():
        return []

    # Which atom indexes to score?
    if atom_type:
        indexes = [
            _atom_id_to_idx[aid]
            for aid in _atom_ids_by_type.get(atom_type, [])
        ]
    else:
        indexes = list(range(len(_all_atoms)))

    # Additional filters
    if parent_section or category:
        indexes = [
            i for i in indexes
            if (not parent_section or _all_atoms[i].get("parent_section") == parent_section)
            and (not category or _all_atoms[i].get("category") == category)
        ]

    if not indexes:
        return []

    # Cosine sim via dot product
    emb_subset = _all_embeddings[indexes]
    scores = emb_subset @ query_embedding
    scores = np.maximum(scores, 0.0)

    results = [
        (_all_atoms[indexes[i]], float(scores[i]))
        for i in range(len(indexes))
    ]
    results.sort(key=lambda x: -x[1])
    return results


# ── Back-compat APIs matching v1 signatures ────────────────────


def score_concept_sections(
    query_embedding: np.ndarray,
) -> Dict[str, float]:
    """Return {concept_id: cosine_similarity} for all concept sections.

    Compatibility shim: uses atoms with atom_type='concept_section'
    and their 'concept_id' field.
    """
    results = score_atoms(
        query_embedding, atom_type="concept_section",
    )
    out: Dict[str, float] = {}
    for atom, score in results:
        cid = atom.get("concept_id", atom.get("atom_id", ""))
        if cid:
            out[cid] = score
    return out


def score_recs(
    query_embedding: np.ndarray,
    rec_ids: Optional[List[str]] = None,
) -> Dict[str, float]:
    """Return {rec_id: cosine_similarity} for rec atoms.

    Compatibility shim: uses atoms with atom_type='recommendation'.
    The 'rec_id' is reconstructed by stripping the 'atom-' prefix.
    """
    results = score_atoms(query_embedding, atom_type="recommendation")
    out: Dict[str, float] = {}
    for atom, score in results:
        aid = atom.get("atom_id", "")
        # atom-rec-4.8-017 → rec-4.8-017
        rec_id = aid[len("atom-"):] if aid.startswith("atom-") else aid
        out[rec_id] = score

    if rec_ids is not None:
        want = set(rec_ids)
        out = {rid: s for rid, s in out.items() if rid in want}
    return out
