"""
Pipeline v2 — section router guard + assembly for the scaffolding-driven path.

This module is the glue between the v2 parser/verifier/re-scorer/focused-agent
stages and the final answer. It owns two responsibilities:

1. **Section router v2 (`route_v2`)** — takes the verified+re-scored parse
   and applies the `routable_only_when` guard: review-flagged sections
   (§4.1, 4.2, 4.4, 4.5, 4.6.2 per dd.v2 review_flags) may only be routed
   to when the parser's topic is the EXACT topic entry for that section
   in guideline_topic_map.json. This is the safety net that keeps the
   known-buggy sections from poisoning off-topic queries during the
   parallel PDF cross-check workstream.

2. **Assembly v2 (`assemble_v2`)** — turns a `FocusedResult` into the
   final user-facing answer. It does NOT call the LLM: the focused agent
   already extracted and verified the answer text and citations, so the
   assembler just formats per answer_shape and appends an audit trail.
   Out-of-scope and error paths render canned messages.

The orchestrator (Step 10 / Step 11) will wire `parse_v2 → verify →
rescore → route_v2 → dispatch_focused_agent → assemble_v2` into the live
QA path. Nothing in this file touches v1 data structures.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .focused_agents_v2 import FocusedResult
from .scaffolding_loader import ScaffoldingBundle, get_scaffolding
from .schemas import CitationClaim, ParsedQAQueryV2, VnIntent

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Section router v2 — routable_only_when guard
# ---------------------------------------------------------------------------


@dataclass
class RoutedSections:
    """Output of `route_v2`.

    `sections` is the post-guard list of dd.v2 section ids the focused
    agent should actually read. `dropped_sections` lists sections that
    the parser wanted to route to but were blocked by the
    `routable_only_when` guard (or by family resolution failures).
    `guard_reasons` maps each dropped section id to an explanation so
    the audit trail stays debuggable.
    """

    sections: List[str] = field(default_factory=list)
    dropped_sections: List[str] = field(default_factory=list)
    guard_reasons: Dict[str, str] = field(default_factory=dict)
    out_of_scope: bool = False


def route_v2(
    parsed: ParsedQAQueryV2,
    bundle: Optional[ScaffoldingBundle] = None,
    verifier_resolved: Optional[List[str]] = None,
) -> RoutedSections:
    """
    Apply the `routable_only_when` guard to the verifier's resolved sections.

    Args:
        parsed: the ParsedQAQueryV2 coming out of parse_v2 + verifier + re-scorer.
        bundle: the scaffolding bundle. Loaded lazily if None.
        verifier_resolved: the `resolved_sections` field from the
            scaffolding_verifier's VerificationResult. Preferred over
            `parsed.sections` because the verifier already expanded gtm
            parents into their dd.v2 children.

    Returns:
        RoutedSections with the final post-guard section list.

    Guard rule:
        A section marked `review_flags.needs_review=true` in dd.v2 is
        only routable when the parser's chosen topic exact-matches the
        topic entry for that section in guideline_topic_map.json. This
        mirrors the PDF cross-check workstream item in dev_log/INDEX.md
        — the sections aren't deleted, they're fenced until human review.
    """
    bundle = bundle or get_scaffolding()

    if parsed.intent == VnIntent.OUT_OF_SCOPE:
        return RoutedSections(out_of_scope=True)

    # Prefer the verifier's resolved sections (already family-expanded).
    candidate_sections = list(verifier_resolved or [])
    if not candidate_sections:
        # Fall back to resolving the parser's raw section claims.
        for sid in parsed.sections:
            candidate_sections.extend(bundle.resolve_section_family(sid))
        # Dedupe while preserving order.
        seen = set()
        candidate_sections = [
            s for s in candidate_sections if not (s in seen or seen.add(s))
        ]

    if not candidate_sections:
        return RoutedSections(
            sections=[],
            dropped_sections=[],
            guard_reasons={},
            out_of_scope=True,
        )

    final_sections: List[str] = []
    dropped: List[str] = []
    reasons: Dict[str, str] = {}

    for sid in candidate_sections:
        if not bundle.is_review_flagged(sid):
            final_sections.append(sid)
            continue

        # Review-flagged: only allow when the parser's topic exact-matches
        # the topic entry for this section in gtm. That is the ONLY way we
        # can be confident the question was actually about the core scope
        # of a leakage-prone section.
        gtm_entry = bundle.topic_entry(sid) or {}
        core_topic = gtm_entry.get("topic")
        parser_topic = parsed.topic

        if core_topic and parser_topic and core_topic == parser_topic:
            final_sections.append(sid)
            logger.info(
                "route_v2: review-flagged §%s allowed — topic exact-match '%s'",
                sid, core_topic,
            )
        else:
            dropped.append(sid)
            reasons[sid] = (
                f"review_flagged; topic mismatch "
                f"(parser='{parser_topic}' vs core='{core_topic}')"
            )
            logger.info(
                "route_v2: review-flagged §%s DROPPED — %s", sid, reasons[sid]
            )

    # If the guard dropped EVERYTHING, the query is effectively unroutable
    # for now. Mark as out_of_scope so assembly renders the fenced-section
    # decline rather than a silent empty answer.
    out_of_scope = not final_sections

    return RoutedSections(
        sections=final_sections,
        dropped_sections=dropped,
        guard_reasons=reasons,
        out_of_scope=out_of_scope,
    )


# ---------------------------------------------------------------------------
# Assembly v2 — format per answer_shape
# ---------------------------------------------------------------------------


@dataclass
class AssembledAnswer:
    """Final answer produced by `assemble_v2`.

    `text` is the user-facing string. `answer_shape` is copied from the
    intent catalog so downstream rendering (markdown, JSON, voice) can
    pick the right template. `citations` are the byte-exact-verified
    claims from the focused agent (empty on the numeric path).
    `audit` holds a full trace for the dev_log and regression fixture:
    parsed intent, routed sections, dropped sections with reasons,
    whether parsed_values was used, token usage, any errors.

    `plain_summary` is the optional LLM-produced plain-English reading
    aid prepended above the verbatim source block. Empty string when
    the summarizer is disabled or failed — the verbatim source block
    is always the authoritative content.

    `scope` labels the provenance of the answer so the frontend can
    render it with a distinct treatment. Values:
      - "in_guideline"      → byte-exact answer from the 2026 AIS
                              Guidelines (the default deterministic path)
      - "out_of_guideline"  → general-knowledge fallback with disclaimer
                              banner + footer
      - "denied"            → patient-specific decision blocked by the
                              deny list; safe decline message
      - "fenced"            → matched a review-flagged section the
                              pipeline can't return yet
    """

    ok: bool
    text: str
    answer_shape: str
    citations: List[CitationClaim] = field(default_factory=list)
    audit: Dict[str, Any] = field(default_factory=dict)
    plain_summary: str = ""
    scope: str = "in_guideline"


_FENCED_MESSAGE = (
    "This question maps to a section of the 2026 AIS Guidelines that is "
    "currently undergoing human review for data quality, so I can't return "
    "a verified answer from the structured database yet. Please check the "
    "guideline PDF directly, or rephrase the question to target a different "
    "section."
)

_OUT_OF_SCOPE_MESSAGE = (
    "This question is not addressed by the 2026 AHA/ASA Acute Ischemic "
    "Stroke Guidelines. I can only answer questions grounded in the "
    "structured AIS guideline database."
)

_NO_ANSWER_MESSAGE = (
    "I couldn't find a verified answer to this question in the 2026 AIS "
    "Guidelines database. The recommendations in the relevant sections "
    "didn't directly address the question, and I won't speculate outside "
    "the source."
)


def assemble_v2(
    parsed: ParsedQAQueryV2,
    focused: FocusedResult,
    routed: RoutedSections,
    plain_summary: str = "",
) -> AssembledAnswer:
    """
    Format a FocusedResult into the final user-facing answer.

    This is a pure formatter. It does NOT call the LLM. The focused agent
    has already extracted and verified the answer text and citations; the
    assembler just chooses the right template per `answer_shape` and
    appends the audit trail.

    Three formatting paths:

    - **out_of_scope / fully-fenced** — render the appropriate canned
      decline message. No citations, no numeric content.
    - **numeric (used_parsed_values=True)** — emit the parsed_values
      summary that the focused agent already assembled, prefixed with a
      one-line context header derived from the intent.
    - **text (llm_used=True)** — emit the LLM's answer text followed by
      a `References` block listing each verified citation.

    On any error path (`focused.ok=False` without out_of_scope), the
    assembler renders the `_NO_ANSWER_MESSAGE` with an audit-visible
    error list so the orchestrator can surface a failure signal.
    """
    audit: Dict[str, Any] = {
        "intent": parsed.intent.value,
        "topic": parsed.topic,
        "parser_sections": list(parsed.sections),
        "routed_sections": list(routed.sections),
        "dropped_sections": list(routed.dropped_sections),
        "guard_reasons": dict(routed.guard_reasons),
        "used_parsed_values": focused.used_parsed_values,
        "llm_used": focused.llm_used,
        "usage": dict(focused.usage),
        "errors": list(focused.errors),
        "rejected_citations": [
            {
                "section_id": c.section_id,
                "rec_number": c.rec_number,
                "reason": c.reason or "",
            }
            for c in focused.rejected_citations
        ],
    }

    # ── Path A: out_of_scope (true decline) ──────────────────────────
    if parsed.intent == VnIntent.OUT_OF_SCOPE:
        return AssembledAnswer(
            ok=True,
            text=_OUT_OF_SCOPE_MESSAGE,
            answer_shape="not_addressed_in_guideline",
            citations=[],
            audit=audit,
            scope="in_guideline",
        )

    # ── Path B: fully fenced by router guard ────────────────────────
    # The parser picked a topic, but every resolved section was dropped by
    # the routable_only_when guard. Emit the "under human review" message.
    if routed.out_of_scope and routed.dropped_sections:
        return AssembledAnswer(
            ok=True,
            text=_FENCED_MESSAGE,
            answer_shape="not_addressed_in_guideline",
            citations=[],
            audit=audit,
            scope="fenced",
        )

    # ── Path C: focused agent failed to produce an answer ────────────
    if not focused.ok:
        return AssembledAnswer(
            ok=False,
            text=_NO_ANSWER_MESSAGE,
            answer_shape=focused.answer_shape or "not_addressed_in_guideline",
            citations=[],
            audit=audit,
            scope="in_guideline",
        )

    # ── Path D: numeric family ───────────────────────────────────────
    if focused.used_parsed_values:
        header = _numeric_header(parsed)
        body_lines: List[str] = []
        # Plain-English summary goes ABOVE the numeric body when present.
        if plain_summary:
            body_lines.append("**Plain-language summary**")
            body_lines.append(plain_summary.strip())
            body_lines.append("")
            body_lines.append("**Guideline source (verbatim)**")
        if header:
            body_lines.append(header)
        if focused.text:
            body_lines.append(focused.text)
        body_lines.append("")
        body_lines.append(
            f"_Source: 2026 AHA/ASA AIS Guidelines, "
            f"§{', §'.join(routed.sections) or ', '.join(parsed.sections)}._"
        )
        return AssembledAnswer(
            ok=True,
            text="\n".join(body_lines).strip(),
            answer_shape=focused.answer_shape,
            citations=[],
            audit=audit,
            plain_summary=plain_summary,
            scope="in_guideline",
        )

    # ── Path E: text family — verbatim recs, deterministic layout ───
    # Each citation IS a full recommendation from guideline_knowledge.json.
    # We render them one per block, grouped by section, with a stable
    # header so the user sees exactly which section and rec number each
    # verbatim quote came from. When a plain-English summary was produced
    # by llm_summarizer, it is prepended above the source block.
    parts: List[str] = []

    # Plain-English summary (when enabled) goes FIRST so the clinician
    # sees the reading aid before scrolling to the verbatim block.
    if plain_summary:
        parts.append("**Plain-language summary**")
        parts.append(plain_summary.strip())
        parts.append("")

    if focused.text:
        parts.append(focused.text.strip())
        parts.append("")

    if focused.citations:
        header_topic = parsed.topic or "Relevant Guideline Recommendations"
        if plain_summary:
            parts.append("**Guideline source (verbatim)**")
        parts.append(f"**{header_topic}** — 2026 AHA/ASA AIS Guidelines")
        parts.append("")

        # Group by section to keep the layout readable when multiple
        # sections contributed recs.
        by_section: Dict[str, List[CitationClaim]] = {}
        for c in focused.citations:
            by_section.setdefault(c.section_id, []).append(c)

        for sid in sorted(by_section.keys()):
            parts.append(f"**§{sid}**")
            for c in by_section[sid]:
                # quote IS the full rec text byte-exact from gk.json
                parts.append(f"- Rec #{c.rec_number}: {c.quote.strip()}")
            parts.append("")

    body = "\n".join(parts).strip()
    return AssembledAnswer(
        ok=True,
        text=body or _NO_ANSWER_MESSAGE,
        answer_shape=focused.answer_shape,
        citations=list(focused.citations),
        audit=audit,
        plain_summary=plain_summary,
        scope="in_guideline",
    )


# ---------------------------------------------------------------------------
# Out-of-guideline assemblers — fallback and deny paths
# ---------------------------------------------------------------------------


def assemble_fallback(
    question: str,
    fallback_answer_text: str,
    fallback_header: str,
    fallback_footer: str,
    audit: Optional[Dict[str, Any]] = None,
) -> AssembledAnswer:
    """
    Wrap a general-knowledge fallback answer with the mandatory
    provenance banner + footer. Returns an AssembledAnswer with
    scope='out_of_guideline' so the frontend can render it distinctly.

    The banner is prepended, the footer is appended, regardless of
    what the LLM produced. Provenance is structural, not cosmetic.
    """
    audit = dict(audit or {})
    audit.setdefault("question", question)
    audit.setdefault("scope", "out_of_guideline")

    parts = [
        fallback_header,
        "",
        fallback_answer_text.strip(),
        "",
        fallback_footer,
    ]
    return AssembledAnswer(
        ok=True,
        text="\n".join(parts).strip(),
        answer_shape="out_of_guideline_general_knowledge",
        citations=[],
        audit=audit,
        plain_summary="",
        scope="out_of_guideline",
    )


def assemble_denied(
    question: str,
    decline_message: str,
    deny_reasons: List[str],
    matched_decision: str = "",
    matched_drug: str = "",
) -> AssembledAnswer:
    """
    Render the safe-decline response for a question blocked by the
    treatment-decision deny list. No LLM is called on this path.
    """
    audit: Dict[str, Any] = {
        "question": question,
        "scope": "denied",
        "deny_reasons": list(deny_reasons),
        "matched_decision": matched_decision,
        "matched_drug": matched_drug,
    }
    return AssembledAnswer(
        ok=True,
        text=decline_message,
        answer_shape="patient_specific_decision_declined",
        citations=[],
        audit=audit,
        plain_summary="",
        scope="denied",
    )


def _numeric_header(parsed: ParsedQAQueryV2) -> str:
    """One-line context header for numeric answers.

    Uses the parser's topic + the most relevant slot so the user sees
    what the numeric values refer to without reading the audit trail.
    """
    topic = parsed.topic or ""
    intent_label = parsed.intent.value.replace("_", " ")
    key_slot = ""
    for k in (
        "treatment_or_procedure",
        "drug_or_agent",
        "parameter",
        "therapy_or_protocol",
        "metric",
        "action",
    ):
        v = parsed.slots.get(k)
        if v:
            key_slot = str(v)
            break
    if topic and key_slot:
        return f"**{intent_label.title()}** — {topic}, {key_slot}:"
    if topic:
        return f"**{intent_label.title()}** — {topic}:"
    if key_slot:
        return f"**{intent_label.title()}** — {key_slot}:"
    return f"**{intent_label.title()}**:"


__all__ = [
    "AssembledAnswer",
    "RoutedSections",
    "assemble_v2",
    "route_v2",
]
