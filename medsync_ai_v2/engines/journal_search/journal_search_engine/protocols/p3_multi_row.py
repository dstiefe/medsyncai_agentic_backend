"""P3: Multi-row single-table lookup — complete list from one trial."""

from __future__ import annotations
from ..models.query import ClassifiedIntent, ProtocolResult
from .db_access import (
    resolve_trial_acronym, get_study_table_rows, get_baseline_demographics,
    _strip_nulls, NOT_REPORTED, FIELD_MAP,
)


async def execute_p3(intent: ClassifiedIntent) -> ProtocolResult:
    """Return a complete list (e.g., all inclusion criteria for a trial)."""
    study = resolve_trial_acronym(intent.trial_acronym)
    if not study:
        return ProtocolResult(
            protocol="P3",
            trial_acronym=intent.trial_acronym,
            query=intent.original_query,
            data={"error": f"Trial '{intent.trial_acronym}' not found in the database."},
            data_found=False,
        )

    # Resolve table key
    table_key = intent.table_requested or intent.field_requested or ""
    mapping = FIELD_MAP.get(table_key.lower())
    if mapping:
        resolved = mapping[0]
        if resolved == "_demographics":
            rows = get_baseline_demographics(study)
            table_key = "baseline_demographics"
        else:
            table_key = resolved
            rows = get_study_table_rows(study, table_key)
    else:
        rows = get_study_table_rows(study, table_key)

    if not rows:
        return ProtocolResult(
            protocol="P3",
            trial_acronym=study.get("trial_acronym"),
            query=intent.original_query,
            data={
                "table": table_key,
                "trial": study.get("trial_acronym"),
                "message": NOT_REPORTED,
            },
            data_found=False,
            source_tables=[table_key],
        )

    # Group by category if available
    grouped = {}
    for row in rows:
        cat = row.get("category") or row.get("arm_type") or row.get("subgroup_variable") or "general"
        grouped.setdefault(cat, []).append(_strip_nulls(row))

    return ProtocolResult(
        protocol="P3",
        trial_acronym=study.get("trial_acronym"),
        query=intent.original_query,
        data={
            "table": table_key,
            "trial": study.get("trial_acronym"),
            "items": [_strip_nulls(r) for r in rows],
            "grouped": grouped,
            "count": len(rows),
        },
        data_found=True,
        source_tables=[table_key],
    )
