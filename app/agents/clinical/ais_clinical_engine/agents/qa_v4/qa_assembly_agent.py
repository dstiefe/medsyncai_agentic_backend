# ─── v4 (Q&A v4 namespace) ─────────────────────────────────────────────
# This file lives under agents/qa_v4/ and is the active v4 copy of the
# Guideline Q&A pipeline. The previous location agents/qa_v3/ has been
# archived to agents/_archive_qa_v3/ and is no longer imported anywhere.
# v4 changes: unified Step 1 pipeline — 38 intents from
# intent_content_source_map.json, anchor_terms as Dict[str, Any]
# (term → value/range), values_verified, rescoped clarification.
# ───────────────────────────────────────────────────────────────────────
"""
Q&A Assembly Agent — formats Guideline Q&A responses.

This is the assembly agent for the Guideline Q&A module ONLY.
Clarification for vague queries is handled upstream in the
orchestrator (vagueness gate). This agent focuses on formatting.

The pipeline:
    Python routes to section → pulls recs/RSS/KG
    → 3 LLMs pick recs, summarize RSS, summarize KG
    → 4th LLM generates conversational summary
    → THIS agent formats the final response

Conversation history is passed through to the summary LLM so
follow-up questions have context from prior turns.

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
from ...data.loader import load_guideline_knowledge


# ── Table 8 verbatim listing helpers ─────────────────────────────────
#
# When the user asks a general listing question about IVT
# contraindications ("What are the absolute contraindications for
# IVT?"), we surface the verbatim Table 8 synopsis from
# guideline_knowledge.json instead of routing through recs/RSS —
# recs/RSS don't contain the table content, and the LLM summary ends
# up degenerate when Table 8 isn't in the candidate sections.

_T8_LISTING_PHRASES = (
    "what are the", "what are all", "list the", "list all",
    "show me the", "show the", "show all",
    "what contraindication", "what are absolute", "what are relative",
    "name the", "tell me the contraindication",
    "tell me about the contraindication",
    "what does table 8", "what's in table 8",
    "all contraindication", "all the contraindication",
)

# Specific clinical conditions from Table 8 — if the question names one,
# it's a per-condition question, not a listing.
_T8_SPECIFIC_CONDITIONS = (
    "extra-axial", "extraaxial", "unruptured aneurysm", "moya-moya", "moyamoya",
    "procedural stroke", "remote gi", "remote gu", "history of gi bleeding",
    "history of mi", "recreational drug", "cocaine", "stroke mimic",
    "seizure at onset", "microbleed", "menstruation", "diabetic retinopathy",
    "intracranial hemorrhage", "hypodensity", "traumatic brain injury", "tbi",
    "neurosurgery", "spinal cord injury", "intra-axial", "intraaxial",
    "brain tumor", "glioma", "endocarditis", "coagulopathy",
    "aortic dissection", "aria", "amyloid", "lecanemab", "aducanumab",
    "doac within 48", "recent doac", "prior ich", "cervical dissection",
    "pregnancy", "pregnant", "postpartum", "post-partum",
    "active malignancy", "active cancer", "pre-existing disability",
    "vascular malformation", "avm", "cavernoma", "pericarditis",
    "cardiac thrombus", "dural puncture", "arterial puncture",
)


def _is_table8_listing(question: str) -> bool:
    """True if this is a general listing question about Table 8."""
    q = question.lower()
    if "contraindication" not in q and "table 8" not in q:
        return False
    if not any(p in q for p in _T8_LISTING_PHRASES):
        return False
    if any(c in q for c in _T8_SPECIFIC_CONDITIONS):
        return False
    return True


def _parse_table8_tier_rows(segment: str) -> List[tuple]:
    """
    Parse a tier segment from the verbatim Table 8 synopsis into a list
    of (label, description) tuples. The segment text is expected to look
    like:

      Conditions that are Considered Absolute Contraindications:

      CT with extensive hypodensity: IV thrombolysis should not...
      CT with hemorrhage: IV thrombolysis should not...
      ...

    Paragraphs are separated by blank lines. The label is everything
    before the first colon; the description is everything after.
    Paragraphs that look like the tier header or the abbreviation key
    footer are skipped.
    """
    rows: List[tuple] = []
    paragraphs = [p.strip() for p in segment.split("\n\n") if p.strip()]
    for p in paragraphs:
        # Skip the tier header itself
        if p.startswith("Conditions "):
            continue
        # Skip abbreviation-key footer ("AIS indicates acute ischemic stroke; ...")
        if " indicates " in p and p.rstrip().endswith("."):
            continue
        # Must have a "Label: description" shape
        if ":" not in p:
            continue
        label, _, desc = p.partition(":")
        label = label.strip()
        desc = desc.strip()
        if not label or not desc:
            continue
        rows.append((label, desc))
    return rows


def _format_table8_bullets(synopsis: str, question: str) -> str:
    """
    Format the verbatim Table 8 synopsis as a conversational bulleted
    answer scoped to the tier(s) the clinician asked about.

    Output shape (per tier):

        <conversational lead-in sentence for the tier>

        - **Label** — description text.
        - **Label** — description text.
        ...

    Multiple tiers (e.g., "list all contraindications") are stacked
    with a blank line between them. The table title, tier section
    headers, and abbreviation-key footer are stripped.
    """
    q = question.lower()
    wants_absolute = "absolute" in q
    wants_relative = "relative" in q and "absolute" not in q
    wants_benefit = any(t in q for t in (
        "benefit may exceed", "benefit over risk",
        "benefit outweigh", "benefit exceed", "benefit likely",
        "greater than risk",
    ))
    wants_all = not (wants_absolute or wants_relative or wants_benefit)

    # Split the verbatim synopsis on its three tier headers
    markers = [
        ("benefit", "Conditions in Which Benefits"),
        ("relative", "Conditions That are Relative Contraindications"),
        ("absolute", "Conditions that are Considered Absolute Contraindications"),
    ]
    positions = []
    for key, marker in markers:
        idx = synopsis.find(marker)
        if idx >= 0:
            positions.append((idx, key))
    positions.sort()
    if not positions:
        return synopsis

    segments: Dict[str, str] = {}
    for i, (start, key) in enumerate(positions):
        end = positions[i + 1][0] if i + 1 < len(positions) else len(synopsis)
        segments[key] = synopsis[start:end]

    # Conversational lead-ins per tier
    leads = {
        "absolute": (
            "These are the absolute contraindications to IV thrombolysis "
            "per the 2026 AHA/ASA AIS Guidelines."
        ),
        "relative": (
            "These are the relative contraindications to IV thrombolysis "
            "per the 2026 AHA/ASA AIS Guidelines."
        ),
        "benefit": (
            "These are the situations where the benefit of IV thrombolysis "
            "generally outweighs the bleeding risk per the 2026 AHA/ASA "
            "AIS Guidelines."
        ),
    }

    want_keys: List[str] = []
    if wants_all:
        want_keys = ["absolute", "relative", "benefit"]
    else:
        if wants_absolute:
            want_keys.append("absolute")
        if wants_relative:
            want_keys.append("relative")
        if wants_benefit:
            want_keys.append("benefit")

    blocks: List[str] = []
    for key in want_keys:
        if key not in segments:
            continue
        rows = _parse_table8_tier_rows(segments[key])
        if not rows:
            continue
        bullets = [f"- {label} — {desc}" for label, desc in rows]
        blocks.append(leads[key] + "\n\n" + "\n".join(bullets))

    if not blocks:
        return synopsis

    return "\n\n".join(blocks).strip()


class QAAssemblyAgent:
    """
    Formats Guideline Q&A responses.
    Vagueness clarification is handled upstream in the orchestrator.
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
        conversation_history: Optional[List[Dict[str, str]]] = None,
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

        # ── 0. Table 8 verbatim listing short-circuit ─────────────
        # General listing questions about IVT contraindications
        # ("What are the absolute contraindications for IVT?") should
        # surface the verbatim Table 8 synopsis from
        # guideline_knowledge.json — recs/RSS don't contain the
        # table content and routing through the LLM summary path
        # produces a degenerate answer.
        if _is_table8_listing(intent.question):
            try:
                gk = load_guideline_knowledge()
                t8 = gk.get("sections", {}).get("Table 8", {})
                synopsis = t8.get("synopsis", "")
                if synopsis:
                    sliced = _format_table8_bullets(synopsis, intent.question)
                    audit.append(AuditEntry(
                        step="qa_table8_verbatim",
                        detail={
                            "reason": "general_contraindication_listing",
                            "chars": len(sliced),
                        },
                    ))
                    return AssemblyResult(
                        status="complete",
                        answer=sliced,
                        summary=sliced,
                        citations=[
                            "Table 8 — Other Situations Wherein "
                            "Thrombolysis is Deemed to Be Considered "
                            "(2026 AHA/ASA AIS Guidelines)"
                        ],
                        related_sections=["Table 8"],
                        audit_trail=audit,
                    )
            except Exception as e:
                logger.warning("Table 8 short-circuit failed: %s", e)

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
                    conversation_history=conversation_history,
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
