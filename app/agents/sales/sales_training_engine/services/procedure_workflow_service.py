"""
Procedure Workflow Service for MedSync AI Sales Training Engine.

Loads procedure workflow JSON files and provides methods for querying,
comparing devices, and searching across workflows.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

from ..config import get_settings
from ..models.workflow import (
    DeviceComparisonResult,
    DeviceMapping,
    ProcedureStep,
    ProcedureWorkflow,
    WorkflowSummary,
)

logger = logging.getLogger(__name__)


class ProcedureWorkflowService:
    """Service for loading and querying procedure workflows."""

    def __init__(self) -> None:
        """Load all workflow JSON files from the data/workflows/ directory."""
        self._workflows: Dict[str, ProcedureWorkflow] = {}
        self._load_workflows()

    def _load_workflows(self) -> None:
        """Scan the workflows directory and parse each JSON file."""
        settings = get_settings()
        workflows_dir = settings.data_dir / "workflows"

        if not workflows_dir.exists():
            logger.warning("Workflows directory not found: %s", workflows_dir)
            return

        for json_file in sorted(workflows_dir.glob("*.json")):
            try:
                with open(json_file, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                workflow = ProcedureWorkflow(**data)
                self._workflows[workflow.procedureId] = workflow
                logger.info(
                    "Loaded workflow: %s (%d steps)",
                    workflow.procedureName,
                    len(workflow.steps),
                )
            except (json.JSONDecodeError, Exception) as exc:
                logger.error("Failed to load workflow from %s: %s", json_file, exc)

        logger.info("Total workflows loaded: %d", len(self._workflows))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_workflows(self) -> List[WorkflowSummary]:
        """
        List all available workflows with summary information.

        Returns:
            List of WorkflowSummary objects (id, name, category, stepCount).
        """
        summaries: List[WorkflowSummary] = []
        for wf in self._workflows.values():
            summaries.append(
                WorkflowSummary(
                    procedureId=wf.procedureId,
                    procedureName=wf.procedureName,
                    category=wf.category,
                    stepCount=len(wf.steps),
                )
            )
        return summaries

    def get_workflow(self, procedure_id: str) -> Optional[ProcedureWorkflow]:
        """
        Return the full workflow for a given procedure ID.

        Args:
            procedure_id: The procedure identifier (e.g. 'mechanical-thrombectomy').

        Returns:
            The ProcedureWorkflow if found, otherwise None.
        """
        return self._workflows.get(procedure_id)

    def compare_devices(
        self,
        procedure_id: str,
        device_a_name: str,
        device_b_name: str,
    ) -> Optional[DeviceComparisonResult]:
        """
        Compare two devices within a specific procedure workflow.

        Searches across all steps to find the devices and returns their
        mappings side by side. If both devices appear in the same step
        that step context is included.

        Args:
            procedure_id: The procedure identifier.
            device_a_name: Name (or partial name) of the first device.
            device_b_name: Name (or partial name) of the second device.

        Returns:
            DeviceComparisonResult or None if the procedure is not found.
        """
        workflow = self._workflows.get(procedure_id)
        if workflow is None:
            return None

        device_a: Optional[DeviceMapping] = None
        device_b: Optional[DeviceMapping] = None
        step_a: Optional[ProcedureStep] = None
        step_b: Optional[ProcedureStep] = None
        a_lower = device_a_name.lower()
        b_lower = device_b_name.lower()

        for step in workflow.steps:
            for dm in step.deviceMappings:
                name_lower = dm.deviceName.lower()
                if a_lower in name_lower and device_a is None:
                    device_a = dm
                    step_a = step
                if b_lower in name_lower and device_b is None:
                    device_b = dm
                    step_b = step

        # Determine shared step context
        shared_step_name: Optional[str] = None
        shared_step_number: Optional[int] = None
        if step_a is not None and step_b is not None and step_a.stepNumber == step_b.stepNumber:
            shared_step_name = step_a.name
            shared_step_number = step_a.stepNumber

        return DeviceComparisonResult(
            procedureId=workflow.procedureId,
            procedureName=workflow.procedureName,
            deviceA=device_a,
            deviceB=device_b,
            stepName=shared_step_name,
            stepNumber=shared_step_number,
        )

    def search_workflows(self, query: str) -> List[Dict]:
        """
        Search workflows by procedure name or device name.

        Args:
            query: Search string (case-insensitive).

        Returns:
            List of dicts with matching workflow and device information.
        """
        if not query or len(query.strip()) < 2:
            return []

        query_lower = query.lower().strip()
        results: List[Dict] = []

        for wf in self._workflows.values():
            # Check procedure-level match
            procedure_match = (
                query_lower in wf.procedureName.lower()
                or query_lower in wf.procedureId.lower()
                or query_lower in wf.category.lower()
                or query_lower in wf.description.lower()
            )

            if procedure_match:
                results.append(
                    {
                        "procedureId": wf.procedureId,
                        "procedureName": wf.procedureName,
                        "category": wf.category,
                        "matchType": "procedure",
                        "matchedDevices": [],
                    }
                )
                continue

            # Check device-level matches within steps
            matched_devices: List[Dict] = []
            for step in wf.steps:
                for dm in step.deviceMappings:
                    if (
                        query_lower in dm.deviceName.lower()
                        or query_lower in dm.manufacturer.lower()
                    ):
                        matched_devices.append(
                            {
                                "deviceName": dm.deviceName,
                                "manufacturer": dm.manufacturer,
                                "stepNumber": step.stepNumber,
                                "stepName": step.name,
                            }
                        )

            if matched_devices:
                results.append(
                    {
                        "procedureId": wf.procedureId,
                        "procedureName": wf.procedureName,
                        "category": wf.category,
                        "matchType": "device",
                        "matchedDevices": matched_devices,
                    }
                )

        return results


# ---------------------------------------------------------------------------
# Module-level singleton accessor
# ---------------------------------------------------------------------------

_service_instance: Optional[ProcedureWorkflowService] = None


def get_procedure_workflow_service() -> ProcedureWorkflowService:
    """Return (and lazily create) the singleton ProcedureWorkflowService."""
    global _service_instance
    if _service_instance is None:
        _service_instance = ProcedureWorkflowService()
    return _service_instance
