"""
llm_summarizer.py — Claude Sonnet back-door for in-scope Q&A answers.

The summarizer turns a set of verbatim recommendations (pulled
deterministically from guideline_knowledge.json by the focused agent)
into a short plain-English reading aid. It is a READING AID, not the
answer — the authoritative answer is always the verbatim rec block
that the assembler renders below the summary.

Hard rules enforced in the system prompt and by the orchestrator's
rendering contract:

1. The LLM receives ONLY the verbatim recommendations that were
   pulled deterministically for this question. It never sees the
   guideline index, other sections, or anything else.
2. The LLM MUST NOT invent recommendations, citations, or clinical
   advice not present in the input recs.
3. The LLM MUST cite sections inline as §X.Y so the reader can match
   the summary sentence to a source block.
4. The summary is always followed by the verbatim source block in the
   final response, no matter what the LLM produced. If the summary
   drifts, the clinician can see the mismatch at a glance.
5. The summary is 2-3 sentences, max 80 words. Anything longer is
   truncated.

Feature-flagged off by default. Enable with QA_LLM_SUMMARIZER_ENABLED=true.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from app import config
from app.shared.llm_client import get_llm_client

from .schemas import CitationClaim, VnIntent

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Feature flag
# ---------------------------------------------------------------------------


def is_enabled() -> bool:
    """Return True if the LLM summarizer feature flag is on."""
    return os.getenv("QA_LLM_SUMMARIZER_ENABLED", "false").lower() in (
        "1", "true", "yes", "on",
    )


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class SummarizerResult:
    """Output of `summarize_recs`.

    - `summary`: the plain-English reading aid. Empty string on failure.
    - `ok`: True when the LLM produced a non-empty summary.
    - `latency_ms`, `input_tokens`, `output_tokens`: usage metadata.
    - `error`: short failure reason when ok is False.
    """

    summary: str = ""
    ok: bool = False
    latency_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------


_SYSTEM_PROMPT = """You are a clinical reading aid for a Q&A tool over the 2026 AHA/ASA Acute Ischemic Stroke Guidelines.

You will be given:
1. A clinician's question.
2. The EXACT recommendations that a deterministic search pulled from the guideline to answer it. Each recommendation is labeled with its section (e.g. §4.6.1) and rec number.

Your job is to write a short plain-English summary (2-3 sentences, max 80 words) that helps the clinician quickly understand what the recommendations say. The verbatim recommendations will be shown BELOW your summary, so you do not need to repeat them. Your summary is a reading aid, not the answer.

RULES:
- You MUST NOT invent recommendations, doses, COR/LOE labels, or clinical advice that are not explicitly in the input recommendations.
- You MUST NOT contradict any recommendation.
- You MUST cite sections inline in parentheses (e.g. "IV alteplase is recommended within 4.5 hours (§4.6).").
- If the recommendations do not fully answer the question, say so briefly.
- If the question asks about a specific detail (dose, time, threshold) that the recommendations don't mention, say "the recommendations don't specify".
- Plain clinical language. No hedging. No "based on the guidelines". Just say what the guidelines say.

OUTPUT: Return ONLY the summary text. No JSON, no markdown headers, no preamble.
"""


def _format_recs_for_prompt(citations: List[CitationClaim]) -> str:
    """Render the verbatim recs as a compact numbered list for the prompt."""
    lines: List[str] = []
    for i, c in enumerate(citations, start=1):
        text = (c.quote or "").strip()
        lines.append(f"{i}. §{c.section_id} Rec #{c.rec_number}: {text}")
    return "\n".join(lines)


def _build_user_message(
    question: str,
    citations: List[CitationClaim],
    intent: Optional[VnIntent],
) -> str:
    """Build the user message passed to Claude Sonnet."""
    intent_hint = (
        intent.value.replace("_", " ") if intent else "recommendation"
    )
    recs_block = _format_recs_for_prompt(citations)
    return (
        f"Clinician question ({intent_hint}): {question.strip()}\n\n"
        f"Verbatim recommendations pulled from the guideline:\n"
        f"{recs_block}\n\n"
        f"Write the plain-English summary now."
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


_MAX_SUMMARY_CHARS = 600  # ~80 words hard cap


async def summarize_recs(
    question: str,
    citations: List[CitationClaim],
    intent: Optional[VnIntent] = None,
    model: Optional[str] = None,
) -> SummarizerResult:
    """
    Produce a plain-English summary of the verbatim recommendations.

    Never raises on LLM errors — returns `SummarizerResult(ok=False,
    error=...)` instead. The orchestrator treats a failed summary as
    "just render the source block without a summary".

    Args:
        question: the clinician's question (already merged with any
            clarification context).
        citations: the verbatim citations the focused agent pulled.
        intent: the classified VnIntent, used only as a hint in the
            user message so the LLM knows what kind of answer to frame.
        model: Anthropic model slug. Defaults to DEFAULT_MODELS["anthropic"]
            (Sonnet).

    Returns:
        SummarizerResult.
    """
    if not citations:
        return SummarizerResult(
            ok=False,
            error="no_citations_to_summarize",
        )

    model = (
        model
        or os.getenv("QA_LLM_SUMMARIZER_MODEL")
        or config.DEFAULT_MODELS.get("anthropic")
    )

    user_message = _build_user_message(question, citations, intent)
    messages = [{"role": "user", "content": user_message}]

    t0 = time.perf_counter()
    try:
        client = get_llm_client(provider="anthropic", model=model)
        result = await client.call(
            system_prompt=_SYSTEM_PROMPT,
            messages=messages,
            model=model,
            max_tokens=300,
        )
    except Exception as exc:  # noqa: BLE001 - bounded by graceful fallback
        logger.warning("llm_summarizer: LLM call failed: %s", exc)
        return SummarizerResult(
            ok=False,
            error=f"llm_call_failed: {exc}",
            latency_ms=int((time.perf_counter() - t0) * 1000),
        )

    latency_ms = int((time.perf_counter() - t0) * 1000)
    usage = result.get("usage") or {}
    input_tokens = usage.get("input_tokens", 0)
    output_tokens = usage.get("output_tokens", 0)

    text = (result.get("content") or "").strip()
    if not text:
        return SummarizerResult(
            ok=False,
            error="empty_summary",
            latency_ms=latency_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    # Hard cap — the source block is the authoritative content.
    if len(text) > _MAX_SUMMARY_CHARS:
        text = text[: _MAX_SUMMARY_CHARS].rstrip() + "..."

    return SummarizerResult(
        summary=text,
        ok=True,
        latency_ms=latency_ms,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


__all__ = [
    "SummarizerResult",
    "is_enabled",
    "summarize_recs",
]
