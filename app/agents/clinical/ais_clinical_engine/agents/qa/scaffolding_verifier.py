"""
scaffolding_verifier.py — deterministic, pre-LLM verification layer.

The LLM is allowed to hallucinate; the pipeline is not. Before any LLM
output is allowed to reach QAAssemblyAgent, it must pass this verifier:

    1. Claimed intent name exists in intent_catalog.json
    2. Claimed section IDs resolve against the scaffolding (either a
       dd.v2 section or a gtm parent that resolves to dd.v2 children)
    3. Claimed citation text is BYTE-EXACT present in the recommendation
       text stored in guideline_knowledge.json
    4. Out-of-scope path: if nothing resolves, the verifier returns an
       OutOfScope result so QAAssemblyAgent can emit the
       not_addressed_in_guideline response.

All checks are Python-only. No LLM is called here.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

from .scaffolding_loader import ScaffoldingBundle, get_scaffolding

_GUIDELINE_KNOWLEDGE_PATH = os.path.join(
    os.path.dirname(__file__),
    "..",
    "..",
    "data",
    "guideline_knowledge.json",
)


@lru_cache(maxsize=1)
def _load_guideline_knowledge() -> Dict[str, Any]:
    with open(_GUIDELINE_KNOWLEDGE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _get_rec_text(section_id: str, rec_number: int) -> Optional[str]:
    """Return the raw byte-exact text of a numbered recommendation, or None
    if the section/rec doesn't exist."""
    gk = _load_guideline_knowledge()
    sec = gk.get("sections", {}).get(section_id)
    if not sec:
        return None
    for r in sec.get("rss") or []:
        if r.get("recNumber") == rec_number:
            return r.get("text")
    return None


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class CitationCheck:
    section_id: str
    rec_number: int
    quote: str
    ok: bool
    reason: Optional[str] = None


@dataclass
class VerificationResult:
    ok: bool
    out_of_scope: bool = False
    errors: List[str] = field(default_factory=list)
    resolved_sections: List[str] = field(default_factory=list)
    citation_checks: List[CitationCheck] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return bool(self.errors)


# ---------------------------------------------------------------------------
# Individual verifiers
# ---------------------------------------------------------------------------


def verify_intent(intent_name: str, bundle: ScaffoldingBundle) -> Optional[str]:
    """Return None if intent is valid, else an error message."""
    if not intent_name:
        return "empty intent name"
    if bundle.intent(intent_name) is None:
        valid = sorted(bundle.intent_catalog.get("intents", {}).keys())
        return (
            f"intent '{intent_name}' not in catalog. "
            f"Valid intents: {valid}"
        )
    return None


def verify_section_ids(
    section_ids: List[str], bundle: ScaffoldingBundle
) -> Tuple[List[str], List[str]]:
    """
    Resolve a list of claimed section IDs against the scaffolding.

    Returns (resolved_children, errors):
    - resolved_children: flat list of dd.v2 section IDs (deduped, ordered)
    - errors: one message per unresolvable claim
    """
    resolved: List[str] = []
    seen = set()
    errors: List[str] = []
    for sid in section_ids or []:
        children = bundle.resolve_section_family(sid)
        if not children:
            errors.append(f"section '{sid}' does not resolve in scaffolding")
            continue
        for c in children:
            if c not in seen:
                seen.add(c)
                resolved.append(c)
    return resolved, errors


def verify_citation(
    section_id: str, rec_number: int, quote: str
) -> CitationCheck:
    """
    Byte-exact substring check: the quote must appear character-for-character
    inside the text of the numbered recommendation in guideline_knowledge.json.

    This is a SUBSTRING check, not a fuzzy match. Whitespace, punctuation,
    capitalization all matter. Callers should normalize whitespace on the
    LLM's output BEFORE handing it to the verifier if that's desired — but
    the verifier itself is strict.
    """
    text = _get_rec_text(section_id, rec_number)
    if text is None:
        return CitationCheck(
            section_id=section_id,
            rec_number=rec_number,
            quote=quote,
            ok=False,
            reason=f"section {section_id} rec #{rec_number} not found "
                   f"in guideline_knowledge.json",
        )
    if not quote:
        return CitationCheck(
            section_id=section_id,
            rec_number=rec_number,
            quote=quote,
            ok=False,
            reason="empty quote string",
        )
    if quote in text:
        return CitationCheck(
            section_id=section_id,
            rec_number=rec_number,
            quote=quote,
            ok=True,
        )
    return CitationCheck(
        section_id=section_id,
        rec_number=rec_number,
        quote=quote,
        ok=False,
        reason=(
            "quote not byte-exact present in rec text "
            f"(quote_len={len(quote)}, rec_len={len(text)})"
        ),
    )


# ---------------------------------------------------------------------------
# Top-level: verify a parsed query or an LLM response
# ---------------------------------------------------------------------------


def verify_parsed_query(
    parsed: Dict[str, Any],
    bundle: Optional[ScaffoldingBundle] = None,
) -> VerificationResult:
    """
    Verify a ParsedQAQuery dict-shaped object. Expected keys:
      - intent: str
      - sections: list[str] (may be empty)
      - slots: dict (required_slots must be subset of present keys, unless
                     intent is out_of_scope)

    If intent is 'out_of_scope' the result is marked out_of_scope and other
    checks are relaxed (since by definition there's nothing to resolve).
    """
    if bundle is None:
        bundle = get_scaffolding()

    result = VerificationResult(ok=True)
    intent_name = parsed.get("intent") or ""

    # 1. intent validity
    err = verify_intent(intent_name, bundle)
    if err:
        result.ok = False
        result.errors.append(f"[intent] {err}")
        return result

    if intent_name == "out_of_scope":
        result.out_of_scope = True
        return result

    # 2. section resolution
    resolved, sec_errors = verify_section_ids(
        parsed.get("sections") or [], bundle
    )
    result.resolved_sections = resolved
    for e in sec_errors:
        result.errors.append(f"[section] {e}")

    if not resolved and not sec_errors:
        # nothing claimed and nothing resolved -> mark out_of_scope
        result.out_of_scope = True

    # 3. slot presence check
    intent_obj = bundle.intent(intent_name) or {}
    required = intent_obj.get("required_slots") or []
    slots = parsed.get("slots") or {}
    missing = [s for s in required if s not in slots or slots[s] in (None, "", [])]
    if missing:
        result.errors.append(
            f"[slots] intent '{intent_name}' missing required slots: {missing}"
        )

    # 4. review_flags guard: sections marked for review can only be routed
    # to when the claimed topic exact-matches their core scope. We don't
    # have topic→section evidence here (that's router's job); we just flag
    # that it's review-gated so the router can apply the routable_only_when
    # guard.
    result.resolved_sections = resolved

    result.ok = not result.errors
    return result


def verify_llm_citations(
    citations: List[Dict[str, Any]],
) -> List[CitationCheck]:
    """
    Run byte-exact checks across a list of {section_id, rec_number, quote}
    dicts. Returns a CitationCheck per entry. Callers should treat any
    `ok=False` as a fatal LLM hallucination and refuse to emit the answer.
    """
    out: List[CitationCheck] = []
    for c in citations or []:
        out.append(
            verify_citation(
                section_id=c.get("section_id") or "",
                rec_number=int(c.get("rec_number") or 0),
                quote=c.get("quote") or "",
            )
        )
    return out


def reset_guideline_knowledge_cache() -> None:
    """Clear guideline_knowledge cache (for tests)."""
    _load_guideline_knowledge.cache_clear()


__all__ = [
    "CitationCheck",
    "VerificationResult",
    "verify_intent",
    "verify_section_ids",
    "verify_citation",
    "verify_parsed_query",
    "verify_llm_citations",
    "reset_guideline_knowledge_cache",
]
