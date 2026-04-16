"""
Semantic scoring service for qa_v4 retrieval pipeline.

Provides embedding-based similarity scoring across all 3 retrieval
stages (dispatcher, rec search, row/atom search) using pre-computed
embeddings.

Pre-computed embeddings:
  - concept_section_embeddings.npz: 75 concept sections
  - recommendation_embeddings.npz: 202 recommendations
  - atom embeddings in guideline_knowledge.atomized.json

All embeddings use all-MiniLM-L6-v2 (384 dims, L2-normalized).
Cosine similarity = dot product.

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
_CONCEPT_EMB_PATH = os.path.join(_DATA_DIR, "concept_section_embeddings.npz")
_REC_EMB_PATH = os.path.join(_DATA_DIR, "recommendation_embeddings.npz")

_MODEL_NAME = "all-MiniLM-L6-v2"

# Module-level caches (lazy-loaded once per process)
_model = None
_concept_embeddings: Optional[np.ndarray] = None
_concept_metadata: Optional[List[Dict[str, Any]]] = None
_concept_id_to_idx: Optional[Dict[str, int]] = None

_rec_embeddings: Optional[np.ndarray] = None
_rec_metadata: Optional[List[Dict[str, Any]]] = None
_rec_id_to_idx: Optional[Dict[str, int]] = None


def _get_model():
    """Lazy-load the sentence-transformer model."""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        logger.info("semantic_service: loading model %s", _MODEL_NAME)
        _model = SentenceTransformer(_MODEL_NAME)
    return _model


def _load_concept_embeddings() -> Tuple[
    Optional[np.ndarray],
    Optional[List[Dict[str, Any]]],
    Optional[Dict[str, int]],
]:
    """Load concept section embeddings + metadata."""
    global _concept_embeddings, _concept_metadata, _concept_id_to_idx
    if _concept_embeddings is not None:
        return _concept_embeddings, _concept_metadata, _concept_id_to_idx

    if not os.path.exists(_CONCEPT_EMB_PATH):
        logger.warning(
            "semantic_service: concept embeddings not found at %s",
            _CONCEPT_EMB_PATH,
        )
        return None, None, None

    data = np.load(_CONCEPT_EMB_PATH, allow_pickle=True)
    _concept_embeddings = np.asarray(data["embeddings"], dtype=np.float32)
    _concept_metadata = json.loads(str(data["metadata"]))
    _concept_id_to_idx = {
        m["concept_id"]: i for i, m in enumerate(_concept_metadata)
    }
    logger.info(
        "semantic_service: loaded %d concept section embeddings",
        len(_concept_metadata),
    )
    return _concept_embeddings, _concept_metadata, _concept_id_to_idx


def _load_rec_embeddings() -> Tuple[
    Optional[np.ndarray],
    Optional[List[Dict[str, Any]]],
    Optional[Dict[str, int]],
]:
    """Load recommendation embeddings + metadata."""
    global _rec_embeddings, _rec_metadata, _rec_id_to_idx
    if _rec_embeddings is not None:
        return _rec_embeddings, _rec_metadata, _rec_id_to_idx

    if not os.path.exists(_REC_EMB_PATH):
        logger.warning(
            "semantic_service: rec embeddings not found at %s",
            _REC_EMB_PATH,
        )
        return None, None, None

    data = np.load(_REC_EMB_PATH, allow_pickle=True)
    _rec_embeddings = np.asarray(data["embeddings"], dtype=np.float32)
    raw_meta = json.loads(str(data["metadata"]))
    # Ensure L2-normalized (atoms are, but npz files may not be)
    norms = np.linalg.norm(_rec_embeddings, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    _rec_embeddings = _rec_embeddings / norms
    _rec_metadata = raw_meta
    _rec_id_to_idx = {m["rec_id"]: i for i, m in enumerate(raw_meta)}
    logger.info(
        "semantic_service: loaded %d rec embeddings",
        len(raw_meta),
    )
    return _rec_embeddings, _rec_metadata, _rec_id_to_idx


def embed_query(text: str) -> np.ndarray:
    """Embed a query string with the same model, L2-normalized."""
    model = _get_model()
    return model.encode(text, normalize_embeddings=True).astype(np.float32)


def score_concept_sections(
    query_embedding: np.ndarray,
) -> Dict[str, float]:
    """Return {concept_id: cosine_similarity} for all concept sections.

    Score is in [0, 1] (clipped negative similarities to 0).
    """
    embeddings, metadata, _ = _load_concept_embeddings()
    if embeddings is None:
        return {}

    # Cosine sim = dot product on L2-normalized vectors
    scores = embeddings @ query_embedding
    scores = np.maximum(scores, 0.0)  # clip negative to zero

    result: Dict[str, float] = {}
    for i, meta in enumerate(metadata):
        result[meta["concept_id"]] = float(scores[i])
    return result


def score_recs(
    query_embedding: np.ndarray,
    rec_ids: Optional[List[str]] = None,
) -> Dict[str, float]:
    """Return {rec_id: cosine_similarity} for rec embeddings.

    If rec_ids provided, only return scores for those recs. Otherwise
    return scores for all recs.
    """
    embeddings, metadata, id_to_idx = _load_rec_embeddings()
    if embeddings is None:
        return {}

    scores = embeddings @ query_embedding
    scores = np.maximum(scores, 0.0)

    if rec_ids is None:
        return {
            metadata[i]["rec_id"]: float(scores[i])
            for i in range(len(metadata))
        }

    result: Dict[str, float] = {}
    for rid in rec_ids:
        idx = id_to_idx.get(rid)
        if idx is not None:
            result[rid] = float(scores[idx])
    return result


def is_available() -> bool:
    """True if both concept and rec embeddings are available."""
    emb, _, _ = _load_concept_embeddings()
    return emb is not None
