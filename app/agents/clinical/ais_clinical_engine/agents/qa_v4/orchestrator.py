# ─── v4 (Q&A v4 namespace) ─────────────────────────────────────────────
# This file lives under agents/qa_v4/ and is the active v4 copy of the
# Guideline Q&A pipeline. The previous location agents/qa_v3/ has been
# archived to agents/_archive_qa_v3/ and is no longer imported anywhere.
# v4 changes: unified Step 1 pipeline — 44 intents,
# anchor_terms as Dict[str, Any] (term → value/range), values_verified, rescoped
# clarification. ParsedQAQuery backward-compat properties (question_type,
# search_keywords) keep this orchestrator working without modification.
# ───────────────────────────────────────────────────────────────────────
"""
QA Orchestrator — coordinates the unified v4 Q&A pipeline.

Pipeline (Steps 1 → 2 → 3 → 4):
    1. QAQueryParsingAgent (LLM): understand the question — intent,
       topic, anchor_terms with values, question_summary
    2. Step 1 Validator (Python): validate LLM output — intent in enum,
       topic in enum, anchor terms in vocabulary, values in question text
    3. Content Retriever (Python): route to sections + narrow content —
       intent → source types, topic → primary section, anchor terms →
       additional sections (scored by concept families + value metrics)
       CMI override: when patient variables present, match recs by
       trial eligibility criteria (replaces Step 3 recs when matched)
    4. Response Presenter: single LLM call writes clinical summary
       (bullet points, COR/LOE references). Python builds verbatim
       detail section (recs, RSS, KG exactly as in guideline).
       Output: summary (SUMMARY box) + detail (DETAILS & CITATIONS box)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .audit_logger import log_audit
from .query_parsing_agent import QAQueryParsingAgent
from .recommendation_matcher import RecommendationMatcher
from .response_presenter import ResponsePresenter
from .schemas import (
    AssemblyResult,
    AuditEntry,
    CMIMatchedRecommendation,
)
from .step1_validator import validate_step1_output, ValidationResult
from .content_retriever import retrieve_content, RetrievedContent
from .topic_verification_agent import TopicVerificationAgent

logger = logging.getLogger(__name__)

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
        self._recommendations_store = recommendations_store

        # ── CMI components ────────────────────────────────────────
        # Query parser uses the same Anthropic client as nlp_service
        llm_client = nlp_service.client if nlp_service else None
        self._query_parser = QAQueryParsingAgent(nlp_client=llm_client)

        # ── Topic verification agent ─────────────────────────────
        # Double-checks the classifier's topic pick before Python lookup
        self._topic_verifier = TopicVerificationAgent(nlp_client=llm_client)

        # ── Response presenter (single LLM call for summary) ─────
        self._presenter = ResponsePresenter(nlp_client=llm_client)

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

    @staticmethod
    def _count_clarification_rounds(history: List[Dict[str, str]]) -> int:
        """Count how many clarification rounds have occurred in this session.

        A round is an assistant turn with type=="clarification". We count
        these to enforce the max-2-rounds limit.
        """
        count = 0
        for turn in history:
            if turn.get("role") == "assistant" and turn.get("type") == "clarification":
                count += 1
        return count

    @staticmethod
    def _build_clarification_context(
        history: List[Dict[str, str]], current_question: str,
    ) -> Dict[str, Any]:
        """Detect if the current question is a reply to a prior clarification.

        If the last assistant turn was a clarification, this walks backward
        to find the original question and builds a merged context string
        that gives the Step 1 LLM the full picture.

        Returns:
            {
                "is_clarification_reply": bool,
                "original_question": str or None,
                "merged_question": str or None,
            }
        """
        if not history:
            return {"is_clarification_reply": False, "original_question": None, "merged_question": None}

        # Check if the last assistant turn was a clarification
        last_assistant = None
        for turn in reversed(history):
            if turn.get("role") == "assistant":
                last_assistant = turn
                break

        if not last_assistant or last_assistant.get("type") != "clarification":
            return {"is_clarification_reply": False, "original_question": None, "merged_question": None}

        # Walk backward to find the original user question (before the
        # clarification chain). Collect clarification exchanges along the way.
        exchanges = []  # [(assistant_question, user_reply)]
        original_question = None

        i = len(history) - 1
        while i >= 0:
            turn = history[i]
            if turn.get("role") == "assistant" and turn.get("type") == "clarification":
                # This is a clarification question from the assistant
                assistant_q = turn.get("content", "")
                # The next user turn (i+1) is the reply to this clarification,
                # but if this is the most recent clarification, the reply is
                # the current_question (not in history yet)
                if i + 1 < len(history) and history[i + 1].get("role") == "user":
                    user_reply = history[i + 1].get("content", "")
                else:
                    user_reply = None
                exchanges.append((assistant_q, user_reply))
                i -= 1
            elif turn.get("role") == "user":
                # This is the original question that started the chain
                original_question = turn.get("content", "")
                break
            else:
                i -= 1

        exchanges.reverse()  # chronological order

        if not original_question:
            # Couldn't find an original question — treat as normal
            return {"is_clarification_reply": False, "original_question": None, "merged_question": None}

        # Build the merged context string
        parts = [f"Original question: {original_question[:500]}"]
        for assistant_q, user_reply in exchanges:
            parts.append(f"\nYou asked: {assistant_q}")
            if user_reply:
                parts.append(f"User replied: {user_reply}")
        # The current question is the latest reply
        parts.append(f"\nUser replied: {current_question}")

        return {
            "is_clarification_reply": True,
            "original_question": original_question,
            "merged_question": "\n".join(parts),
        }

    async def answer(
        self,
        question: str,
        context: Optional[Dict[str, Any]] = None,
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """
        Answer a clinical question about AIS management.

        This is the main entry point that replaces answer_question()
        in qa_service.py.

        Args:
            question: the user's raw question
            context: optional patient context dict
            conversation_history: prior Q&A turns in this session,
                each {"role": "user"|"assistant", "content": str}

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
        _history = conversation_history or []

        # ── Clarification loop detection ─────────────────────────────
        # If the user is replying to a prior clarification we asked,
        # merge the original question + exchanges into context for Step 1.
        # After 2 rounds of clarification, force best-effort (no more asking).
        clarification_count = self._count_clarification_rounds(_history)
        clar_ctx = self._build_clarification_context(_history, question)
        _force_best_effort = clarification_count >= 2

        if clar_ctx["is_clarification_reply"]:
            logger.info(
                "Clarification reply detected (round %d, force_best_effort=%s). "
                "Original: '%s'",
                clarification_count + 1, _force_best_effort,
                clar_ctx["original_question"],
            )

        # ── Step 1: LLM classifier (primary) ──────────────────────────
        # The LLM understands the question and classifies it into
        # intent, topic, search_terms, anchor term values.
        # The deterministic IntentAgent is the fallback when LLM is unavailable.
        parsed_query = None
        cmi_used = False
        cmi_audit = {}

        if self._query_parser.is_available:
            try:
                # Pass merged context when replying to a clarification
                clarification_context = (
                    clar_ctx["merged_question"]
                    if clar_ctx["is_clarification_reply"]
                    else None
                )
                parsed_query, parse_usage = await self._query_parser.parse(
                    question, clarification_context=clarification_context,
                )
                cmi_audit["parse_usage"] = parse_usage
                cmi_audit["is_criterion_specific"] = parsed_query.is_criterion_specific
                cmi_audit["extraction_confidence"] = parsed_query.extraction_confidence
                cmi_audit["scenario_vars"] = parsed_query.get_scenario_variables()
                # Store the full LLM classifier output for the audit trail
                cmi_audit["llm_classifier"] = {
                    "intent": parsed_query.intent,
                    "topic": parsed_query.topic,
                    "qualifier": parsed_query.qualifier,
                    "question_summary": parsed_query.question_summary,
                    "anchor_terms": parsed_query.anchor_terms,
                    "has_anchor_values": parsed_query.has_anchor_values(),
                    "anchor_values": parsed_query.anchor_values,
                    "clarification": parsed_query.clarification,
                    "clarification_reason": parsed_query.clarification_reason,
                    "is_criterion_specific": parsed_query.is_criterion_specific,
                    "extraction_confidence": parsed_query.extraction_confidence,
                    "values_verified": parsed_query.values_verified,
                }
                logger.info(
                    "Step 1 (LLM): intent=%s topic=%s anchor_terms=%s",
                    parsed_query.intent, parsed_query.topic,
                    parsed_query.anchor_terms,
                )
            except Exception as e:
                logger.error("LLM classifier failed: %s", e)
                parsed_query = None

        # ── Step 2: Validate Step 1 output ────────────────────────────
        # Deterministic Python checks: intent in enum, topic in enum,
        # anchor terms in vocabulary, anchor term values in question text.
        # Catches LLM hallucination before it reaches routing.
        validation: Optional[ValidationResult] = None
        if parsed_query:
            validation = validate_step1_output(parsed_query, question)
            cmi_audit["step2_validation"] = validation.to_audit_dict()["detail"]
            logger.info(
                "Step 2 (validation): action=%s corrections=%d warnings=%d",
                validation.action,
                len(validation.corrections),
                len(validation.warnings),
            )

            # ── Step 2 says stop → return immediately ─────────────────
            if validation.action == "stop_out_of_scope":
                return AssemblyResult(
                    status="complete",
                    answer=validation.stop_message,
                    summary="Question is outside the scope of the AIS guideline.",
                    audit_trail=[
                        AuditEntry(step="step1_parse", detail=cmi_audit.get("llm_classifier", {})),
                        AuditEntry(**validation.to_audit_dict()),
                    ],
                ).to_dict()

            if validation.action == "stop_clarify" and not _force_best_effort:
                return AssemblyResult(
                    status="needs_clarification",
                    answer=validation.stop_message,
                    summary=validation.stop_message,
                    audit_trail=[
                        AuditEntry(step="step1_parse", detail=cmi_audit.get("llm_classifier", {})),
                        AuditEntry(**validation.to_audit_dict()),
                    ],
                ).to_dict()
            elif validation.action == "stop_clarify" and _force_best_effort:
                logger.warning(
                    "Step 2 wants clarification but max rounds reached — proceeding best-effort. "
                    "Message was: %s",
                    validation.stop_message,
                )

        # ── Step 1 clarification ────────────────────────────────────
        # If the Step 1 LLM said "I need to ask a clarifying question",
        # return early before routing or retrieval.
        if parsed_query and parsed_query.clarification and not _force_best_effort:
            logger.info(
                "Step 1 clarification (round %d): %s",
                clarification_count + 1, parsed_query.clarification,
            )
            return AssemblyResult(
                status="needs_clarification",
                answer=parsed_query.clarification,
                summary=parsed_query.clarification,
                audit_trail=[AuditEntry(
                    step="step1_clarification",
                    detail={
                        "clarification": parsed_query.clarification,
                        "clarification_reason": parsed_query.clarification_reason,
                        "clarification_round": clarification_count + 1,
                    },
                )],
            ).to_dict()
        elif parsed_query and parsed_query.clarification and _force_best_effort:
            logger.warning(
                "Max clarification rounds (%d) reached — proceeding best-effort. "
                "LLM wanted to ask: %s",
                clarification_count, parsed_query.clarification,
            )

        # ── Topic verification ───────────────────────────────────────
        # Sanity-check the LLM's topic classification before routing.
        # Gates: not_ais (reject), not_coherent (reject), wrong_topic
        # (correct). Must run BEFORE Step 3 so routing uses the
        # verified/corrected topic.
        if parsed_query and parsed_query.topic:
            verification_question = (
                clar_ctx["merged_question"]
                if clar_ctx["is_clarification_reply"]
                else question
            )
            verification = await self._topic_verifier.verify(
                verification_question,
                parsed_query.topic,
                parsed_query.qualifier,
                parsed_query={
                    "intent": parsed_query.intent,
                    "question_summary": parsed_query.question_summary,
                    "anchor_terms": list(parsed_query.anchor_terms.keys()),
                },
            )
            cmi_audit["verification"] = {
                "verdict": verification.verdict,
                "reason": verification.reason,
            }
            if verification.usage:
                cmi_audit["verification_usage"] = verification.usage

            if verification.verdict == "not_ais":
                logger.info("Verification: not_ais — %s", verification.reason)
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

            if verification.verdict == "not_coherent" and not _force_best_effort:
                logger.info("Verification: not_coherent — %s", verification.reason)
                return AssemblyResult(
                    status="needs_clarification",
                    answer=(
                        "I couldn't understand that as a clinical question. "
                        "Could you rephrase? For example: "
                        "\"What BP threshold for IVT?\" or "
                        "\"Is EVT recommended for M2 occlusion?\""
                    ),
                    summary="Could you rephrase that as a clinical question?",
                    audit_trail=[AuditEntry(
                        step="topic_verification",
                        detail={
                            "original_topic": parsed_query.topic,
                            "verdict": "not_coherent",
                            "reason": verification.reason,
                        },
                    )],
                ).to_dict()
            elif verification.verdict == "not_coherent" and _force_best_effort:
                logger.warning(
                    "Verification: not_coherent but force_best_effort — proceeding. %s",
                    verification.reason,
                )

            if verification.verdict == "wrong_topic":
                logger.warning(
                    "Verification: wrong_topic for '%s' — %s (suggested: %s)",
                    parsed_query.topic, verification.reason,
                    verification.suggested_topic,
                )
                if verification.suggested_topic:
                    parsed_query.topic = verification.suggested_topic
                    parsed_query.qualifier = None
                    logger.info(
                        "Re-routing to verifier suggestion: '%s'",
                        verification.suggested_topic,
                    )
                else:
                    parsed_query.topic = None

        # ── Step 3: Route to sections + narrowed retrieval ────────────
        # Runs AFTER topic verification so the topic is confirmed/corrected.
        # Two levels of scoring:
        #   Level 1: topic + anchor terms → scored sections (concept families)
        #   Level 2: anchor term values → narrowed content (structured metrics)
        retrieved: Optional[RetrievedContent] = None
        if parsed_query and validation and validation.action in ("proceed", "proceed_low_confidence"):
            retrieved = retrieve_content(
                parsed=parsed_query,
                raw_query=question,
                recommendations_store=self._recommendations_store,
                guideline_knowledge=self._guideline_knowledge,
            )
            cmi_audit["step3_retrieval"] = retrieved.to_audit_dict()["detail"]
            logger.info(
                "Step 3 (retrieval): %d sections, %d recs, %d rss, "
                "%d synopsis, %d tables, %d figures, source_types=%s",
                len(retrieved.sections),
                len(retrieved.recommendations),
                len(retrieved.rss),
                len(retrieved.synopsis),
                len(retrieved.tables),
                len(retrieved.figures),
                retrieved.source_types,
            )

        if not retrieved:
            # Steps 1-3 couldn't produce content — LLM parse failed or
            # validation rejected the query. Can't proceed.
            logger.warning("Steps 1-3 produced no content — returning clarification")
            return AssemblyResult(
                status="needs_clarification",
                answer=(
                    "I wasn't able to process that question. Could you rephrase it? "
                    "For example: \"What BP threshold for IVT?\" or "
                    "\"Is EVT recommended for M2 occlusion?\""
                ),
                summary="Could you rephrase that as a clinical question?",
                audit_trail=[
                    AuditEntry(step="step1_parse", detail=cmi_audit.get("llm_classifier", {})),
                    AuditEntry(step="step2_validation", detail=cmi_audit.get("step2_validation", {})),
                ],
            ).to_dict()

        # ── CMI override (patient-specific scenarios) ────────────────
        # When the user provides enough anchor term values (NIHSS, age,
        # ASPECTS, etc.), CMI matches recs by trial eligibility criteria.
        # CMI results REPLACE Step 3's recs when matched.
        _scenario_vars = parsed_query.get_scenario_variables()
        _has_patient_vars = len(_scenario_vars) >= 2 or any(
            v in _scenario_vars
            for v in (
                "time_window_hours", "nihss_range", "age_range",
                "aspects_range", "vessel_occlusion", "premorbid_mrs",
                "core_volume_ml",
            )
        )
        if (
            parsed_query.is_criterion_specific
            and parsed_query.extraction_confidence >= _CMI_CONFIDENCE_THRESHOLD
            and self._rec_matcher.is_available
            and _has_patient_vars
        ):
            cmi_matches = self._rec_matcher.match(parsed_query)
            if cmi_matches:
                # Replace Step 3 recs with CMI-matched recs, ordered by tier
                cmi_matches.sort(key=lambda m: (m.tier, -m.scope_index))
                retrieved.recommendations = [m.rec_data for m in cmi_matches]
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
                logger.info("CMI path: no matches — using Step 3 recs")

        # ── Step 4: Present (1 LLM call for summary, Python for detail)
        # The presenter reads the retrieved content and writes a clinical
        # summary (bullet points). Python builds the verbatim detail
        # section from the same content. No interpretation or paraphrasing.
        target_sections = [s.section_id for s in retrieved.sections]

        presenter_result = await self._presenter.present(
            question=question,
            retrieved=retrieved,
            parsed=parsed_query,
            conversation_history=_history,
        )

        result = AssemblyResult(
            status="complete",
            answer=presenter_result["answer"],
            summary=presenter_result["summary"],
            citations=presenter_result["citations"],
            related_sections=presenter_result["related_sections"],
            cmi_used=cmi_used,
        )

        logger.info(
            "Step 4 (presenter): summary=%d_chars detail=%d_chars "
            "citations=%d sections=%s cmi=%s",
            len(result.summary),
            len(result.answer),
            len(result.citations),
            target_sections[:5],
            cmi_used,
        )

        # ── Audit trail ──────────────────────────────────────────────
        if cmi_audit.get("llm_classifier"):
            result.audit_trail.append(AuditEntry(
                step="step1_llm_parse",
                detail=cmi_audit["llm_classifier"],
            ))

        if cmi_audit.get("verification"):
            result.audit_trail.append(AuditEntry(
                step="step1b_topic_verification",
                detail=cmi_audit["verification"],
            ))

        if cmi_audit.get("step2_validation"):
            result.audit_trail.append(AuditEntry(
                step="step2_validation",
                detail=cmi_audit["step2_validation"],
            ))

        if cmi_audit.get("step3_retrieval"):
            result.audit_trail.append(AuditEntry(
                step="step3_retrieval",
                detail=cmi_audit["step3_retrieval"],
            ))

        result.audit_trail.append(AuditEntry(
            step="step4_presenter",
            detail={
                "target_sections": target_sections,
                "source_types": retrieved.source_types,
                "rec_count": len(retrieved.recommendations),
                "rss_count": len(retrieved.rss),
                "kg_count": len(retrieved.knowledge_gaps),
                "synopsis_count": len(retrieved.synopsis),
                "citation_count": len(result.citations),
                "summary_length": len(result.summary),
                "detail_length": len(result.answer),
                "cmi_used": cmi_used,
            },
        ))

        logger.info(
            "QA complete: status=%s sections=%s cmi=%s",
            result.status,
            result.related_sections,
            cmi_used,
        )

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
