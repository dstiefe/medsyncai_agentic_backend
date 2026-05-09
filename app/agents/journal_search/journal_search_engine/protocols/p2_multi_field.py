"""P2: Multi-field single-row lookup — all fields of one outcome type for one trial."""

from __future__ import annotations
from ..models.query import ClassifiedIntent, ProtocolResult
from .db_access import resolve_trial_acronym, get_study_table_rows, _strip_nulls, NOT_REPORTED, FIELD_MAP


async def execute_p2(intent: ClassifiedIntent) -> ProtocolResult:
    """Look up all fields of one outcome type for one trial."""
    study = resolve_trial_acronym(intent.trial_acronym)
    if not study:
        return ProtocolResult(
            protocol="P2",
            trial_acronym=intent.trial_acronym,
            query=intent.original_query,
            data={"error": f"Trial '{intent.trial_acronym}' not found in the database."},
            data_found=False,
        )

    # Resolve the table key from field_requested or table_requested
    table_key = intent.table_requested or intent.field_requested or ""
    mapping = FIELD_MAP.get(table_key.lower())
    if mapping:
        table_key = mapping[0]

    # Skip internal study-level fields — those are P1
    if table_key == "_study":
        from .p1_single_field import execute_p1
        return await execute_p1(intent)

    rows = get_study_table_rows(study, table_key)

    if not rows:
        return ProtocolResult(
            protocol="P2",
            trial_acronym=study.get("trial_acronym"),
            query=intent.original_query,
            data={
                "table": table_key,
                "trial": study.get("trial_acronym"),
                "message": NOT_REPORTED,
            },
            data_found=False,
            missing_fields=[table_key],
            source_tables=[table_key],
        )

    # For single-row tables (primary outcome, safety), return first row cleaned
    # For multi-row tables, return all rows
    if len(rows) == 1:
        cleaned = _strip_nulls(rows[0])
        missing = [k for k, v in rows[0].items() if v is None and k != "study_id"]
        data = {
            "table": table_key,
            "trial": study.get("trial_acronym"),
            "row": cleaned,
        }
    else:
        cleaned_rows = [_strip_nulls(r) for r in rows]
        missing = []
        data = {
            "table": table_key,
            "trial": study.get("trial_acronym"),
            "rows": cleaned_rows,
            "count": len(cleaned_rows),
        }

    return ProtocolResult(
        protocol="P2",
        trial_acronym=study.get("trial_acronym"),
        query=intent.original_query,
        data=data,
        data_found=True,
        missing_fields=missing,
        source_tables=[table_key],
    )
