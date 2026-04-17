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
   Cite every recommendation and table row by its section marker exactly as provided in the context. Markers look like "§4.8", "§4.6.1", or "§4.6.1 Table 8". No invented sections. If a section marker in the context is empty or appears to be a category slug (e.g. "§absolute_contraindications_ivt"), OMIT the Sections line entirely — do NOT emit garbage section markers.

8. NO META-PREAMBLES.
   Forbidden phrases: "Based on the retrieved content", "The guideline identifies several", "There are several", "According to the guideline", "The 2026 guidelines state that". These are editorializing filler. The answer is always the VERBATIM content itself. If you cannot write the answer without such a preamble, you are paraphrasing.

9. RSS-ONLY QUESTIONS (no recommendations retrieved).
   Some questions are answered by evidence-summary rows (RSS) rather than by a numbered recommendation. When NO recommendation atoms are provided but RSS rows are, use those RSS rows as the verbatim source. Render each row verbatim — do NOT collapse them into a prose paragraph.

   Lead-in (choose in this order):
     A. If every provided RSS row shares the same section_title (all from one table subsection, e.g. all T8.3 rows), use that section_title as the lead followed by a colon. Drop a leading "Conditions that are Considered " or similar qualifier-prefix so the lead reads as a natural clinical noun phrase. Examples:
        - context section_title "Conditions that are Considered Absolute Contraindications (to IVT)"
          → lead: "Absolute Contraindications (to IVT):"
        - context section_title "Conditions That are Relative Contraindications (to IVT)"
          → lead: "Relative Contraindications (to IVT):"
        - context section_title "Conditions in Which Benefits of Intravenous Thrombolysis Generally are Greater Than Risks of Bleeding"
          → lead: "Conditions in Which Benefits of Intravenous Thrombolysis Generally are Greater Than Risks of Bleeding:"
     B. If rows span multiple section_titles, use `The guideline states:` as the generic lead.

   When an RSS row is provided with a row_label (context shows "[§X.Y TN.i] <row_label>: <text>"), render it as:
     • <row_label>: <text>
   Do NOT wrap the text in quotation marks. The guideline formats these as "Label: description" without quotes, and that is the format a bedside clinician expects.

   When an RSS row has no label (context shows "§X.Y: <text>"), render it as:
     • <text>
   (still no quotation marks)

   For enumerative questions ("what are the contraindications", "what are the exclusion criteria") always render ALL provided rows as a LIST — one bullet per row, in the order retrieved. Do not drop rows. Do not deduplicate with any summary paragraph.

════════════════════════════════════════════════════════════════
OUTPUT STRUCTURE
════════════════════════════════════════════════════════════════

Answer
  For a yes/no question: begin with "Yes." or "No." on its own, then quote the pertinent recommendation verbatim in quotation marks with minimal framing — exactly: `The guideline states: "<verbatim rec text>"`.
  For any other question where a recommendation exists: quote the pertinent recommendation verbatim in quotation marks with the same minimal framing.
  For enumerative questions with NO recommendation (contraindications, criteria lists, etc.): use `The guideline states:` followed by a bulleted list of verbatim RSS rows — one bullet per row, exactly as retrieved. Do NOT write a prose paragraph.
  NEVER rewrite, compress, summarize, or drop any word — this includes route modifiers ("IV", "oral", "IA", "intra-arterial"), drug forms, patient subsets, time windows, dose amounts, and eligibility qualifiers. If two words are present in the source, two words appear in your answer.
  Do NOT invent a lead sentence that restates the source in your own words. The lead IS the quoted source.

Recommendations (include this block ONLY when recommendation atoms were retrieved)
  - §X.Y Recommendation N [COR X, LOE Y]
    "<verbatim text>"
  - (one bullet per retrieved recommendation, verbatim)

Supporting Evidence (optional, only if RSS adds information not already in the recommendations AND recommendations are present; when RSS is the PRIMARY content per rule 9, put it in the Answer block, not here)
  - <verbatim text — never paraphrase>

Sections: §X.Y, §A.B  (comma-separated — OMIT entirely if section markers in context are empty or non-numeric per rule 7)

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

════════════════════════════════════════════════════════════════
WHAT A GOOD RSS-ONLY RESPONSE LOOKS LIKE (rule 9)
════════════════════════════════════════════════════════════════

User asked: "What are the absolute contraindications for IVT?"

Retrieved (no recommendations; Evidence Summary rows with row_labels from Table 8.3):
  - [§4.6 T8.3] CT with hemorrhage: IV thrombolysis should not be administered to patients whose CT brain imaging reveals an acute intracranial hemorrhage.
  - [§4.6 T8.3] Neurosurgery <14 days: For patients with AIS and a history of intracranial/spinal surgery within 14 days, IV thrombolysis is potentially harmful and should not be administered.
  - [§4.6 T8.3] Aortic arch dissection: For patients with AIS and known or suspected aortic arch dissection, treatment with IV thrombolysis should not be administered.
  - [§4.6 T8.3] Amyloid-related imaging abnormalities (ARIA): The risk of thrombolysis related ICH in patients on amyloid immunotherapy or with ARIA is unknown and IV thrombolysis should be avoided in such patients.

GOOD answer (all rows share one section_title, so lead with that title per rule 9.A):
  Absolute Contraindications (to IVT):
  • CT with hemorrhage: IV thrombolysis should not be administered to patients whose CT brain imaging reveals an acute intracranial hemorrhage.
  • Neurosurgery <14 days: For patients with AIS and a history of intracranial/spinal surgery within 14 days, IV thrombolysis is potentially harmful and should not be administered.
  • Aortic arch dissection: For patients with AIS and known or suspected aortic arch dissection, treatment with IV thrombolysis should not be administered.
  • Amyloid-related imaging abnormalities (ARIA): The risk of thrombolysis related ICH in patients on amyloid immunotherapy or with ARIA is unknown and IV thrombolysis should be avoided in such patients.

  Sections: §4.6 T8.3

BAD answer (preamble — violates rule 8):
  "Based on the retrieved content, the guideline identifies several absolute contraindications for IV thrombolysis (IVT) in patients with acute ischemic stroke."
  Why it fails: editorializing meta-preamble. A bedside clinician needs the ACTUAL list, not a sentence that announces a list is coming.

BAD answer (prose-summarized RSS — violates rules 1, 9):
  "Supporting Evidence - IV thrombolysis should not be administered to patients whose CT brain imaging reveals an acute intracranial hemorrhage - For patients with AIS and a history..."
  Why it fails: rows run together as continuous prose, losing bullet structure, losing row labels, and losing readability.

BAD answer (quotation marks — violates rule 9):
  "• CT with hemorrhage: \"IV thrombolysis should not be administered to patients whose CT brain imaging reveals an acute intracranial hemorrhage.\""
  Why it fails: the guideline does not wrap bullet text in quotes. The label-plus-colon format already marks the text as verbatim.

BAD answer (dropped row — violates rule 9):
  (the LLM lists 9 of 10 retrieved rows)
  Why it fails: the rule says render ALL provided rows. Dropping a row is a failure of completeness.

BAD answer (invented section slug — violates rule 7):
  "Sections: §absolute_contraindications_ivt, §relative_contraindications_ivt"
  Why it fails: these are category slugs, not guideline section markers. Real markers look like "§4.6 T8.3" or "§4.8". Omit the Sections line when real markers aren't available.
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


def _display_section(entry: Dict[str, Any]) -> str:
    """Human-readable section reference for citations and display.

    Table rows carry a `section_path` like ["4.6", "T8.3",
    "Conditions that are Considered Absolute Contraindications (to IVT)"].
    For user-facing display we render "§4.6 T8.3" — chapter + short
    table/subsection label. The long subsection heading lives in
    `section_title` on the atom, not in the citation.

    Non-table atoms (plain recs, narrative, etc.) keep "§<section>".
    """
    a = _atom_of(entry)
    path = entry.get("section_path") or a.get("section_path")
    if isinstance(path, list) and len(path) >= 2:
        chapter, label = str(path[0]).strip(), str(path[1]).strip()
        if chapter and label:
            return f"§{chapter} {label}"
        if chapter:
            return f"§{chapter}"
    section = _section_of(entry)
    return f"§{section}" if section else ""


def _format_recommendation(rec_entry: Dict[str, Any]) -> str:
    """Render a recommendation for the LLM context with COR/LOE inline."""
    a = _atom_of(rec_entry)
    rec_id = rec_entry.get("recNumber") or a.get("recNumber") or a.get("rec_id") or "?"
    section_display = _display_section(rec_entry)
    cor = rec_entry.get("cor") or a.get("cor") or ""
    loe = rec_entry.get("loe") or a.get("loe") or ""
    text = (rec_entry.get("text") or a.get("text") or "").strip()

    header = f"{section_display} Recommendation {rec_id}".strip()
    if cor:
        header += f" [COR {cor}"
        if loe:
            header += f", LOE {loe}"
        header += "]"
    return f"- {header}\n  \"{text}\""


def _format_rss(entry: Dict[str, Any]) -> str:
    """Render an RSS row for the LLM context.

    Table rows carry a `row_label` — the guideline's own condition
    heading (e.g. "Amyloid-related imaging abnormalities (ARIA)") that
    prefixes the descriptive sentence. When present, we pass the label
    through so the LLM can emit the guideline's native
    "• <label>: <text>" formatting.
    """
    a = _atom_of(entry)
    section_display = _display_section(entry)
    text = (entry.get("text") or a.get("text") or "").strip()
    row_label = entry.get("row_label") or a.get("row_label") or ""
    if row_label:
        # Provide label to the LLM alongside section marker
        return f"- [{section_display}] {row_label}: {text}"
    # Atoms without row_label (non-table RSS, or not yet labelled)
    category = entry.get("category") or a.get("category") or ""
    cat = f" ({category})" if category else ""
    return f"- {section_display}{cat}: {text}"


def _format_synopsis(entry: Dict[str, Any]) -> str:
    section_display = _display_section(entry)
    a = _atom_of(entry)
    text = (entry.get("text") or a.get("text") or "").strip()
    return f"- {section_display}: {text}"


def _format_kg(entry: Dict[str, Any]) -> str:
    section_display = _display_section(entry)
    a = _atom_of(entry)
    text = (entry.get("text") or a.get("text") or "").strip()
    return f"- {section_display}: {text}"


def _format_table(entry: Dict[str, Any]) -> str:
    a = _atom_of(entry)
    section_display = _display_section(entry)
    text = (entry.get("text") or a.get("text") or "").strip()
    prefix = f"{section_display}: " if section_display else ""
    return f"- {prefix}{text}"


def _format_figure(entry: Dict[str, Any]) -> str:
    a = _atom_of(entry)
    section_display = _display_section(entry)
    text = (entry.get("text") or a.get("text") or "").strip()
    prefix = f"{section_display}: " if section_display else ""
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
    """Deterministic citations from retrieved atoms — display-ready.

    Uses `_display_section` so table rows cite as "§4.6 T8.3"
    rather than the internal canonical id. Plain recs cite as
    "§<section>" unchanged.
    """
    sections: List[str] = []
    seen = set()

    def _add(display: str) -> None:
        if display and display not in seen:
            seen.add(display)
            sections.append(display)

    for r in content.recommendations:
        _add(_display_section(r))
    for r in content.rss:
        _add(_display_section(r))

    return sections


def _parse_answer_sections_line(answer_text: str) -> Optional[List[str]]:
    """Extract canonical citation list from the LLM's 'Sections:' line.

    The presenter prompt requires the answer to end with
    'Sections: §X, §Y'. Parsing that line gives us the sections the
    LLM actually used — which is usually a tighter list than the raw
    retrieved-atom set. Falls back to None when no Sections line
    present so the caller can use a different source.
    """
    if not answer_text:
        return None
    for raw_line in reversed(answer_text.splitlines()):
        line = raw_line.strip()
        if not line:
            continue
        # Case-insensitive match on the label
        lowered = line.lower()
        if not (lowered.startswith("sections:") or lowered.startswith("sections ")):
            # Only scan the last handful of lines
            # If we hit something that clearly isn't a trailer, bail
            if line.startswith("•") or line.startswith("-") or len(line) > 120:
                return None
            continue
        _, _, rest = line.partition(":")
        parts = [p.strip() for p in rest.split(",") if p.strip()]
        out: List[str] = []
        for p in parts:
            # Normalize the § prefix — accept "§X" or "X" inputs and
            # always emit with a single leading §.
            q = p.lstrip("§ ").strip()
            if q:
                out.append(f"§{q}")
        return out or None
    return None


def _scope_citations(
    fallback: List[str], answer_text: str,
) -> List[str]:
    """If the LLM's Sections line parsed cleanly, use it. Else fallback."""
    parsed = _parse_answer_sections_line(answer_text)
    if parsed:
        return parsed
    return fallback


def _strip_sections_trailer(answer_text: str) -> str:
    """Remove a trailing `Sections: ...` line from the rendered answer.

    The LLM is still asked to emit this line so retrieval can scope
    citations via _parse_answer_sections_line. But once we've extracted
    it into the structured `citations` field, showing it again in the
    Details panel is visual noise — the same section markers already
    appear in the Guideline References chip list the frontend renders
    from citations.

    Scans from the bottom and drops any trailing blank / section-line
    text. Leaves the rest of the answer intact.
    """
    if not answer_text:
        return answer_text
    lines = answer_text.splitlines()
    # Work from the end, stripping blank lines and any line whose
    # first token (case-insensitive) is "Sections:".
    while lines:
        last = lines[-1].strip()
        if not last:
            lines.pop()
            continue
        lowered = last.lower()
        if lowered.startswith("sections:") or lowered.startswith("sections "):
            lines.pop()
            continue
        break
    return "\n".join(lines).rstrip()


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
            max_tokens=2500,  # Raised from 800: enumerative RSS answers
                              # (e.g. all 18 relative contraindications, each
                              # a verbatim sentence) need headroom so the
                              # LLM doesn't truncate the list.
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

    # Scope citations to what the LLM actually referenced. If it
    # emitted the canonical "Sections: §..." trailer, use that; else
    # fall back to the full retrieved-atom section list. This kills
    # stale references (e.g. a §5.4 IPC rec or a §4.6.4 rec that
    # passed the gate but didn't source the visible answer).
    fallback_cits = _collect_citations(content)
    citations = _scope_citations(fallback_cits, answer_text)
    trials = _collect_trials(content)

    # Now that citations are a structured field, strip the inline
    # "Sections: §X, §Y" trailer from the answer_text so it doesn't
    # render visually alongside the Guideline References chip list.
    answer_text = _strip_sections_trailer(answer_text)

    # Summary is the full lead paragraph — not just "Yes." or "No.".
    # A bedside clinician asking a yes/no question deserves the reason
    # in the same breath.
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
