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
from .pipeline_v2 import assemble_v2, route_v2
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

        # ── 1. Merge clarification reply with original question ────────
        merged_question = self._merge_clarification_context(
            question, conversation_history
        )

        # ── 2. Deterministic parse ─────────────────────────────────────
        parsed = parse_deterministic(merged_question, bundle=self._bundle)
        logger.info(
            "v2 parse: intent=%s topic=%s sections=%s slots=%s",
            parsed.intent.value, parsed.topic, parsed.sections, parsed.slots,
        )

        # ── 3. Verifier: resolve section families + enforce slot contract
        verification = verify_parsed_query(parsed.to_dict(), self._bundle)

        # ── 4. Route with review_flags guard ───────────────────────────
        routed = route_v2(
            parsed, bundle=self._bundle,
            verifier_resolved=verification.resolved_sections,
        )

        # ── 5. Clarification decision (deterministic) ──────────────────
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

        # ── 6. Dispatch focused agent (numeric or verbatim-rec) ────────
        focused = await dispatch_focused_agent(
            parsed,
            resolved_sections=verification.resolved_sections,
            bundle=self._bundle,
            nlp_client=None,  # deterministic path never uses LLM
        )

        # ── 7. Assemble the final answer ───────────────────────────────
        assembled = assemble_v2(parsed, focused, routed)

        return self._build_answer_response(parsed, assembled, verification)

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
    ) -> Dict[str, Any]:
        # Citations for the frontend are human-readable strings like
        # "§4.3 rec #2". Keep it simple and deterministic.
        citation_strings = [
            f"§{c.section_id} rec #{c.rec_number}" for c in assembled.citations
        ]

        status = "complete" if assembled.ok else "complete"
        # Out-of-scope and fenced paths still return "complete" because
        # the user sees a valid (decline) response — nothing to retry.

        summary = self._first_line(assembled.text) or assembled.text[:240]

        return {
            "status": status,
            "answer": assembled.text,
            "summary": summary,
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
