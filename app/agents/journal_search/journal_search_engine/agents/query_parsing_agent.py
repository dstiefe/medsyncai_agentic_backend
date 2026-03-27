"""
QueryParsingAgent — LLM agent that extracts structured query variables
from a clinician's natural language question.

Handles:
- Standard queries → ParsedQuery
- Comparison queries → ComparisonQuery dict
- Vague queries → ParsedQuery with needs_clarification=True

Uses haiku-tier model for fast extraction.
"""

from __future__ import annotations

import os
import json
from typing import Union
from medsync_ai_v2.base_agent import LLMAgent
from ..models.query import ParsedQuery, RangeFilter, TimeWindowFilter


_SKILL_PATH = os.path.join(
    os.path.dirname(__file__), "..", "references", "query_parsing_schema.md"
)


class QueryParsingAgent(LLMAgent):
    """Extracts structured query variables from a clinical question."""

    def __init__(self):
        super().__init__(
            name="journal_query_parser",
            skill_path=_SKILL_PATH,
        )

    async def parse_query(self, user_question: str) -> tuple[Union[ParsedQuery, dict], dict]:
        """
        Parse a clinical question into structured query variables.

        Returns:
            (result, usage_dict)
            - result is ParsedQuery for standard/vague queries
            - result is a dict with is_comparison=True for comparison queries
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
                return ParsedQuery(
                    clinical_question=user_question,
                    needs_clarification=True,
                    clarification_question="I wasn't able to parse that question. Could you rephrase it with specific clinical variables?",
                    extraction_confidence=0.0,
                ), {"input_tokens": 0, "output_tokens": 0}

        usage = {
            "input_tokens": response.get("input_tokens", 0),
            "output_tokens": response.get("output_tokens", 0),
        }

        # Check if comparison query
        if content.get("is_comparison"):
            return content, usage

        # Standard query
        parsed = self._build_parsed_query(content, user_question)
        return parsed, usage

    @staticmethod
    def _build_parsed_query(data: dict, original_question: str) -> ParsedQuery:
        """Convert LLM JSON output to a ParsedQuery model."""

        def _to_range(val) -> RangeFilter | None:
            if val is None:
                return None
            if isinstance(val, dict):
                r = RangeFilter(min=val.get("min"), max=val.get("max"))
                return r if r.is_set() else None
            return None

        def _to_time_window(val) -> TimeWindowFilter | None:
            if val is None:
                return None
            if isinstance(val, dict):
                tw = TimeWindowFilter(
                    min=val.get("min"),
                    max=val.get("max"),
                    reference=val.get("reference"),
                )
                return tw if tw.is_set() else None
            return None

        return ParsedQuery(
            aspects_range=_to_range(data.get("aspects_range")),
            pc_aspects_range=_to_range(data.get("pc_aspects_range")),
            nihss_range=_to_range(data.get("nihss_range")),
            age_range=_to_range(data.get("age_range")),
            time_window_hours=_to_time_window(data.get("time_window_hours")),
            core_volume_ml=_to_range(data.get("core_volume_ml")),
            mismatch_ratio=_to_range(data.get("mismatch_ratio")),
            premorbid_mrs=_to_range(data.get("premorbid_mrs")),
            vessel_occlusion=data.get("vessel_occlusion"),
            imaging_required=data.get("imaging_required"),
            intervention=data.get("intervention"),
            comparator=data.get("comparator"),
            study_type=data.get("study_type"),
            circulation=data.get("circulation"),
            outcome_focus=data.get("outcome_focus"),
            clinical_question=data.get("clinical_question", original_question),
            needs_clarification=data.get("needs_clarification", False),
            clarification_question=data.get("clarification_question"),
            extraction_confidence=data.get("extraction_confidence", 0.5),
        )
