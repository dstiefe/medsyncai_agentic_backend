"""
Rep profile and activity log models for MedSync AI Sales Intelligence Platform.
"""

from typing import Dict, List, Optional

from pydantic import BaseModel


class RepProfile(BaseModel):
    """Sales rep identity and profile."""

    rep_id: str
    name: str
    company: str
    role: str = "rep"  # "rep" or "manager"
    created_at: str = ""
    last_active: str = ""


class ActivityLogEntry(BaseModel):
    """A single activity log entry (simulation, assessment, Q&A, etc.)."""

    entry_id: str
    rep_id: str
    activity_type: str  # simulation, assessment, qa_session, meeting_prep, field_debrief
    mode: Optional[str] = None
    session_id: Optional[str] = None
    physician_id: Optional[str] = None
    physician_name: Optional[str] = None
    company: str = ""
    timestamp: str = ""
    duration_seconds: Optional[int] = None
    scores: Optional[Dict[str, float]] = None
    overall_score: Optional[float] = None
    metadata: Dict = {}
