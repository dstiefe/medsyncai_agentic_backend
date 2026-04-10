"""
Deterministic parser for the v2 Q&A pipeline.

This is the "least fragile, most deterministic" replacement for
QAQueryParsingAgent.parse_v2(). It produces a ParsedQAQueryV2 using
only the scaffolding bundle (intent_catalog, guideline_topic_map,
synonym_dictionary, data_dictionary.v2) — NO LLM calls, no network.

Contract:
    input:   a free-text clinical question
    output:  ParsedQAQueryV2 with intent, topic, sections, slots

Pipeline:
    1. Normalize the question (lowercase, strip punctuation).
    2. Intent classification by keyword match against intent_catalog
       trigger_patterns, with a fixed-priority tiebreaker.
    3. Topic + section resolution by scoring every gtm topic against
       the question using topic name + `addresses` blurb; the synonym
       dictionary's reverse_index contributes additional section hits.
    4. Slot extraction by scanning the question for canonical phrases
       from the synonym dictionary and a small regex table for
       numerics (age, NIHSS, time windows, etc.).
    5. Out-of-scope fallback when no topic and no section resolve.

The parser is auditable: every decision is a Python function with a
traceable score. The orchestrator records the full trace in
`scaffolding_trace` so the dev_log can reconstruct why any question
routed where it did.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .scaffolding_loader import ScaffoldingBundle, get_scaffolding
from .schemas import ParsedQAQueryV2, VnIntent


# ---------------------------------------------------------------------------
# Intent trigger table — compiled once per module load
# ---------------------------------------------------------------------------
#
# Each intent maps to an ordered list of (phrase, weight) pairs. Phrases are
# matched case-insensitively against the question. Multi-word phrases score
# higher than single keywords so "who is eligible for tenecteplase"
# unambiguously picks eligibility_criteria over treatment_choice.
#
# Priority rules (applied in order when multiple intents tie):
#     1. Higher score wins.
#     2. If tied, the intent with the longer matched phrase wins.
#     3. If still tied, the fixed _INTENT_PRIORITY list wins.
#
# Keep this table close to intent_catalog.json's trigger_patterns. If an
# intent is added to the catalog, add a row here.

_INTENT_TRIGGERS: Dict[VnIntent, List[Tuple[str, int]]] = {
    VnIntent.DOSE: [
        ("what dose", 5), ("dose of", 5), ("dosing", 4),
        ("how much", 3), ("mg/kg", 5), ("maximum dose", 5),
    ],
    VnIntent.DURATION: [
        ("how long", 4), ("duration of", 5), ("for how long", 5),
        ("continue for", 3),
    ],
    VnIntent.TIME_WINDOW: [
        ("time window", 5), ("within how many hours", 5),
        ("window for", 4), ("how long after", 4), ("up to how many hours", 5),
    ],
    VnIntent.ONSET_TO_TREATMENT: [
        ("onset to treatment", 5), ("door to needle", 5),
        ("door-to-needle", 5), ("door to groin", 5), ("last known well", 4),
    ],
    VnIntent.THRESHOLD_TARGET: [
        ("target", 4), ("threshold", 4), ("goal", 3),
        ("bp target", 5), ("blood pressure target", 5),
        ("glucose target", 5), ("saturation target", 5),
    ],
    VnIntent.FREQUENCY: [
        ("how often", 5), ("how frequently", 5), ("frequency of", 5),
        ("every how many", 5),
    ],
    VnIntent.ELIGIBILITY_CRITERIA: [
        ("who is eligible", 5), ("who qualifies", 5), ("eligibility for", 5),
        ("inclusion criteria", 5), ("candidate for", 4), ("candidates for", 4),
        ("is a candidate", 4),
    ],
    VnIntent.EXCLUSION_CRITERIA: [
        ("exclusion criteria", 5), ("who is excluded", 5),
        ("excluded from", 4), ("disqualifies", 4), ("disqualified from", 4),
    ],
    VnIntent.CONTRAINDICATIONS: [
        ("contraindication", 5), ("contraindications", 5),
        ("cannot receive", 4), ("must not receive", 4),
        ("when not to", 3),
    ],
    VnIntent.INDICATION: [
        ("indication for", 5), ("indications for", 5),
        ("when to give", 4), ("when to use", 4),
    ],
    VnIntent.DRUG_CHOICE: [
        ("which drug", 5), ("which agent", 5), ("drug of choice", 5),
        ("preferred drug", 5), ("which thrombolytic", 5),
    ],
    VnIntent.TREATMENT_CHOICE: [
        ("which treatment", 5), ("which therapy", 5), ("which intervention", 5),
        ("preferred treatment", 5),
    ],
    VnIntent.ALTERNATIVE_OPTION: [
        ("alternative to", 5), ("instead of", 4), ("if not", 3),
        ("when ivt is not", 4), ("cannot get", 3),
    ],
    VnIntent.IMAGING_CHOICE: [
        ("which imaging", 5), ("ct or mri", 4), ("which scan", 5),
        ("imaging modality", 5), ("cta or mra", 4),
    ],
    VnIntent.DIAGNOSTIC_TEST: [
        ("which test", 5), ("which lab", 5), ("what labs", 5),
        ("diagnostic test", 5), ("which blood test", 5),
    ],
    VnIntent.MONITORING: [
        ("monitor", 3), ("monitoring", 4), ("watch for", 3),
        ("follow up", 2), ("follow-up", 2),
    ],
    VnIntent.REASSESSMENT: [
        ("reassess", 5), ("repeat imaging", 5), ("recheck", 4),
        ("reassessment", 5),
    ],
    VnIntent.POST_TREATMENT_CARE: [
        ("after ivt", 4), ("post ivt", 4), ("after evt", 4),
        ("post evt", 4), ("post-treatment", 5), ("post treatment", 5),
    ],
    VnIntent.COMPLICATION_MANAGEMENT: [
        ("complication", 4), ("sich", 5), ("hemorrhagic transformation", 5),
        ("angioedema", 5), ("manage bleeding", 5),
    ],
    VnIntent.REVERSAL: [
        ("reverse", 4), ("reversal", 5), ("reverse alteplase", 5),
        ("reverse tpa", 5), ("reverse anticoagulation", 5),
    ],
    VnIntent.SEQUENCING: [
        ("before or after", 5), ("what order", 5), ("sequence of", 5),
        ("first or second", 4),
    ],
    VnIntent.PROCEDURAL_TIMING: [
        ("when to perform", 5), ("timing of the procedure", 5),
        ("how soon", 4),
    ],
    VnIntent.SETTING_OF_CARE: [
        ("where should", 4), ("which unit", 5), ("stroke unit", 4),
        ("icu or ward", 5), ("comprehensive stroke center", 4),
    ],
    VnIntent.SCREENING: [
        ("screen for", 5), ("screening for", 5),
    ],
    VnIntent.RISK_FACTOR: [
        ("risk factor", 5), ("risk factors", 5),
    ],
    VnIntent.CLASS_OF_RECOMMENDATION: [
        ("class of recommendation", 5), ("cor for", 4),
        ("level of evidence", 5), ("loe for", 4),
    ],
    VnIntent.RATIONALE: [
        ("why is", 3), ("what is the rationale", 5), ("rationale for", 5),
    ],
    VnIntent.DEFINITION: [
        ("what is", 2), ("define", 4), ("definition of", 5),
        ("what does", 2),
    ],
    VnIntent.EVIDENCE_RETRIEVAL: [
        ("what evidence", 5), ("what does the evidence", 5),
        ("studies show", 4), ("trial data", 4),
    ],
    VnIntent.INTERVENTION_RECOMMENDATION: [
        ("should i give", 4), ("should we give", 4), ("recommend", 3),
    ],
    VnIntent.PATIENT_ELIGIBILITY: [
        ("is this patient", 5), ("is my patient", 5),
        ("can this patient", 5), ("can my patient", 5),
    ],
}

# Fixed tie-breaker order when scores are equal. More specific/narrower
# intents first so "dose" beats the generic "treatment_choice".
_INTENT_PRIORITY: List[VnIntent] = [
    VnIntent.DOSE,
    VnIntent.DURATION,
    VnIntent.TIME_WINDOW,
    VnIntent.ONSET_TO_TREATMENT,
    VnIntent.THRESHOLD_TARGET,
    VnIntent.FREQUENCY,
    VnIntent.ELIGIBILITY_CRITERIA,
    VnIntent.EXCLUSION_CRITERIA,
    VnIntent.CONTRAINDICATIONS,
    VnIntent.REVERSAL,
    VnIntent.COMPLICATION_MANAGEMENT,
    VnIntent.ALTERNATIVE_OPTION,
    VnIntent.SCREENING,
    VnIntent.REASSESSMENT,
    VnIntent.POST_TREATMENT_CARE,
    VnIntent.SEQUENCING,
    VnIntent.PROCEDURAL_TIMING,
    VnIntent.MONITORING,
    VnIntent.SETTING_OF_CARE,
    VnIntent.DRUG_CHOICE,
    VnIntent.IMAGING_CHOICE,
    VnIntent.DIAGNOSTIC_TEST,
    VnIntent.CLASS_OF_RECOMMENDATION,
    VnIntent.RATIONALE,
    VnIntent.DEFINITION,
    VnIntent.RISK_FACTOR,
    VnIntent.INDICATION,
    VnIntent.EVIDENCE_RETRIEVAL,
    VnIntent.PATIENT_ELIGIBILITY,
    VnIntent.TREATMENT_CHOICE,
    VnIntent.INTERVENTION_RECOMMENDATION,
]


# ---------------------------------------------------------------------------
# Slot extraction — regex table for numerics, synonym dict for everything else
# ---------------------------------------------------------------------------

_SLOT_REGEXES: Dict[str, re.Pattern] = {
    "age": re.compile(r"\b(\d{1,3})\s*(?:y|yo|yr|yrs|year[- ]?old|years? old)\b", re.I),
    "nihss": re.compile(r"\bnihss\s*(?:of|is|=|:)?\s*(\d{1,2})\b", re.I),
    "time_from_onset": re.compile(r"\b(\d{1,2}(?:\.\d)?)\s*(?:h|hr|hrs|hours?)\b", re.I),
    "sbp": re.compile(r"\bsbp\s*(?:of|is|=|:)?\s*(\d{2,3})\b", re.I),
    "glucose_value": re.compile(r"\bglucose\s*(?:of|is|=|:)?\s*(\d{2,3})\b", re.I),
}


@dataclass
class ParseTrace:
    """Audit trace emitted into ParsedQAQueryV2.scaffolding_trace."""

    intent_scores: Dict[str, int] = field(default_factory=dict)
    intent_matched_phrases: Dict[str, List[str]] = field(default_factory=dict)
    topic_scores: Dict[str, int] = field(default_factory=dict)
    synonym_section_hits: Dict[str, List[str]] = field(default_factory=dict)
    resolved_sections_before_verifier: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "intent_scores": dict(self.intent_scores),
            "intent_matched_phrases": {
                k: list(v) for k, v in self.intent_matched_phrases.items()
            },
            "topic_scores": dict(self.topic_scores),
            "synonym_section_hits": {
                k: list(v) for k, v in self.synonym_section_hits.items()
            },
            "resolved_sections_before_verifier": list(
                self.resolved_sections_before_verifier
            ),
            "notes": list(self.notes),
        }


# ---------------------------------------------------------------------------
# Intent classification
# ---------------------------------------------------------------------------


def _normalize(question: str) -> str:
    """Lowercase, strip leading/trailing whitespace, collapse runs of spaces."""
    return re.sub(r"\s+", " ", question.strip().lower())


def _score_intents(normalized: str) -> Tuple[
    Dict[VnIntent, int], Dict[VnIntent, List[str]]
]:
    """Return (scores, matched_phrases_per_intent)."""
    scores: Dict[VnIntent, int] = {}
    matches: Dict[VnIntent, List[str]] = {}
    for intent, triggers in _INTENT_TRIGGERS.items():
        score = 0
        hit_phrases: List[str] = []
        for phrase, weight in triggers:
            if phrase in normalized:
                score += weight
                hit_phrases.append(phrase)
        if score > 0:
            scores[intent] = score
            matches[intent] = hit_phrases
    return scores, matches


def _pick_intent(
    scores: Dict[VnIntent, int],
    matches: Dict[VnIntent, List[str]],
) -> VnIntent:
    """Select the winning intent given scores and matched phrases.

    Tie-breaker order:
        1. Highest total score.
        2. Longest single matched phrase (specificity).
        3. Fixed _INTENT_PRIORITY position.
    """
    if not scores:
        return VnIntent.OUT_OF_SCOPE

    top_score = max(scores.values())
    candidates = [i for i, s in scores.items() if s == top_score]
    if len(candidates) == 1:
        return candidates[0]

    # Tiebreak 2: longest matched phrase.
    def longest_phrase(intent: VnIntent) -> int:
        return max((len(p) for p in matches.get(intent, [])), default=0)

    max_len = max(longest_phrase(c) for c in candidates)
    candidates = [c for c in candidates if longest_phrase(c) == max_len]
    if len(candidates) == 1:
        return candidates[0]

    # Tiebreak 3: priority list.
    priority_index = {intent: i for i, intent in enumerate(_INTENT_PRIORITY)}
    candidates.sort(key=lambda c: priority_index.get(c, 999))
    return candidates[0]


# ---------------------------------------------------------------------------
# Topic + section resolution
# ---------------------------------------------------------------------------


_STOPWORDS = {
    "the", "a", "an", "of", "for", "in", "on", "to", "and", "or", "is",
    "are", "was", "were", "be", "been", "being", "what", "which", "who",
    "when", "where", "how", "does", "do", "did", "has", "have", "had",
    "with", "from", "about", "my", "this", "that", "it", "can", "should",
    "would", "could", "will", "i", "we", "you",
}


def _tokenize(text: str) -> List[str]:
    """Split on non-alphanumeric, drop stopwords, drop 1-char tokens."""
    toks = re.findall(r"[a-z0-9]+", text.lower())
    return [t for t in toks if t not in _STOPWORDS and len(t) > 1]


def _score_topics(
    normalized: str, bundle: ScaffoldingBundle
) -> Dict[str, int]:
    """Score every gtm topic against the normalized question.

    Score = (topic name substring hit × 10)
          + (unique tokens shared with `addresses` blurb × 1)
    """
    q_tokens = set(_tokenize(normalized))
    scores: Dict[str, int] = {}
    for t in bundle.topic_map.get("topics", []):
        name = (t.get("topic") or "").lower()
        section = t.get("section")
        if not name or not section:
            continue
        score = 0
        if name in normalized:
            score += 10
        addresses = (t.get("addresses") or "").lower()
        addr_tokens = set(_tokenize(addresses))
        score += len(q_tokens & addr_tokens)
        if score > 0:
            # Use "topic|section" as the key so duplicate topic names
            # (if any) don't collide.
            scores[f"{t.get('topic')}|{section}"] = score
    return scores


def _synonym_section_hits(
    normalized: str, bundle: ScaffoldingBundle
) -> Dict[str, List[str]]:
    """Scan the synonym dictionary terms and return {section_id: [hit_terms]}.

    Each term object has a `sections` list. If a term's full form, id, or
    any of its synonyms appears in the question, every section in that
    term's list gets a hit.
    """
    hits: Dict[str, List[str]] = {}
    terms = bundle.synonym_dict.get("terms", {}) or {}
    for term_id, obj in terms.items():
        if not isinstance(obj, dict):
            continue
        candidates = [term_id, obj.get("full_term", "")] + list(
            obj.get("synonyms") or []
        )
        matched_surface = None
        for c in candidates:
            if not c:
                continue
            cl = c.lower()
            # Boundary-aware match so "bp" doesn't fire on "bpa".
            if re.search(rf"\b{re.escape(cl)}\b", normalized):
                matched_surface = c
                break
        if not matched_surface:
            continue
        for sec in obj.get("sections") or []:
            # Skip pseudo-section tokens the synonym dict uses for
            # cross-cutting terms ("all", "multiple", empty strings).
            # Also skip anything that doesn't resolve in the scaffolding
            # — the verifier would reject it anyway, and leaving it in
            # just pollutes the trace.
            if not sec or sec in ("all", "multiple"):
                continue
            if sec not in bundle.dd_sections and sec not in bundle.gtm_sections:
                continue
            hits.setdefault(sec, []).append(matched_surface)
    return hits


# ---------------------------------------------------------------------------
# Slot extraction
# ---------------------------------------------------------------------------


def _extract_slots(
    intent: VnIntent,
    normalized: str,
    bundle: ScaffoldingBundle,
    synonym_hits: Dict[str, List[str]],
) -> Dict[str, Any]:
    """Build the slots dict for the chosen intent.

    Populates:
        - numeric slots via _SLOT_REGEXES (age, nihss, time_from_onset, etc.)
        - treatment_or_procedure / drug_or_agent from the synonym dict
          (any matched term whose category is treatment/drug/procedure)
        - parameter from keyword scan (BP/glucose/temperature/saturation)
        - topic passthrough handled by the caller
    """
    slots: Dict[str, Any] = {}

    # numerics
    for slot, regex in _SLOT_REGEXES.items():
        m = regex.search(normalized)
        if m:
            try:
                slots[slot] = float(m.group(1))
            except (TypeError, ValueError):
                slots[slot] = m.group(1)

    # treatment / drug / procedure — scan the synonym hits for categories.
    # The synonym dict uses category="medication" + subcategory="thrombolytic"
    # for drugs and category="treatment" for procedures, so we check both
    # category and subcategory against a tolerant keyword list.
    terms = bundle.synonym_dict.get("terms", {}) or {}
    treatments: List[str] = []
    drugs: List[str] = []

    drug_markers = ("medication", "drug", "agent", "thrombolytic")
    treatment_markers = ("treatment", "procedure", "intervention")

    seen_drug_canon: set = set()
    seen_treatment_canon: set = set()

    for sec_id, matched_terms in synonym_hits.items():
        for surface in matched_terms:
            surface_lc = surface.lower()
            for term_id, obj in terms.items():
                if not isinstance(obj, dict):
                    continue
                haystack = [term_id.lower(), (obj.get("full_term") or "").lower()]
                haystack.extend((s or "").lower() for s in obj.get("synonyms") or [])
                if surface_lc not in haystack:
                    continue

                category = (obj.get("category") or "").lower()
                subcategory = (obj.get("subcategory") or "").lower()
                combined = f"{category} {subcategory}"
                canonical = obj.get("full_term") or term_id

                if any(m in combined for m in drug_markers):
                    if canonical not in seen_drug_canon:
                        drugs.append(canonical)
                        seen_drug_canon.add(canonical)
                if any(m in combined for m in treatment_markers):
                    if canonical not in seen_treatment_canon:
                        treatments.append(canonical)
                        seen_treatment_canon.add(canonical)

    # Drugs are also treatments for eligibility_criteria questions (e.g.
    # "who is eligible for tenecteplase" — the drug IS the treatment).
    if drugs and not treatments and intent in (
        VnIntent.ELIGIBILITY_CRITERIA,
        VnIntent.EXCLUSION_CRITERIA,
        VnIntent.CONTRAINDICATIONS,
        VnIntent.INDICATION,
        VnIntent.DOSE,
        VnIntent.DURATION,
        VnIntent.ROUTE,
        VnIntent.ALTERNATIVE_OPTION,
    ):
        treatments = list(drugs)

    if treatments:
        slots["treatment_or_procedure"] = (
            treatments[0] if len(treatments) == 1 else treatments
        )
    if drugs:
        slots["drug_or_agent"] = drugs[0] if len(drugs) == 1 else drugs

    # ── intent-specific slot aliases ────────────────────────────
    # Some intents have specific slot names ("term", "agent_to_reverse",
    # "test_name", "screening_target") that are semantically "the thing
    # the user is asking about". When the parser found synonym hits in
    # the question, use them to fill the intent's specific slot name.
    first_synonym = None
    for sec_id, matched_terms in synonym_hits.items():
        if matched_terms:
            first_synonym = matched_terms[0]
            break

    if intent == VnIntent.DEFINITION and first_synonym:
        slots.setdefault("term", first_synonym)
    if intent == VnIntent.REVERSAL and drugs:
        slots.setdefault("agent_to_reverse", drugs[0])
    if intent == VnIntent.DIAGNOSTIC_TEST and first_synonym:
        slots.setdefault("test_name", first_synonym)
    if intent == VnIntent.SCREENING and first_synonym:
        slots.setdefault("screening_target", first_synonym)
    if intent == VnIntent.RISK_FACTOR and first_synonym:
        slots.setdefault("outcome", first_synonym)
    if intent == VnIntent.CLASS_OF_RECOMMENDATION and first_synonym:
        slots.setdefault("recommendation_subject", first_synonym)

    # parameter (for threshold_target questions)
    param_keywords = [
        ("blood pressure", "blood pressure"),
        ("bp target", "blood pressure"),
        ("glucose", "glucose"),
        ("temperature", "temperature"),
        ("oxygen saturation", "oxygen saturation"),
        ("spo2", "oxygen saturation"),
        ("saturation", "oxygen saturation"),
    ]
    for surface, canonical in param_keywords:
        if surface in normalized:
            slots["parameter"] = canonical
            break

    return slots


# ---------------------------------------------------------------------------
# Top-level parse
# ---------------------------------------------------------------------------


def parse_deterministic(
    question: str,
    bundle: Optional[ScaffoldingBundle] = None,
) -> ParsedQAQueryV2:
    """
    Deterministic parse of a user question into a ParsedQAQueryV2.

    This is the entry point the v2 orchestrator calls. No LLM, no
    network, no side effects beyond reading the cached scaffolding.
    """
    bundle = bundle or get_scaffolding()
    normalized = _normalize(question)
    trace = ParseTrace()

    # ── 1. Intent classification ────────────────────────────────────
    intent_scores, intent_matches = _score_intents(normalized)
    intent = _pick_intent(intent_scores, intent_matches)
    trace.intent_scores = {i.value: s for i, s in intent_scores.items()}
    trace.intent_matched_phrases = {
        i.value: list(ps) for i, ps in intent_matches.items()
    }

    # ── 2. Topic scoring ────────────────────────────────────────────
    topic_scores = _score_topics(normalized, bundle)
    trace.topic_scores = dict(topic_scores)
    picked_topic: Optional[str] = None
    picked_section_from_topic: Optional[str] = None
    if topic_scores:
        best_key = max(topic_scores.keys(), key=lambda k: topic_scores[k])
        topic_name, section = best_key.split("|", 1)
        picked_topic = topic_name
        picked_section_from_topic = section

    # ── 3. Synonym-driven section hits ──────────────────────────────
    syn_hits = _synonym_section_hits(normalized, bundle)
    trace.synonym_section_hits = {k: list(v) for k, v in syn_hits.items()}

    # ── 4. Assemble candidate sections ──────────────────────────────
    candidate_sections: List[str] = []
    if picked_section_from_topic:
        candidate_sections.append(picked_section_from_topic)
    # Synonym hits ranked by number of matches so a term that hits once
    # doesn't drown out the topic match. Cap at top 5 to keep the
    # downstream verifier focused.
    syn_ranked = sorted(
        syn_hits.items(), key=lambda kv: (-len(kv[1]), kv[0])
    )
    for sec, _ in syn_ranked[:5]:
        if sec not in candidate_sections:
            candidate_sections.append(sec)
    trace.resolved_sections_before_verifier = list(candidate_sections)

    # ── 5. Out-of-scope fallback ────────────────────────────────────
    if intent == VnIntent.OUT_OF_SCOPE and not candidate_sections:
        trace.notes.append("no intent match and no section hits → out_of_scope")
        return ParsedQAQueryV2(
            question=question,
            intent=VnIntent.OUT_OF_SCOPE,
            topic=None,
            sections=[],
            slots={},
            scaffolding_trace={
                **trace.to_dict(),
                "answer_shape": "not_addressed_in_guideline",
                "parser": "deterministic",
            },
            parser_confidence=1.0,
        )

    # If we found sections but no intent, fall back to intervention_recommendation
    # so the text path fires and returns the relevant recs verbatim.
    if intent == VnIntent.OUT_OF_SCOPE and candidate_sections:
        intent = VnIntent.INTERVENTION_RECOMMENDATION
        trace.notes.append(
            "no intent match but sections resolved → intervention_recommendation fallback"
        )

    # ── 6. Slot extraction ──────────────────────────────────────────
    slots = _extract_slots(intent, normalized, bundle, syn_hits)

    # ── 7. answer_shape from catalog ────────────────────────────────
    intent_entry = bundle.intent(intent.value) or {}
    answer_shape = intent_entry.get("answer_shape") or "narrative_text"

    return ParsedQAQueryV2(
        question=question,
        intent=intent,
        topic=picked_topic,
        sections=candidate_sections,
        slots=slots,
        scaffolding_trace={
            **trace.to_dict(),
            "answer_shape": answer_shape,
            "parser": "deterministic",
        },
        parser_confidence=1.0,
    )


__all__ = [
    "parse_deterministic",
    "ParseTrace",
]
