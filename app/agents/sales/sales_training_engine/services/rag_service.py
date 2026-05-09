"""
RAG (Retrieval-Augmented Generation) service for MedSync AI Sales Simulation Engine.

Assembles multi-layer context for LLM generation during simulations.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from ..config import get_settings
from ..models.simulation_state import SimulationSession
from ..rag.retrieval import VectorRetriever
from .data_loader import DataManager


class RAGService:
    """Assembles multi-layer context for each conversation turn."""

    # Safety keywords that trigger adverse event context
    SAFETY_KEYWORDS = {
        "safety",
        "adverse",
        "risk",
        "complication",
        "injury",
        "death",
        "mortality",
        "recall",
        "malfunction",
        "failure",
        "bleeding",
        "perforation",
        "dissection",
        "thrombosis",
    }

    def __init__(self, data_manager: DataManager, config=None):
        """
        Initialize RAGService.

        Args:
            data_manager: The DataManager instance
            config: Optional configuration object
        """
        self.data_manager = data_manager
        self.config = config or get_settings()
        self.retriever = VectorRetriever(
            data_manager, model_name=self.config.embedding_model
        )

    def assemble_context(self, session: SimulationSession, user_message: str) -> str:
        """
        Assemble comprehensive multi-layer context for a turn.

        Builds context string with these layers:

        LAYER 1 - PHYSICIAN PROFILE:
        Name, specialty, case volume, years experience, current device stack with specs,
        clinical priorities, technique preference

        LAYER 2 - DEVICE SPECIFICATIONS:
        For all devices mentioned in physician's stack AND rep's assigned portfolio,
        include: Device name, manufacturer, category, key specs, compatibility

        LAYER 3 - COMPETITIVE INTELLIGENCE:
        From competitive_intel.json, include for the physician's current manufacturer
        and rep's company: Marketing claims, key differentiators, positioning

        LAYER 4 - VECTOR RETRIEVAL:
        Use VectorRetriever to get top-k chunks relevant to user_message,
        formatted as: [SOURCE_TYPE:file_name] section_hint\n{text}

        LAYER 5 - PROCEDURAL CONTEXT:
        From compatibility_matrix, relevant procedural stacks for both companies

        LAYER 6 - ADVERSE EVENTS (if safety topic detected):
        If user_message contains safety/adverse/recall keywords, pull relevant data

        Args:
            session: The SimulationSession
            user_message: The user's current message

        Returns:
            Assembled context string
        """
        context_parts = []

        # LAYER 1: PHYSICIAN PROFILE
        physician_context = self._get_physician_profile_context(session)
        context_parts.append("=== PHYSICIAN PROFILE ===\n" + physician_context)

        # LAYER 2: DEVICE SPECIFICATIONS
        device_ids = self._extract_device_ids(session)
        if device_ids:
            device_context = self._get_device_specs_context(device_ids)
            context_parts.append("\n=== DEVICE SPECIFICATIONS ===\n" + device_context)

        # LAYER 3: COMPETITIVE INTELLIGENCE
        comp_context = self._get_competitive_context(
            session.physician_profile.current_device_stack[0].manufacturer
            if session.physician_profile.current_device_stack
            else "Unknown",
            session.rep_company,
        )
        if comp_context:
            context_parts.append("\n=== COMPETITIVE INTELLIGENCE ===\n" + comp_context)

        # LAYER 4: VECTOR RETRIEVAL
        rag_context = self._get_rag_chunks(user_message, k=8)
        if rag_context:
            context_parts.append("\n=== RELEVANT DOCUMENTS ===\n" + rag_context)

        # LAYER 5: PROCEDURAL CONTEXT
        proc_context = self._get_procedural_context(
            [
                session.physician_profile.current_device_stack[0].manufacturer
                if session.physician_profile.current_device_stack
                else "Unknown",
                session.rep_company,
            ]
        )
        if proc_context:
            context_parts.append("\n=== PROCEDURAL WORKFLOWS ===\n" + proc_context)

        # LAYER 6: ADVERSE EVENTS (if safety topic detected)
        if self._detect_safety_topic(user_message):
            safety_context = self._get_safety_context(user_message)
            if safety_context:
                context_parts.append("\n=== SAFETY & ADVERSE EVENTS ===\n" + safety_context)

        return "\n".join(context_parts)

    def _get_physician_profile_context(self, session: SimulationSession) -> str:
        """Extract physician profile context."""
        physician = session.physician_profile

        context = f"""Name: {physician.name}
Specialty: {physician.specialty}
Institution: {physician.institution} ({physician.institution_type})
Case Volume: {physician.case_volume} cases/year ({physician.case_volume_tier})
Years Experience: {physician.years_experience}
Technique Preference: {physician.technique_preference}

Current Device Stack:
"""
        for entry in physician.current_device_stack:
            context += f"  - {entry.role}: {entry.device_name} ({entry.manufacturer})\n"

        context += f"\nClinical Priorities: {', '.join(physician.clinical_priorities)}"
        context += f"\nPersonality Traits: {dict(physician.personality_traits)}"
        context += f"\nDecision Style: {physician.decision_style}"

        return context

    def _extract_device_ids(self, session: SimulationSession) -> List[int]:
        """Extract all relevant device IDs from session."""
        device_ids = set()

        # From physician's device stack
        for entry in session.physician_profile.current_device_stack:
            if entry.device_id:
                device_ids.add(entry.device_id)

        # From rep's portfolio
        device_ids.update(session.rep_portfolio_ids)

        return list(device_ids)

    def _get_device_specs_context(self, device_ids: List[int]) -> str:
        """Build device specifications context."""
        context = ""

        for device_id in device_ids:
            device = self.data_manager.get_device(device_id)
            if not device:
                continue

            context += f"\n{device.device_name}\n"
            context += f"  Manufacturer: {device.manufacturer}\n"
            context += f"  Category: {device.category.display_name} ({device.category.role})\n"
            context += f"  ID (mm/French): {device.specifications.inner_diameter.mm or device.specifications.inner_diameter.french}\n"
            context += f"  OD Distal: {device.specifications.outer_diameter_distal.mm or device.specifications.outer_diameter_distal.french}\n"
            context += f"  OD Proximal: {device.specifications.outer_diameter_proximal.mm or device.specifications.outer_diameter_proximal.french}\n"
            context += f"  Length: {device.specifications.length.cm or device.specifications.length.mm}\n"

            # Compatibility
            if device.compatibility.catheter_max_od.mm:
                context += f"  Max Catheter OD: {device.compatibility.catheter_max_od.mm}mm\n"
            if device.compatibility.guide_min_id.mm:
                context += f"  Guide Min ID: {device.compatibility.guide_min_id.mm}mm\n"

        return context

    def _get_competitive_context(
        self, physician_company: str, rep_company: str
    ) -> str:
        """Build competitive intelligence context."""
        context = ""

        intel = self.data_manager.competitive_intel

        if not intel or "manufacturers" not in intel:
            return ""

        manufacturers = intel["manufacturers"]

        # Physician's company context
        if physician_company in manufacturers:
            phys_intel = manufacturers[physician_company]
            context += f"\n{physician_company} (Physician's Current):\n"

            if "marketing_claims" in phys_intel:
                claims = phys_intel["marketing_claims"]
                if isinstance(claims, dict) and "feature_claims" in claims:
                    top_claims = claims.get("feature_claims", [])[:5]
                    if top_claims:
                        context += "  Top Marketing Claims:\n"
                        for claim in top_claims:
                            context += f"    - {claim}\n"

        # Rep's company context
        if rep_company in manufacturers:
            rep_intel = manufacturers[rep_company]
            context += f"\n{rep_company} (Rep's Company):\n"

            if "marketing_claims" in rep_intel:
                claims = rep_intel["marketing_claims"]
                if isinstance(claims, dict) and "feature_claims" in claims:
                    top_claims = claims.get("feature_claims", [])[:5]
                    if top_claims:
                        context += "  Top Marketing Claims:\n"
                        for claim in top_claims:
                            context += f"    - {claim}\n"

                # Competitive claims
                if "competitive_claims" in claims:
                    comp_claims = claims.get("competitive_claims", [])[:3]
                    if comp_claims:
                        context += "  Competitive Positioning:\n"
                        for claim in comp_claims:
                            context += f"    - {claim}\n"

        return context

    def _get_rag_chunks(self, query: str, k: int = 8) -> str:
        """Retrieve and format relevant document chunks."""
        context = ""

        try:
            results = self.retriever.retrieve(query, k=k)

            for result in results:
                context += f"\n[{result.source_type.upper()}:{result.file_name}] {result.section_hint}\n"
                context += f"(Manufacturer: {result.manufacturer})\n"
                context += result.text[:500] + "...\n"

        except Exception as e:
            # Log error but don't fail
            context = f"(RAG retrieval error: {str(e)})"

        return context

    def _get_procedural_context(self, companies: List[str]) -> str:
        """Build procedural workflow context from compatibility matrix."""
        context = ""

        compat_matrix = self.data_manager.compatibility_matrix

        if not compat_matrix or "procedural_stacks" not in compat_matrix:
            return ""

        stacks = compat_matrix.get("procedural_stacks", {})

        for company in companies:
            if company in stacks:
                company_stacks = stacks[company]
                context += f"\n{company} Procedural Stacks:\n"

                # Show first 2-3 stacks as examples
                for i, stack in enumerate(list(company_stacks.values())[:2]):
                    if isinstance(stack, dict) and "devices" in stack:
                        context += f"  Stack {i+1}:\n"
                        for device_entry in stack.get("devices", [])[:4]:
                            if isinstance(device_entry, dict):
                                context += f"    - {device_entry.get('role', 'unknown')}: {device_entry.get('device_name', 'N/A')}\n"

        return context

    def _get_safety_context(self, query: str) -> str:
        """Retrieve safety and adverse event information."""
        context = ""

        # Use section-specific retrieval for adverse events
        try:
            safety_results = self.retriever.retrieve_by_section(
                query, section="adverse_events", k=5
            )

            for result in safety_results:
                context += f"\n[ADVERSE EVENT] {result.file_name}\n"
                context += result.text[:400] + "...\n"

        except Exception:
            pass

        # Also include MAUDE data from competitive intel if available
        intel = self.data_manager.competitive_intel

        if intel and "manufacturers" in intel:
            for company, company_data in intel["manufacturers"].items():
                if "adverse_events_summary" in company_data:
                    summary = company_data["adverse_events_summary"]
                    if isinstance(summary, dict):
                        count = summary.get("total_events", 0)
                        if count > 0:
                            context += f"\n{company}: {count} reported adverse events"
                            serious = summary.get("serious_events", 0)
                            if serious:
                                context += f" ({serious} serious)"
                            context += "\n"

        return context

    def _detect_safety_topic(self, message: str) -> bool:
        """Detect if message contains safety-related topics."""
        message_lower = message.lower()

        for keyword in self.SAFETY_KEYWORDS:
            if keyword in message_lower:
                return True

        return False
