from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field
from .clinical import Note


class Table8Rule(BaseModel):
    """Rule for Table 8 contraindication assessment."""
    id: str
    tier: Literal["absolute", "relative", "benefit_over_risk"]
    condition: str  # Human-readable condition name
    trigger: Dict[str, Any]  # Dict with var, op, val keys for evaluation
    guidance: str  # Verbatim guidance text from guideline
    sourceTable: str = "Table 8"
    sourcePage: int = 0


class Table8Item(BaseModel):
    """Individual Table 8 checklist item with assessment status."""
    ruleId: str
    tier: Literal["absolute", "relative", "benefit_over_risk"]
    condition: str  # Human-readable condition name
    guidance: str  # Guideline text for this item
    status: Literal["confirmed_present", "confirmed_absent", "unassessed"]
    assessedVariables: List[str] = Field(
        default_factory=list,
        description="Which clinical variables were used to assess this item"
    )


class Table8Result(BaseModel):
    """Result of Table 8 contraindication assessment."""
    riskTier: Literal[
        "absolute_contraindication",
        "relative_contraindication",
        "benefit_over_risk",
        "no_contraindications"
    ]
    absoluteContraindications: List[str] = Field(
        default_factory=list,
        description="List of absolute contraindications found"
    )
    relativeContraindications: List[str] = Field(
        default_factory=list,
        description="List of relative contraindications found"
    )
    benefitOverRisk: List[str] = Field(
        default_factory=list,
        description="List of benefit-over-risk conditions found"
    )
    notes: List[Note] = Field(
        default_factory=list,
        description="Detailed notes with guidance"
    )
    checklist: List[Table8Item] = Field(
        default_factory=list,
        description="Full Table 8 checklist with assessment status per item"
    )
    unassessedCount: int = Field(
        default=0,
        description="Number of Table 8 items not yet assessed"
    )
