"""
Simulation state models for MedSync AI Sales Simulation Engine.

Models representing simulation sessions, turns, and associated metadata.
"""

from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from .physician_profile import PhysicianProfile


class SimulationMode(str, Enum):
    """Enumeration of simulation modes."""

    COMPETITIVE_SALES_CALL = "competitive_sales_call"
    PRODUCT_KNOWLEDGE = "product_knowledge"
    COMPETITOR_DEEP_DIVE = "competitor_deep_dive"
    OBJECTION_HANDLING = "objection_handling"


class SimulationStatus(str, Enum):
    """Enumeration of simulation statuses."""

    SETUP = "setup"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    SCORED = "scored"


class CitationType(str, Enum):
    """Types of citations for claims and facts."""

    SPECS = "specs"
    IFU = "ifu"
    WEBPAGE = "webpage"
    LITERATURE = "literature"
    MAUDE = "maude"


class Citation(BaseModel):
    """Represents a citation for a statement made during simulation."""

    citation_type: CitationType = Field(..., description="Type of citation source")
    reference: str = Field(..., description="Reference identifier or URL")
    excerpt: str = Field(..., description="Relevant excerpt from source")
    verified: bool = Field(
        default=False, description="Whether citation has been verified"
    )


class RetrievalResult(BaseModel):
    """Represents a document retrieval result from RAG."""

    chunk_id: str = Field(..., description="Unique chunk identifier")
    score: float = Field(..., description="Relevance score")
    source_type: str = Field(..., description="Type of source (ifu, webpage_text, etc.)")
    manufacturer: str = Field(default="", description="Device manufacturer")
    device_names: List[str] = Field(default_factory=list, description="Relevant device names")
    file_name: str = Field(..., description="Name of the source file")
    section_hint: str = Field(default="", description="Section or topic hint")
    text: str = Field(..., description="The retrieved text content")


class Turn(BaseModel):
    """Represents a single turn in a simulation conversation."""

    turn_number: int = Field(..., description="Turn number in sequence")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Turn timestamp")
    speaker: str = Field(
        ..., description="Speaker: 'user' (sales rep) or 'physician'"
    )
    message: str = Field(..., description="The message content")
    citations: List[Citation] = Field(
        default_factory=list, description="Citations supporting statements"
    )
    scores: Optional[Dict[str, float]] = Field(
        None, description="Dimension scores for this turn"
    )
    context_metadata: Optional[Dict] = Field(
        None, description="Additional context and metadata"
    )


class SimulationSession(BaseModel):
    """Represents a complete simulation session."""

    session_id: str = Field(..., description="Unique session identifier")
    mode: SimulationMode = Field(..., description="Type of simulation")
    status: SimulationStatus = Field(
        default=SimulationStatus.SETUP, description="Current session status"
    )
    physician_profile: PhysicianProfile = Field(
        ..., description="Simulated physician profile"
    )
    rep_company: str = Field(..., description="Sales rep company")
    rep_name: str = Field(default="", description="Sales rep name for personalized interactions")
    difficulty_level: str = Field(default="intermediate", description="Difficulty level: beginner, intermediate, experienced")
    sub_mode: str = Field(default="", description="Sub-mode: conversational, structured (for product_knowledge)")
    rep_portfolio_ids: List[int] = Field(
        ..., description="Device IDs in rep's portfolio"
    )
    scenario_context: Dict = Field(
        default_factory=dict, description="Scenario-specific context"
    )
    turns: List[Turn] = Field(
        default_factory=list, description="Conversation turns"
    )
    created_at: datetime = Field(
        default_factory=datetime.utcnow, description="Creation timestamp"
    )
    updated_at: datetime = Field(
        default_factory=datetime.utcnow, description="Last update timestamp"
    )

    class Config:
        """Pydantic config."""

        json_encoders = {
            datetime: lambda v: v.isoformat(),
        }
