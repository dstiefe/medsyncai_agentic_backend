"""
Structured Assessment API router for MedSync AI Sales Intelligence Platform.

Provides endpoints to generate, submit, and retrieve scored assessments.
Assessments are structured exams (not chat-based) with MC, write-in, and matching questions.
"""

import logging
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..services.assessment_service import AssessmentService, get_assessment_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/assessment", tags=["assessment"])


# --- Request / Response Models ---


class GenerateAssessmentRequest(BaseModel):
    """Request to generate a new structured assessment."""
    rep_company: str = Field(..., description="Rep's company for relevant questions")
    difficulty_level: str = Field(default="intermediate", description="beginner, intermediate, experienced")
    rep_name: str = Field(default="", description="Rep name for personalization")
    rep_id: str = Field(default="", description="Rep ID for tracking")
    question_count: int = Field(default=15, ge=5, le=25, description="Number of questions to generate")


class SubmissionEntry(BaseModel):
    """A single question answer submission."""
    question_id: str
    rep_answer: str  # For matching, this is a JSON string of {"left": "right"} pairs


class SubmitAssessmentRequest(BaseModel):
    """Request to submit answers for scoring."""
    submissions: List[SubmissionEntry]


# --- Endpoints ---


@router.post("/generate")
async def generate_assessment(request: GenerateAssessmentRequest):
    """
    Generate a new structured assessment.

    The LLM creates questions from document chunks organized by category.
    Questions are returned WITHOUT correct answers (stored server-side).
    """
    try:
        service = get_assessment_service()
        result = await service.generate_assessment(
            rep_company=request.rep_company,
            difficulty_level=request.difficulty_level,
            rep_name=request.rep_name,
            rep_id=request.rep_id,
            question_count=request.question_count,
        )
        return result

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Error generating assessment")
        raise HTTPException(status_code=500, detail=f"Failed to generate assessment: {str(e)}")


@router.post("/{assessment_id}/submit")
async def submit_assessment(assessment_id: str, request: SubmitAssessmentRequest):
    """
    Submit answers for a generated assessment and receive scores.

    MC answers are scored directly. Write-in answers are evaluated by LLM.
    Matching answers are compared pair by pair.
    """
    try:
        service = get_assessment_service()
        submissions = [s.model_dump() for s in request.submissions]
        results = await service.score_assessment(assessment_id, submissions)
        return results

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("Error scoring assessment")
        raise HTTPException(status_code=500, detail=f"Failed to score assessment: {str(e)}")


@router.get("/{assessment_id}/results")
async def get_assessment_results(assessment_id: str):
    """
    Retrieve stored results for a completed assessment.
    """
    service = get_assessment_service()
    results = service.get_results(assessment_id)
    if not results:
        raise HTTPException(status_code=404, detail=f"Results not found for assessment {assessment_id}")
    return results
