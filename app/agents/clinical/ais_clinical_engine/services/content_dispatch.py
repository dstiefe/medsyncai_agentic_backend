# ─── v3 (Q&A v3 namespace) ─────────────────────────────────────────────
# This service module is part of the Q&A v3 pipeline. It is imported
# only by code under agents/qa_v3/ and by services/qa_v3_filter.py.
# The prior agents/qa/ tree has been archived to agents/_archive_qa_v2/
# and is no longer imported anywhere in the live route.
# ───────────────────────────────────────────────────────────────────────
"""
Content-source dispatcher — maps parser question_type to the primary
guideline content source and the set of supplements.

Locks in the rule from the user's design discussion (transcript msg #89):

    "Intent also helps direct the system to either recommendations, RSS,
     KG or a combination of them."

The parser's ``question_type`` field (``recommendation`` / ``evidence`` /
``knowledge_gap``) is the single source of truth for dispatch. This
module exposes the mapping as a pure function so the orchestrator, the
focused agents, and any future caller all agree on:

1. Which source is the PRIMARY answer for this question type
2. Which sources act as SUPPLEMENTS (supporting context)
3. Which focused agents need to run (and which can be skipped)

Do NOT branch on question_type by hand in new code. Import
``primary_source``, ``supplements``, ``should_run_rec_agent``,
``should_run_rss_agent``, or ``should_run_kg_agent`` from here.

Content-source meanings:
    recs  — the recommendation statements themselves (COR/LOE rules)
    rss   — Recommendation-Specific Supportive text (the "why" / evidence)
    kg    — Knowledge Gaps (what the guideline says is still unknown)
"""

from __future__ import annotations

from typing import Dict, List, Set

# ---------------------------------------------------------------------------
# The mapping
# ---------------------------------------------------------------------------

# question_type → {"primary": <source>, "supplements": [<source>, ...]}
#
# Rules:
#  - recommendation: user wants to know what to do. Recs are primary.
#    RSS paragraphs can supplement (e.g. "the rec is based on ECASS-III").
#  - evidence:       user wants to know why / what the data are. RSS is
#    primary (it carries trial results). A top rec supplements as the
#    citation anchor so the user sees the rec the evidence supports.
#  - knowledge_gap:  user wants to know what is unknown. KG is primary.
#    No supplement — KG paragraphs are self-contained.
_DISPATCH: Dict[str, Dict[str, object]] = {
    "recommendation": {
        "primary": "recs",
        "supplements": ("rss",),
    },
    "evidence": {
        "primary": "rss",
        "supplements": ("recs",),
    },
    "knowledge_gap": {
        "primary": "kg",
        "supplements": (),
    },
}

_VALID_QUESTION_TYPES: Set[str] = set(_DISPATCH.keys())
_VALID_SOURCES: Set[str] = {"recs", "rss", "kg"}


# ---------------------------------------------------------------------------
# Pure lookups
# ---------------------------------------------------------------------------

def _normalize(question_type: str) -> str:
    """Default to 'recommendation' for unknown values so the pipeline
    degrades gracefully rather than crashing on a new question_type."""
    if not question_type:
        return "recommendation"
    qt = question_type.strip().lower()
    return qt if qt in _VALID_QUESTION_TYPES else "recommendation"


def primary_source(question_type: str) -> str:
    """Return the primary content source for a question_type.

    >>> primary_source("recommendation")
    'recs'
    >>> primary_source("evidence")
    'rss'
    >>> primary_source("knowledge_gap")
    'kg'
    """
    return str(_DISPATCH[_normalize(question_type)]["primary"])


def supplements(question_type: str) -> List[str]:
    """Return the list of supplement content sources (possibly empty).

    >>> supplements("recommendation")
    ['rss']
    >>> supplements("knowledge_gap")
    []
    """
    return list(_DISPATCH[_normalize(question_type)]["supplements"])  # type: ignore[arg-type]


def sources_needed(question_type: str) -> List[str]:
    """Return primary + supplements in a single list (primary first).

    Use this when you need to know every source that feeds the final
    answer for this question.

    >>> sources_needed("recommendation")
    ['recs', 'rss']
    >>> sources_needed("evidence")
    ['rss', 'recs']
    >>> sources_needed("knowledge_gap")
    ['kg']
    """
    return [primary_source(question_type)] + supplements(question_type)


# ---------------------------------------------------------------------------
# Focused-agent gates
# ---------------------------------------------------------------------------
# Used by the orchestrator to skip focused-agent LLM calls whose output
# would never appear in the final answer.

def should_run_rec_agent(question_type: str) -> bool:
    """True iff the rec_selection / rec_summary work contributes to the
    final answer for this question_type.

    For recommendation questions, recs ARE the answer.
    For evidence questions, we still want the top rec as a citation anchor.
    For pure knowledge_gap questions, recs add nothing.
    """
    return "recs" in sources_needed(question_type)


def should_run_rss_agent(question_type: str) -> bool:
    """True iff the rss_summary work contributes to the final answer.

    Recommendation questions get supplementary RSS context.
    Evidence questions are answered from RSS directly.
    Knowledge-gap questions do not use RSS.
    """
    return "rss" in sources_needed(question_type)


def should_run_kg_agent(question_type: str) -> bool:
    """True iff the kg_summary work contributes to the final answer.

    Only knowledge-gap questions use KG content. Recommendation and
    evidence questions never surface KG text in their final answers.
    """
    return "kg" in sources_needed(question_type)


# ---------------------------------------------------------------------------
# Debug / audit helpers
# ---------------------------------------------------------------------------

def describe(question_type: str) -> Dict[str, object]:
    """Return a small dict suitable for logging or audit trail entries.

    Example:
        describe("evidence") ->
            {"question_type": "evidence",
             "primary": "rss",
             "supplements": ["recs"],
             "run_rec_agent": True,
             "run_rss_agent": True,
             "run_kg_agent": False}
    """
    qt = _normalize(question_type)
    return {
        "question_type": qt,
        "primary": primary_source(qt),
        "supplements": supplements(qt),
        "run_rec_agent": should_run_rec_agent(qt),
        "run_rss_agent": should_run_rss_agent(qt),
        "run_kg_agent": should_run_kg_agent(qt),
    }


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover
    import json

    tests = [
        ("recommendation", "recs", ["rss"], True, True, False),
        ("evidence",       "rss",  ["recs"], True, True, False),
        ("knowledge_gap",  "kg",   [],       False, False, True),
        # unknown values default to recommendation
        ("",               "recs", ["rss"], True, True, False),
        ("garbage",        "recs", ["rss"], True, True, False),
        ("RECOMMENDATION", "recs", ["rss"], True, True, False),
    ]

    fails = []
    for qt, exp_primary, exp_supp, exp_rec, exp_rss, exp_kg in tests:
        got_primary = primary_source(qt)
        got_supp = supplements(qt)
        got_rec = should_run_rec_agent(qt)
        got_rss = should_run_rss_agent(qt)
        got_kg = should_run_kg_agent(qt)
        if got_primary != exp_primary:
            fails.append(f"{qt!r}: primary {got_primary!r} != {exp_primary!r}")
        if got_supp != exp_supp:
            fails.append(f"{qt!r}: supplements {got_supp!r} != {exp_supp!r}")
        if got_rec != exp_rec:
            fails.append(f"{qt!r}: run_rec {got_rec} != {exp_rec}")
        if got_rss != exp_rss:
            fails.append(f"{qt!r}: run_rss {got_rss} != {exp_rss}")
        if got_kg != exp_kg:
            fails.append(f"{qt!r}: run_kg {got_kg} != {exp_kg}")

    if fails:
        print("FAIL")
        for f in fails:
            print("  " + f)
        raise SystemExit(1)

    print("OK — all dispatch tests pass")
    print(json.dumps(describe("evidence"), indent=2))
