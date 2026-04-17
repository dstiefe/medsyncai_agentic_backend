"""
qa_v6 data contracts.

One object per pipeline stage:
  Step 1 LLM parse    → ParsedQAQuery
  Step 3 retrieval    → RetrievedContent
  Step 4 presentation → AssemblyResult (final user-facing output)

No dead fields. If it's not populated at runtime, it's not here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ── Step 1: Parsed Query ──────────────────────────────────────────

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


@dataclass
class ParsedQAQuery:
    """Output of Step 1 LLM query parsing.

    anchor_terms maps clinical concept → value or None.
    Values are literal numbers or {min, max} ranges when the
    clinician supplied quantitative input.
    """

    intent: Optional[str] = None
    topic: Optional[str] = None
    qualifier: Optional[str] = None
    question_summary: Optional[str] = None

    clarification: Optional[str] = None
    clarification_reason: Optional[str] = None

    anchor_terms: Dict[str, Any] = field(default_factory=dict)

    is_criterion_specific: bool = False
    extraction_confidence: float = 0.0
    values_verified: bool = False

    # ── Value access helpers (used by CMI recommendation matcher) ──

    @property
    def anchor_values(self) -> Dict[str, Any]:
        return {
            k.lower(): v for k, v in self.anchor_terms.items()
            if v is not None
        }

    def _value(self, key: str) -> Any:
        v = self.anchor_terms.get(key)
        if v is not None:
            return v
        for k, val in self.anchor_terms.items():
            if k.lower() == key.lower() and val is not None:
                return val
        return None

    def _range(self, key: str) -> Optional[Dict[str, Any]]:
        v = self._value(key)
        if v is None:
            return None
        if isinstance(v, dict):
            return v
        return {"min": v, "max": v}

    @property
    def age(self) -> Optional[int]:
        return self._value("age")

    @property
    def nihss(self) -> Optional[int]:
        return self._value("nihss")

    @property
    def vessel_occlusion(self) -> Optional[Any]:
        return self._value("vessel_occlusion")

    @property
    def aspects(self) -> Optional[int]:
        return self._value("aspects")

    @property
    def sbp(self) -> Optional[int]:
        return self._value("sbp")

    @property
    def inr(self) -> Optional[float]:
        return self._value("inr")

    @property
    def platelets(self) -> Optional[int]:
        return self._value("platelets")

    @property
    def glucose(self) -> Optional[int]:
        return self._value("glucose")

    @property
    def premorbid_mrs(self) -> Optional[int]:
        return self._value("premorbid_mrs")

    @property
    def core_volume_ml(self) -> Optional[float]:
        return self._value("core_volume_ml")

    @property
    def mismatch_ratio(self) -> Optional[float]:
        return self._value("mismatch_ratio")

    @property
    def dbp(self) -> Optional[int]:
        return self._value("dbp")

    @property
    def pc_aspects(self) -> Optional[int]:
        return self._value("pc_aspects")

    @property
    def age_range(self) -> Optional[Dict[str, Any]]:
        return self._range("age")

    @property
    def nihss_range(self) -> Optional[Dict[str, Any]]:
        return self._range("nihss")

    @property
    def time_window_hours(self) -> Optional[Dict[str, Any]]:
        return self._range("time_from_lkw_hours")

    @property
    def aspects_range(self) -> Optional[Dict[str, Any]]:
        return self._range("aspects")

    @property
    def pc_aspects_range(self) -> Optional[Dict[str, Any]]:
        return self._range("pc_aspects")

    @property
    def intervention(self) -> Optional[str]:
        topic = (self.topic or "").lower()
        if any(t in topic for t in ("ivt", "thrombol", "alteplase",
                                     "tenecteplase")):
            return "IVT"
        if any(t in topic for t in ("evt", "thrombectomy", "endovascular")):
            return "EVT"
        return None

    @property
    def circulation(self) -> Optional[str]:
        qualifier = (self.qualifier or "").lower()
        if "posterior" in qualifier or "basilar" in qualifier:
            return "posterior"
        if "anterior" in qualifier:
            return "anterior"
        return None

    def has_anchor_values(self) -> bool:
        return any(v is not None for v in self.anchor_terms.values())

    def get_scenario_variables(self) -> List[str]:
        variables = []
        for key, val in self.anchor_terms.items():
            if val is not None:
                cmi_name = _KEY_TO_CMI.get(key, key)
                if cmi_name not in variables:
                    variables.append(cmi_name)
        if self.intervention:
            variables.append("intervention")
        if self.circulation:
            variables.append("circulation")
        return variables


# ── CMI Matched Recommendation (patient-scenario matching) ────────

@dataclass
class CMIMatchedRecommendation:
    """A recommendation matched via CMI tiering — analog of MatchedTrial.

    Used only when a patient scenario is present (age, NIHSS, vessel,
    LKW, etc.). Pure rec lookups bypass CMI.
    """

    rec_id: str
    tier: int                   # 1-4 (lower = better match)
    scope_index: float          # 0.0-1.0 (fraction of query vars addressed)
    tier_reason: str = ""
    match_details: Dict[str, Any] = field(default_factory=dict)
    rec_data: Dict[str, Any] = field(default_factory=dict)


# ── Step 3: Retrieved Content ─────────────────────────────────────

@dataclass
class ScoredAtom:
    """One atom with its score and component breakdown.

    Keeps the ranking rationale for audit/debug.
    """

    atom: Dict[str, Any]
    score: float
    breakdown: Dict[str, float] = field(default_factory=dict)


@dataclass
class RetrievedContent:
    """Output of Step 3 retrieval, grouped by atom type for the presenter.

    All content is derived from one unified scored pass over the atom
    index. Different atom types drive different parts of the rendered
    output.
    """

    raw_query: str
    parsed_query: ParsedQAQuery
    intent: str

    # Content grouped by atom_type for the presenter
    recommendations: List[Dict[str, Any]] = field(default_factory=list)
    rss: List[Dict[str, Any]] = field(default_factory=list)
    synopsis: Dict[str, str] = field(default_factory=dict)
    knowledge_gaps: Dict[str, str] = field(default_factory=dict)
    tables: List[Dict[str, Any]] = field(default_factory=list)
    figures: List[Dict[str, Any]] = field(default_factory=list)

    # Concept categories represented in the retrieved content
    # (used for presentation grouping and clarification axes)
    concept_categories: List[str] = field(default_factory=list)

    # Ambiguity signal: if >MAX_RECS cleared threshold and cluster
    # tightly, present the clarification options instead of answering.
    needs_clarification: bool = False
    clarification_options: List[Dict[str, Any]] = field(default_factory=list)


# ── Step 4: Assembly Result ───────────────────────────────────────

@dataclass
class AuditEntry:
    step: str
    detail: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ClarificationOption:
    label: str
    description: str
    section: str
    rec_id: str
    cor: str
    loe: str


@dataclass
class AssemblyResult:
    """Final user-facing output."""

    status: str  # "complete" | "needs_clarification" | "out_of_scope"
    answer: str
    summary: str
    citations: List[str] = field(default_factory=list)
    related_sections: List[str] = field(default_factory=list)
    referenced_trials: List[str] = field(default_factory=list)
    clarification_options: List[ClarificationOption] = field(default_factory=list)
    audit_trail: List[AuditEntry] = field(default_factory=list)
    cmi_used: bool = False

    def to_dict(self) -> Dict[str, Any]:
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
