"""
Chain Engine - Decision Logic

Deterministic Python business rules that decide what to do after
the compatibility evaluator runs. No LLM involved.

Rules from design doc:
- All junctions pass -> return as-is
- Failed + multi_device + exploratory/discovery -> run n-1 subset analysis
- Failed + two_device + positive framing -> flag for gentle correction
- Failed + two_device + neutral -> return failure with reason
- Discovery mode -> search category for all compatible devices
"""

import copy
from medsync_ai_v2.engines.chain_engine.compat_evaluator import (
    ChainPairGenerator,
    CompatEvaluatorMulti,
)


def decide_next_action(classification: dict, chain_summary: dict) -> dict:
    """
    Based on classification and results, decide what additional processing is needed.

    Args:
        classification: Query classification from QueryClassifier
        chain_summary: Summary from ChainAnalyzerMulti.get_summary()

    Returns:
        {
            "action": "return_as_is" | "run_n1_subsets" | "flag_gentle_correction" | "run_discovery",
            "reason": str,
            "additional_data": dict
        }
    """
    query_mode = classification.get("query_mode", "specific")
    framing = classification.get("framing", "neutral")
    structure = classification.get("structure", "two_device")

    passing = chain_summary.get("passing_chain_count", 0)
    failing = chain_summary.get("failing_chain_count", 0)
    total = chain_summary.get("total_chains", 0)

    # All pass
    if failing == 0 and passing > 0:
        return {
            "action": "return_as_is",
            "reason": "All chains pass",
            "additional_data": {},
        }

    # All fail
    if passing == 0 and failing > 0:
        # Multi-device + exploratory/discovery -> n-1 subsets
        if structure == "multi_device" and query_mode in ("exploratory", "discovery", "stack_validation"):
            return {
                "action": "run_n1_subsets",
                "reason": "Full stack failed, analyzing subsets to find what works",
                "additional_data": {},
            }

        # Two-device + positive framing -> gentle correction
        if structure == "two_device" and framing == "positive":
            return {
                "action": "flag_gentle_correction",
                "reason": "User expected compatibility but devices are incompatible",
                "additional_data": {},
            }

        # Default: return failure with reason
        return {
            "action": "return_as_is",
            "reason": "Incompatible - returning failure details",
            "additional_data": {},
        }

    # Mixed results (some pass, some fail)
    return {
        "action": "return_as_is",
        "reason": f"{passing} passing, {failing} failing chains",
        "additional_data": {},
    }


def run_n1_subsets(
    original_chains: list,
    devices: dict,
    database: dict,
) -> list:
    """
    Remove one device at a time from the chain and re-evaluate subsets.
    Used when a full multi-device stack fails.

    Args:
        original_chains: The original chain configs
        devices: Device lookup dict
        database: Full device database

    Returns:
        List of subset results, each with the removed device and pass/fail
    """
    subset_results = []
    generator = ChainPairGenerator()

    for chain in original_chains:
        sequence = chain.get("sequence", [])
        levels = chain.get("levels", [])

        if len(sequence) < 3:
            continue

        for remove_idx in range(len(sequence)):
            removed_device = sequence[remove_idx]
            subset_seq = sequence[:remove_idx] + sequence[remove_idx + 1:]
            subset_levels = levels[:remove_idx] + levels[remove_idx + 1:]

            if len(subset_seq) < 2:
                continue

            subset_chain = {
                "sequence": subset_seq,
                "levels": subset_levels,
                "contains_category": False,
            }

            # Generate pairs and evaluate
            chain_results = generator.generate_chain_pairs(
                [subset_chain], devices, database
            )
            processed = generator.process_chain_results(chain_results)

            # Check if this subset passes
            all_pass = True
            for proc_chain in processed:
                for path in proc_chain.get("paths", []):
                    for conn in path.get("connections", []):
                        for pair in conn.get("processed_pairs", []):
                            status = pair.get("overall_status", {}).get("status", "fail")
                            if status not in ("pass", "pass_with_warning"):
                                all_pass = False

            subset_results.append({
                "removed_device": removed_device,
                "subset_sequence": subset_seq,
                "subset_levels": subset_levels,
                "status": "pass" if all_pass else "fail",
            })

    return subset_results
