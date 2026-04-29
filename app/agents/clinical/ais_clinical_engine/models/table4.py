from typing import List, Literal, Optional
from pydantic import BaseModel, Field


class Table4Result(BaseModel):
    """Result of Table 4 disabling deficit assessment."""
    isDisabling: Optional[bool] = Field(
        None,
        description="True if disabling deficit, False if non-disabling, None if needs assessment"
    )
    rationale: str = Field(
        default="",
        description="Explanation of the assessment"
    )
    disablingDeficits: List[str] = Field(
        default_factory=list,
        description="NIHSS items indicating disabling deficits"
    )
    possiblyNonDisabling: List[str] = Field(
        default_factory=list,
        description="NIHSS items that might be non-disabling"
    )
    recommendation: Literal[
        "standard_ivt",
        "non_disabling_dapt",
        "needs_assessment"
    ] = Field(
        default="needs_assessment",
        description="Treatment pathway recommendation"
    )
