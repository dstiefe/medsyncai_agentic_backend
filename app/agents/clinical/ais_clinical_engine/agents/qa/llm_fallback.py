"""
llm_fallback.py — Claude Sonnet general-knowledge responder for
questions that are NOT addressed by the 2026 AIS Guidelines.

The in-scope path returns byte-exact guideline recommendations. The
fallback path fires only when the LLM parser and deterministic parser
BOTH return out_of_scope — i.e. the question is real but the guideline
doesn't cover it. In that case, rather than a flat decline, we let
Claude answer from general clinical knowledge, with a hard disclaimer
stating the answer is NOT from the 2026 AIS Guidelines.

Three safety layers sit before this module:

1. `llm_deny_list.check_deny_list` blocks patient-specific treatment
   decisions before they ever reach this LLM.
2. The system prompt tells Claude explicitly that the answer will be
   rendered with a "NOT FROM THE GUIDELINES" banner and must be concise.
3. The orchestrator's response renderer ALWAYS prepends a banner and
   appends a footer disclaimer regardless of what the LLM produced.
   Provenance is a structural property, not just a text property.

This call is stateless — no conversation history, no prior turns. Each
fallback question is answered on its own so content from a previous
in-scope turn cannot leak into a general-knowledge answer.

Feature-flagged off by default. Enable with QA_LLM_FALLBACK_ENABLED=true.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Optional

from app import config
from app.shared.llm_client import get_llm_client

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Feature flag
# ---------------------------------------------------------------------------


def is_enabled() -> bool:
    """Return True if the LLM fallback feature flag is on."""
    return os.getenv("QA_LLM_FALLBACK_ENABLED", "false").lower() in (
        "1", "true", "yes", "on",
    )


# ---------------------------------------------------------------------------
# Disclaimer strings (used here and by the assembler)
# ---------------------------------------------------------------------------

FALLBACK_HEADER = (
    "⚠️  NOT FROM THE 2026 AIS GUIDELINES — GENERAL CLINICAL KNOWLEDGE"
)

FALLBACK_FOOTER = (
    "⚠️  This answer reflects general clinical knowledge, not the 2026 "
    "AHA/ASA AIS Guidelines. It should be verified against primary "
    "sources and your institution's protocols before acting on it."
)


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class FallbackResult:
    """Output of `fallback_answer`.

    - `answer`: the LLM's plain-English response, WITHOUT banners. The
      assembler wraps it with the header and footer at render time.
    - `ok`: True when the LLM produced a non-empty answer.
    - `latency_ms`, `input_tokens`, `output_tokens`: usage metadata.
    - `error`: short failure reason when ok is False.
    """

    answer: str = ""
    ok: bool = False
    latency_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------


_SYSTEM_PROMPT = """You are a clinical assistant answering a question that is NOT addressed by the 2026 AHA/ASA Acute Ischemic Stroke Guidelines.

The user interface will render your response with a clear banner stating the answer is NOT from the guidelines and should be verified against primary sources. You do NOT need to repeat that disclaimer — it will be shown separately.

RULES:
- Answer from general clinical knowledge in plain, concise language (3-6 sentences, max ~150 words).
- Stay on clinically relevant ground: pathophysiology, drug mechanisms, monitoring, related comorbidities, adjunct care, general clinical concepts.
- You MUST NOT make patient-specific treatment decisions, dosing recommendations, or decisions that should be governed by a guideline or institutional protocol. If the user is asking for one, say so and tell them to consult the guideline or their institution's protocol.
- You MUST NOT fabricate citations, trial names, or specific numerical thresholds. If you are uncertain, say you are uncertain.
- Do NOT contradict the 2026 AHA/ASA AIS Guidelines. If the question touches on anything that IS in the AIS guideline, note that the guideline should be the primary source.
- No preamble, no "great question", no hedging about your training data. Just answer.

OUTPUT: Return ONLY the plain-English answer. No JSON, no markdown headers, no banners.
"""


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


_MAX_ANSWER_CHARS = 1200  # ~150 words hard cap


async def fallback_answer(
    question: str,
    model: Optional[str] = None,
) -> FallbackResult:
    """
    Answer an out-of-scope question from general clinical knowledge.

    Never raises on LLM errors — returns `FallbackResult(ok=False,
    error=...)`. The orchestrator treats a failed fallback as "fall
    back to the canned OOS decline message".

    Args:
        question: the user's raw question. Stateless — no history is
            passed, by design, to prevent in-scope content from leaking
            across turns.
        model: Anthropic model slug. Defaults to DEFAULT_MODELS["anthropic"]
            (Sonnet).

    Returns:
        FallbackResult.
    """
    if not question or not question.strip():
        return FallbackResult(ok=False, error="empty_question")

    model = (
        model
        or os.getenv("QA_LLM_FALLBACK_MODEL")
        or config.DEFAULT_MODELS.get("anthropic")
    )

    messages = [{"role": "user", "content": question.strip()}]

    t0 = time.perf_counter()
    try:
        client = get_llm_client(provider="anthropic", model=model)
        result = await client.call(
            system_prompt=_SYSTEM_PROMPT,
            messages=messages,
            model=model,
            max_tokens=400,
        )
    except Exception as exc:  # noqa: BLE001 - bounded by graceful fallback
        logger.warning("llm_fallback: LLM call failed: %s", exc)
        return FallbackResult(
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
        return FallbackResult(
            ok=False,
            error="empty_answer",
            latency_ms=latency_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    if len(text) > _MAX_ANSWER_CHARS:
        text = text[: _MAX_ANSWER_CHARS].rstrip() + "..."

    return FallbackResult(
        answer=text,
        ok=True,
        latency_ms=latency_ms,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


__all__ = [
    "FALLBACK_FOOTER",
    "FALLBACK_HEADER",
    "FallbackResult",
    "fallback_answer",
    "is_enabled",
]
