# ─── v3 (Q&A v3 namespace) ─────────────────────────────────────────────
# This service module is part of the Q&A v3 pipeline. It is imported
# only by code under agents/qa_v3/ and by services/qa_v3_filter.py.
# The prior agents/qa/ tree has been archived to agents/_archive_qa_v2/
# and is no longer imported anywhere in the live route.
# ───────────────────────────────────────────────────────────────────────
"""
Deterministic clarification builders driven by intent + anchors.

The LLM parser already emits its own clarification text when it is
uncertain up front. This module provides Python-side clarification
triggers that fire AFTER routing and filtering, when the data itself
tells us the pipeline cannot give a safe answer without more input.

Design rules (from transcript msg #88):
  "We also need triggers for clarification. but use the intent or
   anchors to help build the clarification question."

Triggers:

  1. EMPTY_SURVIVAL
     Routing picked a section, but the anchor-survival filter dropped
     every rec and every RSS paragraph in that section. The section
     contains none of the user's canonical anchors — either routing
     was wrong or the anchors are absent from the guideline. Ask the
     user to narrow down.

  2. MULTI_SECTION_TIE
     The anchor-vocab section ranker returned two or more sections
     with the same top score (or within one anchor of each other),
     and topic_map subtopic disambiguation did not pick a winner.
     Ask the user which of the candidate topics they mean.

  3. MISSING_SLOTS
     The parsed intent requires patient variables that are not in the
     parsed_query (e.g. eligibility questions need NIHSS / time / vessel).
     Ask for the missing slots by name. This is a deterministic backup
     to the LLM parser's own missing_clinical_context clarification.

Every builder returns ``Optional[str]``:
  - ``None`` means "no clarification needed — continue the pipeline".
  - A string means "return this verbatim to the user as the
    clarification message".

Builders never fabricate clinical content. Every label they emit is
pulled from the scaffolding (synonym_dictionary, topic_map, or
intent catalog values observed in the parsed_query), so clarifications
are always grounded in the same closed vocabulary used elsewhere in
the pipeline.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _friendly_anchor(term_id: str) -> str:
    """Turn a canonical term_id into a human label.

    Synthetic concept_expansion keys are stored as ``_concept:blood pressure``.
    Real synonym_dictionary entries use term_ids like ``BP``, ``TNK``, etc.
    The synonym_dictionary's full_term is not carried on the vocab object,
    so we fall back to a best-effort cleanup of the term_id. Callers that
    have the full vocab can pre-map term_id → label if they want prettier
    output.
    """
    if not term_id:
        return ""
    if term_id.startswith("_concept:"):
        return term_id.split(":", 1)[1]
    return term_id


def _join_anchor_phrase(anchors: Iterable[str]) -> str:
    """Produce "DWI-FLAIR, extended window, and tenecteplase" style text."""
    items = [a for a in (_friendly_anchor(t) for t in anchors) if a]
    items = sorted(set(items))
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-1]) + f", and {items[-1]}"


# ---------------------------------------------------------------------------
# Trigger 1: empty survival
# ---------------------------------------------------------------------------

def clarify_empty_survival(
    anchors: List[str],
    section_id: str,
    section_title: str = "",
) -> Optional[str]:
    """Trigger 1: routing picked a section but no rec/paragraph survived
    the anchor filter inside it.

    Args:
        anchors: canonical anchors extracted from the question
        section_id: the section the router picked (e.g. "4.6.3")
        section_title: human-readable section title if available

    Returns:
        Clarification text, or None when there is nothing to ask (e.g.
        the question has zero anchors — we have no data to build a
        grounded question from).
    """
    if not anchors:
        return None

    anchor_phrase = _join_anchor_phrase(anchors)
    if not anchor_phrase:
        return None

    sect = f"§{section_id}"
    if section_title:
        sect = f"{sect} ({section_title})"

    msg = (
        f"I understood your question to be about {anchor_phrase}, "
        f"and routing pointed to {sect}, but none of the recommendations "
        f"or supporting text in that section mention those concepts. "
        f"Could you confirm the clinical topic you're asking about, "
        f"or rephrase using the specific term (drug, imaging modality, "
        f"vessel, time window) that matters most?"
    )
    logger.info(
        "clarify_empty_survival: anchors=%s section=%s", anchors, section_id
    )
    return msg


# ---------------------------------------------------------------------------
# Trigger 2: multi-section tie
# ---------------------------------------------------------------------------

def _topic_label(topic_map: Dict[str, Any], section_id: str) -> Optional[str]:
    """Walk guideline_topic_map.json and return the topic string (or
    subtopic qualifier) whose section matches the given id.

    Returns None when nothing matches — caller should fall back to the
    bare section id.
    """
    if not topic_map or not section_id:
        return None
    for entry in topic_map.get("topics", []) or []:
        if entry.get("section") == section_id:
            return entry.get("topic")
        for sub in entry.get("subtopics", []) or []:
            if sub.get("section") == section_id:
                # Combine parent topic + subtopic qualifier
                parent = entry.get("topic", "").strip()
                qualifier = sub.get("qualifier", "").strip()
                if parent and qualifier:
                    return f"{parent} — {qualifier}"
                return qualifier or parent or None
    return None


def clarify_multi_section_tie(
    anchors: List[str],
    candidates: List[Tuple[str, int]],
    topic_map: Optional[Dict[str, Any]] = None,
    *,
    max_options: int = 3,
    tie_window: int = 1,
) -> Optional[str]:
    """Trigger 2: the router returned multiple sections with near-equal
    anchor scores and cannot safely pick a single winner.

    Args:
        anchors: canonical anchors extracted from the question
        candidates: list of (section_id, anchor_score) tuples, already
            ranked best-first by the caller. Scores at the top of the
            list that fall within ``tie_window`` of the leader are
            treated as tied.
        topic_map: optional guideline_topic_map.json dict, used to map
            section ids to human-readable topic labels.
        max_options: cap on how many tied options to present.
        tie_window: a candidate counts as tied if leader_score - its
            score is strictly less than this value. Default 1 means
            only exact-score ties clarify; use 2 to also clarify near
            ties where the next section is 1 anchor behind.

    Returns:
        Clarification text listing the tied options, or None when there
        is no real tie (one clear winner).
    """
    if not candidates:
        return None

    candidates = [(s, n) for s, n in candidates if s]
    if len(candidates) < 2:
        return None

    top_score = candidates[0][1]
    if top_score <= 0:
        return None  # nothing matched — that's a different trigger

    tied = [
        (sec, n) for sec, n in candidates
        if top_score - n < tie_window
    ]
    if len(tied) < 2:
        return None
    tied = tied[:max_options]

    # Build a "1. ... 2. ... 3. ..." option list using topic labels.
    lines: List[str] = []
    for i, (sec, _score) in enumerate(tied, start=1):
        label = _topic_label(topic_map or {}, sec) or f"Section {sec}"
        lines.append(f"  {i}. {label} (§{sec})")

    anchor_phrase = _join_anchor_phrase(anchors)
    header = "I understood your question to be about "
    if anchor_phrase:
        header += f"{anchor_phrase}. "
    header += (
        "It could be answered by more than one part of the 2026 AHA/ASA AIS "
        "Guideline. Which of these did you mean?"
    )

    msg = header + "\n\n" + "\n".join(lines)
    logger.info(
        "clarify_multi_section_tie: anchors=%s tied=%s",
        anchors, [s for s, _ in tied],
    )
    return msg


# ---------------------------------------------------------------------------
# Trigger 3: missing required slots
# ---------------------------------------------------------------------------

# Intents that are fundamentally patient-specific. When the parser
# picks one of these but no patient variables are present, we ask.
# This is a safety net — the LLM parser is supposed to emit its own
# "missing_clinical_context" clarification first. If it doesn't, we do.
_PATIENT_SPECIFIC_INTENTS = {
    "eligibility",
    "patient_eligibility",
    "treatment_protocol",
    "treatment_recommendation",
    "safety",
    "contraindication_check",
}

# Slots considered "required" per intent. These lists are intentionally
# small and specific — asking for every possible variable makes the
# clarification noisy.
_REQUIRED_SLOTS_BY_INTENT: Dict[str, List[str]] = {
    "eligibility":            ["nihss", "time_from_lkw_hours", "vessel_occlusion"],
    "patient_eligibility":    ["nihss", "time_from_lkw_hours", "vessel_occlusion"],
    "treatment_protocol":     ["nihss", "time_from_lkw_hours", "vessel_occlusion"],
    "treatment_recommendation": ["nihss", "time_from_lkw_hours", "vessel_occlusion"],
    "safety":                 ["age"],
    "contraindication_check": ["age"],
}

_SLOT_LABELS: Dict[str, str] = {
    "nihss":              "NIHSS",
    "age":                "age",
    "time_from_lkw_hours": "time from last-known-well",
    "vessel_occlusion":   "vessel occlusion site",
    "aspects":            "ASPECTS",
    "pc_aspects":         "pc-ASPECTS",
    "core_volume_ml":     "core volume (mL)",
    "mismatch_ratio":     "mismatch ratio",
    "premorbid_mrs":      "pre-morbid mRS",
    "sbp":                "SBP",
    "dbp":                "DBP",
    "inr":                "INR",
    "platelets":          "platelet count",
    "glucose":            "glucose",
}


def clarify_missing_slots(
    intent: str,
    provided_slots: Dict[str, Any],
    *,
    required_override: Optional[List[str]] = None,
) -> Optional[str]:
    """Trigger 3: the parser picked a patient-specific intent but did
    not extract the slots that intent needs.

    Args:
        intent: parser-classified intent string
        provided_slots: dict of slot_name → value (may contain Nones)
        required_override: optional list of required slot names to
            replace the default for this intent. Useful when the caller
            wants a custom requirement set for one question.

    Returns:
        Clarification text naming the missing slots, or None when
        nothing is missing OR the intent is not patient-specific.
    """
    if not intent:
        return None

    intent_key = intent.lower().strip()
    if intent_key not in _PATIENT_SPECIFIC_INTENTS:
        return None

    required = required_override or _REQUIRED_SLOTS_BY_INTENT.get(intent_key, [])
    if not required:
        return None

    missing = [
        slot for slot in required
        if provided_slots.get(slot) in (None, "", 0)
    ]
    if not missing:
        return None

    # Build a natural-language list of labels.
    labels = [_SLOT_LABELS.get(s, s) for s in missing]
    if len(labels) == 1:
        need_phrase = labels[0]
    elif len(labels) == 2:
        need_phrase = f"{labels[0]} and {labels[1]}"
    else:
        need_phrase = ", ".join(labels[:-1]) + f", and {labels[-1]}"

    msg = (
        f"To answer a {intent_key.replace('_', ' ')} question safely, I need "
        f"a few clinical details: {need_phrase}. Could you add those?"
    )
    logger.info(
        "clarify_missing_slots: intent=%s missing=%s", intent, missing
    )
    return msg


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover
    fails: List[str] = []

    # Empty survival
    msg = clarify_empty_survival(["DWI-FLAIR mismatch", "TNK"], "4.6.3", "Extended Window IVT")
    if not msg or "DWI-FLAIR" not in msg or "4.6.3" not in msg:
        fails.append(f"empty_survival with anchors: unexpected {msg!r}")

    msg = clarify_empty_survival([], "4.6.3")
    if msg is not None:
        fails.append(f"empty_survival zero anchors must be None, got {msg!r}")

    # Multi-section tie — exact tie
    topic_map = {
        "topics": [
            {"topic": "IVT", "section": "4.6",
             "subtopics": [
                 {"qualifier": "choice of agent (alteplase vs tenecteplase)", "section": "4.6.2"},
                 {"qualifier": "extended time window", "section": "4.6.3"},
             ]},
            {"topic": "EVT", "section": "4.7",
             "subtopics": [
                 {"qualifier": "medium vessel occlusion", "section": "4.7.4"},
             ]},
        ],
    }
    msg = clarify_multi_section_tie(
        ["TNK", "M2"],
        [("4.6.2", 2), ("4.7.4", 2), ("4.6.3", 1)],
        topic_map=topic_map,
    )
    if not msg or "4.6.2" not in msg or "4.7.4" not in msg:
        fails.append(f"multi_section_tie: unexpected {msg!r}")
    if msg and "4.6.3" in msg:
        # 4.6.3 score 1 is outside tie_window=1, should NOT be listed
        fails.append(f"multi_section_tie leaked non-tied section: {msg!r}")

    # Multi-section tie — single winner
    msg = clarify_multi_section_tie(
        ["DWI-FLAIR"],
        [("4.6.3", 5), ("3.2", 1)],
        topic_map=topic_map,
    )
    if msg is not None:
        fails.append(f"multi_section_tie clear winner must be None, got {msg!r}")

    # Missing slots
    msg = clarify_missing_slots("eligibility", {"nihss": None, "time_from_lkw_hours": 2, "vessel_occlusion": None})
    if not msg or "NIHSS" not in msg or "vessel" not in msg:
        fails.append(f"missing_slots: expected NIHSS+vessel in {msg!r}")

    msg = clarify_missing_slots("eligibility", {"nihss": 18, "time_from_lkw_hours": 2, "vessel_occlusion": "M1"})
    if msg is not None:
        fails.append(f"missing_slots complete must be None, got {msg!r}")

    msg = clarify_missing_slots("threshold_target", {"nihss": None})
    if msg is not None:
        fails.append(f"missing_slots non-patient intent must be None, got {msg!r}")

    if fails:
        print("FAIL")
        for f in fails:
            print("  " + f)
        raise SystemExit(1)

    print("OK — clarification builders pass")
    print("---")
    print(clarify_multi_section_tie(
        ["TNK", "M2"],
        [("4.6.2", 2), ("4.7.4", 2)],
        topic_map=topic_map,
    ))
