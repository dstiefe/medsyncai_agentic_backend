"""
Data models for MedSync AI Sales Simulation Engine.
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
    SpecPicSource,
    WebpageSource,
)
from .physician_dossier import PhysicianDossier, PhysicianDossierSummary
from .physician_profile import DeviceStackEntry, PhysicianProfile
from .scoring import SCORING_DIMENSIONS, SimulationScore, TurnScore
from .simulation_state import (
    Citation,
    CitationType,
    SimulationMode,
    SimulationSession,
    SimulationStatus,
    Turn,
)

__all__ = [
    # Device models
    "Device",
    "DeviceCategory",
    "DeviceCompatibility",
    "DeviceSources",
    "DeviceSpecifications",
    "Dimension",
    "LengthDimension",
    "SourceInfo",
    "SpecPicSource",
    "WebpageSource",
    # Physician models
    "DeviceStackEntry",
    "PhysicianDossier",
    "PhysicianDossierSummary",
    "PhysicianProfile",
    # Simulation models
    "Citation",
    "CitationType",
    "SimulationMode",
    "SimulationSession",
    "SimulationStatus",
    "Turn",
    # Scoring models
    "SCORING_DIMENSIONS",
    "SimulationScore",
    "TurnScore",
]
