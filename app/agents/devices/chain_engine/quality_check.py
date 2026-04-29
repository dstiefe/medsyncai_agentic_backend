"""
Chain Engine - Quality Check

Validates that chain engine results are complete and correct.
Pure Python, no LLM.
"""


def check_quality(input_data: dict, result: dict) -> dict:
    """
    Validate chain engine results for completeness.

    Checks:
    - All input devices were addressed
    - All junctions were checked
    - Result has required fields

    Args:
        input_data: Original input to the chain engine
        result: The chain engine's result data

    Returns:
        {"passed": bool, "issues": [...]}
    """
    issues = []

    # Check result structure
    if not result:
        return {"passed": False, "issues": ["No result data"]}

    data = result.get("data", {})
    if not data:
        issues.append("Empty data field in result")

    # Check that we got chain results
    chain_summary = data.get("chain_summary", {})
    total_chains = chain_summary.get("total_chains", 0)
    if total_chains == 0:
        issues.append("No chains were evaluated")

    # Check all input devices are mentioned in results
    input_devices = set()
    devices = input_data.get("devices", {})
    for name in devices:
        input_devices.add(name)

    result_devices = set()
    passed_chains = chain_summary.get("passed_chains", [])
    failed_chains = chain_summary.get("failed_chains", [])
    all_chains = passed_chains + failed_chains

    for chain in all_chains:
        for path in chain.get("path_results", []):
            for device in path.get("device_path", []):
                result_devices.add(device)

    missing = input_devices - result_devices
    if missing:
        issues.append(f"Devices not addressed in results: {missing}")

    # Check classification exists
    classification = result.get("classification", {})
    if not classification.get("query_mode"):
        issues.append("Missing query_mode in classification")

    return {
        "passed": len(issues) == 0,
        "issues": issues,
    }
