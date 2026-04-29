"""
Section Router — maps LLM topic classification to guideline sections.

Architecture:
    1. LLM classifies question → topic + optional qualifier
    2. THIS MODULE looks up topic → section (deterministic, like a calculator)
    3. Orchestrator pulls ALL recs/RSS from that section
    4. Assembly LLM presents the data

The LLM understands intent (picks the topic).
Python does the lookup (topic → section) and retrieval.
No keyword matching. No scoring. Direct mapping.

Reference files used:
    - guideline_topic_map.json         — topic → section mapping (the calculator)

    - ais_guideline_section_map.json   — section IDs + titles (for validation)
    - data_dictionary.json             — additional section IDs (for validation)
"""

from __future__ import annotations

import itertools
import json
import logging
import os
import re
from collections import defaultdict
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_REF_DIR = os.path.join(os.path.dirname(__file__), "references")


# ── Synonym groups loaded from synonym_dictionary.json ──────────────
# When counting distinct search term matches, synonyms count as ONE
# concept, not multiple. "IVT" + "thrombolysis" = 1 concept, not 2.
#
# Groups are built by:
#   1. Each dictionary entry → set of {abbreviation, full_term, synonyms}
#   2. Entries with related categories AND overlapping guideline sections
#      are merged into one group (e.g., IVT + tPA + TNK → one group)
#
# Merging rules:
# - Only entries with the SAME category merge (not cross-category)
# - Sections must overlap: exact match, parent-child, or siblings
#   under a 2+ level parent (e.g., 4.7.2 and 4.7.3 share 4.7)
# - Chapter-level parents (e.g., "4") are too broad and don't count


def _sections_overlap(secs_a: set, secs_b: set) -> bool:
    """Check if two section sets overlap (exact, parent-child, or sibling under 2+ level parent)."""
    for sa in secs_a:
        for sb in secs_b:
            if sa == sb:
                return True
            # Parent-child: 4.6 is parent of 4.6.2
            if sa.startswith(sb + ".") or sb.startswith(sa + "."):
                return True
            # Siblings under a 2+ level parent: 4.7.2 and 4.7.3 share 4.7
            parts_a = sa.split(".")
            parts_b = sb.split(".")
            if len(parts_a) >= 2 and len(parts_b) >= 2:
                if parts_a[:2] == parts_b[:2]:
                    return True
    return False


def _parse_sections(sections_list: List[str]) -> set:
    """Parse section strings like ['4.6', '4.6.1'] or ['4.6.5, 4.9']."""
    result = set()
    for s in sections_list:
        if isinstance(s, str):
            for part in s.split(","):
                cleaned = part.strip().lower()
                if cleaned and cleaned not in ("all", "multiple"):
                    result.add(cleaned)
    return result


def _normalize_category(category: str) -> str:
    """Normalize category string for comparison."""
    return category.lower().replace("/", "_").replace(" ", "_").strip()


def _merge_key(info: Dict[str, Any]) -> str:
    """
    Return the key used to decide whether two entries can merge.

    Uses subcategory (drug class) when present — this separates
    thrombolytics from anticoagulants from antiplatelets, even though
    they're all "medication" or "treatment".

    Falls back to category when no subcategory exists.
    """
    sub = info.get("subcategory", "")
    if sub:
        return sub.lower().strip()
    return _normalize_category(info.get("category", ""))


def _build_synonym_groups() -> List[set]:
    """
    Build synonym groups from synonym_dictionary.json.

    Each entry becomes a set of all its forms (abbreviation + full_term +
    synonyms). Entries with the same merge key (subcategory or category)
    AND overlapping sections are merged into one group via union-find.

    subcategory separates drug classes:
        IVT/tPA/TNK → "thrombolytic"
        DOAC/LMWH/UFH → "anticoagulant"
        DAPT → "antiplatelet"
        CTA/CTP/NCCT → "ct"
        DWI/FLAIR/MRI/MRA → "mri"
    """
    path = os.path.join(_REF_DIR, "synonym_dictionary.json")
    with open(path, "r") as f:
        data = json.load(f)

    terms = data.get("terms", {})

    # Step 1: Build per-entry synonym sets
    entry_sets: Dict[str, set] = {}
    entry_sections: Dict[str, set] = {}
    entry_merge_key: Dict[str, str] = {}

    for abbrev, info in terms.items():
        # Skip comment entries (keys like "_comment_trials" whose value is a
        # plain string used as a section separator in the source JSON).
        if abbrev.startswith("_") or not isinstance(info, dict):
            continue
        forms = {abbrev.lower()}
        full_term = info.get("full_term", "")
        if full_term:
            forms.add(full_term.lower())
        for syn in info.get("synonyms", []):
            forms.add(syn.lower())
        entry_sets[abbrev] = forms
        entry_sections[abbrev] = _parse_sections(info.get("sections", []))
        entry_merge_key[abbrev] = _merge_key(info)

    # Step 2: Union-find to merge entries with same merge key + overlapping sections
    abbrevs = list(entry_sets.keys())
    parent = {a: a for a in abbrevs}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        px, py = find(x), find(y)
        if px != py:
            parent[px] = py

    for a, b in itertools.combinations(abbrevs, 2):
        if entry_merge_key[a] != entry_merge_key[b]:
            continue
        if _sections_overlap(entry_sections[a], entry_sections[b]):
            union(a, b)

    # Step 3: Build final groups
    groups: Dict[str, set] = defaultdict(set)
    for abbrev in abbrevs:
        root = find(abbrev)
        groups[root].update(entry_sets[abbrev])

    result = list(groups.values())
    logger.info(
        "Built %d synonym groups from synonym_dictionary.json (%d entries)",
        len(result), len(abbrevs),
    )
    return result


# Build once at module load
_SYNONYM_GROUPS = _build_synonym_groups()


def _word_boundary_match(term: str, corpus: str) -> bool:
    """Check if a search term appears in the corpus as a whole phrase.

    Uses word boundaries so "stroke unit" matches "stroke unit care" and
    "organized stroke unit" but NOT "mobile stroke unit" (where "mobile"
    is part of the concept).

    For multi-word terms: checks the term appears with a word boundary
    (or start-of-string) immediately before the first word. This prevents
    "stroke unit" from matching inside "mobile stroke unit."

    For single-word terms or short abbreviations (<=4 chars like IVT, EVT):
    uses standard word boundary \\b on both sides.
    """
    escaped = re.escape(term)
    if len(term) <= 4 or " " not in term:
        # Short term or single word: word boundaries on both sides
        return bool(re.search(r"\b" + escaped + r"\b", corpus))
    # Multi-word phrase: require start-of-string or word boundary before,
    # and word boundary after
    return bool(re.search(r"(?:^|(?<=\s))" + escaped + r"\b", corpus))


def _deduplicate_by_synonyms(terms: List[str]) -> List[str]:
    """
    Deduplicate search terms so synonyms count as one concept.

    Returns a list with at most one representative per synonym group.
    Terms not in any group pass through unchanged.
    """
    terms_lower = [t.lower() for t in terms]
    result = []
    used_groups: set = set()

    for term in terms_lower:
        # Check if this term belongs to a synonym group
        matched_group = None
        for i, group in enumerate(_SYNONYM_GROUPS):
            if term in group:
                matched_group = i
                break

        if matched_group is not None:
            if matched_group not in used_groups:
                used_groups.add(matched_group)
                result.append(term)
            # else: skip — this synonym group already counted
        else:
            result.append(term)

    return result


# RELATED_SECTIONS removed. Sections are included only when their
# content matches multiple search terms from the question. A section
# that shares one keyword (e.g. "IVT") is not relevant — it must
# contain the actual topic terms (e.g. "blood pressure", "SBP", "185").
# Search term filtering in the orchestrator handles this.


def _load_json(filename: str) -> Dict[str, Any]:
    path = os.path.join(_REF_DIR, filename)
    with open(path, "r") as f:
        return json.load(f)


class SectionRouter:
    """
    Maps LLM topic picks to guideline sections and retrieves content.

    The LLM classifies the question into a topic from the Topic Guide.
    This router looks up topic → section. That's a direct lookup —
    no keyword matching, no scoring, no ambiguity.
    """

    def __init__(self):
        self._section_map = _load_json("ais_guideline_section_map.json")
        self._topic_map = _load_json("guideline_topic_map.json")
        self._data_dict = _load_json("data_dictionary.json")

        # Build topic → section lookup (the calculator)
        self._topic_to_section: Dict[str, str] = {}
        self._topic_to_subtopics: Dict[str, List[Dict[str, str]]] = {}
        for entry in self._topic_map.get("topics", []):
            topic = entry["topic"]
            self._topic_to_section[topic] = entry["section"]
            if "subtopics" in entry:
                self._topic_to_subtopics[topic] = entry["subtopics"]

        # Build set of all valid section IDs for validation
        self._valid_ids: set = set()
        for section in self._section_map.get("sections", []):
            self._collect_section_ids(section, self._valid_ids)
        for sec_id in self._data_dict.get("sections", {}):
            self._valid_ids.add(sec_id)

        logger.info(
            "SectionRouter: %d topics, %d valid section IDs",
            len(self._topic_to_section), len(self._valid_ids),
        )

    # ── Public API ────────────────────────────────────────────────────

    def resolve_topic(
        self, topic: str, qualifier: Optional[str] = None,
    ) -> List[str]:
        """
        Look up topic → section. If qualifier matches a subtopic, narrow
        to that subsection. Appends clinically related sections so the
        LLM has the full picture. Pure lookup — like a calculator.

        Args:
            topic: LLM-classified topic (e.g., "EVT", "IVT")
            qualifier: optional subtopic qualifier (e.g., "posterior circulation")

        Returns:
            List of section IDs (primary + related), or empty if topic not found
        """
        section = self._topic_to_section.get(topic)
        if not section:
            logger.warning("Topic not found in map: '%s'", topic)
            return []

        primary = section

        # Try to narrow by qualifier
        if qualifier and topic in self._topic_to_subtopics:
            for subtopic in self._topic_to_subtopics[topic]:
                if subtopic["qualifier"].lower() == qualifier.lower():
                    primary = subtopic["section"]
                    logger.info(
                        "Topic '%s' + qualifier '%s' → section %s",
                        topic, qualifier, primary,
                    )
                    break
            else:
                # Qualifier didn't match any subtopic exactly — try partial match
                qualifier_lower = qualifier.lower()
                for subtopic in self._topic_to_subtopics[topic]:
                    if qualifier_lower in subtopic["qualifier"].lower():
                        primary = subtopic["section"]
                        logger.info(
                            "Topic '%s' + qualifier '%s' → section %s (partial match)",
                            topic, qualifier, primary,
                        )
                        break
                else:
                    # Qualifier not recognized — use parent section
                    logger.info(
                        "Topic '%s' qualifier '%s' not matched — using parent section %s",
                        topic, qualifier, section,
                    )

        logger.info("Topic '%s' → section %s", topic, primary)
        return [primary]

    def validate_sections(self, sections: List[str]) -> List[str]:
        """
        Validate that section IDs exist in the guideline.

        Args:
            sections: section IDs to validate

        Returns:
            List of valid section IDs (preserves order, max 3)
        """
        validated = [s for s in sections if s in self._valid_ids]
        validated = self._prefer_specific(validated)

        dropped = [s for s in sections if s not in self._valid_ids]
        if dropped:
            logger.warning("Dropped invalid section IDs: %s", dropped)

        return validated[:3]

    def pull_section_recs(
        self,
        sections: List[str],
        recommendations_store: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """
        Pull ALL recommendations from the specified sections.

        No scoring. No filtering. The section IS the filter.
        Returns recs ordered by COR strength (1 > 2a > 2b > 3).
        """
        COR_ORDER = {"1": 0, "2a": 1, "2b": 2, "3:No Benefit": 3, "3:Harm": 4, "3": 3}

        recs = []
        for rec_id, rec in recommendations_store.items():
            rec_section = rec.get("section", "")
            if rec_section in sections or any(
                rec_section.startswith(s + ".") for s in sections
            ):
                recs.append(rec)

        recs.sort(key=lambda r: (
            COR_ORDER.get(r.get("cor", ""), 99),
            r.get("recNumber", 99),
        ))
        return recs

    def pull_section_content(
        self,
        sections: List[str],
        guideline_knowledge: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Pull ALL RSS, synopsis, and knowledge gaps from sections.

        No keyword filtering. The section IS the filter.
        """
        sections_data = guideline_knowledge.get("sections", {})
        rss_entries = []
        synopsis_parts = []
        kg_parts = []

        for sec_id in sections:
            sec = sections_data.get(sec_id, {})
            title = sec.get("sectionTitle", "")

            for rss in sec.get("rss", []):
                rss_entries.append({
                    "section": sec_id,
                    "sectionTitle": title,
                    "recNumber": rss.get("recNumber", ""),
                    "text": rss.get("text", ""),
                })

            synopsis = sec.get("synopsis", "")
            if synopsis:
                synopsis_parts.append(f"Section {sec_id} ({title}): {synopsis}")

            kg = sec.get("knowledgeGaps", "")
            if kg:
                kg_parts.append(f"Section {sec_id}: {kg}")

        return {
            "rss": rss_entries,
            "synopsis": "\n\n".join(synopsis_parts),
            "knowledge_gaps": "\n\n".join(kg_parts),
            "has_knowledge_gaps": bool(kg_parts),
            "sections": sections,
        }

    def score_sections_by_search_terms(
        self,
        sections: List[str],
        search_terms: List[str],
        recommendations_store: Dict[str, Any],
        guideline_knowledge: Dict[str, Any],
        min_matches: int = 2,
    ) -> List[str]:
        """
        Score sections by how many distinct search terms appear in their content.

        Searches rec text + RSS text for each section. Returns only sections
        that match at least `min_matches` distinct search terms, ranked by
        match count (most matches first).

        A section matching 1 search term (e.g. just "IVT") is coincidental.
        A section matching 3+ terms (e.g. "blood pressure", "SBP", "185") is
        genuinely relevant.
        """
        if not search_terms:
            return sections

        # Deduplicate synonyms: "IVT" + "thrombolysis" = 1 concept
        deduped = _deduplicate_by_synonyms(search_terms)
        terms_lower = [t.lower() for t in deduped]
        sections_data = guideline_knowledge.get("sections", {})
        section_scores: Dict[str, int] = {}

        for sec_id in sections:
            # Gather all text from this section: recs + RSS
            text_parts = []

            # Rec text
            for rec_id, rec in recommendations_store.items():
                if rec.get("section", "") == sec_id:
                    text_parts.append((rec.get("text", "") or "").lower())
                    text_parts.append((rec.get("sectionTitle", "") or "").lower())

            # RSS text
            sec = sections_data.get(sec_id, {})
            for rss in sec.get("rss", []):
                text_parts.append((rss.get("text", "") or "").lower())

            corpus = " ".join(text_parts)

            # Count distinct concepts found (synonyms already collapsed)
            matches = sum(1 for t in terms_lower if t in corpus)
            section_scores[sec_id] = matches

        # Filter to sections with enough matches, rank by count
        qualified = [
            (sec_id, count)
            for sec_id, count in section_scores.items()
            if count >= min_matches
        ]
        qualified.sort(key=lambda x: -x[1])

        result = [sec_id for sec_id, _ in qualified]

        logger.info(
            "Section search term scoring: %s → qualified=%s (min=%d)",
            {s: section_scores.get(s, 0) for s in sections},
            result,
            min_matches,
        )

        return result

    def rank_sections_by_search_terms(
        self,
        sections: List[str],
        search_terms: List[str],
        recommendations_store: Dict[str, Any],
        guideline_knowledge: Dict[str, Any],
    ) -> tuple:
        """
        Rank ALL sections by search term density. Returns the ranked list
        and the score dict so the caller can compare the LLM's pick against
        the best match.

        Returns:
            (ranked_section_ids, score_dict)
            ranked_section_ids: sections sorted by match count (highest first),
                                only those with ≥2 matches
            score_dict: {section_id: match_count} for all sections
        """
        if not search_terms:
            return sections, {}

        # Deduplicate synonyms: "IVT" + "thrombolysis" = 1 concept
        deduped = _deduplicate_by_synonyms(search_terms)
        terms_lower = [t.lower() for t in deduped]
        sections_data = guideline_knowledge.get("sections", {})
        section_scores: Dict[str, int] = {}

        for sec_id in sections:
            text_parts = []

            for rec_id, rec in recommendations_store.items():
                if rec.get("section", "") == sec_id:
                    text_parts.append((rec.get("text", "") or "").lower())

            sec = sections_data.get(sec_id, {})
            for rss in sec.get("rss", []):
                text_parts.append((rss.get("text", "") or "").lower())

            corpus = " ".join(text_parts)
            matches = sum(1 for t in terms_lower if _word_boundary_match(t, corpus))
            section_scores[sec_id] = matches

        qualified = [
            (sec_id, count)
            for sec_id, count in section_scores.items()
            if count >= 2
        ]
        qualified.sort(key=lambda x: -x[1])

        ranked = [sec_id for sec_id, _ in qualified]

        logger.info(
            "Section ranking: top=%s scores=%s",
            ranked[:5],
            {s: section_scores[s] for s in ranked[:5]} if ranked else {},
        )

        return ranked, section_scores

    def rank_sections_by_anchor_vocab(
        self,
        question: str,
        sections: List[str],
        recommendations_store: Dict[str, Any],
        guideline_knowledge: Dict[str, Any],
    ) -> tuple:
        """
        Anchor-count scoring against the closed canonical vocabulary.

        Rule (locked in transcript 2026-04-11 04:55–04:56 EDT, stated twice):
            "What if we get intent wrong? Matching as many keywords / anchor
             words will help. A section that matches 3 anchor words is
             probably more appropriate than a section that matches one
             anchor word."

        Differences from rank_sections_by_search_terms:

        1. Uses the closed canonical vocabulary built from
           synonym_dictionary.json and intent_map.json concept_expansions
           (loaded by qa_v3_filter.load_anchor_vocab). Free-text search
           terms from the LLM are NOT used here — generic English words
           cannot vote on routing because they are not in the vocabulary
           by construction.

        2. Synonym dedup is automatic via AnchorVocab.extract(): one hit
           per canonical term_id regardless of how many surface forms
           matched. "SBP" + "blood pressure" = 1, not 2.

        3. Anchors are first extracted from the USER'S QUESTION, then
           counted in each section's corpus. A section only scores for
           anchors the user actually mentioned. A section stacked with
           clinical terms unrelated to the question cannot win.

        Args:
            question: raw user question text
            sections: candidate section IDs to score
            recommendations_store: rec_id → rec dict
            guideline_knowledge: section_id → {"rss":[...], "synopsis":..., ...}

        Returns:
            (ranked_section_ids, score_dict)
            ranked_section_ids: sections sorted by anchor count desc,
                                only those with ≥1 anchor from the question
            score_dict: {section_id: anchor_count} for every input section

        This method is additive. It does not replace the existing scorers.
        Callers decide whether to use it as a cross-check on intent,
        an override when intent-routing scores 0, or a ranking tiebreaker.
        """
        if not question or not sections:
            return sections, {}

        # Lazy import to avoid a module-load cycle with services/.
        from app.agents.clinical.ais_clinical_engine.services.qa_v3_filter import (
            load_anchor_vocab,
        )

        # Build once per call. For hot paths the caller can cache a vocab
        # and pass it in via a thin wrapper; keeping the constructor
        # simple for now.
        vocab = load_anchor_vocab()

        # 1. Extract the canonical anchors the USER actually said,
        #    then collapse to family roots. The family-root rule
        #    (locked 2026-04-11) says SBP and "blood pressure" are
        #    the same anchor for counting purposes:
        #      "SBP and Blood pressure are the same if they are both
        #       matched that's not 2 they count as 1 match"
        #    Counting by family at the SECTION layer means a section
        #    mentioning SBP + DBP + "blood pressure" contributes one
        #    anchor (BP family), not three.
        question_raw = vocab.extract(question)
        question_families = set(vocab.distinct_families(question_raw))
        if not question_families:
            logger.info(
                "rank_sections_by_anchor_vocab: zero anchors in question "
                "%r — returning input order unchanged",
                question[:120],
            )
            return sections, {s: 0 for s in sections}

        sections_data = guideline_knowledge.get("sections", {})
        section_scores: Dict[str, int] = {}

        for sec_id in sections:
            parts: List[str] = []

            # Rec text for recs owned by this section (or children of it).
            for rec in recommendations_store.values():
                rec_section = rec.get("section", "") or ""
                if rec_section == sec_id or rec_section.startswith(sec_id + "."):
                    text = rec.get("text") or ""
                    if text:
                        parts.append(text)

            # RSS prose + synopsis + knowledge gaps for this section.
            sec = sections_data.get(sec_id, {}) or {}
            for rss in sec.get("rss", []) or []:
                rss_text = rss.get("text") or ""
                if rss_text:
                    parts.append(rss_text)
            synopsis = sec.get("synopsis") or ""
            if synopsis:
                parts.append(synopsis)
            kg = sec.get("knowledgeGaps") or ""
            if kg:
                parts.append(kg)

            corpus = "\n".join(parts)
            if not corpus:
                section_scores[sec_id] = 0
                continue

            # Canonical anchor families present in this section's corpus.
            corpus_raw = vocab.extract(corpus)
            corpus_families = set(vocab.distinct_families(corpus_raw))

            # Only credit the section for families the USER mentioned.
            matched = question_families & corpus_families
            section_scores[sec_id] = len(matched)

        # Rank sections with at least 1 matching family, highest first.
        qualified = [
            (sec_id, count)
            for sec_id, count in section_scores.items()
            if count >= 1
        ]
        qualified.sort(key=lambda x: -x[1])
        ranked = [sec_id for sec_id, _ in qualified]

        logger.info(
            "anchor_vocab ranking: question_families=%d top=%s scores=%s",
            len(question_families),
            ranked[:5],
            {s: section_scores.get(s, 0) for s in ranked[:5]},
        )
        return ranked, section_scores

    def get_section_title(self, sec_id: str) -> str:
        """Look up the human-readable title for a section ID."""
        def _search(section: Dict[str, Any]) -> Optional[str]:
            if section["id"] == sec_id:
                return section.get("title", "")
            for sub in section.get("subsections", []):
                result = _search(sub)
                if result is not None:
                    return result
            return None

        for section in self._section_map.get("sections", []):
            title = _search(section)
            if title is not None:
                return title
        return ""

    # ── Internal helpers ─────────────────────────────────────────────

    def _collect_section_ids(
        self, section: Dict[str, Any], ids: set
    ) -> None:
        ids.add(section["id"])
        for sub in section.get("subsections", []):
            self._collect_section_ids(sub, ids)

    def _prefer_specific(self, sections: List[str]) -> List[str]:
        """
        When both parent and child sections match (e.g., 4.7 and 4.7.3),
        prefer the more specific child.
        """
        if len(sections) <= 1:
            return sections

        to_remove = set()
        for s1 in sections:
            for s2 in sections:
                if s1 != s2 and s2.startswith(s1 + "."):
                    to_remove.add(s1)

        filtered = [s for s in sections if s not in to_remove]
        return filtered if filtered else sections
