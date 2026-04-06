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

The prompt is tiny: question + topic + addresses line. ~200 input tokens.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Optional

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


@dataclass
class VerificationResult:
    """Output of the Topic Verification Agent."""

    verdict: str          # "confirmed" | "wrong_topic" | "not_ais"
    reason: str           # one-sentence explanation
    usage: dict = None    # token usage for cost tracking

    def __post_init__(self):
        if self.usage is None:
            self.usage = {"input_tokens": 0, "output_tokens": 0}


class TopicVerificationAgent:
    """Verifies that the classifier's topic pick is in the right clinical area."""

    def __init__(self, nlp_client=None):
        self._client = nlp_client
        self._schema = _load_schema()
        self._topic_addresses = _load_topic_addresses()

    @property
    def is_available(self) -> bool:
        return self._client is not None and bool(self._schema)

    async def verify(
        self,
        question: str,
        topic: str,
        qualifier: Optional[str] = None,
    ) -> VerificationResult:
        """
        Verify whether the classified topic is the right clinical area.

        Args:
            question: the original clinician question
            topic: the topic the classifier picked
            qualifier: optional subtopic qualifier

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

        # Build the verification prompt — deliberately small
        user_prompt = self._build_prompt(question, topic, addresses, qualifier)

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
                            usage=usage,
                        )
                        logger.info(
                            "Topic verification: topic='%s' verdict=%s reason='%s'",
                            topic, result.verdict, result.reason,
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

    @staticmethod
    def _build_prompt(
        question: str,
        topic: str,
        addresses: str,
        qualifier: Optional[str] = None,
    ) -> str:
        """Build the compact verification prompt."""
        parts = [
            f"Question: {question}",
            f"Classified topic: {topic}",
            f"This topic addresses: {addresses}",
        ]
        if qualifier:
            parts.append(f"Qualifier: {qualifier}")
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
