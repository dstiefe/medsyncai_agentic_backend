# ─── v4 (Q&A v4 namespace) ─────────────────────────────────────────────
# This file lives under agents/qa_v4/ and is the active v4 copy of the
# Guideline Q&A pipeline. The previous location agents/qa_v3/ has been
# archived to agents/_archive_qa_v3/ and is no longer imported anywhere.
# v4 changes: unified Step 1 pipeline — 38 intents from
# intent_content_source_map.json, flexible clinical_variables dict,
# anchor_terms, values_verified, rescoped clarification.
# ───────────────────────────────────────────────────────────────────────
"""
Knowledge Gap Summary Agent — Step 5c of the Guideline Q&A pipeline.

Receives verbatim Knowledge Gaps / Future Research text from Python.
Summarizes the gaps relevant to the question.

RULES:
    - Summarize only. No interpretation, no outside knowledge.
    - Preserve specific research questions and methodological gaps exactly.
    - If no knowledge gaps exist for the section, return empty string
      (the orchestrator handles the deterministic "no gaps" response).

Input:
    - The question + Step 1 JSON (intent, topic, search_terms)
    - All knowledge gap entries from the resolved sections (verbatim from Python)

Output:
    - A concise summary of the relevant knowledge gaps / future research needs
"""

from __future__ import annotations

import logging
from typing import List, Optional

from .schemas import KnowledgeGapEntry

logger = logging.getLogger(__name__)


class KGSummaryAgent:
    """
    Summarizes knowledge gap text relevant to the clinician's question.

    Does NOT interpret or add outside knowledge.
    Selects and condenses from the verbatim text Python provided.
    """

    def __init__(self, nlp_client=None):
        self._client = nlp_client
        # Lazy-cached anchor vocabulary for the per-question survival
        # filter. Built on first use and reused for the agent lifetime.
        self._vocab = None

    @property
    def is_available(self) -> bool:
        return self._client is not None

    def _get_vocab(self):
        if self._vocab is None:
            from app.agents.clinical.ais_clinical_engine.services.qa_v3_filter import (
                load_anchor_vocab,
            )
            self._vocab = load_anchor_vocab()
        return self._vocab

    async def summarize(
        self,
        question: str,
        intent: str,
        question_summary: str,
        kg_entries: List[KnowledgeGapEntry],
    ) -> str:
        """
        Summarize knowledge gap entries relevant to the question.

        Args:
            question: original clinician question
            intent: the classified intent
            question_summary: plain-language restatement
            kg_entries: all knowledge gap entries from resolved sections

        Returns:
            Summary string. Empty string if no KG entries or LLM unavailable.
        """
        if not self.is_available or not kg_entries:
            return ""

        # ── Anchor-survival pre-filter ──────────────────────────────
        # Drop KG entries that don't mention any canonical anchor from
        # the question. Never-starve: if the filter would return zero,
        # fall back to the unfiltered list.
        kg_entries = self._anchor_survival_filter(question, kg_entries)
        if not kg_entries:
            return ""

        # Build KG blocks for the LLM
        kg_blocks = []
        for entry in kg_entries:
            block = (
                f"Section {entry.section} ({entry.section_title}):\n"
                f"{entry.text}"
            )
            kg_blocks.append(block)

        kg_text = "\n\n".join(kg_blocks)

        # Cap context
        if len(kg_text) > 8000:
            kg_text = kg_text[:8000] + "\n[...truncated]"

        try:
            response = self._client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=400,
                system=(
                    "You are a clinical evidence summarizer for the 2026 AHA/ASA AIS Guidelines.\n\n"
                    "You will be given a clinician's question and the Knowledge Gaps / Future "
                    "Research text from the guideline.\n\n"
                    "Your job: summarize the knowledge gaps that are relevant to the question.\n\n"
                    "RULES (strict):\n"
                    "- Summarize ONLY from the provided text. No outside knowledge. Ever.\n"
                    "- Do NOT interpret or draw conclusions. Just condense.\n"
                    "- Preserve specific research questions exactly as stated.\n"
                    "- Preserve methodological gaps (e.g., 'no RCTs', 'limited data').\n"
                    "- If the KG text does not contain gaps relevant to the question, "
                    "say 'No specific knowledge gaps in the provided text for this question.'\n"
                    "- Keep it concise — 2-3 sentences for most questions.\n"
                    "- No markdown formatting. Plain text only.\n"
                ),
                messages=[{
                    "role": "user",
                    "content": (
                        f"Question: {question}\n"
                        f"Intent: {intent}\n"
                        f"Summary: {question_summary}\n\n"
                        f"Knowledge Gaps / Future Research:\n{kg_text}\n\n"
                        "Summarize the relevant knowledge gaps."
                    ),
                }],
            )

            for block in response.content:
                if hasattr(block, "text"):
                    summary = block.text.strip()
                    logger.info(
                        "KGSummaryAgent: %d chars from %d entries",
                        len(summary), len(kg_entries),
                    )
                    return summary

        except Exception as e:
            logger.error("KGSummaryAgent failed: %s", e)

        return ""

    def _anchor_survival_filter(
        self,
        question: str,
        entries: List[KnowledgeGapEntry],
    ) -> List[KnowledgeGapEntry]:
        """Keep KG entries whose text mentions at least one question anchor.

        Same rules as the RSS filter: closed canonical vocabulary,
        family-aware distinct counting, never-starve fallback when no
        entries survive or when the question contains zero anchors.
        """
        if not entries or not question:
            return entries

        # Reversibility flag — disabled = pass-through (pre-v3 behavior).
        from app.agents.clinical.ais_clinical_engine.services import qa_v3_flags
        if not qa_v3_flags.KG_ANCHOR_FILTER:
            return entries

        try:
            from app.agents.clinical.ais_clinical_engine.services.qa_v3_filter import (
                filter_paragraphs_by_anchor_survival,
            )
            vocab = self._get_vocab()
        except Exception as e:
            logger.warning(
                "KG anchor filter unavailable (%s) — passing through", e
            )
            return entries

        question_anchors = vocab.extract(question)
        if not question_anchors:
            logger.info(
                "KG anchor filter: 0 question anchors — passing through %d entries",
                len(entries),
            )
            return entries

        wrapped = [
            {"text": e.text, "_entry": e, "section": e.section}
            for e in entries
        ]

        survivors = filter_paragraphs_by_anchor_survival(
            paragraphs=wrapped,
            vocab=vocab,
            question_anchors=question_anchors,
            min_anchors=1,
        )

        if not survivors:
            logger.info(
                "KG anchor filter: 0/%d survived — falling back to unfiltered",
                len(entries),
            )
            return entries

        kept = [w["_entry"] for w, _hits in survivors]
        logger.info(
            "KG anchor filter: kept %d/%d entries (q_anchors=%d)",
            len(kept), len(entries), len(question_anchors),
        )
        return kept
