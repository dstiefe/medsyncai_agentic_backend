"""
QA Orchestrator — coordinates the multi-agent Q&A pipeline.

Pipeline:
    1. IntentAgent: classify question, extract search parameters
    2. QAQueryParsingAgent: LLM-based variable extraction (async)
    3. Branching:
       - CMI path (criterion-specific): RecommendationMatcher ranks recs
         by applicability, same algorithm as Journal Search TrialMatcher
       - Keyword path (general/definitional): existing RecommendationAgent
    4. SupportiveTextAgent + KnowledgeGapAgent: run in parallel
    5. AssemblyAgent: combine results, apply scope gate, detect
       clarification, format verbatim recs + summarized RSS/KG

This replaces the monolithic answer_question() function in qa_service.py
with a modular, testable, multi-agent architecture.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from .assembly_agent import AssemblyAgent
from .qa_assembly_agent import QAAssemblyAgent
from .audit_logger import log_audit
from .intent_agent import IntentAgent
from .kg_summary_agent import KGSummaryAgent
from .knowledge_gap_agent import KnowledgeGapAgent
from .query_parsing_agent import QAQueryParsingAgent
from .rec_selection_agent import RecSelectionAgent
from .recommendation_agent import RecommendationAgent
from .recommendation_matcher import RecommendationMatcher
from .rss_summary_agent import RSSSummaryAgent
from .schemas import (
    AssemblyResult,
    AuditEntry,
    RecommendationResult,
    ScoredRecommendation,
    CMIMatchedRecommendation,
)
from .section_index import build_section_concept_index
from .section_router import SectionRouter
from .supportive_text_agent import SupportiveTextAgent
from .topic_verification_agent import TopicVerificationAgent

logger = logging.getLogger(__name__)

# ── CMI score mapping: tier → base score ─────────────────────────
# These scores slot CMI results into the existing scoring system
# so the AssemblyAgent's thresholds and formatting work unchanged.
_TIER_BASE_SCORE = {1: 100, 2: 80, 3: 60, 4: 40}

# Minimum confidence from the LLM parser to activate CMI path
_CMI_CONFIDENCE_THRESHOLD = 0.6


class QAOrchestrator:
    """
    Orchestrates the multi-agent Q&A pipeline.

    Usage:
        orchestrator = QAOrchestrator(
            recommendations_store=load_recommendations_by_id(),
            guideline_knowledge=load_guideline_knowledge(),
            rule_engine=rule_engine,
            nlp_service=nlp_service,
        )
        result = await orchestrator.answer(question, context)
    """

    def __init__(
        self,
        recommendations_store: Dict[str, Any],
        guideline_knowledge: Dict[str, Any],
        rule_engine=None,
        nlp_service=None,
        embedding_store=None,
    ):
        self._guideline_knowledge = guideline_knowledge
        self._nlp_service = nlp_service
        # Build section concept index from guideline data
        all_recs = list(recommendations_store.values())
        section_concepts = build_section_concept_index(
            all_recs, guideline_knowledge
        )
        logger.info(
            "Section concept index: %d sections, %d total concepts",
            len(section_concepts),
            sum(len(v) for v in section_concepts.values()),
        )

        self._intent_agent = IntentAgent(section_concepts=section_concepts)
        self._rec_agent = RecommendationAgent(
            recommendations_store=recommendations_store,
            rule_engine=rule_engine,
            embedding_store=embedding_store,
        )
        self._rss_agent = SupportiveTextAgent(
            guideline_knowledge=guideline_knowledge,
        )
        self._kg_agent = KnowledgeGapAgent(
            guideline_knowledge=guideline_knowledge,
        )
        self._assembly_agent = AssemblyAgent(
            nlp_service=nlp_service,
            guideline_knowledge=guideline_knowledge,
            recommendations_store=recommendations_store,
        )
        self._recommendations_store = recommendations_store

        # ── Q&A Assembly Agent (no gates, Q&A module only) ────────
        self._qa_assembly_agent = QAAssemblyAgent(nlp_service=nlp_service)

        # ── Section Router (deterministic, reference-file-driven) ─
        self._section_router = SectionRouter()

        # ── CMI components ────────────────────────────────────────
        # Query parser uses the same Anthropic client as nlp_service
        llm_client = nlp_service.client if nlp_service else None
        self._query_parser = QAQueryParsingAgent(nlp_client=llm_client)

        # ── Topic verification agent ─────────────────────────────
        # Double-checks the classifier's topic pick before Python lookup
        self._topic_verifier = TopicVerificationAgent(nlp_client=llm_client)

        # ── Focused agents (Step 5: parallel LLM processing) ─────
        self._rec_selector = RecSelectionAgent(nlp_client=llm_client)
        self._rss_summarizer = RSSSummaryAgent(nlp_client=llm_client)
        self._kg_summarizer = KGSummaryAgent(nlp_client=llm_client)

        # Recommendation matcher loads pre-extracted criteria
        self._rec_matcher = RecommendationMatcher()
        self._rec_matcher.set_recommendation_store(recommendations_store)

        # Log CMI availability
        if self._query_parser.is_available and self._rec_matcher.is_available:
            logger.info("CMI matching: enabled")
        else:
            reasons = []
            if not self._query_parser.is_available:
                reasons.append("no LLM client")
            if not self._rec_matcher.is_available:
                reasons.append("no criteria file")
            logger.info("CMI matching: disabled (%s)", ", ".join(reasons))

    def _find_sections_by_content(
        self, question: str, search_terms: List[str],
    ) -> List[str]:
        """Search ALL guideline RSS + synopsis + rec text for the question's
        distinctive key terms.  Scores each section by how many unique key
        terms appear in its content.  Returns the top sections ranked by
        relevance.  Fully deterministic — works for any question phrasing.

        search_terms may come from:
        - LLM search_keywords (preferred — clinically targeted)
        - Deterministic extract_search_terms (fallback)
        """
        from .assembly_agent import AssemblyAgent

        # Use provided search_terms directly (they may be LLM-curated
        # search_keywords), plus extract key terms from the question
        # to catch anything the LLM missed.
        key_terms = list(search_terms) if search_terms else []
        extracted = AssemblyAgent.extract_key_terms(question)
        # Merge extracted terms that aren't already covered
        key_lower = {t.lower() for t in key_terms}
        for t in extracted:
            if t.lower() not in key_lower:
                key_terms.append(t)
                key_lower.add(t.lower())
        if not key_terms:
            return []

        sections_data = self._guideline_knowledge.get("sections", {})
        section_scores: Dict[str, float] = {}

        # Score each section by key term hits in RSS + synopsis
        for sec_num, sec in sections_data.items():
            text_blob = ""
            for rss in sec.get("rss", []):
                text_blob += " " + rss.get("text", "")
            text_blob += " " + sec.get("synopsis", "")
            text_lower = text_blob.lower()

            # Count distinct key terms found + frequency bonus
            terms_found = 0
            freq_bonus = 0
            for term in key_terms:
                tl = term.lower()
                count = text_lower.count(tl)
                if count > 0:
                    terms_found += 1
                    # Frequency bonus (diminishing): each additional
                    # occurrence adds 0.1 up to +1.0
                    freq_bonus += min(count - 1, 10) * 0.1
            if terms_found > 0:
                section_scores[sec_num] = terms_found + freq_bonus

        # Also check recommendation text (lower weight)
        for rec_id, rec in self._recommendations_store.items():
            sec = rec.get("section", "")
            text = (rec.get("text", "") + " " + rec.get("sectionTitle", "")).lower()
            for term in key_terms:
                if term.lower() in text:
                    section_scores[sec] = section_scores.get(sec, 0) + 0.5

        if not section_scores:
            return []

        # Return top sections: include all within 60% of top score, max 3
        ranked = sorted(section_scores.items(), key=lambda x: -x[1])
        top_score = ranked[0][1]
        threshold = top_score * 0.4
        result = [sec for sec, score in ranked if score >= threshold][:3]
        return result

    async def answer(
        self,
        question: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Answer a clinical question about AIS management.

        This is the main entry point that replaces answer_question()
        in qa_service.py.

        Args:
            question: the user's raw question
            context: optional patient context dict

        Returns:
            dict matching the shape expected by engine.py:
            {
                "answer": str,
                "summary": str,
                "citations": [str],
                "relatedSections": [str],
                "referencedTrials": [str],
                "needsClarification": bool (optional),
                "clarificationOptions": [...] (optional),
                "auditTrail": [...] (optional),
                "cmiUsed": bool (optional),
            }
        """
        # ── Step 1: LLM classifier (primary) ──────────────────────────
        # The LLM understands the question and classifies it into
        # intent, topic, search_terms, clinical_variables.
        # The deterministic IntentAgent is the fallback when LLM is unavailable.
        parsed_query = None
        cmi_used = False
        cmi_audit = {}

        if self._query_parser.is_available:
            try:
                parsed_query, parse_usage = await self._query_parser.parse(question)
                cmi_audit["parse_usage"] = parse_usage
                cmi_audit["is_criterion_specific"] = parsed_query.is_criterion_specific
                cmi_audit["extraction_confidence"] = parsed_query.extraction_confidence
                cmi_audit["scenario_vars"] = parsed_query.get_scenario_variables()
                # Store the full LLM classifier output for the audit trail
                cmi_audit["llm_classifier"] = {
                    "intent": parsed_query.intent,
                    "topic": parsed_query.topic,
                    "qualifier": parsed_query.qualifier,
                    "question_type": parsed_query.question_type,
                    "question_summary": parsed_query.question_summary,
                    "search_keywords": parsed_query.search_keywords,
                    "clarification": parsed_query.clarification,
                    "has_clinical_variables": parsed_query.has_clinical_variables(),
                }
                logger.info(
                    "Step 1 (LLM): intent=%s topic=%s type=%s search_terms=%s",
                    parsed_query.intent, parsed_query.topic,
                    parsed_query.question_type, parsed_query.search_keywords,
                )
            except Exception as e:
                logger.error("LLM classifier failed: %s", e)
                parsed_query = None

        # Fallback: deterministic IntentAgent when LLM is unavailable
        intent = self._intent_agent.run(question, context)
        if not parsed_query:
            logger.info(
                "Step 1 (fallback): type=%s sections=%s terms=%d",
                intent.question_type,
                intent.section_refs or intent.topic_sections,
                len(intent.search_terms),
            )

        # ── Derive pipeline values from the primary source ────────────
        # LLM's JSON is the single source of truth. IntentAgent is fallback.
        question_type = (
            parsed_query.question_type if parsed_query
            else intent.question_type
        )
        search_terms_for_content = (
            parsed_query.search_keywords if parsed_query and parsed_query.search_keywords
            else intent.search_terms
        )

        # ── Step 2: Section routing (topic → section, like a calculator) ─
        # The LLM classifies the question into a topic from the Topic Guide.
        # Python looks up topic → section. Direct mapping, no keywords.
        # The section IS the filter — once resolved, we pull everything from it.

        target_sections = []
        topic_verified = False  # True when LLM topic was confirmed by verifier

        if parsed_query:
            # ── LLM needs clarification → return it immediately ──
            if parsed_query.clarification:
                logger.info(
                    "LLM requesting clarification: %s", parsed_query.clarification,
                )
                return AssemblyResult(
                    status="needs_clarification",
                    answer=parsed_query.clarification,
                    summary=parsed_query.clarification,
                    audit_trail=[AuditEntry(
                        step="topic_clarification",
                        detail={"clarification": parsed_query.clarification},
                    )],
                ).to_dict()

            # ── Topic classified → verify before Python lookup ──
            if parsed_query.topic:
                # Verification agent: sanity-check the classifier's pick
                # It confirms the topic is the right clinical area to look in.
                # It does NOT redirect or suggest alternatives — the downstream
                # system reads the actual section content and determines whether
                # the specific question is answered.
                verification = await self._topic_verifier.verify(
                    question,
                    parsed_query.topic,
                    parsed_query.qualifier,
                    parsed_query={
                        "intent": parsed_query.intent,
                        "question_summary": parsed_query.question_summary,
                        "search_terms": parsed_query.search_keywords,
                    },
                )
                cmi_audit["verification"] = {
                    "verdict": verification.verdict,
                    "reason": verification.reason,
                }
                if verification.usage:
                    cmi_audit["verification_usage"] = verification.usage

                if verification.verdict == "not_ais":
                    # Question is outside AIS guideline entirely
                    logger.info(
                        "Verification: not_ais — %s", verification.reason,
                    )
                    return AssemblyResult(
                        status="complete",
                        answer=(
                            "This question falls outside the scope of the "
                            "2026 AHA/ASA Acute Ischemic Stroke Guidelines. "
                            f"{verification.reason}"
                        ),
                        summary="Question is outside the scope of the AIS guideline.",
                        audit_trail=[AuditEntry(
                            step="topic_verification",
                            detail={
                                "original_topic": parsed_query.topic,
                                "verdict": "not_ais",
                                "reason": verification.reason,
                            },
                        )],
                    ).to_dict()

                if verification.verdict == "wrong_topic":
                    # Wrong clinical area — try verifier's suggested topic
                    # before falling through to keyword fallback
                    logger.warning(
                        "Verification: wrong_topic for '%s' — %s (suggested: %s)",
                        parsed_query.topic, verification.reason,
                        verification.suggested_topic,
                    )
                    if verification.suggested_topic:
                        # Re-route to the verifier's suggestion
                        parsed_query.topic = verification.suggested_topic
                        parsed_query.qualifier = None  # clear qualifier for fresh lookup
                        logger.info(
                            "Re-routing to verifier suggestion: '%s'",
                            verification.suggested_topic,
                        )
                    else:
                        parsed_query.topic = None  # clear so fallbacks can try

                # Proceed with confirmed topic → section lookup
                if parsed_query.topic:
                    target_sections = self._section_router.resolve_topic(
                        parsed_query.topic, parsed_query.qualifier,
                    )
                    # Mark as verified so keyword override doesn't clobber it
                    if target_sections and verification.verdict == "confirmed":
                        topic_verified = True
                    logger.info(
                        "Topic routing: topic='%s' qualifier='%s' → sections=%s (verdict=%s, verified=%s)",
                        parsed_query.topic, parsed_query.qualifier,
                        target_sections, verification.verdict, topic_verified,
                    )

            # ── Legacy fallback: LLM provided target_sections directly ──
            if not target_sections and parsed_query.target_sections:
                target_sections = self._section_router.validate_sections(
                    parsed_query.target_sections
                )

        # Deterministic topic map from intent agent as additional fallback
        if not target_sections:
            topic_sections = intent.section_refs or intent.topic_sections or []
            if topic_sections:
                target_sections = self._section_router.validate_sections(
                    topic_sections
                )

        # Last resort: content-based search
        if not target_sections and self._guideline_knowledge:
            target_sections = self._find_sections_by_content(
                question, search_terms_for_content
            )

        # ── Validate section against search terms ─────────────────
        # Only override when the section came from a FALLBACK path
        # (keyword search, legacy target_sections, etc.).
        # When the LLM topic was verified by TopicVerificationAgent,
        # the section is correct — keyword density is noise that
        # causes wrong-section routing (e.g. "tenecteplase vs alteplase"
        # → §3.2 Imaging instead of §4.6.2 Choice of Agent).
        if target_sections and search_terms_for_content and not topic_verified:
            all_section_ids = list(
                self._guideline_knowledge.get("sections", {}).keys()
            )
            best_sections, section_scores = self._section_router.rank_sections_by_search_terms(
                all_section_ids,
                search_terms_for_content,
                self._recommendations_store,
                self._guideline_knowledge,
            )

            if best_sections:
                llm_section = target_sections[0]
                llm_score = section_scores.get(llm_section, 0)
                best_section = best_sections[0]
                best_score = section_scores.get(best_section, 0)

                cmi_audit["section_validation"] = {
                    "llm_section": llm_section,
                    "llm_score": llm_score,
                    "best_section": best_section,
                    "best_score": best_score,
                    "overridden": best_section != llm_section and best_score > llm_score,
                    "top_5": {s: section_scores.get(s, 0) for s in best_sections[:5]},
                }

                if best_section != llm_section and best_score > llm_score:
                    logger.warning(
                        "Fallback section %s (score=%d) but %s scores higher (%d) — overriding",
                        llm_section, llm_score, best_section, best_score,
                    )
                    target_sections = [best_section]
                else:
                    logger.info(
                        "Fallback section %s confirmed (score=%d, best=%s score=%d)",
                        llm_section, llm_score, best_section, best_score,
                    )
        elif target_sections and topic_verified:
            logger.info(
                "Topic verified — skipping keyword override for sections=%s",
                target_sections,
            )

        logger.info(
            "Section routing: topic=%s qualifier=%s resolved=%s type=%s",
            parsed_query.topic if parsed_query else None,
            parsed_query.qualifier if parsed_query else None,
            target_sections,
            question_type,
        )

        if (
            question_type in ("evidence", "knowledge_gap")
            and target_sections
            and self._nlp_service
        ):
            from ...services.qa_service import gather_section_content

            # Evidence questions need ALL RSS content from the target section —
            # keyword filtering drops critical subgroup/trial data (e.g. HERMES,
            # large core trials). Skip filter so LLM sees full section content.
            is_evidence = question_type == "evidence"
            section_content = gather_section_content(
                self._guideline_knowledge, target_sections, search_terms_for_content,
                max_chars=12000 if is_evidence else 8000,
                skip_filter=is_evidence,
            )

            # Knowledge gaps: deterministic when empty (61/62 sections)
            if question_type == "knowledge_gap" and not section_content["has_knowledge_gaps"]:
                return AssemblyResult(
                    status="complete",
                    answer="No specific knowledge gaps are documented for this topic in the 2026 AHA/ASA AIS Guidelines.",
                    summary="No specific knowledge gaps are documented for this topic in the 2026 AHA/ASA AIS Guidelines.",
                    citations=[f"Section {s} -- Knowledge Gaps (none documented)" for s in target_sections],
                    related_sections=sorted(target_sections),
                    audit_trail=[AuditEntry(step="knowledge_gap_deterministic", detail={"sections": target_sections})],
                ).to_dict()

            # LLM extraction from section content
            llm_answer = await self._nlp_service.extract_from_section(
                question, section_content, question_type
            )

            # Retry with content-based section search if LLM says "no data"
            _NO_DATA_MARKERS = [
                "does not contain", "does not address", "no data",
                "no information", "no specific", "not mentioned",
                "not discussed", "not contain",
            ]
            if (
                llm_answer
                and is_evidence
                and any(m in llm_answer.lower() for m in _NO_DATA_MARKERS)
            ):
                alt_sections = self._find_sections_by_content(
                    question, search_terms_for_content
                )
                # Only retry if fallback found different sections
                alt_sections = [s for s in alt_sections if s not in target_sections]
                if alt_sections:
                    logger.info(
                        "Evidence retry: original=%s returned no-data, "
                        "trying fallback sections=%s",
                        target_sections, alt_sections,
                    )
                    retry_content = gather_section_content(
                        self._guideline_knowledge, alt_sections,
                        search_terms_for_content, max_chars=12000,
                        skip_filter=True,
                    )
                    if retry_content.get("rss"):
                        retry_answer = await self._nlp_service.extract_from_section(
                            question, retry_content, question_type
                        )
                        if retry_answer and not any(
                            m in retry_answer.lower() for m in _NO_DATA_MARKERS
                        ):
                            llm_answer = retry_answer
                            target_sections = alt_sections

            if llm_answer:
                # Also get the top rec for context (keyword path, quick)
                rec_result_for_context = await asyncio.to_thread(self._rec_agent.run, intent)
                top_rec = None
                if rec_result_for_context.scored_recs:
                    top_rec = rec_result_for_context.scored_recs[0]

                # Build response: LLM answer as summary, section content as details
                answer_parts = [llm_answer]
                citations = []
                sections_set = set(target_sections)

                for s in target_sections:
                    sd = self._guideline_knowledge.get("sections", {}).get(s, {})
                    title = sd.get("sectionTitle", "")
                    if question_type == "evidence":
                        citations.append(f"Section {s} -- {title} (Recommendation-Specific Supportive Text)")
                    else:
                        citations.append(f"Section {s} -- {title} (Knowledge Gaps)")

                if top_rec:
                    answer_parts.append(
                        f"RECOMMENDATION [{top_rec.rec_id}]\n"
                        f"Section {top_rec.section} — {top_rec.section_title}\n"
                        f"Class of Recommendation: {top_rec.cor}  |  Level of Evidence: {top_rec.loe}\n\n"
                        f"\"{top_rec.text}\""
                    )
                    citations.append(
                        f"Section {top_rec.section} -- {top_rec.section_title} "
                        f"(COR {top_rec.cor}, LOE {top_rec.loe})"
                    )
                    sections_set.add(top_rec.section)

                logger.info(
                    "Evidence extraction: type=%s sections=%s llm_len=%d",
                    question_type, target_sections, len(llm_answer),
                )

                return AssemblyResult(
                    status="complete",
                    answer="\n\n".join(answer_parts),
                    summary=llm_answer,
                    citations=citations,
                    related_sections=sorted(sections_set),
                    audit_trail=[
                        AuditEntry(step="evidence_extraction", detail={
                            "question_type": question_type,
                            "target_sections": target_sections,
                            "rss_count": len(section_content.get("rss", [])),
                            "llm_answer_len": len(llm_answer),
                        }),
                    ],
                ).to_dict()

            # LLM extraction failed — fall through to standard pipeline
            logger.warning("Evidence extraction failed, falling through to standard pipeline")

        # ── Step 3: Choose recommendation retrieval path ────────────────
        rec_result = None

        # ── Step 3: Choose recommendation retrieval path ────────────────
        #
        # Priority:
        #   1. CMI path (patient scenario with ≥2 variables)
        #   2. Section-routed retrieval (pull ALL recs from resolved sections)
        #   3. Keyword fallback (only if no sections resolved — rare)

        # CMI gate: require patient-specific variables
        _scenario_vars = (
            parsed_query.get_scenario_variables() if parsed_query else []
        )
        _has_patient_vars = len(_scenario_vars) >= 2 or any(
            v in _scenario_vars
            for v in (
                "time_window_hours", "nihss_range", "age_range",
                "aspects_range", "vessel_occlusion", "premorbid_mrs",
                "core_volume_ml",
            )
        )
        if (
            parsed_query
            and parsed_query.is_criterion_specific
            and parsed_query.extraction_confidence >= _CMI_CONFIDENCE_THRESHOLD
            and self._rec_matcher.is_available
            and _has_patient_vars
        ):
            cmi_matches = self._rec_matcher.match(parsed_query)

            if cmi_matches:
                rec_result = self._cmi_to_recommendation_result(cmi_matches)
                cmi_used = True
                cmi_audit["cmi_matches"] = len(cmi_matches)
                cmi_audit["tier_counts"] = {
                    t: sum(1 for m in cmi_matches if m.tier == t)
                    for t in (1, 2, 3, 4)
                    if any(m.tier == t for m in cmi_matches)
                }
                logger.info(
                    "CMI path: %d matches (T1=%d T2=%d T3=%d T4=%d)",
                    len(cmi_matches),
                    sum(1 for m in cmi_matches if m.tier == 1),
                    sum(1 for m in cmi_matches if m.tier == 2),
                    sum(1 for m in cmi_matches if m.tier == 3),
                    sum(1 for m in cmi_matches if m.tier == 4),
                )
            else:
                cmi_audit["cmi_matches"] = 0
                logger.info("CMI path: no matches, falling back")

        # Section-routed retrieval: pull ALL recs from resolved sections
        if rec_result is None and target_sections:
            section_recs = self._section_router.pull_section_recs(
                target_sections, self._recommendations_store
            )
            if section_recs:
                rec_result = self._section_recs_to_result(
                    section_recs, target_sections,
                    search_terms=search_terms_for_content,
                    question=question,
                )
                logger.info(
                    "Section-route path: %d recs from sections %s",
                    len(rec_result.scored_recs), target_sections,
                )

        # Keyword fallback (only when no sections resolved)
        if rec_result is None:
            logger.info("No sections resolved — falling back to keyword search")
            rec_result = await asyncio.to_thread(self._rec_agent.run, intent)

        logger.info(
            "QA retrieval: recs=%d method=%s cmi=%s",
            len(rec_result.scored_recs),
            rec_result.search_method,
            cmi_used,
        )

        # ── Step 4: RSS + KG from resolved sections ───────────────────
        # When sections are resolved, pull RSS/KG directly from those
        # sections instead of keyword-searching all sections.
        if target_sections:
            section_content = self._section_router.pull_section_content(
                target_sections, self._guideline_knowledge
            )
            from .schemas import SupportiveTextEntry, SupportiveTextResult
            from .schemas import KnowledgeGapEntry, KnowledgeGapResult

            rss_entries = [
                SupportiveTextEntry(
                    section=r["section"],
                    section_title=r["sectionTitle"],
                    rec_number=str(r["recNumber"]),
                    text=r["text"],
                )
                for r in section_content["rss"]
            ]
            rss_result = SupportiveTextResult(
                entries=rss_entries, has_content=bool(rss_entries)
            )

            kg_text = section_content.get("knowledge_gaps", "")
            kg_entries = []
            if kg_text:
                for sec_id in target_sections:
                    sd = self._guideline_knowledge.get("sections", {}).get(sec_id, {})
                    kg = sd.get("knowledgeGaps", "")
                    if kg:
                        kg_entries.append(KnowledgeGapEntry(
                            section=sec_id,
                            section_title=sd.get("sectionTitle", ""),
                            text=kg,
                        ))
            kg_result = KnowledgeGapResult(
                entries=kg_entries, has_gaps=bool(kg_entries)
            )
        else:
            rss_result, kg_result = await asyncio.gather(
                asyncio.to_thread(self._rss_agent.run, intent),
                asyncio.to_thread(self._kg_agent.run, intent),
            )

        logger.info(
            "QA retrieval: rss=%d kg=%s",
            len(rss_result.entries),
            "yes" if kg_result.has_gaps else "no",
        )

        # ── Step 5: Focused agents (parallel LLM processing) ──────────
        # Three agents run in parallel, each handling one slice of content:
        #   5a. RecSelectionAgent: picks which recs answer the question
        #   5b. RSSSummaryAgent: summarizes relevant RSS text
        #   5c. KGSummaryAgent: summarizes knowledge gaps
        # Their outputs feed into the assembly agent (Step 6).
        _q_summary = parsed_query.question_summary if parsed_query else question
        _intent_str = parsed_query.intent if parsed_query else (intent.question_type or "recommendation")

        # Run all three in parallel
        selected_rec_ids, rss_summary, kg_summary = await asyncio.gather(
            self._rec_selector.select(
                question=question,
                intent=_intent_str,
                question_summary=_q_summary,
                recs=rec_result.scored_recs,
            ),
            self._rss_summarizer.summarize(
                question=question,
                intent=_intent_str,
                question_summary=_q_summary,
                rss_entries=rss_result.entries,
                selected_rec_numbers=None,  # filled after rec selection
            ),
            self._kg_summarizer.summarize(
                question=question,
                intent=_intent_str,
                question_summary=_q_summary,
                kg_entries=kg_result.entries,
            ),
        )

        logger.info(
            "Step 5 agents: selected_recs=%s rss_summary=%d_chars kg_summary=%d_chars",
            selected_rec_ids,
            len(rss_summary),
            len(kg_summary),
        )

        # ── Step 6: Assembly ────────────────────────────────────────
        # Two separate assembly agents:
        #   - QAAssemblyAgent: Guideline Q&A module (section-routed)
        #     No gates, no clarification, just answer formatting.
        #   - AssemblyAgent: Clinical Scenario module (keyword fallback)
        #     Has scenario-specific gates, clarification, ambiguity detection.
        if parsed_query and parsed_query.topic:
            intent.topic = parsed_query.topic

        if target_sections:
            intent.topic_sections = target_sections
            intent.topic_sections_source = "topic_map"

        is_section_routed = rec_result.search_method == "section_route"

        if is_section_routed:
            # Q&A module: clean path, no scenario gates
            logger.info("Using QAAssemblyAgent (section-routed, no gates)")
            result = await self._qa_assembly_agent.run(
                intent, rec_result, rss_result, kg_result,
                selected_rec_ids=selected_rec_ids,
                rss_summary=rss_summary,
                kg_summary=kg_summary,
            )
        else:
            # Scenario module: full gate chain
            logger.info("Using AssemblyAgent (keyword fallback, with gates)")
            result = await self._assembly_agent.run(
                intent, rec_result, rss_result, kg_result,
                selected_rec_ids=selected_rec_ids,
                rss_summary=rss_summary,
                kg_summary=kg_summary,
            )

        # Mark if CMI was used
        if cmi_used:
            result.cmi_used = True

        # ── Full pipeline audit trail ────────────────────────────────
        # Every step of the pipeline is recorded so we can see exactly
        # what happened: LLM JSON, Python section search, rec retrieval,
        # focused agent outputs, and assembly summary.

        # Step 1: LLM Classifier output
        if cmi_audit.get("llm_classifier"):
            result.audit_trail.append(AuditEntry(
                step="step1_llm_classifier",
                detail=cmi_audit["llm_classifier"],
            ))

        # Step 1b: Topic verification
        if cmi_audit.get("verification"):
            result.audit_trail.append(AuditEntry(
                step="step1b_topic_verification",
                detail=cmi_audit["verification"],
            ))

        # Step 2: Section routing + Python validation
        result.audit_trail.append(AuditEntry(
            step="step2_section_routing",
            detail={
                "target_sections": target_sections,
                "question_type": question_type,
                "search_terms": search_terms_for_content,
                **(cmi_audit.get("section_validation", {})),
            },
        ))

        # Step 3: Recommendation retrieval
        result.audit_trail.append(AuditEntry(
            step="step3_rec_retrieval",
            detail={
                "method": rec_result.search_method,
                "total_recs": len(rec_result.scored_recs),
                "cmi_used": cmi_used,
                "recs": [
                    {
                        "rec_id": r.rec_id,
                        "section": r.section,
                        "cor": r.cor,
                        "loe": r.loe,
                        "score": r.score,
                        "text": r.text[:120] + "..." if len(r.text) > 120 else r.text,
                    }
                    for r in rec_result.scored_recs[:10]
                ],
            },
        ))

        # Step 4: RSS + Knowledge Gaps data retrieval
        result.audit_trail.append(AuditEntry(
            step="step4_rss_kg_retrieval",
            detail={
                "rss_count": len(rss_result.entries),
                "rss_sections": list({e.section for e in rss_result.entries}),
                "kg_has_gaps": kg_result.has_gaps,
                "kg_sections": [e.section for e in kg_result.entries],
            },
        ))

        # Step 5: Focused agents output
        result.audit_trail.append(AuditEntry(
            step="step5_focused_agents",
            detail={
                "rec_selection_agent": {
                    "selected_rec_ids": selected_rec_ids,
                },
                "rss_summary_agent": {
                    "summary_length": len(rss_summary),
                    "summary": rss_summary[:500] + "..." if len(rss_summary) > 500 else rss_summary,
                },
                "kg_summary_agent": {
                    "summary_length": len(kg_summary),
                    "summary": kg_summary[:500] + "..." if len(kg_summary) > 500 else kg_summary,
                },
            },
        ))

        # Step 6: Assembly result
        result.audit_trail.append(AuditEntry(
            step="step6_assembly",
            detail={
                "status": result.status,
                "related_sections": result.related_sections,
                "citation_count": len(result.citations),
                "summary_length": len(result.summary) if result.summary else 0,
                "answer_length": len(result.answer) if result.answer else 0,
            },
        ))

        logger.info(
            "QA assembly: status=%s sections=%s cmi=%s",
            result.status,
            result.related_sections,
            cmi_used,
        )

        # Write full pipeline audit to persistent log file
        result_dict = result.to_dict()
        log_audit(
            question=question,
            audit_entries=result_dict.get("auditTrail", []),
            extra={
                "status": result.status,
                "related_sections": result.related_sections,
                "cmi_used": cmi_used,
            },
        )

        return result_dict

    @staticmethod
    def _cmi_to_recommendation_result(
        cmi_matches: List[CMIMatchedRecommendation],
    ) -> RecommendationResult:
        """
        Convert CMI-matched recommendations to the standard
        RecommendationResult format that AssemblyAgent consumes.

        Score mapping: Tier 1 = 100, Tier 2 = 80, Tier 3 = 60, Tier 4 = 40
        Within each tier, scope_index provides secondary ordering.
        """
        scored_recs = []
        for match in cmi_matches:
            rec = match.rec_data
            base_score = _TIER_BASE_SCORE.get(match.tier, 40)
            # Add scope bonus (0-10 points) for finer ordering within tier
            scope_bonus = int(match.scope_index * 10)
            score = base_score + scope_bonus

            scored_recs.append(
                ScoredRecommendation(
                    rec_id=match.rec_id,
                    section=rec.get("section", ""),
                    section_title=rec.get("sectionTitle", ""),
                    rec_number=rec.get("recNumber", ""),
                    cor=rec.get("cor", ""),
                    loe=rec.get("loe", ""),
                    text=rec.get("text", ""),
                    score=score,
                    source="cmi",
                )
            )

        return RecommendationResult(
            scored_recs=scored_recs,
            search_method="cmi",
        )

    @staticmethod
    def _section_recs_to_result(
        section_recs: List[Dict[str, Any]],
        target_sections: List[str],
        search_terms: Optional[List[str]] = None,
        question: str = "",
    ) -> RecommendationResult:
        """
        Convert section-pulled recs to RecommendationResult.

        Recs are scored by how many distinct search terms they match.
        Recs that match 0 search terms are DROPPED — they are not
        relevant to the question. Remaining recs are ranked by score
        so the most relevant appear first.
        """
        from ...services.qa_service import score_recommendation

        scored_recs = []
        for rec in section_recs:
            cor = rec.get("cor", "")

            # Score by search term relevance — 0 means not relevant
            if search_terms:
                score = score_recommendation(
                    rec, search_terms,
                    question=question,
                    topic_sections=target_sections,
                )
                # Drop recs with 0 search term matches — they are noise
                if score == 0:
                    continue
            else:
                # No search terms available: COR-based ordering
                COR_SCORE = {
                    "1": 100, "2a": 80, "2b": 60,
                    "3:No Benefit": 30, "3:Harm": 20, "3": 30,
                }
                score = COR_SCORE.get(cor, 50)

            scored_recs.append(
                ScoredRecommendation(
                    rec_id=rec.get("recId", rec.get("rec_id", "")),
                    section=rec.get("section", ""),
                    section_title=rec.get("sectionTitle", ""),
                    rec_number=rec.get("recNumber", ""),
                    cor=cor,
                    loe=rec.get("loe", ""),
                    text=rec.get("text", ""),
                    score=score,
                    source="section_route",
                )
            )

        # Sort by search term relevance (highest first)
        scored_recs.sort(key=lambda r: -r.score)

        return RecommendationResult(
            scored_recs=scored_recs,
            search_method="section_route",
        )
