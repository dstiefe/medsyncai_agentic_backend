# ─── v6 (Q&A v6 namespace) ─────────────────────────────────────────────
# This file lives under agents/qa_v6/ and is the active v6 copy of the
# Guideline Q&A pipeline. CMI matching logic is unchanged from v4 — the
# v6 rewrite targeted the general retrieval/scoring layer. The CMI path
# is only invoked when a patient scenario is present in the query.
# ───────────────────────────────────────────────────────────────────────
"""
Recommendation Matcher — CMI (Clinical Matching Index) adapted for guidelines.

Matches a parsed clinical query against pre-extracted recommendation criteria,
using the same tiering algorithm as Journal Search's TrialMatcher:

  1. Inverted Tiering (query → rec): How many query variables does the rec address?
  2. Applicability Gate: Does the query value fall outside the rec's criteria?
  3. Forward Tiering (rec → query): Does the rec require variables the query lacks?
  4. Scope Index: fraction of query variables addressed (threshold ≥ 0.6)

Pure Python. No LLM calls. Auditable and reproducible.

This is the guideline analog of:
  app/agents/journal_search/journal_search_engine/services/trial_matcher.py
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

from .schemas import CMIMatchedRecommendation, ParsedQAQuery

logger = logging.getLogger(__name__)


# ── Intervention synonym groups (shared with Journal Search) ──────

EVT_SYNONYMS = {
    "EVT", "THROMBECTOMY", "MECHANICAL THROMBECTOMY", "ENDOVASCULAR",
    "ENDOVASCULAR THERAPY", "ENDOVASCULAR TREATMENT",
}

IVT_SYNONYMS = {
    "IVT", "THROMBOLYSIS", "IV THROMBOLYSIS", "INTRAVENOUS THROMBOLYSIS",
}

ALTEPLASE_SYNONYMS = {"ALTEPLASE", "TPA", "T-PA", "RT-PA", "ACTIVASE"}
TENECTEPLASE_SYNONYMS = {"TENECTEPLASE", "TNK", "TNKASE"}

INTERVENTION_GROUPS = [EVT_SYNONYMS, IVT_SYNONYMS, ALTEPLASE_SYNONYMS, TENECTEPLASE_SYNONYMS]


# ── COR strength ordering (for tie-breaking within same tier) ─────

COR_SORT_ORDER = {
    "1": 0,
    "2a": 1,
    "2b": 2,
    "3: No Benefit": 3,
    "3:No Benefit": 3,
    "3: Harm": 4,
    "3:Harm": 4,
}

# ── Range fields that can be compared ────────────────────────────

RANGE_FIELDS = [
    "time_window_hours",
    "aspects_range",
    "pc_aspects_range",
    "nihss_range",
    "age_range",
    "premorbid_mrs",
    "core_volume_ml",
]


class RecommendationMatcher:
    """CMI-style matcher for guideline recommendations."""

    def __init__(self, criteria_path: Optional[str] = None):
        """
        Load pre-extracted recommendation criteria.

        Args:
            criteria_path: path to recommendation_criteria.json.
                If None, uses the default location in data/.
        """
        if criteria_path is None:
            criteria_path = os.path.join(
                os.path.dirname(__file__), "..", "..",
                "data", "recommendation_criteria.json",
            )

        if os.path.exists(criteria_path):
            with open(criteria_path) as f:
                self._criteria: Dict[str, Dict] = json.load(f)
            logger.info(
                "Loaded criteria for %d recommendations (%d with criteria)",
                len(self._criteria),
                sum(1 for v in self._criteria.values() if v.get("criteria_count", 0) > 0),
            )
        else:
            self._criteria = {}
            logger.warning("No recommendation_criteria.json found at %s", criteria_path)

        # Also need the full recommendation data for building results
        self._rec_store: Dict[str, Dict] = {}

    def set_recommendation_store(self, store: Dict[str, Any]) -> None:
        """Set the recommendation store for building full results."""
        self._rec_store = {}
        for rec_id, rec in store.items():
            if isinstance(rec, dict):
                self._rec_store[rec_id] = rec
            elif hasattr(rec, "model_dump"):
                self._rec_store[rec_id] = rec.model_dump()
            else:
                self._rec_store[rec_id] = vars(rec)

    @property
    def is_available(self) -> bool:
        """True if criteria have been loaded."""
        return len(self._criteria) > 0

    def match(self, query: ParsedQAQuery) -> List[CMIMatchedRecommendation]:
        """
        Run the CMI matching pipeline against all recommendations.

        Returns recommendations sorted by:
          tier ASC → COR strength → scope_index DESC
        """
        if not self._criteria:
            return []

        scenario_vars = query.get_scenario_variables()
        if not scenario_vars:
            return []

        results: List[CMIMatchedRecommendation] = []

        for rec_id, criteria in self._criteria.items():
            # Skip recs with no extractable criteria — they go through keyword path
            if criteria.get("criteria_count", 0) == 0:
                continue

            matched = self._evaluate_recommendation(query, scenario_vars, rec_id, criteria)
            if matched is not None:
                results.append(matched)

        # Sort: tier ASC, COR strength, scope DESC
        results.sort(key=lambda m: (
            m.tier,
            COR_SORT_ORDER.get(m.rec_data.get("cor", ""), 9),
            -m.scope_index,
        ))

        # Filter: only return Tier 1-2 recs (or Tier 3 with scope >= 0.5)
        # Tier 4 noise (scope < 0.25) is never useful for the user
        filtered = [
            r for r in results
            if r.tier <= 2
            or (r.tier == 3 and r.scope_index >= 0.5)
        ]

        # If no Tier 1-2 results, include Tier 3 as well
        if not any(r.tier <= 2 for r in filtered):
            filtered = [r for r in results if r.tier <= 3]

        return filtered

    def _evaluate_recommendation(
        self,
        query: ParsedQAQuery,
        scenario_vars: List[str],
        rec_id: str,
        criteria: Dict[str, Any],
    ) -> Optional[CMIMatchedRecommendation]:
        """
        Evaluate a single recommendation against the query using CMI.

        Returns None if the recommendation is excluded by the applicability gate.
        """
        # ── Step 1a: Inverted Tiering (query → rec) ──────────────
        # How many of the user's query variables does this rec address?
        present_in_rec = []
        missing_from_rec = []

        for var_name in scenario_vars:
            if self._rec_has_variable(var_name, criteria):
                present_in_rec.append(var_name)
            else:
                missing_from_rec.append(var_name)

        missing_count = len(missing_from_rec)
        if missing_count == 0:
            inverse_tier = 1
        elif missing_count == 1:
            inverse_tier = 2
        elif missing_count == 2:
            inverse_tier = 3
        else:
            inverse_tier = 4

        # ── Step 1b: Applicability Gate ──────────────────────────
        # Does the query value fall OUTSIDE the rec's criteria range?
        failed_criteria = []
        for var_name in present_in_rec:
            result = self._check_applicability(var_name, query, criteria)
            if result == "excluded":
                failed_criteria.append(var_name)

        if failed_criteria:
            # Query is outside this rec's criteria — exclude it
            logger.debug(
                "CMI: %s excluded — failed: %s",
                rec_id, ", ".join(failed_criteria),
            )
            return None

        # ── Step 1c: Forward Tiering (rec → query) ───────────────
        # What criteria does the rec define that the query doesn't specify?
        rec_vars = self._get_rec_variables(criteria)
        query_missing_for_rec = []

        for var_name in rec_vars:
            if var_name not in scenario_vars:
                # Rec requires this variable but user didn't specify it
                # Don't hard-penalize — user asked a focused question
                query_missing_for_rec.append(var_name)

        # Forward tier: only penalize if user specified AND conflicts
        fwd_conflicts = []
        for var_name in rec_vars:
            if var_name in scenario_vars:
                result = self._check_applicability(var_name, query, criteria)
                if result == "excluded":
                    fwd_conflicts.append(var_name)

        fwd_count = len(fwd_conflicts)
        if fwd_count == 0:
            forward_tier = 1
        elif fwd_count == 1:
            forward_tier = 2
        elif fwd_count == 2:
            forward_tier = 3
        else:
            forward_tier = 4

        # ── Final tier ───────────────────────────────────────────
        final_tier = min(max(inverse_tier, forward_tier), 4)

        # ── Scope Index ──────────────────────────────────────────
        scope_index = (
            len(present_in_rec) / len(scenario_vars)
            if scenario_vars else 0.0
        )

        # Build match details
        variable_results = {}
        for var_name in present_in_rec:
            variable_results[var_name] = self._compare_variable(var_name, query, criteria)

        match_details = {
            "inverse_tier": inverse_tier,
            "forward_tier": forward_tier,
            "scope_index": round(scope_index, 2),
            "scenario_vars": scenario_vars,
            "present_in_rec": present_in_rec,
            "missing_from_rec": missing_from_rec,
            "query_missing_for_rec": query_missing_for_rec,
            "failed_criteria": failed_criteria,
            "variable_results": variable_results,
        }

        # Build reason text
        reason_parts = []
        if inverse_tier == 1 and forward_tier == 1:
            reason_parts.append("Full match — rec addresses all query variables")
        else:
            if missing_from_rec:
                reason_parts.append(
                    f"Rec missing query variables: {', '.join(missing_from_rec)}"
                )
            if fwd_conflicts:
                reason_parts.append(
                    f"Query conflicts with rec criteria: {', '.join(fwd_conflicts)}"
                )

        # Get full recommendation data
        rec_data = self._rec_store.get(rec_id, {})
        if not rec_data:
            rec_data = {
                "id": rec_id,
                "section": criteria.get("section", ""),
                "cor": criteria.get("cor", ""),
                "loe": criteria.get("loe", ""),
            }

        return CMIMatchedRecommendation(
            rec_id=rec_id,
            tier=final_tier,
            scope_index=round(scope_index, 2),
            tier_reason="; ".join(reason_parts) if reason_parts else f"Tier {final_tier} match",
            match_details=match_details,
            rec_data=rec_data,
        )

    # ── Variable detection ───────────────────────────────────────

    @staticmethod
    def _rec_has_variable(var_name: str, criteria: Dict) -> bool:
        """Check if a recommendation's criteria address this variable."""
        if var_name in ("intervention", "circulation"):
            return criteria.get(var_name) is not None

        if var_name == "vessel_occlusion":
            val = criteria.get("vessel_occlusion")
            return val is not None and len(val) > 0

        # Range fields
        val = criteria.get(var_name)
        if val is None:
            return False
        if isinstance(val, dict):
            return val.get("min") is not None or val.get("max") is not None
        return False

    @staticmethod
    def _get_rec_variables(criteria: Dict) -> List[str]:
        """Get all variables that a recommendation defines criteria for."""
        variables = []
        if criteria.get("intervention"):
            variables.append("intervention")
        if criteria.get("circulation"):
            variables.append("circulation")
        if criteria.get("vessel_occlusion"):
            variables.append("vessel_occlusion")
        for field_name in RANGE_FIELDS:
            val = criteria.get(field_name)
            if val and isinstance(val, dict):
                if val.get("min") is not None or val.get("max") is not None:
                    variables.append(field_name)
        return variables

    # ── Applicability Gate ───────────────────────────────────────

    def _check_applicability(
        self, var_name: str, query: ParsedQAQuery, criteria: Dict
    ) -> str:
        """
        Check if the query's value passes the rec's criterion.

        Returns: "pass", "excluded", or "unknown"
        """
        # Pediatric/adult exclusion: §4.7.5 pediatric EVT rec (and any
        # rec whose section number starts with "4.7.5" or whose text
        # explicitly targets "pediatric") should not match adult queries.
        # Rationale: age>=6 numerically satisfies 65yo, but the rec is
        # categorically restricted to pediatric patients.
        if var_name == "age_range":
            q_age = query.age
            rec_section = str(criteria.get("section", ""))
            is_pediatric_rec = rec_section == "4.7.5"
            if q_age is not None and is_pediatric_rec and q_age >= 18:
                return "excluded"

        # Intervention matching with synonym groups
        if var_name == "intervention":
            query_val = (query.intervention or "").upper()
            rec_val = (criteria.get("intervention") or "").upper()
            if not query_val or not rec_val:
                return "pass"
            # Check synonym groups
            for group in INTERVENTION_GROUPS:
                if query_val in group and rec_val in group:
                    return "pass"
            if query_val == rec_val:
                return "pass"
            return "excluded"

        # Circulation matching
        if var_name == "circulation":
            query_val = (query.circulation or "").lower()
            rec_val = (criteria.get("circulation") or "").lower()
            if not query_val or not rec_val:
                return "pass"
            if query_val == rec_val:
                return "pass"
            return "excluded"

        # Vessel occlusion — list intersection (query.vessel_occlusion
        # can be a string "M1" or a list ["M1","ICA"]; normalize both).
        if var_name == "vessel_occlusion":
            qv = query.vessel_occlusion
            if qv is None:
                query_vessels = []
            elif isinstance(qv, str):
                query_vessels = [qv]
            else:
                query_vessels = list(qv)
            rec_vessels = criteria.get("vessel_occlusion") or []
            if isinstance(rec_vessels, str):
                rec_vessels = [rec_vessels]
            if not query_vessels or not rec_vessels:
                return "pass"
            q_set = {str(v).upper() for v in query_vessels if v}
            r_set = {str(v).upper() for v in rec_vessels if v}
            if q_set & r_set:
                return "pass"
            # Special case: LVO covers ICA and M1
            if "LVO" in q_set and (r_set & {"ICA", "M1"}):
                return "pass"
            if "LVO" in r_set and (q_set & {"ICA", "M1"}):
                return "pass"
            return "excluded"

        # Range fields
        query_range = getattr(query, var_name, None)
        rec_range = criteria.get(var_name)

        if not query_range or not isinstance(query_range, dict):
            return "pass"
        if not rec_range or not isinstance(rec_range, dict):
            return "pass"

        return self._range_overlap(query_range, rec_range)

    @staticmethod
    def _range_overlap(query_range: Dict, rec_range: Dict) -> str:
        """
        Check if query range overlaps with rec range.

        Returns "pass" if overlap exists, "excluded" if completely outside.
        Identical logic to TrialMatcher._range_contains.
        """
        q_min = query_range.get("min")
        q_max = query_range.get("max")
        r_min = rec_range.get("min")
        r_max = rec_range.get("max")

        # Effective bounds (null = unbounded)
        q_min_eff = q_min if q_min is not None else float("-inf")
        q_max_eff = q_max if q_max is not None else float("inf")
        r_min_eff = r_min if r_min is not None else float("-inf")
        r_max_eff = r_max if r_max is not None else float("inf")

        # Completely outside — no overlap
        if q_max_eff < r_min_eff or q_min_eff > r_max_eff:
            return "excluded"

        return "pass"

    # ── Variable comparison ──────────────────────────────────────

    def _compare_variable(
        self, var_name: str, query: ParsedQAQuery, criteria: Dict
    ) -> str:
        """Compare a single variable — returns 'exact', 'overlap', or 'none'."""
        if var_name in ("intervention", "circulation"):
            return "exact"  # If we got here, applicability passed

        if var_name == "vessel_occlusion":
            # query.vessel_occlusion may be a single string (e.g. "M1")
            # or a list (e.g. ["M1", "ICA"]). Normalize both sides.
            qv = query.vessel_occlusion
            if qv is None:
                query_vessels = []
            elif isinstance(qv, str):
                query_vessels = [qv]
            else:
                query_vessels = list(qv)
            rec_vessels = criteria.get("vessel_occlusion") or []
            if isinstance(rec_vessels, str):
                rec_vessels = [rec_vessels]
            if not query_vessels or not rec_vessels:
                return "none"
            q_set = {str(v).upper() for v in query_vessels if v}
            r_set = {str(v).upper() for v in rec_vessels if v}
            if q_set <= r_set:
                return "exact"
            if q_set & r_set:
                return "overlap"
            return "none"

        # Range fields
        query_range = getattr(query, var_name, None)
        rec_range = criteria.get(var_name)

        if not query_range or not isinstance(query_range, dict):
            return "none"
        if not rec_range or not isinstance(rec_range, dict):
            return "none"

        return self._compare_range(query_range, rec_range)

    @staticmethod
    def _compare_range(query_range: Dict, rec_range: Dict) -> str:
        """exact = rec fully contains query, overlap = intersect, none = disjoint."""
        q_min = query_range.get("min")
        q_max = query_range.get("max")
        r_min = rec_range.get("min")
        r_max = rec_range.get("max")

        r_min_eff = r_min if r_min is not None else float("-inf")
        r_max_eff = r_max if r_max is not None else float("inf")
        q_min_eff = q_min if q_min is not None else float("-inf")
        q_max_eff = q_max if q_max is not None else float("inf")

        # No overlap
        if r_min_eff > q_max_eff or q_min_eff > r_max_eff:
            return "none"

        # Rec fully contains query range
        if r_min_eff <= q_min_eff and q_max_eff <= r_max_eff:
            return "exact"

        return "overlap"
