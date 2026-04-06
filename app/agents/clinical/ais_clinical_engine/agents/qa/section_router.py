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

import json
import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_REF_DIR = os.path.join(os.path.dirname(__file__), "references")

# Clinically linked sections that should be pulled together.
# When the primary section is resolved, related sections are also
# included so the LLM has the full clinical picture.
# Key = primary section, Value = list of related sections to include.
RELATED_SECTIONS: Dict[str, List[str]] = {
    "2.3": ["2.4"],       # Prehospital Assessment ↔ EMS Destination
    "2.4": ["2.3"],       # EMS Destination ↔ Prehospital Assessment
    "4.6.1": ["4.6.2"],   # IVT Decision-Making ↔ IVT Agent Selection
    "4.6.2": ["4.6.1", "4.3", "4.8", "5.1", "6.1"],  # Post-IVT: agent selection + BP + antiplatelets + stroke units + brain swelling
    "4.3": ["4.7.4", "5.1", "6.1"],   # Post-EVT: BP mgmt + EVT techniques + stroke units + brain swelling
    "4.7.1": ["4.7.2"],   # EVT + IVT ↔ EVT Adult Patients
    "4.7.2": ["4.7.1"],   # EVT Adult Patients ↔ EVT + IVT
    "4.10": ["4.11"],     # Volume Expansion ↔ Neuroprotection
    "4.11": ["4.10"],     # Neuroprotection ↔ Volume Expansion
}


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

        # Build result: primary section + any clinically related sections
        result = [primary]
        related = RELATED_SECTIONS.get(primary, [])
        for rel in related:
            if rel not in result:
                result.append(rel)

        if related:
            logger.info("Topic '%s' → sections %s (primary=%s, related=%s)",
                        topic, result, primary, related)
        else:
            logger.info("Topic '%s' → section %s", topic, primary)

        return result

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
