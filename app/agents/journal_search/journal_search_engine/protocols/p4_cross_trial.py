"""P4: Cross-trial comparison assembly — side-by-side data from multiple trials."""

from __future__ import annotations
from ..models.query import ClassifiedIntent, ProtocolResult
from .db_access import resolve_trial_acronym, resolve_trial_group, get_multi_study_data


async def execute_p4(intent: ClassifiedIntent) -> ProtocolResult:
    """Assemble comparison data across multiple named trials or a trial group."""
    acronyms = intent.trials_to_compare or []

    # If no explicit trials, try to resolve from the query
    if not acronyms and intent.original_query:
        # Check for group labels
        acronyms = resolve_trial_group(intent.original_query)

    if not acronyms:
        return ProtocolResult(
            protocol="P4",
            query=intent.original_query,
            data={"error": "No trials specified for comparison."},
            data_found=False,
        )

    comparison_data = get_multi_study_data(acronyms)

    if not comparison_data:
        return ProtocolResult(
            protocol="P4",
            query=intent.original_query,
            data={"error": f"None of the specified trials found: {acronyms}"},
            data_found=False,
        )

    # Build comparison summary
    found_trials = [d["trial_id"] for d in comparison_data]
    not_found = [a for a in acronyms if a not in found_trials]

    return ProtocolResult(
        protocol="P4",
        query=intent.original_query,
        data={
            "trials": comparison_data,
            "trial_count": len(comparison_data),
            "found": found_trials,
            "not_found": not_found,
        },
        data_found=True,
        source_tables=["primary_outcomes", "safety_outcomes", "treatment_arms",
                        "inclusion_criteria", "reperfusion_metrics"],
    )
