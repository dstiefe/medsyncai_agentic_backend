"""
Recommendation Selection Agent — Step 5a of the Guideline Q&A pipeline.

Receives ALL recommendations from the resolved sections (verbatim from Python).
Picks which ones answer the clinician's question.
Does NOT summarize, paraphrase, or interpret. Just selects.

Input:
    - The question + Step 1 JSON (intent, topic, search_terms)
    - All recommendations from the resolved sections (verbatim)

Output:
    - List of recommendation numbers that answer the question
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from .schemas import ScoredRecommendation
from ...services.qa_v3_filter import (
    AnchorVocab,
    filter_recs_by_anchor_survival,
    load_anchor_vocab,
)

logger = logging.getLogger(__name__)

# Module-level cache: built once per process. Vocab is derived from static
# JSON files so it does not need to be rebuilt per request.
_ANCHOR_VOCAB: Optional[AnchorVocab] = None


def _get_vocab() -> AnchorVocab:
    global _ANCHOR_VOCAB
    if _ANCHOR_VOCAB is None:
        _ANCHOR_VOCAB = load_anchor_vocab()
    return _ANCHOR_VOCAB


def _anchor_prefilter(
    question: str,
    recs: List[ScoredRecommendation],
) -> Tuple[List[ScoredRecommendation], List[str], List[str]]:
    """Deterministic anchor-count survival pre-filter before the LLM selector.

    Rules (locked during 2026-04-10/11 design work):
      - Extract canonical anchors from the user's question against the
        closed vocabulary (synonym_dictionary.json + intent_map.json
        concept_expansions).
      - Generic English words are not anchors.
      - Keep a rec only if its text contains >=1 distinct anchor from the
        question.
      - Rank survivors by distinct-anchor count desc, COR strength as
        tiebreaker.

    Safety fallbacks:
      - If the question yields zero anchors (too short/generic), return
        the recs unchanged. The LLM selector will still see all recs and
        behavior matches the pre-v3 path.
      - If the filter drops every rec, return the recs unchanged and log
        it as a warning. Empty survival is a clarification trigger in the
        future, not a dead end here.

    Returns:
        (filtered_recs, question_anchors, matched_anchors_per_rec_flat)
    """
    if not recs:
        return recs, [], []

    try:
        vocab = _get_vocab()
    except Exception as e:  # pragma: no cover — vocab load is file I/O
        logger.warning("Anchor vocab load failed, skipping pre-filter: %s", e)
        return recs, [], []

    question_anchors = vocab.extract(question or "")
    if not question_anchors:
        logger.info("Anchor pre-filter: question yielded zero anchors, passing %d recs through", len(recs))
        return recs, [], []

    survivors = filter_recs_by_anchor_survival(
        recs, vocab, question_anchors=question_anchors, min_anchors=1
    )
    if not survivors:
        logger.warning(
            "Anchor pre-filter: %d question anchors but no rec survived. "
            "Falling back to unfiltered rec list. anchors=%s",
            len(question_anchors), question_anchors,
        )
        return recs, question_anchors, []

    filtered: List[ScoredRecommendation] = [rec for rec, _hits in survivors]
    flat_hits: List[str] = []
    for _rec, hits in survivors:
        flat_hits.extend(hits)

    logger.info(
        "Anchor pre-filter: %d -> %d recs (question_anchors=%s)",
        len(recs), len(filtered), question_anchors,
    )
    return filtered, question_anchors, flat_hits


class RecSelectionAgent:
    """
    Picks which recommendations answer the clinician's question.

    The LLM sees all recs from the resolved sections and returns
    the rec numbers that are relevant. The recs themselves are
    never modified — they flow through verbatim.
    """

    def __init__(self, nlp_client=None):
        self._client = nlp_client

    @property
    def is_available(self) -> bool:
        return self._client is not None

    async def select(
        self,
        question: str,
        intent: str,
        question_summary: str,
        recs: List[ScoredRecommendation],
    ) -> List[str]:
        """
        Select which recommendations answer the question.

        Args:
            question: original clinician question
            intent: the classified intent (e.g., "threshold_target")
            question_summary: plain-language restatement
            recs: all recommendations from resolved sections

        Returns:
            List of rec identifiers (e.g., ["4.3-5", "4.3-7"]) that
            answer the question. Empty list if none are relevant.
        """
        if not self.is_available or not recs:
            # Fallback: return all recs (let assembly handle it)
            return [f"{r.section}-{r.rec_number}" for r in recs]

        # Deterministic anchor-count survival pre-filter (v3 rule).
        # Narrows the rec list the LLM selector sees so it cannot be
        # confused by 14 recs of 4.6.1 when only 3 actually match the
        # question's anchors. Safe fallback to unfiltered list when the
        # question has no anchors or when nothing survives.
        recs, question_anchors, _hits = _anchor_prefilter(question, recs)

        # Build rec blocks for the LLM
        rec_blocks = []
        for r in recs:
            rec_blocks.append(
                f"[{r.section}-{r.rec_number}] "
                f"Section {r.section}: {r.section_title}\n"
                f"COR: {r.cor} | LOE: {r.loe}\n"
                f"{r.text}"
            )

        rec_text = "\n\n".join(rec_blocks)

        try:
            response = self._client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=300,
                system=(
                    "You are a recommendation selector for the 2026 AHA/ASA AIS Guidelines.\n\n"
                    "You will be given a clinician's question and a list of guideline recommendations.\n"
                    "Your ONLY job: pick which recommendations answer the question and rank them "
                    "by how directly they answer it.\n\n"
                    "RULES:\n"
                    "- Return ONLY the IDs of recommendations that answer the question.\n"
                    "- ORDER MATTERS: put the most directly relevant recommendation FIRST. "
                    "The first rec in the array should be the one that most directly answers "
                    "the clinician's question. The rest follow in decreasing relevance.\n"
                    "- Read ALL recommendations before selecting — the best answer may not be first in the list.\n"
                    "- Think about what the clinician is really asking. For 'Can I give tPA to a patient on aspirin?', "
                    "the rec saying 'IVT is recommended for patients on antiplatelet therapy' is the direct answer, "
                    "even though 'aspirin' and 'antiplatelet' are different words.\n"
                    "- Include related recs that a clinician would need alongside the primary answer "
                    "(e.g., safety warnings, timing constraints for the same treatment).\n"
                    "- Be STRICT: exclude recs that merely mention a keyword from the question "
                    "but answer a different clinical question. For example, if the question is "
                    "'Should I give tPA within 3 hours?', a rec about telemedicine systems or "
                    "imaging protocols for transfers is NOT relevant even though it mentions IVT. "
                    "Only include recs that directly help the clinician decide about the specific "
                    "action they are asking about.\n"
                    "- If NO recommendations answer the question, return an empty array.\n\n"
                    "RESPONSE FORMAT:\n"
                    'Return JSON: {"selected": ["4.6.1-9", "4.8-17"]}\n'
                    "Array of rec IDs, ordered by relevance (most relevant first). Nothing else."
                ),
                messages=[{
                    "role": "user",
                    "content": (
                        f"Question: {question}\n"
                        f"Intent: {intent}\n"
                        f"Summary: {question_summary}\n\n"
                        f"Recommendations:\n{rec_text}\n\n"
                        "Return JSON with selected rec IDs."
                    ),
                }],
            )

            for block in response.content:
                if hasattr(block, "text"):
                    raw = block.text.strip()
                    if raw.startswith("```"):
                        raw = re.sub(r"^```(?:json)?\s*", "", raw)
                        raw = re.sub(r"\s*```$", "", raw)
                        raw = raw.strip()
                    try:
                        result = json.loads(raw)
                        selected = result.get("selected", [])
                        logger.info(
                            "RecSelectionAgent: %d/%d recs selected: %s",
                            len(selected), len(recs), selected,
                        )
                        return selected
                    except json.JSONDecodeError:
                        logger.warning("RecSelectionAgent: invalid JSON: %s", raw[:200])

        except Exception as e:
            logger.error("RecSelectionAgent failed: %s", e)

        # Fallback: return all recs
        return [f"{r.section}-{r.rec_number}" for r in recs]
