from typing import Any, List, Literal, Optional, Union
from pydantic import BaseModel, Field


class RuleClause(BaseModel):
    """Single clause in a rule condition."""
    var: str = Field(description="Variable name from ParsedVariables")
    op: str = Field(description="Operator: ==, !=, >=, <=, >, <, in, not_in, is_null, is_not_null")
    val: Optional[Any] = Field(None, description="Value to compare (optional for null checks)")
    optional: bool = Field(False, description="If true, missing value is treated as met (not blocking)")


class RuleCondition(BaseModel):
    """Condition with AND/OR logic."""
    logic: Literal["AND", "OR"]
    clauses: List[Union["RuleClause", "RuleCondition"]]


# Allow self-reference
RuleCondition.model_rebuild()


class RuleAction(BaseModel):
    """Action to take when rule fires."""
    type: Literal["fire", "note"]
    recIds: Optional[List[str]] = Field(None, description="Recommendation IDs to fire")
    severity: Optional[str] = Field(None, description="Severity for notes: danger, warning, info")
    text: Optional[str] = Field(None, description="Note text")


class Rule(BaseModel):
    """Complete rule with condition and actions."""
    id: str
    guidelineId: str
    name: str
    priority: int = Field(default=0, description="Higher priority fires first")
    enabled: bool = Field(default=True)
    condition: RuleCondition
    actions: List[RuleAction]
