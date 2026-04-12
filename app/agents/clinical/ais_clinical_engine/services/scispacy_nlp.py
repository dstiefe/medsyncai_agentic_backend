# ─── v3 (Q&A v3 namespace) ─────────────────────────────────────────────
# This service module is part of the Q&A v3 pipeline. It is imported
# only by code under agents/qa_v3/ and by services/qa_v3_filter.py.
# The prior agents/qa/ tree has been archived to agents/_archive_qa_v2/
# and is no longer imported anywhere in the live route.
# ───────────────────────────────────────────────────────────────────────
"""
scispaCy / spaCy biomedical NLP wrapper for the Q&A v3 anchor layer.

Two jobs, both complementary to the existing synonym_dictionary.json:

1. Lemmatization bridge
   Collapses surface-form plurals, verb tenses, and simple morphology
   so that a rec saying "stent retrievers are preferred" matches a
   question asking about "stent retriever" without forcing us to
   enumerate every plural by hand in the synonym dictionary.

2. Clinical entity gate
   When the user's question contains a term the parser COULD treat
   as an anchor (e.g. "oxygen"), scispaCy's biomedical NER tells us
   whether the term is clinically load-bearing in this specific
   sentence. "Oxygen" in "should I give supplemental oxygen to a
   hypoxic AIS patient" is an ENTITY. "Oxygen" in "the patient had a
   wake-up stroke" is not even present. This turns the user's rule —
   "oxygen may be an anchor depending on context" (transcript msg
   #78) — into a deterministic check.

This module does NOT replace the canonical anchor vocabulary from
synonym_dictionary.json + intent_map.json. It LAYERS on top:

    Layer 1: the synonym_dictionary (hand-curated, clinical truth)
    Layer 2: intent_map concept_expansions (compound concept groups)
    Layer 3: scispaCy lemmatization (plural/tense collapse)
    Layer 4: scispaCy NER (context gate for generic-looking terms)

When scispaCy is unavailable or QA_V3_SCISPACY is off, all four
layers gracefully degrade to layers 1 and 2 — the pre-scispaCy
behaviour. That way the dev server keeps working in environments
where the model wheel was not installed.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Dict, Iterable, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lazy single-load of the scispaCy pipeline
# ---------------------------------------------------------------------------

_MODEL_NAME = os.environ.get("QA_V3_SCISPACY_MODEL", "en_core_sci_sm")

_nlp = None
_load_lock = threading.Lock()
_load_failed = False

# Separate lazy pipeline with the UMLS EntityLinker attached. Kept
# distinct from the base _nlp so the lemmatization / NER fast path
# does not pay the 2-5 second linker-load cost unless UMLS is enabled.
# Access via ``_try_load_umls()`` only.
_umls_nlp = None
_umls_load_lock = threading.Lock()
_umls_load_failed = False


def _try_load() -> Optional[object]:
    """Lazy-load the scispaCy pipeline once per process.

    Returns the spacy Language object on success. Returns None and
    sets ``_load_failed`` when scispaCy or the model is not available
    so we do not retry on every call.
    """
    global _nlp, _load_failed
    if _nlp is not None:
        return _nlp
    if _load_failed:
        return None
    with _load_lock:
        if _nlp is not None:
            return _nlp
        if _load_failed:
            return None
        try:
            import spacy  # type: ignore
            import scispacy  # noqa: F401  (triggers scispacy registration)
        except ImportError as e:
            logger.warning(
                "scispaCy not importable (%s) — anchor layer will run "
                "without lemmatization / NER",
                e,
            )
            _load_failed = True
            return None
        try:
            _nlp = spacy.load(_MODEL_NAME)
        except Exception as e:
            logger.warning(
                "scispaCy model %s failed to load (%s) — anchor layer "
                "will run without lemmatization / NER",
                _MODEL_NAME, e,
            )
            _load_failed = True
            return None
        logger.info("scispaCy model %s loaded for anchor layer", _MODEL_NAME)
        return _nlp


def is_available() -> bool:
    """True iff the scispaCy pipeline can be loaded in this process."""
    return _try_load() is not None


# ---------------------------------------------------------------------------
# UMLS EntityLinker — separate lazy pipeline
# ---------------------------------------------------------------------------

def _try_load_umls() -> Optional[object]:
    """Lazy-load a separate scispaCy pipeline with the UMLS EntityLinker.

    Kept distinct from ``_try_load()`` because attaching the linker
    triggers a ~1 GB KB / nmslib index load that takes 2-5 seconds on
    first call. Callers that only need lemmatization or NER must not
    pay that cost.

    Returns the spacy Language object (with linker attached) on
    success. Returns None and sets ``_umls_load_failed`` when UMLS is
    unavailable so we do not retry on every call. Graceful degradation:
    downstream callers treat None as "UMLS not available" and fall
    back to the non-UMLS path.
    """
    global _umls_nlp, _umls_load_failed
    if _umls_nlp is not None:
        return _umls_nlp
    if _umls_load_failed:
        return None
    with _umls_load_lock:
        if _umls_nlp is not None:
            return _umls_nlp
        if _umls_load_failed:
            return None
        try:
            import spacy  # type: ignore
            import scispacy  # noqa: F401
            from scispacy.linking import EntityLinker  # noqa: F401
        except ImportError as e:
            logger.warning(
                "scispaCy linker not importable (%s) — UMLS layer disabled", e
            )
            _umls_load_failed = True
            return None
        try:
            nlp = spacy.load(_MODEL_NAME)
            # Attach the linker. resolve_abbreviations expands "tPA" to
            # "tissue plasminogen activator" before KB lookup, which is
            # exactly the behaviour we want for a clinical question.
            # max_entities_per_mention=3 keeps the top-3 CUIs per span.
            nlp.add_pipe(
                "scispacy_linker",
                config={
                    "resolve_abbreviations": True,
                    "linker_name": "umls",
                    "max_entities_per_mention": 3,
                },
            )
        except Exception as e:
            logger.warning(
                "UMLS linker attach failed (%s) — UMLS layer disabled", e
            )
            _umls_load_failed = True
            return None
        _umls_nlp = nlp
        logger.info("scispaCy UMLS linker loaded for anchor layer")
        return _umls_nlp


def is_umls_available() -> bool:
    """True iff the UMLS-enabled pipeline can be loaded in this process."""
    return _try_load_umls() is not None


# ---------------------------------------------------------------------------
# UMLS filtering rules
# ---------------------------------------------------------------------------

# Clinical-domain UMLS Semantic Types (TUIs) the anchor layer accepts.
# A CUI whose `types` field is empty of these TUIs is dropped as a
# non-clinical false positive (e.g. T073 "Manufactured Object" for
# the word "window"). Derived from the UMLS Semantic Network with a
# bias toward stroke-specific clinical content.
#
# Categories:
#   Findings / pathologies:     T033 T034 T037 T046 T047 T048 T184 T190 T191
#   Procedures / activities:    T058 T059 T060 T061
#   Drugs / substances:         T103 T104 T109 T110 T114 T116 T120 T121 T122
#                               T123 T125 T126 T129 T130 T131 T195 T200
#   Anatomy:                    T017 T023 T024 T025 T029 T030
#   Devices:                    T074 T075 T203
#   Body systems:               T022
#   Diseases / disorders:       T019 T020 T045 T049 T050
#   Organisms (for pathogens):  T007
_CLINICAL_TUIS: Set[str] = {
    # Findings, pathologies, symptoms
    "T033", "T034", "T037", "T046", "T047", "T048", "T184", "T190", "T191",
    # Procedures
    "T058", "T059", "T060", "T061",
    # Drugs, substances, pharmacological agents
    "T103", "T104", "T109", "T110", "T114", "T116", "T120", "T121", "T122",
    "T123", "T125", "T126", "T129", "T130", "T131", "T195", "T200",
    # Anatomy
    "T017", "T022", "T023", "T024", "T025", "T029", "T030",
    # Devices
    "T074", "T075", "T203",
    # Diseases and disorders
    "T019", "T020", "T045", "T049", "T050",
    # Organism (pathogens, relevant for endocarditis etc.)
    "T007",
}

# Generic English words that receive UMLS CUIs but add no clinical signal.
# Expanded from the earlier version after observing "extended" and "window"
# linking as Functional Concept / Manufactured Object. These are dropped
# before TUI filtering so the cheap rejection happens first.
_UMLS_NOISE_SURFACES: Set[str] = {
    "patient", "patients", "disease", "diseases", "condition",
    "conditions", "clinical", "clinically", "symptoms", "signs",
    "history", "window", "windows", "extended", "extension",
    "old", "year", "years", "hour", "hours", "onset", "last",
    "known", "well", "give", "giving", "treatment", "therapy",
    "event", "events", "time", "acute", "chronic", "severe",
    "mild", "moderate", "recent", "current", "baseline",
    # "mismatch" on its own links to "Mismatch Probe" (genetics lab
    # reagent). The clinical sense "DWI-FLAIR mismatch" / "perfusion
    # mismatch" is handled by the synonym dictionary, not UMLS.
    "mismatch", "mismatches",
    # "management" on its own links to "Disease Management" which is
    # a care-delivery concept — too generic to help with routing.
    "management", "managing",
    # "core" alone is ambiguous; it links to non-clinical
    # "core" via compounds like "core infarct". The synonym
    # dictionary handles the clinical core-volume concept.
    "core", "cores",
    # "eligibility" links to "Eligibility Determination" which is a
    # process concept, not a stroke-specific clinical anchor.
    "eligibility", "eligible",
}


def umls_concepts(
    text: str,
    min_score: float = 0.80,
    max_per_mention: int = 1,
    clinical_tuis_only: bool = True,
) -> List[Tuple[str, str, str, float]]:
    """Return clinically filtered UMLS concept matches for ``text``.

    Each result is a tuple (surface_form, cui, canonical_name, score).
    By default returns the best clinical-TUI concept per mention with
    score >= ``min_score``.

    The filtering pipeline applied to every call:

      1. Drop mentions shorter than 3 characters.
      2. Drop surface forms in ``_UMLS_NOISE_SURFACES`` (generic English
         words that receive UMLS CUIs in everyday senses — "window"
         would otherwise link to Manufactured Object, "extended" to
         Functional Concept, etc.).
      3. For each surviving mention, iterate ALL linker candidates for
         that span (the linker produces up to 3 per mention) and pick
         the FIRST candidate whose:
           - score >= min_score, AND
           - at least one TUI is in _CLINICAL_TUIS (when
             ``clinical_tuis_only`` is True)
         This corrects the classic "M1 occlusion -> Dental Occlusion"
         failure mode: the linker actually returns three candidates for
         "occlusion" (Dental, Obstruction, Cardiovascular occlusion);
         Dental is T042 Organ or Tissue Function (not in the clinical
         allow-list), so the TUI filter picks the next candidate
         instead of the first.
      4. Up to ``max_per_mention`` concepts per mention are returned,
         in the order the linker reported them after filtering.

    When ``clinical_tuis_only`` is False, the TUI filter is disabled
    and every score-qualifying candidate is returned — use this only
    for debugging or when you want to see what the linker produced.

    Returns an empty list when UMLS is unavailable (graceful
    degradation). The caller must check ``is_umls_available()`` if it
    needs to distinguish "UMLS off" from "no concepts found".
    """
    if not text:
        return []
    nlp = _try_load_umls()
    if nlp is None:
        return []

    try:
        doc = nlp(text)
    except Exception as e:
        logger.warning("umls_concepts failed on %r: %s", text[:80], e)
        return []

    # Access the linker to resolve CUIs -> canonical names and TUIs.
    linker = None
    try:
        linker = nlp.get_pipe("scispacy_linker")
    except Exception:
        linker = None

    results: List[Tuple[str, str, str, float]] = []
    for ent in doc.ents:
        surface = ent.text.strip()
        if len(surface) < 3:
            continue
        if surface.lower() in _UMLS_NOISE_SURFACES:
            continue
        kb_ents = getattr(ent._, "kb_ents", None) or []
        if not kb_ents:
            continue

        kept = 0
        for cui, score in kb_ents:
            if score < min_score:
                continue

            canonical_name = ""
            tuis: List[str] = []
            if linker is not None:
                try:
                    ent_obj = linker.kb.cui_to_entity.get(cui)
                    if ent_obj is not None:
                        canonical_name = ent_obj.canonical_name or ""
                        tuis = list(ent_obj.types or [])
                except Exception:
                    pass

            if clinical_tuis_only and tuis:
                # Require at least one clinical TUI.
                if not any(t in _CLINICAL_TUIS for t in tuis):
                    continue

            results.append((surface, cui, canonical_name, float(score)))
            kept += 1
            if kept >= max_per_mention:
                break

    return results


def umls_concepts_compact(text: str, **kwargs) -> List[Dict[str, object]]:
    """Wrapper returning a dict-per-concept shape suitable for JSON logs
    and LLM prompt embedding.

    Each dict has keys: ``surface``, ``cui``, ``canonical``, ``score``.
    """
    return [
        {"surface": s, "cui": c, "canonical": n, "score": round(sc, 3)}
        for (s, c, n, sc) in umls_concepts(text, **kwargs)
    ]


def format_umls_concepts_for_prompt(
    text: str,
    min_score: float = 0.80,
) -> str:
    """Return a newline-free human-readable string suitable for a
    'Clinical concepts detected' line in an LLM user prompt.

    Format: ``"<canonical_name> (CUI <cui>) from '<surface>'"``
    separated by semicolons. Deduplicated by (cui, canonical) so if
    two surface spans resolve to the same CUI, the line shows it once.
    Returns an empty string if UMLS is unavailable or no concepts
    survive filtering.
    """
    hits = umls_concepts(text, min_score=min_score, max_per_mention=1)
    if not hits:
        return ""
    seen: Set[Tuple[str, str]] = set()
    parts: List[str] = []
    for surface, cui, name, score in hits:
        key = (cui, (name or "").lower())
        if key in seen:
            continue
        seen.add(key)
        if name:
            parts.append(f"{name} (CUI {cui}) from '{surface}'")
        else:
            parts.append(f"CUI {cui} from '{surface}'")
    return "; ".join(parts)


# ---------------------------------------------------------------------------
# Lemmatization
# ---------------------------------------------------------------------------

def lemmatize(text: str) -> str:
    """Return a lemmatized, lowercase whitespace-joined version of text.

    Preserves token order. Stopwords and punctuation are kept (we do
    not want "extended window" to collapse to "extend" or lose
    "window"). Numbers and hyphenated tokens pass through unchanged.

    Returns the input text lowercased with no further changes when
    scispaCy is unavailable.
    """
    if not text:
        return ""
    nlp = _try_load()
    if nlp is None:
        return text.lower()
    try:
        doc = nlp(text)
    except Exception as e:
        logger.warning("scispaCy lemmatize failed on %r: %s", text[:80], e)
        return text.lower()
    return " ".join(t.lemma_.lower() for t in doc)


def lemma_tokens(text: str) -> List[str]:
    """Return the list of lemma tokens for a text (lowercase, punctuation dropped).

    Useful when a caller wants to check token-by-token containment
    rather than string containment.
    """
    if not text:
        return []
    nlp = _try_load()
    if nlp is None:
        return [tok for tok in text.lower().split() if tok]
    try:
        doc = nlp(text)
    except Exception as e:
        logger.warning("scispaCy token lemmatize failed on %r: %s", text[:80], e)
        return [tok for tok in text.lower().split() if tok]
    return [t.lemma_.lower() for t in doc if not t.is_punct and not t.is_space]


# ---------------------------------------------------------------------------
# Clinical entity recognition
# ---------------------------------------------------------------------------

def clinical_entity_spans(text: str) -> List[Tuple[str, int, int]]:
    """Return (surface_form, start_char, end_char) for every scispaCy entity.

    en_core_sci_sm tags every biomedical span as label ``ENTITY``. We
    do not filter by label — the model has already decided the span is
    clinically relevant. Returns an empty list when scispaCy is
    unavailable.
    """
    if not text:
        return []
    nlp = _try_load()
    if nlp is None:
        return []
    try:
        doc = nlp(text)
    except Exception as e:
        logger.warning("scispaCy NER failed on %r: %s", text[:80], e)
        return []
    return [(ent.text, ent.start_char, ent.end_char) for ent in doc.ents]


def clinical_entity_strings(text: str) -> Set[str]:
    """Return a set of lowercased clinical entity surface forms from text."""
    return {ent.lower() for ent, _s, _e in clinical_entity_spans(text)}


def is_clinical_entity(term: str, context: str) -> bool:
    """Return True iff ``term`` appears in ``context`` inside a scispaCy
    clinical-entity span.

    Used by the anchor layer to decide whether a generic-looking term
    like "oxygen" or "sodium" should count as an anchor for this
    particular question. When scispaCy is unavailable this returns
    True (fail open) so the filter does not silently drop legitimate
    matches in degraded environments.
    """
    if not term or not context:
        return False
    nlp = _try_load()
    if nlp is None:
        return True
    term_l = term.lower()
    try:
        doc = nlp(context)
    except Exception as e:
        logger.warning(
            "scispaCy is_clinical_entity failed on %r in %r: %s",
            term, context[:80], e,
        )
        return True
    for ent in doc.ents:
        if term_l in ent.text.lower():
            return True
    return False


# ---------------------------------------------------------------------------
# Convenience: bridge a surface form through lemmatization
# ---------------------------------------------------------------------------

def normalize_match(haystack: str, needle: str) -> bool:
    """Return True iff the lemmatized form of ``needle`` appears as a
    contiguous token sub-sequence in the lemmatized form of ``haystack``.

    This catches "retriever" vs "retrievers", "occlusion" vs
    "occlusions", "give" vs "given", etc. without listing every
    inflection in the synonym dictionary.

    Falls back to case-insensitive substring containment when scispaCy
    is unavailable, so the filter still works in degraded mode.
    """
    if not haystack or not needle:
        return False
    h_tokens = lemma_tokens(haystack)
    n_tokens = lemma_tokens(needle)
    if not h_tokens or not n_tokens:
        return needle.lower() in haystack.lower()
    if len(n_tokens) == 1:
        return n_tokens[0] in h_tokens
    n_len = len(n_tokens)
    for i in range(0, len(h_tokens) - n_len + 1):
        if h_tokens[i : i + n_len] == n_tokens:
            return True
    return False


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover
    if not is_available():
        print("scispaCy not available in this environment — skipping tests")
        raise SystemExit(0)

    fails: List[str] = []

    # Lemmatization: plurals
    lem = lemmatize("Stent retrievers are preferred for M1 occlusions in patients")
    if "retriever" not in lem or "occlusion" not in lem:
        fails.append(f"lemmatize: {lem!r}")

    # normalize_match: plural -> singular
    if not normalize_match(
        "Stent retrievers are preferred for large vessel occlusions",
        "stent retriever",
    ):
        fails.append("normalize_match: plural collapse failed")

    # normalize_match: verb tense — compare against a haystack where
    # the lemmatized verb is in the same order as the needle. This is
    # a contiguous-subsequence check by design, not a bag-of-words.
    if not normalize_match(
        "Clinicians should give IV alteplase within 4.5 hours",
        "give IV alteplase",
    ):
        fails.append("normalize_match: verb tense failed")

    # Clinical entity gate: "oxygen" in a hypoxia context IS clinical
    if not is_clinical_entity("oxygen", "Supplemental oxygen for hypoxic AIS patients"):
        fails.append("is_clinical_entity: oxygen in hypoxia context should be True")

    # Clinical entity gate: "the" is never a clinical entity
    if is_clinical_entity("the", "The patient had a wake-up stroke with DWI-FLAIR mismatch"):
        fails.append("is_clinical_entity: 'the' should not be a clinical entity")

    # NER returns something on clinical prose
    ents = clinical_entity_strings(
        "IV alteplase 0.9 mg/kg for acute ischemic stroke within 4.5 hours"
    )
    if not ents:
        fails.append("clinical_entity_strings: no entities on clinical prose")

    if fails:
        print("FAIL")
        for f in fails:
            print("  " + f)
        raise SystemExit(1)

    print("OK — scispaCy wrapper tests pass")
    print(f"  model = {_MODEL_NAME}")
    print(f"  sample lemmatize: stent retrievers -> "
          f"{lemmatize('stent retrievers')!r}")
    print(f"  sample entities:  "
          f"{sorted(clinical_entity_strings('IV alteplase for AIS within 4.5h'))}")
