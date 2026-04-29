"""
Protocol Router — dispatches ClassifiedIntent to the correct P1-P8 handler.

Handles multi-intent queries by running sub-intents sequentially and merging.
"""

from __future__ import annotations
from ..models.query import ClassifiedIntent, ProtocolResult

from .p1_single_field import execute_p1
from .p2_multi_field import execute_p2
from .p3_multi_row import execute_p3
from .p4_cross_trial import execute_p4
from .p5_guideline_table import execute_p5
from .p6_management_protocol import execute_p6
from .p7_definition import execute_p7
from .p8_extracted_table import execute_p8


PROTOCOL_DISPATCH = {
    "P1": execute_p1,
    "P2": execute_p2,
    "P3": execute_p3,
    "P4": execute_p4,
    "P5": execute_p5,
    "P6": execute_p6,
    "P7": execute_p7,
    "P8": execute_p8,
}


async def route_protocol(intent: ClassifiedIntent) -> ProtocolResult:
    """Execute the appropriate protocol handler based on intent classification."""

    # Multi-intent: run each sub-intent and merge results
    if intent.is_multi_intent and intent.sub_intents:
        results = []
        for sub in intent.sub_intents:
            handler = PROTOCOL_DISPATCH.get(sub.protocol, execute_p8)
            result = await handler(sub)
            results.append(result)
        return _merge_results(results, intent.original_query)

    # Single intent
    handler = PROTOCOL_DISPATCH.get(intent.protocol, execute_p8)
    return await handler(intent)


def _merge_results(results: list[ProtocolResult], query: str) -> ProtocolResult:
    """Merge multiple protocol results for multi-intent queries."""
    sub_data = []
    all_missing = []
    all_tables = []
    any_found = False

    for r in results:
        sub_data.append({
            "protocol": r.protocol,
            "trial_acronym": r.trial_acronym,
            "data": r.data,
            "data_found": r.data_found,
        })
        all_missing.extend(r.missing_fields)
        all_tables.extend(r.source_tables)
        if r.data_found:
            any_found = True

    return ProtocolResult(
        protocol="multi",
        trial_acronym=results[0].trial_acronym if results else None,
        query=query,
        data={"sub_results": sub_data},
        data_found=any_found,
        missing_fields=all_missing,
        source_tables=list(set(all_tables)),
    )
