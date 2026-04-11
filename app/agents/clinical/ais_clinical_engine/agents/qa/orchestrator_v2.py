"""
QA Orchestrator v2 — deterministic, scaffolding-driven Q&A pipeline.

Pipeline:

    question
       │
       ▼
    deterministic_parser.parse_deterministic
       │     (keyword intent + topic + synonym sections + slots)
       ▼
    scaffolding_verifier.verify_parsed_query
       │     (resolve section families, enforce required_slots)
       ▼
    pipeline_v2.route_v2
       │     (review_flags guard — routable_only_when)
       ▼
    clarification_v2.decide_clarification_v2
       │     (pause here if required slots still missing; max 2 rounds)
       ▼
    focused_agents_v2.dispatch_focused_agent
       │     (numeric → parsed_values, text → verbatim recs)
       ▼
    pipeline_v2.assemble_v2
       │     (pure formatter; no LLM)
       ▼
    dict matching the contract routes.py expects

Zero LLM calls. Zero probabilistic logic. One source of truth:
data_dictionary.v2.json + guideline_topic_map.json + synonym_dictionary.v2.json
+ intent_catalog.json + guideline_knowledge.json.

All dispatch is pure Python. Every answer is traceable to a specific
section and rec number in the 2026 AHA/ASA AIS Guidelines.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .clarification_v2 import MAX_CLARIFICATION_ROUNDS, decide_clarification_v2
from .deterministic_parser import parse_deterministic
from .focused_agents_v2 import dispatch_focused_agent
from . import llm_deny_list, llm_fallback, llm_parser, llm_summarizer
from .llm_schema_validator import validate_llm_parse
from .pipeline_v2 import (
    assemble_denied,
    assemble_fallback,
    assemble_v2,
    route_v2,
)
from .scaffolding_loader import ScaffoldingBundle, get_scaffolding, validate_bundle
from .scaffolding_verifier import verify_parsed_query
from .schemas import ParsedQAQueryV2, VnIntent

logger = logging.getLogger(__name__)


class QAOrchestratorV2:
    """Deterministic Q&A orchestrator for the 2026 AIS Guidelines.

    The constructor accepts the same kwargs as the legacy QAOrchestrator
    so routes.py can swap implementations with a one-line change.
    Unused kwargs (recommendations_store, rule_engine, embedding_store,
    guideline_knowledge) are accepted for signature compatibility and
    ignored — the v2 pipeline reads directly from the scaffolding
    bundle and guideline_knowledge.json at the module level.
    """

    def __init__(
        self,
        recommendations_store: Optional[Dict[str, Any]] = None,
        guideline_knowledge: Optional[Dict[str, Any]] = None,
        rule_engine: Any = None,
        nlp_service: Any = None,
        embedding_store: Any = None,
    ) -> None:
        self._bundle: ScaffoldingBundle = get_scaffolding()

        # Fail loud on startup if the scaffolding has drifted.
        errors = validate_bundle(self._bundle)
        if errors:
            for e in errors:
                logger.error("scaffolding drift: %s", e)
            raise RuntimeError(
                f"Scaffolding bundle has {len(errors)} drift errors — "
                f"fix references/*.json before starting the server"
            )

        logger.info(
            "QAOrchestratorV2 ready — %d dd.v2 sections, %d gtm topics, "
            "%d intents, %d review-flagged sections",
            len(self._bundle.dd_sections),
            len(self._bundle.gtm_sections),
            len(self._bundle.intent_catalog.get("intents", {})),
            len(self._bundle.review_flagged_sections),
        )

    # ------------------------------------------------------------------
    # Public API — matches the legacy QAOrchestrator shape used by routes.py
    # ------------------------------------------------------------------

    async def answer(
        self,
        question: str,
        context: Optional[Dict[str, Any]] = None,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Answer one Q&A turn.

        Returns a dict matching the contract routes.py expects:

            {
                "status": "complete" | "needs_clarification",
                "answer": str,
                "summary": str,
                "citations": [str],
                "relatedSections": [str],
                "referencedTrials": [],
                "needsClarification": bool,       # when clarifying
                "clarificationOptions": [...],    # when clarifying
                "auditTrail": [{"step": ..., "detail": ...}],
            }
        """
        conversation_history = conversation_history or []
        context = context or {}

        # Audit trail for the LLM feature flags — populated as each
        # optional hybrid stage runs. Falls through to the response
        # builder so the dev log can see which path fired.
        llm_audit: Dict[str, Any] = {
            "parser_used": "deterministic",
            "parser_fallthrough_reason": None,
            "summarizer_used": False,
            "fallback_used": False,
            "deny_list_blocked": False,
        }

        # ── 1. Merge clarification reply with original question ────────
        merged_question = self._merge_clarification_context(
            question, conversation_history
        )

        # ── 2. Parse: LLM front-door (if enabled) then deterministic ───
        parsed: Optional[ParsedQAQueryV2] = None
        if llm_parser.is_enabled():
            llm_result = await llm_parser.parse_with_llm(
                merged_question, bundle=self._bundle,
            )
            llm_audit["llm_parser_latency_ms"] = llm_result.latency_ms
            llm_audit["llm_parser_input_tokens"] = llm_result.input_tokens
            llm_audit["llm_parser_output_tokens"] = llm_result.output_tokens
            if llm_result.parsed is not None:
                validation = validate_llm_parse(
                    llm_result.parsed, bundle=self._bundle,
                )
                if validation.ok:
                    parsed = llm_result.parsed
                    llm_audit["parser_used"] = "llm"
                    llm_audit["llm_parser_confidence"] = llm_result.confidence
                else:
                    llm_audit["parser_fallthrough_reason"] = (
                        f"schema_validation_failed: {validation.errors}"
                    )
                    logger.info(
                        "v2 LLM parse rejected by validator: %s",
                        validation.errors,
                    )
            else:
                llm_audit["parser_fallthrough_reason"] = (
                    llm_result.error or "llm_parse_empty"
                )

        if parsed is None:
            parsed = parse_deterministic(merged_question, bundle=self._bundle)

        logger.info(
            "v2 parse (%s): intent=%s topic=%s sections=%s slots=%s",
            llm_audit["parser_used"],
            parsed.intent.value, parsed.topic, parsed.sections, parsed.slots,
        )

        # ── 3. Out-of-scope hybrid branch ──────────────────────────────
        # If the parser said OOS, run the deny-list and optional
        # general-knowledge fallback BEFORE touching the in-scope
        # pipeline. This is the only place the LLM is allowed to answer
        # from general clinical knowledge.
        if parsed.intent == VnIntent.OUT_OF_SCOPE:
            return await self._handle_out_of_scope(
                parsed, merged_question, llm_audit,
            )

        # ── 4. Verifier: resolve section families + enforce slot contract
        verification = verify_parsed_query(parsed.to_dict(), self._bundle)

        # ── 5. Route with review_flags guard ───────────────────────────
        routed = route_v2(
            parsed, bundle=self._bundle,
            verifier_resolved=verification.resolved_sections,
        )

        # ── 6. Clarification decision (deterministic) ──────────────────
        # Count prior clarification rounds from history so we don't
        # exceed MAX_CLARIFICATION_ROUNDS.
        rounds_so_far = self._count_clarification_rounds(conversation_history)
        clar_decision = decide_clarification_v2(
            parsed, rounds_so_far=rounds_so_far, bundle=self._bundle,
        )

        if clar_decision.should_clarify and not verification.out_of_scope:
            logger.info(
                "v2 clarification round %d: missing=%s",
                clar_decision.round_after, clar_decision.missing_slots,
            )
            return self._build_clarification_response(
                parsed, clar_decision, verification.resolved_sections, routed,
            )

        # ── 7. Dispatch focused agent (numeric or verbatim-rec) ────────
        focused = await dispatch_focused_agent(
            parsed,
            resolved_sections=verification.resolved_sections,
            bundle=self._bundle,
            nlp_client=None,  # deterministic path never uses LLM
        )

        # ── 8. Optional LLM summarizer — plain-English reading aid ─────
        plain_summary = ""
        if (
            llm_summarizer.is_enabled()
            and focused.ok
            and focused.citations
            and not focused.used_parsed_values
        ):
            summ = await llm_summarizer.summarize_recs(
                merged_question,
                focused.citations,
                intent=parsed.intent,
            )
            llm_audit["summarizer_latency_ms"] = summ.latency_ms
            llm_audit["summarizer_input_tokens"] = summ.input_tokens
            llm_audit["summarizer_output_tokens"] = summ.output_tokens
            if summ.ok:
                plain_summary = summ.summary
                llm_audit["summarizer_used"] = True
            else:
                llm_audit["summarizer_error"] = summ.error

        # ── 9. Assemble the final answer ───────────────────────────────
        assembled = assemble_v2(
            parsed, focused, routed, plain_summary=plain_summary,
        )

        return self._build_answer_response(
            parsed, assembled, verification, llm_audit=llm_audit,
        )

    # ------------------------------------------------------------------
    # Out-of-scope hybrid branch
    # ------------------------------------------------------------------

    async def _handle_out_of_scope(
        self,
        parsed: ParsedQAQueryV2,
        merged_question: str,
        llm_audit: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Run deny-list → optional LLM fallback → assembled response.

        Order matters: the deny-list is deterministic and runs first so
        patient-specific treatment decisions never incur LLM latency or
        cost. If the question survives the deny-list AND the fallback
        feature flag is on, Claude Sonnet answers from general clinical
        knowledge with a mandatory banner + footer. Otherwise we return
        the canned out-of-scope decline from the in-scope assembler.
        """
        # Deterministic deny-list (always runs — no feature flag).
        deny_result = llm_deny_list.check_deny_list(merged_question)
        if deny_result.denied:
            llm_audit["deny_list_blocked"] = True
            llm_audit["deny_reasons"] = list(deny_result.reasons)
            assembled = assemble_denied(
                question=merged_question,
                decline_message=llm_deny_list.SAFE_DECLINE_MESSAGE,
                deny_reasons=deny_result.reasons,
                matched_decision=deny_result.matched_decision,
                matched_drug=deny_result.matched_drug,
            )
            return self._build_oos_response(parsed, assembled, llm_audit)

        # Optional general-knowledge fallback.
        if llm_fallback.is_enabled():
            fb = await llm_fallback.fallback_answer(merged_question)
            llm_audit["fallback_latency_ms"] = fb.latency_ms
            llm_audit["fallback_input_tokens"] = fb.input_tokens
            llm_audit["fallback_output_tokens"] = fb.output_tokens
            if fb.ok:
                llm_audit["fallback_used"] = True
                assembled = assemble_fallback(
                    question=merged_question,
                    fallback_answer_text=fb.answer,
                    fallback_header=llm_fallback.FALLBACK_HEADER,
                    fallback_footer=llm_fallback.FALLBACK_FOOTER,
                    audit={"parser_intent": parsed.intent.value},
                )
                return self._build_oos_response(parsed, assembled, llm_audit)
            llm_audit["fallback_error"] = fb.error

        # No fallback (flag off or LLM failed) → canned OOS decline.
        from .focused_agents_v2 import FocusedResult
        from .pipeline_v2 import RoutedSections

        empty_focused = FocusedResult(
            ok=False,
            intent=parsed.intent,
            answer_shape="not_addressed_in_guideline",
        )
        empty_routed = RoutedSections(out_of_scope=True)
        assembled = assemble_v2(parsed, empty_focused, empty_routed)
        return self._build_oos_response(parsed, assembled, llm_audit)

    # ------------------------------------------------------------------
    # Clarification helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _count_clarification_rounds(
        history: List[Dict[str, Any]],
    ) -> int:
        """Count assistant turns with type='clarification' in history."""
        return sum(
            1
            for turn in history
            if turn.get("role") == "assistant"
            and turn.get("type") == "clarification"
        )

    @staticmethod
    def _merge_clarification_context(
        question: str, history: List[Dict[str, Any]],
    ) -> str:
        """If the previous assistant turn was a clarification, merge the
        original question with the current reply so the parser has full
        context. Otherwise return the question unchanged.
        """
        if not history:
            return question
        # Walk backwards looking for the most recent clarification ask
        # and the user question that triggered it.
        for i in range(len(history) - 1, -1, -1):
            turn = history[i]
            if (
                turn.get("role") == "assistant"
                and turn.get("type") == "clarification"
            ):
                # The user turn immediately before this clarification is
                # the original question we need to merge with.
                for j in range(i - 1, -1, -1):
                    prior = history[j]
                    if prior.get("role") == "user":
                        original = prior.get("content") or ""
                        if original:
                            return f"{original} — clarification: {question}"
                        break
                break
        return question

    # ------------------------------------------------------------------
    # Response builders — shape the dict routes.py returns to the frontend
    # ------------------------------------------------------------------

    def _build_clarification_response(
        self,
        parsed: ParsedQAQueryV2,
        clar_decision,
        resolved_sections: List[str],
        routed,
    ) -> Dict[str, Any]:
        return {
            "status": "needs_clarification",
            "answer": clar_decision.question,
            "summary": clar_decision.question,
            "citations": [],
            "relatedSections": list(resolved_sections),
            "referencedTrials": [],
            "needsClarification": True,
            "clarificationOptions": [],
            "auditTrail": [
                {
                    "step": "v2_parse",
                    "detail": {
                        "intent": parsed.intent.value,
                        "topic": parsed.topic,
                        "sections": list(parsed.sections),
                        "slots": dict(parsed.slots),
                    },
                },
                {
                    "step": "v2_clarification",
                    "detail": {
                        "missing_slots": list(clar_decision.missing_slots),
                        "reason": clar_decision.reason,
                        "round_after": clar_decision.round_after,
                    },
                },
            ],
        }

    def _build_answer_response(
        self,
        parsed: ParsedQAQueryV2,
        assembled,
        verification,
        llm_audit: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        # Citations for the frontend are human-readable strings like
        # "§4.3 rec #2". Keep it simple and deterministic.
        citation_strings = [
            f"§{c.section_id} rec #{c.rec_number}" for c in assembled.citations
        ]

        # Out-of-scope and fenced paths still return "complete" because
        # the user sees a valid (decline) response — nothing to retry.
        status = "complete"

        summary = (
            assembled.plain_summary.strip()
            or self._first_line(assembled.text)
            or assembled.text[:240]
        )

        return {
            "status": status,
            "answer": assembled.text,
            "summary": summary,
            "plainSummary": assembled.plain_summary,
            "scope": assembled.scope,
            "citations": citation_strings,
            "relatedSections": list(verification.resolved_sections),
            "referencedTrials": [],
            "auditTrail": [
                {
                    "step": "v2_parse",
                    "detail": {
                        "intent": parsed.intent.value,
                        "topic": parsed.topic,
                        "sections": list(parsed.sections),
                        "slots": dict(parsed.slots),
                        "scaffolding_trace": dict(parsed.scaffolding_trace),
                    },
                },
                {
                    "step": "v2_verify",
                    "detail": {
                        "resolved_sections": list(verification.resolved_sections),
                        "out_of_scope": verification.out_of_scope,
                        "errors": list(verification.errors),
                    },
                },
                {
                    "step": "v2_assemble",
                    "detail": dict(assembled.audit),
                },
                {
                    "step": "v2_llm",
                    "detail": dict(llm_audit or {}),
                },
            ],
        }

    def _build_oos_response(
        self,
        parsed: ParsedQAQueryV2,
        assembled,
        llm_audit: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Response shape for the out-of-scope hybrid branch.

        Shares the same keys as `_build_answer_response` so routes.py
        can render a denied/fallback/canned-decline response through
        the same frontend contract. There is no `verification` object
        on this path because the in-scope pipeline never ran.
        """
        summary = (
            self._first_line(assembled.text) or assembled.text[:240]
        )
        return {
            "status": "complete",
            "answer": assembled.text,
            "summary": summary,
            "plainSummary": assembled.plain_summary,
            "scope": assembled.scope,
            "citations": [],
            "relatedSections": [],
            "referencedTrials": [],
            "auditTrail": [
                {
                    "step": "v2_parse",
                    "detail": {
                        "intent": parsed.intent.value,
                        "topic": parsed.topic,
                        "sections": list(parsed.sections),
                        "slots": dict(parsed.slots),
                        "scaffolding_trace": dict(parsed.scaffolding_trace),
                    },
                },
                {
                    "step": "v2_out_of_scope",
                    "detail": dict(assembled.audit),
                },
                {
                    "step": "v2_llm",
                    "detail": dict(llm_audit),
                },
            ],
        }

    @staticmethod
    def _first_line(text: str) -> str:
        for line in (text or "").splitlines():
            line = line.strip()
            if line:
                return line
        return ""


__all__ = ["QAOrchestratorV2"]
