"""
Simulation orchestrator for MedSync AI Sales Simulation Engine.

Main controller for managing simulation sessions and processing conversation turns.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Dict, List, Optional

from ..config import get_settings
from ..models.device import Device
from ..models.simulation_state import (
    SimulationMode,
    SimulationSession,
    SimulationStatus,
    Turn,
)
from ..prompts.system_prompts import get_physician_prompt, get_system_prompt
from ..rag.citation_manager import CitationManager
from .data_loader import DataManager
from .device_service import DeviceService
from .llm_service import LLMService
from .rag_service import RAGService
from .scoring_service import ScoringService


# Module-level session storage
ACTIVE_SESSIONS: Dict[str, SimulationSession] = {}


class CompatibilityEngine:
    """Compatibility engine for checking device compatibility."""

    def __init__(self, data_manager: DataManager):
        """Initialize compatibility engine."""
        self.data_manager = data_manager
        self.compat_matrix = data_manager.compatibility_matrix

    def check_compatibility(
        self, device_id1: int, device_id2: int
    ) -> Dict:
        """Check if two devices are compatible."""
        # Simplified compatibility check
        device1 = self.data_manager.get_device(device_id1)
        device2 = self.data_manager.get_device(device_id2)

        if not device1 or not device2:
            return {"compatible": False, "reason": "Device not found"}

        # In a real implementation, this would check the compatibility matrix
        return {"compatible": True, "details": "Compatibility check available"}


class SimulationOrchestrator:
    """Main orchestrator for simulation sessions."""

    def __init__(self, data_manager: DataManager, config=None):
        """
        Initialize SimulationOrchestrator.

        Args:
            data_manager: The DataManager instance
            config: Optional configuration object
        """
        self.data_manager = data_manager
        self.config = config or get_settings()

        # Initialize services
        self.device_service = DeviceService(data_manager)
        self.compatibility_engine = CompatibilityEngine(data_manager)
        self.rag_service = RAGService(data_manager, config)
        self.llm_service = LLMService(config)
        self.citation_manager = CitationManager(data_manager)
        self.scoring_service = ScoringService(self.llm_service)

    def create_session(
        self,
        mode: str,
        physician_profile_id: str,
        rep_company: str,
        rep_name: str = "",
        difficulty_level: str = "intermediate",
        sub_mode: str = "",
        session_id: Optional[str] = None,
    ) -> SimulationSession:
        """
        Create a new simulation session.

        Args:
            mode: The simulation mode (e.g., 'competitive_sales_call')
            physician_profile_id: ID of the physician profile
            rep_company: Name of the rep's company
            rep_name: Sales rep's name for personalized interactions
            difficulty_level: Difficulty level (beginner, intermediate, experienced)
            sub_mode: Sub-mode (conversational, structured) for product_knowledge
            session_id: Optional custom session ID

        Returns:
            The created SimulationSession
        """
        if not session_id:
            session_id = f"sim_{uuid.uuid4().hex[:8]}"

        # Look up physician profile
        physician_profile = self._get_physician_profile(physician_profile_id)

        # Get rep's device portfolio
        rep_portfolio = self.device_service.get_portfolio(rep_company)
        rep_portfolio_ids = [device.id for device in rep_portfolio]

        # Create session
        session = SimulationSession(
            session_id=session_id,
            mode=SimulationMode(mode),
            status=SimulationStatus.SETUP,
            physician_profile=physician_profile,
            rep_company=rep_company,
            rep_name=rep_name,
            difficulty_level=difficulty_level,
            sub_mode=sub_mode,
            rep_portfolio_ids=rep_portfolio_ids,
            scenario_context={
                "briefing": f"Sales call with {physician_profile.name} at {physician_profile.institution}",
                "objective": f"Discuss {rep_company} devices for {physician_profile.specialty} procedures",
            },
        )

        # Store in active sessions
        ACTIVE_SESSIONS[session_id] = session

        return session

    def _get_enriched_physician_prompt(self, session: SimulationSession) -> str:
        """Build physician prompt, enriched with dossier data if available."""
        physician_info = {
            "name": session.physician_profile.name,
            "specialty": session.physician_profile.specialty,
            "institution": session.physician_profile.institution,
            "institution_type": session.physician_profile.institution_type,
            "years_experience": session.physician_profile.years_experience,
            "case_volume": session.physician_profile.case_volume,
            "technique_preference": session.physician_profile.technique_preference,
            "clinical_priorities": session.physician_profile.clinical_priorities,
            "personality_traits": session.physician_profile.personality_traits,
            "objection_patterns": session.physician_profile.objection_patterns,
            "decision_style": session.physician_profile.decision_style,
        }

        physician_prompt = get_physician_prompt(
            physician_info,
            rep_name=session.rep_name,
            rep_company=session.rep_company,
        )

        # Inject dossier summary for richer context if physician comes from dossier
        try:
            from ..services.dossier_service import get_dossier_service
            dossier_svc = get_dossier_service()
            dossier_summary = dossier_svc.get_prompt_summary(session.physician_profile.id)
            if dossier_summary:
                physician_prompt += (
                    "\n\n=== DETAILED PHYSICIAN DOSSIER ===\n"
                    "Use this real-world data to inform your responses. Reference specific details "
                    "about your practice, preferences, and experience when relevant.\n\n"
                    f"{dossier_summary}\n"
                    "=== END DOSSIER ==="
                )
        except Exception as e:
            logger.debug(f"No dossier enrichment for {session.physician_profile.id}: {e}")

        return physician_prompt

    async def generate_opening(self, session: SimulationSession) -> str:
        """
        Generate an LLM-powered physician opening message to start the conversation.

        The physician introduces themselves and sets the tone for the meeting.
        """
        physician_prompt = self._get_enriched_physician_prompt(session)

        rep_label = session.rep_name or "a sales representative"
        opening_instruction = (
            f"{rep_label} from {session.rep_company} has just arrived for a scheduled meeting. "
            "You are the physician. Greet them briefly and set the tone for the conversation. "
            "Stay in character — mention what you're interested in discussing or what your time constraints are. "
            "Keep it to 2-3 sentences."
        )

        response = await self.llm_service.generate(
            system_prompt=physician_prompt,
            messages=[{"role": "user", "content": opening_instruction}],
            temperature=0.8,
            max_tokens=300,
        )

        # Store as first physician turn
        physician_turn = Turn(
            turn_number=0,
            timestamp=datetime.utcnow(),
            speaker="physician",
            message=response,
            citations=[],
            scores=None,
            context_metadata={"ai_generated": True, "opening": True},
        )
        session.turns.append(physician_turn)

        return response

    async def process_turn(
        self, session: SimulationSession, user_message: str
    ) -> Turn:
        """
        Process a turn in the simulation.

        Handles the complete workflow: context assembly, LLM generation, citation
        extraction, and scoring.

        Args:
            session: The SimulationSession
            user_message: The user's message

        Returns:
            The created Turn object
        """
        # Update session status
        session.status = SimulationStatus.ACTIVE

        # Step 1: Assemble RAG context
        context = self.rag_service.assemble_context(session, user_message)

        # Step 2: Build conversation history
        history = self._build_conversation_history(session)

        # Step 3: Get mode-specific system prompt
        system_prompt = self._get_system_prompt(session)

        # Inject citation instructions
        system_prompt = self.citation_manager.inject_citation_instructions(
            system_prompt
        )

        # Step 4: Call LLM
        llm_response = await self.llm_service.generate(
            system_prompt=system_prompt,
            messages=history + [{"role": "user", "content": user_message}],
            context=context,
            temperature=0.7,
            max_tokens=1500,
        )

        # Step 5: Extract citations
        citations = self.citation_manager.extract_citations(llm_response)

        # Step 6: Score the user's message
        turn_number = len(session.turns) + 1
        try:
            turn_score = await self.scoring_service.score_turn(
                session,
                turn_number,
            )
            scores = turn_score.dimension_scores
        except Exception:
            # If scoring fails, continue without scores
            scores = {}

        # Step 7: Create turn and add to session
        turn = Turn(
            turn_number=turn_number,
            timestamp=datetime.utcnow(),
            speaker="user",
            message=user_message,
            citations=citations,
            scores=scores,
            context_metadata={
                "context_length": len(context),
                "rag_results_used": True,
            },
        )

        session.turns.append(turn)

        # Step 8: Generate physician response
        physician_response = await self._generate_physician_response(
            session, llm_response
        )

        physician_turn = Turn(
            turn_number=turn_number + 1,
            timestamp=datetime.utcnow(),
            speaker="physician",
            message=physician_response,
            citations=[],
            scores=None,
            context_metadata={"ai_generated": True},
        )

        session.turns.append(physician_turn)

        # Update session timestamp
        session.updated_at = datetime.utcnow()

        # Check if we should end the session
        if turn_number >= self.config.max_simulation_turns:
            session.status = SimulationStatus.COMPLETED

        # Return the physician turn (contains the AI response)
        return physician_turn

    async def _generate_physician_response(
        self, session: SimulationSession, rep_message: str
    ) -> str:
        """
        Generate a physician response to the rep's message.

        Args:
            session: The SimulationSession
            rep_message: The rep's message

        Returns:
            The physician's response
        """
        physician_prompt = self._get_enriched_physician_prompt(session)

        # Get recent conversation context
        recent_messages = self._build_conversation_history(session)[-4:]

        # Generate physician response
        rep_label = session.rep_name or "Rep"
        response = await self.llm_service.generate(
            system_prompt=physician_prompt,
            messages=recent_messages
            + [{"role": "user", "content": f"{rep_label}: {rep_message}"}],
            temperature=0.8,
            max_tokens=500,
        )

        return response

    def _get_system_prompt(self, session: SimulationSession) -> str:
        """Get mode-specific system prompt."""
        # Use conversational quiz prompt for product_knowledge + conversational sub-mode
        if session.mode.value == "product_knowledge" and session.sub_mode == "conversational":
            from ..prompts.mode_conversational_quiz import get_conversational_quiz_prompt
            return get_conversational_quiz_prompt(
                difficulty=session.difficulty_level,
                rep_name=session.rep_name,
                rep_company=session.rep_company,
            )

        return get_system_prompt(
            session.mode.value,
            rep_name=session.rep_name,
            rep_company=session.rep_company,
        )

    def _build_conversation_history(
        self, session: SimulationSession
    ) -> List[dict]:
        """
        Build conversation history for LLM context.

        Args:
            session: The SimulationSession

        Returns:
            List of message dicts for LLM
        """
        messages = []

        for turn in session.turns:
            role = "assistant" if turn.speaker == "user" else "user"
            messages.append({"role": role, "content": turn.message})

        return messages

    async def get_session_summary(self, session: SimulationSession) -> dict:
        """
        Get a summary of the simulation session.

        Args:
            session: The SimulationSession

        Returns:
            Summary dictionary with aggregated metrics
        """
        # Get full scores if available
        session_score = None
        try:
            session_score = await self.scoring_service.score_session(session)
        except Exception:
            pass

        # Build summary
        summary = {
            "session_id": session.session_id,
            "mode": session.mode.value,
            "status": session.status.value,
            "physician": {
                "name": session.physician_profile.name,
                "specialty": session.physician_profile.specialty,
                "institution": session.physician_profile.institution,
            },
            "rep_company": session.rep_company,
            "total_turns": len(session.turns),
            "duration_seconds": (
                (session.updated_at - session.created_at).total_seconds()
                if session.updated_at
                else 0
            ),
        }

        if session_score:
            summary["scoring"] = {
                "overall_average": session_score.overall_average,
                "dimension_averages": session_score.dimension_averages,
                "trend": session_score.trend,
                "strengths": session_score.strengths,
                "improvement_areas": session_score.improvement_areas,
            }

        return summary

    def _get_physician_profile(self, profile_id: str):
        """
        Get physician profile by ID from the defined profiles.

        Args:
            profile_id: The profile ID (e.g., 'dr_chen', 'dr_rodriguez')

        Returns:
            PhysicianProfile object
        """
        from ..models.physician_profile import PhysicianProfile, DeviceStackEntry
        from ..prompts.system_prompts import PHYSICIAN_PROFILES

        # Look up the profile from system_prompts definitions
        prompt_profile = PHYSICIAN_PROFILES.get(profile_id)

        if prompt_profile:
            # Build device stack from the profile's current_stack dict
            device_stack = []
            for role, device_name in prompt_profile.current_stack.items():
                device_stack.append(
                    DeviceStackEntry(
                        role=role,
                        device_name=device_name,
                        device_id=0,
                        manufacturer="",
                    )
                )

            return PhysicianProfile(
                id=prompt_profile.profile_id,
                name=prompt_profile.name,
                specialty=prompt_profile.specialty,
                institution=prompt_profile.hospital_type,
                institution_type=prompt_profile.hospital_type.lower().replace(" ", "_"),
                case_volume=prompt_profile.annual_cases,
                case_volume_tier="high" if prompt_profile.annual_cases >= 100 else "medium" if prompt_profile.annual_cases >= 50 else "low",
                years_experience=prompt_profile.experience_years,
                technique_preference=prompt_profile.technique_preference,
                current_device_stack=device_stack,
                clinical_priorities=prompt_profile.clinical_priorities,
                personality_traits=prompt_profile.personality_traits,
                objection_patterns=[],
                decision_style=prompt_profile.decision_style,
            )

        # Fallback: check physician dossier system
        from ..services.dossier_service import get_dossier_service

        dossier_svc = get_dossier_service()
        dossier = dossier_svc.get_dossier(profile_id)

        if dossier:
            # Build device stack from dossier's current devices
            device_stack = []
            for dev in dossier.competitive_landscape.current_devices:
                device_stack.append(
                    DeviceStackEntry(
                        role=dev.category or "unknown",
                        device_name=dev.device or "",
                        device_id=0,
                        manufacturer=dev.manufacturer or "",
                    )
                )

            # Compute total procedural volume
            total_procedures = sum(
                cv.annual_services
                for cv in dossier.business_intelligence.case_volumes
                if cv.cpt_code.startswith(("36", "37", "61", "75"))
            )

            # Synthesize clinical priorities from dossier data
            clinical_priorities = []
            if dossier.clinical_profile.preferred_techniques:
                clinical_priorities.append(
                    f"Prefers {', '.join(dossier.clinical_profile.preferred_techniques)}"
                )
            if dossier.clinical_profile.clinical_trial_involvement:
                clinical_priorities.append("Active in clinical trials")
            if dossier.clinical_profile.kol_status and dossier.clinical_profile.kol_status != "none":
                clinical_priorities.append(f"KOL ({dossier.clinical_profile.kol_status})")
            if not clinical_priorities:
                clinical_priorities = ["safety", "efficacy"]

            technique = "combined"
            if dossier.clinical_profile.preferred_techniques:
                technique = dossier.clinical_profile.preferred_techniques[0].lower()

            return PhysicianProfile(
                id=dossier.id,
                name=dossier.name,
                specialty=dossier.specialty or "neurovascular",
                institution=dossier.institution or "Unknown",
                institution_type=(dossier.institution_type or "academic").lower().replace(" ", "_"),
                case_volume=total_procedures or 100,
                case_volume_tier="high" if total_procedures >= 100 else "medium" if total_procedures >= 50 else "low",
                years_experience=dossier.years_experience or 10,
                technique_preference=technique,
                current_device_stack=device_stack,
                clinical_priorities=clinical_priorities,
                personality_traits=dossier.personality_traits or {"evidence_driven": 0.7},
                objection_patterns=dossier.competitive_landscape.known_objections or [],
                decision_style=dossier.decision_making.decision_style or "data-driven",
            )

        # Final fallback for truly unknown profiles
        return PhysicianProfile(
            id=profile_id,
            name=profile_id.replace("_", " ").title(),
            specialty="neurovascular",
            institution="Unknown",
            institution_type="academic",
            case_volume=100,
            case_volume_tier="medium",
            years_experience=10,
            technique_preference="combined",
            current_device_stack=[],
            clinical_priorities=["safety", "efficacy"],
            personality_traits={"evidence_driven": 0.7},
            objection_patterns=[],
            decision_style="data-driven",
        )


def get_session(session_id: str) -> Optional[SimulationSession]:
    """
    Get an active session by ID.

    Args:
        session_id: The session ID

    Returns:
        The SimulationSession, or None if not found
    """
    return ACTIVE_SESSIONS.get(session_id)


def list_active_sessions() -> List[str]:
    """
    List all active session IDs.

    Returns:
        List of active session IDs
    """
    return list(ACTIVE_SESSIONS.keys())


def delete_session(session_id: str) -> bool:
    """
    Delete a session.

    Args:
        session_id: The session ID

    Returns:
        True if session was deleted, False if not found
    """
    if session_id in ACTIVE_SESSIONS:
        del ACTIVE_SESSIONS[session_id]
        return True
    return False
