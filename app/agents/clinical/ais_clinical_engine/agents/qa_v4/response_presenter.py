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
            # Filter recs to only those the LLM identified as relevant
            if relevant_rec_ids:
                # Filter recs AND RSS to only what the LLM used
                relevant_sections = {
                    rid.split("(")[0] for rid in relevant_rec_ids
                }
                filtered = RetrievedContent(
                    raw_query=retrieved.raw_query,
                    parsed_query=retrieved.parsed_query,
                    source_types=retrieved.source_types,
                    sections=retrieved.sections,
                    recommendations=[
                        r for r in retrieved.recommendations
                        if _rec_id(r) in relevant_rec_ids
                    ],
                    synopsis={
                        sec: text
                        for sec, text in retrieved.synopsis.items()
                        if sec in relevant_sections
                    },
                    rss=[
                        r for r in retrieved.rss
                        if f"{r.get('section', '')}({r.get('recNumber', '')})"
                        in relevant_rec_ids
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
                    "Step 4: LLM filtered %d → %d recs (relevant: %s)",
                    len(retrieved.recommendations),
                    len(filtered.recommendations),
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
        rss = retrieved.rss[:_MAX_RSS_FOR_LLM]
        if rss:
            content_parts.append("\nSUPPORTING EVIDENCE:")
            for entry in rss:
                sec = entry.get("section", "")
                text = entry.get("text", "")
                if len(text) > _MAX_RSS_CHARS:
                    text = text[:_MAX_RSS_CHARS] + "..."
                content_parts.append(f"  [Section {sec}]: {text}")

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
                content_parts.append(f"  [Section {sec_id}]: {text}")

        content_block = "\n".join(content_parts)

        # ── Prompt ───────────────────────────────────────────────────
        system_prompt = (
            "You are a stroke specialist colleague answering a question "
            "about the 2026 AHA/ASA AIS guidelines.\n\n"
            "You have two jobs:\n"
            "1. FILTER: From the recommendations below, identify ONLY "
            "the ones that semantically answer the question. A rec is "
            "relevant if it directly addresses the clinical scenario — "
            "not just because it mentions a related term. A rec about "
            "EVT BP targets is NOT relevant to an IVT BP question. "
            "A rec about patients who 'did not receive IVT' is NOT "
            "relevant to IVT eligibility.\n"
            "2. SUMMARIZE: Write a short clinical summary using only "
            "the relevant recommendations.\n\n"
            "OUTPUT FORMAT (follow exactly):\n"
            "Line 1: RELEVANT: followed by comma-separated rec IDs "
            "from the content, e.g. RELEVANT: 4.3(5), 4.3(8)\n"
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
            "First line: RELEVANT: followed by the IDs of recs that "
            "answer the question.\n"
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
    if retrieved.synopsis and not recs:
        for sec_id, text in retrieved.synopsis.items():
            parts.append(f"Guideline Text — {sec_id}")
            parts.append("")
            parts.append(text)
            parts.append("")

    # ── Supporting evidence (RSS) ────────────────────────────────
    rss = retrieved.rss[:_MAX_RSS_FOR_DETAIL]
    if rss:
        # Combine RSS entries into one block
        rss_texts = [entry.get("text", "") for entry in rss if entry.get("text")]
        if rss_texts:
            parts.append(f"Supporting Evidence: {' '.join(rss_texts)}")
            parts.append("")

    # ── Knowledge gaps ───────────────────────────────────────────
    if retrieved.knowledge_gaps:
        kg_texts = list(retrieved.knowledge_gaps.values())
        parts.append(f"Knowledge Gaps: {' '.join(kg_texts)}")
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

    # RSS citations
    for rss in retrieved.rss:
        sec = rss.get("section", "")
        sec_title = rss.get("sectionTitle", "")
        if sec:
            citation = f"Section {sec} -- {sec_title} (Recommendation-Specific Supportive Text)"
            if citation not in seen:
                seen.add(citation)
                citations.append(citation)

    return citations


def _rec_id(rec: Dict[str, Any]) -> str:
    """Build a rec ID string like '4.3(5)' from a rec dict."""
    sec = rec.get("section", "")
    num = rec.get("recNumber", "")
    return f"{sec}({num})"


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
