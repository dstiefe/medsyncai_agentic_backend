"""
Engine Contracts — Universal envelope shapes for engine I/O.

These are documented dict shapes, not classes. Factory functions
ensure consistent construction; helper functions enable engine composition.
"""


def make_engine_input(
    normalized_query="",
    devices=None,
    categories=None,
    generic_specs=None,
    constraints=None,
    classification=None,
    prior_results=None,
    metadata=None,
) -> dict:
    """
    Canonical engine input envelope.

    Shape:
        {
            "normalized_query": str,
            "devices": {ProductName: {"ids": [...], "conical_category": "L2"}},
            "categories": ["microcatheter", ...],
            "generic_specs": [...],
            "constraints": [...],
            "classification": {...},
            "prior_results": [<EngineOutput dicts>],
            "metadata": {...},
        }
    """
    return {
        "normalized_query": normalized_query,
        "devices": devices or {},
        "categories": categories or [],
        "generic_specs": generic_specs or [],
        "constraints": constraints or [],
        "classification": classification or {},
        "prior_results": prior_results or [],
        "metadata": metadata or {},
    }


def find_prior_result(prior_results, engine, result_type=None):
    """
    Find a prior engine result by engine name and optional result_type.

    Args:
        prior_results: List of EngineOutput dicts from previous engine runs.
        engine: Engine name to match (e.g., "database_engine").
        result_type: Optional result_type to further narrow (e.g., "database_query").

    Returns:
        The first matching EngineOutput dict, or None.
    """
    for r in (prior_results or []):
        if r.get("engine") == engine:
            if result_type is None or r.get("result_type") == result_type:
                return r
    return None


def transform_device_list_to_category_package(device_list, category_label="db_filtered"):
    """
    Transform a database engine's device_list into category expansion format.

    Instead of injecting individual product names as devices (which the chain
    builder LLM must reference exactly), package them as a virtual category
    with pre-resolved product names. The existing expand_chains() +
    update_devices_lookup() pipeline handles the rest — and product names
    come from the database, so ID resolution is guaranteed to match.

    Args:
        device_list: List of device dicts from database engine output,
                     each having "product_name", "conical_category", etc.
        category_label: Label for the virtual category (default: "db_filtered").

    Returns:
        {
            "category_mappings": {
                "<category_label>": {
                    "device_categories": [],
                    "conical_categories": ["L2", ...],
                    "products": ["ProductA", "ProductB", ...],
                }
            },
            "categories": ["<category_label>"],
        }
    """
    product_names = []
    conical_categories = set()
    seen = set()

    for device in device_list:
        pname = device.get("product_name")
        if pname and pname not in seen:
            product_names.append(pname)
            seen.add(pname)
        ccat = device.get("conical_category")
        if ccat:
            conical_categories.add(ccat)

    return {
        "category_mappings": {
            category_label: {
                "device_categories": [],
                "conical_categories": sorted(conical_categories),
                "products": sorted(product_names),
            }
        },
        "categories": [category_label],
    }
