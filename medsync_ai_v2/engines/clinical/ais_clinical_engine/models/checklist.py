"""
Generalized clinical checklist model.

Used across all clinical domains (IVT contraindications, EVT eligibility,
imaging, BP management, medications) to track what has been assessed vs
what the clinician still needs to consider.

Design principle: "Not mentioned" means "not yet assessed," never "not present."
The system assumes nothing and gently surfaces everything that hasn't been
explicitly addressed.
"""

from typing import Any, Dict, List, Literal, Optional, Set
from pydantic import BaseModel, Field


class ChecklistItem(BaseModel):
    """Individual checklist item with assessment status."""
    ruleId: str = Field(description="Unique rule identifier")
    domain: str = Field(description="Clinical domain: ivt_contraindications, evt_eligibility, imaging, bp_management, medications")
    category: str = Field(description="Sub-category within the domain")
    condition: str = Field(description="Human-readable condition name")
    guidance: str = Field(description="Guideline text / clinical rationale")
    status: Literal["confirmed_present", "confirmed_absent", "unassessed"] = "unassessed"
    assessedVariables: List[str] = Field(
        default_factory=list,
        description="Which clinical variables determine this item"
    )
    sourceTable: Optional[str] = Field(None, description="Source table in guideline (e.g. Table 8)")
    sourcePage: Optional[int] = Field(None, description="Page number in guideline")


class ChecklistSummary(BaseModel):
    """Summary of a clinical checklist for a specific domain."""
    domain: str
    domainLabel: str = Field(description="Human-readable domain label for UI")
    totalItems: int = 0
    assessedItems: int = 0
    unassessedItems: int = 0
    confirmedPresent: int = 0
    confirmedAbsent: int = 0
    items: List[ChecklistItem] = Field(default_factory=list)
    reminderText: Optional[str] = Field(
        None,
        description="Gentle reminder text when unassessed items exist"
    )


class ClinicalChecklistRule(BaseModel):
    """
    A rule definition for the checklist system.

    Each rule maps a clinical concept to the variables needed to assess it,
    so the system can determine assessed vs unassessed status.
    """
    id: str
    domain: str
    category: str
    condition: str
    guidance: str
    variables: List[str] = Field(description="Variable names from ParsedVariables needed to assess this item")
    trigger: Optional[Dict[str, Any]] = Field(
        None,
        description="Optional trigger dict for evaluating confirmed_present (same format as Table8 triggers)"
    )
    sourceTable: Optional[str] = None
    sourcePage: Optional[int] = None
