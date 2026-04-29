"""
Physician profile models for MedSync AI Sales Simulation Engine.

Models representing simulated physicians with their preferences, experiences, and decision patterns.
"""

from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class DeviceStackEntry(BaseModel):
    """Represents a device in a physician's procedural stack."""

    role: str = Field(..., description="Device role in procedure (e.g., guide, catheter)")
    device_name: str = Field(..., description="Full device name")
    device_id: Optional[int] = Field(None, description="Unique device identifier")
    manufacturer: str = Field(..., description="Device manufacturer")


class PhysicianProfile(BaseModel):
    """Represents a simulated physician with clinical characteristics and preferences."""

    id: str = Field(..., description="Unique physician identifier")
    name: str = Field(..., description="Physician name")
    specialty: str = Field(
        ..., description="Medical specialty (e.g., neurovascular, stroke)"
    )
    institution: str = Field(..., description="Institution/hospital name")
    institution_type: str = Field(
        ..., description="Institution type: academic or community"
    )
    case_volume: int = Field(..., description="Annual case volume")
    case_volume_tier: str = Field(
        ..., description="Case volume tier: low, medium, or high"
    )
    years_experience: int = Field(..., description="Years of clinical experience")
    technique_preference: str = Field(
        ...,
        description="Primary technique preference: aspiration, stent_retriever, or combined",
    )
    current_device_stack: List[DeviceStackEntry] = Field(
        ..., description="Current procedural device stack"
    )
    clinical_priorities: List[str] = Field(
        ..., description="Clinical priorities and concerns"
    )
    personality_traits: Dict[str, float] = Field(
        ..., description="Personality trait scores (0-1)"
    )
    objection_patterns: List[str] = Field(
        ..., description="Common objection patterns"
    )
    decision_style: str = Field(
        ..., description="Decision-making style (e.g., data-driven, experience-based)"
    )

    class Config:
        """Pydantic config."""

        json_schema_extra = {
            "example": {
                "id": "phys_001",
                "name": "Dr. Sarah Chen",
                "specialty": "neurovascular",
                "institution": "Stanford Medical Center",
                "institution_type": "academic",
                "case_volume": 150,
                "case_volume_tier": "high",
                "years_experience": 12,
                "technique_preference": "combined",
                "current_device_stack": [
                    {
                        "role": "guide_catheter",
                        "device_name": "Example Guide",
                        "device_id": 1,
                        "manufacturer": "Example Corp",
                    }
                ],
                "clinical_priorities": ["safety", "speed", "cost"],
                "personality_traits": {"confidence": 0.85, "risk_aversion": 0.4},
                "objection_patterns": ["cost_concern", "brand_loyalty"],
                "decision_style": "data-driven",
            }
        }
