"""
Meeting Prep Service for MedSync AI Sales Simulation Engine.

Orchestrates the generation of pre-call intelligence briefs by combining
device specs, compatibility analysis, competitive intelligence, and RAG retrieval.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from ..config import get_settings
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
from .llm_service import LLMService


# Module-level storage for meeting prep sessions
ACTIVE_PREPS: Dict[str, MeetingPrepSession] = {}


class MeetingPrepService:
    """Generates pre-call intelligence briefs and manages meeting prep sessions."""

    def __init__(self, data_manager: DataManager, config=None):
        self.data_manager = data_manager
        self.config = config or get_settings()
        self.device_service = DeviceService(data_manager)
        self.compatibility_engine = CompatibilityEngine(data_manager)

        try:
            self.llm_service = LLMService(config)
        except Exception:
            self.llm_service = None

        try:
            self.retriever = VectorRetriever(
                data_manager, model_name=self.config.embedding_model
            )
        except Exception:
            self.retriever = None

    def generate_brief(self, request: MeetingPrepRequest) -> MeetingPrepSession:
        """
        Generate a complete intelligence brief from a meeting prep request.

        Args:
            request: The meeting prep request with physician and meeting details

        Returns:
            MeetingPrepSession containing the generated IntelligenceBrief
        """
        prep_id = f"prep_{uuid.uuid4().hex[:8]}"
        brief_id = f"brief_{uuid.uuid4().hex[:8]}"

        # 1. Resolve physician's devices
        physician_devices = self._resolve_devices(request.physician_device_ids)

        # 2. Resolve rep's devices to pitch (or auto-select from rep's portfolio)
        if request.products_to_pitch:
            rep_devices = self._resolve_devices(request.products_to_pitch)
        else:
            rep_devices = self._auto_select_rep_devices(
                request.rep_company, physician_devices
            )

        # 3. Build physician stack summary
        current_stack = self._build_stack_summary(physician_devices)

        # 4. Infer clinical approach
        inferred_approach = self._infer_approach(physician_devices)

        # 5. Generate device comparisons
        comparisons = self._generate_comparisons(physician_devices, rep_devices)

        # 6. Pull competitive claims
        competitive_claims = self._get_competitive_claims(
            request.rep_company, physician_devices
        )

        # 7. Check cross-manufacturer compatibility
        compatibility_insights = self._check_cross_compatibility(
            physician_devices, rep_devices
        )

        # 8. Generate migration path
        migration_path = self._generate_migration_path(
            physician_devices, rep_devices, compatibility_insights
        )

        # 9. Generate talking points
        talking_points = self._generate_talking_points(
            physician_devices, rep_devices, request
        )

        # 10. Generate objection playbook
        objection_playbook = self._generate_objection_playbook(
            physician_devices, rep_devices, request
        )

        # Track data sources used
        data_sources = ["devices.json", "compatibility_matrix.json", "competitive_intel.json"]
        if self.retriever:
            data_sources.append("document_chunks.json (FAISS)")

        brief = IntelligenceBrief(
            brief_id=brief_id,
            physician_name=request.physician_name,
            physician_specialty=request.physician_specialty.value,
            hospital_type=request.hospital_type.value,
            annual_case_volume=request.annual_case_volume,
            current_stack_summary=current_stack,
            inferred_approach=inferred_approach,
            device_comparisons=comparisons,
            competitive_claims=competitive_claims,
            compatibility_insights=compatibility_insights,
            migration_path=migration_path,
            talking_points=talking_points,
            objection_playbook=objection_playbook,
            meeting_context=request.meeting_context,
            rep_company=request.rep_company,
            data_sources_used=data_sources,
        )

        session = MeetingPrepSession(
            prep_id=prep_id,
            brief=brief,
            request=request,
        )

        ACTIVE_PREPS[prep_id] = session
        return session

    def create_rehearsal_profile(
        self, prep_session: MeetingPrepSession
    ) -> PhysicianProfile:
        """
        Create a dynamic PhysicianProfile from the meeting prep data
        for use in a rehearsal simulation.
        """
        request = prep_session.request
        brief = prep_session.brief

        # Build device stack entries from physician's devices
        device_stack = []
        for dev_summary in brief.current_stack_summary:
            device_stack.append(DeviceStackEntry(
                role=dev_summary.get("category", "device"),
                device_name=dev_summary.get("device_name", "Unknown"),
                device_id=dev_summary.get("id"),
                manufacturer=dev_summary.get("manufacturer", "Unknown"),
            ))

        # Infer personality traits from hospital type and case volume
        traits = self._infer_personality_traits(request)

        # Infer objection patterns from brief
        objection_patterns = [obj.objection for obj in brief.objection_playbook[:5]]

        # Infer technique preference from approach
        technique_map = {
            "aspiration-first": "aspiration",
            "stent-retriever-first": "stent_retriever",
            "combined": "combined",
        }
        technique = technique_map.get(brief.inferred_approach, "combined")

        # Map specialty enum to display string
        specialty_display = {
            "neurointerventional_surgery": "Neurointerventional Surgery",
            "neurointerventional_radiology": "Neurointerventional Radiology",
            "neurosurgery": "Neurosurgery",
            "stroke_neurology": "Stroke Neurology",
        }

        hospital_display = {
            "academic": "Academic Medical Center",
            "community": "Community Hospital",
            "rural": "Rural Hospital",
            "private_practice": "Private Practice",
        }

        profile = PhysicianProfile(
            id=f"dynamic_{prep_session.prep_id}",
            name=request.physician_name,
            specialty=specialty_display.get(
                request.physician_specialty.value, request.physician_specialty.value
            ),
            institution=f"{hospital_display.get(request.hospital_type.value, 'Hospital')}",
            institution_type=request.hospital_type.value,
            case_volume=request.annual_case_volume or 75,
            case_volume_tier=self._case_volume_tier(request.annual_case_volume),
            years_experience=10,
            technique_preference=technique,
            current_device_stack=device_stack,
            clinical_priorities=self._infer_clinical_priorities(brief),
            personality_traits=traits,
            objection_patterns=objection_patterns,
            decision_style=self._infer_decision_style(request),
        )

        return profile

    # --- Private Methods ---

    def _resolve_devices(self, device_ids: List[int]) -> List[Device]:
        """Look up devices by ID, skip any not found."""
        devices = []
        for did in device_ids:
            device = self.data_manager.get_device(did)
            if device:
                devices.append(device)
        return devices

    def _auto_select_rep_devices(
        self, rep_company: str, physician_devices: List[Device]
    ) -> List[Device]:
        """Auto-select rep devices that match physician device categories."""
        rep_devices = []
        physician_categories = {d.category.key for d in physician_devices}

        for device in self.data_manager.get_all_devices():
            if (
                device.manufacturer.lower() == rep_company.lower()
                and device.category.key in physician_categories
            ):
                rep_devices.append(device)

        return rep_devices[:10]  # Cap at 10 for brief readability

    def _build_stack_summary(self, devices: List[Device]) -> List[Dict]:
        """Build a summary of the physician's device stack."""
        summaries = []
        for d in devices:
            summaries.append({
                "id": d.id,
                "device_name": d.device_name,
                "manufacturer": d.manufacturer,
                "category": d.category.display_name,
                "category_key": d.category.key,
                "inner_diameter_mm": d.specifications.inner_diameter.mm,
                "outer_diameter_mm": d.specifications.outer_diameter_distal.mm,
                "length_cm": d.specifications.length.cm,
            })
        return summaries

    def _infer_approach(self, devices: List[Device]) -> str:
        """Infer the physician's clinical approach from their device stack."""
        categories = [d.category.key.lower() for d in devices]

        has_aspiration = any(
            "aspiration" in c or "jet" in c or "penumbra" in c for c in categories
        )
        has_stent = any(
            "stent" in c or "retriever" in c for c in categories
        )

        # Also check device names
        device_names = [d.device_name.lower() for d in devices]
        if not has_aspiration:
            has_aspiration = any(
                term in name
                for name in device_names
                for term in ["jet", "penumbra", "sofia", "react", "catalyst", "ace"]
            )
        if not has_stent:
            has_stent = any(
                term in name
                for name in device_names
                for term in ["trevo", "solitaire", "embotrap", "eric", "tigertriever"]
            )

        if has_aspiration and has_stent:
            return "combined"
        elif has_aspiration:
            return "aspiration-first"
        elif has_stent:
            return "stent-retriever-first"
        else:
            return "combined"

    def _generate_comparisons(
        self, physician_devices: List[Device], rep_devices: List[Device]
    ) -> List[DeviceSpecComparison]:
        """Generate side-by-side spec comparisons for matching device categories."""
        comparisons = []

        for phys_dev in physician_devices:
            # Find rep devices in the same category
            matching_rep_devices = [
                rd for rd in rep_devices
                if rd.category.key == phys_dev.category.key
            ]

            for rep_dev in matching_rep_devices[:2]:  # Max 2 comparisons per physician device
                advantages = []
                disadvantages = []

                # Compare inner diameter
                phys_id = phys_dev.specifications.inner_diameter.mm
                rep_id = rep_dev.specifications.inner_diameter.mm
                if phys_id and rep_id:
                    if rep_id > phys_id:
                        advantages.append(
                            f"Larger inner diameter ({rep_id}mm vs {phys_id}mm) — better device passage"
                        )
                    elif rep_id < phys_id:
                        disadvantages.append(
                            f"Smaller inner diameter ({rep_id}mm vs {phys_id}mm)"
                        )

                # Compare outer diameter (smaller is better for navigability)
                phys_od = phys_dev.specifications.outer_diameter_distal.mm
                rep_od = rep_dev.specifications.outer_diameter_distal.mm
                if phys_od and rep_od:
                    if rep_od < phys_od:
                        advantages.append(
                            f"Lower profile OD ({rep_od}mm vs {phys_od}mm) — better navigability"
                        )
                    elif rep_od > phys_od:
                        disadvantages.append(
                            f"Larger OD ({rep_od}mm vs {phys_od}mm)"
                        )

                # Compare length
                phys_len = phys_dev.specifications.length.cm
                rep_len = rep_dev.specifications.length.cm
                if phys_len and rep_len and abs(rep_len - phys_len) > 1:
                    if rep_len > phys_len:
                        advantages.append(
                            f"Longer working length ({rep_len}cm vs {phys_len}cm)"
                        )

                comparisons.append(DeviceSpecComparison(
                    physician_device_id=phys_dev.id,
                    physician_device_name=phys_dev.device_name,
                    physician_manufacturer=phys_dev.manufacturer,
                    rep_device_id=rep_dev.id,
                    rep_device_name=rep_dev.device_name,
                    rep_manufacturer=rep_dev.manufacturer,
                    spec_advantages=advantages,
                    spec_disadvantages=disadvantages,
                ))

        return comparisons

    def _get_competitive_claims(
        self, rep_company: str, physician_devices: List[Device]
    ) -> List[Dict]:
        """Pull relevant marketing claims for both the rep and physician's manufacturers."""
        claims = []
        physician_manufacturers = list({d.manufacturer for d in physician_devices})

        intel = self.data_manager.competitive_intel

        # Get claims for physician's manufacturers
        for mfr in physician_manufacturers:
            mfr_claims = intel.get(mfr, intel.get(mfr.lower(), {}))
            if isinstance(mfr_claims, dict):
                for claim_type, claim_list in mfr_claims.items():
                    if isinstance(claim_list, list):
                        for claim in claim_list[:3]:
                            claims.append({
                                "manufacturer": mfr,
                                "type": claim_type,
                                "claim": claim if isinstance(claim, str) else str(claim),
                                "side": "physician",
                            })

        # Get claims for rep's company
        rep_claims = intel.get(rep_company, intel.get(rep_company.lower(), {}))
        if isinstance(rep_claims, dict):
            for claim_type, claim_list in rep_claims.items():
                if isinstance(claim_list, list):
                    for claim in claim_list[:3]:
                        claims.append({
                            "manufacturer": rep_company,
                            "type": claim_type,
                            "claim": claim if isinstance(claim, str) else str(claim),
                            "side": "rep",
                        })

        return claims[:20]  # Cap at 20 claims

    def _check_cross_compatibility(
        self, physician_devices: List[Device], rep_devices: List[Device]
    ) -> List[CompatibilityInsight]:
        """Check which rep devices are physically compatible with physician's devices."""
        insights = []

        for rep_dev in rep_devices:
            for phys_dev in physician_devices:
                # Check if rep device fits inside physician's device
                compat = self.compatibility_engine.check_compatibility(
                    rep_dev.id, phys_dev.id
                )
                if compat.get("compatible"):
                    insights.append(CompatibilityInsight(
                        rep_device_id=rep_dev.id,
                        rep_device_name=rep_dev.device_name,
                        physician_device_id=phys_dev.id,
                        physician_device_name=phys_dev.device_name,
                        compatible=True,
                        fit_type=compat.get("fit_type"),
                        clearance_mm=compat.get("clearance_mm"),
                        explanation=f"{rep_dev.device_name} fits inside {phys_dev.device_name}",
                    ))

                # Check reverse direction
                compat_rev = self.compatibility_engine.check_compatibility(
                    phys_dev.id, rep_dev.id
                )
                if compat_rev.get("compatible"):
                    insights.append(CompatibilityInsight(
                        rep_device_id=rep_dev.id,
                        rep_device_name=rep_dev.device_name,
                        physician_device_id=phys_dev.id,
                        physician_device_name=phys_dev.device_name,
                        compatible=True,
                        fit_type=compat_rev.get("fit_type"),
                        clearance_mm=compat_rev.get("clearance_mm"),
                        explanation=f"{phys_dev.device_name} fits inside {rep_dev.device_name}",
                    ))

        return insights

    def _generate_migration_path(
        self,
        physician_devices: List[Device],
        rep_devices: List[Device],
        compatibility_insights: List[CompatibilityInsight],
    ) -> List[MigrationStep]:
        """Generate recommended device migration order (easiest first)."""
        steps = []
        order = 1

        # Compatible devices go first (lowest disruption)
        compatible_rep_ids = {ci.rep_device_id for ci in compatibility_insights if ci.compatible}
        for rep_dev in rep_devices:
            if rep_dev.id in compatible_rep_ids:
                steps.append(MigrationStep(
                    order=order,
                    action=f"Introduce {rep_dev.device_name} as adjunct/alternative",
                    rationale=f"Cross-compatible with physician's existing stack — minimal workflow disruption",
                    disruption_level="low",
                ))
                order += 1

        # Then category-matched devices not already included
        for rep_dev in rep_devices:
            if rep_dev.id not in compatible_rep_ids:
                matching_phys = [
                    pd for pd in physician_devices
                    if pd.category.key == rep_dev.category.key
                ]
                if matching_phys:
                    steps.append(MigrationStep(
                        order=order,
                        action=f"Replace {matching_phys[0].device_name} with {rep_dev.device_name}",
                        rationale=f"Same category ({rep_dev.category.display_name}) — direct swap",
                        disruption_level="medium",
                    ))
                    order += 1

        return steps[:6]  # Cap at 6 steps

    def _generate_talking_points(
        self,
        physician_devices: List[Device],
        rep_devices: List[Device],
        request: MeetingPrepRequest,
    ) -> List[TalkingPoint]:
        """Generate evidence-backed talking points."""
        points = []

        # Point 1: Cross-compatibility advantage
        phys_manufacturers = list({d.manufacturer for d in physician_devices})
        if phys_manufacturers:
            points.append(TalkingPoint(
                headline=f"Works with your existing {phys_manufacturers[0]} setup",
                detail=f"Our devices are designed with cross-manufacturer compatibility in mind. "
                       f"You don't need to replace your entire stack — you can integrate our products "
                       f"alongside your current {phys_manufacturers[0]} devices.",
                evidence_type="workflow",
                citations=[f"[SPECS:id={rd.id}]" for rd in rep_devices[:2]],
            ))

        # Point 2: Spec advantages
        for rep_dev in rep_devices[:2]:
            matching = [pd for pd in physician_devices if pd.category.key == rep_dev.category.key]
            if matching:
                phys_dev = matching[0]
                rep_id = rep_dev.specifications.inner_diameter.mm
                phys_id = phys_dev.specifications.inner_diameter.mm
                if rep_id and phys_id and rep_id > phys_id:
                    points.append(TalkingPoint(
                        headline=f"{rep_dev.product_name}: Larger lumen for better device passage",
                        detail=f"With a {rep_id}mm inner diameter compared to {phys_id}mm on your "
                               f"{phys_dev.product_name}, you get improved device delivery and aspiration flow.",
                        evidence_type="spec_advantage",
                        citations=[f"[SPECS:id={rep_dev.id}]", f"[SPECS:id={phys_dev.id}]"],
                    ))

        # Point 3: Clinical evidence (if retriever available)
        if self.retriever:
            device_names = " ".join([d.device_name for d in rep_devices[:3]])
            try:
                results = self.retriever.retrieve(
                    query=f"{device_names} clinical outcomes first pass recanalization",
                    top_k=3,
                )
                for result in results[:1]:
                    points.append(TalkingPoint(
                        headline="Clinical evidence supporting improved outcomes",
                        detail=result.get("text", "")[:200],
                        evidence_type="clinical_data",
                        citations=[f"[{result.get('source_type', 'DOC').upper()}:{result.get('file_name', '')}]"],
                    ))
            except Exception:
                pass

        # Point 4: Meeting-context-aware point
        if request.meeting_context:
            points.append(TalkingPoint(
                headline="Tailored to this conversation",
                detail=f"Given the context of this meeting ({request.meeting_context}), focus on demonstrating "
                       f"incremental value — show how {request.rep_company} devices solve a specific pain point "
                       f"rather than asking for a full stack change.",
                evidence_type="workflow",
                citations=[],
            ))

        return points[:5]  # Cap at 5 talking points

    def _generate_objection_playbook(
        self,
        physician_devices: List[Device],
        rep_devices: List[Device],
        request: MeetingPrepRequest,
    ) -> List[ObjectionResponse]:
        """Generate predicted objections with recommended responses."""
        objections = []
        phys_manufacturers = list({d.manufacturer for d in physician_devices})
        phys_mfr = phys_manufacturers[0] if phys_manufacturers else "their current vendor"

        # Known objections get priority
        if request.known_objections:
            objections.append(ObjectionResponse(
                objection=request.known_objections,
                likelihood="high",
                recommended_response=f"Acknowledge their concern directly. Present evidence that addresses "
                                     f"this specific issue. Reference compatible products that minimize disruption.",
                supporting_data=[f"[SPECS:id={rd.id}]" for rd in rep_devices[:2]],
            ))

        # Standard objection set
        objections.append(ObjectionResponse(
            objection=f"I'm happy with my current {phys_mfr} setup",
            likelihood="high",
            recommended_response=f"Acknowledge their satisfaction — they've built a strong workflow. Position your "
                                 f"device as an addition, not a replacement. Highlight the specific clinical scenario "
                                 f"where your device provides an advantage their current stack doesn't cover.",
            supporting_data=[f"Cross-compatible with {d.device_name}" for d in physician_devices[:2]],
        ))

        objections.append(ObjectionResponse(
            objection="Show me the clinical data",
            likelihood="high",
            recommended_response=f"Be ready with specific trial results, case studies, and outcome data. "
                                 f"Focus on metrics this physician cares about: first-pass recanalization rates, "
                                 f"time-to-reperfusion, and safety profile.",
            supporting_data=["Reference IFU clinical data sections", "Cite peer-reviewed publications"],
        ))

        objections.append(ObjectionResponse(
            objection="Your device costs too much",
            likelihood="medium",
            recommended_response=f"Reframe from per-unit cost to total procedure cost and outcomes. "
                                 f"If first-pass rates improve, total costs decrease through fewer passes, "
                                 f"shorter procedures, and reduced complications.",
            supporting_data=["Total cost of procedure analysis", "Reduced re-intervention rates"],
        ))

        objections.append(ObjectionResponse(
            objection="I don't want to retrain my team on new devices",
            likelihood="medium",
            recommended_response=f"Emphasize the similarity in technique. Offer hands-on training, proctored cases, "
                                 f"and technical support. Highlight cross-compatibility so the learning curve is minimal.",
            supporting_data=[f"Similar deployment technique to {phys_mfr} devices"],
        ))

        objections.append(ObjectionResponse(
            objection="My hospital has a contract with another vendor",
            likelihood="medium" if request.hospital_type.value in ["academic", "community"] else "low",
            recommended_response=f"Ask about evaluation pathways and trial programs. Many hospitals allow "
                                 f"physicians to request new products through formulary committees or VAC reviews. "
                                 f"Offer clinical and economic data to support the evaluation.",
            supporting_data=["Offer trial/evaluation program", "Provide health economics data"],
        ))

        return objections[:6]

    def _infer_personality_traits(self, request: MeetingPrepRequest) -> Dict[str, float]:
        """Infer personality traits based on hospital type and case volume."""
        base_traits = {
            "evidence_driven": 0.7,
            "cautious": 0.5,
            "open_to_new": 0.5,
            "cost_conscious": 0.5,
            "brand_loyal": 0.5,
            "relationship_oriented": 0.6,
        }

        if request.hospital_type.value == "academic":
            base_traits["evidence_driven"] = 0.9
            base_traits["open_to_new"] = 0.7
            base_traits["cost_conscious"] = 0.4
        elif request.hospital_type.value == "community":
            base_traits["cost_conscious"] = 0.7
            base_traits["brand_loyal"] = 0.6
        elif request.hospital_type.value == "rural":
            base_traits["cost_conscious"] = 0.8
            base_traits["cautious"] = 0.7
            base_traits["brand_loyal"] = 0.7
        elif request.hospital_type.value == "private_practice":
            base_traits["cost_conscious"] = 0.6
            base_traits["relationship_oriented"] = 0.8

        if request.annual_case_volume:
            if request.annual_case_volume >= 100:
                base_traits["open_to_new"] = min(base_traits["open_to_new"] + 0.15, 1.0)
                base_traits["evidence_driven"] = min(base_traits["evidence_driven"] + 0.1, 1.0)
            elif request.annual_case_volume <= 40:
                base_traits["cautious"] = min(base_traits["cautious"] + 0.15, 1.0)

        return base_traits

    def _infer_clinical_priorities(self, brief: IntelligenceBrief) -> List[str]:
        """Infer clinical priorities from the brief data."""
        priorities = ["patient_outcomes", "procedural_efficiency"]

        if brief.inferred_approach == "aspiration-first":
            priorities.append("first_pass_effect")
            priorities.append("aspiration_force")
        elif brief.inferred_approach == "stent-retriever-first":
            priorities.append("stent_integration")
            priorities.append("vessel_preservation")
        else:
            priorities.append("combined_technique")
            priorities.append("first_pass_effect")

        if brief.hospital_type == "academic":
            priorities.append("clinical_evidence")
        elif brief.hospital_type in ("community", "rural"):
            priorities.append("cost_effectiveness")

        return priorities[:5]

    def _infer_decision_style(self, request: MeetingPrepRequest) -> str:
        """Infer decision-making style."""
        if request.hospital_type.value == "academic":
            return "data-driven"
        elif request.hospital_type.value == "rural":
            return "experience-based"
        elif request.annual_case_volume and request.annual_case_volume >= 100:
            return "data-driven"
        else:
            return "relationship-based"

    def _case_volume_tier(self, volume: Optional[int]) -> str:
        """Classify case volume into tiers."""
        if not volume:
            return "medium"
        if volume >= 100:
            return "high"
        elif volume >= 50:
            return "medium"
        else:
            return "low"
