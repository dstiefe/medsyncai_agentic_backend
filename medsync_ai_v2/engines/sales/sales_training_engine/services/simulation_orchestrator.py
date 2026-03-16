"""
Simulation orchestrator for MedSync AI Sales Simulation Engine.
Main controller for managing simulation sessions and processing conversation turns.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Dict, List, Optional

from ..models.device import Device
from ..models.simulation_state import (
    SimulationMode,
    SimulationSession,
    SimulationStatus,
    Turn,
)
from .system_prompts import get_physician_prompt, get_system_prompt, PHYSICIAN_PROFILES
from ..rag.citation_manager import CitationManager
from .data_loader import DataManager
from .device_service import DeviceService
from .llm_adapter import SalesLLMAdapter
from .rag_service import RAGService
from .scoring_service import ScoringService

MAX_SIMULATION_TURNS = 20

# Module-level session storage
ACTIVE_SESSIONS: Dict[str, SimulationSession] = {}


class CompatibilityEngine:
    """Compatibility engine for checking device compatibility."""

    def __init__(self, data_manager: DataManager):
        self.data_manager = data_manager
        self.compat_matrix = data_manager.compatibility_matrix

    def check_compatibility(self, device_id1: int, device_id2: int) -> Dict:
        device1 = self.data_manager.get_device(device_id1)
        device2 = self.data_manager.get_device(device_id2)
        if not device1 or not device2:
            return {"compatible": False, "reason": "Device not found"}
        return {"compatible": True, "details": "Compatibility check available"}


class SimulationOrchestrator:
    """Main orchestrator for simulation sessions."""

    def __init__(self, data_manager: DataManager):
        self.data_manager = data_manager
        self.device_service = DeviceService(data_manager)
        self.compatibility_engine = CompatibilityEngine(data_manager)
        self.rag_service = RAGService(data_manager)
        self.llm_service = SalesLLMAdapter()
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
        if not session_id:
            session_id = f"sim_{uuid.uuid4().hex[:8]}"

        physician_profile = self._get_physician_profile(physician_profile_id)
        rep_portfolio = self.device_service.get_portfolio(rep_company)
        rep_portfolio_ids = [device.id for device in rep_portfolio]

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

        ACTIVE_SESSIONS[session_id] = session
        return session

    async def generate_opening(self, session: SimulationSession) -> str:
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
        session.status = SimulationStatus.ACTIVE

        context = self.rag_service.assemble_context(session, user_message)
        history = self._build_conversation_history(session)
        system_prompt = self._get_system_prompt(session)
        system_prompt = self.citation_manager.inject_citation_instructions(system_prompt)

        llm_response = await self.llm_service.generate(
            system_prompt=system_prompt,
            messages=history + [{"role": "user", "content": user_message}],
            context=context,
            temperature=0.7,
            max_tokens=1500,
        )

        citations = self.citation_manager.extract_citations(llm_response)

        turn_number = len(session.turns) + 1
        try:
            turn_score = await self.scoring_service.score_turn(session, turn_number)
            scores = turn_score.dimension_scores
        except Exception:
            scores = {}

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

        physician_response = await self._generate_physician_response(session, llm_response)
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
        session.updated_at = datetime.utcnow()

        if turn_number >= MAX_SIMULATION_TURNS:
            session.status = SimulationStatus.COMPLETED

        return physician_turn

    async def _generate_physician_response(
        self, session: SimulationSession, rep_message: str
    ) -> str:
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

        recent_messages = self._build_conversation_history(session)[-4:]
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
        if session.mode.value == "product_knowledge" and session.sub_mode == "conversational":
            # Load conversational quiz reference
            from pathlib import Path
            ref_path = Path(__file__).resolve().parent.parent / "references" / "conversational_quiz.md"
            if ref_path.exists():
                return ref_path.read_text(encoding="utf-8")
            # Fallback to standard prompt
            return get_system_prompt(session.mode.value, rep_name=session.rep_name, rep_company=session.rep_company)

        return get_system_prompt(
            session.mode.value,
            rep_name=session.rep_name,
            rep_company=session.rep_company,
        )

    def _build_conversation_history(self, session: SimulationSession) -> List[dict]:
        messages = []
        for turn in session.turns:
            role = "assistant" if turn.speaker == "user" else "user"
            messages.append({"role": role, "content": turn.message})
        return messages

    async def get_session_summary(self, session: SimulationSession) -> dict:
        session_score = None
        try:
            session_score = await self.scoring_service.score_session(session)
        except Exception:
            pass

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
        from ..models.physician_profile import PhysicianProfile, DeviceStackEntry

        prompt_profile = PHYSICIAN_PROFILES.get(profile_id)

        if prompt_profile:
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

        # Fallback for unknown profiles
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
    return ACTIVE_SESSIONS.get(session_id)


def list_active_sessions() -> List[str]:
    return list(ACTIVE_SESSIONS.keys())


def delete_session(session_id: str) -> bool:
    if session_id in ACTIVE_SESSIONS:
        del ACTIVE_SESSIONS[session_id]
        return True
    return False
