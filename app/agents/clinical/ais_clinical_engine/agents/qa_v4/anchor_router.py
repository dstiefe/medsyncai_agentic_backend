# ─── v4 Step 3 — Deterministic Section Router ───────────────────────
# Reads guideline_anchor_words.json and returns a ranked set of
# candidate guideline sections for a query's anchor_terms.
#
# Pure Python. No LLM. No regex beyond a trivial word-boundary match.
#
# Algorithm (two-stage, from metadata.routing_algorithm):
#   Stage 1: for each anchor term, find every section whose
#            anchor_words list contains that term (case-insensitive,
#            substring match against `term` field). Score each hit
#            by the term's tier weight (pinpoint > narrow > broad >
#            global). Sum per section. Add a role bonus when the
#            matched term carries role=primary.
#
#   Stage 2: drop `global` terms (AIS, IVT, stroke — they light up
#            the whole guideline and drown the signal) and rescore.
#            Stage 2 is the discriminating pass: the section at the
#            top of Stage 2 is the section a clinician would navigate
#            to. Stage 1 is kept as a tiebreaker.
#
# Output: an ordered list of (section_id, score) pairs, highest
# first. The content_retriever uses this set as a boost when
# scoring rec/RSS/semantic-unit matches.
# ───────────────────────────────────────────────────────────────────────
"""Deterministic section router driven by guideline_anchor_words.json."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

_REF_DIR = os.path.join(os.path.dirname(__file__), "references")
_ANCHOR_WORDS_FILE = "guideline_anchor_words.json"


# Tier weights. Pinpoint matches are worth 4x global.
# These weights lean hard on discrimination — a single pinpoint hit
# should beat a pile of global hits.
_TIER_WEIGHT = {
    "pinpoint": 4.0,
    "narrow": 2.0,
    "broad": 1.0,
    "global": 0.25,
}

# Extra weight when the matched term has role=primary.
_PRIMARY_ROLE_BONUS = 1.5


@dataclass
class SectionMatch:
    """One section with its total score and the terms that landed there."""
    section_id: str
    title: str
    stage1_score: float = 0.0
    stage2_score: float = 0.0
    matched_terms: List[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.matched_terms is None:
            self.matched_terms = []


class AnchorRouter:
    """Lazy-loaded section router over guideline_anchor_words.json.

    Loads once per process. Exposes `route(anchor_terms)` which
    returns a ranked list of SectionMatch objects — highest score
    first, after the two-stage discrimination pass.
    """

    _instance: Optional["AnchorRouter"] = None

    def __init__(self) -> None:
        self._term_index: Optional[
            Dict[str, List[Tuple[str, str, str, Optional[str]]]]
        ] = None
        self._section_titles: Dict[str, str] = {}

    @classmethod
    def get(cls) -> "AnchorRouter":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── Loading ───────────────────────────────────────────────
    def _load(self) -> None:
        path = os.path.join(_REF_DIR, _ANCHOR_WORDS_FILE)
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # term_lower → list of (section_id, tier, category, role)
        index: Dict[str, List[Tuple[str, str, str, Optional[str]]]] = {}

        def add_term(
            section_id: str,
            term: str,
            tier: str,
            category: str,
            role: Optional[str],
        ) -> None:
            if not term:
                return
            index.setdefault(term.lower(), []).append(
                (section_id, tier, category, role),
            )

        def ingest(section_id: str, container: Dict[str, Any]) -> None:
            title = container.get("title", "")
            if title:
                self._section_titles[section_id] = title
            words = container.get("anchor_words")
            # Two shapes in the JSON:
            #   sections: {"concepts": [{term, tier, role}], ...}
            #   special_tables/figures: ["term1", "term2", ...]
            if isinstance(words, dict):
                for category, entries in words.items():
                    if not isinstance(entries, list):
                        continue
                    for entry in entries:
                        if isinstance(entry, dict):
                            add_term(
                                section_id,
                                entry.get("term", ""),
                                entry.get("tier", "broad"),
                                category,
                                entry.get("role"),
                            )
                        elif isinstance(entry, str):
                            add_term(
                                section_id, entry, "pinpoint",
                                category, None,
                            )
            elif isinstance(words, list):
                # Flat list on tables/figures — treat every term as
                # pinpoint for that container.
                for entry in words:
                    if isinstance(entry, str):
                        add_term(
                            section_id, entry, "pinpoint", "misc", None,
                        )
                    elif isinstance(entry, dict):
                        add_term(
                            section_id,
                            entry.get("term", ""),
                            entry.get("tier", "pinpoint"),
                            "misc",
                            entry.get("role"),
                        )

        for sec_id, sec in (data.get("sections") or {}).items():
            ingest(sec_id, sec)

        # Tables and figures keep their original ids ("Table 9",
        # "Figure 4") so they match the keys used by _RoutingMaps
        # in content_retriever.
        for tbl_id, tbl in (data.get("special_tables") or {}).items():
            ingest(tbl_id, tbl)
        for fig_id, fig in (data.get("special_figures") or {}).items():
            ingest(fig_id, fig)

        self._term_index = index
        logger.info(
            "AnchorRouter loaded: %d distinct terms across %d sections",
            len(index), len(self._section_titles),
        )

    @property
    def term_index(
        self,
    ) -> Dict[str, List[Tuple[str, str, str, Optional[str]]]]:
        if self._term_index is None:
            self._load()
        assert self._term_index is not None
        return self._term_index

    # ── Routing ───────────────────────────────────────────────
    def _score_pass(
        self,
        anchor_terms: List[str],
        drop_global: bool,
    ) -> Dict[str, Tuple[float, List[str]]]:
        """Score every section under a single pass.

        Returns section_id → (score, matched_terms).
        """
        scores: Dict[str, Tuple[float, List[str]]] = {}
        idx = self.term_index

        for term in anchor_terms:
            t_lower = term.lower()
            # Exact match first; fall back to substring matches against
            # index keys so "alteplase dose" finds "alteplase".
            hits = idx.get(t_lower, [])
            if not hits:
                for key, val in idx.items():
                    # word-boundary-ish: match if the query term IS
                    # one of the tokens in the indexed term
                    if t_lower == key:
                        hits = val
                        break
                    if t_lower in key.split() or key in t_lower.split():
                        hits = val
                        break

            if not hits:
                continue

            # Dedupe hits per (section, term) so a section that indexes
            # the same term in multiple sub-categories (e.g. §4.6.1
            # listing "non-disabling deficit" under both `concepts`
            # and `conditions`) only earns its weight ONCE for this
            # query term. Without this, a section whose anchor_words
            # have sub-category structure would score 2x against a
            # flat-list container (e.g. Table 4) for the exact same
            # term — a structural bias, not a content signal. Pick
            # the single best hit per (section, term): highest tier
            # first, then primary-role bonus.
            best_by_section: Dict[str, Tuple[str, Optional[str]]] = {}
            for section_id, tier, _category, role in hits:
                if drop_global and tier == "global":
                    continue
                prev = best_by_section.get(section_id)
                if prev is None:
                    best_by_section[section_id] = (tier, role)
                    continue
                prev_weight = _TIER_WEIGHT.get(prev[0], 1.0)
                if prev[1] == "primary":
                    prev_weight *= _PRIMARY_ROLE_BONUS
                new_weight = _TIER_WEIGHT.get(tier, 1.0)
                if role == "primary":
                    new_weight *= _PRIMARY_ROLE_BONUS
                if new_weight > prev_weight:
                    best_by_section[section_id] = (tier, role)

            for section_id, (tier, role) in best_by_section.items():
                weight = _TIER_WEIGHT.get(tier, 1.0)
                if role == "primary":
                    weight *= _PRIMARY_ROLE_BONUS
                prev_score, prev_terms = scores.get(section_id, (0.0, []))
                new_terms = prev_terms + [term] if term not in prev_terms \
                    else prev_terms
                scores[section_id] = (prev_score + weight, new_terms)
        return scores

    def route(
        self,
        anchor_terms: List[str],
        max_results: int = 8,
    ) -> List[SectionMatch]:
        """Return a ranked list of candidate sections for these terms.

        Runs two passes (Stage 1 keeps global terms, Stage 2 drops
        them) and sorts by Stage 2 score first, Stage 1 as tiebreaker.
        """
        if not anchor_terms:
            return []

        stage1 = self._score_pass(anchor_terms, drop_global=False)
        stage2 = self._score_pass(anchor_terms, drop_global=True)

        all_section_ids = set(stage1) | set(stage2)
        matches: List[SectionMatch] = []
        for sid in all_section_ids:
            s1, terms1 = stage1.get(sid, (0.0, []))
            s2, terms2 = stage2.get(sid, (0.0, []))
            matches.append(SectionMatch(
                section_id=sid,
                title=self._section_titles.get(sid, ""),
                stage1_score=s1,
                stage2_score=s2,
                matched_terms=sorted(set(terms1) | set(terms2)),
            ))

        # Sort: Stage 2 (discriminating) first, then Stage 1 as tiebreaker
        matches.sort(
            key=lambda m: (-m.stage2_score, -m.stage1_score, m.section_id),
        )
        return matches[:max_results]

    def candidate_section_ids(
        self,
        anchor_terms: List[str],
        max_results: int = 8,
    ) -> Set[str]:
        """Convenience: return just the section ids as a set."""
        return {m.section_id for m in self.route(anchor_terms, max_results)}
