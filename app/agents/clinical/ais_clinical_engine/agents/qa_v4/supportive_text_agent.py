# ─── v4 (Q&A v4 namespace) ─────────────────────────────────────────────
# This file lives under agents/qa_v4/ and is the active v4 copy of the
# Guideline Q&A pipeline. The previous location agents/qa_v3/ has been
# archived to agents/_archive_qa_v3/ and is no longer imported anywhere.
# v4 changes: unified Step 1 pipeline — 44 intents from
# intent_content_source_map.json, anchor_terms as Dict[str, Any]
# (term → value/range), values_verified, rescoped clarification.
# ───────────────────────────────────────────────────────────────────────
"""
Supportive Text Agent — searches Recommendation-Specific Supportive Text (RSS).

Responsibilities:
    - Search guideline_knowledge.json for RSS entries matching the query
    - Search section synopses for additional context
    - Return raw text entries — the Assembly Agent decides how to summarize

This agent is purely deterministic — no LLM calls.
"""

from __future__ import annotations

from typing import Any, Dict, List

from .schemas import IntentResult, SupportiveTextEntry, SupportiveTextResult

# Import existing search function from qa_service
from ...services.qa_service import (
    score_text,
    search_knowledge_store,
)


class SupportiveTextAgent:
    """Searches RSS and synopsis content from the guideline knowledge store."""

    def __init__(self, guideline_knowledge: Dict[str, Any]):
        self._knowledge = guideline_knowledge

    def run(self, intent: IntentResult) -> SupportiveTextResult:
        """
        Search for supportive text matching the question.

        Args:
            intent: output from the IntentAgent

        Returns:
            SupportiveTextResult with RSS and synopsis entries
        """
        # Use the existing search_knowledge_store but filter to RSS + synopsis only
        max_results = 7 if intent.is_evidence_question else 5

        all_results = search_knowledge_store(
            self._knowledge,
            intent.search_terms,
            max_results=max_results,
            section_refs=intent.section_refs,
            topic_sections=intent.topic_sections,
        )

        entries: List[SupportiveTextEntry] = []
        for entry in all_results:
            entry_type = entry.get("type", "")
            if entry_type not in ("rss", "synopsis"):
                continue
            entries.append(
                SupportiveTextEntry(
                    section=entry.get("section", ""),
                    section_title=entry.get("sectionTitle", ""),
                    rec_number=str(entry.get("recNumber", "")),
                    text=entry.get("text", ""),
                    entry_type=entry_type,
                )
            )

        return SupportiveTextResult(
            entries=entries,
            has_content=bool(entries),
        )
