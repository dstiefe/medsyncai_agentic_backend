"""
Scoring service for MedSync AI Sales Simulation Engine.
Evaluates sales rep performance across multiple dimensions.
"""

from __future__ import annotations

import json
from typing import Dict, List, Optional

from ..models.scoring import SCORING_DIMENSIONS, SimulationScore, TurnScore
from ..models.simulation_state import SimulationSession
from .llm_adapter import SalesLLMAdapter


class ScoringService:
    """Service for evaluating simulation performance."""

    def __init__(self, llm_service: SalesLLMAdapter):
        self.llm_service = llm_service

    async def score_turn(
        self, session: SimulationSession, turn_number: int
    ) -> TurnScore:
        if turn_number < 1 or turn_number > len(session.turns):
            raise ValueError(f"Invalid turn number: {turn_number}")

        turn = session.turns[turn_number - 1]
        if turn.speaker != "user":
            raise ValueError("Can only score sales rep turns (speaker='user')")

        eval_prompt = self._build_evaluation_prompt(session, turn)
        evaluation = await self.llm_service.evaluate(eval_prompt, turn.message)

        dimension_scores = {}
        feedback = {}
        flags = []

        if "error" not in evaluation:
            dimensions = evaluation.get("dimensions", {})
            for dim_name in SCORING_DIMENSIONS:
                score = dimensions.get(dim_name, 0)
                dimension_scores[dim_name] = min(1.0, max(0.0, score / 3.0))
            feedback = evaluation.get("feedback", {})
            flags = evaluation.get("flags", [])

        overall = self._calculate_overall_score(dimension_scores)

        return TurnScore(
            turn_number=turn_number,
            dimension_scores=dimension_scores,
            overall=overall,
            feedback=feedback,
            flags=flags,
        )

    async def score_session(self, session: SimulationSession) -> SimulationScore:
        turn_scores = []
        for i, turn in enumerate(session.turns):
            if turn.speaker == "user":
                try:
                    turn_score = await self.score_turn(session, i + 1)
                    turn_scores.append(turn_score)
                except Exception:
                    continue

        dimension_averages = {}
        if turn_scores:
            for dim_name in SCORING_DIMENSIONS:
                scores = [ts.dimension_scores.get(dim_name, 0) for ts in turn_scores]
                dimension_averages[dim_name] = sum(scores) / len(scores) if scores else 0

        overall_average = self._calculate_overall_score(dimension_averages)
        trend = [ts.overall for ts in turn_scores]
        strengths, improvements = self._analyze_performance(dimension_averages, turn_scores)

        return SimulationScore(
            session_id=session.session_id,
            total_turns=len(turn_scores),
            dimension_averages=dimension_averages,
            overall_average=overall_average,
            trend=trend,
            strengths=strengths,
            improvement_areas=improvements,
        )

    def _build_evaluation_prompt(self, session: SimulationSession, turn) -> str:
        physician = session.physician_profile
        prompt = f"""You are an expert sales coach evaluating a medical device sales rep's performance in a simulated call with a physician.

Context:
- Physician: {physician.name}, {physician.specialty} specialist
- Institution: {physician.institution}
- Case Volume: {physician.case_volume} procedures/year
- Current Focus: {physician.clinical_priorities}
- Physician's Current Company: {session.physician_profile.current_device_stack[0].manufacturer if session.physician_profile.current_device_stack else "Unknown"}
- Rep's Company: {session.rep_company}

Evaluate the rep's message on these dimensions (scale 0-3):

{self._format_rubrics()}

Respond with ONLY valid JSON in this exact format:
{{
  "dimensions": {{
    "clinical_accuracy": <score 0-3>,
    "spec_accuracy": <score 0-3>,
    "regulatory_compliance": <score 0-3>,
    "competitive_knowledge": <score 0-3>,
    "objection_handling": <score 0-3>,
    "procedural_workflow": <score 0-3>,
    "closing_effectiveness": <score 0-3>
  }},
  "feedback": {{
    "clinical_accuracy": "<brief feedback>",
    "spec_accuracy": "<brief feedback>"
  }},
  "flags": ["<flag1>", "<flag2>"]
}}

Flags might include: clinical_error, spec_error, compliance_issue, unsupported_claim, etc.
Keep feedback concise (1-2 sentences per dimension)."""
        return prompt

    def _format_rubrics(self) -> str:
        rubric_text = ""
        for dim_name, dim_info in SCORING_DIMENSIONS.items():
            rubric_text += f"\n{dim_info['name']} ({dim_name}):\n"
            rubric_text += f"  Description: {dim_info['description']}\n"
            rubric_text += f"  Rubric: {dim_info['rubric']}\n"
        return rubric_text

    def _calculate_overall_score(self, dimension_scores: Dict[str, float]) -> float:
        if not dimension_scores:
            return 0.0
        total_weight = 0.0
        weighted_sum = 0.0
        for dim_name, dim_info in SCORING_DIMENSIONS.items():
            score = dimension_scores.get(dim_name, 0)
            weight = dim_info.get("weight", 1 / 7)
            weighted_sum += score * weight
            total_weight += weight
        return weighted_sum / total_weight if total_weight > 0 else 0.0

    def _analyze_performance(
        self, dimension_averages: Dict[str, float], turn_scores: List[TurnScore]
    ) -> tuple:
        strengths = []
        improvements = []
        for dim_name, score in dimension_averages.items():
            if score > 0.75:
                dim_info = SCORING_DIMENSIONS.get(dim_name, {})
                strengths.append(f"{dim_info.get('name', dim_name)}: {score:.0%}")
        for dim_name, score in dimension_averages.items():
            if score < 0.50:
                dim_info = SCORING_DIMENSIONS.get(dim_name, {})
                improvements.append(f"{dim_info.get('name', dim_name)}: {score:.0%}")
        if len(turn_scores) >= 3:
            early_avg = sum(ts.overall for ts in turn_scores[:3]) / 3
            late_avg = sum(ts.overall for ts in turn_scores[-3:]) / 3
            if late_avg > early_avg + 0.1:
                improvements.append("Note: Performance improved significantly over time")
        flag_count = sum(len(ts.flags) for ts in turn_scores)
        if flag_count > 3:
            improvements.append(f"Multiple issues detected ({flag_count} flags) - review feedback")
        return strengths, improvements
