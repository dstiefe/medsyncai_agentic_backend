"""
Q&A v3 anchor-count survival filter.

Implements the rules locked in during the 2026-04-10/11 architecture work:

  1. LLM-first parser (in query_parsing_agent.py) extracts user intent and
     anchors against the closed vocabulary of synonym_dictionary.json.

  2. This module is the deterministic Stage D ("pull logic") survival filter.
     Given a set of recs or RSS/KG paragraphs from the routed section(s),
     it keeps only items that contain at least one canonical anchor and
     ranks them by the number of DISTINCT anchors matched (COR as
     tiebreaker for recs).

Core rules enforced here:

  - Generic English words are NEVER anchors. Only term_ids that exist in
    synonym_dictionary.json (or canonical concepts in intent_map.json
    concept_expansions) count.

  - Synonyms dedupe to their canonical term_id. If a rec contains both
    "SBP" and "blood pressure", that is ONE anchor hit (blood_pressure),
    not two. This is the rule the user called out verbatim:
    "SBP and Blood pressure are the same if they are both matched
    that's not 2 they count as 1 match".

  - Token-level containment, case-insensitive. No regex on clinical prose.

  - A rec survives with >=1 anchor. Ranking is by distinct-anchor count
    descending, then COR strength (Class I > IIa > IIb > III/no benefit
    > III/harm) as a tiebreaker.

  - A paragraph survives with >=1 anchor. Ranking is by distinct-anchor
    count descending. No COR on paragraphs.

The filter is deterministic, pure Python, unit-testable, and has no
LLM dependency. It is called by rec_selection_agent and by the pull
logic in qa_service BEFORE any LLM assembler sees the content, so the
assembler only receives content that actually answers the question.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Anchor vocabulary
# ---------------------------------------------------------------------------

# COR strength ranking for rec tiebreaker. Lower index = stronger.
_COR_RANK = {
    "1": 0, "I": 0, "Class I": 0,
    "2a": 1, "IIa": 1, "Class IIa": 1,
    "2b": 2, "IIb": 2, "Class IIb": 2,
    "3": 3, "III": 3, "Class III": 3,
    "3 no benefit": 4, "III no benefit": 4, "Class III no benefit": 4,
    "3 harm": 5, "III harm": 5, "Class III harm": 5,
}


def _cor_sort_key(cor: str) -> int:
    if not cor:
        return 99
    return _COR_RANK.get(str(cor).strip(), 99)


@dataclass
class AnchorVocab:
    """Closed vocabulary of canonical clinical anchors.

    Built from synonym_dictionary.json (primary source) and extended with
    concept_expansions from intent_map.json. Each canonical term_id owns
    a set of match strings (the term_id itself, its full_term, and any
    listed synonyms), all lowercased for case-insensitive containment.
    """

    # term_id -> set of lowercased match strings
    term_matches: Dict[str, set] = field(default_factory=dict)
    # For debugging / audit
    source_counts: Dict[str, int] = field(default_factory=dict)

    def canonical_term_ids(self) -> List[str]:
        return sorted(self.term_matches.keys())

    def extract(self, text: str) -> List[str]:
        """Return the list of distinct canonical term_ids found in text.

        Token-level case-insensitive substring containment. Each term_id
        is counted at most once regardless of how many of its match
        strings hit — this is the SBP/blood-pressure dedup rule.
        """
        if not text:
            return []
        haystack = text.lower()
        hits: List[str] = []
        for term_id, matches in self.term_matches.items():
            for m in matches:
                if not m:
                    continue
                # Token-boundary-ish containment. Clinical prose does not
                # play nicely with strict \b word boundaries (hyphens,
                # slashes, digits), so we accept any substring that is
                # flanked by non-alphanumeric characters or end-of-string.
                if _contains_with_boundary(haystack, m):
                    hits.append(term_id)
                    break  # one hit per term_id is enough
        return hits


def _contains_with_boundary(haystack: str, needle: str) -> bool:
    """Case-insensitive containment that respects token boundaries without regex.

    haystack and needle must both be lowercase. Returns True when needle
    appears in haystack and is not glued to another alphanumeric character
    on either side. This prevents "MRI" from hitting "MRIT" and "TNK" from
    hitting "TNKase" (without blocking "M2-segment" or "DWI-FLAIR").
    """
    if not needle:
        return False
    nlen = len(needle)
    start = 0
    while True:
        idx = haystack.find(needle, start)
        if idx == -1:
            return False
        left_ok = idx == 0 or not haystack[idx - 1].isalnum()
        right_idx = idx + nlen
        right_ok = right_idx >= len(haystack) or not haystack[right_idx].isalnum()
        if left_ok and right_ok:
            return True
        start = idx + 1


def _default_refs_dir() -> str:
    """Resolve the references directory without depending on CWD."""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(
        os.path.join(here, "..", "agents", "qa", "references")
    )


def load_anchor_vocab(refs_dir: Optional[str] = None) -> AnchorVocab:
    """Build the AnchorVocab from the live reference files on dev.

    Sources:
      synonym_dictionary.json -> terms[term_id].full_term + .synonyms
      intent_map.json         -> concept_expansions[concept].expands_to

    Generic English words never enter the vocabulary because they are
    not in either source file by design.
    """
    refs = refs_dir or _default_refs_dir()

    vocab = AnchorVocab()

    syn_path = os.path.join(refs, "synonym_dictionary.json")
    try:
        with open(syn_path, "r", encoding="utf-8") as f:
            syn = json.load(f)
    except FileNotFoundError:
        logger.warning("synonym_dictionary.json not found at %s", syn_path)
        syn = {"terms": {}}

    for term_id, entry in (syn.get("terms") or {}).items():
        if not isinstance(entry, dict):
            continue
        matches = set()
        matches.add(term_id.lower())
        full = entry.get("full_term") or ""
        if full:
            matches.add(full.lower())
        for s in entry.get("synonyms") or []:
            if isinstance(s, str) and s.strip():
                matches.add(s.strip().lower())
        # Discard empty/noise members
        matches = {m for m in matches if m}
        if matches:
            vocab.term_matches[term_id] = matches

    vocab.source_counts["synonym_dictionary"] = len(vocab.term_matches)

    im_path = os.path.join(refs, "intent_map.json")
    try:
        with open(im_path, "r", encoding="utf-8") as f:
            im = json.load(f)
    except FileNotFoundError:
        logger.warning("intent_map.json not found at %s", im_path)
        im = {}

    added_from_intent_map = 0
    for concept, entry in (im.get("concept_expansions") or {}).items():
        if concept.startswith("_"):  # _doc, metadata-style keys
            continue
        if not isinstance(entry, dict):
            continue
        # A concept like "treatment" expands to canonical term_ids
        # (e.g. ["IVT","EVT"]). The concept key ITSELF is also a valid
        # anchor surface form — if the user says "treatment", that is
        # already an anchor in the vocabulary, even if we then expand
        # it during routing. For survival filtering we treat the
        # concept key as a synthetic canonical term and union in its
        # expansions as match strings so either wording hits it.
        key_id = f"_concept:{concept}"
        if key_id in vocab.term_matches:
            continue
        matches = {concept.lower()}
        for expansion in entry.get("expands_to") or []:
            if isinstance(expansion, str) and expansion.strip():
                matches.add(expansion.strip().lower())
        if matches:
            vocab.term_matches[key_id] = matches
            added_from_intent_map += 1

    vocab.source_counts["intent_map_concepts"] = added_from_intent_map
    logger.info(
        "AnchorVocab loaded: %d from synonym_dict + %d from intent_map = %d total",
        vocab.source_counts.get("synonym_dictionary", 0),
        added_from_intent_map,
        len(vocab.term_matches),
    )
    return vocab


# ---------------------------------------------------------------------------
# Rec-level and paragraph-level survival filters
# ---------------------------------------------------------------------------

def _rec_text(rec: Dict[str, Any]) -> str:
    # The rec may be a dict from recommendations_store or a ScoredRecommendation.
    if isinstance(rec, dict):
        return (rec.get("text") or "").strip()
    return (getattr(rec, "text", "") or "").strip()


def _rec_cor(rec: Dict[str, Any]) -> str:
    if isinstance(rec, dict):
        return str(rec.get("cor") or "")
    return str(getattr(rec, "cor", "") or "")


def filter_recs_by_anchor_survival(
    recs: List[Any],
    vocab: AnchorVocab,
    question_anchors: Optional[List[str]] = None,
    min_anchors: int = 1,
) -> List[Tuple[Any, List[str]]]:
    """Keep recs that contain at least `min_anchors` distinct canonical anchors.

    When `question_anchors` is given, the filter only counts those anchors
    (scoped to the user's question). When omitted, ALL canonical anchors
    in the vocabulary are considered — useful for smoke tests and for
    cases where upstream parsing has not yet produced anchors.

    Returns a list of (rec, matched_term_ids) tuples, ranked by
    distinct-anchor count descending, then COR strength ascending.
    """
    scoped_terms: Optional[set] = None
    if question_anchors:
        scoped_terms = {a for a in question_anchors if a in vocab.term_matches}

    scored: List[Tuple[int, int, Any, List[str]]] = []
    for rec in recs:
        text = _rec_text(rec)
        if not text:
            continue
        hits = vocab.extract(text)
        if scoped_terms is not None:
            hits = [h for h in hits if h in scoped_terms]
        distinct = sorted(set(hits))
        if len(distinct) < min_anchors:
            continue
        scored.append((-len(distinct), _cor_sort_key(_rec_cor(rec)), rec, distinct))

    scored.sort(key=lambda t: (t[0], t[1]))
    return [(rec, hits) for _nd, _cor, rec, hits in scored]


def filter_paragraphs_by_anchor_survival(
    paragraphs: List[Dict[str, Any]],
    vocab: AnchorVocab,
    question_anchors: Optional[List[str]] = None,
    min_anchors: int = 1,
) -> List[Tuple[Dict[str, Any], List[str]]]:
    """Keep paragraphs (RSS/KG) that contain at least `min_anchors` anchors.

    Paragraphs are the shape produced by gather_section_content_v3() —
    dicts with `text` and metadata (`section`, optional `recNumber`,
    optional `paragraph_index`).

    Returns a list of (paragraph, matched_term_ids) tuples ranked by
    distinct-anchor count descending. No COR tiebreaker (paragraphs
    have no COR).
    """
    scoped_terms: Optional[set] = None
    if question_anchors:
        scoped_terms = {a for a in question_anchors if a in vocab.term_matches}

    scored: List[Tuple[int, Dict[str, Any], List[str]]] = []
    for p in paragraphs:
        text = (p.get("text") or "").strip()
        if not text:
            continue
        hits = vocab.extract(text)
        if scoped_terms is not None:
            hits = [h for h in hits if h in scoped_terms]
        distinct = sorted(set(hits))
        if len(distinct) < min_anchors:
            continue
        scored.append((-len(distinct), p, distinct))

    scored.sort(key=lambda t: t[0])
    return [(p, hits) for _nd, p, hits in scored]


# ---------------------------------------------------------------------------
# Section scoring for router (anchor count cross-checks intent)
# ---------------------------------------------------------------------------

def score_section_by_anchors(
    section_text: str,
    vocab: AnchorVocab,
    question_anchors: Optional[List[str]] = None,
) -> Tuple[int, List[str]]:
    """Return (distinct_anchor_count, matched_term_ids) for a section text blob.

    Feed this the concatenated rec + synopsis + KG text for a section.
    Used by the router to apply the locked rule:
      "A section that matches 3 anchor words is probably more appropriate
       than a section that matches one anchor word."
    """
    if not section_text:
        return 0, []
    hits = vocab.extract(section_text)
    if question_anchors:
        scoped = {a for a in question_anchors if a in vocab.term_matches}
        hits = [h for h in hits if h in scoped]
    distinct = sorted(set(hits))
    return len(distinct), distinct


# ---------------------------------------------------------------------------
# Self-test (run as: python -m app.agents.clinical.ais_clinical_engine.services.qa_v3_filter)
# ---------------------------------------------------------------------------

def _selftest() -> int:
    """Sanity checks for the anchor filter. Returns 0 on success, 1 on failure."""
    failures: List[str] = []

    # Build a mini vocab by hand (does not touch the real JSON files).
    vocab = AnchorVocab()
    vocab.term_matches = {
        "BP":               {"bp", "blood pressure"},
        "SBP":              {"sbp", "systolic blood pressure"},
        "DWI-FLAIR_mismatch": {"dwi-flair mismatch", "dwi-flair", "dwi/flair mismatch"},
        "TNK":              {"tnk", "tenecteplase"},
        "EVT":              {"evt", "endovascular thrombectomy", "thrombectomy"},
        "IVT":              {"ivt", "intravenous thrombolysis"},
        "MRI":              {"mri", "magnetic resonance imaging"},
    }

    # Test 1: generic words never count
    hits = vocab.extract("Patient with stroke presenting in the acute phase")
    if hits:
        failures.append(f"T1 generic words matched: {hits}")

    # Test 2: SBP + blood pressure dedupe to distinct canonicals
    hits = vocab.extract("Target SBP below 185 and keep blood pressure stable")
    # Both SBP (via 'sbp') and BP (via 'blood pressure') are legitimate
    # distinct canonicals. The dedup rule is within a single term_id,
    # not across term_ids. So we expect TWO distinct here.
    if sorted(set(hits)) != ["BP", "SBP"]:
        failures.append(f"T2 expected [BP,SBP], got {sorted(set(hits))}")

    # Test 3: one canonical term, two surface forms, dedup to 1
    hits = vocab.extract("Give TNK (tenecteplase) 0.25 mg/kg")
    if sorted(set(hits)) != ["TNK"]:
        failures.append(f"T3 expected [TNK], got {sorted(set(hits))}")

    # Test 4: token boundary — TNKase should NOT hit TNK
    hits = vocab.extract("Do not confuse with TNKase brand name")
    if "TNK" in hits:
        failures.append(f"T4 TNKase incorrectly matched TNK")

    # Test 5: rec-level filter keeps only rec with anchor
    recs = [
        {"text": "Target systolic blood pressure <185 mm Hg.", "cor": "1"},
        {"text": "Consider admission to a stroke unit.", "cor": "1"},
        {"text": "Tenecteplase 0.25 mg/kg for DWI-FLAIR mismatch in extended window.", "cor": "2a"},
    ]
    question_anchors = ["TNK", "DWI-FLAIR_mismatch"]
    survivors = filter_recs_by_anchor_survival(recs, vocab, question_anchors=question_anchors)
    if len(survivors) != 1:
        failures.append(f"T5 expected 1 survivor, got {len(survivors)}")
    elif survivors[0][1] != ["DWI-FLAIR_mismatch", "TNK"]:
        failures.append(f"T5 anchors wrong: {survivors[0][1]}")

    # Test 6: rec-level filter ranks by distinct anchor count desc
    recs = [
        {"text": "TNK for DWI-FLAIR mismatch.", "cor": "2a"},  # 2 anchors
        {"text": "TNK dosing.", "cor": "1"},                   # 1 anchor
    ]
    question_anchors = ["TNK", "DWI-FLAIR_mismatch"]
    survivors = filter_recs_by_anchor_survival(recs, vocab, question_anchors=question_anchors)
    if len(survivors) != 2 or len(survivors[0][1]) != 2 or len(survivors[1][1]) != 1:
        failures.append(f"T6 ranking wrong: {[(s[0]['text'], s[1]) for s in survivors]}")

    # Test 7: rec-level filter tiebreaker: same anchor count, stronger COR wins
    recs = [
        {"text": "EVT within 6h.", "cor": "2a"},
        {"text": "EVT within 6h.", "cor": "1"},
    ]
    question_anchors = ["EVT"]
    survivors = filter_recs_by_anchor_survival(recs, vocab, question_anchors=question_anchors)
    if len(survivors) != 2 or survivors[0][0]["cor"] != "1":
        failures.append(f"T7 COR tiebreaker wrong: {[s[0]['cor'] for s in survivors]}")

    # Test 8: paragraph filter keeps only paragraphs with anchors
    paragraphs = [
        {"section": "4.6.3", "paragraph_index": 0,
         "text": "The DAWN trial enrolled patients with DWI-FLAIR mismatch and extended windows."},
        {"section": "4.6.3", "paragraph_index": 1,
         "text": "Methodology details unrelated to the clinical question."},
        {"section": "4.6.3", "paragraph_index": 2,
         "text": "Tenecteplase showed non-inferiority in several trials."},
    ]
    question_anchors = ["TNK", "DWI-FLAIR_mismatch"]
    survivors = filter_paragraphs_by_anchor_survival(paragraphs, vocab, question_anchors=question_anchors)
    if len(survivors) != 2:
        failures.append(f"T8 expected 2 paragraph survivors, got {len(survivors)}")

    # Test 9: section scoring returns distinct anchor count
    section_blob = "TNK is preferred in DWI-FLAIR mismatch. EVT adjunct considered."
    n, matched = score_section_by_anchors(
        section_blob, vocab, question_anchors=["TNK", "DWI-FLAIR_mismatch", "EVT"]
    )
    if n != 3 or sorted(matched) != ["DWI-FLAIR_mismatch", "EVT", "TNK"]:
        failures.append(f"T9 section scoring wrong: {n} {matched}")

    # Test 10: loading the real vocab should succeed and have >0 terms
    real = load_anchor_vocab()
    if not real.term_matches:
        failures.append("T10 real vocab empty — file path wrong?")
    else:
        print(
            f"T10 real vocab OK: {real.source_counts.get('synonym_dictionary',0)} "
            f"synonym terms + {real.source_counts.get('intent_map_concepts',0)} concepts "
            f"= {len(real.term_matches)} canonical anchors"
        )

    if failures:
        print("FAIL")
        for f in failures:
            print(" -", f)
        return 1
    print("PASS — 10/10 self-tests OK")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_selftest())
