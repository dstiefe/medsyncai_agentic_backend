# ─── v4 (Q&A v4 namespace) ─────────────────────────────────────────────
# This file lives under agents/qa_v4/ and is the active v4 copy of the
# Guideline Q&A pipeline. The previous location agents/qa_v3/ has been
# archived to agents/_archive_qa_v3/ and is no longer imported anywhere.
# v4 changes: unified Step 1 pipeline — 44 intents from
# intent_content_source_map.json, anchor_terms as Dict[str, Any]
# (term → value/range), values_verified, rescoped clarification.
# ───────────────────────────────────────────────────────────────────────
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
from dataclasses import dataclass
from typing import Optional

from .query_parsing_agent import (
    _load_json,
    _build_synonym_appendix,
    _build_data_dict_appendix,
    _build_topic_map_appendix,
    _build_intent_map_appendix,
    _SYNONYM_PATH,
    _DATA_DICT_PATH,
    _TOPIC_MAP_PATH as _QPA_TOPIC_MAP_PATH,
    _INTENT_MAP_PATH,
)

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
    """Combine the verification schema with the SAME reference appendices Step 1 uses.

    The first LLM (query parser) and the validating LLM (this verifier) must
    share the exact same supporting resources so a term expanded/understood
    by one is also understood by the other. This means: synonym dictionary,
    data dictionary, guideline topic map, and intent map.
    """
    parts = [schema]

    topic_map_appendix = _build_topic_map_appendix(_load_json(_QPA_TOPIC_MAP_PATH))
    if topic_map_appendix:
        parts.append("\n\n---\n\n" + topic_map_appendix)

    synonym_appendix = _build_synonym_appendix(_load_json(_SYNONYM_PATH))
    if synonym_appendix:
        parts.append("\n\n---\n\n" + synonym_appendix)

    intent_map_appendix = _build_intent_map_appendix(_load_json(_INTENT_MAP_PATH))
    if intent_map_appendix:
        parts.append("\n\n---\n\n" + intent_map_appendix)

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


class TopicVerificationAgent:
    """Verifies that the classifier's topic pick is in the right clinical area."""

    def __init__(self, nlp_client=None):
        self._client = nlp_client
        self._schema = _build_verification_prompt(_load_schema())
        self._topic_addresses = _load_topic_addresses()

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

        # v3 UMLS layer (same as parser): prepend a "Clinical concepts
        # detected" line so the verifier sees the same deterministic
        # second opinion on clinical concepts that the parser saw.
        # Keeping parser and verifier on the same UMLS signal is the
        # same principle as the shared scaffolding appendix — both
        # LLMs reason from identical inputs.
        try:
            from ...services import qa_v3_flags
            if getattr(qa_v3_flags, "UMLS", False):
                from ...services import scispacy_nlp
                umls_line = scispacy_nlp.format_umls_concepts_for_prompt(
                    question, min_score=0.80,
                )
                if umls_line:
                    user_prompt = (
                        f"Clinical concepts detected (UMLS): {umls_line}\n\n"
                        f"{user_prompt}"
                    )
        except Exception as e:
            logger.debug("UMLS concept extraction skipped in verifier: %s", e)

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
