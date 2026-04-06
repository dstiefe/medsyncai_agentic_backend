"""
Deterministic section router — maps LLM-parsed concepts to guideline sections.

Architecture:
    1. LLM parses question → dominant concept, qualifiers, intent
    2. THIS MODULE maps concepts → section IDs using reference files
    3. Orchestrator pulls ALL recs/RSS from matched sections
    4. Assembly LLM presents the data

This module does NOT understand natural language. It is a structured
lookup engine. The LLM does the understanding; this module does the
mapping.

Reference files used:
    - ais_guideline_section_map.json  — section routing_keywords
    - intent_map.json                 — concept expansions + groups
    - synonym_dictionary.json         — abbreviation → canonical term
    - data_dictionary.json            — subheadings within sections
    - section_variable_matrix.json    — variable types per section
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_REF_DIR = os.path.join(os.path.dirname(__file__), "references")


def _load_json(filename: str) -> Dict[str, Any]:
    path = os.path.join(_REF_DIR, filename)
    with open(path, "r") as f:
        return json.load(f)


class SectionRouter:
    """
    Resolves LLM-parsed concepts to guideline section IDs.

    The LLM outputs structured concepts (dominant topic, qualifiers).
    This router maps those concepts to specific sections using the
    reference infrastructure — no keyword searching, no scoring.
    """

    def __init__(self):
        self._section_map = _load_json("ais_guideline_section_map.json")
        self._intent_map = _load_json("intent_map.json")
        self._synonyms = _load_json("synonym_dictionary.json")
        self._data_dict = _load_json("data_dictionary.json")
        self._variable_matrix = _load_json("section_variable_matrix.json")

        # Build fast lookup: keyword → section IDs
        self._keyword_to_sections: Dict[str, List[str]] = {}
        self._build_keyword_index()

        # Build synonym → canonical mapping
        self._synonym_to_canonical: Dict[str, str] = {}
        self._build_synonym_index()

        logger.info(
            "SectionRouter: %d keyword entries, %d synonym entries",
            len(self._keyword_to_sections),
            len(self._synonym_to_canonical),
        )

    # ── Index builders ────────────────────────────────────────────────

    def _build_keyword_index(self) -> None:
        """Build keyword → [section_ids] from the section map."""
        for section in self._section_map.get("sections", []):
            self._index_section(section)

    def _index_section(self, section: Dict[str, Any]) -> None:
        sec_id = section["id"]
        for kw in section.get("routing_keywords", []):
            kw_lower = kw.lower()
            self._keyword_to_sections.setdefault(kw_lower, [])
            if sec_id not in self._keyword_to_sections[kw_lower]:
                self._keyword_to_sections[kw_lower].append(sec_id)
        for sub in section.get("subsections", []):
            self._index_section(sub)

    def _build_synonym_index(self) -> None:
        """Build abbreviation/synonym → canonical term mapping."""
        for abbrev, entry in self._synonyms.items():
            if abbrev == "metadata" or abbrev == "category_index":
                continue
            canonical = entry.get("full_term", abbrev).lower()
            self._synonym_to_canonical[abbrev.lower()] = canonical
            for syn in entry.get("synonyms", []):
                self._synonym_to_canonical[syn.lower()] = canonical

    # ── Public API ────────────────────────────────────────────────────

    def resolve(
        self,
        target_sections: Optional[List[str]] = None,
        dominant_concept: Optional[str] = None,
        qualifiers: Optional[List[str]] = None,
        search_keywords: Optional[List[str]] = None,
    ) -> List[str]:
        """
        Resolve to 1-3 guideline section IDs.

        Priority:
            1. LLM target_sections (if provided and valid)
            2. Concept intersection (dominant + qualifiers)
            3. Keyword-to-section mapping (search_keywords)

        Args:
            target_sections: LLM-suggested section IDs from Section Guide
            dominant_concept: main topic (e.g., "thrombectomy")
            qualifiers: narrowing terms (e.g., ["posterior circulation"])
            search_keywords: LLM-extracted search terms

        Returns:
            List of 1-3 section IDs, ordered by specificity
        """
        # Priority 1: LLM picked sections — verify against keywords
        if target_sections and search_keywords:
            validated = self._validate_sections(target_sections)
            verified = self._verify_llm_sections(validated, search_keywords)
            if verified:
                if qualifiers and len(verified) > 1:
                    narrowed = self._narrow_by_qualifiers(verified, qualifiers)
                    if narrowed:
                        return narrowed[:3]
                return verified[:3]
            else:
                # LLM drifted — all its sections failed verification.
                # Fall through to keyword-based resolution.
                logger.warning(
                    "LLM drift detected: sections %s have no keyword "
                    "overlap with %s — re-resolving from keywords",
                    validated, search_keywords,
                )

        # Priority 1b: LLM sections without keywords (can't verify, trust)
        if target_sections and not search_keywords:
            validated = self._validate_sections(target_sections)
            if validated:
                return validated[:3]

        # Priority 2: Concept intersection
        if dominant_concept:
            sections = self._resolve_by_concepts(
                dominant_concept, qualifiers or []
            )
            if sections:
                return sections[:3]

        # Priority 3: Search keywords → section mapping
        if search_keywords:
            sections = self._resolve_by_keywords(search_keywords)
            if sections:
                return sections[:3]

        return []

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

        # Order by COR strength, then by rec number
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

    # ── Internal resolution methods ───────────────────────────────────

    def _resolve_by_concepts(
        self, dominant: str, qualifiers: List[str],
    ) -> List[str]:
        """
        Find sections where the dominant concept AND all qualifiers
        coexist in routing keywords.
        """
        # Expand the dominant concept
        dominant_lower = dominant.lower()
        dominant_canonical = self._canonicalize(dominant_lower)
        dominant_sections = self._sections_for_concept(dominant_canonical)

        if not dominant_sections:
            # Try the original term if canonical didn't match
            dominant_sections = self._sections_for_concept(dominant_lower)

        if not dominant_sections:
            return []

        if not qualifiers:
            # No qualifiers — return most specific sections
            return self._prefer_specific(dominant_sections)

        # Intersect with qualifier sections
        result = set(dominant_sections)
        for qual in qualifiers:
            qual_canonical = self._canonicalize(qual.lower())
            qual_sections = self._sections_for_concept(qual_canonical)
            if not qual_sections:
                qual_sections = self._sections_for_concept(qual.lower())
            if qual_sections:
                intersection = result & set(qual_sections)
                if intersection:
                    result = intersection
                # If intersection is empty, qualifier doesn't narrow —
                # keep current result (qualifier might be within-section context)

        return self._prefer_specific(list(result))

    def _resolve_by_keywords(self, keywords: List[str]) -> List[str]:
        """Map search keywords to sections via routing_keywords index."""
        section_hits: Dict[str, int] = {}
        for kw in keywords:
            kw_canonical = self._canonicalize(kw.lower())
            for term in [kw_canonical, kw.lower()]:
                for sec_id in self._keyword_to_sections.get(term, []):
                    section_hits[sec_id] = section_hits.get(sec_id, 0) + 1

        if not section_hits:
            return []

        # Sort by hit count, prefer specific sections
        ranked = sorted(
            section_hits.items(),
            key=lambda x: (-x[1], -x[0].count(".")),
        )
        return [sec for sec, _ in ranked[:3]]

    def _sections_for_concept(self, concept: str) -> List[str]:
        """
        Find all sections that have this concept in their routing keywords.
        Also checks concept expansions and section hints from intent_map.
        """
        sections = set()

        # Direct keyword match
        for sec_id in self._keyword_to_sections.get(concept, []):
            sections.add(sec_id)

        # Check concept expansions in intent_map
        expansions = self._intent_map.get("concept_expansions", {})
        for concept_name, expansion in expansions.items():
            if concept_name.lower() == concept or concept in [
                s.lower() for s in expansion.get("synonyms", [])
            ]:
                # This concept matches — check if there's a section_hint
                if "section_hint" in expansion:
                    sections.add(expansion["section_hint"])
                # Also look up each expanded term
                for expanded in expansion.get("expands_to", []):
                    for sec_id in self._keyword_to_sections.get(
                        expanded.lower(), []
                    ):
                        sections.add(sec_id)

        # Check synonym dictionary for direct section mappings
        syn_entry = self._synonyms.get(concept, {})
        if not syn_entry:
            # Try uppercase/original casing
            for key, val in self._synonyms.items():
                if key.lower() == concept:
                    syn_entry = val
                    break
        if syn_entry and "sections" in syn_entry:
            for sec_id in syn_entry["sections"]:
                sections.add(sec_id)

        return list(sections)

    def _canonicalize(self, term: str) -> str:
        """Resolve synonyms/abbreviations to canonical term."""
        return self._synonym_to_canonical.get(term, term)

    def _verify_llm_sections(
        self,
        sections: List[str],
        search_keywords: List[str],
    ) -> List[str]:
        """
        Drift check: Python independently resolves sections from the
        LLM's keywords, then checks if the LLM's section picks overlap.
        Keeps LLM sections that Python also finds. Drops the rest.

        This is a consensus check: LLM proposes, Python cross-checks.
        If they agree, high confidence. If they diverge, trust Python.
        """
        if not search_keywords:
            return sections

        # Python's independent resolution from keywords
        python_sections = set(self._resolve_by_keywords(search_keywords))

        # Also expand: if Python finds 4.7, accept LLM's 4.7.3
        python_parents = set()
        for ps in python_sections:
            parts = ps.split(".")
            for i in range(1, len(parts)):
                python_parents.add(".".join(parts[:i]))

        verified = []
        for sec_id in sections:
            # LLM section matches Python's resolution
            if sec_id in python_sections:
                verified.append(sec_id)
            # LLM picked a child of a section Python found (e.g., 4.7.3 when Python found 4.7)
            elif any(sec_id.startswith(ps + ".") for ps in python_sections):
                verified.append(sec_id)
            # LLM picked a parent of a section Python found
            elif sec_id in python_parents:
                verified.append(sec_id)
            else:
                logger.info(
                    "Drift check: dropped %s (Python resolved %s from keywords %s)",
                    sec_id, sorted(python_sections), search_keywords,
                )

        return verified

    def _validate_sections(self, sections: List[str]) -> List[str]:
        """Validate that section IDs exist in the guideline."""
        valid_ids = set()
        for section in self._section_map.get("sections", []):
            self._collect_section_ids(section, valid_ids)

        # Also accept sections from the data dictionary
        for sec_id in self._data_dict.get("sections", {}):
            valid_ids.add(sec_id)

        return [s for s in sections if s in valid_ids]

    def _collect_section_ids(
        self, section: Dict[str, Any], ids: set
    ) -> None:
        ids.add(section["id"])
        for sub in section.get("subsections", []):
            self._collect_section_ids(sub, ids)

    def _narrow_by_qualifiers(
        self, sections: List[str], qualifiers: List[str],
    ) -> List[str]:
        """Narrow a section list by checking which sections contain qualifier concepts."""
        scored: Dict[str, int] = {}
        for sec_id in sections:
            score = 0
            sec_keywords = self._get_section_keywords(sec_id)
            for qual in qualifiers:
                qual_lower = qual.lower()
                qual_canonical = self._canonicalize(qual_lower)
                if qual_lower in sec_keywords or qual_canonical in sec_keywords:
                    score += 1
            scored[sec_id] = score

        max_score = max(scored.values()) if scored else 0
        if max_score > 0:
            return [s for s, sc in scored.items() if sc == max_score]
        return sections

    def _get_section_keywords(self, sec_id: str) -> set:
        """Get all routing_keywords for a section as a lowercase set."""
        keywords = set()

        def _search(section: Dict[str, Any]) -> None:
            if section["id"] == sec_id:
                for kw in section.get("routing_keywords", []):
                    keywords.add(kw.lower())
            for sub in section.get("subsections", []):
                _search(sub)

        for section in self._section_map.get("sections", []):
            _search(section)
        return keywords

    def _prefer_specific(self, sections: List[str]) -> List[str]:
        """
        When both parent and child sections match (e.g., 4.7 and 4.7.3),
        prefer the more specific child.
        """
        if len(sections) <= 1:
            return sections

        # Remove parents when their children are also present
        to_remove = set()
        for s1 in sections:
            for s2 in sections:
                if s1 != s2 and s2.startswith(s1 + "."):
                    to_remove.add(s1)

        filtered = [s for s in sections if s not in to_remove]
        return filtered if filtered else sections
