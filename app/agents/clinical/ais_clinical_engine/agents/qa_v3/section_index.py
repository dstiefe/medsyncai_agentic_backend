# ─── v3 (Q&A v3 namespace) ─────────────────────────────────────────────
# This file lives under agents/qa_v3/ and is the active v3 copy of the
# Guideline Q&A pipeline. Edits made here do NOT affect agents/qa/
# which remains as the v2 baseline. To switch the live route to v3,
# update the import at services/qa_service.py or routes.py accordingly.
# ───────────────────────────────────────────────────────────────────────
"""
Section Concept Index — auto-generated reverse index from guideline content.

For each section, extracts all clinically meaningful terms from:
    1. Recommendation text (202 recs)
    2. Section titles
    3. RSS/supportive text

This gives the intent agent a data-driven way to resolve ambiguous
questions to the correct section, complementing the hand-curated
TOPIC_SECTION_MAP. When TOPIC_SECTION_MAP has a match, it wins (more
precise). When it doesn't, the concept index provides a fallback
that's still better than raw keyword scoring.

Architecture:
    - Built once at startup from existing JSON data
    - Pure Python, deterministic, no LLM
    - Returns scored section matches for a question
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Dict, List, Set, Tuple


# Clinical stopwords — terms too generic to distinguish sections
_STOPWORDS = {
    "patient", "patients", "stroke", "ischemic", "acute", "ais",
    "treatment", "management", "recommendation", "recommended",
    "guideline", "clinical", "evidence", "study", "studies",
    "outcome", "outcomes", "risk", "benefit", "may", "should",
    "based", "data", "trial", "trials", "versus", "compared",
    "associated", "significant", "increase", "decrease", "reduce",
    "improved", "higher", "lower", "use", "used", "using",
    "time", "hours", "minutes", "days", "weeks", "months",
    "onset", "admission", "hospital", "emergency",
    "class", "level", "cor", "loe", "section",
    "including", "considered", "reasonable", "performed",
    "receiving", "eligible", "appropriate", "initiation",
    "within", "before", "after", "during",
}

# Minimum term length to include
_MIN_TERM_LENGTH = 3


def build_section_concept_index(
    recommendations: List[Dict[str, Any]],
    guideline_knowledge: Dict[str, Any],
) -> Dict[str, Set[str]]:
    """
    Build a section → set of distinctive terms index.

    Terms that appear in many sections are down-weighted by only keeping
    terms that appear in ≤3 sections (discriminating power).

    Returns:
        Dict mapping section number to set of distinctive terms
    """
    # Step 1: collect all terms per section
    section_terms: Dict[str, List[str]] = defaultdict(list)

    # From recommendations
    for rec in recommendations:
        section = rec.get("section", "")
        if not section:
            continue
        text = rec.get("text", "")
        title = rec.get("sectionTitle", "")
        terms = _extract_terms(text + " " + title)
        section_terms[section].extend(terms)

    # From guideline knowledge (RSS, synopsis, section titles)
    sections_data = guideline_knowledge.get("sections", {})
    for sec_num, sec_data in sections_data.items():
        title = sec_data.get("sectionTitle", "")
        section_terms[sec_num].extend(_extract_terms(title))

        # RSS entries
        for rss in sec_data.get("rss", []):
            rss_text = rss.get("text", "")[:500]  # cap per entry
            section_terms[sec_num].extend(_extract_terms(rss_text))

        # Synopsis
        synopsis = sec_data.get("synopsis", "")
        if synopsis:
            section_terms[sec_num].extend(_extract_terms(synopsis[:500]))

    # Step 2: count how many sections each term appears in
    term_section_count: Dict[str, int] = defaultdict(int)
    for section, terms in section_terms.items():
        unique_terms = set(terms)
        for term in unique_terms:
            term_section_count[term] += 1

    # Step 3: keep only discriminating terms (appear in ≤3 sections)
    section_concepts: Dict[str, Set[str]] = {}
    for section, terms in section_terms.items():
        unique = set(terms)
        discriminating = {
            t for t in unique
            if term_section_count[t] <= 3
            and t not in _STOPWORDS
            and len(t) >= _MIN_TERM_LENGTH
        }
        section_concepts[section] = discriminating

    return section_concepts


def score_question_sections(
    question: str,
    section_concepts: Dict[str, Set[str]],
    top_k: int = 5,
) -> List[Tuple[str, int]]:
    """
    Score all sections against a question using the concept index.

    Returns list of (section, score) tuples sorted by score descending.
    Only returns sections with score > 0.
    """
    q_terms = set(_extract_terms(question))
    if not q_terms:
        return []

    scores: List[Tuple[str, int]] = []
    for section, concepts in section_concepts.items():
        overlap = q_terms & concepts
        if overlap:
            # Score = number of matching concepts, weighted by term length
            # (longer terms are more specific)
            score = sum(len(t) for t in overlap)
            scores.append((section, score))

    scores.sort(key=lambda x: -x[1])
    return scores[:top_k]


def _extract_terms(text: str) -> List[str]:
    """Extract clinically meaningful terms from text."""
    if not text:
        return []

    text_lower = text.lower()

    # Extract individual words
    words = re.findall(r'[a-z][a-z\-]+[a-z]', text_lower)
    terms = [w for w in words if len(w) >= _MIN_TERM_LENGTH and w not in _STOPWORDS]

    # Extract bigrams (two-word phrases) for compound clinical terms
    word_list = re.findall(r'[a-z][a-z\-]+', text_lower)
    for i in range(len(word_list) - 1):
        bigram = f"{word_list[i]} {word_list[i+1]}"
        if len(bigram) >= 8 and word_list[i] not in _STOPWORDS:
            terms.append(bigram)

    # Extract specific clinical patterns
    # Drug names (capitalized in original text)
    drug_pattern = re.findall(r'\b[A-Z][a-z]{3,}(?:plase|parin|parin|pine|lol|zol|tase|mab|ide)\b', text)
    terms.extend(d.lower() for d in drug_pattern)

    # Numeric thresholds (e.g., "185/110", "4.5 hours")
    threshold_pattern = re.findall(r'\d+(?:\.\d+)?/\d+', text)
    terms.extend(threshold_pattern)

    return terms
