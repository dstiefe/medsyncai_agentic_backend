# ─── v3 (Q&A v3 namespace) ─────────────────────────────────────────────
# This file lives under agents/qa_v3/ and is the active v3 copy of the
# Guideline Q&A pipeline. Edits made here do NOT affect agents/qa/
# which remains as the v2 baseline. To switch the live route to v3,
# update the import at services/qa_service.py or routes.py accordingly.
# ───────────────────────────────────────────────────────────────────────
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
import re
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

        # ── Applicability reranking ────────────────────────────────────
        # When the question contains clinical variables (time, vessel,
        # age, etc.), rerank recs by how well their criteria match.
        # This ensures "M1 at 10 hrs" surfaces the 6-24h recs first.
        if intent.clinical_vars:
            merged = _applicability_rerank(merged, intent.clinical_vars)

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

        scored.sort(key=lambda x: (
            -x[0], _COR_SORT_ORDER.get(x[1].get("cor", ""), 9)
        ))

        # ── Off-topic suppression ────────────────────────────────────
        # When TOPIC_SECTION_MAP gives specific sections, demote recs from
        # unrelated sections that only scored via generic keyword overlap.
        # This prevents "antiepileptic drugs after stroke" → 4.8 when the
        # map clearly says → 6.5.
        if intent.topic_sections and not intent.section_refs:
            target_set = set(intent.topic_sections)
            adjusted = []
            for s, r in scored:
                rec_sec = r.get("section", "")
                in_target = any(
                    rec_sec == ts or rec_sec.startswith(ts + ".")
                    or ts.startswith(rec_sec + ".")
                    for ts in target_set
                )
                if in_target:
                    # Boost in-target recs to ensure they surface
                    adjusted.append((s + 20, r))
                else:
                    # Demote off-topic recs that only scored via generic overlap
                    adjusted.append((s // 2, r))
            scored = adjusted
            scored.sort(key=lambda x: (
                -x[0], _COR_SORT_ORDER.get(x[1].get("cor", ""), 9)
            ))

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

        # COR-aware sorting: within the same section, recs with stronger
        # COR (1 > 2a > 2b > 3) should appear first even if the semantic
        # similarity score gives a slight edge to a weaker rec.
        # We bucket scores into bands of 5 so that small score differences
        # from embedding noise don't override clinical strength.
        merged.sort(key=lambda r: (
            -(r.score // 5),  # score bucket (5-point bands)
            _COR_SORT_ORDER.get(r.cor, 9),  # COR strength within bucket
            -r.score,  # exact score within same COR
        ))
        return merged


# COR strength ordering for tie-breaking (lower = stronger)
_COR_SORT_ORDER = {
    "1": 0,
    "2a": 1,
    "2b": 2,
    "3: No Benefit": 3,
    "3:No Benefit": 3,
    "3: Harm": 4,
    "3:Harm": 4,
}


# ── Applicability Reranking ───────────────────────────────────────
# Post-retrieval step: parse each rec's text for clinical criteria
# (time windows, vessel types, etc.) and compare against the user's
# specified variables. Boost matching recs, demote conflicting ones.
#
# This is the QA equivalent of the CMI applicability gate.

# Score adjustments
_APPLICABILITY_MATCH_BONUS = 15    # rec criteria match user's variable
_APPLICABILITY_CONFLICT_PENALTY = 20  # rec criteria conflict with user's variable


def _extract_time_windows(text: str) -> List[Tuple[float, float]]:
    """
    Extract time window ranges from recommendation text.

    Returns list of (lower_hours, upper_hours) tuples.
    Examples:
        "within 6 hours" → [(0, 6)]
        "6 to 24 hours" → [(6, 24)]
        "between 6 and 24 hours" → [(6, 24)]
        "within 24 hours" → [(0, 24)]
    """
    windows = []
    text_lower = text.lower()

    # "between X and Y hours" or "X to Y hours"
    for m in re.finditer(
        r'(?:between|presenting)\s+(\d+\.?\d*)\s+(?:and|to)\s+(\d+\.?\d*)\s*hours?',
        text_lower,
    ):
        windows.append((float(m.group(1)), float(m.group(2))))

    # "within X hours" or "presenting within X hours"
    for m in re.finditer(r'within\s+(\d+\.?\d*)\s*hours?', text_lower):
        windows.append((0, float(m.group(1))))

    # "X to Y hours from" (more flexible pattern)
    if not windows:
        for m in re.finditer(
            r'(\d+\.?\d*)\s*(?:[-\u2013]|to)\s*(\d+\.?\d*)\s*hours?\s*(?:from|after|of)',
            text_lower,
        ):
            windows.append((float(m.group(1)), float(m.group(2))))

    return windows


def _extract_vessel_refs(text: str) -> List[str]:
    """Extract vessel references from recommendation text."""
    vessels = []
    text_lower = text.lower()
    # Order matters: check specific before generic
    vessel_patterns = [
        (r'\bm3\b', 'M3'),
        (r'\bm2\b', 'M2'),
        (r'\bm1\b', 'M1'),
        (r'\bica\b', 'ICA'),
        (r'\bbasilar\b', 'basilar'),
        (r'\bvertebr', 'basilar'),
        (r'\banterior cerebral\b|aca', 'ACA'),
        (r'\bposterior cerebral\b|pca', 'PCA'),
        (r'\bmedium\s+or\s+distal\b', 'medium_distal'),
        (r'\bdistal\s+mca\b', 'distal_MCA'),
        (r'\bproximal\s+lvo\b', 'proximal_LVO'),
    ]
    for pattern, label in vessel_patterns:
        if re.search(pattern, text_lower):
            vessels.append(label)
    return vessels


def _time_in_window(
    time_hours: float, windows: List[Tuple[float, float]]
) -> Optional[bool]:
    """
    Check if a time value falls within any of the rec's time windows.

    Returns:
        True  — time fits within at least one window
        False — time is outside all windows (conflict)
        None  — rec has no time windows (neutral)
    """
    if not windows:
        return None
    for lo, hi in windows:
        if lo <= time_hours <= hi:
            return True
    return False


def _applicability_rerank(
    scored_recs: List[ScoredRecommendation],
    clinical_vars: Dict[str, Any],
) -> List[ScoredRecommendation]:
    """
    Rerank scored recs by applicability to the user's clinical variables.

    For each rec, parse its text for time windows, vessel references, etc.
    and check compatibility with the extracted variables. Adjust scores
    so matching recs surface first.
    """
    if not scored_recs or not clinical_vars:
        return scored_recs

    time_val = clinical_vars.get("timeHours")
    vessel_val = clinical_vars.get("vessel")

    # Nothing to gate on
    if time_val is None and vessel_val is None:
        return scored_recs

    # Normalize time to a single float (if it's a range, use the midpoint)
    query_time: Optional[float] = None
    if time_val is not None:
        if isinstance(time_val, tuple):
            query_time = (time_val[0] + time_val[1]) / 2
        else:
            query_time = float(time_val)

    reranked = []
    for rec in scored_recs:
        adjustment = 0

        # ── Time window matching ──────────────────────────────────
        if query_time is not None:
            windows = _extract_time_windows(rec.text)
            match = _time_in_window(query_time, windows)
            if match is True:
                adjustment += _APPLICABILITY_MATCH_BONUS
            elif match is False:
                adjustment -= _APPLICABILITY_CONFLICT_PENALTY

        # ── Vessel matching ───────────────────────────────────────
        if vessel_val is not None:
            rec_vessels = _extract_vessel_refs(rec.text)
            if rec_vessels:
                vessel_upper = vessel_val.upper()
                rec_vessels_upper = [v.upper() for v in rec_vessels]

                # Direct match: rec mentions the user's vessel
                if vessel_upper in rec_vessels_upper:
                    adjustment += _APPLICABILITY_MATCH_BONUS
                # Proximal LVO covers M1 and ICA
                elif vessel_upper in ("M1", "ICA") and "PROXIMAL_LVO" in rec_vessels_upper:
                    adjustment += _APPLICABILITY_MATCH_BONUS
                # Conflict: rec is about a different vessel type
                elif vessel_upper not in rec_vessels_upper:
                    # Only penalize if the rec is specifically about OTHER vessels
                    # Don't penalize generic recs that don't mention vessels
                    adjustment -= _APPLICABILITY_CONFLICT_PENALTY // 2

        rec.score += adjustment
        reranked.append(rec)

    # Re-sort with COR-aware bucketing
    reranked.sort(key=lambda r: (
        -(r.score // 5),
        _COR_SORT_ORDER.get(r.cor, 9),
        -r.score,
    ))
    return reranked
