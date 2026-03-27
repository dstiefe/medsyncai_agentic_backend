"""
Scoring API router for MedSync AI Sales Simulation Engine.

Provides endpoints for accessing scoring dimensions and detailed turn-by-turn scoring.
"""

import logging
from typing import Dict, List

from fastapi import APIRouter, Depends, HTTPException

from ..models.scoring import SCORING_DIMENSIONS
from ..services.data_loader import DataManager, get_data_manager
from ..services.simulation_orchestrator import ACTIVE_SESSIONS, SimulationOrchestrator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/scoring", tags=["scoring"])


@router.get("/dimensions")
async def get_scoring_dimensions() -> Dict:
    """
    Get all scoring dimensions and their metadata.

    Returns:
        Dictionary with scoring dimensions and their descriptions
    """
    try:
        dimensions = []

        for dim_key, dim_data in SCORING_DIMENSIONS.items():
            dimensions.append({
                "key": dim_key,
                "name": dim_data["name"],
                "description": dim_data["description"],
                "weight": dim_data["weight"],
                "deterministic": dim_data["deterministic"],
                "rubric": dim_data["rubric"],
            })

        return {
            "dimensions": dimensions,
            "total": len(dimensions),
            "total_weight": sum(d["weight"] for d in dimensions),
        }

    except Exception as e:
        logger.exception("Error getting scoring dimensions")
        raise HTTPException(
            status_code=500,
            detail=f"Error getting dimensions: {str(e)}"
        )


@router.get("/{session_id}/detail")
async def get_detailed_scores(
    session_id: str,
    data_mgr: DataManager = Depends(get_data_manager),
) -> Dict:
    """
    Get detailed turn-by-turn scoring breakdown for a session.

    Path Parameters:
        session_id: The session ID

    Returns:
        Dictionary with per-turn scoring details and dimension feedback

    Raises:
        404: If session not found
    """
    try:
        session = ACTIVE_SESSIONS.get(session_id)

        if not session:
            raise HTTPException(
                status_code=404,
                detail=f"Session {session_id} not found"
            )

        # Build turn-by-turn scoring breakdown
        turns_breakdown = []

        for turn in session.turns:
            turn_scores = {
                "turn_number": turn.turn_number,
                "speaker": turn.speaker,
                "timestamp": turn.timestamp.isoformat() if hasattr(turn.timestamp, 'isoformat') else str(turn.timestamp),
                "message_length": len(turn.message),
                "dimension_scores": turn.scores or {},
                "citations_count": len(turn.citations),
                "feedback": turn.context_metadata.get("feedback", {}) if turn.context_metadata else {},
            }
            turns_breakdown.append(turn_scores)

        # Calculate dimension trends
        dimension_trends = {}
        for dim_key in SCORING_DIMENSIONS.keys():
            dimension_trends[dim_key] = []

            for turn in session.turns:
                if turn.scores and dim_key in turn.scores:
                    dimension_trends[dim_key].append(turn.scores[dim_key])

        return {
            "session_id": session_id,
            "total_turns": len(session.turns),
            "turns": turns_breakdown,
            "dimension_trends": dimension_trends,
            "metrics": {
                "total_messages": len(session.turns),
                "average_message_length": sum(len(t.message) for t in session.turns) / len(session.turns) if session.turns else 0,
                "total_citations": sum(len(t.citations) for t in session.turns),
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error getting detailed scores for session {session_id}")
        raise HTTPException(
            status_code=500,
            detail=f"Error getting detailed scores: {str(e)}"
        )
