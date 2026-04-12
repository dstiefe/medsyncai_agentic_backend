# ─── v4 (Q&A v4 namespace) ─────────────────────────────────────────────
# This file lives under agents/qa_v4/ and is the active v4 copy of the
# Guideline Q&A pipeline. The previous location agents/qa_v3/ has been
# archived to agents/_archive_qa_v3/ and is no longer imported anywhere.
# v4 changes: unified Step 1 pipeline — 38 intents from
# intent_content_source_map.json, flexible clinical_variables dict,
# anchor_terms, values_verified, rescoped clarification.
# ───────────────────────────────────────────────────────────────────────
"""
JSON contracts between Q&A pipeline agents.

Every agent receives and returns one of these typed dicts.
This is the single source of truth for inter-agent data shapes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional


# ── Intent Agent Output ─────────────────────────────────────────────

@dataclass
class IntentResult:
    """Output of the Intent Agent — everything downstream agents need."""

    question: str
    question_type: str                          # "recommendation" | "evidence" | "knowledge_gap"
    search_terms: List[str] = field(default_factory=list)
    section_refs: List[str] = field(default_factory=list)       # explicit "Section X.X" refs
    topic_sections: List[str] = field(default_factory=list)     # inferred from TOPIC_SECTION_MAP
    topic_sections_source: str = ""                             # "topic_map" | "concept_index" | ""
    suppressed_sections: List[str] = field(default_factory=list)
    numeric_context: Dict[str, Any] = field(default_factory=dict)
    clinical_vars: Dict[str, Any] = field(default_factory=dict)
    is_general_question: bool = False
    is_evidence_question: bool = False
    is_contraindication_question: bool = False
    contraindication_tier: Optional[str] = None  # "Absolute" | "Relative" | "Benefit May Exceed Risk"
    context_summary: str = ""                    # patient context string for display
    topic: Optional[str] = None                  # LLM-classified topic (e.g. "Post-Treatment Management")


# ── Recommendation Agent Output ─────────────────────────────────────

@dataclass
class ScoredRecommendation:
    """A single recommendation with its relevance score."""

    rec_id: str
    section: str
    section_title: str
    rec_number: str
    cor: str
    loe: str
    text: str                   # verbatim guideline text — NEVER modified
    score: int
    source: str = "deterministic"   # "deterministic" | "semantic" | "both"


@dataclass
class RecommendationResult:
    """Output of the Recommendation Agent."""

    scored_recs: List[ScoredRecommendation] = field(default_factory=list)
    search_method: str = "deterministic"    # "deterministic" | "semantic" | "hybrid" | "section_route"


# ── Supportive Text Agent Output ────────────────────────────────────

@dataclass
class SupportiveTextEntry:
    """A single RSS entry from guideline_knowledge.json."""

    section: str
    section_title: str
    rec_number: str
    text: str               # raw RSS text — Assembly Agent may summarize this
    entry_type: str = "rss"  # "rss" | "synopsis"


@dataclass
class SupportiveTextResult:
    """Output of the Supportive Text Agent."""

    entries: List[SupportiveTextEntry] = field(default_factory=list)
    has_content: bool = False


# ── Knowledge Gap Agent Output ──────────────────────────────────────

@dataclass
class KnowledgeGapEntry:
    """A single knowledge gap entry."""

    section: str
    section_title: str
    text: str               # raw KG text — Assembly Agent may summarize this


@dataclass
class KnowledgeGapResult:
    """Output of the Knowledge Gap Agent."""

    entries: List[KnowledgeGapEntry] = field(default_factory=list)
    has_gaps: bool = False
    deterministic_response: Optional[str] = None  # pre-built "no gaps" response


# ── Assembly Agent Output ───────────────────────────────────────────

@dataclass
class ClarificationOption:
    """One option in a clarification prompt."""

    label: str          # e.g. "A"
    description: str    # e.g. "Standard window IVT (0-4.5 hours from onset)"
    section: str
    rec_id: str
    cor: str
    loe: str


@dataclass
class AuditEntry:
    """One step in the audit trail."""

    step: str           # e.g. "intent_classification", "rec_search", "scope_gate"
    detail: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AssemblyResult:
    """Final output of the Assembly Agent — the response to the user."""

    status: str                     # "complete" | "needs_clarification" | "out_of_scope"
    answer: str                     # formatted answer text
    summary: str                    # concise summary
    citations: List[str] = field(default_factory=list)
    related_sections: List[str] = field(default_factory=list)
    referenced_trials: List[str] = field(default_factory=list)

    # Clarification (populated when status == "needs_clarification")
    clarification_options: List[ClarificationOption] = field(default_factory=list)

    # Audit trail
    audit_trail: List[AuditEntry] = field(default_factory=list)

    # CMI matching metadata (populated when CMI path was used)
    cmi_used: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert to the dict shape expected by engine.py _build_return()."""
        result = {
            "answer": self.answer,
            "summary": self.summary,
            "citations": self.citations,
            "relatedSections": self.related_sections,
            "referencedTrials": self.referenced_trials,
        }
        if self.status == "needs_clarification":
            result["needsClarification"] = True
            result["clarificationOptions"] = [
                {
                    "label": opt.label,
                    "description": opt.description,
                    "section": opt.section,
                    "recId": opt.rec_id,
                    "cor": opt.cor,
                    "loe": opt.loe,
                }
                for opt in self.clarification_options
            ]
        if self.audit_trail:
            result["auditTrail"] = [
                {"step": e.step, "detail": e.detail}
                for e in self.audit_trail
            ]
        if self.cmi_used:
            result["cmiUsed"] = True
        return result


# ── CMI Query Parsing Output ──────────────────────────────────────

@dataclass
class RangeFilter:
    """Numeric range with optional min/max bounds."""

    min: Optional[float] = None
    max: Optional[float] = None

    def is_set(self) -> bool:
        return self.min is not None or self.max is not None


# Mapping from clinical_variables keys to CMI variable names
_KEY_TO_CMI: Dict[str, str] = {
    "age": "age_range",
    "nihss": "nihss_range",
    "vessel_occlusion": "vessel_occlusion",
    "time_from_lkw_hours": "time_window_hours",
    "aspects": "aspects_range",
    "pc_aspects": "pc_aspects_range",
    "premorbid_mrs": "premorbid_mrs",
    "core_volume_ml": "core_volume_ml",
    "mismatch_ratio": "mismatch_ratio",
    "sbp": "sbp",
    "dbp": "dbp",
    "inr": "inr",
    "platelets": "platelets",
    "glucose": "glucose",
}

# Keys that produce {min, max} range dicts for CMI compatibility
_RANGE_KEYS = {"age", "nihss", "time_from_lkw_hours", "aspects", "pc_aspects"}


@dataclass
class ParsedQAQuery:
    """
    Output of LLM-based query parsing for Guideline Q&A (v4).

    Step 1 output: the LLM understands the question and produces
    intent, topic, clinical variables, anchor terms, and a semantic
    summary. clinical_variables is a flexible dict — the LLM populates
    whatever is relevant from the question. Empty dict when no patient data.

    This is the primary object that flows through the entire pipeline.
    """

    # ── Classification (Step 1 — all LLM) ─────────────────────────
    intent: Optional[str] = None                   # one of 38 intents from intent_content_source_map.json
    topic: Optional[str] = None                    # one of 38 topics from guideline_topic_map.json
    qualifier: Optional[str] = None                # subtopic qualifier
    question_summary: Optional[str] = None         # plain-language semantic summary

    # ── Clarification (understanding-level only) ──────────────────
    clarification: Optional[str] = None            # clarifying question when understanding fails
    clarification_reason: Optional[str] = None     # "off_topic" | "vague_with_anchor" | "vague_no_anchor" | "topic_ambiguity"

    # ── Clinical variables (flexible dict) ────────────────────────
    clinical_variables: Dict[str, Any] = field(default_factory=dict)

    # ── Anchor terms (grounded in reference vocabulary) ───────────
    anchor_terms: List[str] = field(default_factory=list)

    # ── Confidence and verification ───────────────────────────────
    is_criterion_specific: bool = False             # True when patient scenario present
    extraction_confidence: float = 0.0
    values_verified: bool = False                   # True when all extracted values cross-checked

    # ── Backward Compatibility (orchestrator / assembly / CMI) ─────
    # These properties derive legacy fields from v4 fields so
    # downstream code (orchestrator, assembly_agent, content_dispatch,
    # CMI matcher) continues to work without modification.
    # Remove once downstream is updated to read v4 fields directly.

    # Intents whose primary purpose is surfacing evidence (RSS)
    _EVIDENCE_INTENTS = frozenset({
        "evidence_for_recommendation", "trial_specific_data",
        "evidence_with_recommendation", "evidence_with_confidence",
        "evidence_vs_gaps",
    })
    # Intents whose primary purpose is knowledge gaps (KG)
    _KG_INTENTS = frozenset({
        "knowledge_gap", "current_understanding_and_gaps",
        "rationale_with_uncertainty",
    })

    @property
    def question_type(self) -> str:
        """Derive legacy question_type from v4 intent.

        Maps the 38-intent enum back to the 3-value question_type
        that orchestrator.py, assembly_agent.py, and content_dispatch.py
        still read. Temporary bridge until Step 2 rewires content dispatch.
        """
        if not self.intent:
            return "recommendation"
        if self.intent in self._EVIDENCE_INTENTS:
            return "evidence"
        if self.intent in self._KG_INTENTS:
            return "knowledge_gap"
        return "recommendation"

    @property
    def search_keywords(self) -> Optional[List[str]]:
        """Derive legacy search_keywords from v4 anchor_terms.

        orchestrator.py reads search_keywords for logging and fallback
        search. anchor_terms serves the same purpose in v4.
        """
        return self.anchor_terms if self.anchor_terms else None

    def _compat_range(self, key: str) -> Optional[Dict[str, Any]]:
        """Build a {min, max} range dict from a scalar clinical variable."""
        v = self.clinical_variables.get(key)
        if v is None:
            return None
        if isinstance(v, dict):
            return v  # already a range like {"min": 3, "max": 5}
        return {"min": v, "max": v}

    @property
    def age(self) -> Optional[int]:
        return self.clinical_variables.get("age")

    @property
    def nihss(self) -> Optional[int]:
        return self.clinical_variables.get("nihss")

    @property
    def vessel_occlusion(self) -> Optional[Any]:
        return self.clinical_variables.get("vessel_occlusion")

    @property
    def time_from_lkw_hours(self) -> Optional[float]:
        return self.clinical_variables.get("time_from_lkw_hours")

    @property
    def aspects(self) -> Optional[int]:
        return self.clinical_variables.get("aspects")

    @property
    def pc_aspects(self) -> Optional[int]:
        return self.clinical_variables.get("pc_aspects")

    @property
    def premorbid_mrs(self) -> Optional[int]:
        return self.clinical_variables.get("premorbid_mrs")

    @property
    def core_volume_ml(self) -> Optional[float]:
        return self.clinical_variables.get("core_volume_ml")

    @property
    def mismatch_ratio(self) -> Optional[float]:
        return self.clinical_variables.get("mismatch_ratio")

    @property
    def sbp(self) -> Optional[int]:
        return self.clinical_variables.get("sbp")

    @property
    def dbp(self) -> Optional[int]:
        return self.clinical_variables.get("dbp")

    @property
    def inr(self) -> Optional[float]:
        return self.clinical_variables.get("inr")

    @property
    def platelets(self) -> Optional[int]:
        return self.clinical_variables.get("platelets")

    @property
    def glucose(self) -> Optional[int]:
        return self.clinical_variables.get("glucose")

    @property
    def intervention(self) -> Optional[str]:
        """Derive intervention from topic for CMI compatibility."""
        topic = (self.topic or "").lower()
        if any(t in topic for t in ("ivt", "thrombol", "alteplase", "tenecteplase")):
            return "IVT"
        if any(t in topic for t in ("evt", "thrombectomy", "endovascular")):
            return "EVT"
        return None

    @property
    def circulation(self) -> Optional[str]:
        """Derive circulation from qualifier for CMI compatibility."""
        qualifier = (self.qualifier or "").lower()
        if "posterior" in qualifier or "basilar" in qualifier:
            return "posterior"
        if "anterior" in qualifier:
            return "anterior"
        return None

    @property
    def age_range(self) -> Optional[Dict[str, Any]]:
        return self._compat_range("age")

    @property
    def nihss_range(self) -> Optional[Dict[str, Any]]:
        return self._compat_range("nihss")

    @property
    def time_window_hours(self) -> Optional[Dict[str, Any]]:
        return self._compat_range("time_from_lkw_hours")

    @property
    def aspects_range(self) -> Optional[Dict[str, Any]]:
        return self._compat_range("aspects")

    @property
    def pc_aspects_range(self) -> Optional[Dict[str, Any]]:
        return self._compat_range("pc_aspects")

    def has_clinical_variables(self) -> bool:
        """Return True if any clinical variable is populated."""
        return bool(self.clinical_variables)

    def get_scenario_variables(self) -> List[str]:
        """Return list of CMI variable names from clinical_variables."""
        variables = []
        for key in self.clinical_variables:
            cmi_name = _KEY_TO_CMI.get(key, key)
            if cmi_name not in variables:
                variables.append(cmi_name)
        if self.intervention:
            variables.append("intervention")
        if self.circulation:
            variables.append("circulation")
        return variables


# ── CMI Matched Recommendation ────────────────────────────────────

@dataclass
class CMIMatchedRecommendation:
    """A recommendation matched via CMI tiering — analog of MatchedTrial."""

    rec_id: str
    tier: int                   # 1-4 (lower = better match)
    scope_index: float          # 0.0-1.0 (fraction of query vars addressed)
    tier_reason: str = ""
    match_details: Dict[str, Any] = field(default_factory=dict)
    rec_data: Dict[str, Any] = field(default_factory=dict)   # full recommendation dict
