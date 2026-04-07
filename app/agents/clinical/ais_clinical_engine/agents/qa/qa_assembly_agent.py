"""
Q&A Assembly Agent — formats Guideline Q&A responses.

This is the assembly agent for the Guideline Q&A module ONLY.
It has NO gates, NO clarification logic, NO ambiguity detection.

The pipeline is simple:
    Python routes to section → pulls recs/RSS/KG
    → 3 LLMs pick recs, summarize RSS, summarize KG
    → 4th LLM generates summary
    → THIS agent formats the final response

The Clinical Scenario module uses the separate AssemblyAgent
in assembly_agent.py, which has scenario-specific gates.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

from .schemas import (
    AssemblyResult,
    AuditEntry,
    IntentResult,
    KnowledgeGapResult,
    RecommendationResult,
    ScoredRecommendation,
    SupportiveTextResult,
)

from ...services.qa_service import (
    clean_pdf_text,
    extract_trial_names,
    strip_rec_prefix_from_rss,
    truncate_text,
)


class QAAssemblyAgent:
    """
    Formats Guideline Q&A responses. No gates. No clarification.
    Section routing already validated the question is in scope.
    """

    def __init__(self, nlp_service=None):
        self._nlp_service = nlp_service

    async def run(
        self,
        intent: IntentResult,
        rec_result: RecommendationResult,
        rss_result: SupportiveTextResult,
        kg_result: KnowledgeGapResult,
        selected_rec_ids: Optional[List[str]] = None,
        rss_summary: Optional[str] = None,
        kg_summary: Optional[str] = None,
    ) -> AssemblyResult:
        """
        Assemble the Q&A response from all upstream outputs.

        No gates. No clarification. Just answer formatting.
        """
        audit: List[AuditEntry] = []
        answer_parts: List[str] = []
        citations: List[str] = []
        sections: set = set(intent.topic_sections or [])
        all_trial_names: List[str] = []

        # ── 1. BUILD LLM CONTEXT ──────────────────────────────────
        # Feed ALL recs + RSS + KG to the summary LLM so it sees
        # the full picture and can pick the most relevant answer.

        candidate_recs = rec_result.scored_recs
        all_qualifying_recs: List[ScoredRecommendation] = []
        rec_parts_for_llm: List[str] = []

        for rec in candidate_recs:
            if rec.score < 1:
                continue
            rec_block = (
                f"Recommendation {rec.section} ({rec.rec_number})\n"
                f"{rec.section_title}\n"
                f"Class of Recommendation: {rec.cor}  |  "
                f"Level of Evidence: {rec.loe}\n\n"
                f"{rec.text}"
            )
            rec_parts_for_llm.append(rec_block)
            all_qualifying_recs.append(rec)
            sections.add(rec.section)

        # RSS for LLM context
        rss_parts_for_llm: List[str] = []
        seen_rss_keys: set = set()
        all_rss_by_rec: dict = {}

        for entry in rss_result.entries:
            if entry.entry_type == "rss":
                rss_key = f"{entry.section}:{entry.rec_number}"
                if rss_key in seen_rss_keys:
                    continue
                seen_rss_keys.add(rss_key)

                cleaned = clean_pdf_text(entry.text)
                if len(cleaned.strip()) < 40:
                    continue

                label = f"Supporting Evidence, Section {entry.section}"
                if entry.rec_number:
                    label += f" Rec {entry.rec_number}"
                rss_parts_for_llm.append(f"{label}: {cleaned}")

                rn = str(entry.rec_number) if entry.rec_number else ""
                all_rss_by_rec.setdefault(rn, []).append({
                    "block": f"{label}: {truncate_text(cleaned, max_chars=800)}",
                    "citation": (
                        f"Section {entry.section} -- {entry.section_title} "
                        f"(Recommendation-Specific Supportive Text)"
                    ),
                    "entry": entry,
                })

            elif entry.entry_type == "synopsis":
                cleaned = clean_pdf_text(entry.text)
                rss_parts_for_llm.append(f"Synopsis: {cleaned}")

            sections.add(entry.section)

        # KG for LLM context
        kg_parts_for_llm: List[str] = []
        if kg_result.has_gaps:
            for kg_entry in kg_result.entries:
                cleaned = clean_pdf_text(kg_entry.text)
                kg_parts_for_llm.append(
                    f"Knowledge Gaps, Section {kg_entry.section}: {cleaned}"
                )
                sections.add(kg_entry.section)

        audit.append(AuditEntry(
            step="qa_assembly_context",
            detail={
                "recs": len(all_qualifying_recs),
                "rss": len(rss_parts_for_llm),
                "kg": len(kg_parts_for_llm),
                "sections": sorted(sections),
            },
        ))

        # ── 2. LLM SUMMARY ────────────────────────────────────────
        # The 4th LLM call: sees ALL content, generates the summary
        # the user sees at the top of the response.

        llm_context_parts = rec_parts_for_llm + rss_parts_for_llm + kg_parts_for_llm
        summary = ""
        cited_recs_from_llm = []

        if self._nlp_service and llm_context_parts:
            try:
                all_content = "\n\n".join(llm_context_parts)
                if len(all_content) > 20000:
                    all_content = all_content[:20000]

                logger.info(
                    "QA Assembly: calling summarize_qa, recs=%d rss=%d chars=%d",
                    len(rec_parts_for_llm), len(rss_parts_for_llm),
                    len(all_content),
                )

                llm_result = await self._nlp_service.summarize_qa(
                    question=intent.question,
                    details=all_content,
                    citations=[],
                    patient_context=intent.context_summary or "",
                )
                summary = llm_result.get("summary", "")
                cited_recs_from_llm = llm_result.get("cited_recs", [])

                if summary:
                    logger.info(
                        "QA Assembly: summary=%d chars, cited_recs=%s",
                        len(summary), cited_recs_from_llm,
                    )
            except Exception as e:
                logger.error("QA Assembly: LLM summary failed: %s", e)

        if not summary:
            summary = self._deterministic_summary(all_qualifying_recs, intent)

        # ── 3. SELECT RECS FOR DISPLAY ─────────────────────────────
        # Priority: RecSelectionAgent picks → LLM cited_recs → top by score
        # Plus safety net: always include top 2 keyword-scored recs.

        cited_rec_numbers = set()
        if selected_rec_ids:
            for rid in selected_rec_ids:
                parts = rid.split("-", 1)
                if len(parts) == 2:
                    cited_rec_numbers.add(parts[1].strip())
                else:
                    cited_rec_numbers.add(rid.strip())
        for r in cited_recs_from_llm:
            cited_rec_numbers.add(str(r))

        if cited_rec_numbers:
            # Build ordered list following RecSelectionAgent's ranking
            rec_by_number = {}
            for rec in all_qualifying_recs:
                rn = str(rec.rec_number).strip()
                key = f"{rec.section}-{rn}"
                rec_by_number[key] = rec
                if rn not in rec_by_number:
                    rec_by_number[rn] = rec

            recs_to_show = []
            seen = set()

            # First: RecSelectionAgent's picks (in order)
            if selected_rec_ids:
                for rid in selected_rec_ids:
                    rec = rec_by_number.get(rid)
                    if not rec:
                        parts = rid.split("-", 1)
                        if len(parts) == 2:
                            rec = rec_by_number.get(parts[1].strip())
                    if rec and id(rec) not in seen:
                        recs_to_show.append(rec)
                        seen.add(id(rec))

            # Second: LLM cited recs not already included
            for rn in cited_rec_numbers:
                rec = rec_by_number.get(rn)
                if rec and id(rec) not in seen:
                    recs_to_show.append(rec)
                    seen.add(id(rec))

            # Safety net: top 2 keyword-scored recs the LLMs missed
            extra = 0
            for rec in all_qualifying_recs:
                if extra >= 2:
                    break
                if id(rec) not in seen:
                    recs_to_show.append(rec)
                    seen.add(id(rec))
                    extra += 1

            self._add_recs_to_answer(
                recs_to_show, answer_parts, citations,
                all_trial_names, sections,
            )
        else:
            # No LLM citations — show top 5 by score
            self._add_recs_to_answer(
                all_qualifying_recs[:5], answer_parts, citations,
                all_trial_names, sections,
            )

        # ── 4. SUPPORTING EVIDENCE ─────────────────────────────────
        if rss_summary:
            answer_parts.append(f"Supporting Evidence: {rss_summary}")
            for rn in cited_rec_numbers:
                for rss_info in all_rss_by_rec.get(rn, []):
                    citations.append(rss_info["citation"])
                    all_trial_names.extend(
                        extract_trial_names(rss_info["entry"].text)
                    )
        elif cited_rec_numbers:
            for rn in cited_rec_numbers:
                for rss_info in all_rss_by_rec.get(rn, []):
                    answer_parts.append(rss_info["block"])
                    citations.append(rss_info["citation"])
                    all_trial_names.extend(
                        extract_trial_names(rss_info["entry"].text)
                    )

        # ── 5. KNOWLEDGE GAPS ──────────────────────────────────────
        if kg_summary:
            answer_parts.append(f"Knowledge Gaps: {kg_summary}")
            for kg_entry in kg_result.entries[:1]:
                citations.append(
                    f"Section {kg_entry.section} -- {kg_entry.section_title} "
                    f"(Knowledge Gaps)"
                )
        elif kg_result.has_gaps:
            for kg_entry in kg_result.entries:
                cleaned = clean_pdf_text(kg_entry.text)
                text = truncate_text(cleaned, max_chars=800)
                answer_parts.append(
                    f"Knowledge Gaps, Section {kg_entry.section}: {text}"
                )
                citations.append(
                    f"Section {kg_entry.section} -- {kg_entry.section_title} "
                    f"(Knowledge Gaps)"
                )

        # ── 6. REFERENCED TRIALS ───────────────────────────────────
        unique_trials = list(dict.fromkeys(
            t for t in all_trial_names if t
        ))
        if unique_trials:
            answer_parts.append(
                "Referenced Studies/Articles: " + ", ".join(unique_trials)
            )

        # ── 7. HANDLE EMPTY ────────────────────────────────────────
        if not answer_parts:
            return AssemblyResult(
                status="out_of_scope",
                answer=(
                    "The 2026 AHA/ASA AIS Guideline does not specifically "
                    "address this question. This may be covered in other "
                    "guidelines, local institutional protocols, or "
                    "prescribing information."
                ),
                summary="",
                audit_trail=audit,
            )

        # ── 8. FORMAT AND RETURN ───────────────────────────────────
        answer = "\n\n".join(answer_parts)
        citations_deduped = list(dict.fromkeys(citations))

        audit.append(AuditEntry(
            step="qa_assembly_complete",
            detail={
                "answer_parts": len(answer_parts),
                "citations": len(citations_deduped),
                "summary_len": len(summary),
            },
        ))

        return AssemblyResult(
            status="complete",
            answer=answer,
            summary=summary,
            citations=citations_deduped,
            related_sections=sorted(s for s in sections if s),
            referenced_trials=unique_trials,
            audit_trail=audit,
        )

    # ── Helpers ────────────────────────────────────────────────────

    @staticmethod
    def _add_recs_to_answer(
        recs: List[ScoredRecommendation],
        answer_parts: List[str],
        citations: List[str],
        all_trial_names: List[str],
        sections: set,
    ):
        """Add verbatim recommendation blocks to the answer."""
        for rec in recs:
            rec_block = (
                f"Recommendation {rec.section} ({rec.rec_number}) — "
                f"{rec.section_title}\n"
                f"Class of Recommendation: {rec.cor}  |  "
                f"Level of Evidence: {rec.loe}\n\n"
                f"{rec.text}"
            )
            answer_parts.append(rec_block)
            citations.append(
                f"Section {rec.section} -- {rec.section_title} "
                f"(COR {rec.cor}, LOE {rec.loe})"
            )
            sections.add(rec.section)
            all_trial_names.extend(extract_trial_names(rec.text))

    @staticmethod
    def _deterministic_summary(
        recs: List[ScoredRecommendation],
        intent: IntentResult,
    ) -> str:
        """Fallback summary when LLM is unavailable."""
        if not recs:
            return ""
        top = recs[0]
        return (
            f"The guideline addresses this in Section {top.section} "
            f"({top.section_title}), Recommendation {top.rec_number} "
            f"(COR {top.cor}, LOE {top.loe})."
        )
