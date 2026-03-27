"""
JSON file-based persistence service for MedSync AI Sales Intelligence Platform.

Provides lightweight data persistence using JSON files for the beta/demo version.
No database required — all data stored in the data/ directory.
"""

import json
import threading
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

from ..config import get_settings
from ..models.rep_profile import ActivityLogEntry, RepProfile


class PersistenceService:
    """JSON file-based persistence layer for rep profiles, activity logs, and more."""

    def __init__(self, data_dir: Optional[Path] = None):
        if data_dir is None:
            data_dir = get_settings().data_dir
        self.data_dir = Path(data_dir)
        self._lock = threading.Lock()

    def _load_json(self, filename: str) -> dict:
        """Load a JSON file from the data directory. Returns empty dict if not found."""
        filepath = self.data_dir / filename
        if not filepath.exists():
            return {}
        try:
            with open(filepath, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}

    def _save_json(self, filename: str, data: dict) -> None:
        """Save data to a JSON file in the data directory."""
        filepath = self.data_dir / filename
        with self._lock:
            with open(filepath, "w") as f:
                json.dump(data, f, indent=2, default=str)

    # --- Rep Profiles ---

    def save_rep_profile(self, profile: RepProfile) -> None:
        """Save or update a rep profile."""
        data = self._load_json("rep_profiles.json")
        if "profiles" not in data:
            data["profiles"] = {}
        data["profiles"][profile.rep_id] = profile.model_dump()
        self._save_json("rep_profiles.json", data)

    def get_rep_profile(self, rep_id: str) -> Optional[dict]:
        """Get a rep profile by ID."""
        data = self._load_json("rep_profiles.json")
        return data.get("profiles", {}).get(rep_id)

    def get_all_rep_profiles(self) -> List[dict]:
        """Get all rep profiles."""
        data = self._load_json("rep_profiles.json")
        return list(data.get("profiles", {}).values())

    # --- Activity Logging ---

    def log_activity(self, entry: ActivityLogEntry) -> None:
        """Log a new activity entry."""
        data = self._load_json("rep_activity.json")
        if "entries" not in data:
            data["entries"] = []
        data["entries"].append(entry.model_dump())
        self._save_json("rep_activity.json", data)

        # Also update last_active on rep profile
        profile_data = self._load_json("rep_profiles.json")
        if "profiles" in profile_data and entry.rep_id in profile_data["profiles"]:
            profile_data["profiles"][entry.rep_id]["last_active"] = entry.timestamp
            self._save_json("rep_profiles.json", profile_data)

    def get_rep_activities(
        self, rep_id: str, limit: int = 50, activity_type: Optional[str] = None
    ) -> List[dict]:
        """Get activity log for a specific rep."""
        data = self._load_json("rep_activity.json")
        entries = data.get("entries", [])

        # Filter by rep_id
        filtered = [e for e in entries if e.get("rep_id") == rep_id]

        # Filter by activity_type if specified
        if activity_type:
            filtered = [e for e in filtered if e.get("activity_type") == activity_type]

        # Sort by timestamp descending (most recent first)
        filtered.sort(key=lambda e: e.get("timestamp", ""), reverse=True)

        return filtered[:limit]

    def get_all_activities(self, limit: int = 200) -> List[dict]:
        """Get all activity entries across all reps."""
        data = self._load_json("rep_activity.json")
        entries = data.get("entries", [])
        entries.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
        return entries[:limit]

    # --- Dashboard Aggregation ---

    def get_rep_dashboard_data(self, rep_id: str) -> dict:
        """Compute aggregated dashboard data for a rep."""
        activities = self.get_rep_activities(rep_id, limit=500)

        # Filter to scored activities only
        scored = [a for a in activities if a.get("scores")]

        # Dimension averages across all scored sessions
        dimension_totals: Dict[str, List[float]] = {}
        for a in scored:
            for dim, score in (a.get("scores") or {}).items():
                if dim not in dimension_totals:
                    dimension_totals[dim] = []
                dimension_totals[dim].append(score)

        dimension_averages = {
            dim: round(sum(vals) / len(vals), 3) if vals else 0
            for dim, vals in dimension_totals.items()
        }

        # Score history (chronological)
        score_history = []
        for a in reversed(scored):  # oldest first
            score_history.append({
                "date": a.get("timestamp", ""),
                "overall_score": a.get("overall_score", 0),
                "mode": a.get("mode", ""),
                "activity_type": a.get("activity_type", ""),
            })

        # Streak calculation
        activity_dates = set()
        for a in activities:
            ts = a.get("timestamp", "")
            if ts:
                try:
                    date_str = ts[:10]  # YYYY-MM-DD
                    activity_dates.add(date_str)
                except (ValueError, IndexError):
                    pass

        streak_current = 0
        streak_longest = 0
        if activity_dates:
            sorted_dates = sorted(activity_dates, reverse=True)
            today = datetime.utcnow().strftime("%Y-%m-%d")

            # Current streak
            current = 0
            check_date = datetime.utcnow()
            for i in range(365):
                d = (check_date - __import__("datetime").timedelta(days=i)).strftime("%Y-%m-%d")
                if d in activity_dates:
                    current += 1
                elif i == 0:
                    continue  # today might not have activity yet
                else:
                    break
            streak_current = current

            # Longest streak
            longest = 1
            run = 1
            for i in range(1, len(sorted_dates)):
                prev = datetime.strptime(sorted_dates[i - 1], "%Y-%m-%d")
                curr = datetime.strptime(sorted_dates[i], "%Y-%m-%d")
                if (prev - curr).days == 1:
                    run += 1
                    longest = max(longest, run)
                else:
                    run = 1
            streak_longest = longest if sorted_dates else 0

        # Weak dimensions (bottom 3)
        weak_dimensions = []
        if dimension_averages:
            sorted_dims = sorted(dimension_averages.items(), key=lambda x: x[1])
            for dim, avg in sorted_dims[:3]:
                suggestion = _get_improvement_suggestion(dim)
                weak_dimensions.append({
                    "name": dim.replace("_", " ").title(),
                    "key": dim,
                    "avg_score": round(avg, 2),
                    "suggestion": suggestion,
                })

        # Recent activity (last 10)
        recent = activities[:10]

        return {
            "rep_id": rep_id,
            "total_sessions": len([a for a in activities if a.get("activity_type") in ("simulation", "assessment")]),
            "total_qa_queries": len([a for a in activities if a.get("activity_type") == "qa_session"]),
            "total_activities": len(activities),
            "dimension_averages": dimension_averages,
            "score_history": score_history,
            "streak_current": streak_current,
            "streak_longest": streak_longest,
            "weak_dimensions": weak_dimensions,
            "recent_activity": recent,
        }

    # --- Team Aggregation (for Manager) ---

    def get_team_overview(self) -> dict:
        """Get aggregated team overview for manager console."""
        profiles = self.get_all_rep_profiles()
        all_activities = self.get_all_activities(limit=1000)

        team = []
        for profile in profiles:
            rep_id = profile.get("rep_id", "")
            rep_activities = [a for a in all_activities if a.get("rep_id") == rep_id]
            scored = [a for a in rep_activities if a.get("scores")]

            # Compute averages
            overall_scores = [a.get("overall_score", 0) for a in scored if a.get("overall_score")]
            avg_score = round(sum(overall_scores) / len(overall_scores), 2) if overall_scores else 0

            # Find weakest dimension
            dim_totals: Dict[str, List[float]] = {}
            for a in scored:
                for dim, score in (a.get("scores") or {}).items():
                    if dim not in dim_totals:
                        dim_totals[dim] = []
                    dim_totals[dim].append(score)
            dim_avgs = {d: sum(v) / len(v) for d, v in dim_totals.items()} if dim_totals else {}
            weakest = min(dim_avgs, key=dim_avgs.get) if dim_avgs else ""

            team.append({
                "rep_id": rep_id,
                "name": profile.get("name", ""),
                "company": profile.get("company", ""),
                "role": profile.get("role", "rep"),
                "session_count": len([a for a in rep_activities if a.get("activity_type") in ("simulation", "assessment")]),
                "total_activities": len(rep_activities),
                "avg_score": avg_score,
                "last_active": profile.get("last_active", ""),
                "weakest_dimension": weakest.replace("_", " ").title() if weakest else "N/A",
            })

        # Team-level dimension aggregates
        all_scored = [a for a in all_activities if a.get("scores")]
        team_dim_totals: Dict[str, List[float]] = {}
        for a in all_scored:
            for dim, score in (a.get("scores") or {}).items():
                if dim not in team_dim_totals:
                    team_dim_totals[dim] = []
                team_dim_totals[dim].append(score)
        team_dimension_averages = {
            d: round(sum(v) / len(v), 3) for d, v in team_dim_totals.items()
        }

        return {
            "team": team,
            "total_reps": len(profiles),
            "total_sessions": len([a for a in all_activities if a.get("activity_type") in ("simulation", "assessment")]),
            "team_dimension_averages": team_dimension_averages,
        }

    # --- Assignments ---

    def save_assignment(self, assignment: dict) -> None:
        """Save a training assignment."""
        data = self._load_json("assignments.json")
        if "assignments" not in data:
            data["assignments"] = []
        data["assignments"].append(assignment)
        self._save_json("assignments.json", data)

    def get_assignments(self, rep_id: Optional[str] = None) -> List[dict]:
        """Get assignments, optionally filtered by rep."""
        data = self._load_json("assignments.json")
        assignments = data.get("assignments", [])
        if rep_id:
            assignments = [a for a in assignments if a.get("assigned_to") == rep_id]
        return assignments

    def update_assignment(self, assignment_id: str, updates: dict) -> bool:
        """Update an assignment's fields."""
        data = self._load_json("assignments.json")
        for a in data.get("assignments", []):
            if a.get("assignment_id") == assignment_id:
                a.update(updates)
                self._save_json("assignments.json", data)
                return True
        return False

    # --- Field Intel ---

    def save_field_debrief(self, debrief: dict) -> None:
        """Save a field debrief."""
        data = self._load_json("field_intel.json")
        if "debriefs" not in data:
            data["debriefs"] = []
        data["debriefs"].append(debrief)
        self._save_json("field_intel.json", data)

    def get_field_debriefs(
        self, rep_id: Optional[str] = None, limit: int = 50
    ) -> List[dict]:
        """Get field debriefs, optionally filtered by rep."""
        data = self._load_json("field_intel.json")
        debriefs = data.get("debriefs", [])
        if rep_id:
            debriefs = [d for d in debriefs if d.get("rep_id") == rep_id]
        debriefs.sort(key=lambda d: d.get("timestamp", ""), reverse=True)
        return debriefs[:limit]

    # --- Certifications ---

    def save_certification(self, cert: dict) -> None:
        """Save an earned certification."""
        data = self._load_json("certifications.json")
        if "earned" not in data:
            data["earned"] = []
        data["earned"].append(cert)
        self._save_json("certifications.json", data)

    def get_rep_certifications(self, rep_id: str) -> List[dict]:
        """Get certifications earned by a rep."""
        data = self._load_json("certifications.json")
        return [c for c in data.get("earned", []) if c.get("rep_id") == rep_id]

    # --- IFU Tracking ---

    def save_ifu_tracking(self, tracking_data: dict) -> None:
        """Save IFU tracking data."""
        self._save_json("ifu_tracking.json", tracking_data)

    def get_ifu_tracking(self) -> dict:
        """Get IFU tracking data."""
        return self._load_json("ifu_tracking.json")


def _get_improvement_suggestion(dimension: str) -> str:
    """Return a contextual improvement suggestion for a weak dimension."""
    suggestions = {
        "clinical_accuracy": "Review clinical trial data in the Knowledge Base. Focus on key trial endpoints and patient outcomes.",
        "spec_accuracy": "Practice device specifications using Product Knowledge Assessment. Focus on dimensions, compatibility, and materials.",
        "regulatory_compliance": "Review IFU documents for your portfolio. Pay attention to contraindications, warnings, and on-label boundaries.",
        "competitive_knowledge": "Run Competitor Deep Dive sessions. Study how your devices compare on key differentiators.",
        "objection_handling": "Practice Objection Handling Drills. Prepare evidence-based responses to common physician concerns.",
        "procedural_workflow": "Use the Procedure Workflow Visualizer to understand device stacking and compatibility.",
        "closing_effectiveness": "Focus on tying clinical evidence to the physician's specific priorities and patient population.",
    }
    return suggestions.get(dimension, "Continue practicing to improve in this area.")


@lru_cache(maxsize=1)
def get_persistence_service() -> PersistenceService:
    """Get the singleton PersistenceService instance."""
    return PersistenceService()
