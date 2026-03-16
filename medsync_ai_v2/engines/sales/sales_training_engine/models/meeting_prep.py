"""
Meeting Prep models for MedSync AI Sales Simulation Engine.

Models for generating pre-call intelligence briefs and managing meeting prep sessions.
"""

from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class HospitalType(str, Enum):
    """Types of hospital/institution."""

    ACADEMIC = "academic"
    COMMUNITY = "community"
    RURAL = "rural"
    PRIVATE_PRACTICE = "private_practice"


class PhysicianSpecialty(str, Enum):
    """Physician specialty options."""

    NEUROINTERVENTIONAL_SURGERY = "neurointerventional_surgery"
    NEUROINTERVENTIONAL_RADIOLOGY = "neurointerventional_radiology"
    NEUROSURGERY = "neurosurgery"
    STROKE_NEUROLOGY = "stroke_neurology"


# --- Request Models ---


class MeetingPrepRequest(BaseModel):
    """Request model for generating a meeting prep intelligence brief."""

    # Required fields
    physician_name: str = Field(
        ..., description="Name of the physician being visited", min_length=2
    )
    physician_device_ids: List[int] = Field(
        ...,
        description="Device IDs the physician currently uses",
        min_length=1,
    )
    physician_specialty: PhysicianSpecialty = Field(
        ..., description="Physician's medical specialty"
    )
    hospital_type: HospitalType = Field(
        ..., description="Type of hospital/institution"
    )
    rep_company: str = Field(
        ..., description="Sales rep's company name", min_length=2
    )

    # Optional fields
    annual_case_volume: Optional[int] = Field(
        None, description="Physician's estimated annual stroke cases", ge=1, le=500
    )
    products_to_pitch: Optional[List[int]] = Field(
        None, description="Device IDs the rep wants to pitch"
    )
    known_objections: Optional[str] = Field(
        None,
        description="Objections raised in previous meetings (free text)",
    )
    meeting_context: Optional[str] = Field(
        None,
        description="Context: first call, follow-up, contract renewal, trial request, etc.",
    )

    class Config:
        json_schema_extra = {
            "example": {
                "physician_name": "Dr. Patel",
                "physician_device_ids": [45, 48, 51, 60],
                "physician_specialty": "neurointerventional_radiology",
                "hospital_type": "community",
                "rep_company": "Stryker",
                "annual_case_volume": 80,
                "products_to_pitch": [10, 15],
                "known_objections": "Happy with current Penumbra setup, concerned about switching costs",
                "meeting_context": "Second meeting after product demo at conference",
            }
        }


# --- Brief Output Models ---


class DeviceSpecComparison(BaseModel):
    """Side-by-side spec comparison between two devices."""

    physician_device_id: int
    physician_device_name: str
    physician_manufacturer: str
    rep_device_id: int
    rep_device_name: str
    rep_manufacturer: str
    spec_advantages: List[str] = Field(
        default_factory=list, description="Spec advantages of rep's device"
    )
    spec_disadvantages: List[str] = Field(
        default_factory=list, description="Spec disadvantages of rep's device"
    )
    compatibility_note: Optional[str] = Field(
        None, description="Cross-manufacturer compatibility info"
    )


class CompatibilityInsight(BaseModel):
    """Cross-manufacturer compatibility finding."""

    rep_device_id: int
    rep_device_name: str
    physician_device_id: int
    physician_device_name: str
    compatible: bool
    fit_type: Optional[str] = None
    clearance_mm: Optional[float] = None
    explanation: str


class TalkingPoint(BaseModel):
    """An evidence-backed talking point for the meeting."""

    headline: str = Field(..., description="Short headline (1 line)")
    detail: str = Field(..., description="Supporting detail (2-3 sentences)")
    evidence_type: str = Field(
        ..., description="Type: clinical_data, spec_advantage, workflow, cost"
    )
    citations: List[str] = Field(
        default_factory=list,
        description="Source citations ([SPECS:id=X], [IFU:file], etc.)",
    )


class ObjectionResponse(BaseModel):
    """A predicted objection with recommended response."""

    objection: str = Field(..., description="The physician's likely objection")
    likelihood: str = Field(
        ..., description="high, medium, or low"
    )
    recommended_response: str = Field(
        ..., description="How to respond (2-3 sentences)"
    )
    supporting_data: List[str] = Field(
        default_factory=list, description="Data points to cite"
    )


class MigrationStep(BaseModel):
    """A step in the recommended device migration path."""

    order: int = Field(..., description="Step order (1, 2, 3...)")
    action: str = Field(
        ..., description="What to introduce or change"
    )
    rationale: str = Field(
        ..., description="Why this step comes in this order"
    )
    disruption_level: str = Field(
        ..., description="low, medium, or high disruption to physician's workflow"
    )


class IntelligenceBrief(BaseModel):
    """The complete pre-call intelligence brief."""

    brief_id: str = Field(..., description="Unique brief identifier")
    created_at: datetime = Field(
        default_factory=datetime.utcnow, description="When brief was generated"
    )

    # Section A: Physician Profile Summary
    physician_name: str
    physician_specialty: str
    hospital_type: str
    annual_case_volume: Optional[int] = None
    current_stack_summary: List[Dict] = Field(
        default_factory=list,
        description="Physician's current devices with specs",
    )
    inferred_approach: str = Field(
        default="",
        description="Inferred clinical approach (aspiration-first, stent-retriever-first, combined)",
    )

    # Section B: Competitive Analysis
    device_comparisons: List[DeviceSpecComparison] = Field(
        default_factory=list,
        description="Side-by-side device comparisons",
    )
    competitive_claims: List[Dict] = Field(
        default_factory=list,
        description="Relevant marketing claims from both sides",
    )

    # Section C: Compatibility Intelligence
    compatibility_insights: List[CompatibilityInsight] = Field(
        default_factory=list,
        description="Cross-manufacturer compatibility findings",
    )
    migration_path: List[MigrationStep] = Field(
        default_factory=list,
        description="Recommended device migration order",
    )

    # Section D: Talking Points
    talking_points: List[TalkingPoint] = Field(
        default_factory=list,
        description="Evidence-backed talking points",
    )

    # Section E: Objection Playbook
    objection_playbook: List[ObjectionResponse] = Field(
        default_factory=list,
        description="Predicted objections with responses",
    )

    # Metadata
    meeting_context: Optional[str] = None
    rep_company: str = ""
    data_sources_used: List[str] = Field(
        default_factory=list,
        description="Which data sources contributed to this brief",
    )


class MeetingPrepSession(BaseModel):
    """Tracks a meeting prep session (brief + optional rehearsal)."""

    prep_id: str = Field(..., description="Unique prep session ID")
    brief: IntelligenceBrief = Field(..., description="Generated intelligence brief")
    request: MeetingPrepRequest = Field(..., description="Original request")
    rehearsal_session_id: Optional[str] = Field(
        None, description="Linked simulation session ID for rehearsal"
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)
    status: str = Field(default="brief_generated", description="Status: brief_generated, rehearsing, completed")
