# ─── v4 (Q&A v4 namespace) ─────────────────────────────────────────────
# This file lives under agents/qa_v4/ and is the active v4 copy of the
# Guideline Q&A pipeline. The previous location agents/qa_v3/ has been
# archived to agents/_archive_qa_v3/ and is no longer imported anywhere.
# v4 changes: unified Step 1 pipeline — 38 intents from
# intent_content_source_map.json, flexible clinical_variables dict,
# anchor_terms, values_verified, rescoped clarification.
# ───────────────────────────────────────────────────────────────────────
"""
Knowledge Gap Agent — searches Knowledge Gaps and Future Research content.

Responsibilities:
    - Search guideline_knowledge.json for knowledge gap entries
    - Return deterministic "no gaps documented" when section has none (61/62 sections)
    - Return raw KG text for Assembly Agent to summarize when gaps exist

This agent is purely deterministic — no LLM calls.
"""

from __future__ import annotations

from typing import Any, Dict, List

from .schemas import IntentResult, KnowledgeGapEntry, KnowledgeGapResult

# Import existing search function from qa_service
from ...services.qa_service import search_knowledge_store


class KnowledgeGapAgent:
    """Searches knowledge gaps from the guideline knowledge store."""

    def __init__(self, guideline_knowledge: Dict[str, Any]):
        self._knowledge = guideline_knowledge

    def run(self, intent: IntentResult) -> KnowledgeGapResult:
        """
        Search for knowledge gaps matching the question.

        Args:
            intent: output from the IntentAgent

        Returns:
            KnowledgeGapResult — may contain a deterministic "no gaps" response
        """
        target_sections = intent.section_refs or intent.topic_sections

        # Check target sections for knowledge gaps directly
        if target_sections:
            return self._search_target_sections(target_sections)

        # Fallback: use keyword search across all sections
        return self._keyword_search(intent)

    def _search_target_sections(self, target_sections: List[str]) -> KnowledgeGapResult:
        """Check specific sections for knowledge gaps."""
        sections_data = self._knowledge.get("sections", {})
        entries: List[KnowledgeGapEntry] = []

        for sec_num in target_sections:
            sec = sections_data.get(sec_num, {})
            kg = sec.get("knowledgeGaps", "").strip()
            if kg:
                entries.append(
                    KnowledgeGapEntry(
                        section=sec_num,
                        section_title=sec.get("sectionTitle", ""),
                        text=kg,
                    )
                )

        if not entries:
            # No gaps documented — build deterministic response
            sec_titles = []
            for s in target_sections:
                sd = sections_data.get(s, {})
                if sd.get("sectionTitle"):
                    sec_titles.append(f"{s} ({sd['sectionTitle']})")
            sec_label = ", ".join(sec_titles) if sec_titles else ", ".join(target_sections)

            return KnowledgeGapResult(
                entries=[],
                has_gaps=False,
                deterministic_response=(
                    f"No specific knowledge gaps are documented in the 2026 AHA/ASA AIS "
                    f"guideline for Section {sec_label}. The guideline does not identify "
                    f"explicit areas of uncertainty or future research needs for this topic."
                ),
            )

        return KnowledgeGapResult(entries=entries, has_gaps=True)

    def _keyword_search(self, intent: IntentResult) -> KnowledgeGapResult:
        """Search all sections by keyword when no specific section is targeted."""
        all_results = search_knowledge_store(
            self._knowledge,
            intent.search_terms,
            max_results=5,
            section_refs=intent.section_refs,
            topic_sections=intent.topic_sections,
        )

        entries: List[KnowledgeGapEntry] = []
        for entry in all_results:
            if entry.get("type") != "knowledge_gaps":
                continue
            entries.append(
                KnowledgeGapEntry(
                    section=entry.get("section", ""),
                    section_title=entry.get("sectionTitle", ""),
                    text=entry.get("text", ""),
                )
            )

        return KnowledgeGapResult(
            entries=entries,
            has_gaps=bool(entries),
        )
