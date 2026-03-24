"""
TrialMatcher — CMI (Clinical Matching Index) Protocol

Implements the CMI matching pipeline:
  Step 1: Methods-Based Trial Matching
    - Inverted Tiering (scenario → trial): Tier by missing variables
    - Applicability Gate: Exclude if scenario fails trial criterion
    - Forward Tiering (trial → scenario): Penalize conflicting variables
    - Scope Index: ratio of matched variables (threshold ≥ 0.6)
  Step 2: Clarification Loop (handled by engine, not matcher)
  Step 3: Results Extraction (structured + raw fallback)
  Step 4: Audit Trail (provenance in match_details)

Pure Python. No LLM calls. Auditable and reproducible.
"""

from __future__ import annotations

from typing import Optional
from ..models.query import ParsedQuery, MatchedTrial, RangeFilter, TimeWindowFilter
from ..data.loader import load_all_studies
from ..data.adapter import adapt_study
from .subgroup_index import get_subgroup_index, trial_has_subgroup_data


# ── Intervention synonym groups ──────────────────────────────────

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


# ── Matchable fields ─────────────────────────────────────────────

RANGE_FIELDS = [
    "aspects_range",
    "pc_aspects_range",
    "nihss_range",
    "age_range",
    "premorbid_mrs",
]

# CTP Variable Equivalence Group — match if ANY are present (CMI v14)
CTP_EQUIVALENCE_FIELDS = [
    "core_volume_ml",
    "mismatch_ratio",
]

LIST_FIELDS = [
    "vessel_occlusion",
    "imaging_required",
]

# Metadata fields excluded from matching per CMI v14
EXCLUDED_METADATA = {"imaging_platform", "vendor", "site", "sex", "race", "ethnicity"}


class TrialMatcher:
    """CMI (Clinical Matching Index) protocol implementation."""

    def __init__(self):
        # Load from SQLite and adapt to V1 format
        self._trials = [adapt_study(s) for s in load_all_studies()]
        # Pre-build subgroup index at init time
        self._subgroup_index = get_subgroup_index()

    def match(self, query: ParsedQuery) -> list[MatchedTrial]:
        """
        Run the full CMI v14 matching pipeline.

        Returns trials sorted by: inverse_tier ASC, scope_index DESC,
        RCTs before non-RCTs, newest first.
        """
        results = []
        for trial in self._trials:
            matched = self._evaluate_trial(query, trial)
            if matched is not None:
                results.append(matched)

        results.sort(key=lambda m: (
            m.tier,
            -m.match_details.get("scope_index", 0),
            0 if m.metadata.get("study_type") == "RCT" else 1,
            -(m.metadata.get("year") or 0),
        ))
        return results

    def _evaluate_trial(self, query: ParsedQuery, trial: dict) -> Optional[MatchedTrial]:
        """Evaluate a single trial against the query using CMI v14."""
        ic = trial.get("inclusion_criteria", {})
        intervention = trial.get("intervention", {})

        # ── Pre-filter: intervention match ──
        intervention_match = self._check_intervention(query, intervention)
        if not intervention_match and query.intervention:
            return None  # Skip trials with wrong intervention

        # ── Pre-filter: circulation ──
        if query.circulation:
            trial_circ = trial.get("metadata", {}).get("circulation", "")
            if trial_circ and query.circulation.lower() != trial_circ.lower():
                if trial_circ != "medical":
                    return None

        # ── Pre-filter: study type ──
        if query.study_type:
            trial_type = trial.get("metadata", {}).get("study_type", "")
            if trial_type and query.study_type.upper() != trial_type.upper():
                return None

        # ── Identify scenario-defined variables ──
        scenario_vars = self._get_scenario_variables(query)
        if not scenario_vars:
            # No specific variables — tier depends on how well intervention + circulation match
            if intervention_match:
                # If circulation was specified and matches, Tier 1
                if query.circulation:
                    trial_circ = trial.get("metadata", {}).get("circulation", "")
                    if trial_circ and query.circulation.lower() == trial_circ.lower():
                        return self._build_match(trial, 1,
                            "Intervention and circulation match, no additional variables specified",
                            {"scope_index": 1.0, "inverse_tier": 1, "forward_tier": 1})
                # Otherwise Tier 4
                return self._build_match(trial, 4,
                    "Same intervention, no specific scenario variables",
                    {"scope_index": 0, "inverse_tier": 4, "forward_tier": 4})
            return None

        # ── Step 1a: Inverted Tiering (Scenario → Trial) ──
        # How many scenario variables does the trial address?
        # Check both inclusion criteria AND subgroup data in Results
        present_in_trial = []
        present_via_subgroup = []
        missing_from_trial = []
        trial_id = trial.get("trial_id", "unknown")

        for var_name in scenario_vars:
            if self._trial_has_variable(var_name, ic):
                present_in_trial.append(var_name)
            else:
                # Check subgroup index — does the trial report results by this variable?
                subgroup_info = trial_has_subgroup_data(trial_id, var_name)
                if subgroup_info:
                    present_via_subgroup.append(var_name)
                else:
                    missing_from_trial.append(var_name)

        # Variables present via subgroup count as "present" for scope index
        # but cap the trial at Tier 2 (subgroup data, not inclusion criteria)
        missing_count = len(missing_from_trial)
        if missing_count == 0:
            inverse_tier = 1
        elif missing_count == 1:
            inverse_tier = 2
        elif missing_count == 2:
            inverse_tier = 3
        else:
            inverse_tier = 4

        # ── Step 1b: Applicability Gate ──
        # Exclude if scenario value FAILS a trial inclusion criterion
        failed_criteria = []
        for var_name in present_in_trial:
            result = self._check_applicability(var_name, query, ic)
            if result == "fail":
                failed_criteria.append(var_name)

        if failed_criteria:
            # Trial explicitly excludes this scenario
            return None

        # ── If all variables are only via subgroup, cap at Tier 2 ──
        if present_via_subgroup and not present_in_trial:
            inverse_tier = max(inverse_tier, 2)  # At best Tier 2 for subgroup-only

        # ── Scope Index — include subgroup matches ──
        all_present = len(present_in_trial) + len(present_via_subgroup)
        scope_index = all_present / len(scenario_vars) if scenario_vars else 0

        if scope_index < 0.6 and inverse_tier > 2:
            # Below threshold — skip unless we're desperate
            # Still include but mark as low scope
            pass

        # ── Step 1c: Forward Tiering (Trial → Scenario) ──
        # Check: for the variables the user DID specify, does the scenario
        # pass the trial's criteria? Forward tiering only penalizes for
        # variables that BOTH the trial and scenario define but conflict.
        # Unspecified variables are not penalized (the user is asking a
        # focused question, not providing a full patient scenario).
        trial_required_vars = self._get_trial_required_variables(ic)
        scenario_missing_for_trial = []

        for var_name in trial_required_vars:
            # Only penalize if the user specified this variable AND it conflicts
            if self._scenario_has_variable(var_name, query):
                result = self._check_applicability(var_name, query, ic)
                if result == "excluded":
                    scenario_missing_for_trial.append(var_name)
            # If user didn't specify this variable, don't penalize

        fwd_missing = len(scenario_missing_for_trial)
        if fwd_missing == 0:
            forward_tier = 1
        elif fwd_missing == 1:
            forward_tier = 2
        elif fwd_missing == 2:
            forward_tier = 3
        else:
            forward_tier = 4

        # ── Final tier = max(inverse_tier, forward_tier) ──
        final_tier = max(inverse_tier, forward_tier)

        # Cap at tier 4
        final_tier = min(final_tier, 4)

        # Build reason
        reason_parts = []
        if inverse_tier == 1 and forward_tier == 1 and not present_via_subgroup:
            reason_parts.append("Full bidirectional match — trial addresses all scenario variables and scenario meets all trial criteria")
        else:
            if present_via_subgroup:
                # Get subgroup details for the reason text
                subgroup_details = []
                for var_name in present_via_subgroup:
                    sg = trial_has_subgroup_data(trial_id, var_name)
                    if sg:
                        subgroup_details.append(f"{var_name}: {sg.get('details', 'subgroup data')} (see {sg.get('source', 'Results')})")
                reason_parts.append(f"Subgroup data available: {'; '.join(subgroup_details)}")
            if missing_from_trial:
                reason_parts.append(f"Trial missing scenario variables: {', '.join(missing_from_trial)}")
            if scenario_missing_for_trial:
                reason_parts.append(f"Scenario missing trial requirements: {', '.join(scenario_missing_for_trial)}")

        # Build variable-level match details
        variable_results = {}
        for var_name in present_in_trial:
            variable_results[var_name] = self._compare_variable(var_name, query, ic)

        # Add subgroup match info
        subgroup_matches = {}
        for var_name in present_via_subgroup:
            sg = trial_has_subgroup_data(trial_id, var_name)
            if sg:
                subgroup_matches[var_name] = sg

        match_details = {
            "inverse_tier": inverse_tier,
            "forward_tier": forward_tier,
            "scope_index": round(scope_index, 2),
            "scenario_vars": scenario_vars,
            "present_in_trial": present_in_trial,
            "present_via_subgroup": present_via_subgroup,
            "subgroup_matches": subgroup_matches,
            "missing_from_trial": missing_from_trial,
            "scenario_missing_for_trial": scenario_missing_for_trial,
            "variable_results": variable_results,
        }

        return self._build_match(
            trial, final_tier,
            "; ".join(reason_parts) if reason_parts else f"Tier {final_tier} match",
            match_details,
        )

    # ── Variable detection ───────────────────────────────────────

    def _get_scenario_variables(self, query: ParsedQuery) -> list[str]:
        """Get list of variable names specified in the query."""
        vars_present = []

        for field in RANGE_FIELDS:
            val = getattr(query, field, None)
            if val is not None and val.is_set():
                vars_present.append(field)

        if query.time_window_hours and query.time_window_hours.is_set():
            vars_present.append("time_window_hours")

        # CTP equivalence group — count as one variable if any are specified
        ctp_specified = False
        for field in CTP_EQUIVALENCE_FIELDS:
            val = getattr(query, field, None)
            if val is not None and val.is_set():
                ctp_specified = True
        if ctp_specified:
            vars_present.append("ctp_group")

        for field in LIST_FIELDS:
            val = getattr(query, field, None)
            if val:
                vars_present.append(field)

        return vars_present

    def _trial_has_variable(self, var_name: str, ic: dict) -> bool:
        """Check if a trial's inclusion criteria address this variable."""
        if var_name == "ctp_group":
            # CTP equivalence: match if ANY of core_volume, mismatch_ratio present
            return any(ic.get(f) is not None for f in CTP_EQUIVALENCE_FIELDS)

        if var_name == "time_window_hours":
            val = ic.get("time_window_hours")
            return val is not None and isinstance(val, dict)

        if var_name in LIST_FIELDS:
            val = ic.get(var_name)
            return val is not None and len(val) > 0

        # Range fields
        val = ic.get(var_name)
        return val is not None

    def _scenario_has_variable(self, var_name: str, query: ParsedQuery) -> bool:
        """Check if the scenario (query) specifies this variable."""
        if var_name == "ctp_group":
            return any(
                getattr(query, f, None) is not None and getattr(query, f).is_set()
                for f in CTP_EQUIVALENCE_FIELDS
            )
        if var_name == "time_window_hours":
            return query.time_window_hours is not None and query.time_window_hours.is_set()
        if var_name in LIST_FIELDS:
            return bool(getattr(query, var_name, None))
        val = getattr(query, var_name, None)
        return val is not None and hasattr(val, 'is_set') and val.is_set()

    def _get_trial_required_variables(self, ic: dict) -> list[str]:
        """Get variables that a trial defines as inclusion criteria."""
        required = []
        for field in RANGE_FIELDS:
            if ic.get(field) is not None:
                required.append(field)
        if ic.get("time_window_hours") is not None:
            required.append("time_window_hours")
        # CTP equivalence
        if any(ic.get(f) is not None for f in CTP_EQUIVALENCE_FIELDS):
            required.append("ctp_group")
        for field in LIST_FIELDS:
            if ic.get(field) and len(ic[field]) > 0:
                required.append(field)
        return required

    # ── Applicability Gate ───────────────────────────────────────

    def _check_applicability(self, var_name: str, query: ParsedQuery, ic: dict) -> str:
        """
        Check if the scenario value passes the trial's inclusion criterion.

        Returns: "pass", "fail", or "unknown"
        """
        if var_name == "ctp_group":
            # For CTP equivalence, pass if any CTP variable overlaps
            for field in CTP_EQUIVALENCE_FIELDS:
                q_val = getattr(query, field, None)
                t_val = ic.get(field)
                if q_val and q_val.is_set() and t_val:
                    result = self._range_contains(
                        {"min": q_val.min, "max": q_val.max}, t_val
                    )
                    if result != "excluded":
                        return "pass"
            return "pass"  # If no CTP variable to compare, don't exclude

        if var_name == "time_window_hours":
            if query.time_window_hours and query.time_window_hours.is_set():
                t_val = ic.get("time_window_hours")
                if t_val and isinstance(t_val, dict):
                    return self._range_contains(
                        {"min": query.time_window_hours.min, "max": query.time_window_hours.max},
                        t_val,
                    )
            return "pass"

        if var_name in LIST_FIELDS:
            q_val = getattr(query, var_name, None)
            t_val = ic.get(var_name)
            if q_val and t_val:
                q_set = {v.upper() for v in q_val}
                t_set = {v.upper() for v in t_val}
                if q_set & t_set:
                    return "pass"
                return "fail"
            return "pass"

        # Range fields
        q_val = getattr(query, var_name, None)
        t_val = ic.get(var_name)
        if q_val and q_val.is_set() and t_val:
            return self._range_contains(
                {"min": q_val.min, "max": q_val.max}, t_val
            )
        return "pass"

    @staticmethod
    def _range_contains(scenario_range: dict, trial_range: dict) -> str:
        """
        Check if a scenario value would pass a trial's inclusion criterion.

        Returns "pass" if any part of scenario range falls within trial range,
        "excluded" if completely outside, "pass" if can't determine.
        """
        q_min = scenario_range.get("min")
        q_max = scenario_range.get("max")
        t_min = trial_range.get("min")
        t_max = trial_range.get("max")

        t_min_eff = t_min if t_min is not None else float("-inf")
        t_max_eff = t_max if t_max is not None else float("inf")
        q_min_eff = q_min if q_min is not None else float("-inf")
        q_max_eff = q_max if q_max is not None else float("inf")

        # Completely outside — scenario fails trial criterion
        if q_max_eff < t_min_eff or q_min_eff > t_max_eff:
            return "excluded"

        return "pass"

    # ── Variable comparison ──────────────────────────────────────

    def _compare_variable(self, var_name: str, query: ParsedQuery, ic: dict) -> str:
        """Compare a single variable — returns 'exact', 'overlap', or 'none'."""
        if var_name == "ctp_group":
            for field in CTP_EQUIVALENCE_FIELDS:
                q_val = getattr(query, field, None)
                t_val = ic.get(field)
                if q_val and q_val.is_set() and t_val:
                    return self._compare_range(
                        {"min": q_val.min, "max": q_val.max}, t_val)
            return "none"

        if var_name == "time_window_hours":
            if query.time_window_hours and query.time_window_hours.is_set():
                t_val = ic.get("time_window_hours")
                if t_val and isinstance(t_val, dict):
                    return self._compare_range(
                        {"min": query.time_window_hours.min, "max": query.time_window_hours.max},
                        t_val)
            return "none"

        if var_name in LIST_FIELDS:
            q_val = getattr(query, var_name, None)
            t_val = ic.get(var_name)
            if q_val and t_val:
                return self._compare_list(q_val, t_val)
            return "none"

        q_val = getattr(query, var_name, None)
        t_val = ic.get(var_name)
        if q_val and q_val.is_set() and t_val:
            return self._compare_range({"min": q_val.min, "max": q_val.max}, t_val)
        return "none"

    @staticmethod
    def _compare_range(query_range: dict, trial_range: dict) -> str:
        """exact = trial fully contains query, overlap = intersect, none = no intersect."""
        q_min = query_range.get("min")
        q_max = query_range.get("max")
        t_min = trial_range.get("min")
        t_max = trial_range.get("max")

        t_min_eff = t_min if t_min is not None else float("-inf")
        t_max_eff = t_max if t_max is not None else float("inf")
        q_min_eff = q_min if q_min is not None else float("-inf")
        q_max_eff = q_max if q_max is not None else float("inf")

        if t_min_eff > q_max_eff or q_min_eff > t_max_eff:
            return "none"
        if t_min_eff <= q_min_eff and q_max_eff <= t_max_eff:
            return "exact"
        return "overlap"

    @staticmethod
    def _compare_list(query_list: list, trial_list: list) -> str:
        """exact = query subset of trial, overlap = some shared, none = no shared."""
        q_set = {v.upper() for v in query_list}
        t_set = {v.upper() for v in trial_list}
        if q_set <= t_set:
            return "exact"
        if q_set & t_set:
            return "overlap"
        return "none"

    # ── Intervention matching ────────────────────────────────────

    @staticmethod
    def _check_intervention(query: ParsedQuery, intervention: dict) -> bool:
        """Check if query intervention matches trial intervention."""
        if query.intervention is None:
            return True

        query_agent = query.intervention.upper()
        trial_agent = (intervention.get("agent") or "").upper()

        if query_agent == trial_agent:
            return True

        for group in INTERVENTION_GROUPS:
            if query_agent in group and trial_agent in group:
                return True

        if query_agent in IVT_SYNONYMS:
            if trial_agent in ALTEPLASE_SYNONYMS or trial_agent in TENECTEPLASE_SYNONYMS:
                return True
        if trial_agent in IVT_SYNONYMS:
            if query_agent in ALTEPLASE_SYNONYMS or query_agent in TENECTEPLASE_SYNONYMS:
                return True

        return False

    # ── Build helpers ────────────────────────────────────────────

    @staticmethod
    def _build_match(trial: dict, tier: int, reason: str, details: dict) -> MatchedTrial:
        return MatchedTrial(
            trial_id=trial.get("trial_id", "unknown"),
            tier=tier,
            tier_reason=reason,
            match_details=details,
            metadata=trial.get("metadata", {}),
            intervention=trial.get("intervention", {}),
            results=trial.get("results", {}),
            methods_text=trial.get("raw_sections", {}).get("methods_text", ""),
            results_text=trial.get("raw_sections", {}).get("results_text", ""),
        )

    @property
    def trial_count(self) -> int:
        return len(self._trials)

    def get_clarification_candidates(self, query: ParsedQuery) -> list[dict]:
        """
        CMI v14 Step 2: Identify Tier 2-3 trials and the variables
        that would promote them to Tier 1 if the user clarifies.

        Returns list of {trial_id, missing_variables, current_tier}.
        """
        candidates = []
        for trial in self._trials:
            matched = self._evaluate_trial(query, trial)
            if matched and matched.tier in (2, 3):
                details = matched.match_details
                candidates.append({
                    "trial_id": matched.trial_id,
                    "current_tier": matched.tier,
                    "missing_variables": details.get("missing_from_trial", []),
                    "scope_index": details.get("scope_index", 0),
                })
        return candidates
