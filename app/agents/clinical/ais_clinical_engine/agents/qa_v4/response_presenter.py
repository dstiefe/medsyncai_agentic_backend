# ─── v4 (Q&A v4 namespace) ─────────────────────────────────────────────
# Step 4: Present retrieved content to the clinician.
#
# Single LLM call. The LLM does two things:
#   1. Semantic filter: identify which recs actually answer the question
#      (Python term-matching casts a wide net; the LLM understands meaning)
#   2. Summary: write a concise clinical summary from the relevant recs
#
# Python builds the detail section from ONLY the LLM-selected recs.
#
# Rules enforced by prompt:
#   - The LLM selects recs by semantic relevance, not keyword match
#   - Summary: clear, concise, conversational clinical language
#   - The LLM does NOT interpret, editorialize, or paraphrase
#   - Detail: exact verbatim recs, RSS, KG (built by Python, not LLM)
# ───────────────────────────────────────────────────────────────────────
"""
Step 4: Response Presenter — one LLM call for filtering + summary.

    1. LLM reads retrieved content and the question, identifies which
       recs semantically answer the question (not just term matches),
       and writes a clinical summary
    2. Python builds the detail section from only the LLM-selected recs
       (verbatim recs with COR/LOE, RSS text, KG text)
    3. Combined: summary + filtered detail = full answer
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .content_retriever import RetrievedContent
from .schemas import ParsedQAQuery

logger = logging.getLogger(__name__)

# ── Limits on content passed to the LLM ──────────────────────────────
# Step 3 already narrowed and scored; these caps prevent token bloat
# for very broad topics.
_MAX_RECS_FOR_LLM = 12
_MAX_RSS_FOR_LLM = 8
_MAX_KG_FOR_LLM = 5
_MAX_RSS_CHARS = 1200   # truncate individual RSS entries

# ── Limits on the detail section ─────────────────────────────────────
_MAX_RECS_FOR_DETAIL = 15
_MAX_RSS_FOR_DETAIL = 10


class ResponsePresenter:
    """Formats Step 3 retrieved content into summary + detail."""

    def __init__(self, nlp_client=None):
        self._client = nlp_client
        self.is_available = nlp_client is not None

    async def present(
        self,
        question: str,
        retrieved: RetrievedContent,
        parsed: ParsedQAQuery,
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """
        Generate summary (LLM) + detail (Python) from retrieved content.

        The LLM does two things in one call:
        1. Semantic filter: identify which recs answer the question
        2. Summary: write a concise clinical summary

        Python then builds the detail section from only the selected recs.

        Returns:
            {
                "summary": str,           # LLM-written clinical summary
                "answer": str,            # Python-built verbatim content
                "citations": [str],
                "related_sections": [str],
            }
        """
        has_content = bool(
            retrieved.recommendations
            or retrieved.rss
            or retrieved.knowledge_gaps
            or retrieved.synopsis
        )

        # ── LLM: semantic filter + summary ───────────────────────────
        if self._client and has_content:
            summary, relevant_rec_ids = await self._generate_summary(
                question, retrieved, parsed,
            )
            # Filter all content to only what the LLM identified
            if relevant_rec_ids:
                relevant_sections = {
                    rid.split("(")[0] for rid in relevant_rec_ids
                }
                # IDs with parens are entry-level (recs or individual
                # RSS entries). Bare section IDs are section-level.
                entry_ids = {
                    rid for rid in relevant_rec_ids if "(" in rid
                }
                filtered = RetrievedContent(
                    raw_query=retrieved.raw_query,
                    parsed_query=retrieved.parsed_query,
                    source_types=retrieved.source_types,
                    sections=retrieved.sections,
                    recommendations=[
                        r for r in retrieved.recommendations
                        if _rec_id(r) in entry_ids
                    ],
                    synopsis={
                        sec: text
                        for sec, text in retrieved.synopsis.items()
                        if sec in relevant_sections
                    },
                    rss=[
                        r for r in retrieved.rss
                        if _rss_id(r) in entry_ids
                        or (r.get("section", "") in relevant_sections
                            and not entry_ids)
                    ],
                    knowledge_gaps={
                        sec: text
                        for sec, text in retrieved.knowledge_gaps.items()
                        if sec in relevant_sections
                    },
                    tables=retrieved.tables,
                    figures=retrieved.figures,
                )
                logger.info(
                    "Step 4: LLM filtered %d→%d recs, %d→%d rss "
                    "(relevant: %s)",
                    len(retrieved.recommendations),
                    len(filtered.recommendations),
                    len(retrieved.rss),
                    len(filtered.rss),
                    relevant_rec_ids,
                )
            else:
                # LLM didn't return rec IDs — use all
                filtered = retrieved
        else:
            summary = _fallback_summary(retrieved)
            filtered = retrieved

        # ── Detail section (Python, verbatim, filtered recs) ─────────
        detail = _build_detail(filtered)
        citations = _extract_citations(filtered)

        # Related sections: from filtered recs, or from synopsis if no recs
        seen_sections: list = []
        for rec in filtered.recommendations:
            sec = rec.get("section", "")
            if sec and sec not in seen_sections:
                seen_sections.append(sec)
        if not seen_sections and filtered.synopsis:
            for sec_id in filtered.synopsis:
                if sec_id not in seen_sections:
                    seen_sections.append(sec_id)

        # ── Output ────────────────────────────────────────────────────
        return {
            "summary": summary,
            "answer": detail,
            "citations": citations,
            "related_sections": seen_sections,
        }

    async def _generate_summary(
        self,
        question: str,
        retrieved: RetrievedContent,
        parsed: ParsedQAQuery,
    ) -> tuple:
        """Single LLM call: filter recs by relevance + write summary.

        Returns:
            (summary_text, relevant_rec_ids)
            relevant_rec_ids is a set of "section(recNumber)" strings,
            e.g. {"4.3(5)", "4.3(8)"}.
        """

        # ── Build content blocks for the LLM ─────────────────────────
        content_parts: List[str] = []

        # Recommendations (top N, with metadata)
        recs = retrieved.recommendations[:_MAX_RECS_FOR_LLM]
        if recs:
            content_parts.append("RECOMMENDATIONS:")
            for rec in recs:
                sec = rec.get("section", "")
                rec_num = rec.get("recNumber", "")
                cor = rec.get("cor", "")
                loe = rec.get("loe", "")
                text = rec.get("text", "")
                content_parts.append(
                    f"  [{sec}({rec_num})] "
                    f"(COR {cor}, LOE {loe}): {text}"
                )

        # RSS / supporting evidence (top N, truncated)
        # Label each entry with [section(recNumber)] so the LLM can
        # reference individual entries on the RELEVANT line.
        rss = retrieved.rss[:_MAX_RSS_FOR_LLM]
        if rss:
            content_parts.append("\nSUPPORTING EVIDENCE:")
            for entry in rss:
                sec = entry.get("section", "")
                rec_num = entry.get("recNumber", "")
                text = entry.get("text", "")
                if len(text) > _MAX_RSS_CHARS:
                    text = text[:_MAX_RSS_CHARS] + "..."
                entry_id = f"{sec}({rec_num})" if rec_num else sec
                content_parts.append(f"  [{entry_id}]: {text}")

        # Synopsis / narrative content (for table-based answers)
        # Table synopses can be long (Table 8 = 11k chars) — use a
        # higher limit since this may be the only content source.
        _MAX_SYN_CHARS = 6000
        if retrieved.synopsis:
            content_parts.append("\nGUIDELINE TEXT:")
            for sec_id, text in retrieved.synopsis.items():
                if len(text) > _MAX_SYN_CHARS:
                    text = text[:_MAX_SYN_CHARS] + "..."
                content_parts.append(f"  [{sec_id}]: {text}")

        # Knowledge gaps (top N, truncated)
        kg_items = list(retrieved.knowledge_gaps.items())[:_MAX_KG_FOR_LLM]
        if kg_items:
            content_parts.append("\nKNOWLEDGE GAPS:")
            for sec_id, text in kg_items:
                if len(text) > 500:
                    text = text[:500] + "..."
                content_parts.append(f"  [{sec_id}]: {text}")

        content_block = "\n".join(content_parts)

        # ── Prompt ───────────────────────────────────────────────────
        system_prompt = (
            "You are a stroke specialist colleague answering a question "
            "about the 2026 AHA/ASA AIS guidelines.\n\n"
            "You have two jobs:\n"
            "1. FILTER: From the content below, identify ONLY the "
            "sections and recommendations that semantically answer "
            "the question. Content is relevant if it directly "
            "addresses the clinical scenario — not just because it "
            "mentions a related term. A rec about EVT BP targets is "
            "NOT relevant to an IVT BP question.\n"
            "2. SUMMARIZE: Write a short clinical summary using only "
            "the relevant content.\n\n"
            "OUTPUT FORMAT (follow exactly):\n"
            "Line 1: RELEVANT: followed by comma-separated IDs from "
            "the content. For recommendations use the full ID, e.g. "
            "4.3(5). For supporting evidence or guideline text use "
            "the section ID, e.g. Table 8 or 4.6.1\n"
            "Line 2 onwards: Your clinical summary.\n\n"
            "SUMMARY RULES:\n"
            "- Plain text only. No markdown, no asterisks, no bold, "
            "no headers, no special formatting.\n"
            "- Use bullet points (plain dash -) to separate distinct items.\n"
            "- Parenthetical COR/LOE references inline, "
            "e.g. '...to reduce hemorrhagic complications "
            "(Rec 5, COR 1, LOE B-NR).'\n"
            "- Conversational but precise — like a brief consult answer.\n"
            "- Answer ONLY what was asked — nothing more. Do not add "
            "related information the user did not ask about. "
            "The user can ask a follow-up if needed.\n"
            "- Lead with the direct answer to the question.\n"
            "- Do NOT use filler words like 'importantly', 'notably', "
            "'it should be noted', 'according to the guidelines'.\n"
            "- State what the guideline says. Do NOT answer yes/no or "
            "draw conclusions the guideline does not explicitly state.\n"
            "- Do NOT interpret or add clinical opinions beyond what the "
            "guideline states.\n"
            "- Do NOT fabricate — if the content does not answer the "
            "question, say so plainly.\n"
            "- If knowledge gaps exist, note them briefly.\n"
            "- Keep it concise — a busy clinician should grasp the "
            "answer in under 30 seconds of reading.\n"
        )

        question_summary = parsed.question_summary or question

        user_message = (
            f"QUESTION: {question}\n"
            f"CLINICAL CONTEXT: {question_summary}\n\n"
            f"GUIDELINE CONTENT:\n{content_block}\n\n"
            "First line: RELEVANT: followed by the IDs of content that "
            "answers the question.\n"
            "Then: concise clinical summary in plain text."
        )

        try:
            response = self._client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1000,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
            )
            for block in response.content:
                if hasattr(block, "text"):
                    raw = block.text.strip()
                    relevant_ids, summary = _parse_relevant_and_summary(raw)
                    return summary, relevant_ids
        except Exception as e:
            logger.error("Summary generation failed: %s", e)

        return _fallback_summary(retrieved), set()


# ── Detail section (pure Python, verbatim) ────────────────────────────


_CATEGORY_LABELS = {
    "absolute_contraindication": "Absolute Contraindication",
    "relative_contraindication": "Relative Contraindication",
    "benefit_greater_than_risk": "Benefit Generally Greater Than Risk of Bleeding",
}


def _format_category(category: str) -> str:
    """Map RSS category slugs to clinician-facing labels."""
    return _CATEGORY_LABELS.get(category, "")


def _section_title(sec_id: str, retrieved: RetrievedContent) -> str:
    """Get section title from RSS or rec metadata."""
    for entry in retrieved.rss:
        if entry.get("section") == sec_id:
            title = entry.get("sectionTitle", "")
            if title:
                return title
    for rec in retrieved.recommendations:
        if rec.get("section") == sec_id:
            title = rec.get("sectionTitle", "")
            if title:
                return title
    return ""


def _build_detail(retrieved: RetrievedContent) -> str:
    """Build the verbatim detail section from retrieved content.

    Deterministic. No LLM. Every word comes directly from the
    guideline JSON — recs, RSS, KG — unmodified.

    Format matches frontend DETAILS & CITATIONS rendering:
        Recommendation {section} ({rec_num}) — {sectionTitle}
        Class of Recommendation: {COR} | Level of Evidence: {LOE}

        {verbatim text}

        Supporting Evidence: {verbatim RSS text}
    """
    parts: List[str] = []

    # ── Recommendations (ordered by Step 3 relevance score) ──────
    recs = retrieved.recommendations[:_MAX_RECS_FOR_DETAIL]
    for rec in recs:
        sec = rec.get("section", "")
        rec_num = rec.get("recNumber", "")
        sec_title = rec.get("sectionTitle", "")
        cor = rec.get("cor", "")
        loe = rec.get("loe", "")
        text = rec.get("text", "")

        parts.append(
            f"Recommendation {sec} ({rec_num}) — {sec_title} "
            f"Class of Recommendation: {cor} | Level of Evidence: {loe}"
        )
        parts.append("")
        parts.append(text)
        parts.append("")

    # ── Synopsis / guideline text (for table-based answers) ──────
    # Group RSS by section so we can pair headers with their evidence.
    rss = retrieved.rss[:_MAX_RSS_FOR_DETAIL]
    rss_by_section: Dict[str, List[Dict[str, Any]]] = {}
    for entry in rss:
        sec = entry.get("section", "")
        rss_by_section.setdefault(sec, []).append(entry)

    if retrieved.synopsis and not recs:
        for sec_id, text in retrieved.synopsis.items():
            # Header: use sectionTitle (already contains the section ID)
            sec_title = _section_title(sec_id, retrieved)
            if sec_title:
                parts.append(f"Guideline Text — {sec_title}")
            else:
                parts.append(f"Guideline Text — {sec_id}")
            parts.append("")

            # If RSS entries exist for this section, they ARE the
            # content — skip the synopsis body (which is structural
            # metadata like "Three categories of conditions...").
            sec_rss = rss_by_section.pop(sec_id, [])
            if sec_rss:
                for entry in sec_rss:
                    entry_text = entry.get("text", "")
                    if not entry_text:
                        continue
                    category = entry.get("category", "")
                    cat_label = _format_category(category)
                    if cat_label:
                        parts.append(f"{cat_label}:")
                        parts.append("")
                    parts.append(f"\u2022 {entry_text}")
                    parts.append("")
            else:
                # No RSS — show the synopsis body as content
                parts.append(text)
            parts.append("")

    # ── Remaining RSS not paired with a synopsis section ────────
    remaining_rss = []
    for sec_entries in rss_by_section.values():
        remaining_rss.extend(sec_entries)
    if remaining_rss:
        parts.append("Supporting Evidence:")
        parts.append("")
        for entry in remaining_rss:
            entry_text = entry.get("text", "")
            if not entry_text:
                continue
            category = entry.get("category", "")
            cat_label = _format_category(category)
            if cat_label:
                parts.append(f"{cat_label}:")
                parts.append("")
            parts.append(f"\u2022 {entry_text}")
            parts.append("")

    # ── Knowledge gaps ───────────────────────────────────────────
    if retrieved.knowledge_gaps:
        for _sec_id, text in retrieved.knowledge_gaps.items():
            parts.append(f"\u2022 Knowledge Gap: {text}")
        parts.append("")

    return "\n".join(parts)


def _extract_citations(retrieved: RetrievedContent) -> List[str]:
    """Extract citation strings matching the frontend GUIDELINE REFERENCES format.

    Format:
        Section {section} -- {sectionTitle} (COR {COR}, LOE {LOE})
        Section {section} -- {sectionTitle} (Recommendation-Specific Supportive Text)
    """
    citations: List[str] = []
    seen: set = set()

    # Recommendation citations
    for rec in retrieved.recommendations:
        sec = rec.get("section", "")
        sec_title = rec.get("sectionTitle", "")
        cor = rec.get("cor", "")
        loe = rec.get("loe", "")
        if sec:
            citation = f"Section {sec} -- {sec_title} (COR {cor}, LOE {loe})"
            if citation not in seen:
                seen.add(citation)
                citations.append(citation)

    # RSS citations — use sectionTitle directly (avoids redundancy)
    for rss in retrieved.rss:
        sec = rss.get("section", "")
        sec_title = rss.get("sectionTitle", "")
        if sec:
            label = sec_title if sec_title else sec
            citation = f"{label} (Supporting Evidence)"
            if citation not in seen:
                seen.add(citation)
                citations.append(citation)

    return citations


def _rec_id(rec: Dict[str, Any]) -> str:
    """Build a rec ID string like '4.3(5)' from a rec dict."""
    sec = rec.get("section", "")
    num = rec.get("recNumber", "")
    return f"{sec}({num})"


def _rss_id(entry: Dict[str, Any]) -> str:
    """Build an RSS entry ID like 'Table 8(severe-coagulopathy-or-thrombocytopenia)'."""
    sec = entry.get("section", "")
    num = entry.get("recNumber", "")
    return f"{sec}({num})" if num else sec


def _parse_relevant_and_summary(raw: str) -> tuple:
    """Parse LLM output into (relevant_rec_ids, summary_text).

    Expected format:
        RELEVANT: 4.3(5), 4.3(8)
        Summary text here...

    Returns:
        (set of rec ID strings, summary text)
    """
    lines = raw.strip().split("\n")
    relevant_ids: set = set()
    summary_start = 0

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.upper().startswith("RELEVANT:"):
            # Parse the comma-separated IDs after "RELEVANT:"
            id_part = stripped[len("RELEVANT:"):].strip()
            if id_part and id_part.upper() != "NONE":
                for token in id_part.split(","):
                    token = token.strip()
                    if token:
                        relevant_ids.add(token)
            summary_start = i + 1
            break

    # Everything after the RELEVANT line is the summary
    summary = "\n".join(lines[summary_start:]).strip()
    if not summary:
        summary = raw.strip()  # fallback: entire response is summary

    return relevant_ids, summary


def _fallback_summary(retrieved: RetrievedContent) -> str:
    """Simple summary when LLM is unavailable."""
    parts = []
    if retrieved.recommendations:
        parts.append(
            f"Found {len(retrieved.recommendations)} relevant "
            f"recommendation(s) from {len(retrieved.sections)} section(s)."
        )
    if retrieved.rss:
        parts.append(
            f"Supporting evidence from {len(retrieved.rss)} source(s)."
        )
    if retrieved.knowledge_gaps:
        parts.append("Knowledge gaps noted.")
    return " ".join(parts) if parts else "No relevant content found."
