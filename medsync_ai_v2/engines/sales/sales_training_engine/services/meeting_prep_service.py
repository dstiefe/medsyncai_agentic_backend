"""
Meeting prep service for MedSync AI Sales Simulation Engine.
Generates pre-call intelligence briefs for sales rep meetings with physicians.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Dict, List, Optional

from ..models.device import Device
from ..models.meeting_prep import (
    CompatibilityInsight,
    DeviceSpecComparison,
    IntelligenceBrief,
    MeetingPrepRequest,
    MeetingPrepSession,
    MigrationStep,
    ObjectionResponse,
    TalkingPoint,
)
from ..models.physician_profile import DeviceStackEntry, PhysicianProfile
from ..models.simulation_state import SimulationMode, SimulationSession, SimulationStatus
from ..rag.retrieval import VectorRetriever
from .compatibility_engine import CompatibilityEngine
from .data_loader import DataManager
from .device_service import DeviceService
from .llm_adapter import SalesLLMAdapter

# Module-level session storage
ACTIVE_PREP_SESSIONS: Dict[str, MeetingPrepSession] = {}


class MeetingPrepService:
    """Service for generating pre-call intelligence briefs and meeting preparation."""

    def __init__(self, data_manager: DataManager):
        """
        Initialize MeetingPrepService.

        Args:
            data_manager: The DataManager instance
        """
        self.data_manager = data_manager
        self.device_service = DeviceService(data_manager)
        self.compatibility_engine = CompatibilityEngine(data_manager)
        self.llm_service = SalesLLMAdapter()
        self.vector_retriever = VectorRetriever(data_manager)

    async def generate_brief(self, request: MeetingPrepRequest) -> MeetingPrepSession:
        """
        Generate a complete pre-call intelligence brief.

        Args:
            request: The meeting prep request with physician and rep details

        Returns:
            MeetingPrepSession containing the generated brief
        """
        prep_id = f"prep_{uuid.uuid4().hex[:8]}"
        brief_id = f"brief_{uuid.uuid4().hex[:8]}"

        # Section A: Build physician profile summary
        physician_stack = self._build_physician_stack(request.physician_device_ids)
        inferred_approach = self._infer_clinical_approach(physician_stack)

        # Section B: Competitive analysis
        rep_portfolio = self.device_service.get_portfolio(request.rep_company)
        device_comparisons = self._build_device_comparisons(
            physician_stack, rep_portfolio, request.products_to_pitch
        )

        # Section C: Compatibility intelligence
        compatibility_insights = self._check_cross_compatibility(
            physician_stack, rep_portfolio
        )
        migration_path = await self._generate_migration_path(
            physician_stack, rep_portfolio, request
        )

        # Section D: Talking points
        talking_points = await self._generate_talking_points(
            device_comparisons, compatibility_insights, request
        )

        # Section E: Objection playbook
        objection_playbook = await self._generate_objection_playbook(request)

        # Assemble brief
        brief = IntelligenceBrief(
            brief_id=brief_id,
            physician_name=request.physician_name,
            physician_specialty=request.physician_specialty.value,
            hospital_type=request.hospital_type.value,
            annual_case_volume=request.annual_case_volume,
            current_stack_summary=[
                {
                    "role": entry.role,
                    "device_name": entry.device_name,
                    "device_id": entry.device_id,
                    "manufacturer": entry.manufacturer,
                }
                for entry in physician_stack
            ],
            inferred_approach=inferred_approach,
            device_comparisons=device_comparisons,
            compatibility_insights=compatibility_insights,
            migration_path=migration_path,
            talking_points=talking_points,
            objection_playbook=objection_playbook,
            meeting_context=request.meeting_context,
            rep_company=request.rep_company,
            data_sources_used=["device_specs", "compatibility_matrix", "competitive_intel"],
        )

        # Create prep session
        session = MeetingPrepSession(
            prep_id=prep_id,
            brief=brief,
            request=request,
        )

        ACTIVE_PREP_SESSIONS[prep_id] = session
        return session

    def _build_physician_stack(self, device_ids: List[int]) -> List[DeviceStackEntry]:
        """Build physician's device stack from device IDs."""
        stack = []
        for did in device_ids:
            device = self.data_manager.get_device(did)
            if device:
                stack.append(
                    DeviceStackEntry(
                        role=device.category.role if hasattr(device.category, "role") else device.category.key,
                        device_name=device.device_name,
                        device_id=device.id,
                        manufacturer=device.manufacturer,
                    )
                )
        return stack

    def _infer_clinical_approach(self, stack: List[DeviceStackEntry]) -> str:
        """Infer the physician's clinical approach from their device stack."""
        device_names_lower = [entry.device_name.lower() for entry in stack]
        all_text = " ".join(device_names_lower)

        has_aspiration = any(
            kw in all_text
            for kw in ["aspiration", "penumbra", "jet", "ace", "cat"]
        )
        has_stent_retriever = any(
            kw in all_text
            for kw in ["solitaire", "trevo", "embotrap", "stent retriever"]
        )

        if has_aspiration and has_stent_retriever:
            return "combined"
        elif has_aspiration:
            return "aspiration-first"
        elif has_stent_retriever:
            return "stent-retriever-first"
        else:
            return "unknown"

    def _build_device_comparisons(
        self,
        physician_stack: List[DeviceStackEntry],
        rep_portfolio: List[Device],
        products_to_pitch: Optional[List[int]],
    ) -> List[DeviceSpecComparison]:
        """Build side-by-side device comparisons."""
        comparisons = []

        # Determine which rep devices to compare
        rep_devices_to_compare = []
        if products_to_pitch:
            for did in products_to_pitch:
                device = self.data_manager.get_device(did)
                if device:
                    rep_devices_to_compare.append(device)
        else:
            rep_devices_to_compare = rep_portfolio

        # Match by category
        for physician_entry in physician_stack:
            physician_device = self.data_manager.get_device(physician_entry.device_id)
            if not physician_device:
                continue

            for rep_device in rep_devices_to_compare:
                if rep_device.category.key == physician_device.category.key:
                    advantages, disadvantages = self._compare_specs(
                        rep_device, physician_device
                    )
                    comparisons.append(
                        DeviceSpecComparison(
                            physician_device_id=physician_device.id,
                            physician_device_name=physician_device.device_name,
                            physician_manufacturer=physician_device.manufacturer,
                            rep_device_id=rep_device.id,
                            rep_device_name=rep_device.device_name,
                            rep_manufacturer=rep_device.manufacturer,
                            spec_advantages=advantages,
                            spec_disadvantages=disadvantages,
                        )
                    )

        return comparisons

    def _compare_specs(
        self, rep_device: Device, physician_device: Device
    ) -> tuple:
        """Compare specs between two devices and identify advantages/disadvantages."""
        advantages = []
        disadvantages = []

        rep_specs = rep_device.specifications if hasattr(rep_device, "specifications") else {}
        phys_specs = physician_device.specifications if hasattr(physician_device, "specifications") else {}

        if isinstance(rep_specs, dict) and isinstance(phys_specs, dict):
            for key in set(list(rep_specs.keys()) + list(phys_specs.keys())):
                rep_val = rep_specs.get(key)
                phys_val = phys_specs.get(key)
                if rep_val and phys_val and rep_val != phys_val:
                    advantages.append(f"{key}: {rep_val} vs {phys_val}")

        return advantages, disadvantages

    def _check_cross_compatibility(
        self,
        physician_stack: List[DeviceStackEntry],
        rep_portfolio: List[Device],
    ) -> List[CompatibilityInsight]:
        """Check cross-manufacturer compatibility between rep and physician devices."""
        insights = []

        for rep_device in rep_portfolio:
            for physician_entry in physician_stack:
                if physician_entry.device_id:
                    compat = self.compatibility_engine.check_compatibility(
                        rep_device.id, physician_entry.device_id
                    )
                    if compat.get("compatible") or compat.get("clearance_mm"):
                        insights.append(
                            CompatibilityInsight(
                                rep_device_id=rep_device.id,
                                rep_device_name=rep_device.device_name,
                                physician_device_id=physician_entry.device_id,
                                physician_device_name=physician_entry.device_name,
                                compatible=compat.get("compatible", False),
                                fit_type=compat.get("fit_type"),
                                clearance_mm=compat.get("clearance_mm"),
                                explanation=compat.get(
                                    "explanation",
                                    f"{rep_device.device_name} with {physician_entry.device_name}",
                                ),
                            )
                        )

        return insights

    async def _generate_migration_path(
        self,
        physician_stack: List[DeviceStackEntry],
        rep_portfolio: List[Device],
        request: MeetingPrepRequest,
    ) -> List[MigrationStep]:
        """Generate a recommended device migration path using LLM."""
        stack_summary = "\n".join(
            f"  - {e.role}: {e.device_name} ({e.manufacturer})"
            for e in physician_stack
        )
        portfolio_summary = "\n".join(
            f"  - {d.device_name} ({d.category.display_name})"
            for d in rep_portfolio[:15]
        )

        prompt = f"""Given a physician's current device stack and a rep's portfolio,
suggest a migration path (ordered steps to transition the physician to the rep's devices).

Physician's Current Stack:
{stack_summary}

Rep's Portfolio ({request.rep_company}):
{portfolio_summary}

Hospital Type: {request.hospital_type.value}
Meeting Context: {request.meeting_context or "Initial meeting"}

Respond with ONLY valid JSON array:
[
  {{"order": 1, "action": "...", "rationale": "...", "disruption_level": "low"}},
  {{"order": 2, "action": "...", "rationale": "...", "disruption_level": "medium"}}
]"""

        response = await self.llm_service.generate(
            system_prompt="You are a medical device sales strategist.",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=1500,
        )

        steps = []
        try:
            json_start = response.find("[")
            json_end = response.rfind("]") + 1
            if json_start >= 0 and json_end > json_start:
                raw_steps = json.loads(response[json_start:json_end])
            else:
                raw_steps = json.loads(response)

            for s in raw_steps:
                steps.append(
                    MigrationStep(
                        order=s.get("order", 0),
                        action=s.get("action", ""),
                        rationale=s.get("rationale", ""),
                        disruption_level=s.get("disruption_level", "medium"),
                    )
                )
        except (json.JSONDecodeError, KeyError, TypeError):
            pass

        return steps

    async def _generate_talking_points(
        self,
        comparisons: List[DeviceSpecComparison],
        compatibility_insights: List[CompatibilityInsight],
        request: MeetingPrepRequest,
    ) -> List[TalkingPoint]:
        """Generate evidence-backed talking points using LLM."""
        comparison_text = ""
        for c in comparisons[:5]:
            comparison_text += (
                f"\n{c.rep_device_name} vs {c.physician_device_name}: "
                f"Advantages: {c.spec_advantages}, Disadvantages: {c.spec_disadvantages}"
            )

        compat_text = ""
        for ci in compatibility_insights[:5]:
            compat_text += (
                f"\n{ci.rep_device_name} + {ci.physician_device_name}: "
                f"Compatible={ci.compatible}, {ci.explanation}"
            )

        # Retrieve relevant documents
        rag_results = self.vector_retriever.retrieve(
            f"{request.rep_company} devices {request.physician_specialty.value}",
            k=5,
        )
        rag_context = "\n".join(
            f"[{r.source_type}] {r.text[:200]}" for r in rag_results
        )

        prompt = f"""Generate 4-6 evidence-backed talking points for a sales call.

Rep Company: {request.rep_company}
Physician: {request.physician_name} ({request.physician_specialty.value})
Hospital: {request.hospital_type.value}

Device Comparisons:{comparison_text}

Compatibility:{compat_text}

Retrieved Evidence:
{rag_context}

Respond with ONLY valid JSON array:
[
  {{"headline": "...", "detail": "...", "evidence_type": "spec_advantage", "citations": ["[SPECS:id=X]"]}}
]"""

        response = await self.llm_service.generate(
            system_prompt="You are a medical device sales strategist. Generate concise, evidence-backed talking points.",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=2000,
        )

        points = []
        try:
            json_start = response.find("[")
            json_end = response.rfind("]") + 1
            if json_start >= 0 and json_end > json_start:
                raw_points = json.loads(response[json_start:json_end])
            else:
                raw_points = json.loads(response)

            for tp in raw_points:
                points.append(
                    TalkingPoint(
                        headline=tp.get("headline", ""),
                        detail=tp.get("detail", ""),
                        evidence_type=tp.get("evidence_type", "general"),
                        citations=tp.get("citations", []),
                    )
                )
        except (json.JSONDecodeError, KeyError, TypeError):
            pass

        return points

    async def _generate_objection_playbook(
        self, request: MeetingPrepRequest
    ) -> List[ObjectionResponse]:
        """Generate predicted objections and recommended responses."""
        known_objections = request.known_objections or "None provided"

        prompt = f"""Generate 4-6 predicted objections a physician might raise in a sales meeting,
with recommended responses.

Physician: {request.physician_name}
Specialty: {request.physician_specialty.value}
Hospital Type: {request.hospital_type.value}
Rep Company: {request.rep_company}
Known Objections: {known_objections}
Meeting Context: {request.meeting_context or "Initial meeting"}

Respond with ONLY valid JSON array:
[
  {{
    "objection": "...",
    "likelihood": "high",
    "recommended_response": "...",
    "supporting_data": ["data point 1", "data point 2"]
  }}
]"""

        response = await self.llm_service.generate(
            system_prompt="You are a medical device sales coach specializing in objection handling.",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=2000,
        )

        objections = []
        try:
            json_start = response.find("[")
            json_end = response.rfind("]") + 1
            if json_start >= 0 and json_end > json_start:
                raw_objections = json.loads(response[json_start:json_end])
            else:
                raw_objections = json.loads(response)

            for obj in raw_objections:
                objections.append(
                    ObjectionResponse(
                        objection=obj.get("objection", ""),
                        likelihood=obj.get("likelihood", "medium"),
                        recommended_response=obj.get("recommended_response", ""),
                        supporting_data=obj.get("supporting_data", []),
                    )
                )
        except (json.JSONDecodeError, KeyError, TypeError):
            pass

        return objections

    def get_prep_session(self, prep_id: str) -> Optional[MeetingPrepSession]:
        """Get a meeting prep session by ID."""
        return ACTIVE_PREP_SESSIONS.get(prep_id)

    def list_prep_sessions(self) -> List[str]:
        """List all active prep session IDs."""
        return list(ACTIVE_PREP_SESSIONS.keys())
