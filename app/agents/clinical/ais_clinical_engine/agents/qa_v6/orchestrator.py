# ─── v6 (Q&A v6 namespace) ─────────────────────────────────────────────
# Orchestrator — wires the 4-step v6 pipeline:
#
#   Step 1: LLM query parse       (query_parsing_agent)
#   Step 2: Python validate       (step1_validator) + LLM topic verify
#                                 (topic_verification_agent)
#   Step 3: Unified retrieve      (retrieval.retrieve)
#   Step 4: LLM present           (presenter.present)
#
# If a patient scenario is present (age, NIHSS, LKW, etc.), the
# recommendation_matcher (CMI) is invoked as an auxiliary pass before
# Step 4 to annotate which retrieved recs actually apply to the patient.
# ───────────────────────────────────────────────────────────────────────
"""
qa_v6 orchestrator.

Single entry point: run(question, nlp_client) -> AssemblyResult dict.

This replaces the v4 orchestrator's 600+ line dispatcher with a linear
4-step flow. Each step's output is audit-trailed so failures are
diagnosable without rerunning.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from .presenter import present
from .query_parsing_agent import QAQueryParsingAgent
from .recommendation_matcher import RecommendationMatcher
from .retrieval import retrieve
from .schemas import AssemblyResult, AuditEntry, ParsedQAQuery
from .step1_validator import validate_step1_output
from .topic_verification_agent import TopicVerificationAgent

logger = logging.getLogger(__name__)


async def run(
    question: str,
    nlp_client=None,
    clarification_context: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Run the full qa_v6 pipeline against a clinician question.

    Args:
        question:              raw clinician question
        nlp_client:            Anthropic client (for Step 1 LLM parse
                               and Step 4 presenter). If None, returns
                               a deterministic-fallback result.
        clarification_context: when the user is replying to a prior
                               clarification question, this string
                               carries the merged prior context.

    Returns:
        dict — AssemblyResult.to_dict() output ready for the API.
    """
    audit: list[AuditEntry] = []

    # ── Step 1: LLM classification ────────────────────────────────
    parser = QAQueryParsingAgent(nlp_client=nlp_client)
    if not parser.is_available:
        logger.warning("qa_v6: LLM parser unavailable — returning fallback")
        return _fallback_unavailable(question, audit)

    parsed, usage = await parser.parse(
        question, clarification_context=clarification_context,
    )
    audit.append(AuditEntry(
        step="step1_parse",
        detail={
            "intent": parsed.intent,
            "topic": parsed.topic,
            "qualifier": parsed.qualifier,
            "anchor_terms": list(parsed.anchor_terms.keys()),
            "confidence": parsed.extraction_confidence,
            "tokens": usage,
        },
    ))

    # Early exit: Step 1 asked for clarification
    if parsed.clarification and not parsed.intent:
        result = AssemblyResult(
            status="needs_clarification",
            answer=parsed.clarification,
            summary=parsed.clarification,
            audit_trail=audit,
        )
        return result.to_dict()

    # ── Step 2a: Python validation ────────────────────────────────
    validation = validate_step1_output(parsed, raw_query=question)
    audit.append(AuditEntry(**validation.to_audit_dict()))

    if validation.action == "stop_out_of_scope":
        result = AssemblyResult(
            status="out_of_scope",
            answer=validation.stop_message or "",
            summary=validation.stop_message or "",
            audit_trail=audit,
        )
        return result.to_dict()

    if validation.action == "stop_clarify":
        result = AssemblyResult(
            status="needs_clarification",
            answer=validation.stop_message or "",
            summary=validation.stop_message or "",
            audit_trail=audit,
        )
        return result.to_dict()

    parsed = validation.query  # corrected

    # ── Step 2b: LLM topic verification ───────────────────────────
    #
    # The verdict now actively influences Step 3 scoring via the
    # topic-alignment bonus (W_TOPIC). Resolution rules:
    #   - confirmed          → use parsed.topic for the bonus
    #   - wrong_topic + suggestion → use suggested_topic for the bonus
    #   - wrong_topic only    → no bonus (don't trust either topic)
    #   - not_ais             → stop, out-of-scope
    #   - verifier unavailable → use parsed.topic as best-effort
    verified_topic: Optional[str] = parsed.topic or None

    verifier = TopicVerificationAgent(nlp_client=nlp_client)
    if verifier.is_available and parsed.topic:
        verdict = await verifier.verify(
            question=question,
            topic=parsed.topic,
            qualifier=parsed.qualifier,
            parsed_query={
                "intent": parsed.intent,
                "question_summary": parsed.question_summary,
            },
        )
        audit.append(AuditEntry(
            step="step2_verify",
            detail={
                "verdict": verdict.verdict,
                "reason": verdict.reason,
                "suggested_topic": verdict.suggested_topic,
                "tokens": verdict.usage,
            },
        ))
        if verdict.verdict == "not_ais":
            result = AssemblyResult(
                status="out_of_scope",
                answer=(
                    "This question falls outside the 2026 AHA/ASA "
                    "Acute Ischemic Stroke Guidelines."
                ),
                summary="Out of AIS guideline scope.",
                audit_trail=audit,
            )
            return result.to_dict()
        if verdict.verdict == "wrong_topic":
            if verdict.suggested_topic:
                verified_topic = verdict.suggested_topic
            else:
                # Ambiguous — disable the topic bonus so neither Step 1
                # nor Step 2b biases the scoring.
                verified_topic = None
        # confirmed: keep verified_topic = parsed.topic

    # ── Step 3: Unified retrieval ─────────────────────────────────
    content = retrieve(
        parsed=parsed,
        raw_query=question,
        verified_topic=verified_topic,
    )
    audit.append(AuditEntry(
        step="step3_retrieve",
        detail={
            "recommendations": len(content.recommendations),
            "rss": len(content.rss),
            "synopsis": len(content.synopsis) if isinstance(
                content.synopsis, (list, dict)) else 0,
            "knowledge_gaps": len(content.knowledge_gaps) if isinstance(
                content.knowledge_gaps, (list, dict)) else 0,
            "tables": len(content.tables),
            "figures": len(content.figures),
            "needs_clarification": content.needs_clarification,
        },
    ))

    # ── Optional: CMI matching when patient scenario present ──────
    # CMI matches against ALL recommendations in the criteria file —
    # not just the subset surfaced by retrieval — so it matches against
    # the process-wide cached store built from the unified atom index.
    # Retrieved recs are ONE view; CMI is a parallel matching pass
    # indexed by patient scenario variables.
    cmi_used = False
    if parsed.has_anchor_values():
        try:
            from . import semantic_service  # lazy module ref
            rec_store = semantic_service.get_recommendation_store()
            matcher = RecommendationMatcher()
            matcher.set_recommendation_store(rec_store)
            if matcher.is_available:
                cmi_matches = matcher.match(parsed)
                audit.append(AuditEntry(
                    step="cmi_match",
                    detail={
                        "matched": len(cmi_matches),
                        "store_size": len(rec_store),
                        "tiers": [m.tier for m in cmi_matches],
                    },
                ))
                cmi_used = bool(cmi_matches)
        except Exception as e:
            logger.warning("CMI matching failed: %s", e)
            audit.append(AuditEntry(
                step="cmi_match",
                detail={"error": str(e)},
            ))

    # ── Step 4: Present ───────────────────────────────────────────
    result = await present(content, nlp_client=nlp_client)
    result.audit_trail = audit
    result.cmi_used = cmi_used

    return result.to_dict()


def _fallback_unavailable(
    question: str,
    audit: list[AuditEntry],
) -> Dict[str, Any]:
    """Return a transient-failure response when the LLM parser can't run.

    Uses status="error" (NOT out_of_scope) — this is a service issue,
    not a scoping decision. The frontend renders different badges and
    may retry on error; out_of_scope is terminal.
    """
    msg = (
        "The Guideline Q&A service is temporarily unavailable. "
        "Please try again shortly."
    )
    result = AssemblyResult(
        status="error",
        answer=msg,
        summary=msg,
        audit_trail=audit,
    )
    return result.to_dict()


# ── Class wrapper preserving v4 QAOrchestrator interface ─────────────
#
# engine.py imports QAOrchestrator and calls `await orch.answer(q, ...)`.
# Swapping v4 → v6 therefore only needs an import-path change if the
# class interface is preserved. The v6 implementation delegates to
# run() above; the stores/rule_engine args are accepted for signature
# compatibility (v6 retrieval reads the unified atom index directly
# and does not need them).

class QAOrchestrator:
    """v6 orchestrator — same interface as v4 QAOrchestrator.

    Args are accepted for signature compatibility with engine.py's
    existing instantiation. v6 retrieval reads the unified atom file
    and does not use recommendations_store / guideline_knowledge /
    rule_engine — those remain passed for backward compatibility.
    """

    def __init__(
        self,
        recommendations_store: Optional[Dict[str, Any]] = None,
        guideline_knowledge: Optional[Dict[str, Any]] = None,
        rule_engine=None,
        nlp_service=None,
    ):
        self._nlp_service = nlp_service
        self._llm_client = nlp_service.client if nlp_service else None

    async def answer(
        self,
        question: str,
        context: Optional[Dict[str, Any]] = None,
        conversation_history: Optional[list] = None,
    ) -> Dict[str, Any]:
        """Main entry point. Returns dict matching engine.py expectations."""
        # Clarification context: if the last assistant turn was a
        # clarification question, concatenate the original + current
        # so Step 1 sees both.
        clarification_context = None
        if conversation_history:
            last_assistant = None
            for turn in reversed(conversation_history):
                if turn.get("role") == "assistant":
                    last_assistant = turn
                    break
            if last_assistant and last_assistant.get("type") == "clarification":
                # Find the original user question
                for turn in conversation_history:
                    if turn.get("role") == "user":
                        orig = turn.get("content", "")
                        clarification_context = (
                            f"Original question: {orig}\n"
                            f"Clarification: {last_assistant.get('content', '')}\n"
                            f"Reply: {question}"
                        )
                        break

        return await run(
            question=question,
            nlp_client=self._llm_client,
            clarification_context=clarification_context,
        )
