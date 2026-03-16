"""
Deterministic score calculation for sales simulation scoring.

Extracted from scoring_service.py — pure Python, no LLM calls.
All scoring math is auditable and unit-testable.
"""

from typing import Dict, List, Tuple


# Default scoring dimensions with equal weights
DEFAULT_WEIGHTS = {
    "clinical_accuracy": 1 / 7,
    "spec_accuracy": 1 / 7,
    "regulatory_compliance": 1 / 7,
    "competitive_knowledge": 1 / 7,
    "objection_handling": 1 / 7,
    "procedural_workflow": 1 / 7,
    "closing_effectiveness": 1 / 7,
}


def normalize_score(raw_score: float, scale_max: float = 3.0) -> float:
    """Normalize a raw score (0-scale_max) to 0-1 range."""
    return min(1.0, max(0.0, raw_score / scale_max))


def calculate_weighted_overall(
    dimension_scores: Dict[str, float],
    weights: Dict[str, float] = None,
) -> float:
    """Calculate weighted overall score from dimension scores (already 0-1)."""
    if not dimension_scores:
        return 0.0

    w = weights or DEFAULT_WEIGHTS
    total_weight = 0.0
    weighted_sum = 0.0

    for dim_name, weight in w.items():
        score = dimension_scores.get(dim_name, 0.0)
        weighted_sum += score * weight
        total_weight += weight

    return weighted_sum / total_weight if total_weight > 0 else 0.0


def identify_strengths_and_gaps(
    dimension_averages: Dict[str, float],
    strength_threshold: float = 0.75,
    gap_threshold: float = 0.50,
) -> Tuple[List[str], List[str]]:
    """Identify strong and weak dimensions from averaged scores."""
    strengths = []
    gaps = []

    for dim_name, score in dimension_averages.items():
        label = dim_name.replace("_", " ").title()
        if score > strength_threshold:
            strengths.append(f"{label}: {score:.0%}")
        elif score < gap_threshold:
            gaps.append(f"{label}: {score:.0%}")

    return strengths, gaps


def compute_trend(turn_overalls: List[float]) -> str:
    """Determine performance trend from turn-level overall scores."""
    if len(turn_overalls) < 3:
        return "insufficient_data"

    early = sum(turn_overalls[:3]) / 3
    late = sum(turn_overalls[-3:]) / 3

    if late > early + 0.1:
        return "improving"
    elif late < early - 0.1:
        return "declining"
    return "stable"


def pass_fail(percentage: float, threshold: float = 70.0) -> str:
    """Determine pass/fail from a percentage score."""
    return "pass" if percentage >= threshold else "fail"
