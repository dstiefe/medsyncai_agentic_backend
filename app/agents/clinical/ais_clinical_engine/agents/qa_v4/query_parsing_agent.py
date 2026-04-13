# ─── v4 (Q&A v4 namespace) ─────────────────────────────────────────────
# This file lives under agents/qa_v4/ and is the active v4 copy of the
# Guideline Q&A pipeline. The previous location agents/qa_v3/ has been
# archived to agents/_archive_qa_v3/ and is no longer imported anywhere.
# v4 changes: unified Step 1 pipeline — 44 intents from
# intent_content_source_map.json, anchor_terms as Dict[str, Any]
# (term → value/range), values_verified, rescoped clarification.
# ───────────────────────────────────────────────────────────────────────
"""
QA Query Parsing Agent — LLM-based question classification (Step 1).

This is the PRIMARY classifier for the Guideline Q&A pipeline.
The LLM reads the clinician's question with structured reference data
as context and returns a structured JSON with intent (44 intents),
topic (38 topics), anchor_terms as Dict[str, Any] (term → value/range)
grounded in reference vocabulary.

The LLM handles the probabilistic task (understanding clinical intent).
All lookup, retrieval, and matching is done by Python (deterministic).

Pipeline role:
    Step 1: THIS AGENT classifies the question
    Step 2: Python content dispatch reads intent → sources
    Step 3: Python routes to guideline sections (not yet implemented)
    Step 4: Python retrieves data from those sections
    Step 5: Focused agents process recs/RSS/KG
    Step 6: Assembly agent writes the answer
"""

from __future__ import annotations

import json
import logging
import os
from typing import Optional, Tuple

from .schemas import ParsedQAQuery

logger = logging.getLogger(__name__)

# Reference file paths
_REF_DIR = os.path.join(os.path.dirname(__file__), "references")
_SCHEMA_PATH = os.path.join(_REF_DIR, "qa_query_parsing_schema.md")
_SYNONYM_PATH = os.path.join(_REF_DIR, "synonym_dictionary.json")
_DATA_DICT_PATH = os.path.join(_REF_DIR, "data_dictionary.json")
_TOPIC_MAP_PATH = os.path.join(_REF_DIR, "guideline_topic_map.json")
_INTENT_MAP_PATH = os.path.join(_REF_DIR, "intent_map.json")
_INTENT_SOURCE_MAP_PATH = os.path.join(_REF_DIR, "intent_content_source_map.json")
_ANCHOR_WORDS_PATH = os.path.join(_REF_DIR, "guideline_anchor_words.json")


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
        "When extracting anchor_terms, use this to normalize known terms",
        "(e.g., 'clot buster' → 'IVT', 'tPA' → 'alteplase'). But also",
        "extract any clinically relevant term from the question even if",
        "it is not in this dictionary.",
        "",
    ]
    for abbr, info in sorted(terms.items()):
        # Skip comment entries (keys like "_comment_trials" whose value is a
        # plain string used as a section separator in the source JSON).
        if abbr.startswith("_") or not isinstance(info, dict):
            continue
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

    Shows what anchor terms (with values/ranges) exist in each guideline section so the
    LLM knows what data lives where when classifying questions.
    """
    sections = data.get("sections", {})
    if not sections:
        return ""

    lines = [
        "## Reference: Section Data Dictionary",
        "",
        "Each guideline section contains specific anchor terms with values/ranges.",
        "Use this to understand what anchor terms exist and their",
        "valid values/ranges when extracting anchor term values from",
        "the question. Do NOT use this to pick a section number.",
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
                # `values` may be a list of allowed values, or a dict whose
                # keys are the meaningful clinical labels (e.g. 4.3.BP has
                # {"pre_IVT": ..., "post_IVT": ...}). Flatten both to a list.
                if isinstance(vals, dict):
                    items = list(vals.keys())
                else:
                    items = list(vals)
                if len(items) <= 4:
                    vars_summary.append(f"{key}={', '.join(str(v) for v in items)}")
                else:
                    vars_summary.append(f"{key}={', '.join(str(v) for v in items[:3])}...")
        if vars_summary:
            lines.append(f"- **{sec_num} {title}**: {'; '.join(vars_summary)}")

    return "\n".join(lines)


def _build_topic_map_appendix(data: dict) -> str:
    """Build detailed topic descriptions for the LLM system prompt.

    These rich descriptions supplement the Topic Guide table in the schema
    with disambiguation guidance, routing rules, and section content details.

    Each topic may carry a ``synopsis`` field extracted from the 2026
    AHA/ASA AIS Guidelines PDF — the guideline's own summary paragraph
    for that section. Synopses are included for sections 3.x–6.x
    (clinical evaluation and treatment) where routing disambiguation
    matters most. Sections 2.x (systems of care) are adequately
    described by addresses alone.
    """
    topics = data.get("topics", [])
    if not topics:
        return ""

    # Sections where synopsis adds routing value (clinical content).
    # Systems-of-care (2.x) are well-described by addresses alone.
    _SYNOPSIS_SECTIONS = {"3", "4", "5", "6"}

    def _should_include_synopsis(section_id: str) -> bool:
        return section_id.split(".")[0] in _SYNOPSIS_SECTIONS

    lines = [
        "## Reference: Detailed Topic Descriptions",
        "",
        "These descriptions expand on the Topic Guide above. Use them to",
        "disambiguate between similar topics and understand what each topic",
        "covers (and does NOT cover). Where available, the guideline's own",
        "Synopsis paragraph is included for additional clinical context.",
        "",
        "IMPORTANT: Use topics for SEMANTIC UNDERSTANDING only — knowing",
        "the question is about blood pressure management. Do NOT pick a",
        "section number — that happens downstream.",
        "",
    ]
    for t in topics:
        name = t.get("topic", "")
        section = t.get("section", "")
        desc = t.get("addresses", "")
        lines.append(f"### {name} (§{section})")
        lines.append(desc)

        # Include guideline synopsis for clinical sections
        synopsis = t.get("synopsis", "")
        if synopsis and _should_include_synopsis(section):
            lines.append(f"*Guideline synopsis:* {synopsis}")

        # Subtopic descriptions. Each subtopic entry carries an
        # ``addresses`` field with an LLM-friendly description (what the
        # subsection covers and what it does NOT cover), same prose
        # style as the top-level topic. Falls back to the qualifier
        # alone if a subtopic is not yet annotated.
        subtopics = t.get("subtopics") or []
        if subtopics:
            lines.append("")
            lines.append(f"**Subtopics of {name}:**")
            for s in subtopics:
                sub_section = s.get("section", "")
                qualifier = s.get("qualifier", "")
                sub_addresses = s.get("addresses", "")
                sub_synopsis = s.get("synopsis", "")
                if sub_addresses:
                    line = f"- **{qualifier}** (§{sub_section}): {sub_addresses}"
                    if sub_synopsis and _should_include_synopsis(sub_section):
                        line += f" *Synopsis:* {sub_synopsis}"
                    lines.append(line)
                else:
                    lines.append(f"- **{qualifier}** → §{sub_section}")
        lines.append("")

    return "\n".join(lines)


def _build_intent_map_appendix(data: dict) -> str:
    """Build a condensed intent map appendix for the LLM system prompt.

    The intent map expands clinical concepts into concept groups used for
    deterministic section routing. The LLM reads this to understand which
    multi-word clinical phrases (e.g. "basilar treatment", "extended
    window EVT") are atomic concepts that map to specific concept groups.
    """
    parts: list = []
    concept_expansions = data.get("concept_expansions", {})
    concept_groups = data.get("concept_groups", {})
    qualifier_rules = data.get("qualifier_rules", {})

    if not (concept_expansions or concept_groups or qualifier_rules):
        return ""

    parts.append("## Reference: Intent Map (concept expansions)")
    parts.append("")
    parts.append(
        "Recognize these clinical phrases as atomic concepts. When the "
        "clinician uses one, treat it as a single intent that maps to a "
        "known concept group — do not decompose it into its individual "
        "words when generating anchor_terms."
    )
    parts.append("")

    if concept_expansions:
        parts.append("### Concept expansions")
        for key, val in sorted(concept_expansions.items()):
            if key.startswith("_"):
                continue
            if isinstance(val, list):
                expanded = ", ".join(str(v) for v in val)
            elif isinstance(val, dict):
                expanded = ", ".join(f"{k}={v}" for k, v in val.items()
                                     if not str(k).startswith("_"))
            else:
                expanded = str(val)
            parts.append(f"- **{key}**: {expanded}")
        parts.append("")

    if concept_groups:
        parts.append("### Concept groups (compound intents)")
        for key, val in sorted(concept_groups.items()):
            if key.startswith("_"):
                continue
            if isinstance(val, list):
                members = ", ".join(str(v) for v in val)
            elif isinstance(val, dict):
                members = ", ".join(f"{k}: {v}" for k, v in val.items()
                                    if not str(k).startswith("_"))
            else:
                members = str(val)
            parts.append(f"- **{key}**: {members}")
        parts.append("")

    if qualifier_rules:
        rule_examples = qualifier_rules.get("examples")
        if isinstance(rule_examples, list) and rule_examples:
            parts.append("### Qualifier rules (examples)")
            for ex in rule_examples[:12]:
                if isinstance(ex, dict):
                    q = ex.get("question", "")
                    r = ex.get("qualifier", "") or ex.get("rule", "")
                    if q and r:
                        parts.append(f"- \"{q}\" → qualifier: {r}")
                elif isinstance(ex, str):
                    parts.append(f"- {ex}")
            parts.append("")

    return "\n".join(parts)


def _build_intent_guide_appendix(data: dict) -> str:
    """Build the 44-intent guide table from intent_content_source_map.json.

    Each intent includes what the user is asking and the content sources
    it maps to, so the LLM picks from a bounded enum with clear semantics.
    """
    intents = data.get("intents", [])
    if not intents:
        return ""

    lines = [
        "## Reference: Intent Guide (44 intents)",
        "",
        "Pick ONE intent from this list. Each intent maps to specific",
        "guideline content sources (REC, SYN, RSS, KG, TBL, FIG, FRONT).",
        "The intent IS the content dispatch key — downstream Python uses it",
        "to know exactly what content types to fetch.",
        "",
        "| Intent | Sources | User Is Asking |",
        "|---|---|---|",
    ]
    for entry in intents:
        intent = entry.get("intent", "")
        sources = entry.get("sources", "")
        asking = entry.get("user_is_asking", "")
        lines.append(f"| {intent} | {sources} | {asking} |")

    return "\n".join(lines)


def _build_anchor_vocab_appendix(data: dict) -> str:
    """Build a condensed anchor vocabulary for the LLM system prompt.

    Step 1 gets a CONDENSED version: term lists organized by category,
    deduplicated across all sections. No section numbers — those are
    used in Step 3 for routing.

    The LLM uses this as a guide to recognize clinical vocabulary in the
    question and extract normalized anchor_terms. Terms from this
    vocabulary should be normalized to their canonical form, but the LLM
    should also extract any clinically relevant term from the question
    even if it is not pre-listed here.
    """
    sections = data.get("sections", {})

    # Collect all terms by category, deduplicating across sections
    by_category: dict[str, set[str]] = {}

    # Regular sections: anchor_words is a dict of {category: [terms]}
    for sec_data in sections.values():
        anchor_words = sec_data.get("anchor_words", {})
        for category, terms in anchor_words.items():
            if not isinstance(terms, list):
                continue
            if category not in by_category:
                by_category[category] = set()
            # Structured metrics are dicts (e.g. {"term": "SBP", "operator": "<", "value": 185}).
            # Extract the term string; skip non-string entries.
            for t in terms:
                if isinstance(t, str):
                    by_category[category].add(t)
                elif isinstance(t, dict) and "term" in t:
                    by_category[category].add(t["term"])

    # Tables and figures: anchor_words is a flat list of strings,
    # grouped under the table/figure title as the category.
    for group_key in ("special_tables", "special_figures"):
        for sec_id, sec_data in data.get(group_key, {}).items():
            title = sec_data.get("title", sec_id)
            cat = f"tables_and_figures"
            if cat not in by_category:
                by_category[cat] = set()
            for t in sec_data.get("anchor_words", []):
                term_str = t if isinstance(t, str) else t.get("term", "")
                if term_str:
                    by_category[cat].add(term_str)

    if not by_category:
        return ""

    lines = [
        "## Reference: Anchor Vocabulary (condensed)",
        "",
        "These are clinical terms from the AIS guideline, organized by",
        "category. Use this as a GUIDE to normalize terms — e.g.,",
        "'clot buster' → 'IVT', 'tPA' → 'alteplase'. But also extract",
        "any clinically relevant term from the question even if it is",
        "not listed here (e.g., 'headache', 'nausea', 'fever').",
        "Numeric values go in anchor term values (Dict), not anchor_terms.",
        "",
    ]
    for category in sorted(by_category.keys()):
        terms = sorted(by_category[category])
        lines.append(f"### {category}")
        lines.append(", ".join(terms))
        lines.append("")

    return "\n".join(lines)


def _build_system_prompt(schema: str, synonym_data: dict,
                         data_dict_data: dict, topic_map_data: dict,
                         intent_map_data: dict,
                         intent_source_map_data: dict,
                         anchor_words_data: dict) -> str:
    """Combine the base schema with reference appendices.

    Six reference sources (synonym dictionary, data dictionary,
    guideline topic map, intent map, intent content source map,
    anchor vocabulary) are authoritative. The LLM MUST consult
    them first. If a question cannot be matched to any of them,
    the LLM should either make a best-effort classification using its
    own clinical understanding OR return a clarification question —
    whichever is more appropriate for the specific question.
    """
    # Primacy directive — prepend so it is read before the base schema
    primacy = (
        "# STEP 1: UNDERSTAND THE QUESTION FIRST\n\n"
        "Before consulting any references, read the clinician's question "
        "and understand what they are asking:\n"
        "1. **What is the clinical scenario?** — pre-treatment, during "
        "treatment, post-treatment, complication, eligibility?\n"
        "2. **What is the intent?** — are they asking what to do, whether "
        "something is safe, what the evidence says, what the protocol is?\n"
        "3. **What are the key clinical concepts?** — every clinically "
        "relevant term in the question is an anchor term. Symptoms "
        "(headache, nausea), findings (hypertension), procedures "
        "(nasogastric tube, catheter), drugs (alteplase), scales (NIHSS), "
        "conditions (coagulopathy) — if it is a real clinical concept "
        "mentioned in the question, extract it as an anchor_term.\n\n"
        "# STEP 2: USE REFERENCES TO NORMALIZE AND CLASSIFY\n\n"
        "After you understand the question, use the reference sources "
        "to normalize and classify:\n"
        "1. Intent guide — 44 intents with content source mappings\n"
        "2. Guideline topic map — maps clinical topics to guideline sections\n"
        "3. Clinical vocabulary (synonym dictionary) — normalize "
        "abbreviations and synonyms (e.g., 'tPA' → 'alteplase', "
        "'clot buster' → 'IVT')\n"
        "4. Section data dictionary — what variables live in each section\n"
        "5. Intent map — atomic compound concepts and their expansions\n"
        "6. Anchor vocabulary — helps normalize known clinical terms\n\n"
        "The vocabularies are a GUIDE for normalization, not a constraint "
        "on what you can extract. If the question says 'headache', extract "
        "'headache' — do not drop it because it is not in the vocabulary.\n\n"
        "**If the question does not fit any of these references**, you have "
        "two options — choose whichever is more appropriate:\n"
        "(a) Make a best-effort classification using your own clinical "
        "understanding of the 2026 AHA/ASA AIS Guidelines, and return a "
        "normal JSON classification with lower extraction_confidence.\n"
        "(b) Return a clarification question in the `clarification` field "
        "with `clarification_reason` explaining what is ambiguous or "
        "missing. Use this when the question is genuinely under-specified "
        "(e.g., 'what about the patient?' with no prior context).\n\n"
        "Do not fabricate topic names, intent names, or clinical "
        "variables that are not in the references and not in the question.\n\n"
        "**IMPORTANT: Do NOT pick a section number — that happens "
        "downstream. Identify the topic to understand the clinical domain "
        "only.**\n\n"
        "---\n\n"
    )
    parts = [primacy, schema]

    # Intent guide (44 intents) — most important reference for classification
    intent_guide = _build_intent_guide_appendix(intent_source_map_data)
    if intent_guide:
        parts.append("\n\n---\n\n" + intent_guide)

    topic_appendix = _build_topic_map_appendix(topic_map_data)
    if topic_appendix:
        parts.append("\n\n---\n\n" + topic_appendix)

    synonym_appendix = _build_synonym_appendix(synonym_data)
    if synonym_appendix:
        parts.append("\n\n---\n\n" + synonym_appendix)

    intent_map_appendix = _build_intent_map_appendix(intent_map_data)
    if intent_map_appendix:
        parts.append("\n\n---\n\n" + intent_map_appendix)

    data_dict_appendix = _build_data_dict_appendix(data_dict_data)
    if data_dict_appendix:
        parts.append("\n\n---\n\n" + data_dict_appendix)

    # Anchor vocabulary (condensed — no section numbers)
    anchor_appendix = _build_anchor_vocab_appendix(anchor_words_data)
    if anchor_appendix:
        parts.append("\n\n---\n\n" + anchor_appendix)

    return "".join(parts)


class QAQueryParsingAgent:
    """
    Step 1 of the Guideline Q&A pipeline (v4).

    Classifies the clinician's question into:
    - intent (one of 38 defined intents from intent_content_source_map)
    - topic (one of 38 guideline topics)
    - anchor_terms as Dict[str, Any] (term → value/range)
    - anchor_terms (clinical concepts grounded in reference vocabulary)
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
        intent_map_data = _load_json(_INTENT_MAP_PATH)
        intent_source_map_data = _load_json(_INTENT_SOURCE_MAP_PATH)
        anchor_words_data = _load_json(_ANCHOR_WORDS_PATH)
        self._schema = _build_system_prompt(
            base_schema, synonym_data, data_dict_data,
            topic_map_data, intent_map_data,
            intent_source_map_data, anchor_words_data,
        )

    @property
    def is_available(self) -> bool:
        """True if the LLM client is configured."""
        return self._client is not None and bool(self._schema)

    async def parse(
        self,
        question: str,
        clarification_context: Optional[str] = None,
    ) -> Tuple[ParsedQAQuery, dict]:
        """
        Parse a clinical question into structured classification.

        Args:
            question: the raw clinician question
            clarification_context: when the user is replying to a prior
                clarification, this contains the merged context string
                (original question + clarification exchanges). If provided,
                it is used as the user message instead of the raw question.

        Returns:
            (ParsedQAQuery, usage_dict)
            usage_dict has input_tokens, output_tokens for cost tracking.
        """
        if not self.is_available:
            logger.debug("QA query parser unavailable — falling back to IntentAgent")
            return ParsedQAQuery(), {"input_tokens": 0, "output_tokens": 0}

        # Use merged context when replying to a clarification,
        # otherwise use the raw question
        user_message = clarification_context or question

        # v4 UMLS layer: prepend a "Clinical concepts detected" line
        # to the user message so the LLM sees a deterministic second
        # opinion on which clinical concepts are actually present in
        # the question text. Each concept is shown with its UMLS CUI
        # and canonical name, filtered to clinical-domain TUIs only
        # (see scispacy_nlp._CLINICAL_TUIS). Gated by the QA_V3_UMLS
        # flag — when off, the user message is unchanged.
        umls_line = ""
        try:
            from ...services import qa_v3_flags
            if getattr(qa_v3_flags, "UMLS", False):
                from ...services import scispacy_nlp
                umls_line = scispacy_nlp.format_umls_concepts_for_prompt(
                    user_message, min_score=0.80,
                )
        except Exception as e:
            logger.debug("UMLS concept extraction skipped: %s", e)

        if umls_line:
            user_message = (
                f"Clinical concepts detected (UMLS): {umls_line}\n\n"
                f"Question: {user_message}"
            )

        try:
            response = self._client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=500,
                system=self._schema,
                messages=[
                    {"role": "user", "content": user_message},
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
                            "QA query parsed: intent=%s topic=%s "
                            "anchor_terms=%s has_vars=%s confidence=%.2f",
                            parsed.intent,
                            parsed.topic,
                            parsed.anchor_terms,
                            parsed.has_anchor_values(),
                            parsed.extraction_confidence,
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
        # Strip markdown code fences if present (no regex)
        if text.startswith("```"):
            # Remove opening fence: ```json or ```
            first_newline = text.find("\n")
            if first_newline >= 0:
                text = text[first_newline + 1:]
            # Remove closing fence
            if text.rstrip().endswith("```"):
                text = text.rstrip()
                text = text[:-3]
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
        """Convert LLM JSON output to a ParsedQAQuery (v4 schema).

        v4 changes from v3:
        - anchor_terms is a Dict[str, Any] (term → value/range or null)
        - Values live WITH their anchor terms, not as a separate field
        - values_verified is a new cross-check field
        - question_type removed (derived from intent via property)
        - Backward-compat CMI fields are properties on ParsedQAQuery
        """
        # Anchor terms — dict of clinical concepts → value/range or null
        anchor_terms = data.get("anchor_terms")
        if not isinstance(anchor_terms, dict):
            anchor_terms = {}

        # Clarification reason validation
        clarification_reason = data.get("clarification_reason")
        valid_reasons = {"off_topic", "vague_with_anchor",
                         "vague_no_anchor", "topic_ambiguity"}
        if clarification_reason and clarification_reason not in valid_reasons:
            clarification_reason = None

        # Extraction confidence — default based on whether topic was found
        confidence = data.get("extraction_confidence")
        if confidence is None:
            confidence = 0.9 if data.get("topic") else 0.3

        # is_criterion_specific: True when any anchor term has a value
        has_values = any(v is not None for v in anchor_terms.values())

        parsed = ParsedQAQuery(
            # Classification
            intent=data.get("intent"),
            topic=data.get("topic"),
            qualifier=data.get("qualifier"),
            question_summary=data.get("question_summary"),

            # Clarification
            clarification=data.get("clarification"),
            clarification_reason=clarification_reason,

            # Anchor terms (term → value/range or null)
            anchor_terms=anchor_terms,

            # Confidence and verification
            is_criterion_specific=has_values,
            extraction_confidence=float(confidence),
            values_verified=bool(data.get("values_verified", False)),
        )

        return parsed
