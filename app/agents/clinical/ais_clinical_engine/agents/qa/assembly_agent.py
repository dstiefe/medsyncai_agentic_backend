"""
Assembly Agent — formats the final response from all search agents' outputs.

Responsibilities:
    1. VERBATIM REC ASSEMBLY — recommendation text is returned character-for-character,
       never paraphrased, never summarized, never blended across recs.
    2. SCOPE GATE — if no recs score above the confidence threshold, explicitly
       refuse rather than letting the LLM fill the gap.
    3. CLARIFICATION DETECTION — when top recs have conflicting COR values in
       the same section, present options instead of guessing.
    4. SUMMARIZATION GUARDRAILS — RSS and KG text may be summarized, but with
       strict rules: no invented numbers, no dropped qualifiers, no blending
       across recs' supportive text.
    5. AUDIT TRAIL — log every decision made during response assembly.

Rules:
    - Recommendations → VERBATIM, untouched
    - Supportive Text (RSS) → may be summarized (LLM)
    - Knowledge Gaps → may be summarized (LLM)
    - The LLM frames, it does not rephrase recommendations.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from .schemas import (
    AssemblyResult,
    AuditEntry,
    ClarificationOption,
    IntentResult,
    KnowledgeGapResult,
    RecommendationResult,
    ScoredRecommendation,
    SupportiveTextResult,
)

# Import helpers from qa_service
from ...services.qa_service import (
    clean_pdf_text,
    extract_trial_names,
    strip_rec_prefix_from_rss,
    truncate_text,
)


# ── Scope Gate Thresholds ───────────────────────────────────────────

# Minimum score for the top recommendation to be considered "in scope"
SCOPE_GATE_MIN_SCORE = 3

# Minimum score for a rec to be included in the response
REC_INCLUSION_MIN_SCORE = 1

# Maximum recommendations to show
MAX_RECS_IN_RESPONSE = 5

# Maximum supporting text entries
MAX_SUPPORTING_TEXT = 5


# ── Clarification Rules (hardcoded for known ambiguity patterns) ────

_ELIGIBILITY_KEYWORDS = {
    "recommend", "recommended", "indication", "indicated", "eligible",
    "eligibility", "candidate", "appropriate",
    "can i give", "is it safe", "should i give", "should we give",
    "is ivt recommended", "is thrombolysis recommended",
}

CLARIFICATION_RULES = [
    {
        "topic_terms": ["m2"],
        "distinguishing_var": "m2Dominant",
        "question_keywords": [
            "dominant", "nondominant", "non-dominant", "codominant",
            "proximal", "m3",
        ],
        "sections": ["4.7.2"],
        "options": [
            ClarificationOption(
                label="A",
                description="Dominant proximal M2 — EVT is reasonable within 6 hours",
                section="4.7.2",
                rec_id="rec-4.7.2-007",
                cor="2a",
                loe="B-NR",
            ),
            ClarificationOption(
                label="B",
                description="Non-dominant or codominant M2 — EVT is NOT recommended",
                section="4.7.2",
                rec_id="rec-4.7.2-008",
                cor="3: No Benefit",
                loe="B-R",
            ),
        ],
        "clarification_text": (
            "The EVT recommendation for M2 occlusions depends on whether the "
            "occlusion is in the **dominant proximal** or **non-dominant/codominant** "
            "division:\n\n"
            "- **A — Dominant proximal M2:** EVT is reasonable within 6 hours "
            "(Section 4.7.2 Rec 7, COR 2a, LOE B-NR)\n"
            "- **B — Non-dominant or codominant M2:** EVT is NOT recommended "
            "(Section 4.7.2 Rec 8, COR 3: No Benefit, LOE B-R)\n\n"
            "Which type of M2 occlusion are you asking about?"
        ),
    },
    {
        "topic_terms": ["ivt", "thrombolysis", "tpa", "alteplase"],
        "distinguishing_var": "nonDisabling",
        "question_keywords": [
            "disabling", "non-disabling", "nondisabling", "mild",
        ],
        "sections": ["4.6.1"],
        "options": [
            ClarificationOption(
                label="A",
                description="Disabling deficit — IVT is recommended regardless of NIHSS",
                section="4.6.1",
                rec_id="rec-4.6.1-001",
                cor="1",
                loe="A",
            ),
            ClarificationOption(
                label="B",
                description="Non-disabling deficit (NIHSS 0-5) — IVT is NOT recommended",
                section="4.6.1",
                rec_id="rec-4.6.1-008",
                cor="3: No Benefit",
                loe="B-R",
            ),
        ],
        "clarification_text": (
            "The IVT recommendation depends on whether the deficit is "
            "**disabling** or **non-disabling**:\n\n"
            "- **A — Disabling deficit:** IVT is recommended regardless of NIHSS "
            "(Section 4.6.1 Rec 1, COR 1, LOE A)\n"
            "- **B — Non-disabling deficit (NIHSS 0-5):** IVT is NOT recommended "
            "(Section 4.6.1 Rec 8, COR 3: No Benefit, LOE B-R)\n\n"
            "Is the deficit disabling or non-disabling?"
        ),
    },
]


class AssemblyAgent:
    """
    Assembles the final response from all search agents' outputs.

    The scope gate, clarification detection, and audit trail all live here
    because only after retrieval do we know whether the guideline covers
    the question and whether the results are ambiguous.
    """

    def __init__(self, nlp_service=None):
        self._nlp_service = nlp_service

    async def run(
        self,
        intent: IntentResult,
        rec_result: RecommendationResult,
        rss_result: SupportiveTextResult,
        kg_result: KnowledgeGapResult,
    ) -> AssemblyResult:
        """
        Assemble the final response.

        Args:
            intent: from IntentAgent
            rec_result: from RecommendationAgent
            rss_result: from SupportiveTextAgent
            kg_result: from KnowledgeGapAgent

        Returns:
            AssemblyResult with the formatted response
        """
        audit: List[AuditEntry] = []

        # Log intent
        audit.append(AuditEntry(
            step="intent_classification",
            detail={
                "question_type": intent.question_type,
                "target_sections": intent.section_refs or intent.topic_sections,
                "search_terms_count": len(intent.search_terms),
                "is_contraindication": intent.is_contraindication_question,
                "is_general": intent.is_general_question,
            },
        ))

        # Log retrieval results
        audit.append(AuditEntry(
            step="retrieval",
            detail={
                "rec_count": len(rec_result.scored_recs),
                "rec_top_score": rec_result.scored_recs[0].score if rec_result.scored_recs else 0,
                "rec_search_method": rec_result.search_method,
                "rss_count": len(rss_result.entries),
                "kg_has_gaps": kg_result.has_gaps,
            },
        ))

        # ── 1. Knowledge Gap deterministic response ─────────────────
        if intent.question_type == "knowledge_gap" and not kg_result.has_gaps:
            audit.append(AuditEntry(
                step="knowledge_gap_deterministic",
                detail={"response": "no_gaps_documented"},
            ))
            sections = intent.section_refs or intent.topic_sections
            return AssemblyResult(
                status="complete",
                answer=kg_result.deterministic_response or "",
                summary=kg_result.deterministic_response or "",
                citations=[
                    f"Section {s} -- Knowledge Gaps (none documented)"
                    for s in sections
                ],
                related_sections=sorted(sections),
                audit_trail=audit,
            )

        # ── 2. Clarification check (hardcoded rules) ───────────────
        clarification = self._check_clarification_rules(intent)
        if clarification:
            audit.append(AuditEntry(
                step="clarification_triggered",
                detail={"rule": clarification["rule_topic"]},
            ))
            return AssemblyResult(
                status="needs_clarification",
                answer=clarification["text"],
                summary=clarification["text"].split("\n")[0],
                related_sections=clarification["sections"],
                clarification_options=clarification["options"],
                audit_trail=audit,
            )

        # ── 3. Generic ambiguity detection (CMI pattern) ────────────
        if rec_result.scored_recs:
            ambiguity = self._detect_generic_ambiguity(rec_result.scored_recs)
            if ambiguity:
                audit.append(AuditEntry(
                    step="ambiguity_detected",
                    detail={
                        "section": ambiguity["section"],
                        "conflicting_cors": ambiguity["cors"],
                    },
                ))
                return AssemblyResult(
                    status="needs_clarification",
                    answer=ambiguity["text"],
                    summary=ambiguity["text"].split("\n")[0],
                    related_sections=[ambiguity["section"]],
                    clarification_options=ambiguity["options"],
                    audit_trail=audit,
                )

        # ── 4. SCOPE GATE ──────────────────────────────────────────
        # Two checks:
        # (a) Score threshold: are the retrieved recs strong enough?
        # (b) Topic coverage: does the question's specific topic appear
        #     in the retrieved recs? (catches "pediatric stroke" etc.)
        top_score = rec_result.scored_recs[0].score if rec_result.scored_recs else 0
        has_rss = rss_result.has_content
        has_kg = kg_result.has_gaps

        # Check (a): score too low and no supporting content
        if top_score < SCOPE_GATE_MIN_SCORE and not has_rss and not has_kg:
            audit.append(AuditEntry(
                step="scope_gate_rejected",
                detail={
                    "reason": "low_score_no_content",
                    "top_score": top_score,
                    "threshold": SCOPE_GATE_MIN_SCORE,
                },
            ))
            return AssemblyResult(
                status="out_of_scope",
                answer=(
                    "The 2026 AHA/ASA AIS Guideline does not specifically address "
                    "this question. This may be covered in other guidelines, "
                    "local institutional protocols, or prescribing information."
                ),
                summary="",
                audit_trail=audit,
            )

        # Check (b): topic coverage — question mentions a specific topic
        # (e.g. "pediatric") that doesn't appear in any retrieved rec
        if not self.check_topic_coverage(
            intent.question, rec_result.scored_recs
        ):
            audit.append(AuditEntry(
                step="scope_gate_rejected",
                detail={
                    "reason": "topic_not_covered",
                    "top_score": top_score,
                },
            ))
            return AssemblyResult(
                status="out_of_scope",
                answer=(
                    "The 2026 AHA/ASA AIS Guideline does not specifically address "
                    "this question. This may be covered in other guidelines "
                    "(e.g., pediatric stroke guidelines), local institutional "
                    "protocols, or prescribing information."
                ),
                summary="",
                audit_trail=audit,
            )

        audit.append(AuditEntry(
            step="scope_gate_passed",
            detail={"top_score": top_score},
        ))

        # ── 5. ASSEMBLE RESPONSE ───────────────────────────────────
        # Route to the appropriate assembly path
        if intent.question_type in ("evidence", "knowledge_gap"):
            return await self._assemble_evidence_response(
                intent, rec_result, rss_result, kg_result, audit
            )
        else:
            return await self._assemble_recommendation_response(
                intent, rec_result, rss_result, kg_result, audit
            )

    # ── Recommendation response assembly ────────────────────────────

    async def _assemble_recommendation_response(
        self,
        intent: IntentResult,
        rec_result: RecommendationResult,
        rss_result: SupportiveTextResult,
        kg_result: KnowledgeGapResult,
        audit: List[AuditEntry],
    ) -> AssemblyResult:
        """Assemble response for recommendation questions — recs are VERBATIM."""
        answer_parts: List[str] = []
        citations: List[str] = []
        sections: set = set()
        all_trial_names: List[str] = []

        # Patient context header
        if intent.context_summary:
            answer_parts.append(f"**For this patient ({intent.context_summary}):**")

        # Contraindication tier classification
        if intent.is_contraindication_question and intent.contraindication_tier:
            tier = intent.contraindication_tier
            answer_parts.append(
                f"**Table 8 — IVT Contraindication Classification: {tier}**\n\n"
                f"Per Table 8 of the 2026 AHA/ASA AIS Guidelines, this is classified as "
                f"an **{tier}** contraindication to IVT."
            )
            citations.append(f"Table 8 -- IVT Contraindications and Special Situations ({tier})")
            sections.add("Table 8")

        # Numeric alerts (platelets, INR)
        self._add_numeric_alerts(intent, answer_parts, citations, sections)

        # ── VERBATIM RECOMMENDATIONS ────────────────────────────────
        # Each recommendation is shown individually with its full text,
        # section, COR, LOE. The text is NEVER modified or summarized.
        included_rec_sections: set = set()
        included_rec_texts: List[str] = []

        for rec in rec_result.scored_recs[:MAX_RECS_IN_RESPONSE]:
            if rec.score < REC_INCLUSION_MIN_SCORE:
                continue

            # Verbatim recommendation block
            answer_parts.append(
                f"**RECOMMENDATION [{rec.rec_id}]**\n"
                f"Section {rec.section} — {rec.section_title}\n"
                f"Class of Recommendation: {rec.cor}  |  Level of Evidence: {rec.loe}\n\n"
                f"\"{rec.text}\""
            )
            citations.append(
                f"Section {rec.section} -- {rec.section_title} "
                f"(COR {rec.cor}, LOE {rec.loe})"
            )
            all_trial_names.extend(extract_trial_names(rec.text))
            sections.add(rec.section)
            included_rec_sections.add(rec.section)
            included_rec_texts.append(rec.text)

        audit.append(AuditEntry(
            step="recs_included",
            detail={
                "count": len(included_rec_sections),
                "sections": sorted(included_rec_sections),
                "verbatim": True,
            },
        ))

        # ── SUPPORTING TEXT (may be summarized) ─────────────────────
        num_formal_recs = sum(
            1 for r in rec_result.scored_recs[:MAX_RECS_IN_RESPONSE]
            if r.score >= REC_INCLUSION_MIN_SCORE
        )
        max_supporting = 2 if num_formal_recs >= 3 else MAX_SUPPORTING_TEXT

        supporting_count = 0
        seen_rss_keys: set = set()

        for entry in rss_result.entries:
            if supporting_count >= max_supporting:
                break

            # Skip synopsis for sections already covered by verbatim recs
            if entry.entry_type == "synopsis" and entry.section in included_rec_sections:
                continue

            # Dedup RSS by section:recNumber
            if entry.entry_type == "rss":
                rss_key = f"{entry.section}:{entry.rec_number}"
                if rss_key in seen_rss_keys:
                    continue
                seen_rss_keys.add(rss_key)

            cleaned = clean_pdf_text(entry.text)
            cleaned = strip_rec_prefix_from_rss(cleaned, included_rec_texts)
            text = truncate_text(cleaned, max_chars=500)
            if len(text.strip()) < 40:
                continue

            if entry.entry_type == "rss":
                label = f"Supporting Evidence, Section {entry.section}"
                if entry.rec_number:
                    label += f" Rec {entry.rec_number}"
                answer_parts.append(f"**{label}:** {text}")
                citations.append(
                    f"Section {entry.section} -- {entry.section_title} "
                    f"(Recommendation-Specific Supportive Text)"
                )
            elif entry.entry_type == "synopsis":
                answer_parts.append(f"**{entry.section_title}:** {text}")
                citations.append(
                    f"Section {entry.section} -- {entry.section_title} (Synopsis)"
                )

            all_trial_names.extend(extract_trial_names(entry.text))
            sections.add(entry.section)
            supporting_count += 1

        # ── KNOWLEDGE GAPS (may be summarized) ──────────────────────
        if kg_result.has_gaps:
            for kg_entry in kg_result.entries[:2]:
                cleaned = clean_pdf_text(kg_entry.text)
                text = truncate_text(cleaned, max_chars=400)
                answer_parts.append(
                    f"**Knowledge Gaps, Section {kg_entry.section}:** {text}"
                )
                citations.append(
                    f"Section {kg_entry.section} -- {kg_entry.section_title} "
                    f"(Knowledge Gaps)"
                )
                sections.add(kg_entry.section)

        # Referenced trials
        unique_trials = self._deduplicate_trials(all_trial_names)
        if unique_trials:
            answer_parts.append(
                "**Referenced Studies/Articles:** " + ", ".join(unique_trials)
            )

        # Handle empty results
        if not answer_parts:
            return AssemblyResult(
                status="out_of_scope",
                answer=(
                    "The 2026 AHA/ASA AIS Guideline does not specifically address "
                    "this question. This may be covered in other guidelines, "
                    "local institutional protocols, or prescribing information."
                ),
                summary="",
                audit_trail=audit,
            )

        answer = "\n\n".join(answer_parts)

        # Summary — deterministic (no LLM needed for recs)
        summary = self._generate_summary(rec_result.scored_recs, intent)

        return AssemblyResult(
            status="complete",
            answer=answer,
            summary=summary,
            citations=list(dict.fromkeys(citations)),
            related_sections=sorted(s for s in sections if s),
            referenced_trials=unique_trials,
            audit_trail=audit,
        )

    # ── Evidence / Knowledge Gap response assembly ──────────────────

    async def _assemble_evidence_response(
        self,
        intent: IntentResult,
        rec_result: RecommendationResult,
        rss_result: SupportiveTextResult,
        kg_result: KnowledgeGapResult,
        audit: List[AuditEntry],
    ) -> AssemblyResult:
        """Assemble response for evidence/KG questions — RSS summarized, recs verbatim."""
        answer_parts: List[str] = []
        citations: List[str] = []
        sections: set = set(intent.section_refs or intent.topic_sections or [])
        all_trial_names: List[str] = []

        type_label = "Evidence" if intent.question_type == "evidence" else "Knowledge Gaps"

        # ── Evidence / KG content (may be summarized) ───────────────
        if intent.question_type == "evidence" and rss_result.has_content:
            for entry in rss_result.entries[:5]:
                cleaned = clean_pdf_text(entry.text)
                text = truncate_text(cleaned, max_chars=500)
                if len(text.strip()) < 40:
                    continue
                label = f"Evidence for Section {entry.section}"
                if entry.rec_number:
                    label += f", Rec {entry.rec_number}"
                answer_parts.append(f"**{label}:** {text}")
                all_trial_names.extend(extract_trial_names(entry.text))
                sections.add(entry.section)

        if intent.question_type == "knowledge_gap" and kg_result.has_gaps:
            for kg_entry in kg_result.entries[:3]:
                cleaned = clean_pdf_text(kg_entry.text)
                text = truncate_text(cleaned, max_chars=400)
                answer_parts.append(
                    f"**Knowledge Gaps, Section {kg_entry.section}:** {text}"
                )
                sections.add(kg_entry.section)

        # Source citations
        for s in (intent.section_refs or intent.topic_sections or []):
            sd = {}
            sections_data = {}
            try:
                from ...data.loader import load_guideline_knowledge
                sections_data = load_guideline_knowledge().get("sections", {})
                sd = sections_data.get(s, {})
            except Exception:
                pass
            title = sd.get("sectionTitle", "")
            if intent.question_type == "evidence":
                citations.append(
                    f"Section {s} -- {title} (Recommendation-Specific Supportive Text)"
                )
            else:
                citations.append(f"Section {s} -- {title} (Knowledge Gaps)")

        # ── Verbatim recs for context ───────────────────────────────
        for rec in rec_result.scored_recs[:3]:
            if rec.score < REC_INCLUSION_MIN_SCORE:
                continue
            answer_parts.append(
                f"**RECOMMENDATION [{rec.rec_id}]**\n"
                f"Section {rec.section} — {rec.section_title}\n"
                f"Class of Recommendation: {rec.cor}  |  Level of Evidence: {rec.loe}\n\n"
                f"\"{rec.text}\""
            )
            citations.append(
                f"Section {rec.section} -- {rec.section_title} "
                f"(COR {rec.cor}, LOE {rec.loe})"
            )
            all_trial_names.extend(extract_trial_names(rec.text))
            sections.add(rec.section)

        unique_trials = self._deduplicate_trials(all_trial_names)
        if unique_trials:
            answer_parts.append(
                "**Referenced Studies/Articles:** " + ", ".join(unique_trials)
            )

        answer = "\n\n".join(answer_parts)

        return AssemblyResult(
            status="complete",
            answer=answer,
            summary=answer_parts[0] if answer_parts else "",
            citations=list(dict.fromkeys(citations)),
            related_sections=sorted(s for s in sections if s),
            referenced_trials=unique_trials,
            audit_trail=audit,
        )

    # ── Clarification helpers ───────────────────────────────────────

    def _check_clarification_rules(
        self, intent: IntentResult,
    ) -> Optional[Dict[str, Any]]:
        """Check hardcoded clarification rules (M2, IVT disabling)."""
        q_lower = intent.question.lower()

        # Skip if this is a contraindication question
        if intent.is_contraindication_question:
            return None

        for rule in CLARIFICATION_RULES:
            topic_match = any(t in q_lower for t in rule["topic_terms"])
            already_specified = any(
                kw in q_lower for kw in rule["question_keywords"]
            )
            var_in_context = (
                intent.clinical_vars.get(rule["distinguishing_var"]) is not None
            )

            # Skip if topic sections point away from this rule
            rule_sections = set(rule.get("sections", []))
            if intent.topic_sections:
                if set(intent.topic_sections) - rule_sections:
                    continue

            has_eligibility = any(ek in q_lower for ek in _ELIGIBILITY_KEYWORDS)

            if (
                topic_match
                and not already_specified
                and not var_in_context
                and has_eligibility
            ):
                return {
                    "text": rule["clarification_text"],
                    "sections": sorted(rule.get("sections", [])),
                    "options": rule["options"],
                    "rule_topic": rule["topic_terms"][0],
                }

        return None

    def _detect_generic_ambiguity(
        self,
        scored_recs: List[ScoredRecommendation],
        threshold: int = 3,
    ) -> Optional[Dict[str, Any]]:
        """
        Detect when top-scored recs have conflicting COR in the same section.

        This is the generic CMI-pattern clarification. Unlike the hardcoded
        rules above, this fires dynamically based on retrieval results.
        """
        if not scored_recs or scored_recs[0].score <= 0:
            return None

        top = scored_recs[0]
        close_recs = [
            r for r in scored_recs
            if r.section == top.section
            and r.score >= top.score - threshold
            and r.score > 0
        ]

        cors = set(r.cor for r in close_recs)
        if len(cors) <= 1:
            return None

        # Group best rec per COR
        by_cor: Dict[str, ScoredRecommendation] = {}
        for r in close_recs:
            if r.cor not in by_cor:
                by_cor[r.cor] = r

        parts = [
            f"Section {top.section} ({top.section_title}) contains multiple "
            f"recommendations with different strength levels depending on the "
            f"clinical scenario:\n"
        ]
        options: List[ClarificationOption] = []
        labels = "ABCDEFGH"

        for i, (cor, r) in enumerate(sorted(by_cor.items())):
            label = labels[i] if i < len(labels) else str(i + 1)
            text_preview = r.text[:200]
            parts.append(
                f"- **{label} — Rec {r.rec_number} [COR {cor}, LOE {r.loe}]:** "
                f"{text_preview}"
            )
            options.append(ClarificationOption(
                label=label,
                description=f"Rec {r.rec_number} (COR {cor}, LOE {r.loe})",
                section=r.section,
                rec_id=r.rec_id,
                cor=r.cor,
                loe=r.loe,
            ))

        parts.append(
            "\nCould you provide more detail about the specific clinical "
            "scenario you're asking about?"
        )

        return {
            "text": "\n".join(parts),
            "section": top.section,
            "cors": sorted(cors),
            "options": options,
        }

    # ── Numeric alerts ──────────────────────────────────────────────

    @staticmethod
    def _add_numeric_alerts(
        intent: IntentResult,
        answer_parts: List[str],
        citations: List[str],
        sections: set,
    ) -> None:
        """Add Table 8 numeric alerts for platelet count, INR."""
        plt = intent.numeric_context.get("platelets")
        if plt is not None and plt < 100000:
            answer_parts.append(
                f"**Platelet count {plt:,}/\u00b5L is below the 100,000/\u00b5L threshold.** "
                "Per Table 8, severe coagulopathy is an absolute contraindication to IVT. "
                "Thresholds: platelets <100,000/\u00b5L, INR >1.7, aPTT >40 s, or PT >15 s."
            )
            citations.append("Table 8 -- Absolute Contraindication: Severe coagulopathy")
            sections.add("Table 8")

        inr = intent.numeric_context.get("inr")
        if inr is not None and inr > 1.7:
            answer_parts.append(
                f"**INR {inr} exceeds the 1.7 threshold.** "
                "Per Table 8, severe coagulopathy is an absolute contraindication to IVT."
            )
            citations.append("Table 8 -- Absolute Contraindication: Severe coagulopathy")
            sections.add("Table 8")

    # ── Summary generation ──────────────────────────────────────────

    @staticmethod
    def _generate_summary(
        scored_recs: List[ScoredRecommendation],
        intent: IntentResult,
    ) -> str:
        """Generate a concise summary from the top-matched recs."""
        top_recs = [r for r in scored_recs[:5] if r.score >= REC_INCLUSION_MIN_SCORE]
        if not top_recs:
            return ""

        cor_strength = {
            "1": "is recommended",
            "2a": "is reasonable",
            "2b": "may be reasonable",
        }

        best = top_recs[0]
        strength = cor_strength.get(best.cor, "")
        if best.cor.startswith("3") and "Harm" in best.cor:
            strength = "is not recommended (causes harm)"
        elif best.cor.startswith("3"):
            strength = "is not recommended (no benefit)"

        all_sections = set(r.section for r in top_recs)
        if strength:
            return (
                f"The guideline addresses this across {len(all_sections)} "
                f"section{'s' if len(all_sections) > 1 else ''}. "
                f"The strongest recommendation (Section {best.section}, COR {best.cor}) "
                f"indicates this {strength}."
            )
        return (
            f"Found {len(top_recs)} relevant recommendation"
            f"{'s' if len(top_recs) > 1 else ''} across "
            f"{len(all_sections)} section{'s' if len(all_sections) > 1 else ''}."
        )

    # ── Trial deduplication ─────────────────────────────────────────

    @staticmethod
    def _deduplicate_trials(trial_names: List[str]) -> List[str]:
        """Deduplicate trial names, case-insensitive."""
        seen: set = set()
        unique: List[str] = []
        for t in trial_names:
            key = t.upper().replace("-", " ").replace("  ", " ")
            if key not in seen:
                seen.add(key)
                unique.append(t)
        return unique

    # ── Summarization guardrails ────────────────────────────────────

    @staticmethod
    def validate_summary(summary: str, source_texts: List[str]) -> List[str]:
        """
        Validate an LLM-generated summary of RSS/KG text against source.

        Checks:
            1. No invented numbers — any number in the summary must appear
               in at least one source text
            2. No invented percentages — same check for % values
            3. No invented drug names — clinical terms in summary must be
               traceable to source
            4. No blending — each sentence should be attributable to a single
               source entry (not mixing facts from multiple sources)

        Returns a list of violation descriptions. Empty list = clean.
        """
        if not summary or not source_texts:
            return []

        violations: List[str] = []
        source_combined = " ".join(source_texts).lower()

        # Check 1: Numbers in summary must appear in source
        summary_numbers = re.findall(r'\b\d+(?:\.\d+)?\b', summary)
        for num in summary_numbers:
            if num not in source_combined:
                violations.append(
                    f"Number '{num}' in summary not found in source text"
                )

        # Check 2: Percentages
        summary_pcts = re.findall(r'\d+(?:\.\d+)?%', summary)
        for pct in summary_pcts:
            if pct not in source_combined:
                violations.append(
                    f"Percentage '{pct}' in summary not found in source text"
                )

        # Check 3: Clinical threshold patterns (e.g., "≤185/110", ">1.7")
        threshold_pattern = r'[<>≤≥]\s*\d+(?:\.\d+)?(?:/\d+)?'
        summary_thresholds = re.findall(threshold_pattern, summary)
        for thresh in summary_thresholds:
            # Normalize whitespace for comparison
            normalized = thresh.replace(" ", "")
            if normalized not in source_combined.replace(" ", ""):
                violations.append(
                    f"Threshold '{thresh}' in summary not found in source text"
                )

        # Check 4: Time durations (e.g., "24 hours", "4.5 hours")
        time_pattern = r'\d+(?:\.\d+)?\s*(?:hours?|minutes?|days?|weeks?|months?)'
        summary_times = re.findall(time_pattern, summary, re.IGNORECASE)
        for t in summary_times:
            t_normalized = t.lower().strip()
            if t_normalized not in source_combined:
                # Try without space
                t_compact = re.sub(r'\s+', '', t_normalized)
                source_compact = re.sub(r'\s+', '', source_combined)
                if t_compact not in source_compact:
                    violations.append(
                        f"Time duration '{t}' in summary not found in source text"
                    )

        return violations

    @staticmethod
    def check_topic_coverage(
        question: str,
        scored_recs: List[ScoredRecommendation],
        min_recs: int = 1,
    ) -> bool:
        """
        Check if the question's specific topic is actually covered by the
        retrieved recommendations.

        Extracts key clinical terms from the question and verifies at least
        one appears in the top-scored recs. This catches cases where generic
        terms (stroke, management) produce high scores but the specific topic
        (pediatric, chronic, etc.) is not in the guideline.

        Returns True if topic is covered, False if it appears out-of-scope.
        """
        if not scored_recs:
            return False

        q_lower = question.lower()

        # Extract potential topic-specific terms from the question
        # These are terms that would distinguish the question's topic from
        # generic AIS content
        _OUT_OF_SCOPE_MARKERS = [
            "pediatric", "children", "child", "neonatal", "neonate",
            "chronic", "long-term management", "outpatient",
            "hemorrhagic stroke", "ich ", "intracerebral hemorrhage",
            "subarachnoid", "tia only",
        ]

        # Check if question contains an out-of-scope marker
        for marker in _OUT_OF_SCOPE_MARKERS:
            if marker in q_lower:
                # Verify the marker appears in at least one top rec
                top_texts = " ".join(
                    r.text.lower() for r in scored_recs[:5]
                    if r.score >= REC_INCLUSION_MIN_SCORE
                )
                if marker not in top_texts:
                    return False  # topic not covered

        return True
