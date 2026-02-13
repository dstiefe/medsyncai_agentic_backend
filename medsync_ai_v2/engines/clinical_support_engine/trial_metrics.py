"""
Trial Metrics Lookup

Loads structured trial data from ais_trials_metrics.json and provides
fast dict-based lookups. Sits between EligibilityRules and OpenAI
file_search to eliminate unnecessary API calls for well-known trials.

Handles the actual JSON structure where "trials" is a dict keyed by
trial name, and normalizes field names for the output agent.
"""

import json
import os
from typing import Optional


DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
METRICS_FILE = os.path.join(DATA_DIR, "ais_trials_metrics.json")


class TrialMetricsLookup:
    """Fast dict-based lookup for structured trial metrics. No API calls."""

    def __init__(self, filepath: str = METRICS_FILE):
        self._trials = {}  # trial_name_lower -> normalized trial dict
        self._loaded = False
        self._filepath = filepath
        self._load()

    def _normalize_metric(self, m: dict) -> dict:
        """Map raw JSON metric fields to output-agent-expected fields."""
        metric_type = m.get("metric_type") or ""
        normalized = {"metric_type": metric_type}

        if metric_type == "percentage_comparison":
            normalized["metric_name"] = m.get("outcome") or ""
            normalized["intervention_value"] = m.get("value_treatment") or ""
            normalized["control_value"] = m.get("value_control") or ""
            normalized["effect_size"] = ""
            normalized["ci"] = ""
            normalized["p_value"] = m.get("p_value") or ""
        elif metric_type == "threshold":
            normalized["metric_name"] = m.get("description") or m.get("outcome") or ""
            normalized["effect_size"] = f"{m.get('value', '')} {m.get('unit', '')}".strip()
            normalized["ci"] = ""
            normalized["p_value"] = ""
        else:
            # HR, OR, RR, percentage, etc.
            normalized["metric_name"] = m.get("outcome") or ""
            value = m.get("value")
            if value is not None:
                normalized["effect_size"] = f"{metric_type} {value}"
            else:
                normalized["effect_size"] = ""
            lo = m.get("ci_95_lower")
            hi = m.get("ci_95_upper")
            if lo is not None and hi is not None:
                normalized["ci"] = f"95% CI {lo}-{hi}"
            else:
                normalized["ci"] = ""
            normalized["p_value"] = m.get("p_value") or ""

        # Pass through enrichment fields from new JSON structure
        if m.get("population_subgroup"):
            normalized["population_subgroup"] = m["population_subgroup"]
        if m.get("comparison"):
            normalized["comparison"] = m["comparison"]
        if m.get("raw_text"):
            normalized["raw_text"] = m["raw_text"]

        return normalized

    def _normalize_trial(self, trial: dict) -> dict:
        """Normalize a single trial dict: fix field names, normalize metrics."""
        return {
            "trial_name": trial.get("trial_name") or "",
            "full_name": trial.get("full_name") or "",
            "category": trial.get("category") or "",
            "pages": trial.get("pages_referenced") or trial.get("pages") or [],
            "sections": trial.get("sections_referenced") or [],
            "metrics": [
                self._normalize_metric(m) for m in (trial.get("metrics") or [])
            ],
        }

    def _load(self):
        """Load and index trial data from JSON file."""
        if not os.path.exists(self._filepath):
            print(f"  [TrialMetricsLookup] File not found: {self._filepath}")
            return

        try:
            with open(self._filepath, "r", encoding="utf-8") as f:
                data = json.load(f)

            raw_trials = data.get("trials", {})

            # Handle both dict-keyed and list formats
            if isinstance(raw_trials, dict):
                trial_list = raw_trials.values()
            else:
                trial_list = raw_trials

            for raw_trial in trial_list:
                name = (raw_trial.get("trial_name") or "").strip()
                if name:
                    normalized = self._normalize_trial(raw_trial)
                    self._trials[name.lower()] = normalized
                    # Also index by acronym variants (e.g., "MR CLEAN" and "MR_CLEAN")
                    self._trials[name.lower().replace(" ", "_")] = normalized
                    self._trials[name.lower().replace("-", "")] = normalized

            self._loaded = True
            unique_trials = len({id(v) for v in self._trials.values()})
            total_metrics = sum(
                len(t.get("metrics", []))
                for t in {id(v): v for v in self._trials.values()}.values()
            )
            print(f"  [TrialMetricsLookup] Loaded {unique_trials} trials, "
                  f"{total_metrics} metrics")
        except Exception as e:
            print(f"  [TrialMetricsLookup] Failed to load: {e}")

    def has_trial(self, name: str) -> bool:
        """Check if a trial exists in the dataset."""
        return name.lower().strip() in self._trials

    def get_trial(self, name: str) -> Optional[dict]:
        """Get full trial data by name. Returns None if not found."""
        return self._trials.get(name.lower().strip())

    def get_metrics(self, name: str) -> list:
        """Get metrics list for a trial. Returns empty list if not found."""
        trial = self.get_trial(name)
        if trial:
            return trial.get("metrics", [])
        return []

    def get_trial_summary(self, name: str) -> Optional[dict]:
        """
        Get a compact summary suitable for LLM context.

        Returns:
            {
                "trial_name": str,
                "full_name": str,
                "category": str,
                "pages": list[int],
                "sections": list[str],
                "metrics": list[dict]
            }
        """
        return self.get_trial(name)

    def lookup_all(self, names: list) -> dict:
        """
        Batch lookup multiple trial names.

        Args:
            names: List of trial name strings (e.g., ["HERMES", "DAWN", "SELECT2"])

        Returns:
            {trial_name: summary_dict} for all found trials.
            Missing trials are silently omitted.
        """
        result = {}
        for name in names:
            summary = self.get_trial_summary(name)
            if summary:
                result[summary["trial_name"]] = summary
        return result
