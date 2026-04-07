"""
RSS Summary Agent — Step 5b of the Guideline Q&A pipeline.

Receives verbatim Recommendation-Specific Supportive Text (RSS) from Python.
Summarizes the supporting evidence relevant to the question.

RULES:
    - Summarize only. No interpretation, no paraphrasing, no outside knowledge.
    - Cut down volume to what's relevant to the question.
    - Preserve trial names, numbers, and clinical findings exactly.
    - If asked about evidence for rec X, focus on RSS entries for rec X.

Input:
    - The question + Step 1 JSON (intent, topic, search_terms)
    - All RSS entries from the resolved sections (verbatim from Python)

Output:
    - A concise summary of the relevant supporting evidence
"""

from __future__ import annotations

import json
import logging
import re
from typing import List, Optional

from .schemas import SupportiveTextEntry

logger = logging.getLogger(__name__)


class RSSSummaryAgent:
    """
    Summarizes RSS text relevant to the clinician's question.

    Does NOT interpret, paraphrase, or add outside knowledge.
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
        rss_entries: List[SupportiveTextEntry],
        selected_rec_numbers: Optional[List[str]] = None,
    ) -> str:
        """
        Summarize RSS entries relevant to the question.

        Args:
            question: original clinician question
            intent: the classified intent
            question_summary: plain-language restatement
            rss_entries: all RSS entries from resolved sections
            selected_rec_numbers: rec IDs selected by RecSelectionAgent
                (used to prioritize RSS for those recs)

        Returns:
            Summary string. Empty string if no relevant RSS or LLM unavailable.
        """
        if not self.is_available or not rss_entries:
            return ""

        # Filter to RSS entries only (skip synopsis for now)
        rss_only = [e for e in rss_entries if e.entry_type == "rss"]
        if not rss_only:
            return ""

        # Build RSS blocks for the LLM
        rss_blocks = []
        for entry in rss_only:
            block = (
                f"Section {entry.section}, Rec {entry.rec_number} "
                f"({entry.section_title}):\n{entry.text}"
            )
            rss_blocks.append(block)

        rss_text = "\n\n".join(rss_blocks)

        # Cap context to avoid overwhelming the LLM
        if len(rss_text) > 12000:
            rss_text = rss_text[:12000] + "\n[...truncated]"

        selected_context = ""
        if selected_rec_numbers:
            selected_context = (
                f"\nThe recommendations selected as relevant to this question are: "
                f"{', '.join(selected_rec_numbers)}. "
                f"Prioritize the supporting text for these recommendations.\n"
            )

        try:
            response = self._client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=600,
                system=(
                    "You are a clinical evidence summarizer for the 2026 AHA/ASA AIS Guidelines.\n\n"
                    "You will be given a clinician's question and the Recommendation-Specific "
                    "Supportive Text (RSS) from the guideline.\n\n"
                    "Your job: summarize the supporting evidence that is relevant to the question.\n\n"
                    "RULES (strict):\n"
                    "- Summarize ONLY from the provided text. No outside knowledge. Ever.\n"
                    "- Do NOT interpret or draw conclusions. Just condense.\n"
                    "- Preserve trial names exactly (e.g., NINDS, ECASS, AcT, TRUTH).\n"
                    "- Preserve specific numbers, percentages, and statistical findings exactly.\n"
                    "- Preserve hedging language ('may', 'suggests', 'insufficient evidence').\n"
                    "- If the RSS text does not contain evidence relevant to the question, "
                    "say 'No specific supporting evidence in the provided text for this question.'\n"
                    "- Keep it concise — 2-4 sentences for most questions.\n"
                    "- No markdown formatting. Plain text only.\n"
                ),
                messages=[{
                    "role": "user",
                    "content": (
                        f"Question: {question}\n"
                        f"Intent: {intent}\n"
                        f"Summary: {question_summary}\n"
                        f"{selected_context}\n"
                        f"Supporting Text (RSS):\n{rss_text}\n\n"
                        "Summarize the relevant supporting evidence."
                    ),
                }],
            )

            for block in response.content:
                if hasattr(block, "text"):
                    summary = block.text.strip()
                    logger.info(
                        "RSSSummaryAgent: %d chars from %d entries",
                        len(summary), len(rss_only),
                    )
                    return summary

        except Exception as e:
            logger.error("RSSSummaryAgent failed: %s", e)

        return ""
