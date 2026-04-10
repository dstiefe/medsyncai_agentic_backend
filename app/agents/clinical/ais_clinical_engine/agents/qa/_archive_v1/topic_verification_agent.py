"""
Topic Verification Agent — sanity-checks the classifier's topic pick.

The classifier LLM picks a topic from the Topic Guide. This agent
verifies whether that topic is the right clinical area to look in.

Three verdicts:
    - "confirmed"    — right clinical area, proceed to Python lookup
    - "wrong_topic"  — completely wrong area (rare — aspirin under Imaging)
    - "not_ais"      — question is outside AIS guideline entirely

The verifier does NOT redirect or suggest alternatives. If the topic
is in the right clinical neighborhood, it confirms. The downstream
system reads the actual section content and determines whether the
specific question is answered.

The system prompt includes the verification schema plus the synonym dictionary
and data dictionary appendices (same as Step 1) so the verifier has full
context to validate the classifier's decisions.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import List, Optional

from .query_parsing_agent import (
    _load_json,
    _build_synonym_appendix,
    _build_data_dict_appendix,
    _SYNONYM_PATH,
    _DATA_DICT_PATH,
)
from .scaffolding_loader import ScaffoldingBundle, get_scaffolding
from .schemas import ParsedQAQueryV2, VnIntent

logger = logging.getLogger(__name__)

_SCHEMA_PATH = os.path.join(
    os.path.dirname(__file__), "references", "topic_verification_schema.md"
)

_TOPIC_MAP_PATH = os.path.join(
    os.path.dirname(__file__), "references", "guideline_topic_map.json"
)


def _load_schema() -> str:
    if os.path.exists(_SCHEMA_PATH):
        with open(_SCHEMA_PATH) as f:
            return f.read()
    logger.error("Topic verification schema not found at %s", _SCHEMA_PATH)
    return ""


def _load_topic_addresses() -> dict:
    """Load topic → addresses mapping for building verification prompts."""
    if not os.path.exists(_TOPIC_MAP_PATH):
        return {}
    with open(_TOPIC_MAP_PATH) as f:
        data = json.load(f)
    result = {}
    for entry in data.get("topics", []):
        result[entry["topic"]] = entry.get("addresses", "")
    return result


def _build_verification_prompt(schema: str) -> str:
    """Combine the verification schema with the same reference appendices Step 1 uses."""
    parts = [schema]

    synonym_appendix = _build_synonym_appendix(_load_json(_SYNONYM_PATH))
    if synonym_appendix:
        parts.append("\n\n---\n\n" + synonym_appendix)

    data_dict_appendix = _build_data_dict_appendix(_load_json(_DATA_DICT_PATH))
    if data_dict_appendix:
        parts.append("\n\n---\n\n" + data_dict_appendix)

    return "".join(parts)


@dataclass
class VerificationResult:
    """Output of the Topic Verification Agent."""

    verdict: str          # "confirmed" | "wrong_topic" | "not_ais"
    reason: str           # one-sentence explanation
    suggested_topic: Optional[str] = None  # when wrong_topic, the correct topic
    usage: dict = None    # token usage for cost tracking

    def __post_init__(self):
        if self.usage is None:
            self.usage = {"input_tokens": 0, "output_tokens": 0}


@dataclass
class TopicRescoreResult:
    """Output of the v2 topic re-scorer.

    Unlike the legacy 3-verdict verifier, this is a pure re-scorer:
    - `changed`: True if the re-scorer picked a different topic than the parser.
    - `original_topic` / `final_topic`: what came in vs. what we're using.
    - `final_sections`: sections mapped from final_topic via guideline_topic_map.json.
    - `confidence`: LLM's self-reported confidence in [0.0, 1.0].

    The re-scorer NEVER vetoes: intent validity, slot completeness,
    section resolution, and out-of-scope handling are already enforced
    deterministically by scaffolding_verifier before this runs.
    """

    changed: bool
    original_topic: Optional[str]
    final_topic: Optional[str]
    final_sections: List[str] = field(default_factory=list)
    confidence: float = 0.0
    reason: str = ""
    usage: dict = field(default_factory=lambda: {"input_tokens": 0, "output_tokens": 0})


class TopicVerificationAgent:
    """Verifies that the classifier's topic pick is in the right clinical area."""

    def __init__(self, nlp_client=None):
        self._client = nlp_client
        self._schema = _build_verification_prompt(_load_schema())
        self._topic_addresses = _load_topic_addresses()
        # v2 re-scorer shares the bundle with the parser/verifier so
        # topic→section lookups stay authoritative.
        try:
            self._bundle: Optional[ScaffoldingBundle] = get_scaffolding()
        except Exception as e:  # noqa: BLE001 — startup safety
            logger.error("topic re-scorer: scaffolding bundle failed: %s", e)
            self._bundle = None

    @property
    def is_available(self) -> bool:
        return self._client is not None and bool(self._schema)

    async def verify(
        self,
        question: str,
        topic: str,
        qualifier: Optional[str] = None,
        parsed_query: Optional[dict] = None,
    ) -> VerificationResult:
        """
        Verify whether the classified topic is the right clinical area.

        Args:
            question: the original clinician question
            topic: the topic the classifier picked
            qualifier: optional subtopic qualifier
            parsed_query: full JSON output from the classifier (intent,
                question_summary, search_terms, etc.) so the verifier
                can see everything the classifier decided

        Returns:
            VerificationResult with verdict and reason
        """
        if not self.is_available:
            logger.debug("Topic verifier unavailable — auto-confirming")
            return VerificationResult(
                verdict="confirmed",
                reason="Verification unavailable — auto-confirmed",
            )

        # Look up what this topic addresses
        addresses = self._topic_addresses.get(topic, "")
        if not addresses:
            logger.warning("Topic '%s' not found in topic map", topic)
            return VerificationResult(
                verdict="wrong_topic",
                reason=f"Topic '{topic}' does not exist in the guideline topic map",
            )

        # Build the verification prompt with full classifier output
        user_prompt = self._build_prompt(question, topic, addresses, qualifier, parsed_query)

        try:
            response = self._client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=150,
                system=self._schema,
                messages=[
                    {"role": "user", "content": user_prompt},
                ],
            )

            usage = {
                "input_tokens": getattr(response.usage, "input_tokens", 0),
                "output_tokens": getattr(response.usage, "output_tokens", 0),
            }

            # Parse response
            for block in response.content:
                if hasattr(block, "text"):
                    text = block.text.strip()
                    data = self._parse_json(text)
                    if data:
                        result = VerificationResult(
                            verdict=data.get("verdict", "confirmed"),
                            reason=data.get("reason", ""),
                            suggested_topic=data.get("suggested_topic"),
                            usage=usage,
                        )
                        logger.info(
                            "Topic verification: topic='%s' verdict=%s reason='%s' suggested='%s'",
                            topic, result.verdict, result.reason, result.suggested_topic,
                        )
                        return result

            logger.warning("Topic verifier returned no JSON — auto-confirming")
            return VerificationResult(
                verdict="confirmed",
                reason="Verifier returned no parseable response",
                usage=usage,
            )

        except Exception as e:
            logger.error("Topic verification failed: %s", e)
            return VerificationResult(
                verdict="confirmed",
                reason=f"Verification error: {e}",
            )

    def _build_prompt(
        self,
        question: str,
        topic: str,
        addresses: str,
        qualifier: Optional[str] = None,
        parsed_query: Optional[dict] = None,
    ) -> str:
        """Build the verification prompt with full classifier output and topic list."""
        parts = [
            f"Question: {question}",
            "",
            "=== Classifier Output ===",
            f"Topic: {topic}",
            f"This topic addresses: {addresses}",
        ]
        if qualifier:
            parts.append(f"Qualifier: {qualifier}")

        # Pass the full classifier JSON so verifier sees everything
        if parsed_query:
            intent = parsed_query.get("intent", "")
            summary = parsed_query.get("question_summary", "")
            terms = parsed_query.get("search_terms", [])
            if intent:
                parts.append(f"Intent: {intent}")
            if summary:
                parts.append(f"Question summary: {summary}")
            if terms:
                parts.append(f"Search terms: {', '.join(terms)}")

        # Include full topic list so verifier can suggest alternatives
        topic_lines = []
        for t, addr in self._topic_addresses.items():
            topic_lines.append(f"- {t}: {addr}")
        if topic_lines:
            parts.append("")
            parts.append("Available topics (use for suggested_topic if wrong):")
            parts.extend(topic_lines)

        return "\n".join(parts)

    @staticmethod
    def _parse_json(text: str) -> Optional[dict]:
        """Extract JSON from LLM response."""
        if text.startswith("{"):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                pass
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                pass
        return None

    # ── v2 re-scorer ─────────────────────────────────────────────────

    async def rescore_topic_v2(
        self,
        parsed: ParsedQAQueryV2,
    ) -> TopicRescoreResult:
        """
        Re-score the topic picked by the v2 parser.

        This is a pure topic re-scorer. It does NOT veto intent, slots,
        section resolution, or out-of-scope state — scaffolding_verifier
        already enforces those deterministically before this runs. If the
        LLM picks a different topic than the parser, the re-scorer swaps
        the topic AND re-derives candidate_sections from the topic map so
        sections stay consistent with the final topic.

        Args:
            parsed: the ParsedQAQueryV2 coming out of parse_v2 + verifier.

        Returns:
            TopicRescoreResult describing whether the topic changed, the
            final topic/sections the router should use, and confidence.
        """
        empty_usage = {"input_tokens": 0, "output_tokens": 0}

        # Out-of-scope: nothing to re-score.
        if parsed.intent == VnIntent.OUT_OF_SCOPE:
            return TopicRescoreResult(
                changed=False,
                original_topic=parsed.topic,
                final_topic=parsed.topic,
                final_sections=list(parsed.sections),
                confidence=1.0,
                reason="out_of_scope — topic re-scoring skipped",
                usage=empty_usage,
            )

        # Auto-pass if the LLM client or bundle isn't available.
        if self._client is None or self._bundle is None:
            logger.debug("topic re-scorer unavailable — auto-confirming")
            return TopicRescoreResult(
                changed=False,
                original_topic=parsed.topic,
                final_topic=parsed.topic,
                final_sections=list(parsed.sections),
                confidence=0.0,
                reason="re-scorer unavailable — auto-confirmed",
                usage=empty_usage,
            )

        topics = self._bundle.topic_map.get("topics", [])
        if not topics:
            return TopicRescoreResult(
                changed=False,
                original_topic=parsed.topic,
                final_topic=parsed.topic,
                final_sections=list(parsed.sections),
                confidence=0.0,
                reason="topic map empty",
                usage=empty_usage,
            )

        user_prompt = self._build_rescore_prompt(parsed, topics)
        system_prompt = self._build_rescore_system_prompt()

        try:
            response = self._client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=250,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            usage = {
                "input_tokens": getattr(response.usage, "input_tokens", 0),
                "output_tokens": getattr(response.usage, "output_tokens", 0),
            }
            data: Optional[dict] = None
            for block in response.content:
                if hasattr(block, "text"):
                    data = self._parse_json(block.text.strip())
                    if data:
                        break

            if not data:
                logger.warning("topic re-scorer returned no JSON — auto-confirming")
                return TopicRescoreResult(
                    changed=False,
                    original_topic=parsed.topic,
                    final_topic=parsed.topic,
                    final_sections=list(parsed.sections),
                    confidence=0.0,
                    reason="re-scorer returned no JSON",
                    usage=usage,
                )

            best_topic = data.get("best_topic") or parsed.topic
            confidence = float(data.get("confidence") or 0.0)
            reason = data.get("reason") or ""

            # If the re-scorer's pick isn't in the topic map, ignore it.
            topic_to_section = {
                t.get("topic"): t.get("section") for t in topics
            }
            if best_topic not in topic_to_section:
                logger.warning(
                    "topic re-scorer picked unknown topic '%s' — keeping original",
                    best_topic,
                )
                return TopicRescoreResult(
                    changed=False,
                    original_topic=parsed.topic,
                    final_topic=parsed.topic,
                    final_sections=list(parsed.sections),
                    confidence=confidence,
                    reason=(
                        f"re-scorer picked unknown topic '{best_topic}'; "
                        f"kept original. {reason}"
                    ),
                    usage=usage,
                )

            changed = best_topic != parsed.topic
            if not changed:
                return TopicRescoreResult(
                    changed=False,
                    original_topic=parsed.topic,
                    final_topic=parsed.topic,
                    final_sections=list(parsed.sections),
                    confidence=confidence,
                    reason=reason or "confirmed original topic",
                    usage=usage,
                )

            # Topic changed — re-derive sections from the topic map. We
            # replace rather than append so the router sees only sections
            # consistent with the final topic.
            new_section = topic_to_section[best_topic]
            final_sections = [new_section] if new_section else []
            logger.info(
                "topic re-scorer: '%s' -> '%s' (sections %s -> %s) conf=%.2f",
                parsed.topic, best_topic, parsed.sections, final_sections, confidence,
            )
            return TopicRescoreResult(
                changed=True,
                original_topic=parsed.topic,
                final_topic=best_topic,
                final_sections=final_sections,
                confidence=confidence,
                reason=reason,
                usage=usage,
            )

        except Exception as e:  # noqa: BLE001 — always surface safe fallback
            logger.error("topic re-scoring failed: %s", e)
            return TopicRescoreResult(
                changed=False,
                original_topic=parsed.topic,
                final_topic=parsed.topic,
                final_sections=list(parsed.sections),
                confidence=0.0,
                reason=f"re-scorer exception: {e}",
                usage=empty_usage,
            )

    @staticmethod
    def _build_rescore_system_prompt() -> str:
        """System prompt for the v2 topic re-scorer.

        Kept intentionally short. The re-scorer's only job is to pick the
        single best topic from the provided list — not to explain the
        clinical answer and not to second-guess intent or slots.
        """
        return (
            "You are a topic re-scorer for the 2026 AHA/ASA Acute Ischemic "
            "Stroke Guidelines Q&A pipeline. A prior agent has already "
            "parsed the user's question and picked a topic. Your ONLY job "
            "is to confirm or revise that topic pick against the provided "
            "topic list. You do NOT answer the clinical question. You do "
            "NOT question the intent or slots. You do NOT invent topics.\n\n"
            "Emit exactly this JSON and nothing else:\n"
            '{"best_topic": "<topic name from the list>", '
            '"confidence": 0.0, "reason": "<one short sentence>"}\n\n'
            "If the original topic is already the best match, return it "
            "unchanged. Pick a different topic ONLY when the original is "
            "clearly in the wrong clinical area."
        )

    def _build_rescore_prompt(
        self,
        parsed: ParsedQAQueryV2,
        topics: list,
    ) -> str:
        """Build the user-facing prompt for the re-scorer."""
        parts = [
            f"Question: {parsed.question}",
            "",
            "Prior parser output:",
            f"- intent: {parsed.intent.value}",
            f"- topic: {parsed.topic or '(none)'}",
            f"- candidate_sections: {parsed.sections}",
            f"- slots: {parsed.slots}",
            "",
            "Available topics (topic — section — addresses):",
        ]
        for t in topics:
            name = t.get("topic", "")
            section = t.get("section", "")
            addresses = t.get("addresses", "")
            parts.append(f"- {name} (§{section}): {addresses}")
        parts.append("")
        parts.append(
            "Pick the single best topic from the list above. If the parser's "
            "topic is already correct, return it unchanged."
        )
        return "\n".join(parts)
