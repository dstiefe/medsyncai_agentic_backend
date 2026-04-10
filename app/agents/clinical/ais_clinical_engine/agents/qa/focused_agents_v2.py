"""
Focused Agents v2 — deterministic per-intent dispatch.

This module is the ONLY place where the v2 pipeline touches rec text or
parsed_values. It has NO LLM calls, NO network, NO probabilistic logic.
Every answer is either:

    Numeric family (dose, duration, onset_to_treatment, time_window,
    threshold_target, frequency):
        → read parsed_values from data_dictionary.v2.json for every
          resolved section and render as a compact summary.

    Text family (everything else except out_of_scope):
        → pull every recommendation verbatim from guideline_knowledge.json
          for the resolved sections and return them as citations. The
          assembler formats them with section/rec headers.

    out_of_scope:
        → no-op. The assembly agent writes the decline message.

Why deterministic text path: we have one document (the 2026 AIS
Guidelines). For any well-scoped question, the answer is "show the
relevant recommendations verbatim." The LLM adds latency, cost, and
hallucination risk without adding accuracy — byte-exact rec text IS
the ground truth.

The numeric path is unchanged from the previous version and already
deterministic.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .scaffolding_loader import ScaffoldingBundle, get_scaffolding
from .scaffolding_verifier import CitationCheck
from .schemas import CitationClaim, ParsedQAQueryV2, VnIntent

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data dictionary + guideline knowledge loading (module-cached)
# ---------------------------------------------------------------------------

_DD_V2_PATH = os.path.join(
    os.path.dirname(__file__), "references", "data_dictionary.v2.json"
)
_GK_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "guideline_knowledge.json"
)

_dd_cache: Optional[Dict[str, Any]] = None
_gk_cache: Optional[Dict[str, Any]] = None


def _load_dd_v2() -> Dict[str, Any]:
    global _dd_cache
    if _dd_cache is None:
        try:
            with open(_DD_V2_PATH) as f:
                _dd_cache = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            logger.error("focused_agents_v2: failed to load dd.v2: %s", e)
            _dd_cache = {"sections": {}}
    return _dd_cache


def _load_gk() -> Dict[str, Any]:
    global _gk_cache
    if _gk_cache is None:
        try:
            with open(os.path.abspath(_GK_PATH)) as f:
                _gk_cache = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            logger.error("focused_agents_v2: failed to load gk: %s", e)
            _gk_cache = {"sections": {}}
    return _gk_cache


def reset_caches() -> None:
    """Reset module-level caches (for tests or hot reload)."""
    global _dd_cache, _gk_cache
    _dd_cache = None
    _gk_cache = None


# ---------------------------------------------------------------------------
# Family routing
# ---------------------------------------------------------------------------

NUMERIC_INTENTS = {
    VnIntent.DOSE,
    VnIntent.DURATION,
    VnIntent.ONSET_TO_TREATMENT,
    VnIntent.TIME_WINDOW,
    VnIntent.THRESHOLD_TARGET,
    VnIntent.FREQUENCY,
}


@dataclass
class FocusedResult:
    """Deterministic output of a focused agent dispatch.

    `llm_used` is preserved for backward compatibility with assemble_v2's
    audit trail, but it is always False in the deterministic pipeline.
    """

    ok: bool
    intent: VnIntent
    answer_shape: str
    text: str = ""
    parsed_numeric: List[Dict[str, Any]] = field(default_factory=list)
    citations: List[CitationClaim] = field(default_factory=list)
    rejected_citations: List[CitationCheck] = field(default_factory=list)
    used_parsed_values: bool = False
    llm_used: bool = False
    errors: List[str] = field(default_factory=list)
    usage: Dict[str, int] = field(
        default_factory=lambda: {"input_tokens": 0, "output_tokens": 0}
    )


# ---------------------------------------------------------------------------
# Numeric path — read parsed_values from dd.v2
# ---------------------------------------------------------------------------

_INTENT_TO_DD_KEYS: Dict[VnIntent, List[str]] = {
    VnIntent.DOSE: ["dose"],
    VnIntent.DURATION: ["duration"],
    VnIntent.ONSET_TO_TREATMENT: ["time_window", "onset_to_treatment", "process_metric"],
    VnIntent.TIME_WINDOW: ["time_window"],
    VnIntent.THRESHOLD_TARGET: [
        "threshold",
        "blood_pressure",
        "glucose",
        "temperature",
        "oxygen_saturation",
    ],
    VnIntent.FREQUENCY: ["frequency", "monitoring_frequency"],
}


def _collect_parsed_values_for_intent(
    intent: VnIntent,
    resolved_sections: List[str],
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Scan dd.v2 for parsed_values matching the intent."""
    dd = _load_dd_v2()
    sections = dd.get("sections", {})
    candidate_keys = _INTENT_TO_DD_KEYS.get(intent, [])
    hits: List[Dict[str, Any]] = []
    sources: List[str] = []

    for sid in resolved_sections:
        sec = sections.get(sid)
        if not isinstance(sec, dict):
            continue
        tried: set = set()
        for key in candidate_keys:
            if key in sec and isinstance(sec[key], dict):
                field_obj = sec[key]
                pv = field_obj.get("parsed_values")
                if pv:
                    hits.append(
                        {
                            "section_id": sid,
                            "field": key,
                            "parsed_values": list(pv),
                            "note": field_obj.get("note"),
                            "source_rec_ids": list(
                                field_obj.get("source_rec_ids") or []
                            ),
                        }
                    )
                    if sid not in sources:
                        sources.append(sid)
                tried.add(key)

        # Fallback scan for numeric-looking fields not in the candidate list.
        for field_name, field_obj in sec.items():
            if field_name in tried or field_name in ("title", "subheadings"):
                continue
            if not isinstance(field_obj, dict):
                continue
            if "parsed_values" not in field_obj:
                continue
            if any(h["section_id"] == sid for h in hits):
                continue
            probe = f"{field_name} {field_obj.get('note', '')}".lower()
            if _intent_keyword_match(intent, probe):
                hits.append(
                    {
                        "section_id": sid,
                        "field": field_name,
                        "parsed_values": list(field_obj["parsed_values"]),
                        "note": field_obj.get("note"),
                        "source_rec_ids": list(
                            field_obj.get("source_rec_ids") or []
                        ),
                    }
                )
                if sid not in sources:
                    sources.append(sid)

    return hits, sources


def _intent_keyword_match(intent: VnIntent, probe: str) -> bool:
    keywords = {
        VnIntent.DOSE: ["dose", "mg", "mg/kg"],
        VnIntent.DURATION: ["duration", "hours", "minutes"],
        VnIntent.ONSET_TO_TREATMENT: ["onset", "door", "needle", "groin"],
        VnIntent.TIME_WINDOW: ["window", "hour"],
        VnIntent.THRESHOLD_TARGET: [
            "threshold", "target", "bp", "pressure",
            "glucose", "temperature", "saturation",
        ],
        VnIntent.FREQUENCY: ["frequency", "every", "q "],
    }
    kws = keywords.get(intent, [])
    return any(kw in probe for kw in kws)


def _numeric_hits_to_text(hits: List[Dict[str, Any]], intent: VnIntent) -> str:
    if not hits:
        return ""
    lines: List[str] = []
    for h in hits:
        sid = h["section_id"]
        field_name = h["field"]
        for pv in h["parsed_values"]:
            rendered = _render_parsed_value(pv)
            if rendered:
                lines.append(f"- §{sid} {field_name}: {rendered}")
    return "\n".join(lines)


def _render_parsed_value(pv: Any) -> str:
    """Render one parsed_values entry — handles dict, str, numeric."""
    if isinstance(pv, dict):
        orig = pv.get("original_value")
        unit = pv.get("unit") or ""
        value_h = pv.get("value_h")
        min_h = pv.get("min_h")
        max_h = pv.get("max_h")
        if orig is not None:
            return f"{orig}{(' ' + unit) if unit else ''}".strip()
        if value_h is not None:
            return f"{value_h} {unit}".strip()
        if min_h is not None and max_h is not None:
            return f"{min_h}-{max_h} {unit}".strip()
        return json.dumps(pv)
    if isinstance(pv, str):
        return pv
    if isinstance(pv, (int, float)):
        return str(pv)
    return json.dumps(pv)


def _has_numeric_pv(h: Dict[str, Any]) -> bool:
    for pv in h.get("parsed_values") or []:
        if isinstance(pv, (dict, int, float)):
            return True
    return False


# ---------------------------------------------------------------------------
# Text path — deterministic verbatim rec extraction
# ---------------------------------------------------------------------------


def _gather_recs_raw(
    section_ids: List[str],
    gk_sections: Dict[str, Any],
) -> List[Tuple[str, int, str, str, str]]:
    """Pull every rec from the listed sections (no fallback)."""
    out: List[Tuple[str, int, str, str, str]] = []
    for sid in section_ids:
        sec = gk_sections.get(sid)
        if not isinstance(sec, dict):
            continue
        rss = sec.get("rss") or []
        for rec in rss:
            if not isinstance(rec, dict):
                continue
            rec_num = rec.get("recNumber")
            text = rec.get("text") or ""
            if rec_num is None or not text:
                continue
            try:
                rn = int(rec_num)
            except (TypeError, ValueError):
                continue
            cor = str(rec.get("cor") or rec.get("COR") or "")
            loe = str(rec.get("loe") or rec.get("LOE") or "")
            out.append((sid, rn, text, cor, loe))
    return out


def _sibling_sections(section_id: str, bundle: ScaffoldingBundle) -> List[str]:
    """Return the sibling dd.v2 sections that share the immediate parent.

    For "4.6.2" with parent "4.6", returns ["4.6", "4.6.1", "4.6.3",
    "4.6.4", "4.6.5"] (minus 4.6.2 itself). Used as a fallback when the
    primary section has zero rec coverage in gk.json so we still answer
    from the same topic area instead of silently failing.
    """
    parts = section_id.split(".")
    if len(parts) < 2:
        return []
    parent = ".".join(parts[:-1])
    siblings: List[str] = []
    if parent in bundle.dd_sections and parent != section_id:
        siblings.append(parent)
    for child in bundle.gtm_parent_to_children.get(parent, []):
        if child != section_id and child in bundle.dd_sections:
            siblings.append(child)
    # stable order
    return sorted(set(siblings))


def _gather_recs_for_sections(
    resolved_sections: List[str],
    bundle: Optional[ScaffoldingBundle] = None,
) -> List[Tuple[str, int, str, str, str]]:
    """Return [(section_id, rec_number, text, cor, loe), ...] for every rec.

    If the direct gather for `resolved_sections` yields nothing, expand
    to sibling sections under the same parent (fallback: when gtm picks
    a topic-level section that happens to have no rss entries in
    guideline_knowledge.json, the answer almost certainly lives in a
    sibling subsection of the same topic).
    """
    gk = _load_gk()
    gk_sections = gk.get("sections", {})

    primary = _gather_recs_raw(resolved_sections, gk_sections)
    if primary:
        return primary

    # Zero-coverage fallback: siblings
    bundle = bundle or get_scaffolding()
    expanded: List[str] = []
    for sid in resolved_sections:
        for sib in _sibling_sections(sid, bundle):
            if sib not in expanded and sib not in resolved_sections:
                expanded.append(sib)
    if not expanded:
        return []
    fallback = _gather_recs_raw(expanded, gk_sections)
    if fallback:
        logger.info(
            "focused_agents_v2: zero-coverage fallback — expanded %s "
            "to siblings %s, recovered %d recs",
            resolved_sections, expanded, len(fallback),
        )
    return fallback


def _rec_matches_slots(text: str, slots: Dict[str, Any]) -> bool:
    """Soft filter: a rec matches if any slot value substring appears in it.

    Empty slots mean "return everything in the section" (no filter). This
    keeps the deterministic path permissive — the section router already
    narrowed the scope, so at the rec level we only filter when the user
    named something specific like "tenecteplase" or "blood pressure".
    """
    if not slots:
        return True
    lowered = text.lower()
    for k, v in slots.items():
        if v is None or v == "" or v == []:
            continue
        if isinstance(v, list):
            values = [str(x) for x in v]
        else:
            values = [str(v)]
        for surface in values:
            if not surface:
                continue
            if surface.lower() in lowered:
                return True
    # No slot matched — still return True so we don't silently drop recs
    # when slot surface forms differ from rec wording. The section router
    # is the primary filter; slot matching is a nice-to-have.
    return True


# ---------------------------------------------------------------------------
# Dispatch (deterministic)
# ---------------------------------------------------------------------------


async def dispatch_focused_agent(
    parsed: ParsedQAQueryV2,
    resolved_sections: List[str],
    bundle: Optional[ScaffoldingBundle] = None,
    nlp_client: Any = None,  # accepted for backward-compat; ignored
) -> FocusedResult:
    """
    Dispatch a parsed v2 query to a deterministic focused agent.

    No LLM calls. Numeric intents read parsed_values from dd.v2. Text
    intents return every rec in the resolved sections verbatim as
    citations. Out-of-scope short-circuits.
    """
    bundle = bundle or get_scaffolding()
    intent = parsed.intent
    answer_shape = parsed.scaffolding_trace.get("answer_shape") or ""
    sections = list(resolved_sections) if resolved_sections else list(parsed.sections)

    # ── Out-of-scope short-circuit ───────────────────────────────────
    if intent == VnIntent.OUT_OF_SCOPE:
        return FocusedResult(
            ok=True,
            intent=intent,
            answer_shape=answer_shape or "not_addressed_in_guideline",
            text="",
        )

    # ── Numeric family ───────────────────────────────────────────────
    if intent in NUMERIC_INTENTS:
        hits, _sources = _collect_parsed_values_for_intent(intent, sections)
        numeric_hits = [h for h in hits if _has_numeric_pv(h)]
        if numeric_hits:
            return FocusedResult(
                ok=True,
                intent=intent,
                answer_shape=answer_shape,
                text=_numeric_hits_to_text(numeric_hits, intent),
                parsed_numeric=numeric_hits,
                citations=[],
                used_parsed_values=True,
                llm_used=False,
            )
        logger.info(
            "focused_agents_v2: numeric intent %s had no numeric parsed_values "
            "in %s — falling through to verbatim-rec text path",
            intent.value, sections,
        )

    # ── Text family (deterministic verbatim recs) ────────────────────
    recs = _gather_recs_for_sections(sections, bundle=bundle)
    if not recs:
        return FocusedResult(
            ok=False,
            intent=intent,
            answer_shape=answer_shape,
            errors=[
                f"[verbatim_recs] no recs found in resolved sections {sections}"
            ],
        )

    slots = parsed.slots or {}
    citations: List[CitationClaim] = []
    for sid, rn, text, cor, loe in recs:
        if not _rec_matches_slots(text, slots):
            continue
        # The quote IS the full rec text, byte-exact from gk.json.
        citations.append(
            CitationClaim(section_id=sid, rec_number=rn, quote=text)
        )

    if not citations:
        return FocusedResult(
            ok=False,
            intent=intent,
            answer_shape=answer_shape,
            errors=[
                f"[verbatim_recs] slot filter dropped all {len(recs)} recs in {sections}"
            ],
        )

    # No natural-language text — the assembler renders the citations.
    return FocusedResult(
        ok=True,
        intent=intent,
        answer_shape=answer_shape,
        text="",
        citations=citations,
        llm_used=False,
    )


__all__ = [
    "FocusedResult",
    "NUMERIC_INTENTS",
    "dispatch_focused_agent",
    "reset_caches",
]
