"""
Intent Classifier — LLM agent that classifies a query as CMI or extraction,
and determines which protocol (P1-P8) to use.

Uses haiku-tier model for speed (~1s latency).
"""

from __future__ import annotations

import os
import json
from app.base_agent import LLMAgent
from ..models.query import ClassifiedIntent


_SKILL_PATH = os.path.join(
    os.path.dirname(__file__), "..", "references", "intent_classification_schema.md"
)


class IntentClassifier(LLMAgent):
    """Classifies a clinical question as CMI or extraction protocol."""

    def __init__(self):
        super().__init__(
            name="intent_classifier",
            skill_path=_SKILL_PATH,
        )

    async def classify(self, user_question: str) -> tuple[ClassifiedIntent, dict]:
        """
        Classify a query into CMI or extraction protocol.

        Returns:
            (ClassifiedIntent, usage_dict)
        """
        messages = [
            {"role": "user", "content": user_question},
        ]

        response = await self.llm_client.call_json(
            system_prompt=self.system_message,
            messages=messages,
            model=self.model,
        )

        content = response.get("content")
        if isinstance(content, str):
            try:
                content = json.loads(content)
            except json.JSONDecodeError:
                # Default to CMI if parsing fails
                return ClassifiedIntent(
                    intent_type="cmi",
                    original_query=user_question,
                    confidence=0.3,
                ), _extract_usage(response)

        if not isinstance(content, dict):
            return ClassifiedIntent(
                intent_type="cmi",
                original_query=user_question,
                confidence=0.3,
            ), _extract_usage(response)

        # Build ClassifiedIntent from response
        intent_type = content.get("intent_type", "cmi")
        protocol = content.get("protocol")
        confidence = content.get("confidence", 0.5)

        # If confidence is low, default to CMI (safer)
        if intent_type == "extraction" and confidence < 0.7:
            intent_type = "cmi"
            protocol = None

        # Handle multi-intent
        sub_intents = None
        is_multi = content.get("is_multi_intent", False)
        if is_multi and content.get("sub_intents"):
            sub_intents = [
                ClassifiedIntent(
                    intent_type="extraction",
                    protocol=si.get("protocol"),
                    trial_acronym=si.get("trial_acronym") or content.get("trial_acronym"),
                    field_requested=si.get("field_requested"),
                    table_requested=si.get("table_requested"),
                    original_query=user_question,
                    confidence=confidence,
                )
                for si in content["sub_intents"]
            ]

        return ClassifiedIntent(
            intent_type=intent_type,
            protocol=protocol,
            trial_acronym=content.get("trial_acronym"),
            field_requested=content.get("field_requested"),
            table_requested=content.get("table_requested"),
            trials_to_compare=content.get("trials_to_compare"),
            definition_term=content.get("definition_term"),
            original_query=user_question,
            is_multi_intent=is_multi,
            sub_intents=sub_intents,
            confidence=confidence,
        ), _extract_usage(response)


def _extract_usage(response: dict) -> dict:
    return {
        "input_tokens": response.get("input_tokens", 0),
        "output_tokens": response.get("output_tokens", 0),
    }
