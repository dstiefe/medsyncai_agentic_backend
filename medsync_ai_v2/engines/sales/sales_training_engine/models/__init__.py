"""
Sales Training Engine — Pydantic models.

Re-exports key classes for convenient imports.
"""

from .device import (
    Device,
    DeviceCategory,
    DeviceCompatibility,
    DeviceSources,
    DeviceSpecifications,
    Dimension,
    LengthDimension,
    SourceInfo,
)
from .meeting_prep import (
    CompatibilityInsight,
    DeviceSpecComparison,
    HospitalType,
    IntelligenceBrief,
    MeetingPrepRequest,
    MeetingPrepSession,
    MigrationStep,
    ObjectionResponse,
    PhysicianSpecialty,
    TalkingPoint,
)
from .physician_dossier import (
    BusinessIntelligence,
    ClinicalProfile,
    CompetitiveLandscape,
    ComplianceInfo,
    DecisionMakingProfile,
    PhysicianDossier,
    PhysicianDossierSummary,
    RelationshipTracking,
)
from .physician_profile import DeviceStackEntry, PhysicianProfile
from .rep_profile import ActivityLogEntry, RepProfile
from .scoring import SCORING_DIMENSIONS, SimulationScore, TurnScore
from .simulation_state import (
    Citation,
    CitationType,
    RetrievalResult,
    SimulationMode,
    SimulationSession,
    SimulationStatus,
    Turn,
)
