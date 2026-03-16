"""
Assessment service for MedSync AI Sales Simulation Engine.
Handles product knowledge assessments, quiz generation, and scoring.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from functools import lru_cache
from typing import Any, Dict, List, Optional

from .data_loader import DataManager, get_data_manager
from .llm_adapter import SalesLLMAdapter
from .persistence_service import PersistenceService, get_persistence_service


class AssessmentQuestion:
    """Represents a single assessment question."""

    def __init__(
        self,
        question_id: str,
        question_text: str,
        question_type: str,
        options: Optional[List[str]] = None,
        correct_answer: Optional[str] = None,
        explanation: Optional[str] = None,
        difficulty: str = "intermediate",
        category: str = "general",
        device_ids: Optional[List[int]] = None,
    ):
        self.question_id = question_id
        self.question_text = question_text
        self.question_type = question_type  # "multiple_choice", "true_false", "write_in"
        self.options = options or []
        self.correct_answer = correct_answer
        self.explanation = explanation
        self.difficulty = difficulty
        self.category = category
        self.device_ids = device_ids or []

    def to_dict(self) -> dict:
        return {
            "question_id": self.question_id,
            "question_text": self.question_text,
            "question_type": self.question_type,
            "options": self.options,
            "correct_answer": self.correct_answer,
            "explanation": self.explanation,
            "difficulty": self.difficulty,
            "category": self.category,
            "device_ids": self.device_ids,
        }


class AssessmentSession:
    """Tracks an assessment session."""

    def __init__(
        self,
        session_id: str,
        rep_id: str,
        rep_company: str,
        assessment_type: str,
        questions: List[AssessmentQuestion],
    ):
        self.session_id = session_id
        self.rep_id = rep_id
        self.rep_company = rep_company
        self.assessment_type = assessment_type
        self.questions = questions
        self.answers: Dict[str, Any] = {}
        self.scores: Dict[str, float] = {}
        self.created_at = datetime.utcnow()
        self.completed_at: Optional[datetime] = None
        self.status = "in_progress"

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "rep_id": self.rep_id,
            "rep_company": self.rep_company,
            "assessment_type": self.assessment_type,
            "questions": [q.to_dict() for q in self.questions],
            "answers": self.answers,
            "scores": self.scores,
            "created_at": self.created_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "status": self.status,
        }


# Module-level session storage
ACTIVE_ASSESSMENTS: Dict[str, AssessmentSession] = {}


class AssessmentService:
    """Service for generating and scoring product knowledge assessments."""

    def __init__(
        self,
        data_manager: Optional[DataManager] = None,
        persistence_service: Optional[PersistenceService] = None,
    ):
        self.data_manager = data_manager or get_data_manager()
        self.persistence = persistence_service or get_persistence_service()
        self.llm = SalesLLMAdapter()

    async def generate_assessment(
        self,
        rep_id: str,
        rep_company: str,
        assessment_type: str = "product_knowledge",
        num_questions: int = 10,
        difficulty: str = "intermediate",
        focus_categories: Optional[List[str]] = None,
        focus_device_ids: Optional[List[int]] = None,
    ) -> AssessmentSession:
        """
        Generate a new assessment with questions.

        Args:
            rep_id: The sales rep's identifier
            rep_company: The rep's company name
            assessment_type: Type of assessment (product_knowledge, competitive, compliance)
            num_questions: Number of questions to generate
            difficulty: Difficulty level (beginner, intermediate, advanced)
            focus_categories: Optional device categories to focus on
            focus_device_ids: Optional specific device IDs to focus on

        Returns:
            AssessmentSession with generated questions
        """
        session_id = f"assess_{uuid.uuid4().hex[:8]}"

        # Gather context for question generation
        context = self._build_assessment_context(
            rep_company, focus_categories, focus_device_ids
        )

        # Generate questions using LLM
        questions = await self._generate_questions(
            context=context,
            assessment_type=assessment_type,
            num_questions=num_questions,
            difficulty=difficulty,
            rep_company=rep_company,
        )

        session = AssessmentSession(
            session_id=session_id,
            rep_id=rep_id,
            rep_company=rep_company,
            assessment_type=assessment_type,
            questions=questions,
        )

        ACTIVE_ASSESSMENTS[session_id] = session
        return session

    async def submit_answer(
        self,
        session_id: str,
        question_id: str,
        answer: str,
    ) -> Dict:
        """
        Submit an answer for a question and get immediate feedback.

        Args:
            session_id: The assessment session ID
            question_id: The question ID
            answer: The submitted answer

        Returns:
            Dict with: correct (bool), score (float), explanation (str)
        """
        session = ACTIVE_ASSESSMENTS.get(session_id)
        if not session:
            return {"error": "Session not found"}

        # Find the question
        question = None
        for q in session.questions:
            if q.question_id == question_id:
                question = q
                break

        if not question:
            return {"error": "Question not found"}

        # Score the answer
        if question.question_type == "write_in":
            result = await self._score_write_in(self.llm, question, answer)
        else:
            result = self._score_objective(question, answer)

        # Store the answer and score
        session.answers[question_id] = answer
        session.scores[question_id] = result.get("score", 0.0)

        # Check if assessment is complete
        if len(session.answers) >= len(session.questions):
            session.status = "completed"
            session.completed_at = datetime.utcnow()
            await self._save_assessment_result(session)

        return result

    async def get_assessment_results(self, session_id: str) -> Dict:
        """
        Get final results for a completed assessment.

        Args:
            session_id: The assessment session ID

        Returns:
            Dict with overall score, dimension breakdown, and recommendations
        """
        session = ACTIVE_ASSESSMENTS.get(session_id)
        if not session:
            return {"error": "Session not found"}

        if session.status != "completed":
            return {"error": "Assessment not yet completed"}

        # Calculate overall score
        scores = list(session.scores.values())
        overall_score = sum(scores) / len(scores) if scores else 0.0

        # Group scores by category
        category_scores: Dict[str, List[float]] = {}
        for q in session.questions:
            cat = q.category
            score = session.scores.get(q.question_id, 0.0)
            if cat not in category_scores:
                category_scores[cat] = []
            category_scores[cat].append(score)

        category_averages = {
            cat: sum(vals) / len(vals) for cat, vals in category_scores.items()
        }

        # Identify weak areas
        weak_areas = [
            cat for cat, avg in category_averages.items() if avg < 0.6
        ]

        return {
            "session_id": session_id,
            "overall_score": round(overall_score, 3),
            "total_questions": len(session.questions),
            "answered": len(session.answers),
            "category_averages": category_averages,
            "weak_areas": weak_areas,
            "status": session.status,
        }

    def _build_assessment_context(
        self,
        rep_company: str,
        focus_categories: Optional[List[str]],
        focus_device_ids: Optional[List[int]],
    ) -> str:
        """Build context string for question generation."""
        context_parts = []

        # Get rep's portfolio
        portfolio_devices = []
        for device_id, device in self.data_manager.devices.items():
            if device.manufacturer == rep_company:
                portfolio_devices.append(device)

        if portfolio_devices:
            context_parts.append(f"Rep's Portfolio ({rep_company}):")
            for d in portfolio_devices[:20]:
                context_parts.append(
                    f"  - {d.device_name} (ID: {d.id}, Category: {d.category.display_name})"
                )

        # Get focused devices
        if focus_device_ids:
            context_parts.append("\nFocus Devices:")
            for did in focus_device_ids:
                device = self.data_manager.get_device(did)
                if device:
                    context_parts.append(
                        f"  - {device.device_name} ({device.manufacturer})"
                    )

        # Get competitor devices
        competitor_devices = []
        for device_id, device in self.data_manager.devices.items():
            if device.manufacturer != rep_company:
                competitor_devices.append(device)

        if competitor_devices:
            context_parts.append(f"\nCompetitor Devices (sample):")
            for d in competitor_devices[:10]:
                context_parts.append(
                    f"  - {d.device_name} ({d.manufacturer}, {d.category.display_name})"
                )

        return "\n".join(context_parts)

    async def _generate_questions(
        self,
        context: str,
        assessment_type: str,
        num_questions: int,
        difficulty: str,
        rep_company: str,
    ) -> List[AssessmentQuestion]:
        """Generate assessment questions using LLM."""
        system_prompt = f"""You are a medical device sales training assessment generator.
Generate {num_questions} questions for a {difficulty}-level {assessment_type} assessment.
The sales rep works for {rep_company}.

Mix question types:
- multiple_choice (4 options, one correct)
- true_false
- write_in (short answer)

Categories to cover: specifications, clinical_applications, competitive_positioning,
regulatory_compliance, procedural_workflow.

Respond with ONLY valid JSON array of questions in this format:
[
  {{
    "question_text": "...",
    "question_type": "multiple_choice",
    "options": ["A) ...", "B) ...", "C) ...", "D) ..."],
    "correct_answer": "A",
    "explanation": "...",
    "difficulty": "{difficulty}",
    "category": "specifications"
  }}
]"""

        messages = [{"role": "user", "content": f"Context:\n{context}\n\nGenerate the assessment questions."}]

        response = await self.llm.generate(
            system_prompt=system_prompt,
            messages=messages,
            temperature=0.7,
            max_tokens=4000,
        )

        # Parse questions from response
        questions = []
        try:
            # Try to extract JSON from response
            json_start = response.find("[")
            json_end = response.rfind("]") + 1
            if json_start >= 0 and json_end > json_start:
                raw_questions = json.loads(response[json_start:json_end])
            else:
                raw_questions = json.loads(response)

            for i, q in enumerate(raw_questions):
                questions.append(
                    AssessmentQuestion(
                        question_id=f"q_{uuid.uuid4().hex[:6]}",
                        question_text=q.get("question_text", ""),
                        question_type=q.get("question_type", "multiple_choice"),
                        options=q.get("options", []),
                        correct_answer=q.get("correct_answer", ""),
                        explanation=q.get("explanation", ""),
                        difficulty=q.get("difficulty", difficulty),
                        category=q.get("category", "general"),
                    )
                )
        except (json.JSONDecodeError, KeyError, TypeError):
            # Fallback: create a single placeholder question
            questions.append(
                AssessmentQuestion(
                    question_id=f"q_{uuid.uuid4().hex[:6]}",
                    question_text="Assessment generation encountered an issue. Please try again.",
                    question_type="write_in",
                    correct_answer="N/A",
                    explanation="Question generation failed.",
                    difficulty=difficulty,
                    category="general",
                )
            )

        return questions

    def _score_objective(self, question: AssessmentQuestion, answer: str) -> Dict:
        """Score a multiple choice or true/false question."""
        # Normalize answer for comparison
        answer_normalized = answer.strip().upper()
        correct_normalized = (question.correct_answer or "").strip().upper()

        # Handle answers like "A" vs "A) ..."
        if len(answer_normalized) > 1 and answer_normalized[1] in ").:":
            answer_normalized = answer_normalized[0]
        if len(correct_normalized) > 1 and correct_normalized[1] in ").:":
            correct_normalized = correct_normalized[0]

        is_correct = answer_normalized == correct_normalized

        return {
            "correct": is_correct,
            "score": 1.0 if is_correct else 0.0,
            "correct_answer": question.correct_answer,
            "explanation": question.explanation or "",
        }

    async def _score_write_in(
        self, llm: SalesLLMAdapter, question: AssessmentQuestion, answer: str
    ) -> Dict:
        """Score a write-in question using LLM evaluation."""
        eval_prompt = f"""Evaluate this answer to a medical device sales knowledge question.

Question: {question.question_text}
Expected Answer: {question.correct_answer}
Given Answer: {answer}

Score from 0.0 to 1.0 based on accuracy and completeness.
Respond with ONLY valid JSON:
{{
  "score": <0.0-1.0>,
  "feedback": "<1-2 sentences>",
  "correct": <true/false>
}}"""

        evaluation = await llm.evaluate(eval_prompt, answer)

        return {
            "correct": evaluation.get("correct", False),
            "score": min(1.0, max(0.0, evaluation.get("score", 0.0))),
            "correct_answer": question.correct_answer,
            "explanation": evaluation.get("feedback", question.explanation or ""),
        }

    async def _save_assessment_result(self, session: AssessmentSession) -> None:
        """Save completed assessment results to persistence."""
        from ..models.rep_profile import ActivityLogEntry

        scores = list(session.scores.values())
        overall_score = sum(scores) / len(scores) if scores else 0.0

        entry = ActivityLogEntry(
            rep_id=session.rep_id,
            activity_type="assessment",
            mode=session.assessment_type,
            timestamp=datetime.utcnow().isoformat(),
            overall_score=round(overall_score, 3),
            scores=session.scores,
            metadata={
                "session_id": session.session_id,
                "total_questions": len(session.questions),
                "rep_company": session.rep_company,
            },
        )

        try:
            self.persistence.log_activity(entry)
        except Exception:
            pass


def get_assessment(session_id: str) -> Optional[AssessmentSession]:
    """Get an active assessment session."""
    return ACTIVE_ASSESSMENTS.get(session_id)


def list_active_assessments() -> List[str]:
    """List all active assessment session IDs."""
    return list(ACTIVE_ASSESSMENTS.keys())


@lru_cache(maxsize=1)
def get_assessment_service() -> AssessmentService:
    """Get singleton AssessmentService instance."""
    return AssessmentService()
