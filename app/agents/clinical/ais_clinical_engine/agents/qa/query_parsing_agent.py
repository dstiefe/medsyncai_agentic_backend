"""
QA Query Parsing Agent — LLM-based question classification (Step 1).

This is the PRIMARY classifier for the Guideline Q&A pipeline.
The LLM reads the clinician's question and returns a structured JSON
with intent, topic, search_terms, and clinical_variables.

The LLM handles the probabilistic task (understanding clinical intent).
All lookup, retrieval, and matching is done by Python (deterministic).

Pipeline role:
    Step 1: THIS AGENT classifies the question
    Step 2: TopicVerificationAgent reviews the classification
    Step 3: Python SectionRouter looks up topic -> section
    Step 4: Python retrieves data from those sections
    Step 5: Focused agents process recs/RSS/KG
    Step 6: Assembly agent writes the answer
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Optional, Tuple

from .schemas import ParsedQAQuery

logger = logging.getLogger(__name__)

# Load the parsing schema (LLM system prompt)
_SCHEMA_PATH = os.path.join(
    os.path.dirname(__file__), "references", "qa_query_parsing_schema.md"
)


def _load_schema() -> str:
    """Load the query parsing schema for the LLM system prompt."""
    if os.path.exists(_SCHEMA_PATH):
        with open(_SCHEMA_PATH) as f:
            return f.read()
    logger.error("Query parsing schema not found at %s", _SCHEMA_PATH)
    return ""


class QAQueryParsingAgent:
    """
    Step 1 of the Guideline Q&A pipeline.

    Classifies the clinician's question into:
    - intent (one of 28 defined intents)
    - topic (one guideline topic)
    - search_terms (clinically-informed keywords)
    - clinical_variables (patient data when present, all null otherwise)
    """

    def __init__(self, nlp_client=None):
        """
        Args:
            nlp_client: Anthropic client instance (from NLPService).
                If None, the agent is disabled and the pipeline falls
                back to the deterministic IntentAgent.
        """
        self._client = nlp_client
        self._schema = _load_schema()

    @property
    def is_available(self) -> bool:
        """True if the LLM client is configured."""
        return self._client is not None and bool(self._schema)

    async def parse(self, question: str) -> Tuple[ParsedQAQuery, dict]:
        """
        Parse a clinical question into structured classification.

        Returns:
            (ParsedQAQuery, usage_dict)
            usage_dict has input_tokens, output_tokens for cost tracking.
        """
        if not self.is_available:
            logger.debug("QA query parser unavailable — falling back to IntentAgent")
            return ParsedQAQuery(), {"input_tokens": 0, "output_tokens": 0}

        try:
            response = self._client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=500,
                system=self._schema,
                messages=[
                    {"role": "user", "content": question},
                ],
            )

            usage = {
                "input_tokens": getattr(response.usage, "input_tokens", 0),
                "output_tokens": getattr(response.usage, "output_tokens", 0),
            }

            # Extract JSON from response
            for block in response.content:
                if hasattr(block, "text"):
                    text = block.text.strip()
                    data = self._parse_json(text)
                    if data:
                        parsed = self._build_parsed_query(data)
                        logger.info(
                            "QA query parsed: intent=%s topic=%s search_terms=%s has_vars=%s",
                            parsed.intent,
                            parsed.topic,
                            parsed.search_keywords,
                            parsed.has_clinical_variables(),
                        )
                        return parsed, usage

            # LLM returned no parseable JSON
            logger.warning("QA query parser returned no JSON")
            return ParsedQAQuery(), usage

        except Exception as e:
            logger.error("QA query parsing failed: %s", e)
            return ParsedQAQuery(), {"input_tokens": 0, "output_tokens": 0}

    @staticmethod
    def _parse_json(text: str) -> Optional[dict]:
        """Extract JSON from LLM response text."""
        # Strip markdown code fences if present
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
            text = text.strip()

        # Try direct parse
        if text.startswith("{"):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                pass

        # Try to find JSON block
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                pass

        return None

    @staticmethod
    def _build_parsed_query(data: dict) -> ParsedQAQuery:
        """Convert LLM JSON output to a ParsedQAQuery."""
        # Validate question_type
        qt = data.get("question_type", "recommendation")
        if qt not in ("recommendation", "evidence", "knowledge_gap"):
            qt = "recommendation"

        # Clinical variables — always a dict, all null when empty
        cv = data.get("clinical_variables") or {}

        # Build the parsed query with new flat clinical variable fields
        parsed = ParsedQAQuery(
            # Classification
            intent=data.get("intent"),
            topic=data.get("topic"),
            qualifier=data.get("qualifier"),
            question_type=qt,
            question_summary=data.get("question_summary"),
            search_keywords=data.get("search_terms"),
            clarification=data.get("clarification"),

            # Clinical variables (flat fields)
            age=cv.get("age"),
            nihss=cv.get("nihss"),
            vessel_occlusion=cv.get("vessel_occlusion"),
            time_from_lkw_hours=cv.get("time_from_lkw_hours"),
            aspects=cv.get("aspects"),
            pc_aspects=cv.get("pc_aspects"),
            premorbid_mrs=cv.get("premorbid_mrs"),
            core_volume_ml=cv.get("core_volume_ml"),
            mismatch_ratio=cv.get("mismatch_ratio"),
            sbp=cv.get("sbp"),
            dbp=cv.get("dbp"),
            inr=cv.get("inr"),
            platelets=cv.get("platelets"),
            glucose=cv.get("glucose"),
        )

        # Populate legacy fields for backward compatibility with CMI matcher
        parsed.is_criterion_specific = parsed.has_clinical_variables()
        parsed.extraction_confidence = 0.9 if parsed.topic else 0.3

        if cv.get("vessel_occlusion"):
            vo = cv["vessel_occlusion"]
            parsed.vessel_occlusion = [vo] if isinstance(vo, str) else vo

        if cv.get("age") is not None:
            parsed.age_range = {"min": cv["age"], "max": cv["age"]}
        if cv.get("nihss") is not None:
            parsed.nihss_range = {"min": cv["nihss"], "max": cv["nihss"]}
        if cv.get("time_from_lkw_hours") is not None:
            parsed.time_window_hours = {"min": cv["time_from_lkw_hours"], "max": cv["time_from_lkw_hours"]}
        if cv.get("aspects") is not None:
            parsed.aspects_range = {"min": cv["aspects"], "max": cv["aspects"]}
        if cv.get("pc_aspects") is not None:
            parsed.pc_aspects_range = {"min": cv["pc_aspects"], "max": cv["pc_aspects"]}

        # Infer intervention and circulation from topic/qualifier
        topic = (data.get("topic") or "").lower()
        qualifier = (data.get("qualifier") or "").lower()
        if "ivt" in topic or "thrombol" in topic:
            parsed.intervention = "IVT"
        elif "evt" in topic or "thrombectomy" in topic:
            parsed.intervention = "EVT"
        if "posterior" in qualifier or "basilar" in qualifier:
            parsed.circulation = "posterior"
        elif "anterior" in qualifier:
            parsed.circulation = "anterior"

        return parsed
