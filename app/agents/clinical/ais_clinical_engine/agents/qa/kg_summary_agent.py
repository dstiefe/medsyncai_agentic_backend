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

    @property
    def is_available(self) -> bool:
        return self._client is not None

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
