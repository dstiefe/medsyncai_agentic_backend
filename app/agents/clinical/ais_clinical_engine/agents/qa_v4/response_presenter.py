# ─── v4 (Q&A v4 namespace) ─────────────────────────────────────────────
# Step 4: Present retrieved content to the clinician.
#
# Single LLM call. The LLM writes only the summary (bullets, clinical).
# Python builds the detail section (verbatim guideline content).
#
# Rules enforced by prompt:
#   - Summary: clear, concise, bullet points, clinical language
#   - The LLM does NOT interpret, editorialize, or paraphrase
#   - The LLM may only summarize — compress related points
#   - Detail: exact verbatim recs, RSS, KG (built by Python, not LLM)
# ───────────────────────────────────────────────────────────────────────
"""
Step 4: Response Presenter — one LLM call for summary, Python for detail.

Replaces RecSelectionAgent + RSSSummaryAgent + KGSummaryAgent +
QAAssemblyAgent with a single, simpler pipeline:

    1. Python builds the detail section from Step 3 retrieved content
       (verbatim recs with COR/LOE, RSS text, KG text)
    2. LLM reads the retrieved content and writes a clinical summary
       (bullet points, references rec numbers + COR/LOE)
    3. Combined: summary + detail = full answer
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

        Returns:
            {
                "summary": str,           # LLM-written clinical summary
                "detail": str,            # Python-built verbatim content
                "answer": str,            # summary + detail combined
                "citations": [str],
                "related_sections": [str],
            }
        """
        # ── Detail section (Python, deterministic, verbatim) ─────────
        detail = _build_detail(retrieved)
        citations = _extract_citations(retrieved)
        related_sections = [s.section_id for s in retrieved.sections]

        # ── Summary section (LLM) ───────────────────────────────────
        has_content = bool(
            retrieved.recommendations
            or retrieved.rss
            or retrieved.knowledge_gaps
        )
        if self._client and has_content:
            summary = await self._generate_summary(
                question, retrieved, parsed,
            )
        else:
            summary = _fallback_summary(retrieved)

        # ── Output ────────────────────────────────────────────────────
        # summary and answer are separate UI sections on the frontend:
        #   SUMMARY box → summary field
        #   DETAILS & CITATIONS box → answer field + citations field
        return {
            "summary": summary,
            "answer": detail,
            "citations": citations,
            "related_sections": related_sections,
        }

    async def _generate_summary(
        self,
        question: str,
        retrieved: RetrievedContent,
        parsed: ParsedQAQuery,
    ) -> str:
        """Single LLM call: read retrieved content, write a clinical summary."""

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
                    f"  [Section {sec}, Rec {rec_num}] "
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
            "You are presenting AIS (Acute Ischemic Stroke) guideline "
            "information to a clinician.\n\n"
            "Write a clear, concise clinical summary using bullet points.\n\n"
            "RULES:\n"
            "1. Talk directly to the clinician as a knowledgeable colleague\n"
            "2. Use bullet points to separate distinct items\n"
            "3. Reference recommendation numbers and COR/LOE when citing "
            "specific guidelines (e.g. 'Rec 5, COR 1, LOE A')\n"
            "4. Do NOT interpret or add clinical opinions beyond what the "
            "guideline states\n"
            "5. Do NOT editorialize — no 'importantly', 'notably', "
            "'it should be noted'\n"
            "6. Do NOT paraphrase recommendations — you may compress "
            "related points into one bullet but use the guideline's "
            "own language\n"
            "7. Do NOT add caveats or warnings the guideline does not "
            "include\n"
            "8. If knowledge gaps exist, note them briefly in a "
            "separate bullet\n"
            "9. Keep it concise — a busy clinician should grasp the "
            "answer in under 30 seconds of reading\n"
            "10. If the retrieved content does not answer the question, "
            "say so plainly — do NOT fabricate an answer\n"
        )

        question_summary = parsed.question_summary or question

        user_message = (
            f"QUESTION: {question}\n"
            f"CLINICAL CONTEXT: {question_summary}\n\n"
            f"GUIDELINE CONTENT:\n{content_block}\n\n"
            "Write a concise clinical summary using bullet points. "
            "Reference recommendation numbers and COR/LOE."
        )

        try:
            response = self._client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=800,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
            )
            for block in response.content:
                if hasattr(block, "text"):
                    return block.text.strip()
        except Exception as e:
            logger.error("Summary generation failed: %s", e)

        return _fallback_summary(retrieved)


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
