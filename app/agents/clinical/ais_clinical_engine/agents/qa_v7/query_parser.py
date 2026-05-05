"""qa_v7 Step 1a — LLM extraction parser.

Input:  raw clinician question (string), Anthropic client.
Output: ParsedQuery with anchor_terms, scenario_variables,
        question_summary, scope, extraction_confidence, and
        clarification populated. `intent` and `intent_description`
        remain None — they are populated by Step 1b.

Design principles (see qa_v7/__init__.py for the full architecture):

  - The parser extracts. It does NOT route. No topic string, no
    qualifier string, no section id comes out of this component.
  - The LLM sees a tight, purpose-built context: anchor vocabulary,
    scenario variables, AIS scope, and instructions. No topic map,
    no synonym dictionary, no intent map — those invite routing
    behavior the parser must not engage in.
  - Output is pure JSON matching the ParsedQuery schema. Parse
    failures degrade gracefully to a low-confidence result with a
    clarification instead of crashing the pipeline.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional, Tuple

from .schemas import ParsedQuery

logger = logging.getLogger(__name__)

_REFS_DIR = os.path.join(os.path.dirname(__file__), "references")
_ANCHOR_VOCAB_PATH = os.path.join(_REFS_DIR, "anchor_vocabulary.json")
_SCENARIO_VARS_PATH = os.path.join(_REFS_DIR, "scenario_variables.json")
_AIS_SCOPE_PATH = os.path.join(_REFS_DIR, "ais_scope.md")
_SYSTEM_PROMPT_PATH = os.path.join(_REFS_DIR, "parser_system_prompt.md")

# Module-level caches (references are immutable per process)
_anchor_vocab_cache: Optional[Dict[str, Any]] = None
_scenario_vars_cache: Optional[Dict[str, Any]] = None
_ais_scope_cache: Optional[str] = None
_system_prompt_base_cache: Optional[str] = None
_full_system_prompt_cache: Optional[str] = None


def _load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _get_anchor_vocab() -> Dict[str, Any]:
    global _anchor_vocab_cache
    if _anchor_vocab_cache is None:
        _anchor_vocab_cache = _load_json(_ANCHOR_VOCAB_PATH)
    return _anchor_vocab_cache


def _get_scenario_vars() -> Dict[str, Any]:
    global _scenario_vars_cache
    if _scenario_vars_cache is None:
        _scenario_vars_cache = _load_json(_SCENARIO_VARS_PATH)
    return _scenario_vars_cache


def _get_ais_scope() -> str:
    global _ais_scope_cache
    if _ais_scope_cache is None:
        _ais_scope_cache = _load_text(_AIS_SCOPE_PATH)
    return _ais_scope_cache


def _build_anchor_vocab_appendix() -> str:
    """Render the anchor vocabulary as a compact appendix.

    Grouped by category with terms as comma-separated lists.
    Keeps the prompt small; the vocabulary has ~1300 terms across
    11 categories, which is tractable in-context.
    """
    vocab = _get_anchor_vocab()
    lines = [
        "## Anchor Vocabulary",
        "",
        "Canonical clinical terms recognized by this pipeline. "
        "Emit anchor_terms using these canonical forms when a "
        "clinician's wording maps to one. Terms are grouped by "
        "category for readability; use whichever category a term "
        "fits — the parser output does not track category.",
        "",
    ]
    for cat, terms in vocab.get("categories", {}).items():
        lines.append(f"### {cat}")
        # Emit as a comma-separated block for token economy
        lines.append(", ".join(terms))
        lines.append("")
    return "\n".join(lines)


def _build_scenario_vars_appendix() -> str:
    """Render scenario variables as a clinician-facing appendix."""
    data = _get_scenario_vars()
    lines = [
        "## Scenario Variables",
        "",
        "Structured clinical fields to extract when the clinician "
        "states them. Emit in the canonical unit shown. Omit any "
        "field the clinician did not explicitly state.",
        "",
    ]
    for var_name, spec in data.get("variables", {}).items():
        vtype = spec.get("type", "")
        units = spec.get("units", "")
        values = spec.get("values", [])
        rng = spec.get("plausible_range")
        notes = spec.get("notes", "")
        parts = [f"### {var_name}", f"- type: {vtype}"]
        if units:
            parts.append(f"- units: {units}")
        if values:
            parts.append(f"- allowed values: {', '.join(values)}")
        if rng:
            parts.append(f"- plausible range: {rng[0]} to {rng[1]}")
        if notes:
            parts.append(f"- notes: {notes}")
        parts.append("")
        lines.extend(parts)
    return "\n".join(lines)


def _build_ais_scope_appendix() -> str:
    return _get_ais_scope()


def _get_full_system_prompt() -> str:
    """Compose the full system prompt: base instructions + appendices."""
    global _full_system_prompt_cache
    if _full_system_prompt_cache is not None:
        return _full_system_prompt_cache
    global _system_prompt_base_cache
    if _system_prompt_base_cache is None:
        _system_prompt_base_cache = _load_text(_SYSTEM_PROMPT_PATH)

    parts = [
        _system_prompt_base_cache,
        "",
        "---",
        "",
        _build_ais_scope_appendix(),
        "",
        "---",
        "",
        _build_scenario_vars_appendix(),
        "",
        "---",
        "",
        _build_anchor_vocab_appendix(),
    ]
    _full_system_prompt_cache = "\n".join(parts)
    return _full_system_prompt_cache


def _parse_json_output(text: str) -> Optional[Dict[str, Any]]:
    """Parse the LLM's JSON output.

    The prompt requires pure JSON with no markdown fences. We accept
    fences defensively because LLMs sometimes emit them anyway.
    No regex — string operations only (project rule).
    """
    if not text:
        return None
    s = text.strip()
    # Strip common markdown fences
    if s.startswith("```"):
        # Drop the first fence line entirely
        newline = s.find("\n")
        if newline != -1:
            s = s[newline + 1:]
        # Drop trailing fence
        if s.endswith("```"):
            s = s[: -3].rstrip()
    try:
        data = json.loads(s)
        if isinstance(data, dict):
            return data
        return None
    except json.JSONDecodeError as e:
        logger.warning("v7 parser: JSON decode failed: %s", e)
        return None


def _coerce_output(
    data: Dict[str, Any], raw_question: str,
) -> ParsedQuery:
    """Build a ParsedQuery from the LLM's JSON output, with
    defensive coercion for missing or malformed fields.
    """
    anchor_terms = data.get("anchor_terms") or {}
    if not isinstance(anchor_terms, dict):
        anchor_terms = {}

    scenario_variables = data.get("scenario_variables") or {}
    if not isinstance(scenario_variables, dict):
        scenario_variables = {}

    question_summary = str(data.get("question_summary") or "").strip()

    scope = str(data.get("scope") or "in_scope").strip().lower()
    if scope not in ("in_scope", "out_of_scope"):
        scope = "in_scope"

    try:
        confidence = float(data.get("extraction_confidence", 1.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    clarification_raw = data.get("clarification")
    clarification = (
        str(clarification_raw).strip()
        if clarification_raw not in (None, "", "null")
        else None
    )

    return ParsedQuery(
        anchor_terms=anchor_terms,
        scenario_variables=scenario_variables,
        question_summary=question_summary or raw_question,
        scope=scope,
        extraction_confidence=confidence,
        clarification=clarification,
        intent=None,
        intent_description=None,
        raw_question=raw_question,
    )


class QueryParserV7:
    """v7 Step 1a — LLM extraction parser.

    Usage:
        parser = QueryParserV7(nlp_client=anthropic_client)
        if parser.is_available:
            parsed, usage = await parser.parse("78yo NIHSS 18 ...")

    When `nlp_client` is None, `is_available` is False and callers
    should bypass the parser (return a service-unavailable response
    at the orchestrator level).
    """

    MODEL = "claude-sonnet-4-20250514"
    MAX_TOKENS = 1000

    def __init__(self, nlp_client: Any = None) -> None:
        self._client = nlp_client

    @property
    def is_available(self) -> bool:
        return self._client is not None

    async def parse(
        self, question: str,
    ) -> Tuple[ParsedQuery, Dict[str, int]]:
        """Run the extraction on a clinician question.

        Returns (ParsedQuery, usage_dict). On any error, returns a
        low-confidence ParsedQuery with a clarification rather than
        raising — Step 2 will short-circuit on the low confidence.
        """
        raw = (question or "").strip()
        if not raw:
            return (
                self._failure(
                    raw,
                    clarification="Please provide a question.",
                ),
                {"input_tokens": 0, "output_tokens": 0},
            )

        if not self.is_available:
            return (
                self._failure(
                    raw,
                    clarification="Parser service unavailable.",
                ),
                {"input_tokens": 0, "output_tokens": 0},
            )

        system_prompt = _get_full_system_prompt()
        user_prompt = f"Question: {raw}"

        try:
            response = self._client.messages.create(
                model=self.MODEL,
                max_tokens=self.MAX_TOKENS,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
        except Exception as e:
            logger.error("v7 parser LLM call failed: %s", e)
            return (
                self._failure(
                    raw,
                    clarification=f"Parser error: {e}",
                ),
                {"input_tokens": 0, "output_tokens": 0},
            )

        text = ""
        for block in response.content:
            if hasattr(block, "text"):
                text += block.text
        text = text.strip()

        usage = {
            "input_tokens": getattr(response.usage, "input_tokens", 0),
            "output_tokens": getattr(response.usage, "output_tokens", 0),
        }

        data = _parse_json_output(text)
        if not data:
            logger.warning(
                "v7 parser: could not parse JSON output; raw=%r",
                text[:300],
            )
            return (
                self._failure(
                    raw,
                    clarification=(
                        "The parser could not produce a structured "
                        "response. Please rephrase the question."
                    ),
                ),
                usage,
            )

        return _coerce_output(data, raw), usage

    @staticmethod
    def _failure(
        raw_question: str, *, clarification: str,
    ) -> ParsedQuery:
        return ParsedQuery(
            anchor_terms={},
            scenario_variables={},
            question_summary=raw_question,
            scope="in_scope",
            extraction_confidence=0.0,
            clarification=clarification,
            intent=None,
            intent_description=None,
            raw_question=raw_question,
        )
