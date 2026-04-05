"""
QA Query Parsing Agent — LLM-based extraction of clinical variables.

Uses Claude to parse a clinician's question into structured variables
(ASPECTS, NIHSS, vessel, time window, etc.) for CMI-style matching
against guideline recommendations.

This replaces the regex-based extract_clinical_variables() for
questions that need applicability matching.

The LLM handles the probabilistic task (parsing natural language).
All matching, tiering, and scoring is done by RecommendationMatcher
(pure Python, deterministic).
"""

from __future__ import annotations

import json
import logging
import os
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
    """Extracts structured clinical variables from guideline questions."""

    def __init__(self, nlp_client=None):
        """
        Args:
            nlp_client: Anthropic client instance (from NLPService).
                If None, the agent is disabled and always returns
                is_criterion_specific=False.
        """
        self._client = nlp_client
        self._schema = _load_schema()

    @property
    def is_available(self) -> bool:
        """True if the LLM client is configured."""
        return self._client is not None and bool(self._schema)

    async def parse(self, question: str) -> Tuple[ParsedQAQuery, dict]:
        """
        Parse a clinical question into structured variables.

        Returns:
            (ParsedQAQuery, usage_dict)
            usage_dict has input_tokens, output_tokens for cost tracking.
        """
        if not self.is_available:
            logger.debug("QA query parser unavailable — skipping CMI path")
            return ParsedQAQuery(clinical_question=question), {"input_tokens": 0, "output_tokens": 0}

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
                        parsed = self._build_parsed_query(data, question)
                        logger.info(
                            "QA query parsed: criterion_specific=%s vars=%s confidence=%.2f",
                            parsed.is_criterion_specific,
                            parsed.get_scenario_variables(),
                            parsed.extraction_confidence,
                        )
                        return parsed, usage

            # LLM returned no parseable JSON
            logger.warning("QA query parser returned no JSON")
            return ParsedQAQuery(clinical_question=question), usage

        except Exception as e:
            logger.error("QA query parsing failed: %s", e)
            return ParsedQAQuery(clinical_question=question), {"input_tokens": 0, "output_tokens": 0}

    @staticmethod
    def _parse_json(text: str) -> Optional[dict]:
        """Extract JSON from LLM response text."""
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
    def _build_parsed_query(data: dict, original_question: str) -> ParsedQAQuery:
        """Convert LLM JSON output to a ParsedQAQuery."""
        # Validate question_type — only accept known values
        qt = data.get("question_type", "recommendation")
        if qt not in ("recommendation", "evidence", "knowledge_gap"):
            qt = "recommendation"

        return ParsedQAQuery(
            is_criterion_specific=data.get("is_criterion_specific", False),
            question_type=qt,
            target_sections=data.get("target_sections"),
            search_keywords=data.get("search_keywords"),
            intervention=data.get("intervention"),
            circulation=data.get("circulation"),
            vessel_occlusion=data.get("vessel_occlusion"),
            time_window_hours=data.get("time_window_hours"),
            aspects_range=data.get("aspects_range"),
            pc_aspects_range=data.get("pc_aspects_range"),
            nihss_range=data.get("nihss_range"),
            age_range=data.get("age_range"),
            premorbid_mrs=data.get("premorbid_mrs"),
            core_volume_ml=data.get("core_volume_ml"),
            clinical_question=data.get("clinical_question", original_question),
            extraction_confidence=data.get("extraction_confidence", 0.5),
        )
