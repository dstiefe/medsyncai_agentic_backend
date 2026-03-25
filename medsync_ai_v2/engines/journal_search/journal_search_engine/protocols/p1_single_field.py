"""P1: Single-field lookup — one field from one trial."""

from __future__ import annotations
from ..models.query import ClassifiedIntent, ProtocolResult
from .db_access import resolve_trial_acronym, get_study_field, NOT_REPORTED


async def execute_p1(intent: ClassifiedIntent) -> ProtocolResult:
    """Look up a single field from a single trial."""
    study = resolve_trial_acronym(intent.trial_acronym)
    if not study:
        return ProtocolResult(
            protocol="P1",
            trial_acronym=intent.trial_acronym,
            query=intent.original_query,
            data={"error": f"Trial '{intent.trial_acronym}' not found in the database."},
            data_found=False,
        )

    field_name = intent.field_requested or ""
    result = get_study_field(study, field_name)

    if not result["found"]:
        # Fall through to P8
        from .p8_extracted_table import execute_p8
        return await execute_p8(intent)

    return ProtocolResult(
        protocol="P1",
        trial_acronym=study.get("trial_acronym"),
        query=intent.original_query,
        data={
            "field": field_name,
            "trial": study.get("trial_acronym"),
            "values": result["values"],
        },
        data_found=True,
        source_tables=["studies"],
    )
