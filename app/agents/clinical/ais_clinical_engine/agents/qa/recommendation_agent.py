"""
Recommendation Agent — searches the 202 recommendations.

Responsibilities:
    - Score all 202 recommendations against the search query
    - Dual retrieval: deterministic (TOPIC_SECTION_MAP + keyword scoring)
      AND semantic (embedding similarity)
    - Merge and deduplicate results from both paths
    - Return scored recommendations with VERBATIM text (never modified)

This agent is deterministic for the keyword path.
The semantic path uses pre-computed embeddings (no LLM calls at query time).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from .schemas import IntentResult, RecommendationResult, ScoredRecommendation

# Import existing scoring functions from qa_service
from ...services.qa_service import (
    build_rec_to_conditions,
    check_applicability,
    get_section_discriminators,
    score_recommendation,
)

logger = logging.getLogger(__name__)


class RecommendationAgent:
    """Searches the 202 guideline recommendations using dual retrieval."""

    def __init__(
        self,
        recommendations_store: Dict[str, Any],
        rule_engine=None,
        embedding_store=None,
    ):
        self._recs_store = recommendations_store
        self._rule_engine = rule_engine
        self._embedding_store = embedding_store  # None until semantic search is built

        # Pre-compute the flat rec list and section discriminators
        self._all_recs_list = []
        for rec_id, rec in self._recs_store.items():
            rec_dict = (
                rec if isinstance(rec, dict)
                else (rec.model_dump() if hasattr(rec, "model_dump") else vars(rec))
            )
            self._all_recs_list.append(rec_dict)
        self._section_discriminators = get_section_discriminators(self._all_recs_list)

    def run(self, intent: IntentResult) -> RecommendationResult:
        """
        Search recommendations using deterministic + semantic retrieval.

        Args:
            intent: output from the IntentAgent

        Returns:
            RecommendationResult with scored, deduplicated recommendations
        """
        # ── Path 1: Deterministic (keyword + TOPIC_SECTION_MAP) ─────────
        deterministic_scored = self._deterministic_search(intent)

        # ── Path 2: Semantic (embedding similarity) ─────────────────────
        semantic_scored = self._semantic_search(intent)

        # ── Merge ───────────────────────────────────────────────────────
        merged = self._merge_results(deterministic_scored, semantic_scored)

        search_method = "deterministic"
        if semantic_scored:
            search_method = "hybrid" if deterministic_scored else "semantic"

        return RecommendationResult(
            scored_recs=merged,
            search_method=search_method,
        )

    def _deterministic_search(self, intent: IntentResult) -> List[ScoredRecommendation]:
        """Run the existing keyword + topic section scoring pipeline."""
        # Build applicability gate (skip for general questions)
        rec_conditions: Dict[str, List[Dict]] = {}
        if (
            self._rule_engine
            and intent.clinical_vars
            and not intent.is_general_question
        ):
            rec_conditions = build_rec_to_conditions(self._rule_engine)

        scored: List[Tuple[int, dict]] = []
        for rec_id, rec in self._recs_store.items():
            rec_dict = (
                rec if isinstance(rec, dict)
                else (rec.model_dump() if hasattr(rec, "model_dump") else vars(rec))
            )
            score = score_recommendation(
                rec_dict,
                intent.search_terms,
                question=intent.question,
                section_refs=intent.section_refs,
                topic_sections=intent.topic_sections,
                suppressed_sections=intent.suppressed_sections,
                section_discriminators=self._section_discriminators,
            )
            if score > 0:
                # Applicability gating
                if intent.clinical_vars and rec_conditions:
                    if not check_applicability(rec_id, intent.clinical_vars, rec_conditions):
                        continue
                scored.append((score, rec_dict))

        scored.sort(key=lambda x: -x[0])

        return [
            ScoredRecommendation(
                rec_id=r.get("id", ""),
                section=r.get("section", ""),
                section_title=r.get("sectionTitle", ""),
                rec_number=r.get("recNumber", ""),
                cor=r.get("cor", ""),
                loe=r.get("loe", ""),
                text=r.get("text", ""),
                score=s,
                source="deterministic",
            )
            for s, r in scored
            if s > 0
        ]

    def _semantic_search(self, intent: IntentResult) -> List[ScoredRecommendation]:
        """Run semantic (embedding) search. Returns empty list until embedding_store is built."""
        if self._embedding_store is None:
            return []

        try:
            results = self._embedding_store.search(
                query=intent.question,
                top_k=20,
            )
        except Exception as e:
            logger.warning("Semantic search failed: %s", e)
            return []

        return [
            ScoredRecommendation(
                rec_id=r["rec_id"],
                section=r["section"],
                section_title=r["section_title"],
                rec_number=r["rec_number"],
                cor=r["cor"],
                loe=r["loe"],
                text=r["text"],
                score=int(r["similarity_score"] * 100),  # normalize to int
                source="semantic",
            )
            for r in results
        ]

    @staticmethod
    def _merge_results(
        deterministic: List[ScoredRecommendation],
        semantic: List[ScoredRecommendation],
    ) -> List[ScoredRecommendation]:
        """
        Merge results from both retrieval paths.

        Deduplication: if the same rec_id appears in both, keep the higher
        score and mark source as "both".

        The merged list is sorted by score descending.
        """
        if not semantic:
            return deterministic
        if not deterministic:
            return semantic

        # Index deterministic results by rec_id
        by_id: Dict[str, ScoredRecommendation] = {}
        for rec in deterministic:
            by_id[rec.rec_id] = rec

        # Merge semantic results
        for rec in semantic:
            if rec.rec_id in by_id:
                existing = by_id[rec.rec_id]
                # Boost: found by both paths → higher confidence
                existing.score = max(existing.score, rec.score) + 5
                existing.source = "both"
            else:
                by_id[rec.rec_id] = rec

        merged = list(by_id.values())
        merged.sort(key=lambda r: -r.score)
        return merged
