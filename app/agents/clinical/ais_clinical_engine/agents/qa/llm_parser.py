"""
llm_parser.py — Claude Haiku front-door for the v2 Q&A pipeline.

The LLM parser is a bounded query translator. It reads the user's
question and the four scaffolding files, and returns a ParsedQAQueryV2.
It never generates answer text and never sees guideline_knowledge.json.

Design constraints (enforced here and re-checked by the schema validator):

1. The LLM MUST pick `intent` from the 33 entries in intent_catalog.json.
2. The LLM MUST pick every `section` from the dd.v2 section index.
3. The LLM MUST normalize slang/aliases to the canonical terms in
   synonym_dictionary.v2.reverse_index.
4. The LLM MUST NOT paraphrase recommendation text; it never sees any.
5. If the question is not covered by the scaffolding, the LLM MUST
   return `intent: "out_of_scope"` with a reason. The orchestrator will
   then route to the general-knowledge fallback with a disclaimer.

The LLM receives the scaffolding as pre-rendered prompt sections that
are built once at module import and cached. Anthropic prompt caching
is enabled on the scaffolding blocks so repeat calls pay ~10% of the
initial cost.

Feature-flagged off by default. Enable with QA_LLM_PARSER_ENABLED=true.
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app import config
from app.shared.llm_client import get_llm_client

from .scaffolding_loader import ScaffoldingBundle, get_scaffolding
from .schemas import ParsedQAQueryV2, VnIntent

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Feature flag
# ---------------------------------------------------------------------------

def is_enabled() -> bool:
    """Return True if the LLM parser feature flag is on."""
    return os.getenv("QA_LLM_PARSER_ENABLED", "false").lower() in (
        "1", "true", "yes", "on",
    )


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class LLMParseResult:
    """Output of `parse_with_llm`.

    - `parsed`: a ParsedQAQueryV2 when the LLM successfully classified,
      even when the classification is out_of_scope. None only on hard
      failure (API error, malformed JSON, validation failure).
    - `is_out_of_scope`: convenience flag mirroring parsed.intent.
    - `confidence`: the LLM's self-reported confidence 0.0-1.0.
    - `raw_json`: the unvalidated JSON the LLM produced, for audit.
    - `latency_ms`, `input_tokens`, `output_tokens`: usage metadata.
    - `error`: short failure reason when parsed is None.
    """

    parsed: Optional[ParsedQAQueryV2]
    is_out_of_scope: bool = False
    confidence: float = 0.0
    raw_json: Dict[str, Any] = field(default_factory=dict)
    latency_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Pre-rendered prompt sections (built once at import, reused on every call)
# ---------------------------------------------------------------------------


def _render_intent_menu(bundle: ScaffoldingBundle) -> str:
    """Render every intent in intent_catalog.json as a compact menu."""
    lines: List[str] = ["=== INTENT MENU (choose exactly one) ==="]
    intents = bundle.intent_catalog.get("intents", {})
    for name in sorted(intents.keys()):
        entry = intents[name]
        desc = (entry.get("description") or "").strip().replace("\n", " ")
        required = entry.get("required_slots") or []
        answer_shape = entry.get("answer_shape") or ""
        examples = entry.get("examples") or []
        example_str = (
            " | ".join(str(e) for e in examples[:3]) if examples else ""
        )
        lines.append(f"- {name}")
        lines.append(f"    description: {desc[:300]}")
        if required:
            lines.append(f"    required_slots: {required}")
        if answer_shape:
            lines.append(f"    answer_shape: {answer_shape}")
        if example_str:
            lines.append(f"    examples: {example_str[:300]}")
    lines.append("")
    lines.append(
        "If the question is not addressed by any of the above intents, "
        "return intent = 'out_of_scope'."
    )
    return "\n".join(lines)


def _render_topic_map(bundle: ScaffoldingBundle) -> str:
    """Render every topic in guideline_topic_map.json as a routing table."""
    lines: List[str] = ["=== TOPIC -> SECTION ROUTING TABLE ==="]
    topics = bundle.topic_map.get("topics", [])
    for t in topics:
        topic = t.get("topic") or ""
        section = t.get("section") or ""
        addresses = (t.get("addresses") or "").strip().replace("\n", " ")
        lines.append(f"- topic: {topic}")
        lines.append(f"    primary_section: {section}")
        if addresses:
            lines.append(f"    addresses: {addresses[:400]}")
    return "\n".join(lines)


def _render_synonym_dictionary(bundle: ScaffoldingBundle) -> str:
    """Render the synonym dictionary as canonical -> aliases lines.

    Uses the terms[] dict keyed by canonical id. For each entry we list
    the full_term (human-readable canonical) and any aliases from
    reverse_index that point at this term.
    """
    lines: List[str] = [
        "=== CANONICAL TERM DICTIONARY "
        "(normalize user phrasing to these terms) ==="
    ]
    terms = bundle.synonym_dict.get("terms", {})
    reverse_index = bundle.synonym_dict.get("reverse_index", {})

    # Build canonical -> aliases map from reverse_index.
    canonical_to_aliases: Dict[str, List[str]] = {}
    for alias, canonicals in reverse_index.items():
        # canonicals is a list of term IDs this alias maps to.
        if not isinstance(canonicals, list):
            continue
        for cid in canonicals:
            canonical_to_aliases.setdefault(cid, []).append(alias)

    for cid in sorted(terms.keys()):
        entry = terms[cid]
        full_term = entry.get("full_term") or cid
        category = entry.get("category") or ""
        sections = entry.get("sections") or []
        aliases = sorted(set(canonical_to_aliases.get(cid, [])))
        if cid not in aliases:
            aliases = [cid] + aliases
        alias_str = ", ".join(aliases[:15])
        meta = []
        if category:
            meta.append(f"category={category}")
        if sections:
            meta.append(
                f"sections={sections if len(sections) <= 5 else sections[:5] + ['...']}"
            )
        meta_str = f"  ({'; '.join(meta)})" if meta else ""
        lines.append(f"- {full_term}{meta_str}")
        if alias_str and alias_str != full_term:
            lines.append(f"    aka: {alias_str}")
    return "\n".join(lines)


def _render_section_index(bundle: ScaffoldingBundle) -> str:
    """Render dd.v2 section IDs + titles only. No content, no recs."""
    lines: List[str] = [
        "=== VALID SECTION IDs "
        "(every `sections` entry MUST come from this list) ==="
    ]
    sections = bundle.data_dict.get("sections", {})
    for sid in sorted(sections.keys(), key=_section_sort_key):
        sec = sections[sid]
        title = (sec.get("title") or "").strip()
        lines.append(f"- {sid}: {title}")
    return "\n".join(lines)


def _section_sort_key(sid: str) -> List[int]:
    """Sort section IDs like 4.6.1 numerically, not lexicographically."""
    out: List[int] = []
    for part in sid.split("."):
        try:
            out.append(int(part))
        except ValueError:
            out.append(0)
    return out


# Module-level cache of rendered sections. Built lazily on first call.
_rendered_cache: Dict[str, str] = {}


def _get_rendered_sections(bundle: ScaffoldingBundle) -> Dict[str, str]:
    """Build and cache the four rendered prompt sections."""
    if _rendered_cache:
        return _rendered_cache
    _rendered_cache["intent_menu"] = _render_intent_menu(bundle)
    _rendered_cache["topic_map"] = _render_topic_map(bundle)
    _rendered_cache["synonyms"] = _render_synonym_dictionary(bundle)
    _rendered_cache["sections"] = _render_section_index(bundle)
    logger.info(
        "llm_parser: pre-rendered scaffolding sections "
        "(intent=%d chars, topics=%d chars, synonyms=%d chars, sections=%d chars)",
        len(_rendered_cache["intent_menu"]),
        len(_rendered_cache["topic_map"]),
        len(_rendered_cache["synonyms"]),
        len(_rendered_cache["sections"]),
    )
    return _rendered_cache


def reset_render_cache() -> None:
    """Clear the rendered prompt cache (for tests or hot reload)."""
    _rendered_cache.clear()


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT_HEADER = """You are a query classifier for a clinical Q&A system over the 2026 AHA/ASA Acute Ischemic Stroke Guidelines.

Your ONLY job is to translate a clinician's question into a structured JSON object. You choose every field from the menus provided below. You MUST NOT:
- invent intents, sections, or slot names that are not in the menus
- answer the clinical question
- explain your reasoning
- paraphrase any guideline recommendation

You MUST:
- choose `intent` from the INTENT MENU (or return "out_of_scope")
- choose every entry in `sections` from the VALID SECTION IDs list
- normalize slang, abbreviations, and brand names using the CANONICAL TERM DICTIONARY
- fill only those `slots` whose keys appear in the `required_slots` or `optional_slots` of the chosen intent
- set `confidence` to a float 0.0-1.0 reflecting how sure you are
- set `clarification_needed` to true only when the question is too vague to classify AND would benefit from a single targeted follow-up

The clinician may use slang ("clot-buster"), abbreviations ("TNK", "LKW", "LVO"), brand names ("Eliquis", "Activase"), or fragments ("78yo afib 4h"). You are expected to handle these by normalizing to the canonical terms in the dictionary below.

If the question is NOT addressed by any intent in the menu OR NOT covered by any section in the dd.v2 index, return intent = "out_of_scope" with a short `reason`. The pipeline will then route to a general-knowledge fallback with a clear "not from the 2026 AIS Guidelines" disclaimer.

OUTPUT SCHEMA (return ONLY this JSON, no prose, no markdown):
{
  "intent": "<one of the intent menu keys, or 'out_of_scope'>",
  "topic": "<one topic name from the routing table, or null>",
  "sections": ["<section id from the valid list>", ...],
  "slots": {"<slot name>": "<value>", ...},
  "confidence": <float 0.0-1.0>,
  "clarification_needed": <bool>,
  "clarification_question": "<targeted follow-up question or null>",
  "reason": "<one sentence; required when intent = out_of_scope>"
}
"""


def _build_system_prompt(bundle: ScaffoldingBundle) -> str:
    """Assemble the full system prompt from the cached rendered sections."""
    rendered = _get_rendered_sections(bundle)
    return (
        _SYSTEM_PROMPT_HEADER
        + "\n\n"
        + rendered["intent_menu"]
        + "\n\n"
        + rendered["topic_map"]
        + "\n\n"
        + rendered["synonyms"]
        + "\n\n"
        + rendered["sections"]
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def parse_with_llm(
    question: str,
    bundle: Optional[ScaffoldingBundle] = None,
    model: Optional[str] = None,
) -> LLMParseResult:
    """
    Translate a free-text clinical question into a ParsedQAQueryV2.

    Uses Claude Haiku via the shared LLMClient with temperature 0 and
    JSON-only output. Never raises on LLM errors — returns
    `LLMParseResult(parsed=None, error=...)` instead so the orchestrator
    can fall through to the deterministic parser without a try/except.

    Args:
        question: the clinician's raw question string.
        bundle: scaffolding bundle. Loaded lazily if None.
        model: Anthropic model slug. Defaults to DEFAULT_FAST_MODELS["anthropic"].

    Returns:
        LLMParseResult.
    """
    if not question or not question.strip():
        return LLMParseResult(
            parsed=None, error="empty question", latency_ms=0,
        )

    bundle = bundle or get_scaffolding()
    model = (
        model
        or os.getenv("QA_LLM_PARSER_MODEL")
        or config.DEFAULT_FAST_MODELS.get("anthropic")
    )

    system_prompt = _build_system_prompt(bundle)
    messages = [{"role": "user", "content": question.strip()}]

    t0 = time.perf_counter()
    try:
        client = get_llm_client(provider="anthropic", model=model)
        result = await client.call_json(
            system_prompt=system_prompt,
            messages=messages,
            model=model,
        )
    except Exception as exc:  # noqa: BLE001 - bounded by graceful fallback
        logger.warning("llm_parser: LLM call failed: %s", exc)
        return LLMParseResult(
            parsed=None,
            error=f"llm_call_failed: {exc}",
            latency_ms=int((time.perf_counter() - t0) * 1000),
        )

    latency_ms = int((time.perf_counter() - t0) * 1000)
    raw = result.get("content") or {}
    input_tokens = result.get("input_tokens", 0)
    output_tokens = result.get("output_tokens", 0)

    if not isinstance(raw, dict) or "raw_text" in raw:
        logger.warning(
            "llm_parser: non-JSON response — falling back to deterministic"
        )
        return LLMParseResult(
            parsed=None,
            raw_json=raw if isinstance(raw, dict) else {"text": str(raw)},
            error="non_json_response",
            latency_ms=latency_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    parsed = _hydrate_parsed(raw, question)
    if parsed is None:
        return LLMParseResult(
            parsed=None,
            raw_json=raw,
            error="hydration_failed",
            latency_ms=latency_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    return LLMParseResult(
        parsed=parsed,
        is_out_of_scope=parsed.intent == VnIntent.OUT_OF_SCOPE,
        confidence=parsed.parser_confidence,
        raw_json=raw,
        latency_ms=latency_ms,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


# ---------------------------------------------------------------------------
# Raw JSON -> ParsedQAQueryV2 hydration (no validation — that's the airlock)
# ---------------------------------------------------------------------------


def _hydrate_parsed(raw: Dict[str, Any], question: str) -> Optional[ParsedQAQueryV2]:
    """Convert the raw LLM JSON into a ParsedQAQueryV2.

    This is a tolerant, best-effort hydration. The schema validator is
    the airlock that enforces closed-vocabulary correctness — this
    function's only job is to not crash on minor shape drift.
    """
    intent_str = str(raw.get("intent") or "out_of_scope").strip()
    try:
        intent = VnIntent(intent_str)
    except ValueError:
        logger.warning(
            "llm_parser: unknown intent '%s' — marking out_of_scope", intent_str
        )
        intent = VnIntent.OUT_OF_SCOPE

    sections_raw = raw.get("sections") or []
    sections: List[str] = []
    if isinstance(sections_raw, list):
        for s in sections_raw:
            if isinstance(s, str) and s.strip():
                sections.append(s.strip())

    slots_raw = raw.get("slots") or {}
    slots: Dict[str, Any] = {}
    if isinstance(slots_raw, dict):
        for k, v in slots_raw.items():
            if v is None or v == "":
                continue
            slots[str(k)] = v

    topic = raw.get("topic")
    if topic is not None and not isinstance(topic, str):
        topic = str(topic)

    confidence_raw = raw.get("confidence")
    try:
        confidence = float(confidence_raw) if confidence_raw is not None else 0.0
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    clarification = raw.get("clarification_question") or None
    if clarification is not None and not isinstance(clarification, str):
        clarification = str(clarification)

    scaffolding_trace: Dict[str, Any] = {
        "parser": "llm",
        "llm_confidence": confidence,
        "llm_clarification_needed": bool(raw.get("clarification_needed")),
        "llm_reason": raw.get("reason"),
    }

    return ParsedQAQueryV2(
        question=question,
        intent=intent,
        sections=sections,
        slots=slots,
        topic=topic,
        clarification=clarification,
        clarification_reason="llm_uncertainty" if raw.get("clarification_needed") else None,
        scaffolding_trace=scaffolding_trace,
        parser_confidence=confidence,
    )


__all__ = [
    "LLMParseResult",
    "is_enabled",
    "parse_with_llm",
    "reset_render_cache",
]
