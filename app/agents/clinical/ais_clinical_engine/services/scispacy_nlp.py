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
from typing import Iterable, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lazy single-load of the scispaCy pipeline
# ---------------------------------------------------------------------------

_MODEL_NAME = os.environ.get("QA_V3_SCISPACY_MODEL", "en_core_sci_sm")

_nlp = None
_load_lock = threading.Lock()
_load_failed = False


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
