# ─── v4 (Q&A v4 namespace) ─────────────────────────────────────────────
# Step 3: Two-stage section routing + content retrieval.
#
# Pure Python. No LLM. No regex. Deterministic lookups only.
#
# Stage 1 — Section Routing (ALL anchor terms participate):
#   Score sections by tier-weighted anchor term matches.
#   Weights: pinpoint=10, narrow=5, broad=2, global=0.5.
#   Primary-role terms score 3x base. Co-occurrence bonus when 2+ match.
#   Highest-scoring section wins.
#
# Stage 2 — Content Retrieval (filter by values + narrow/pinpoint):
#   Two filters refine the rec list:
#     1. Anchor terms with values (ANY tier) → rec must mention the
#        term AND have a number nearby in the text.
#     2. Narrow/pinpoint terms without values → rec must mention the term.
#   Global/broad terms without values don't filter — they did their
#   job getting us to the right sections in Stage 1.
#
# Tier classification comes from anchor_word_discrimination_index.json:
#   global  = 5+ sections (IVT, EVT, AIS, sICH, NIHSS, etc.)
#   broad   = 3-4 sections (alteplase, ASPECTS, CTA, etc.)
#   narrow  = 2 sections (SBP, BP, EMS, etc.)
#   pinpoint = 1 section (labetalol, decompressive craniectomy, etc.)
# ───────────────────────────────────────────────────────────────────────
"""
Step 3: Two-stage routing — section selection then content retrieval.

Takes validated Step 1 output (intent, topic, anchor_terms) and:
1. Stage 1: Scores sections by tier-weighted anchor term co-occurrence
2. Stage 2: Filters recs by anchor values (any tier) and
   narrow/pinpoint terms. Global/broad without values don't filter.
3. Returns a RetrievedContent bundle for Step 4 (ResponsePresenter)
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from .schemas import ParsedQAQuery

logger = logging.getLogger(__name__)
logger.info("content_retriever v4.2 loaded — tables as sections")

_REF_DIR = os.path.join(os.path.dirname(__file__), "references")
_DATA_DIR = os.path.join(
    os.path.dirname(__file__), os.pardir, os.pardir, "data",
)


# ── Tier weights ────────────────────────────────────────────────────

_TIER_WEIGHTS = {
    "pinpoint": 10.0,
    "narrow": 5.0,
    "broad": 2.0,
    "global": 0.5,
}
_PRIMARY_MULTIPLIER = 3.0
_CO_OCCURRENCE_FACTOR = 0.3


# ── Stage 2 filters ─────────────────────────────────────────────────

@dataclass
class _Stage2Filters:
    """Rec-level filters built from anchor terms + values.

    term_filters:  synonym-expanded sets for narrow/pinpoint terms
                   without values. Rec must mention at least one term.
    value_filters: synonym-expanded sets for terms WITH values (any tier).
                   Rec must mention the term AND have a number nearby.
    all_expanded:  union of all filter terms (for scoring/ordering).

    A rec passes Stage 2 if it matches ANY single filter.
    If no filters exist (all global/broad without values), a fallback
    primary term is used.
    """
    term_filters: List[Set[str]] = field(default_factory=list)
    value_filters: List[Set[str]] = field(default_factory=list)
    all_expanded: Set[str] = field(default_factory=set)

    @property
    def has_filters(self) -> bool:
        return bool(self.term_filters or self.value_filters)


# ── Reference data (loaded once, cached) ─────────────────────────────

def _load_ref_json(filename: str) -> dict:
    path = os.path.join(_REF_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


class _RoutingMaps:
    """Lazy-loaded routing maps for two-stage section routing."""

    _instance: Optional[_RoutingMaps] = None

    def __init__(self):
        self._intent_sources: Optional[Dict[str, List[str]]] = None
        self._topic_to_section: Optional[Dict[str, str]] = None
        self._anchor_to_sections: Optional[Dict[str, List[str]]] = None
        self._term_to_tier: Optional[Dict[str, str]] = None
        self._section_term_role: Optional[Dict[str, Dict[str, str]]] = None
        self._table_to_section: Optional[Dict[str, str]] = None
        self._figure_to_section: Optional[Dict[int, str]] = None
        self._term_to_family: Optional[Dict[str, str]] = None
        self._term_to_synonyms: Optional[Dict[str, Set[str]]] = None

    @classmethod
    def get(cls) -> _RoutingMaps:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @property
    def intent_sources(self) -> Dict[str, List[str]]:
        """Intent name → list of source type codes (REC, SYN, RSS, KG, TBL, FIG, FRONT)."""
        if self._intent_sources is None:
            data = _load_ref_json("intent_content_source_map.json")
            self._intent_sources = {}
            for entry in data["intents"]:
                sources = [s.strip() for s in entry["sources"].split("+")]
                self._intent_sources[entry["intent"]] = sources
        return self._intent_sources

    @property
    def topic_to_section(self) -> Dict[str, str]:
        """Topic name → primary section number."""
        if self._topic_to_section is None:
            data = _load_ref_json("guideline_topic_map.json")
            self._topic_to_section = {
                e["topic"]: e["section"] for e in data["topics"]
            }
        return self._topic_to_section

    @property
    def anchor_to_sections(self) -> Dict[str, List[str]]:
        """Lowercased anchor term → list of section IDs.

        Built from guideline_anchor_words.json v2. Scans both
        "sections" (dict-style terms with tier/role) and
        "special_tables"/"special_figures" (plain string terms,
        treated as pinpoint). Side-populates term_to_tier and
        section_term_role during the same scan.
        """
        if self._anchor_to_sections is None:
            self._anchor_to_sections = {}
            self._term_to_tier = {}
            self._section_term_role = {}
            data = _load_ref_json("guideline_anchor_words.json")

            # ── Sections: dict-style terms with tier/role ────────
            for sec_id, sec_data in data.get("sections", {}).items():
                aw = sec_data.get("anchor_words", {})
                for terms in aw.values():
                    if not isinstance(terms, list):
                        continue
                    for t in terms:
                        if not isinstance(t, dict) or "term" not in t:
                            continue
                        self._register_anchor(
                            sec_id, t["term"],
                            t.get("tier", "pinpoint"),
                            t.get("role"),
                        )

            # ── Tables and figures: plain string terms ───────────
            for group in ("special_tables", "special_figures"):
                for sec_id, sec_data in data.get(group, {}).items():
                    aw = sec_data.get("anchor_words", [])
                    if not isinstance(aw, list):
                        continue
                    for t in aw:
                        if isinstance(t, str):
                            self._register_anchor(
                                sec_id, t, "pinpoint", None,
                            )
                        elif isinstance(t, dict) and "term" in t:
                            self._register_anchor(
                                sec_id, t["term"],
                                t.get("tier", "pinpoint"),
                                t.get("role"),
                            )

        return self._anchor_to_sections

    def _register_anchor(
        self, sec_id: str, term: str, tier: str,
        role: Optional[str],
    ) -> None:
        """Register one anchor term for a section."""
        key = term.lower()

        # anchor_to_sections: term → [section_ids]
        if key not in self._anchor_to_sections:
            self._anchor_to_sections[key] = []
        if sec_id not in self._anchor_to_sections[key]:
            self._anchor_to_sections[key].append(sec_id)

        # term_to_tier: term → tier (keep the broadest)
        existing_tier = self._term_to_tier.get(key)
        if existing_tier is None:
            self._term_to_tier[key] = tier
        else:
            tier_rank = {"global": 0, "broad": 1,
                         "narrow": 2, "pinpoint": 3}
            if tier_rank.get(tier, 3) < tier_rank.get(
                existing_tier, 3
            ):
                self._term_to_tier[key] = tier

        # section_term_role: {sec_id: {term: role}}
        if role:
            if sec_id not in self._section_term_role:
                self._section_term_role[sec_id] = {}
            self._section_term_role[sec_id][key] = role

    @property
    def term_to_tier(self) -> Dict[str, str]:
        """Lowercased anchor term → discrimination tier.

        global  = 5+ sections (IVT, EVT, AIS, etc.)
        broad   = 3-4 sections (alteplase, ASPECTS, etc.)
        narrow  = 2 sections (SBP, BP, etc.)
        pinpoint = 1 section (labetalol, etc.)

        Built during anchor_to_sections scan.
        """
        if self._term_to_tier is None:
            # Force the scan
            _ = self.anchor_to_sections
        return self._term_to_tier  # type: ignore[return-value]

    @property
    def section_term_role(self) -> Dict[str, Dict[str, str]]:
        """section_id → {term: role} for global/broad terms.

        Role is "primary" (section teaches this topic, has dedicated
        recs/tables) or "mention" (term appears but isn't the focus).
        Used for tie-breaking when all query terms are global.

        Built during anchor_to_sections scan.
        """
        if self._section_term_role is None:
            _ = self.anchor_to_sections
        return self._section_term_role  # type: ignore[return-value]

    @property
    def table_to_section(self) -> Dict[str, str]:
        """Table identifier (e.g. 'Table 3') → section number."""
        if self._table_to_section is None:
            self._table_to_section = {
                "Table 3": "3.2",
                "Table 4": "4.6.1",
                "Table 5": "4.6.1",
                "Table 6": "4.6.1",
                "Table 7": "4.6.2",
                "Table 8": "4.6.1",
                "Table 9": "4.9.1",
            }
        return self._table_to_section

    @property
    def figure_to_section(self) -> Dict[int, str]:
        """Figure number → section number."""
        if self._figure_to_section is None:
            self._figure_to_section = {
                1: "1.0",
                2: "3.2",
                3: "4.7.2",
                4: "4.9.1",
                5: "5.1",
            }
        return self._figure_to_section

    @property
    def term_to_family(self) -> Dict[str, str]:
        """Lowercased anchor term → concept family name.

        Built from synonym_dictionary.json. Each dictionary entry
        (term_id) IS a family. Synonyms within an entry are alternate
        names for the same concept: tPA and alteplase are the same drug,
        SBP and "systolic" are the same measurement.

        Different entries are different concepts, even if they share a
        category: tPA and TNK are both thrombolytics but are different
        drugs and score separately.

        Used for within-section rec scoring (Stage 2): count unique
        families, not raw term hits.
        """
        if self._term_to_family is None:
            self._term_to_family = {}
            data = _load_ref_json("synonym_dictionary.json")
            for term_id, info in data.get("terms", {}).items():
                family = term_id.lower()
                self._term_to_family[family] = family
                full_term = info.get("full_term", "")
                if full_term:
                    self._term_to_family[full_term.lower()] = family
                for syn in info.get("synonyms", []):
                    self._term_to_family[syn.lower()] = family
        return self._term_to_family

    @property
    def term_to_synonyms(self) -> Dict[str, Set[str]]:
        """Lowercased anchor term → set of all synonyms (including itself).

        Built from synonym_dictionary.json. Every term in a synonym group
        maps to the full set: IVT → {ivt, thrombolysis, iv thrombolysis,
        intravenous thrombolysis, lytic, clot buster}.

        Used for match expansion: when the question says "IVT", we also
        search for "thrombolysis", "alteplase", etc. in rec/RSS text.
        """
        if self._term_to_synonyms is None:
            self._term_to_synonyms = {}
            data = _load_ref_json("synonym_dictionary.json")
            for term_id, info in data.get("terms", {}).items():
                group: Set[str] = {term_id.lower()}
                full_term = info.get("full_term", "")
                if full_term:
                    group.add(full_term.lower())
                for syn in info.get("synonyms", []):
                    group.add(syn.lower())

                for member in group:
                    if member in self._term_to_synonyms:
                        self._term_to_synonyms[member] |= group
                    else:
                        self._term_to_synonyms[member] = set(group)
        return self._term_to_synonyms


# ── Scored section ──────────────────────────────────────────────────

@dataclass
class ScoredSection:
    """A section with its tier-weighted score for prioritization."""
    section_id: str
    tier_score: float = 0.0              # Stage 1: tier-weighted score
    matched_term_count: int = 0          # distinct terms matched
    has_discriminating_term: bool = False # matched pinpoint, narrow, or broad
    has_primary_role: bool = False        # at least one term is primary here
    is_topic_primary: bool = False


# ── Retrieved content bundle ─────────────────────────────────────────

@dataclass
class ScoredItem:
    """A content item (rec or RSS) with its relevance score."""
    data: Dict[str, Any]
    score: int = 0


@dataclass
class RetrievedContent:
    """Output of Step 3: everything the presenter needs to answer."""

    raw_query: str
    parsed_query: ParsedQAQuery
    source_types: List[str]
    sections: List[ScoredSection]
    recommendations: List[Dict[str, Any]] = field(default_factory=list)
    synopsis: Dict[str, str] = field(default_factory=dict)
    rss: List[Dict[str, Any]] = field(default_factory=list)
    knowledge_gaps: Dict[str, str] = field(default_factory=dict)
    tables: List[Dict[str, Any]] = field(default_factory=list)
    figures: List[Dict[str, Any]] = field(default_factory=list)

    def to_audit_dict(self) -> Dict[str, Any]:
        """Audit trail entry for this retrieval step."""
        return {
            "step": "step3_retrieval",
            "detail": {
                "source_types": self.source_types,
                "sections": [
                    {"id": s.section_id, "tier_score": s.tier_score,
                     "matched_terms": s.matched_term_count,
                     "has_discriminating_term": s.has_discriminating_term,
                     "is_topic_primary": s.is_topic_primary}
                    for s in self.sections
                ],
                "recommendations_count": len(self.recommendations),
                "rss_count": len(self.rss),
                "synopsis_sections": list(self.synopsis.keys()),
                "knowledge_gaps_sections": list(self.knowledge_gaps.keys()),
                "tables_count": len(self.tables),
                "figures_count": len(self.figures),
            },
        }


# ── Main retrieval function ──────────────────────────────────────────

def retrieve_content(
    parsed: ParsedQAQuery,
    raw_query: str,
    recommendations_store: Dict[str, Any],
    guideline_knowledge: Dict[str, Any],
) -> RetrievedContent:
    """
    Two-stage routing: section selection then content retrieval.

    Stage 1: Score sections by tier-weighted anchor term co-occurrence.
             ALL terms participate. Highest-scoring section wins.
    Stage 2: Filter recs by anchor values (any tier, term + number)
             and narrow/pinpoint terms. Global/broad without values
             don't filter.
    """
    maps = _RoutingMaps.get()

    # ── Lookup 1: intent → source types ──────────────────────────
    source_types = maps.intent_sources.get(
        parsed.intent, ["REC", "SYN"]
    )

    # ── Stage 1: tier-weighted section scoring ───────────────────
    # All anchor terms participate — including globals. They help
    # find the right neighborhood via intersection scoring.
    scored_sections = _score_sections_stage1(parsed, maps)

    section_ids = [s.section_id for s in scored_sections]
    winning_section = section_ids[0] if section_ids else ""

    logger.info(
        "Step 3 Stage 1: intent=%s, sources=%s, topic=%s → "
        "%d sections (top: %s)",
        parsed.intent, source_types, parsed.topic,
        len(scored_sections),
        [(s.section_id, round(s.tier_score, 2), s.matched_term_count)
         for s in scored_sections[:5]],
    )

    # ── Stage 2: build filters from anchor terms + values ────────
    filters = _build_stage2_filters(
        parsed.anchor_terms, maps.term_to_tier,
        maps.term_to_synonyms, winning_section,
        maps.section_term_role,
    )

    term_to_family = maps.term_to_family

    logger.info(
        "Step 3 Stage 2: %d anchor terms → filters: %s",
        len(parsed.anchor_terms or {}),
        _filters_summary(filters),
    )

    # ── Fetch content by source type ─────────────────────────────
    result = RetrievedContent(
        raw_query=raw_query,
        parsed_query=parsed,
        source_types=source_types,
        sections=scored_sections,
    )

    sections_data = guideline_knowledge.get("sections", {})

    if "REC" in source_types:
        result.recommendations = _fetch_recs(
            section_ids, filters,
            term_to_family, recommendations_store,
        )

    # Always fetch synopsis for table/figure sections (their content
    # lives in synopsis, not recs). Also fetch when SYN requested.
    table_figure_ids = [
        s for s in section_ids
        if s.startswith("Table ") or s.startswith("Figure ")
    ]
    if "SYN" in source_types:
        result.synopsis = _fetch_synopsis(section_ids, sections_data)
    elif table_figure_ids:
        result.synopsis = _fetch_synopsis(
            table_figure_ids, sections_data,
        )

    if "RSS" in source_types:
        result.rss = _fetch_rss(
            section_ids, filters,
            term_to_family, sections_data,
        )

    if "KG" in source_types:
        result.knowledge_gaps = _fetch_knowledge_gaps(
            section_ids, sections_data,
        )

    if "TBL" in source_types:
        anchor_lower = {t.lower() for t in (parsed.anchor_terms or {})}
        result.tables = _fetch_tables(section_ids, anchor_lower, maps)

    if "FIG" in source_types:
        result.figures = _fetch_figures(section_ids, maps)

    if "FRONT" in source_types and "SYN" not in source_types:
        result.synopsis = _fetch_synopsis(section_ids, sections_data)

    logger.info(
        "Step 3 retrieved: %d recs, %d rss, %d synopsis, %d kg, "
        "%d tables, %d figures",
        len(result.recommendations), len(result.rss),
        len(result.synopsis), len(result.knowledge_gaps),
        len(result.tables), len(result.figures),
    )

    return result


# ── Stage 1: Tier-weighted section scoring ─────────────────────────

def _score_sections_stage1(
    parsed: ParsedQAQuery,
    maps: _RoutingMaps,
) -> List[ScoredSection]:
    """Score sections by tier-weighted anchor term co-occurrence.

    ALL anchor terms participate — including global terms like IVT.
    Global terms help via intersection: IVT alone → 26 sections,
    but IVT ∩ SBP → section 4.3.

    Scoring:
      - Each term adds its tier weight to sections it appears in
      - Primary-role terms get 3x base weight
      - Co-occurrence bonus: score *= (1 + 0.3 * (N-1)) when N≥2 terms match
      - Topic primary section gets a tiebreaker bonus

    Returns scored sections ordered by (topic_primary, tier_score).
    """
    section_scores: Dict[str, float] = {}
    section_term_counts: Dict[str, int] = {}
    section_has_disc: Dict[str, bool] = {}    # has discriminating term?
    section_has_primary: Dict[str, bool] = {}  # has term with primary role?
    topic_primary: Optional[str] = None

    # Topic → primary section (gives a baseline entry)
    if parsed.topic:
        sec = maps.topic_to_section.get(parsed.topic)
        if sec:
            topic_primary = sec
            section_scores.setdefault(sec, 0.0)
            section_term_counts.setdefault(sec, 0)
            section_has_disc.setdefault(sec, False)
            section_has_primary.setdefault(sec, False)

    # Score each section by anchor term matches
    for term in (parsed.anchor_terms or {}):
        term_lower = term.lower()
        tier = maps.term_to_tier.get(term_lower, "pinpoint")
        base_weight = _TIER_WEIGHTS.get(tier, 2.0)
        is_discriminating = tier in ("pinpoint", "narrow", "broad")

        term_sections = maps.anchor_to_sections.get(term_lower, [])
        for sec in term_sections:
            # Role multiplier: primary topics score 3x
            role = maps.section_term_role.get(sec, {}).get(
                term_lower, "mention"
            )
            multiplier = (
                _PRIMARY_MULTIPLIER if role == "primary" else 1.0
            )
            weight = base_weight * multiplier

            section_scores[sec] = section_scores.get(sec, 0.0) + weight
            section_term_counts[sec] = (
                section_term_counts.get(sec, 0) + 1
            )
            if is_discriminating:
                section_has_disc[sec] = True
            if role == "primary":
                section_has_primary[sec] = True

    # Co-occurrence bonus: reward sections matching multiple terms
    for sec in section_scores:
        matched = section_term_counts[sec]
        if matched >= 2:
            section_scores[sec] *= (
                1.0 + _CO_OCCURRENCE_FACTOR * (matched - 1)
            )

    # Build scored list
    scored: List[ScoredSection] = []
    for sec_id in section_scores:
        scored.append(ScoredSection(
            section_id=sec_id,
            tier_score=section_scores[sec_id],
            matched_term_count=section_term_counts.get(sec_id, 0),
            has_discriminating_term=section_has_disc.get(sec_id, False),
            has_primary_role=section_has_primary.get(sec_id, False),
            is_topic_primary=(sec_id == topic_primary),
        ))

    # Sort: topic primary first, then by descending tier_score
    scored.sort(key=lambda s: (
        not s.is_topic_primary,
        -s.tier_score,
    ))

    return scored


# ── Stage 2: Build filters from anchor terms + values ────────────────

def _expand_term(
    term: str, term_to_synonyms: Dict[str, Set[str]],
) -> Set[str]:
    """Expand a single term with its synonyms from the dictionary."""
    synonyms = term_to_synonyms.get(term)
    return set(synonyms) if synonyms else {term}


def _build_stage2_filters(
    anchor_terms: Optional[Dict[str, Any]],
    term_to_tier: Dict[str, str],
    term_to_synonyms: Dict[str, Set[str]],
    winning_section: str,
    section_term_role: Dict[str, Dict[str, str]],
) -> _Stage2Filters:
    """Build Stage 2 filters from anchor terms.

    Rules:
    - Anchor term with a value/range → value filter (any tier).
      Rec must mention the term AND have a number nearby.
    - Narrow/pinpoint term without a value → term filter.
      Rec must mention the term.
    - Global/broad term without a value → no filter.
      Already did its job in Stage 1 section routing.

    Fallback: if no filters could be built (all global/broad without
    values), use the primary global/broad term for the winning section.
    """
    filters = _Stage2Filters()
    global_broad_no_value: List[str] = []

    for term, value in (anchor_terms or {}).items():
        term_lower = term.lower()
        tier = term_to_tier.get(term_lower, "pinpoint")
        expanded = _expand_term(term_lower, term_to_synonyms)

        if value is not None:
            # Has a value → value filter, regardless of tier
            filters.value_filters.append(expanded)
            filters.all_expanded |= expanded
        elif tier in ("narrow", "pinpoint"):
            # Narrow/pinpoint without value → term filter
            filters.term_filters.append(expanded)
            filters.all_expanded |= expanded
        else:
            # Global/broad without value → track for fallback
            global_broad_no_value.append(term_lower)

    # Fallback: if no filters, pick the best global/broad for the section
    if not filters.has_filters and global_broad_no_value:
        section_roles = section_term_role.get(winning_section, {})
        best = None
        for g in global_broad_no_value:
            if section_roles.get(g) == "primary":
                best = g
                break
        if best is None:
            best = global_broad_no_value[0]
        expanded = _expand_term(best, term_to_synonyms)
        filters.term_filters.append(expanded)
        filters.all_expanded |= expanded

    return filters


def _filters_summary(filters: _Stage2Filters) -> str:
    """Log-friendly summary of active Stage 2 filters."""
    parts = []
    for ts in filters.term_filters:
        sample = sorted(ts)[:3]
        parts.append(f"term({','.join(sample)})")
    for vs in filters.value_filters:
        sample = sorted(vs)[:3]
        parts.append(f"value({','.join(sample)})")
    return ", ".join(parts) if parts else "none"


# ── Stage 2 content matching ──────────────────────────────────────

def _has_number_near(text: str, term: str, window: int = 120) -> bool:
    """Token walk: check if a digit appears within `window` chars of `term`.

    In clinical rec text, a digit near a clinical term is a threshold
    or target value (e.g., "SBP lowered to <185 mm Hg").
    """
    idx = text.find(term)
    if idx < 0:
        return False
    start = max(0, idx - window)
    end = min(len(text), idx + len(term) + window)
    neighborhood = text[start:end]
    return any(c.isdigit() for c in neighborhood)


def _rec_passes_stage2(text: str, filters: _Stage2Filters) -> bool:
    """Check if a rec passes Stage 2 filters.

    A rec passes if it matches at least one filter:
    - Term filter: text mentions any synonym of a narrow/pinpoint term
    - Value filter: text mentions a synonym AND has a number nearby

    If no filters exist, all recs pass.
    """
    if not filters.has_filters:
        return True

    text_lower = text.lower()

    # Check term filters (narrow/pinpoint without values)
    for expanded in filters.term_filters:
        for term in expanded:
            if term in text_lower:
                return True

    # Check value filters (any tier with values)
    for expanded in filters.value_filters:
        for term in expanded:
            if term in text_lower and _has_number_near(text_lower, term):
                return True

    return False


def _score_text(
    text: str,
    all_expanded: Set[str],
    term_to_family: Dict[str, str],
) -> int:
    """Score a text block by unique concept families matched.

    Used for ordering recs/RSS after Stage 2 filtering. Each unique
    concept family found adds 1.
    Higher score = more diverse concept coverage = more relevant.
    """
    if not text:
        return 0
    text_lower = text.lower()

    matched_families: Set[str] = set()
    for term in all_expanded:
        if term in text_lower:
            family = term_to_family.get(term, term)
            matched_families.add(family)

    return len(matched_families)


# ── Content fetchers ─────────────────────────────────────────────

def _fetch_recs(
    sections: List[str],
    filters: _Stage2Filters,
    term_to_family: Dict[str, str],
    recommendations_store: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Fetch recs from matched sections, filtered by Stage 2.

    Stage 2 filters:
    - Values (any tier): rec must mention the term AND have a number
    - Narrow/pinpoint: rec must mention the term
    - Global/broad without values: no filter
    Recs are scored by concept family count and ordered most-relevant-first.
    """
    scored_recs: List[Tuple[int, Dict[str, Any]]] = []
    sections_set = set(sections)

    for rec_id, rec in recommendations_store.items():
        rec_section = rec.get("section", "")
        if rec_section not in sections_set:
            continue

        rec_text = rec.get("text", "")
        if not _rec_passes_stage2(rec_text, filters):
            continue

        score = _score_text(rec_text, filters.all_expanded, term_to_family)
        scored_recs.append((score, rec))

    scored_recs.sort(key=lambda x: -x[0])
    return [rec for _, rec in scored_recs]


def _fetch_synopsis(
    sections: List[str],
    sections_data: Dict[str, Any],
) -> Dict[str, str]:
    """Fetch synopsis text for matched sections.

    Synopsis is section-level narrative — not filtered by anchor terms.
    """
    result = {}
    for sec_id in sections:
        sec = sections_data.get(sec_id, {})
        synopsis = sec.get("synopsis", "")
        if synopsis:
            result[sec_id] = synopsis
    return result


def _fetch_rss(
    sections: List[str],
    filters: _Stage2Filters,
    term_to_family: Dict[str, str],
    sections_data: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Fetch RSS entries filtered by Stage 2.

    Same Stage 2 filtering as recs — values require term + number,
    narrow/pinpoint require term mention.
    """
    scored_entries: List[Tuple[int, Dict[str, Any]]] = []

    for sec_id in sections:
        sec = sections_data.get(sec_id, {})
        for rss_entry in sec.get("rss", []):
            rss_text = rss_entry.get("text", "")
            if not _rec_passes_stage2(rss_text, filters):
                continue

            score = _score_text(
                rss_text, filters.all_expanded, term_to_family,
            )
            scored_entries.append((score, {
                "section": sec_id,
                "sectionTitle": sec.get("sectionTitle", ""),
                "recNumber": rss_entry.get("recNumber", ""),
                "text": rss_text,
            }))

    scored_entries.sort(key=lambda x: -x[0])
    return [entry for _, entry in scored_entries]


def _fetch_knowledge_gaps(
    sections: List[str],
    sections_data: Dict[str, Any],
) -> Dict[str, str]:
    """Fetch knowledge gap text for matched sections."""
    result = {}
    for sec_id in sections:
        sec = sections_data.get(sec_id, {})
        kg = sec.get("knowledgeGaps", "")
        if kg:
            result[sec_id] = kg
    return result


def _fetch_tables(
    sections: List[str],
    anchor_lower: Set[str],
    maps: _RoutingMaps,
) -> List[Dict[str, Any]]:
    """Fetch table data for tables that belong to matched sections."""
    from ...data.loader import load_table_by_number

    sections_set = set(sections)
    results = []
    for table_name, table_section in maps.table_to_section.items():
        if table_section in sections_set:
            parts = table_name.split()
            if len(parts) == 2 and parts[1].isdigit():
                table_num = int(parts[1])
                table_data = load_table_by_number(table_num)
                if table_data:
                    results.append({
                        "table_name": table_name,
                        "table_number": table_num,
                        "section": table_section,
                        "data": table_data,
                    })
    return results


def _fetch_figures(
    sections: List[str],
    maps: _RoutingMaps,
) -> List[Dict[str, Any]]:
    """Fetch figure metadata for figures that belong to matched sections."""
    from ...data.loader import load_figure

    sections_set = set(sections)
    results = []
    for fig_num, fig_section in maps.figure_to_section.items():
        if fig_section in sections_set:
            fig_data = load_figure(fig_num)
            if fig_data:
                results.append({
                    "figure_number": fig_num,
                    "section": fig_section,
                    "data": fig_data,
                })
    return results
