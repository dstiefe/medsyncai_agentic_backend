"""
Pydantic models for the Journal Search Engine.

ParsedQuery: Structured variables extracted from user's clinical question.
MatchedTrial: A trial matched against the query with tier assignment.
SearchResult: Complete search result returned by the engine.
ClarificationMenu: Lettered/numbered options for narrowing a broad query.
ComparisonQuery: Two ParsedQueries for side-by-side comparison.
"""

from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Optional, List, Literal


class RangeFilter(BaseModel):
    """A numeric range filter with optional min/max bounds."""
    min: Optional[float] = None
    max: Optional[float] = None

    def is_set(self) -> bool:
        return self.min is not None or self.max is not None


class TimeWindowFilter(BaseModel):
    """Time window filter with reference point."""
    min: Optional[float] = None
    max: Optional[float] = None
    reference: Optional[str] = None  # "onset", "LKW", "recognition"

    def is_set(self) -> bool:
        return self.min is not None or self.max is not None


class ParsedQuery(BaseModel):
    """Structured query variables extracted from user's clinical question."""

    # ── Ranges (mirror trial inclusion_criteria fields) ──
    aspects_range: Optional[RangeFilter] = None
    pc_aspects_range: Optional[RangeFilter] = None
    nihss_range: Optional[RangeFilter] = None
    age_range: Optional[RangeFilter] = None
    time_window_hours: Optional[TimeWindowFilter] = None
    core_volume_ml: Optional[RangeFilter] = None
    mismatch_ratio: Optional[RangeFilter] = None
    premorbid_mrs: Optional[RangeFilter] = None

    # ── List filters ──
    vessel_occlusion: Optional[List[str]] = None
    imaging_required: Optional[List[str]] = None

    # ── Intervention & study filters ──
    intervention: Optional[str] = None
    comparator: Optional[str] = None
    study_type: Optional[str] = None
    circulation: Optional[str] = None

    # ── Outcome focus (e.g., "sICH", "mortality", "functional independence") ──
    outcome_focus: Optional[str] = None

    # ── Original question ──
    clinical_question: str = ""

    # ── Clarification handling ──
    needs_clarification: bool = False
    clarification_question: Optional[str] = None
    extraction_confidence: float = 0.0


class ComparisonQuery(BaseModel):
    """A comparison question that requires two separate CMI searches."""
    is_comparison: bool = False
    query_a: Optional[ParsedQuery] = None
    query_b: Optional[ParsedQuery] = None
    comparison_label_a: str = ""  # e.g., "ASPECTS 3-5"
    comparison_label_b: str = ""  # e.g., "ASPECTS ≥6"
    comparison_variable: str = ""  # e.g., "aspects_range"
    clinical_question: str = ""


class ClarificationOption(BaseModel):
    """A single option in a clarification menu."""
    key: str  # "A", "B", "1", "2", etc.
    label: str  # "Anterior circulation"
    variable: str  # "circulation"
    value: dict  # {"circulation": "anterior"} — the update to apply


class ClarificationMenu(BaseModel):
    """A set of clarification options presented to the user."""
    message: str  # "Your query matches 28 trials. To narrow down:"
    groups: List[ClarificationGroup] = Field(default_factory=list)
    partial_query: ParsedQuery  # The query so far (before clarification)
    tier1_count: int = 0  # How many Tier 1 matches before clarification


class ClarificationGroup(BaseModel):
    """A group of related clarification options (e.g., circulation choices)."""
    label: str  # "Circulation?"
    options: List[ClarificationOption] = Field(default_factory=list)


class MatchedTrial(BaseModel):
    """A trial matched against the query with tier assignment."""
    trial_id: str
    tier: Literal[1, 2, 3, 4]
    tier_reason: str
    match_details: dict = Field(default_factory=dict)
    metadata: dict = Field(default_factory=dict)
    intervention: dict = Field(default_factory=dict)
    results: dict = Field(default_factory=dict)
    methods_text: str = ""
    results_text: str = ""


class SearchResult(BaseModel):
    """Complete search result returned by the engine."""
    query: ParsedQuery
    matched_trials: List[MatchedTrial] = Field(default_factory=list)
    tier_counts: dict = Field(default_factory=dict)
    synthesis: str = ""
    total_trials_searched: int = 0
    figures: List[dict] = Field(default_factory=list)  # Relevant figure references


class ComparisonResult(BaseModel):
    """Side-by-side comparison result."""
    label_a: str
    label_b: str
    result_a: SearchResult
    result_b: SearchResult
    synthesis: str = ""
