"""
Clarification loop v2 — deterministic "should we clarify?" decision and
question-builder, driven by the parser's vagueness gate and the intent
catalog's required_slots.

The v2 design splits clarification into three moving parts, two of which
already live elsewhere:

1. **Merging a reply with the original question** — already handled by
   `QAOrchestrator._build_clarification_context` (v1 helper, intent-agnostic).
   The merged string is handed to `parse_v2` and the v2 parser schema
   (Step 5) already knows to treat a merged context as a second-turn
   reply and NOT re-ask the same ambiguity.

2. **Counting rounds** — already handled by
   `QAOrchestrator._count_clarification_rounds`.

3. **Deciding when to clarify and what to ask** — this module.

`decide_clarification_v2` returns a `ClarificationDecision`. The
orchestrator calls it AFTER `parse_v2 → verify → rescore` and BEFORE
`route_v2 → dispatch_focused_agent → assemble_v2`. If the decision says
"clarify", the orchestrator emits the clarification question as the
assistant turn and waits for the user's reply. If it says "answer" (or
"give up and best-effort"), the pipeline proceeds.

Hard rules:
- Never clarify when the intent is `out_of_scope`.
- Never clarify when every required slot is already filled.
- Never exceed `max_rounds` (default 2). After the limit, best-effort
  route with whatever we have — downstream scaffolding_verifier and
  route_v2 will decline gracefully if that isn't enough.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .scaffolding_loader import ScaffoldingBundle, get_scaffolding
from .schemas import ParsedQAQueryV2, VnIntent

# Max clarification rounds per session. Matches v1 behavior.
MAX_CLARIFICATION_ROUNDS = 2


# Answer shapes where a missing optional slot is just a filter. For
# these, if AT LEAST ONE required slot is filled, the pipeline should
# return the full list rather than ask a clarification question. The
# user can always refine the answer in a follow-up turn.
_LIST_SHAPED_ANSWERS = {
    "list_of_criteria",
    "list_with_qualifiers",
    "risk_factor_list",
    "parameter_list_with_frequency",
    "protocol_element_list",
    "test_list_with_required_flag",
    "ordered_list",
    "ordered_management_steps",
    "screening_protocol",
    "reassessment_protocol",
    "reversal_protocol",
}


@dataclass
class ClarificationDecision:
    """Output of `decide_clarification_v2`.

    - `should_clarify` — True when the orchestrator should emit a
      clarification turn.
    - `question` — the user-facing clarification text. Empty when
      `should_clarify=False`.
    - `missing_slots` — slot names that are still unfilled. Populated
      even when `should_clarify=False` so the audit trail records what
      the best-effort path is missing.
    - `reason` — one-sentence explanation for the dev_log.
    - `round_after` — the clarification round count after this turn (only
      meaningful when `should_clarify=True`).
    """

    should_clarify: bool
    question: str = ""
    missing_slots: List[str] = field(default_factory=list)
    reason: str = ""
    round_after: int = 0


# ---------------------------------------------------------------------------
# Slot phrasing — compact templates for common slot names
# ---------------------------------------------------------------------------

# When a required slot is missing, we emit a specific question for the
# most common slot names and fall back to a generic phrasing for the rest.
# Keep this mapping tight: every entry should sound natural when dropped
# into "Could you tell me <phrase>?".
_SLOT_PHRASES: Dict[str, str] = {
    "treatment_or_procedure": "which treatment or procedure you're asking about (e.g., IV alteplase, tenecteplase, EVT)",
    "drug_or_agent": "which drug or agent you mean",
    "condition": "which specific condition or finding you're asking about",
    "clinical_scenario": "the clinical scenario (e.g., anterior LVO within 6h, extended-window IVT)",
    "intervention": "which intervention you mean (e.g., IVT, EVT, anticoagulation)",
    "first_line_option": "which first-line option the patient can't receive",
    "reason_unavailable_or_unsuitable": "why the first-line option isn't an option",
    "actions_to_order": "which actions you want ordered in sequence",
    "therapy_or_protocol": "which therapy or protocol",
    "action": "which action you mean",
    "parameter": "which parameter (e.g., blood pressure, glucose, SpO2)",
    "context": "the clinical context (pre-IVT, post-EVT, in-hospital, etc.)",
    "metric": "which metric (e.g., door-to-needle, onset-to-treatment)",
    "anchor_event": "which event you want this measured against",
    "clinical_decision": "which clinical decision you're trying to make",
    "test_name": "which test you mean",
    "screening_target": "which condition you want to screen for",
    "reassessment_target": "what you want to reassess",
    "anchor_treatment": "which treatment the post-treatment care follows",
    "complication": "which complication you're managing",
    "agent_to_reverse": "which agent you want to reverse",
    "outcome": "which outcome (e.g., sICH, mortality, 90-day mRS)",
    "recommendation_subject": "which recommendation you want the COR/LOE for",
    "term": "which term you want defined",
    "topic": "which guideline topic you're asking about",
    "screening_target ": "which condition you want to screen for",
}


def _phrase_for_slot(slot: str) -> str:
    """Return a natural-language phrase for a slot name."""
    phrase = _SLOT_PHRASES.get(slot)
    if phrase:
        return phrase
    # Generic fallback: humanize the slot name.
    return slot.replace("_", " ")


def _build_question(missing: List[str], intent: VnIntent) -> str:
    """Build a single clarification question from missing slot names.

    One missing slot → one focused question. Two+ slots → bundle them
    so we don't spend multiple rounds asking one at a time.
    """
    intent_hint = intent.value.replace("_", " ")
    if len(missing) == 1:
        return (
            f"Before I answer your {intent_hint} question, could you tell me "
            f"{_phrase_for_slot(missing[0])}?"
        )
    phrases = [_phrase_for_slot(s) for s in missing]
    joined = "; and ".join(phrases) if len(phrases) == 2 else ", ".join(
        phrases[:-1]
    ) + "; and " + phrases[-1]
    return (
        f"Before I answer your {intent_hint} question, could you tell me "
        f"{joined}?"
    )


# ---------------------------------------------------------------------------
# Decision
# ---------------------------------------------------------------------------


def decide_clarification_v2(
    parsed: ParsedQAQueryV2,
    rounds_so_far: int,
    bundle: Optional[ScaffoldingBundle] = None,
    max_rounds: int = MAX_CLARIFICATION_ROUNDS,
) -> ClarificationDecision:
    """
    Decide whether to emit a clarification turn for the v2 pipeline.

    Args:
        parsed: the ParsedQAQueryV2 coming out of parse_v2 + verifier + re-scorer.
        rounds_so_far: how many clarification turns have already occurred
            in this session (from `_count_clarification_rounds`).
        bundle: the scaffolding bundle. Loaded lazily if None.
        max_rounds: hard cap on clarification rounds. Default 2.

    Returns:
        ClarificationDecision.
    """
    bundle = bundle or get_scaffolding()

    # Never clarify out-of-scope — the decline path is instant.
    if parsed.intent == VnIntent.OUT_OF_SCOPE:
        return ClarificationDecision(
            should_clarify=False,
            reason="intent=out_of_scope; no clarification possible",
        )

    # Look up required_slots from the catalog. If the intent entry is
    # missing (shouldn't happen after Step 4c drift check), fall through
    # to best-effort routing.
    intent_entry = bundle.intent(parsed.intent.value) or {}
    required = list(intent_entry.get("required_slots") or [])
    if not required:
        return ClarificationDecision(
            should_clarify=False,
            reason=f"intent '{parsed.intent.value}' has no required_slots",
        )

    # What's missing AFTER the parser and verifier had a chance to fill slots?
    slots = parsed.slots or {}
    missing = [
        s for s in required
        if s not in slots or slots[s] in (None, "", [])
    ]

    if not missing:
        return ClarificationDecision(
            should_clarify=False,
            reason="all required slots filled",
        )

    # List-shaped answers degrade gracefully: if at least one required
    # slot is filled, we skip clarification and return the full list.
    # Missing slots become filters the user can apply in a follow-up.
    answer_shape = intent_entry.get("answer_shape") or ""
    filled = [s for s in required if s not in missing]
    if answer_shape in _LIST_SHAPED_ANSWERS and filled:
        return ClarificationDecision(
            should_clarify=False,
            missing_slots=missing,
            reason=(
                f"list-shaped answer '{answer_shape}' with "
                f"{len(filled)}/{len(required)} slots filled — "
                f"best-effort list, missing={missing}"
            ),
        )

    # Out of rounds — best-effort route with what we have. The downstream
    # focused agent will degrade gracefully (LLM extraction with whatever
    # slots are present) or route_v2 / assemble_v2 will decline.
    if rounds_so_far >= max_rounds:
        return ClarificationDecision(
            should_clarify=False,
            missing_slots=missing,
            reason=(
                f"max clarification rounds ({max_rounds}) reached; "
                f"best-effort routing with missing={missing}"
            ),
        )

    # Emit a clarification question for the missing slots.
    question = _build_question(missing, parsed.intent)
    return ClarificationDecision(
        should_clarify=True,
        question=question,
        missing_slots=missing,
        reason=f"missing required slots: {missing}",
        round_after=rounds_so_far + 1,
    )


__all__ = [
    "ClarificationDecision",
    "MAX_CLARIFICATION_ROUNDS",
    "decide_clarification_v2",
]
