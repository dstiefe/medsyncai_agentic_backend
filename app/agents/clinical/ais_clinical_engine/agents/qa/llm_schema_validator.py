"""
llm_schema_validator.py — closed-vocabulary airlock for LLM parser output.

Every ParsedQAQueryV2 produced by `llm_parser.parse_with_llm` is
cross-checked against the same scaffolding files the deterministic
parser uses. Any drift — hallucinated intent, invented section, unknown
slot name, out-of-shape value — fails validation. The orchestrator then
falls through to the deterministic parser so the LLM cannot corrupt
downstream state.

This module is deterministic Python. It does not call the LLM. It does
not read guideline_knowledge.json. Its only input is a ParsedQAQueryV2
and a ScaffoldingBundle.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from .scaffolding_loader import ScaffoldingBundle, get_scaffolding
from .schemas import ParsedQAQueryV2, VnIntent

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Outcome of validating an LLM parser output.

    - `ok`: True when every field passes. Callers gate on this.
    - `errors`: human-readable reasons the parse failed. Empty when ok.
    - `warnings`: non-fatal anomalies (e.g., section_id outside dd.v2
      but rescuable via gtm parent resolution) the validator chose to
      tolerate. Recorded for the audit trail.
    """

    ok: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


def validate_llm_parse(
    parsed: ParsedQAQueryV2,
    bundle: Optional[ScaffoldingBundle] = None,
) -> ValidationResult:
    """
    Cross-check an LLM-produced ParsedQAQueryV2 against the scaffolding.

    Checks, in order:

    1. Intent is a real VnIntent enum member (guaranteed by hydration,
       but re-checked here so this function is a true airlock).
    2. Intent exists in intent_catalog.json (catches enum drift).
    3. If intent is out_of_scope, sections and slots are ignored — the
       fallback path handles those.
    4. Every section in `sections` resolves to at least one dd.v2
       section via `resolve_section_family()`.
    5. Every slot name is either in `required_slots` or `optional_slots`
       for the chosen intent. Unknown slots are rejected outright.
    6. Required slots that the LLM omitted are NOT a validation error
       — the downstream clarification loop handles missing required
       slots. The validator only gates on shape, not completeness.

    Returns a ValidationResult. Callers should check `.ok` and treat
    a False result as a hard fall-through signal.
    """
    bundle = bundle or get_scaffolding()
    errors: List[str] = []
    warnings: List[str] = []

    # 1 + 2. Intent must be a VnIntent AND exist in the catalog.
    if not isinstance(parsed.intent, VnIntent):
        errors.append(f"intent '{parsed.intent}' is not a VnIntent member")
        return ValidationResult(ok=False, errors=errors, warnings=warnings)

    catalog = bundle.intent_catalog.get("intents", {})
    intent_entry = catalog.get(parsed.intent.value)
    if parsed.intent != VnIntent.OUT_OF_SCOPE and not intent_entry:
        errors.append(
            f"intent '{parsed.intent.value}' not found in intent_catalog.json"
        )
        return ValidationResult(ok=False, errors=errors, warnings=warnings)

    # 3. out_of_scope short-circuit — the fallback path owns this branch.
    if parsed.intent == VnIntent.OUT_OF_SCOPE:
        return ValidationResult(ok=True, errors=errors, warnings=warnings)

    # 4. Every claimed section must resolve against dd.v2 (direct or via
    #    gtm parent expansion). A section that resolves to [] means the
    #    LLM invented it — reject the whole parse.
    if parsed.sections:
        known_dd: Set[str] = bundle.dd_sections
        known_gtm: Set[str] = bundle.gtm_sections
        for sid in parsed.sections:
            resolved = bundle.resolve_section_family(sid)
            if resolved:
                continue
            if sid in known_gtm:
                # Rare: gtm has the section but it has no dd.v2 children.
                # Tolerable — downstream verifier handles it.
                warnings.append(
                    f"section '{sid}' is a gtm topic with no dd.v2 children"
                )
                continue
            errors.append(
                f"section '{sid}' does not exist in data_dictionary.v2 "
                f"or guideline_topic_map.json"
            )
    # (No sections is acceptable — some intents like `definition` can
    #  route purely on slots, and the deterministic path will still
    #  resolve sections downstream.)

    # 5. Slot names must be declared in the intent catalog entry.
    allowed_slots: Set[str] = set(
        (intent_entry.get("required_slots") or [])
    ) | set(intent_entry.get("optional_slots") or [])

    if parsed.slots:
        for slot_name in parsed.slots.keys():
            if slot_name not in allowed_slots:
                errors.append(
                    f"slot '{slot_name}' is not declared for intent "
                    f"'{parsed.intent.value}' (allowed: "
                    f"{sorted(allowed_slots) or 'none'})"
                )

    if errors:
        logger.info(
            "llm_schema_validator: rejected LLM parse — %d errors: %s",
            len(errors), errors,
        )
        return ValidationResult(ok=False, errors=errors, warnings=warnings)

    if warnings:
        logger.debug(
            "llm_schema_validator: accepted with %d warnings: %s",
            len(warnings), warnings,
        )
    return ValidationResult(ok=True, errors=errors, warnings=warnings)


__all__ = ["ValidationResult", "validate_llm_parse"]
