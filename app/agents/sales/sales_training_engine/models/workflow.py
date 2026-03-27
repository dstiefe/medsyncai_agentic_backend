"""
Procedure Workflow data models for MedSync AI Sales Training Engine.

Pydantic v2 models representing step-by-step procedural workflows with
device mappings at each step. Used by the Procedure Workflow module to
structure mechanical thrombectomy and other neurovascular procedure data.
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class DeviceMapping(BaseModel):
    """Maps a specific device to its role within a procedure step."""

    deviceId: int = Field(
        ..., description="Device ID from the device catalog (0 if not cataloged)"
    )
    deviceName: str = Field(..., description="Commercial device name")
    manufacturer: str = Field(..., description="Device manufacturer")
    roleInStep: str = Field(
        ..., description="Description of the device's role in this procedure step"
    )
    manufacturerNotes: str = Field(
        default="",
        description="Manufacturer-provided guidance or recommendations for this device",
    )
    differentiators: List[str] = Field(
        default_factory=list,
        description="Key differentiating features of this device relative to alternatives",
    )


class ProcedureStep(BaseModel):
    """A single step within a procedural workflow."""

    stepNumber: int = Field(..., description="Ordinal step number (1-based)")
    name: str = Field(..., description="Short name for the procedure step")
    description: str = Field(
        ..., description="Detailed description of what happens in this step"
    )
    clinicalContext: str = Field(
        default="",
        description="Clinical rationale, evidence, and practical considerations",
    )
    deviceMappings: List[DeviceMapping] = Field(
        default_factory=list,
        description="Devices used or available for this step",
    )


class ProcedureWorkflow(BaseModel):
    """A complete procedural workflow with steps and device mappings."""

    procedureId: str = Field(
        ..., description="Unique identifier for the procedure (kebab-case)"
    )
    procedureName: str = Field(..., description="Human-readable procedure name")
    category: str = Field(
        ..., description="Clinical category (e.g., 'neurovascular')"
    )
    description: str = Field(
        ..., description="Overview description of the procedure"
    )
    steps: List[ProcedureStep] = Field(
        default_factory=list,
        description="Ordered list of procedure steps",
    )


class WorkflowSummary(BaseModel):
    """Lightweight summary of a workflow for listing endpoints."""

    procedureId: str
    procedureName: str
    category: str
    stepCount: int = Field(default=0, description="Number of steps in the workflow")


class DeviceComparisonResult(BaseModel):
    """Result of comparing two devices within a procedure context."""

    procedureId: str
    procedureName: str
    deviceA: Optional[DeviceMapping] = None
    deviceB: Optional[DeviceMapping] = None
    stepName: Optional[str] = None
    stepNumber: Optional[int] = None
