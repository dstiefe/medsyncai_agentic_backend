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
from .intent_agent import IntentAgent
from .knowledge_gap_agent import KnowledgeGapAgent
from .query_parsing_agent import QAQueryParsingAgent
from .recommendation_agent import RecommendationAgent
from .recommendation_matcher import RecommendationMatcher
from .schemas import (
    AssemblyResult,
    AuditEntry,
    RecommendationResult,
    ScoredRecommendation,
    CMIMatchedRecommendation,
)
from .section_index import build_section_concept_index
from .supportive_text_agent import SupportiveTextAgent

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

        # ── CMI components ────────────────────────────────────────
        # Query parser uses the same Anthropic client as nlp_service
        llm_client = nlp_service.client if nlp_service else None
        self._query_parser = QAQueryParsingAgent(nlp_client=llm_client)

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
        # ── Step 1: Intent classification (synchronous, deterministic) ──
        intent = self._intent_agent.run(question, context)

        logger.info(
            "QA intent: type=%s sections=%s terms=%d",
            intent.question_type,
            intent.section_refs or intent.topic_sections,
            len(intent.search_terms),
        )

        # ── Step 2: LLM query parsing (async, parallel with nothing) ────
        # Run on ALL questions — even non-criterion-specific questions
        # benefit from extracted variables for targeting RSS/KG search.
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
            except Exception as e:
                logger.error("Query parsing failed: %s", e)
                parsed_query = None

        # ── Use LLM's question_type when available ────────────────────────
        # The LLM understands natural language intent better than keyword
        # matching. "Is X an option for Y?" is evidence, not recommendation.
        # Fall back to deterministic classifier only when LLM is unavailable.
        question_type = intent.question_type  # deterministic fallback
        if parsed_query and parsed_query.question_type:
            question_type = parsed_query.question_type
            if question_type != intent.question_type:
                logger.info(
                    "LLM overrode question_type: %s → %s",
                    intent.question_type, question_type,
                )

        # ── Step 2b: Section routing (3 signals, merged) ──────────────────
        # 1. LLM target_sections (highest priority — LLM sees section guide)
        # 2. Content-based search (validates/supplements LLM choice)
        # 3. Deterministic topic map (fallback)
        #
        # The LLM picks sections from the Section Guide (e.g., "4.6.3" for
        # extended-window IVT).  Content search confirms this by scanning
        # actual RSS text.  Topic map fills gaps.  Result: focused sections
        # so the extraction LLM gets manageable, relevant content.
        topic_sections = intent.section_refs or intent.topic_sections or []

        # Prefer LLM search_keywords over deterministic extraction
        search_terms_for_content = intent.search_terms
        if parsed_query and parsed_query.search_keywords:
            search_terms_for_content = parsed_query.search_keywords
            logger.info("Using LLM search_keywords: %s", search_terms_for_content)

        # LLM-suggested sections (from Section Guide)
        llm_sections = []
        if parsed_query and parsed_query.target_sections:
            llm_sections = parsed_query.target_sections
            logger.info("LLM target_sections: %s", llm_sections)

        # Content-based search (validates LLM choice + catches misses)
        content_sections = []
        if self._guideline_knowledge:
            content_sections = self._find_sections_by_content(
                question, search_terms_for_content
            )

        # Merge: LLM sections first, then content search, then topic map
        seen = set()
        target_sections = []
        for s in llm_sections:
            if s not in seen:
                seen.add(s)
                target_sections.append(s)
        for s in content_sections:
            if s not in seen:
                seen.add(s)
                target_sections.append(s)
        for s in topic_sections:
            if s not in seen:
                seen.add(s)
                target_sections.append(s)

        logger.info(
            "Section routing: llm=%s content=%s topic_map=%s merged=%s type=%s",
            llm_sections, content_sections, topic_sections, target_sections,
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

        # CMI gate: require at least 2 scenario variables to avoid
        # misfiring on conceptual questions that only have "intervention".
        # Conceptual questions like "Is tPA safe for X?" extract
        # intervention=IVT but lack patient-specific variables (age,
        # NIHSS, time_window, vessel). The keyword path handles these
        # better because it matches on the specific concept (e.g.,
        # "glucose under 50") rather than broad criteria matching.
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
            # CMI path: match parsed variables against rec criteria
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
                # CMI found nothing — fall through to keyword path
                cmi_audit["cmi_matches"] = 0
                logger.info("CMI path: no matches, falling back to keyword")

        # Keyword fallback (default path)
        if rec_result is None:
            rec_result = await asyncio.to_thread(self._rec_agent.run, intent)

        logger.info(
            "QA retrieval: recs=%d method=%s cmi=%s",
            len(rec_result.scored_recs),
            rec_result.search_method,
            cmi_used,
        )

        # ── Step 4: RSS + KG in parallel ───────────────────────────────
        rss_result, kg_result = await asyncio.gather(
            asyncio.to_thread(self._rss_agent.run, intent),
            asyncio.to_thread(self._kg_agent.run, intent),
        )

        logger.info(
            "QA retrieval: rss=%d kg=%s",
            len(rss_result.entries),
            "yes" if kg_result.has_gaps else "no",
        )

        # ── Step 5: Assembly (scope gate, clarification, formatting) ────
        result = await self._assembly_agent.run(
            intent, rec_result, rss_result, kg_result
        )

        # Mark if CMI was used
        if cmi_used:
            result.cmi_used = True

        # Add CMI audit info
        if cmi_audit:
            result.audit_trail.append(
                AuditEntry(step="cmi_matching", detail=cmi_audit)
            )

        logger.info(
            "QA assembly: status=%s sections=%s cmi=%s",
            result.status,
            result.related_sections,
            cmi_used,
        )

        return result.to_dict()

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
