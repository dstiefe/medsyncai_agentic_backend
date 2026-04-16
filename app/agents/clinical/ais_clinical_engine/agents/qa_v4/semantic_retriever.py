# ─── v4 Semantic Retriever ──────────────────────────────────────────
#
# Embedding-based retrieval over the atomized guideline corpus.
#
# Every atom in guideline_knowledge.json carries a pre-computed
# 384-dim embedding (all-MiniLM-L6-v2, L2-normalized). At query
# time the clinician's question is embedded with the same model
# and scored by cosine similarity against every atom. Top-K atoms
# are returned regardless of section boundaries.
#
# This replaces the six competing search functions in the legacy
# content_retriever.py:
#   _search_all_recs, _search_all_rss, _search_topic_recs,
#   _search_topic_rss, _discover_category_index, _fetch_categorized_rows
#
# Scoring formula:
#   score = semantic_weight × cosine(query_emb, atom_emb)
#         + anchor_weight  × jaccard(query_anchors, atom_anchors)
#         + intent_weight  × (1.0 if intent matches else 0.0)
#
# Weights are tunable. The semantic signal is primary because it
# handles phrasing variation ("non-disabling stroke" ≈ "non-disabling
# deficit") that anchor/intent matching cannot.
#
# Pure Python + numpy. No LLM. Deterministic.
# ───────────────────────────────────────────────────────────────────────
"""
Semantic retriever: embedding-based atom search for qa_v4.

Loads atom embeddings on first use. Exposes `search(query, parsed, k)`
which returns the top-K atoms by combined semantic + anchor + intent
score.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np

from .schemas import ParsedQAQuery

logger = logging.getLogger(__name__)

# ── Paths ─────────────────────────────────────────────────────────────

_DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data",
)
# Prefer the atomized version if it exists; fall back to original.
_ATOMIZED_PATH = os.path.join(_DATA_DIR, "guideline_knowledge.atomized.json")
_FALLBACK_PATH = os.path.join(_DATA_DIR, "guideline_knowledge.json")

_INTENT_MAP_PATH = os.path.join(
    os.path.dirname(__file__),
    "references", "intent_map.json",
)

# ── Scoring weights ──────────────────────────────────────────────────

_W_SEMANTIC = 0.6   # cosine similarity — primary signal
_W_ANCHOR = 0.25    # Jaccard overlap with expanded anchor terms
_W_INTENT = 0.15    # intent affinity match (binary)

# Minimum combined score to include an atom in results.
_SCORE_THRESHOLD = 0.25

# Default top-K for search.
_DEFAULT_K = 15

# ── Embedding model (lazy-loaded) ────────────────────────────────────

_MODEL_NAME = "all-MiniLM-L6-v2"
_model = None


def _get_model():
    """Lazy-load the sentence-transformer model."""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        logger.info("semantic_retriever: loading model %s", _MODEL_NAME)
        _model = SentenceTransformer(_MODEL_NAME)
    return _model


# ── Atom index (lazy-loaded) ─────────────────────────────────────────

_atoms_cache: Optional[List[Dict[str, Any]]] = None
_embeddings_cache: Optional[np.ndarray] = None
_concept_expansions_cache: Optional[Dict[str, List[str]]] = None


def _load_atoms() -> Tuple[List[Dict[str, Any]], np.ndarray]:
    """Load all atoms and their embeddings from the knowledge store."""
    global _atoms_cache, _embeddings_cache
    if _atoms_cache is not None and _embeddings_cache is not None:
        return _atoms_cache, _embeddings_cache

    # Pick data source
    path = _ATOMIZED_PATH if os.path.exists(_ATOMIZED_PATH) else _FALLBACK_PATH
    logger.info("semantic_retriever: loading atoms from %s", path)

    with open(path, "r", encoding="utf-8") as f:
        kb = json.load(f)

    atoms: List[Dict[str, Any]] = []
    embeddings: List[List[float]] = []

    for sec_id, sec_body in (kb.get("sections") or {}).items():
        for atom in (sec_body.get("atoms") or []):
            emb = atom.get("embedding")
            if not emb or not atom.get("text"):
                continue
            atoms.append(atom)
            embeddings.append(emb)

    if not atoms:
        logger.warning("semantic_retriever: no atoms with embeddings found")
        _atoms_cache = []
        _embeddings_cache = np.array([])
        return _atoms_cache, _embeddings_cache

    emb_matrix = np.array(embeddings, dtype=np.float32)
    # Ensure L2-normalized for cosine via dot product
    norms = np.linalg.norm(emb_matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    emb_matrix = emb_matrix / norms

    _atoms_cache = atoms
    _embeddings_cache = emb_matrix
    logger.info(
        "semantic_retriever: indexed %d atoms (%d dims)",
        len(atoms), emb_matrix.shape[1],
    )
    return _atoms_cache, _embeddings_cache


def _load_concept_expansions() -> Dict[str, List[str]]:
    """Load concept expansions from intent_map.json."""
    global _concept_expansions_cache
    if _concept_expansions_cache is not None:
        return _concept_expansions_cache

    out: Dict[str, List[str]] = {}
    try:
        with open(_INTENT_MAP_PATH, "r") as f:
            im = json.load(f)
        raw = im.get("concept_expansions", {}) or {}
        for term, body in raw.items():
            if isinstance(body, dict):
                targets = body.get("expands_to", []) or []
                syns = body.get("synonyms", []) or []
                out[term.lower()] = [t.lower() for t in targets] + [
                    s.lower() for s in syns
                ]
    except Exception as e:
        logger.warning("semantic_retriever: concept expansions: %s", e)
    _concept_expansions_cache = out
    return out


def _expand_anchors(anchor_terms: Optional[Dict[str, Any]]) -> Set[str]:
    """Expand query anchor terms using concept expansions."""
    if not anchor_terms:
        return set()
    expansions = _load_concept_expansions()
    out: Set[str] = set()
    for term in anchor_terms.keys():
        low = term.lower()
        out.add(low)
        for e in expansions.get(low, []):
            out.add(e)
    return out


# ── Scoring ──────────────────────────────────────────────────────────


def _score_atoms(
    query_embedding: np.ndarray,
    query_anchors: Set[str],
    query_intent: str,
    atoms: List[Dict[str, Any]],
    atom_embeddings: np.ndarray,
) -> List[Tuple[float, int, Dict[str, float]]]:
    """Score all atoms against the query.

    Returns list of (total_score, atom_index, breakdown) sorted
    by score descending.
    """
    # Semantic scores: dot product with normalized vectors = cosine sim
    # Shape: (n_atoms,)
    semantic_scores = atom_embeddings @ query_embedding

    scored: List[Tuple[float, int, Dict[str, float]]] = []

    for i, atom in enumerate(atoms):
        breakdown = {
            "semantic": 0.0,
            "anchor": 0.0,
            "intent": 0.0,
        }

        # Semantic score (cosine similarity, already in [−1, 1])
        cos_sim = float(semantic_scores[i])
        # Clamp to [0, 1] — negative similarity means irrelevant
        cos_sim = max(0.0, cos_sim)
        breakdown["semantic"] = cos_sim

        # Anchor Jaccard
        atom_anchors = {a.lower() for a in (atom.get("anchor_terms") or [])}
        if query_anchors and atom_anchors:
            overlap = query_anchors & atom_anchors
            union = query_anchors | atom_anchors
            if union:
                breakdown["anchor"] = len(overlap) / len(union)

        # Intent affinity
        if query_intent and query_intent in (atom.get("intent_affinity") or []):
            breakdown["intent"] = 1.0

        total = (
            _W_SEMANTIC * breakdown["semantic"]
            + _W_ANCHOR * breakdown["anchor"]
            + _W_INTENT * breakdown["intent"]
        )

        scored.append((total, i, breakdown))

    scored.sort(key=lambda x: -x[0])
    return scored


# ── Public API ───────────────────────────────────────────────────────


def search(
    raw_query: str,
    parsed: Optional[ParsedQAQuery] = None,
    k: int = _DEFAULT_K,
    score_threshold: float = _SCORE_THRESHOLD,
) -> List[Dict[str, Any]]:
    """Search the atom corpus by semantic similarity + anchor + intent.

    Args:
        raw_query: the clinician's question text (embedded at runtime).
        parsed: Step 1 output (optional — provides anchor_terms, intent).
        k: maximum number of atoms to return.
        score_threshold: minimum combined score to include.

    Returns:
        List of atom dicts, each augmented with:
          _score: combined score
          _breakdown: {semantic, anchor, intent} component scores
        Sorted by score descending.
    """
    atoms, atom_embeddings = _load_atoms()
    if not atoms:
        logger.warning("semantic_retriever: no atoms loaded — empty results")
        return []

    # Embed the query
    model = _get_model()
    t0 = time.time()
    query_emb = model.encode(
        raw_query,
        normalize_embeddings=True,
    ).astype(np.float32)
    embed_ms = (time.time() - t0) * 1000

    # Extract signals from parsed query
    query_anchors: Set[str] = set()
    query_intent = ""
    if parsed:
        query_anchors = _expand_anchors(parsed.anchor_terms)
        query_intent = parsed.intent or ""

    # Score all atoms
    scored = _score_atoms(
        query_emb, query_anchors, query_intent,
        atoms, atom_embeddings,
    )

    # Filter by threshold and take top-K
    results: List[Dict[str, Any]] = []
    for total, idx, breakdown in scored:
        if total < score_threshold:
            break  # sorted desc — everything below is lower
        atom = atoms[idx]
        results.append({
            **atom,
            "_score": round(total, 4),
            "_breakdown": {k: round(v, 4) for k, v in breakdown.items()},
        })
        if len(results) >= k:
            break

    logger.info(
        "semantic_retriever: query='%s' → %d atoms above threshold "
        "(embed=%.0fms, top_score=%.3f, intent=%s, anchors=%s)",
        raw_query[:60],
        len(results),
        embed_ms,
        results[0]["_score"] if results else 0.0,
        query_intent,
        sorted(query_anchors)[:5] if query_anchors else [],
    )

    return results


def search_rss_rows(
    raw_query: str,
    parsed: Optional[ParsedQAQuery] = None,
    k: int = _DEFAULT_K,
    score_threshold: float = _SCORE_THRESHOLD,
) -> List[Dict[str, Any]]:
    """Search and return results in the RSS row shape expected by
    the response presenter (_build_detail).

    Same as search() but maps atom fields to:
        section, sectionTitle, recNumber, category, condition, text
    """
    atoms = search(raw_query, parsed, k, score_threshold)
    rows: List[Dict[str, Any]] = []
    for atom in atoms:
        rows.append({
            "section": atom.get("parent_section", ""),
            "sectionTitle": atom.get("parent_display_group", ""),
            "recNumber": atom.get("atom_id", ""),
            "category": atom.get("category", "") or atom.get("atom_type", ""),
            "condition": atom.get("condition", ""),
            "text": atom.get("text", ""),
            "_score": atom.get("_score", 0.0),
            "_breakdown": atom.get("_breakdown", {}),
            "_atom": True,
        })
    return rows


def reset_caches() -> None:
    """Testing hook: clear all in-memory caches."""
    global _atoms_cache, _embeddings_cache, _concept_expansions_cache, _model
    _atoms_cache = None
    _embeddings_cache = None
    _concept_expansions_cache = None
    # Don't reset _model — too expensive to reload
