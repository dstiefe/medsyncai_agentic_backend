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
    # term_id -> family root term_id (itself if it is a root).
    # A term A is a child of term B when some match string of A strictly
    # contains a match string of B as a substring with token boundaries.
    # E.g. "systolic blood pressure" contains "blood pressure" ->
    # SBP.family_root = BP. For distinct-anchor COUNTING we collapse
    # term_ids to their family roots so that a rec mentioning both
    # "SBP" and "blood pressure" scores 1, not 2. This is the rule
    # stated verbatim by the user: "SBP and Blood pressure are the
    # same if they are both matched that's not 2 they count as 1 match".
    family_root: Dict[str, str] = field(default_factory=dict)
    # For debugging / audit
    source_counts: Dict[str, int] = field(default_factory=dict)

    def canonical_term_ids(self) -> List[str]:
        return sorted(self.term_matches.keys())

    def root_of(self, term_id: str) -> str:
        return self.family_root.get(term_id, term_id)

    def extract(self, text: str) -> List[str]:
        """Return the list of distinct canonical term_ids found in text.

        Token-level case-insensitive substring containment. Each term_id
        is counted at most once regardless of how many of its match
        strings hit. NOTE: this returns raw term_ids for audit. Callers
        that need the user's "1 match" rule must collapse via
        distinct_families() to get the family-level count.

        Two-pass design:

          Pass 1: literal token-boundary containment on the lowercased
          text. This is the fast path and handles every case where the
          rec/question wording matches the synonym dictionary exactly.

          Pass 2: scispaCy lemma fallback. For term_ids that MISSED in
          Pass 1, lemmatize both sides and retry. This catches surface
          forms the dictionary does not enumerate by hand — plurals,
          verb tenses, simple morphology. Only runs when scispaCy is
          importable AND the QA_V3_SCISPACY flag is enabled. Any
          hits found this way are audited via
          ``source_counts["scispacy_lemma_hits"]``.

        When scispaCy is unavailable or the flag is off, Pass 2 is
        skipped entirely and behavior is identical to the pre-scispaCy
        version.
        """
        if not text:
            return []
        haystack = text.lower()
        hits: List[str] = []

        # Decide once per call whether to enable the lemma fallback.
        use_scispacy = False
        scispacy_nlp = None
        try:
            from app.agents.clinical.ais_clinical_engine.services import (
                qa_v3_flags,
            )
            if getattr(qa_v3_flags, "SCISPACY", True):
                from app.agents.clinical.ais_clinical_engine.services import (
                    scispacy_nlp as _snlp,
                )
                if _snlp.is_available():
                    scispacy_nlp = _snlp
                    use_scispacy = True
        except Exception:
            use_scispacy = False
            scispacy_nlp = None

        missed_term_ids: List[str] = []

        for term_id, matches in self.term_matches.items():
            matched = False
            for m in matches:
                if not m:
                    continue
                # Fast path: token-boundary containment on raw text.
                if _contains_with_boundary(haystack, m):
                    hits.append(term_id)
                    matched = True
                    break
            if not matched and use_scispacy:
                missed_term_ids.append(term_id)

        if use_scispacy and missed_term_ids:
            # Lazily compute the lemmatized haystack only when at least
            # one term_id missed the literal path.
            try:
                lemma_haystack = scispacy_nlp.lemmatize(haystack)  # type: ignore[union-attr]
            except Exception:
                lemma_haystack = haystack
            for term_id in missed_term_ids:
                for m in self.term_matches[term_id]:
                    if not m:
                        continue
                    try:
                        lemma_needle = scispacy_nlp.lemmatize(m)  # type: ignore[union-attr]
                    except Exception:
                        continue
                    if not lemma_needle:
                        continue
                    if _contains_with_boundary(lemma_haystack, lemma_needle):
                        hits.append(term_id)
                        self.source_counts["scispacy_lemma_hits"] = (
                            self.source_counts.get("scispacy_lemma_hits", 0) + 1
                        )
                        break
        return hits

    def distinct_families(self, hits: Iterable[str]) -> List[str]:
        """Collapse raw term_id hits to family roots, deduped and sorted.

        This is the scoring primitive that enforces the SBP/BP rule.
        Matching both SBP and BP in the same text returns just ["BP"]
        because SBP's family_root is BP.

        Reversibility: when ``QA_V3_FAMILY_DEDUP`` is OFF, this method
        returns the raw distinct term_ids without family collapse, so
        SBP/BP/DBP show up as 3 separate anchors. The pre-v3 baseline
        behavior is recoverable by setting that env var to "0".
        """
        try:
            from app.agents.clinical.ais_clinical_engine.services import (
                qa_v3_flags,
            )
            if not qa_v3_flags.FAMILY_DEDUP:
                return sorted({t for t in hits})
        except Exception:  # pragma: no cover — defensive
            pass
        roots = {self.root_of(t) for t in hits}
        return sorted(roots)


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
        # A concept like "imaging" or "treatment" is a valid surface
        # form the user might say. We register ONLY the concept key
        # itself as a match string for a synthetic term_id.
        #
        # IMPORTANT: we deliberately do NOT fold in `expands_to` or
        # `synonyms` values as match strings on the concept term.
        # Those lists are semantic-routing hints, not word synonyms:
        #   - "imaging".synonyms = [CT, CTA, MRI, ...] — these are
        #     modalities a user might mention; they are NOT synonyms
        #     for each other.
        #   - "treatment".expands_to = [IVT, EVT] — IVT and EVT are
        #     alternatives, not the same thing.
        # If we added them to the concept's match strings, the
        # alias-merge rule (terms sharing a match string collapse to
        # one family) would wrongly merge CT with MRI via _concept:
        # imaging, or IVT with EVT via _concept:treatment. Keeping
        # the concept match set to just the concept key itself
        # prevents those cross-term chains. Each synonym already has
        # its own canonical entry in synonym_dictionary.json.
        key_id = f"_concept:{concept}"
        if key_id in vocab.term_matches:
            continue
        matches = {concept.lower()}
        if matches:
            vocab.term_matches[key_id] = matches
            added_from_intent_map += 1

    vocab.source_counts["intent_map_concepts"] = added_from_intent_map

    # Build family_root map. For each term A, search for another term B
    # whose match string is strictly contained (token-bounded) inside
    # one of A's match strings. B becomes A's parent. We pick the
    # LONGEST contained parent match string — that is the most specific
    # parent. Then compress paths so every term resolves to a root in
    # one step.
    _build_family_roots(vocab)

    n_children = sum(1 for t, r in vocab.family_root.items() if r != t)
    logger.info(
        "AnchorVocab loaded: %d from synonym_dict + %d from intent_map = %d total, "
        "%d child terms collapse into family roots",
        vocab.source_counts.get("synonym_dictionary", 0),
        added_from_intent_map,
        len(vocab.term_matches),
        n_children,
    )
    return vocab


# Explicit family groups for clinically meaningful collapses.
# Each inner list collapses to the first element as family root.
# IMPORTANT: only add a group here when the user has explicitly said
# those terms should count as one anchor. We do NOT derive families
# automatically from substring containment — clinical abbreviations
# and trial-acronym expansions create false merges (ABCD2 contains
# "blood pressure", DESTINY contains... etc.). Families are an
# intentional, auditable list.
#
# Locked rule (2026-04-11, stated twice by user):
#   "SBP and Blood pressure are the same if they are both matched
#    that's not 2 they count as 1 match"
# Applies to BP/SBP/DBP specifically. Other clinical variables can
# be added when a user or test case justifies it.
_EXPLICIT_FAMILIES: List[List[str]] = [
    ["BP", "SBP", "DBP"],
]


def _build_family_roots(vocab: AnchorVocab) -> None:
    """Derive term_id -> family root via two safe rules.

    Rule 1 (ALIAS): two distinct term_ids that share ANY match string
    are synonyms and collapse to the same family. This is how the
    `_concept:blood pressure` intent-map key folds into the
    synonym-dictionary term `BP` (both carry "blood pressure" and
    "bp" as match strings). Canonical winner: the non-`_concept:`
    id, or failing that, the lexicographically-first id.

    Rule 2 (EXPLICIT): an explicit list of clinically-motivated
    family groups (see _EXPLICIT_FAMILIES). Every term_id in a group
    collapses to the first element of that group. This is how BP,
    SBP, and DBP end up in one family even though "systolic blood
    pressure" and "diastolic blood pressure" are semantically
    distinct measurements.

    We do NOT use substring containment to derive families. Clinical
    abbreviations, trial acronyms, and long descriptive full_terms
    create false merges (e.g., ABCD2's full_term "Age, Blood
    pressure, Clinical features, Duration, Diabetes" contains
    "blood pressure", which would wrongly put ABCD2 into the BP
    family).

    After both rules run, path-compress so family_root[t] always
    resolves in one lookup.
    """
    term_ids = list(vocab.term_matches.keys())

    # Union-find over term_ids.
    parent: Dict[str, str] = {t: t for t in term_ids}

    def _find(t: str) -> str:
        while parent[t] != t:
            parent[t] = parent[parent[t]]
            t = parent[t]
        return t

    def _alias_winner(a: str, b: str) -> str:
        a_concept = a.startswith("_concept:")
        b_concept = b.startswith("_concept:")
        if a_concept and not b_concept:
            return b
        if b_concept and not a_concept:
            return a
        return a if a < b else b

    def _union(a: str, b: str, winner: Optional[str] = None) -> None:
        ra, rb = _find(a), _find(b)
        if ra == rb:
            return
        if winner is not None:
            # Forced winner wins, regardless of alias tiebreak.
            loser = rb if winner == ra else ra
            parent[loser] = winner
            return
        chosen = _alias_winner(ra, rb)
        loser = rb if chosen == ra else ra
        parent[loser] = chosen

    # ---- Rule 1: alias union over shared match strings ----------
    by_match: Dict[str, List[str]] = {}
    for tid, matches in vocab.term_matches.items():
        for m in matches:
            if not m:
                continue
            by_match.setdefault(m, []).append(tid)
    for m, owners in by_match.items():
        if len(owners) < 2:
            continue
        root = owners[0]
        for other in owners[1:]:
            _union(root, other)

    # ---- Rule 2: explicit family groups -------------------------
    # First element of each group is the forced family root. Any
    # term_id in the group that doesn't exist in term_matches is
    # silently skipped (keeps the list forward-compatible).
    for group in _EXPLICIT_FAMILIES:
        present = [t for t in group if t in vocab.term_matches]
        if len(present) < 2:
            continue
        root = present[0]
        for other in present[1:]:
            _union(root, other, winner=_find(root))

    # Path-compress: every term_id resolves to its root in one step.
    for tid in term_ids:
        vocab.family_root[tid] = _find(tid)


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
        # Count by family root so SBP and BP dedup to one anchor.
        # Raw term_ids are still returned for audit.
        distinct_terms = sorted(set(hits))
        distinct_families = vocab.distinct_families(hits)
        if len(distinct_families) < min_anchors:
            continue
        scored.append(
            (-len(distinct_families), _cor_sort_key(_rec_cor(rec)), rec, distinct_terms)
        )

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
        distinct_terms = sorted(set(hits))
        distinct_families = vocab.distinct_families(hits)
        if len(distinct_families) < min_anchors:
            continue
        scored.append((-len(distinct_families), p, distinct_terms))

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
    # Score is the family-root count (SBP + BP = 1). Returned term
    # list keeps the raw hits so the router can log exactly what was
    # matched for audit.
    families = vocab.distinct_families(hits)
    distinct_terms = sorted(set(hits))
    return len(families), distinct_terms


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
        "DBP":              {"dbp", "diastolic blood pressure"},
        "DWI-FLAIR_mismatch": {"dwi-flair mismatch", "dwi-flair", "dwi/flair mismatch"},
        "TNK":              {"tnk", "tenecteplase"},
        "EVT":              {"evt", "endovascular thrombectomy", "thrombectomy"},
        "IVT":              {"ivt", "intravenous thrombolysis"},
        "MRI":              {"mri", "magnetic resonance imaging"},
    }
    _build_family_roots(vocab)

    # Sanity check family derivation itself.
    if vocab.root_of("SBP") != "BP":
        failures.append(f"T0a SBP family_root wrong: {vocab.root_of('SBP')}")
    if vocab.root_of("DBP") != "BP":
        failures.append(f"T0b DBP family_root wrong: {vocab.root_of('DBP')}")
    if vocab.root_of("BP") != "BP":
        failures.append(f"T0c BP should be its own root: {vocab.root_of('BP')}")
    if vocab.root_of("EVT") != "EVT":
        failures.append(f"T0d EVT should be its own root: {vocab.root_of('EVT')}")

    # Test 1: generic words never count
    hits = vocab.extract("Patient with stroke presenting in the acute phase")
    if hits:
        failures.append(f"T1 generic words matched: {hits}")

    # Test 2: SBP + blood pressure collapse to ONE family (BP).
    # This is the rule stated by the user verbatim: "SBP and Blood
    # pressure are the same if they are both matched that's not 2
    # they count as 1 match". extract() still returns both raw
    # term_ids (for audit), but distinct_families() must collapse.
    hits = vocab.extract("Target SBP below 185 and keep blood pressure stable")
    raw = sorted(set(hits))
    if raw != ["BP", "SBP"]:
        failures.append(f"T2 raw hits expected [BP,SBP], got {raw}")
    families = vocab.distinct_families(hits)
    if families != ["BP"]:
        failures.append(f"T2 family collapse expected [BP], got {families}")

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

    # Test 11: rec-level scoring uses family count, not raw term count.
    # A rec that mentions BP + SBP + DBP should count as 1 distinct
    # anchor (family BP), not 3. A rec that also mentions EVT should
    # count as 2 distinct anchors (BP family + EVT family).
    recs = [
        {"text": "Keep blood pressure low; target SBP <140 and DBP <90.", "cor": "1"},
        {"text": "Keep blood pressure low; target SBP <140 and DBP <90; consider EVT.", "cor": "2a"},
    ]
    question_anchors = ["BP", "SBP", "DBP", "EVT"]
    survivors = filter_recs_by_anchor_survival(recs, vocab, question_anchors=question_anchors)
    if len(survivors) != 2:
        failures.append(f"T11 expected 2 survivors, got {len(survivors)}")
    else:
        # Ranking: the EVT one has 2 families (BP + EVT), beats the
        # BP-only rec (1 family).
        if "EVT" not in survivors[0][0]["text"]:
            failures.append(
                f"T11 ranking wrong — expected BP+EVT rec first, got "
                f"{[s[0]['text'] for s in survivors]}"
            )

    # Test 12: section scoring also collapses to families.
    section_blob = (
        "Target SBP <185 mm Hg, maintain blood pressure, and consider EVT."
    )
    n, matched = score_section_by_anchors(
        section_blob, vocab,
        question_anchors=["BP", "SBP", "EVT"],
    )
    if n != 2:
        failures.append(
            f"T12 section family-count expected 2 (BP family + EVT), got {n} "
            f"matched={matched}"
        )

    if failures:
        print("FAIL")
        for f in failures:
            print(" -", f)
        return 1
    print("PASS — 12/12 self-tests OK")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_selftest())
