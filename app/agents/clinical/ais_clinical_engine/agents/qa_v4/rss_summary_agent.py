# ─── v4 (Q&A v4 namespace) ─────────────────────────────────────────────
# This file lives under agents/qa_v4/ and is the active v4 copy of the
# Guideline Q&A pipeline. The previous location agents/qa_v3/ has been
# archived to agents/_archive_qa_v3/ and is no longer imported anywhere.
# v4 changes: unified Step 1 pipeline — 38 intents from
# intent_content_source_map.json, flexible clinical_variables dict,
# anchor_terms, values_verified, rescoped clarification.
# ───────────────────────────────────────────────────────────────────────
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
        # Lazy-cached anchor vocabulary. Built on first filter call and
        # reused for the lifetime of this agent instance.
        self._vocab = None

    @property
    def is_available(self) -> bool:
        return self._client is not None

    def _get_vocab(self):
        """Load the closed canonical anchor vocabulary once per agent.

        The vocabulary is built from synonym_dictionary.json plus
        intent_map.json concept_expansions. Generic English words are
        excluded by construction because they are not in either source
        file. This is the closed vocabulary used by the Python filter
        that pre-screens RSS paragraphs before the LLM sees them.
        """
        if self._vocab is None:
            # Lazy import so startup does not depend on the services
            # package being importable at module-load time.
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

        # ── Anchor-survival pre-filter ──────────────────────────────
        # Drop RSS entries that don't mention any canonical anchor from
        # the user's question. Counts are family-aware (SBP and "blood
        # pressure" collapse to one). Never-starve: if the filter would
        # leave zero entries, fall back to the unfiltered list so the
        # LLM always has something to summarize.
        rss_only = self._anchor_survival_filter(question, rss_only)
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
                    "- Do NOT reference internal document structure (Table numbers, Figure numbers, "
                    "section numbers). Present the CONTENT, not the location. Say 'The guideline "
                    "defines clearly disabling deficits as...' NOT 'According to Table 4...'.\n"
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

    def _anchor_survival_filter(
        self,
        question: str,
        entries: List[SupportiveTextEntry],
    ) -> List[SupportiveTextEntry]:
        """Keep RSS entries whose text mentions at least one question anchor.

        Uses the closed canonical vocabulary so generic English words
        from the question never vote on survival. Entries are ranked by
        distinct anchor-family count descending — the RSS paragraph
        that mentions the most of the user's anchors appears first.

        Never-starve: if no entry survives, returns the input unchanged
        so the LLM still has the full pile to work with.
        """
        if not entries or not question:
            return entries

        # Reversibility flag — disabled = pass-through (pre-v3 behavior).
        from app.agents.clinical.ais_clinical_engine.services import qa_v3_flags
        if not qa_v3_flags.RSS_ANCHOR_FILTER:
            return entries

        try:
            from app.agents.clinical.ais_clinical_engine.services.qa_v3_filter import (
                filter_paragraphs_by_anchor_survival,
            )
            vocab = self._get_vocab()
        except Exception as e:
            logger.warning(
                "RSS anchor filter unavailable (%s) — passing through", e
            )
            return entries

        # Extract question anchors once. If the question contains no
        # canonical anchors at all, pass through unfiltered — this is
        # typically a very general / definitional question.
        question_anchors = vocab.extract(question)
        if not question_anchors:
            logger.info(
                "RSS anchor filter: 0 question anchors — passing through %d entries",
                len(entries),
            )
            return entries

        # Wrap each entry as a dict so the filter can read `text`,
        # keeping a back-reference so we can return dataclass instances.
        wrapped = [
            {"text": e.text, "_entry": e, "section": e.section, "rec_number": e.rec_number}
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
                "RSS anchor filter: 0/%d survived — falling back to unfiltered",
                len(entries),
            )
            return entries

        kept = [w["_entry"] for w, _hits in survivors]
        logger.info(
            "RSS anchor filter: kept %d/%d entries (q_anchors=%d)",
            len(kept), len(entries), len(question_anchors),
        )
        return kept
