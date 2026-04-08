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

# Reference file paths
_REF_DIR = os.path.join(os.path.dirname(__file__), "references")
_SCHEMA_PATH = os.path.join(_REF_DIR, "qa_query_parsing_schema.md")
_SYNONYM_PATH = os.path.join(_REF_DIR, "synonym_dictionary.json")
_DATA_DICT_PATH = os.path.join(_REF_DIR, "data_dictionary.json")
_TOPIC_MAP_PATH = os.path.join(_REF_DIR, "guideline_topic_map.json")


def _load_schema() -> str:
    """Load the query parsing schema for the LLM system prompt."""
    if os.path.exists(_SCHEMA_PATH):
        with open(_SCHEMA_PATH) as f:
            return f.read()
    logger.error("Query parsing schema not found at %s", _SCHEMA_PATH)
    return ""


def _load_json(path: str) -> dict:
    """Load a JSON reference file, returning empty dict on failure."""
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.error("Failed to load %s: %s", path, e)
    return {}


def _build_synonym_appendix(data: dict) -> str:
    """Build a condensed synonym reference for the LLM system prompt.

    Includes term -> full_term + clinical_context so the LLM can
    correctly interpret abbreviations, compound terms, and trial names.
    """
    terms = data.get("terms", {})
    if not terms:
        return ""

    lines = [
        "## Reference: Clinical Vocabulary",
        "",
        "Use this dictionary to correctly interpret abbreviations, compound terms,",
        "drug names, and clinical trial names in the clinician's question.",
        "Terms with a CONTEXT note have special routing implications — read carefully.",
        "",
    ]
    for abbr, info in sorted(terms.items()):
        full = info.get("full_term", "")
        ctx = info.get("clinical_context", "")
        cat = info.get("category", "")
        entry = f"- **{abbr}**: {full}"
        if cat:
            entry += f" [{cat}]"
        if ctx:
            entry += f" — CONTEXT: {ctx}"
        lines.append(entry)

    return "\n".join(lines)


def _build_data_dict_appendix(data: dict) -> str:
    """Build a condensed data dictionary for the LLM system prompt.

    Shows what clinical variables exist in each guideline section so the
    LLM knows what data lives where when classifying questions.
    """
    sections = data.get("sections", {})
    if not sections:
        return ""

    lines = [
        "## Reference: Section Data Dictionary",
        "",
        "Each guideline section contains specific clinical variables.",
        "Use this to understand what data lives in each section when",
        "choosing a topic and generating search terms.",
        "",
    ]
    for sec_num, sec_data in sorted(sections.items()):
        title = sec_data.get("title", "")
        # Collect variable names and their key values
        vars_summary = []
        for key, val in sec_data.items():
            if key in ("title", "subheadings"):
                continue
            if isinstance(val, dict) and "values" in val:
                vals = val["values"]
                if len(vals) <= 4:
                    vars_summary.append(f"{key}={', '.join(str(v) for v in vals)}")
                else:
                    vars_summary.append(f"{key}={', '.join(str(v) for v in vals[:3])}...")
        if vars_summary:
            lines.append(f"- **{sec_num} {title}**: {'; '.join(vars_summary)}")

    return "\n".join(lines)


def _build_topic_map_appendix(data: dict) -> str:
    """Build detailed topic descriptions for the LLM system prompt.

    These rich descriptions supplement the Topic Guide table in the schema
    with disambiguation guidance, routing rules, and section content details.
    """
    topics = data.get("topics", [])
    if not topics:
        return ""

    lines = [
        "## Reference: Detailed Topic Descriptions",
        "",
        "These descriptions expand on the Topic Guide above. Use them to",
        "disambiguate between similar topics and understand what each section",
        "covers (and does NOT cover).",
        "",
    ]
    for t in topics:
        name = t.get("topic", "")
        section = t.get("section", "")
        desc = t.get("addresses", "")
        lines.append(f"### {name} (§{section})")
        lines.append(desc)
        lines.append("")

    return "\n".join(lines)


def _build_system_prompt(schema: str, synonym_data: dict,
                         data_dict_data: dict, topic_map_data: dict) -> str:
    """Combine the base schema with reference appendices."""
    parts = [schema]

    topic_appendix = _build_topic_map_appendix(topic_map_data)
    if topic_appendix:
        parts.append("\n\n---\n\n" + topic_appendix)

    synonym_appendix = _build_synonym_appendix(synonym_data)
    if synonym_appendix:
        parts.append("\n\n---\n\n" + synonym_appendix)

    data_dict_appendix = _build_data_dict_appendix(data_dict_data)
    if data_dict_appendix:
        parts.append("\n\n---\n\n" + data_dict_appendix)

    return "".join(parts)


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
        base_schema = _load_schema()
        synonym_data = _load_json(_SYNONYM_PATH)
        data_dict_data = _load_json(_DATA_DICT_PATH)
        topic_map_data = _load_json(_TOPIC_MAP_PATH)
        self._schema = _build_system_prompt(
            base_schema, synonym_data, data_dict_data, topic_map_data
        )

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
