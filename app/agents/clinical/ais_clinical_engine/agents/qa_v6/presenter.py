# ─── v6 (Q&A v6 namespace) ─────────────────────────────────────────────
# Step 4 presenter — takes RetrievedContent and renders a bedside-ready
# clinical answer. No RELEVANT filter, no LIST MODE branching, no
# semantic_units rendering. One LLM call with retrieved atoms as
# grounded context; it writes prose that preserves COR/LOE wording
# verbatim and cites sections deterministically.
# ───────────────────────────────────────────────────────────────────────
"""
qa_v6 presenter.

Input:   RetrievedContent (from retrieval.retrieve())
Output:  AssemblyResult (final user-facing JSON)

Contract:
  - Recommendation text is NEVER paraphrased — preserve COR/LOE wording.
  - Evidence summary (RSS), synopsis, knowledge gaps are allowed to be
    summarized but not fabricated.
  - Every clinical assertion traces to a retrieved atom.
  - If needs_clarification is set, emit clarification options instead
    of an answer.
  - If no atoms survived scoring, emit an "insufficient content" answer.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from .schemas import (
    AssemblyResult,
    AuditEntry,
    ClarificationOption,
    RetrievedContent,
)

logger = logging.getLogger(__name__)


# ── Prompt construction ───────────────────────────────────────────────

_SYSTEM_PROMPT = """You are a reference tool for the 2026 AHA/ASA Acute Ischemic Stroke (AIS) Guidelines. Your audience is bedside clinicians.

You SUMMARIZE retrieved guideline content. You do NOT paraphrase, interpret, editorialize, infer, extend, or add commentary. You are not a clinical adviser — you are a faithful presenter of the guideline.

════════════════════════════════════════════════════════════════
HARD RULES — violations are failures
════════════════════════════════════════════════════════════════

1. VERBATIM RECOMMENDATIONS.
   Recommendation text must be reproduced EXACTLY as provided in the retrieved content. Word-for-word. Do not shorten it. Do not rephrase. Do not "clean up" grammar. Do not swap synonyms. Every recommendation in your answer must be quoted verbatim.
   This applies to EVERY word including: route modifiers (IV / oral / IA / intra-arterial / intravenous), drug forms, patient subsets ("in patients with AIS who are eligible for IVT"), dose amounts, time windows, and eligibility qualifiers. Dropping a single modifier like "IV" changes the clinical meaning and is a failure.

2. VERBATIM COR AND LOE.
   Every recommendation must carry its Class of Recommendation (COR) and Level of Evidence (LOE) exactly as retrieved. Formats like "COR 1, LOE A" or "COR 3: Harm, LOE B-R" are produced by the guideline itself — do not translate, re-letter, or re-number them.

3. NO PARAPHRASE, NO INTERPRETATION, NO EDITORIALIZING.
   Do not say "this suggests", "generally", "usually", "in practice", "importantly", "notably", "clinicians should". Do not explain what the guideline "means". Do not infer clinical implications beyond what the retrieved text states. Do not combine recommendations into a generalization.

4. SUMMARIZE ONLY SUPPORTING EVIDENCE AND SYNOPSIS.
   Supporting text (RSS rows and synopsis paragraphs) may be SUMMARIZED in shorter wording, but only to condense — never to reinterpret or add conclusions. Keep numbers, thresholds, trial names, and outcomes exact. Never summarize a recommendation's directive.

5. NO INVENTION.
   Never add a recommendation, trial name, numeric value, or threshold that is not in the retrieved content. If the retrieved content does not answer the question, say so plainly.

6. NO KNOWLEDGE GAPS UNLESS ASKED.
   Omit knowledge-gap content unless the question's intent explicitly asks about uncertainty, ongoing trials, or open questions.

7. CITATIONS.
   Cite every recommendation and table row by its section marker (§X.Y) exactly as provided. No invented sections.

════════════════════════════════════════════════════════════════
OUTPUT STRUCTURE
════════════════════════════════════════════════════════════════

Answer
  For a yes/no question: begin with "Yes." or "No." on its own, then quote the pertinent recommendation verbatim in quotation marks with minimal framing — exactly: `The guideline states: "<verbatim rec text>"`.
  For any other question: quote the pertinent recommendation verbatim in quotation marks with the same minimal framing.
  NEVER rewrite, compress, summarize, or drop any word from the recommendation — this includes route modifiers ("IV", "oral", "IA", "intra-arterial"), drug forms, patient subsets, time windows, dose amounts, and eligibility qualifiers. If two words are present in the rec, two words appear in your answer.
  Do NOT invent a lead sentence that restates the rec in your own words. The lead IS the quoted rec.

Recommendations
  - §X.Y Recommendation N [COR X, LOE Y]
    "<verbatim text>"
  - (one bullet per retrieved recommendation, verbatim)

Supporting Evidence (optional, only if RSS or synopsis adds information not already in the recommendations)
  - <short factual summary of supporting text, with trial names and numbers kept exact>

Sections: §X.Y, §A.B  (comma-separated)

════════════════════════════════════════════════════════════════
WHAT A GOOD RESPONSE LOOKS LIKE
════════════════════════════════════════════════════════════════

User asked: "Do I give aspirin to a patient with stroke after IVT?"

Retrieved rec §4.8 #17 [COR 3: Harm, LOE B-R]:
  "In patients with AIS who are eligible for IVT, IV aspirin should not be administered concurrently or within 90 minutes of IV thrombolysis."

GOOD answer:
  No. The guideline states: "In patients with AIS who are eligible for IVT, IV aspirin should not be administered concurrently or within 90 minutes of IV thrombolysis."

  Recommendations
  - §4.8 Recommendation 17 [COR 3: Harm, LOE B-R]
    "In patients with AIS who are eligible for IVT, IV aspirin should not be administered concurrently or within 90 minutes of IV thrombolysis."

  Sections: §4.8

BAD answer (dropped route modifier — violates rule 1):
  "No. Aspirin should not be administered within 90 minutes after the start of IVT."
  Why it fails: dropped "IV" before "aspirin". IV aspirin and oral aspirin are clinically distinct — oral aspirin at 30 min post-IVT is governed by a different rec, not this one.

BAD answer (paraphrased — violates rule 1):
  "Aspirin is generally avoided within the first 90 minutes after thrombolysis because of bleeding risk..."

BAD answer (editorialized — violates rule 3):
  "Given the risk of hemorrhagic transformation, clinicians should hold aspirin..."
"""


def _atom_of(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Retrieval builders flatten atoms into top-level fields. This helper
    returns the effective source dict: the nested 'atom' if present
    (defensive), else the entry itself (normal case).
    """
    return entry.get("atom", entry) if isinstance(entry, dict) else {}


def _section_of(entry: Dict[str, Any]) -> str:
    """Read section from either naming convention used by the retrieval
    layer. Builders use 'section' at top level; some atoms use
    'parent_section'. Accept both.
    """
    a = _atom_of(entry)
    return str(
        entry.get("section") or a.get("section") or a.get("parent_section") or ""
    )


def _format_recommendation(rec_entry: Dict[str, Any]) -> str:
    """Render a recommendation for the LLM context with COR/LOE inline."""
    a = _atom_of(rec_entry)
    rec_id = rec_entry.get("recNumber") or a.get("recNumber") or a.get("rec_id") or "?"
    section = _section_of(rec_entry)
    cor = rec_entry.get("cor") or a.get("cor") or ""
    loe = rec_entry.get("loe") or a.get("loe") or ""
    text = (rec_entry.get("text") or a.get("text") or "").strip()

    header = f"§{section} Recommendation {rec_id}"
    if cor:
        header += f" [COR {cor}"
        if loe:
            header += f", LOE {loe}"
        header += "]"
    return f"- {header}\n  \"{text}\""


def _format_rss(entry: Dict[str, Any]) -> str:
    a = _atom_of(entry)
    section = _section_of(entry)
    category = entry.get("category") or a.get("category") or ""
    text = (entry.get("text") or a.get("text") or "").strip()
    cat = f" ({category})" if category else ""
    return f"- §{section}{cat}: {text}"


def _format_synopsis(entry: Dict[str, Any]) -> str:
    section = _section_of(entry)
    a = _atom_of(entry)
    text = (entry.get("text") or a.get("text") or "").strip()
    return f"- §{section}: {text}"


def _format_kg(entry: Dict[str, Any]) -> str:
    section = _section_of(entry)
    a = _atom_of(entry)
    text = (entry.get("text") or a.get("text") or "").strip()
    return f"- §{section}: {text}"


def _format_table(entry: Dict[str, Any]) -> str:
    a = _atom_of(entry)
    section = _section_of(entry)
    text = (entry.get("text") or a.get("text") or "").strip()
    prefix = f"{section}: " if section else ""
    return f"- {prefix}{text}"


def _format_figure(entry: Dict[str, Any]) -> str:
    a = _atom_of(entry)
    section = _section_of(entry)
    text = (entry.get("text") or a.get("text") or "").strip()
    prefix = f"{section}: " if section else ""
    return f"- {prefix}{text}"


def _build_context_block(content: RetrievedContent) -> str:
    """Build the grounded context for the LLM from retrieved atoms."""
    parts: List[str] = []

    if content.recommendations:
        parts.append("## Recommendations")
        for r in content.recommendations:
            parts.append(_format_recommendation(r))
        parts.append("")

    if content.rss:
        parts.append("## Evidence Summary (RSS)")
        for r in content.rss:
            parts.append(_format_rss(r))
        parts.append("")

    if content.synopsis:
        parts.append("## Narrative Context (Synopsis)")
        if isinstance(content.synopsis, dict):
            for section, text in content.synopsis.items():
                parts.append(f"- §{section}: {text}")
        else:
            for s in content.synopsis:
                parts.append(_format_synopsis(s))
        parts.append("")

    if content.knowledge_gaps:
        parts.append("## Knowledge Gaps")
        if isinstance(content.knowledge_gaps, dict):
            for section, text in content.knowledge_gaps.items():
                parts.append(f"- §{section}: {text}")
        else:
            for k in content.knowledge_gaps:
                parts.append(_format_kg(k))
        parts.append("")

    if content.tables:
        parts.append("## Tables")
        for t in content.tables:
            parts.append(_format_table(t))
        parts.append("")

    if content.figures:
        parts.append("## Figures")
        for f in content.figures:
            parts.append(_format_figure(f))
        parts.append("")

    return "\n".join(parts).strip()


def _collect_citations(content: RetrievedContent) -> List[str]:
    """Deterministic citations from retrieved atoms — sections hit."""
    sections: List[str] = []
    seen = set()

    def _add(section: str) -> None:
        if section and section not in seen:
            seen.add(section)
            sections.append(section)

    for r in content.recommendations:
        atom = r.get("atom", {}) if "atom" in r else r
        _add(str(atom.get("parent_section", "")))
    for r in content.rss:
        atom = r.get("atom", {}) if "atom" in r else r
        _add(str(atom.get("parent_section", "")))

    return [f"§{s}" for s in sections if s]


def _collect_trials(content: RetrievedContent) -> List[str]:
    """Extract referenced trial names from atom anchor_terms."""
    # Known trial acronyms (upper-case) — simple, deterministic
    trial_hints = {
        "MR CLEAN", "ESCAPE", "REVASCAT", "SWIFT PRIME", "EXTEND-IA",
        "THRACE", "THERAPY", "DAWN", "DEFUSE 3", "EXTEND", "WAKE-UP",
        "ECASS III", "NINDS", "ATTEST", "EXTEND-IA TNK", "TASTE",
        "BASILAR", "ATTENTION", "BAOCHE", "SELECT", "MR ASAP",
        "INTERACT", "ENCHANTED", "TESPI", "TIMELESS",
    }
    found: List[str] = []
    seen = set()

    def _scan(atom: Dict[str, Any]) -> None:
        text = (atom.get("text") or "").upper()
        for t in trial_hints:
            if t in text and t not in seen:
                seen.add(t)
                found.append(t)

    for r in content.recommendations + content.rss:
        atom = r.get("atom", {}) if "atom" in r else r
        _scan(atom)

    return found


# ── Clarification path ────────────────────────────────────────────────

def _render_clarification(content: RetrievedContent) -> AssemblyResult:
    """Emit clarification options when >MAX_RECS clustered tightly."""
    options: List[ClarificationOption] = []
    for opt in content.clarification_options:
        options.append(ClarificationOption(
            label=opt.get("label", ""),
            description=opt.get("description", ""),
            section=str(opt.get("section", "")),
            rec_id=str(opt.get("rec_id", "")),
            cor=str(opt.get("cor", "")),
            loe=str(opt.get("loe", "")),
        ))

    intro = (
        "Multiple recommendations apply to this question. "
        "Which of the following best matches what you're asking about?"
    )
    return AssemblyResult(
        status="needs_clarification",
        answer=intro,
        summary=intro,
        clarification_options=options,
    )


# ── Empty / out-of-scope path ─────────────────────────────────────────

def _render_insufficient(content: RetrievedContent) -> AssemblyResult:
    """No atoms cleared the threshold — tell the user honestly."""
    msg = (
        "I couldn't find guideline content that answers this specific "
        "question in the 2026 AHA/ASA Acute Ischemic Stroke Guidelines. "
        "Try rephrasing with more specific clinical terms (e.g., drug name, "
        "time window, or patient characteristic)."
    )
    return AssemblyResult(
        status="out_of_scope",
        answer=msg,
        summary=msg,
    )


# ── Main LLM call ─────────────────────────────────────────────────────

async def present(
    content: RetrievedContent,
    nlp_client=None,
) -> AssemblyResult:
    """
    Render the retrieved content as a clinical answer.

    Args:
        content:     RetrievedContent from retrieval.retrieve()
        nlp_client:  Anthropic client (from NLPService). If None, falls
                     back to a deterministic rendering.

    Returns:
        AssemblyResult with status, answer, summary, citations.
    """
    # ── Clarification branch ─────────────────────────────────────
    if content.needs_clarification and content.clarification_options:
        return _render_clarification(content)

    # ── Empty branch ─────────────────────────────────────────────
    has_content = bool(
        content.recommendations or content.rss or content.synopsis
        or content.knowledge_gaps or content.tables or content.figures
    )
    if not has_content:
        return _render_insufficient(content)

    # ── Deterministic fallback if no LLM client ──────────────────
    if nlp_client is None:
        return _render_deterministic(content)

    # ── LLM rendering ────────────────────────────────────────────
    context_block = _build_context_block(content)
    user_prompt = (
        f"Clinician's question: {content.raw_query}\n\n"
        f"Parsed intent: {content.intent}\n\n"
        f"Retrieved guideline content (every recommendation below is "
        f"already in verbatim form — reproduce EXACTLY, never paraphrase):\n\n"
        f"{context_block}\n\n"
        f"Write the bedside answer now, following the output structure "
        f"in your system prompt. Summarize only. Reproduce every "
        f"recommendation and its COR/LOE verbatim. No interpretation, "
        f"no editorializing, no clinical advice beyond what the "
        f"retrieved text states. Cite sections by §X.Y."
    )

    try:
        response = nlp_client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=800,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        answer_text = ""
        for block in response.content:
            if hasattr(block, "text"):
                answer_text += block.text
        answer_text = answer_text.strip()
    except Exception as e:
        logger.error("Presenter LLM call failed: %s", e)
        return _render_deterministic(content)

    citations = _collect_citations(content)
    trials = _collect_trials(content)

    # Summary is the full lead paragraph — not just "Yes." or "No.".
    # A bedside clinician asking a yes/no question deserves the reason
    # in the same breath. The presenter prompt requires the lead to be
    # "Yes./No. The guideline states: \"<verbatim rec>\"", so the first
    # paragraph carries the answer AND the rec text.
    summary = _extract_summary(answer_text)

    return AssemblyResult(
        status="complete",
        answer=answer_text,
        summary=summary,
        citations=citations,
        related_sections=citations,
        referenced_trials=trials,
    )


def _extract_summary(answer_text: str) -> str:
    """Return the lead paragraph of the answer as the summary.

    The presenter structure places the verbatim-quoted answer in the
    first paragraph (before the "Recommendations" header). We take
    everything up to the first blank line, then strip trailing "Answer"
    header lines if the LLM included them.
    """
    if not answer_text:
        return ""
    # Split on double newline — first paragraph is the lead.
    first_paragraph = answer_text.split("\n\n", 1)[0].strip()
    # Some renderings prefix with "Answer\n..." — drop that label line.
    lines = [ln for ln in first_paragraph.splitlines()
             if ln.strip().lower() != "answer"]
    return "\n".join(lines).strip()


# ── Deterministic fallback ────────────────────────────────────────────

def _render_deterministic(content: RetrievedContent) -> AssemblyResult:
    """LLM-free rendering used when no client is configured.

    Concatenates recommendation text + top RSS rows. Good enough to
    verify retrieval is working without paying LLM costs.
    """
    parts: List[str] = []
    if content.recommendations:
        parts.append("Recommendations:")
        for r in content.recommendations[:3]:
            atom = r.get("atom", {}) if "atom" in r else r
            parts.append(_format_recommendation(r))
        parts.append("")
    if content.rss:
        parts.append("Evidence:")
        for r in content.rss[:3]:
            parts.append(_format_rss(r))

    answer_text = "\n".join(parts).strip() or "No content retrieved."
    summary = content.recommendations[0]["atom"]["text"][:160] if content.recommendations else answer_text[:160]

    return AssemblyResult(
        status="complete",
        answer=answer_text,
        summary=summary,
        citations=_collect_citations(content),
        related_sections=_collect_citations(content),
        referenced_trials=_collect_trials(content),
    )
