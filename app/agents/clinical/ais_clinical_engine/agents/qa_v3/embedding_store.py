# ─── v3 (Q&A v3 namespace) ─────────────────────────────────────────────
# This file lives under agents/qa_v3/ and is the active v3 copy of the
# Guideline Q&A pipeline. Edits made here do NOT affect agents/qa/
# which remains as the v2 baseline. To switch the live route to v3,
# update the import at services/qa_service.py or routes.py accordingly.
# ───────────────────────────────────────────────────────────────────────
"""
Embedding Store — vector search for the 202 guideline recommendations.

Provides semantic search alongside the deterministic TOPIC_SECTION_MAP
pipeline. When a clinician uses different terminology than what appears
in the guideline, semantic search still finds the right recommendation.

Architecture:
    - One-time offline step: embed all 202 recommendations
    - At query time: embed the question, find top-K nearest recs
    - Uses sentence-transformers for embeddings (runs locally, no API call)
    - Uses numpy cosine similarity (lightweight, no vector DB needed)

The store is loaded lazily and cached in memory after first use.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

# Path to the pre-computed embeddings file
_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_EMBEDDINGS_FILE = _DATA_DIR / "recommendation_embeddings.npz"
_RECS_FILE = _DATA_DIR / "recommendations.json"


class EmbeddingStore:
    """
    Vector store for semantic search over the 202 recommendations.

    Usage:
        store = EmbeddingStore()
        store.load()  # loads pre-computed embeddings
        results = store.search("Can I give clot-busting drugs to someone on blood thinners?", top_k=10)
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self._model_name = model_name
        self._model = None
        self._embeddings: Optional[np.ndarray] = None    # (202, dim)
        self._rec_metadata: List[Dict[str, Any]] = []     # parallel to embeddings
        self._loaded = False

    @property
    def is_available(self) -> bool:
        """True if embeddings are loaded and ready for search."""
        return self._loaded and self._embeddings is not None

    def load(self) -> bool:
        """
        Load pre-computed embeddings from disk.

        Returns True if successful, False if embeddings file doesn't exist
        (call build_embeddings() first).
        """
        if self._loaded:
            return True

        if not _EMBEDDINGS_FILE.exists():
            logger.warning(
                "Embeddings file not found at %s. "
                "Run build_embeddings() to generate it.",
                _EMBEDDINGS_FILE,
            )
            return False

        try:
            data = np.load(str(_EMBEDDINGS_FILE), allow_pickle=True)
            self._embeddings = data["embeddings"]
            self._rec_metadata = json.loads(data["metadata"].item())
            self._loaded = True
            logger.info(
                "Loaded %d recommendation embeddings (dim=%d)",
                self._embeddings.shape[0],
                self._embeddings.shape[1],
            )
            return True
        except Exception as e:
            logger.error("Failed to load embeddings: %s", e)
            return False

    def build_embeddings(self) -> None:
        """
        One-time offline step: embed all 202 recommendations and save to disk.

        Requires sentence-transformers to be installed.
        """
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            raise ImportError(
                "sentence-transformers is required to build embeddings. "
                "Install with: pip install sentence-transformers"
            )

        logger.info("Building embeddings for 202 recommendations...")

        # Load recommendations
        with open(_RECS_FILE, "r", encoding="utf-8") as f:
            recs_data = json.load(f)
        recs = recs_data["recommendations"]

        # Prepare texts for embedding — include context for better matching
        texts = []
        metadata = []
        for rec in recs:
            # Combine section title + rec text for richer embedding
            embed_text = (
                f"Section {rec['section']} {rec['sectionTitle']}: {rec['text']}"
            )
            texts.append(embed_text)
            metadata.append({
                "rec_id": rec["id"],
                "section": rec["section"],
                "section_title": rec["sectionTitle"],
                "rec_number": rec["recNumber"],
                "cor": rec["cor"],
                "loe": rec["loe"],
                "text": rec["text"],
            })

        # Embed
        model = SentenceTransformer(self._model_name)
        embeddings = model.encode(texts, show_progress_bar=True, normalize_embeddings=True)

        # Save
        np.savez(
            str(_EMBEDDINGS_FILE),
            embeddings=embeddings,
            metadata=json.dumps(metadata),
        )
        logger.info(
            "Saved %d embeddings to %s (dim=%d)",
            len(metadata),
            _EMBEDDINGS_FILE,
            embeddings.shape[1],
        )

        # Update in-memory state
        self._embeddings = embeddings
        self._rec_metadata = metadata
        self._loaded = True

    def search(
        self,
        query: str,
        top_k: int = 20,
        min_similarity: float = 0.25,
    ) -> List[Dict[str, Any]]:
        """
        Search recommendations by semantic similarity.

        Args:
            query: the user's question
            top_k: maximum results to return
            min_similarity: minimum cosine similarity threshold

        Returns:
            List of dicts with rec metadata + similarity_score
        """
        if not self.is_available:
            return []

        # Lazy-load the model for query embedding
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
                self._model = SentenceTransformer(self._model_name)
            except ImportError:
                logger.warning("sentence-transformers not available for query embedding")
                return []

        # Embed the query
        query_embedding = self._model.encode(
            [query], normalize_embeddings=True
        )[0]

        # Cosine similarity — embeddings are already L2-normalized so
        # dot product equals cosine similarity.
        # Suppress numpy overflow warnings from LibreSSL/accelerate framework;
        # the results are numerically correct despite the warnings.
        with np.errstate(all="ignore"):
            similarities = np.dot(
                self._embeddings.astype(np.float64),
                query_embedding.astype(np.float64),
            )

        # Replace any NaN with 0 (defensive)
        similarities = np.nan_to_num(similarities, nan=0.0)

        # Get top-K above threshold
        top_indices = np.argsort(similarities)[::-1][:top_k]

        results = []
        for idx in top_indices:
            sim = float(similarities[idx])
            if sim < min_similarity:
                break
            result = dict(self._rec_metadata[idx])
            result["similarity_score"] = sim
            results.append(result)

        return results
