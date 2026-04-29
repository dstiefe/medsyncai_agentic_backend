"""
Scoring models for MedSync AI Sales Simulation Engine.

Models for evaluating simulation performance across multiple dimensions.
"""

from typing import Dict, List

from pydantic import BaseModel, Field


# Define scoring dimensions with metadata
SCORING_DIMENSIONS = {
    "clinical_accuracy": {
        "name": "Clinical Accuracy",
        "description": "Accuracy of clinical information and device specifications presented",
        "weight": 1 / 7,
        "deterministic": True,
        "rubric": "0=major errors, 1=minor errors, 2=acceptable, 3=excellent accuracy",
    },
    "spec_accuracy": {
        "name": "Specification Accuracy",
        "description": "Accuracy of technical specifications and compatibility claims",
        "weight": 1 / 7,
        "deterministic": True,
        "rubric": "0=major errors, 1=minor errors, 2=acceptable, 3=excellent accuracy",
    },
    "regulatory_compliance": {
        "name": "Regulatory Compliance",
        "description": "Adherence to FDA regulations and safety guidelines",
        "weight": 1 / 7,
        "deterministic": True,
        "rubric": "0=violations, 1=minor issues, 2=compliant, 3=exemplary",
    },
    "competitive_knowledge": {
        "name": "Competitive Knowledge",
        "description": "Demonstrated understanding of competitive products and positioning",
        "weight": 1 / 7,
        "deterministic": False,
        "rubric": "0=unaware, 1=basic, 2=good knowledge, 3=expert level",
    },
    "objection_handling": {
        "name": "Objection Handling",
        "description": "Effectiveness in addressing physician concerns and objections",
        "weight": 1 / 7,
        "deterministic": False,
        "rubric": "0=ineffective, 1=basic, 2=competent, 3=excellent",
    },
    "procedural_workflow": {
        "name": "Procedural Workflow",
        "description": "Understanding of clinical workflow and procedural integration",
        "weight": 1 / 7,
        "deterministic": False,
        "rubric": "0=unaware, 1=limited, 2=good understanding, 3=expert",
    },
    "closing_effectiveness": {
        "name": "Closing Effectiveness",
        "description": "Ability to move toward commitment and close the sale",
        "weight": 1 / 7,
        "deterministic": False,
        "rubric": "0=no progress, 1=minimal, 2=makes progress, 3=strong close",
    },
}


class TurnScore(BaseModel):
    """Represents scoring for a single turn in a simulation."""

    turn_number: int = Field(..., description="Turn number being scored")
    dimension_scores: Dict[str, float] = Field(
        ...,
        description="Scores for each dimension (0-3 scale normalized to 0-1)",
    )
    overall: float = Field(
        ..., description="Overall turn score (0-1), weighted average of dimensions"
    )
    feedback: Dict[str, str] = Field(
        default_factory=dict,
        description="Detailed feedback for each dimension",
    )
    flags: List[str] = Field(
        default_factory=list,
        description="Flags for issues or concerns",
    )


class SimulationScore(BaseModel):
    """Represents overall scoring for a completed simulation session."""

    session_id: str = Field(..., description="Session being scored")
    total_turns: int = Field(..., description="Total number of turns")
    dimension_averages: Dict[str, float] = Field(
        ...,
        description="Average score for each dimension across all turns (0-1)",
    )
    overall_average: float = Field(
        ..., description="Overall average score across all turns (0-1)"
    )
    trend: List[float] = Field(
        default_factory=list,
        description="Score trend over time (overall score for each turn)",
    )
    strengths: List[str] = Field(
        default_factory=list,
        description="Identified strengths",
    )
    improvement_areas: List[str] = Field(
        default_factory=list,
        description="Areas identified for improvement",
    )

    class Config:
        """Pydantic config."""

        json_schema_extra = {
            "example": {
                "session_id": "sim_001",
                "total_turns": 12,
                "dimension_averages": {
                    "clinical_accuracy": 0.85,
                    "spec_accuracy": 0.92,
                    "regulatory_compliance": 0.88,
                    "competitive_knowledge": 0.78,
                    "objection_handling": 0.82,
                    "procedural_workflow": 0.80,
                    "closing_effectiveness": 0.75,
                },
                "overall_average": 0.83,
                "trend": [0.70, 0.72, 0.75, 0.80, 0.82, 0.85],
                "strengths": ["Strong clinical knowledge", "Good objection handling"],
                "improvement_areas": ["Competitive positioning", "Closing technique"],
            }
        }
