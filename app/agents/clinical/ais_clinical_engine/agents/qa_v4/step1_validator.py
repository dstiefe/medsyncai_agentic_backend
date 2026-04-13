# ─── v4 (Q&A v4 namespace) ─────────────────────────────────────────────
# Step 2: Validate Step 1 output before retrieval.
#
# Pure Python. No LLM. No regex. Deterministic checks only.
#
# Catches LLM hallucination in Step 1 output:
#   - Invalid intent (not in 38-item enum)
#   - Invalid topic (not in 38-item enum)
#   - Ungrounded anchor terms (not in reference vocabulary)
#   - Clinical variable values not in original question
#   - Low confidence threshold
#
# Every check uses the same reference files Step 1's LLM was given,
# so the validation vocabulary is identical to the generation vocabulary.
# ───────────────────────────────────────────────────────────────────────
"""
Step 2: Validate Step 1 (LLM question understanding) output.

Deterministic Python checks that catch hallucination before
it reaches the retrieval layer. Returns a validated (and possibly
corrected) ParsedQAQuery plus a list of what was fixed.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from .schemas import ParsedQAQuery

logger = logging.getLogger(__name__)

_REF_DIR = os.path.join(os.path.dirname(__file__), "references")

# ── Confidence floor ─────────────────────────────────────────────────
# Below this threshold, the question is too uncertain to route.
_CONFIDENCE_FLOOR = 0.3


# ── Reference vocabulary (loaded once, cached) ──────────────────────

def _load_json(filename: str) -> dict:
    path = os.path.join(_REF_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


class _ReferenceVocab:
    """Lazy-loaded reference vocabulary for validation checks."""

    _instance: Optional[_ReferenceVocab] = None

    def __init__(self):
        self._valid_intents: Optional[Set[str]] = None
        self._valid_topics: Optional[Set[str]] = None
        self._anchor_vocab: Optional[Set[str]] = None
        self._topic_to_section: Optional[Dict[str, str]] = None
        self._anchor_to_sections: Optional[Dict[str, List[str]]] = None

    @classmethod
    def get(cls) -> _ReferenceVocab:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @property
    def valid_intents(self) -> Set[str]:
        if self._valid_intents is None:
            data = _load_json("intent_content_source_map.json")
            self._valid_intents = {e["intent"] for e in data["intents"]}
        return self._valid_intents

    @property
    def valid_topics(self) -> Set[str]:
        if self._valid_topics is None:
            data = _load_json("guideline_topic_map.json")
            self._valid_topics = {e["topic"] for e in data["topics"]}
        return self._valid_topics

    @property
    def topic_to_section(self) -> Dict[str, str]:
        """Topic name → primary section number."""
        if self._topic_to_section is None:
            data = _load_json("guideline_topic_map.json")
            self._topic_to_section = {
                e["topic"]: e["section"] for e in data["topics"]
            }
        return self._topic_to_section

    @property
    def anchor_vocab(self) -> Set[str]:
        """All anchor terms across all sections, lowercased."""
        if self._anchor_vocab is None:
            self._anchor_vocab = set()
            data = _load_json("guideline_anchor_words.json")
            # Section-level terms
            for sec_data in data.get("sections", {}).values():
                aw = sec_data.get("anchor_words", {})
                for terms in aw.values():
                    if isinstance(terms, list):
                        for t in terms:
                            self._anchor_vocab.add(t.lower())
            # Special tables
            for tbl_data in data.get("special_tables", {}).values():
                aw = tbl_data.get("anchor_words", [])
                if isinstance(aw, list):
                    for t in aw:
                        self._anchor_vocab.add(t.lower())
                elif isinstance(aw, dict):
                    for terms in aw.values():
                        if isinstance(terms, list):
                            for t in terms:
                                self._anchor_vocab.add(t.lower())
            # Special figures
            for fig_data in data.get("special_figures", {}).values():
                aw = fig_data.get("anchor_words", [])
                if isinstance(aw, list):
                    for t in aw:
                        self._anchor_vocab.add(t.lower())
                elif isinstance(aw, dict):
                    for terms in aw.values():
                        if isinstance(terms, list):
                            for t in terms:
                                self._anchor_vocab.add(t.lower())
        return self._anchor_vocab

    @property
    def anchor_to_sections(self) -> Dict[str, List[str]]:
        """Lowercased anchor term → list of section IDs where it appears."""
        if self._anchor_to_sections is None:
            self._anchor_to_sections = {}
            data = _load_json("guideline_anchor_words.json")
            for sec_id, sec_data in data.get("sections", {}).items():
                aw = sec_data.get("anchor_words", {})
                for terms in aw.values():
                    if isinstance(terms, list):
                        for t in terms:
                            key = t.lower()
                            if key not in self._anchor_to_sections:
                                self._anchor_to_sections[key] = []
                            if sec_id not in self._anchor_to_sections[key]:
                                self._anchor_to_sections[key].append(sec_id)
        return self._anchor_to_sections


# ── Validation result ────────────────────────────────────────────────

@dataclass
class ValidationResult:
    """Output of Step 2 validation.

    The `action` field is the single routing decision:
      - "proceed"                 All checks pass, or corrections made but
                                  routing is still possible (topic or anchors survive).
      - "proceed_low_confidence"  Valid routing signals exist but extraction
                                  confidence is below the floor. Step 3 runs
                                  but downstream may weight results lower.
      - "stop_clarify"            No routing signal after corrections (no topic
                                  AND no anchors). Return clarification to user.
      - "stop_out_of_scope"       Step 1 flagged off_topic. Return scope
                                  message — don't attempt routing.
    """

    query: ParsedQAQuery               # validated (possibly corrected) query
    action: str = "proceed"             # "proceed" | "proceed_low_confidence" | "stop_clarify" | "stop_out_of_scope"
    corrections: List[str] = field(default_factory=list)  # what was fixed
    warnings: List[str] = field(default_factory=list)     # non-fatal issues
    dropped_anchor_terms: List[str] = field(default_factory=list)
    dropped_variables: List[str] = field(default_factory=list)
    stop_message: Optional[str] = None  # user-facing message when action is stop_*

    def to_audit_dict(self) -> Dict[str, Any]:
        """Audit trail entry for this validation step."""
        return {
            "step": "step2_validation",
            "detail": {
                "action": self.action,
                "corrections": self.corrections,
                "warnings": self.warnings,
                "dropped_anchor_terms": self.dropped_anchor_terms,
                "dropped_variables": self.dropped_variables,
                "stop_message": self.stop_message,
            },
        }


# ── Main validation function ─────────────────────────────────────────

def validate_step1_output(
    parsed: ParsedQAQuery,
    raw_query: str,
) -> ValidationResult:
    """
    Validate Step 1 LLM output against reference vocabulary.

    Checks:
    1. Intent is one of 44 valid intents
    2. Topic is one of 38 valid topics
    3. Anchor terms exist in guideline_anchor_words.json
    4. Clinical variable values appear in the original question
    5. Confidence meets minimum threshold
    6. Clarification reason is valid enum value

    Returns a ValidationResult with the (possibly corrected) query.
    """
    vocab = _ReferenceVocab.get()
    result = ValidationResult(query=parsed)

    # ── Early exit: off-topic ────────────────────────────────────
    # Step 1 already identified this as outside AIS guidelines.
    # Don't attempt routing — return scope message immediately.
    if parsed.clarification_reason == "off_topic":
        result.action = "stop_out_of_scope"
        result.stop_message = (
            parsed.clarification
            or "This question falls outside the scope of the "
            "2026 AHA/ASA Acute Ischemic Stroke Guidelines."
        )
        return result

    # ── Run all checks ───────────────────────────────────────────
    _check_intent(parsed, vocab, result)
    _check_topic(parsed, vocab, result)
    _check_anchor_terms(parsed, vocab, result)
    _check_clinical_variables(parsed, raw_query, result)
    _check_confidence(parsed, result)
    _check_clarification_reason(parsed, result)

    # ── Determine action ─────────────────────────────────────────
    has_routing = bool(parsed.topic) or bool(parsed.anchor_terms)
    low_confidence = parsed.extraction_confidence < _CONFIDENCE_FLOOR
    step1_asked_for_clarification = parsed.clarification_reason in (
        "vague_with_anchor", "vague_no_anchor", "topic_ambiguity",
    )

    if not has_routing:
        # No routing signal after corrections — can't proceed.
        result.action = "stop_clarify"
        result.stop_message = (
            parsed.clarification
            or "I wasn't able to identify enough clinical context in your "
            "question to find the right guideline content. Could you "
            "rephrase or be more specific about what you're looking for?"
        )
    elif step1_asked_for_clarification:
        # Step 1 explicitly said "I don't understand enough."
        # Routing signals exist but Step 1 flagged ambiguity.
        # Respect that — ask the user, don't guess.
        result.action = "stop_clarify"
        result.stop_message = parsed.clarification
    elif low_confidence:
        # Routing signals exist, Step 1 didn't flag ambiguity,
        # but confidence is low. Proceed with caution.
        result.action = "proceed_low_confidence"
        result.warnings.append(
            f"Extraction confidence {parsed.extraction_confidence:.2f} "
            f"below floor {_CONFIDENCE_FLOOR}"
        )
    else:
        # All checks pass, or corrections made but routing survives.
        result.action = "proceed"

    if result.corrections:
        logger.info(
            "Step 2 validation corrected Step 1 output: %s",
            "; ".join(result.corrections),
        )

    return result


# ── Individual checks ────────────────────────────────────────────────

def _check_intent(
    parsed: ParsedQAQuery,
    vocab: _ReferenceVocab,
    result: ValidationResult,
) -> None:
    """Verify intent is in the 44-item enum."""
    if parsed.intent is None:
        return  # clarification case — no intent is valid

    if parsed.intent not in vocab.valid_intents:
        result.corrections.append(
            f"Invalid intent '{parsed.intent}' — defaulting to 'clinical_overview'"
        )
        parsed.intent = "clinical_overview"


def _check_topic(
    parsed: ParsedQAQuery,
    vocab: _ReferenceVocab,
    result: ValidationResult,
) -> None:
    """Verify topic is in the 38-item enum. Try to recover from anchor terms."""
    if parsed.topic is None:
        # If we have grounded anchor terms, try to infer topic from them
        if parsed.anchor_terms:
            inferred = _infer_topic_from_anchors(parsed.anchor_terms, vocab)
            if inferred:
                parsed.topic = inferred
                result.corrections.append(
                    f"Topic was null — inferred '{inferred}' from anchor terms"
                )
        return

    if parsed.topic not in vocab.valid_topics:
        # Try to recover from anchor terms
        inferred = _infer_topic_from_anchors(parsed.anchor_terms, vocab)
        if inferred:
            result.corrections.append(
                f"Invalid topic '{parsed.topic}' — inferred '{inferred}' from anchor terms"
            )
            parsed.topic = inferred
        else:
            result.corrections.append(
                f"Invalid topic '{parsed.topic}' — set to null"
            )
            parsed.topic = None


def _check_anchor_terms(
    parsed: ParsedQAQuery,
    vocab: _ReferenceVocab,
    result: ValidationResult,
) -> None:
    """Drop anchor terms not in the reference vocabulary."""
    if not parsed.anchor_terms:
        return

    grounded = []
    for term in parsed.anchor_terms:
        if term.lower() in vocab.anchor_vocab:
            grounded.append(term)
        else:
            result.dropped_anchor_terms.append(term)

    if result.dropped_anchor_terms:
        result.corrections.append(
            f"Dropped {len(result.dropped_anchor_terms)} ungrounded anchor term(s): "
            f"{result.dropped_anchor_terms}"
        )
        parsed.anchor_terms = grounded


def _check_clinical_variables(
    parsed: ParsedQAQuery,
    raw_query: str,
    result: ValidationResult,
) -> None:
    """Verify every numeric clinical variable value appears in the original question."""
    if not parsed.clinical_variables:
        return

    query_lower = raw_query.lower()
    to_drop = []

    for key, value in parsed.clinical_variables.items():
        # Only check numeric values — strings and booleans pass through
        if isinstance(value, (int, float)):
            # The number must appear somewhere in the original question
            # Check both the raw number and common representations
            str_val = str(value)
            int_str = str(int(value)) if isinstance(value, float) and value == int(value) else None

            found = str_val in query_lower
            if not found and int_str:
                found = int_str in query_lower

            if not found:
                to_drop.append(key)
                result.dropped_variables.append(f"{key}={value}")

        elif isinstance(value, dict):
            # Range dict like {"min": 0, "max": 2} — check both values
            for subkey in ("min", "max"):
                subval = value.get(subkey)
                if isinstance(subval, (int, float)):
                    str_val = str(subval)
                    int_str = str(int(subval)) if isinstance(subval, float) and subval == int(subval) else None
                    found = str_val in query_lower
                    if not found and int_str:
                        found = int_str in query_lower
                    if not found:
                        to_drop.append(key)
                        result.dropped_variables.append(f"{key}.{subkey}={subval}")
                        break  # don't double-count

    if to_drop:
        for key in to_drop:
            del parsed.clinical_variables[key]
        result.corrections.append(
            f"Dropped {len(to_drop)} clinical variable(s) not found in question: "
            f"{result.dropped_variables}"
        )
        # Fix is_criterion_specific if we dropped everything
        if not parsed.clinical_variables:
            parsed.is_criterion_specific = False

    # Override LLM self-reported values_verified with our actual check
    parsed.values_verified = len(to_drop) == 0 and bool(parsed.clinical_variables)


def _check_confidence(
    parsed: ParsedQAQuery,
    result: ValidationResult,
) -> None:
    """Log a warning if confidence is low. Action is decided in the main function."""
    # Confidence-based routing is handled in validate_step1_output()
    # after all checks run. This function exists for future per-field
    # confidence checks if needed.
    pass


def _check_clarification_reason(
    parsed: ParsedQAQuery,
    result: ValidationResult,
) -> None:
    """Verify clarification_reason is a valid enum value."""
    valid_reasons = {"off_topic", "vague_with_anchor", "vague_no_anchor", "topic_ambiguity"}

    if parsed.clarification_reason is not None:
        if parsed.clarification_reason not in valid_reasons:
            result.corrections.append(
                f"Invalid clarification_reason '{parsed.clarification_reason}' — set to null"
            )
            parsed.clarification_reason = None


# ── Helpers ──────────────────────────────────────────────────────────

# Intents that are inherently broad — they ask for "everything about X"
# or a general overview. When paired with high section fan-out and no
# other narrowing signals, the question is too vague.

def _infer_topic_from_anchors(
    anchor_terms: List[str],
    vocab: _ReferenceVocab,
) -> Optional[str]:
    """Try to infer a valid topic from anchor terms.

    Strategy: find which sections the anchor terms point to,
    then find which topic maps to the section with the most hits.
    """
    if not anchor_terms:
        return None

    # Count section hits from anchor terms
    section_counts: Dict[str, int] = {}
    for term in anchor_terms:
        sections = vocab.anchor_to_sections.get(term.lower(), [])
        for sec in sections:
            section_counts[sec] = section_counts.get(sec, 0) + 1

    if not section_counts:
        return None

    # Find the section with the most hits
    best_section = max(section_counts, key=section_counts.get)

    # Reverse lookup: which topic maps to this section?
    section_to_topic = {v: k for k, v in vocab.topic_to_section.items()}
    topic = section_to_topic.get(best_section)

    # If exact section doesn't match, try parent section (e.g. 4.6.2 → 4.6)
    if not topic and "." in best_section:
        parent = best_section.rsplit(".", 1)[0]
        topic = section_to_topic.get(parent)

    return topic
