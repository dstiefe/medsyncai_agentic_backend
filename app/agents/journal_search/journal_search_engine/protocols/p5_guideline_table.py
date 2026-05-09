"""P5: Guideline table parsing — COR/LOE recommendations."""

from __future__ import annotations
from ..models.query import ClassifiedIntent, ProtocolResult
from .db_access import get_guideline_studies, search_extracted_tables, NOT_REPORTED


async def execute_p5(intent: ClassifiedIntent) -> ProtocolResult:
    """Parse guideline recommendation tables for COR/LOE."""
    keyword = intent.field_requested or intent.original_query or ""
    guideline_studies = get_guideline_studies()

    if not guideline_studies:
        return ProtocolResult(
            protocol="P5",
            query=intent.original_query,
            data={"error": "No guideline documents found in the database."},
            data_found=False,
        )

    # Search extracted tables from guideline studies
    all_tables = []
    for gs in guideline_studies:
        tables = search_extracted_tables(gs.get("study_id"), keyword)
        for t in tables:
            t["source_guideline"] = gs.get("trial_acronym") or gs.get("full_title")
            t["year"] = gs.get("pub_year")
        all_tables.extend(tables)

    if not all_tables:
        # Fallback: search key_findings_summary
        findings = []
        for gs in guideline_studies:
            kfs = gs.get("key_findings_summary") or ""
            if keyword.lower() in kfs.lower():
                findings.append({
                    "source": gs.get("trial_acronym") or gs.get("full_title"),
                    "year": gs.get("pub_year"),
                    "key_findings": kfs,
                })

        if findings:
            return ProtocolResult(
                protocol="P5",
                query=intent.original_query,
                data={
                    "source": "key_findings_summary",
                    "findings": findings,
                },
                data_found=True,
                source_tables=["studies"],
            )

        return ProtocolResult(
            protocol="P5",
            query=intent.original_query,
            data={"message": NOT_REPORTED},
            data_found=False,
        )

    return ProtocolResult(
        protocol="P5",
        query=intent.original_query,
        data={
            "tables": all_tables,
            "count": len(all_tables),
        },
        data_found=True,
        source_tables=["extracted_tables"],
    )
