"""
Database Engine - Query Executor

Pure Python query runner that executes structured JSON query specs against DATABASE.
Supports single-action and multi-step queries with step references.

Ported from vs2/agents/direct_query_agents.py (QueryExecutor class).

Available actions:
  get_device_specs, filter_by_spec, find_compatible, compare_devices,
  extract_value, intersect, union, search_both_id_od
"""

import copy
from medsync_ai_v2.shared.device_search import DeviceSearchHelper, get_database


# =============================================================================
# Field Mapping: Friendly names -> DATABASE field names
# =============================================================================

FIELD_MAP = {
    # Inner Diameter
    "ID_in": "specification_inner-diameter_in",
    "ID_mm": "specification_inner-diameter_mm",
    "ID_Fr": "specification_inner-diameter_F",
    # Outer Diameter - Distal
    "OD_distal_in": "specification_outer-diameter-distal_in",
    "OD_distal_mm": "specification_outer-diameter-distal_mm",
    "OD_distal_Fr": "specification_outer-diameter-distal_F",
    # Outer Diameter - Proximal
    "OD_proximal_in": "specification_outer-diameter-proximal_in",
    "OD_proximal_mm": "specification_outer-diameter-proximal_mm",
    "OD_proximal_Fr": "specification_outer-diameter-proximal_F",
    # Length
    "length_cm": "specification_length_cm",
    # Compatibility Rules
    "wire_max_OD_in": "compatibility_wire_max_outer-diameter_in",
    "wire_max_OD_mm": "compatibility_wire_max_outer-diameter_mm",
    "catheter_max_OD_in": "compatibility_catheter_max_outer-diameter_in",
    "catheter_max_OD_mm": "compatibility_catheter_max_outer-diameter_mm",
    "catheter_required_ID_in": "compatibility_catheter_req_inner-diameter_in",
    "catheter_required_ID_mm": "compatibility_catheter_req_inner-diameter_mm",
    "guide_min_ID_in": "compatibility_guide_or_catheter_or_sheath_min_inner-diameter_in",
    "guide_min_ID_mm": "compatibility_guide_or_catheter_or_sheath_min_inner-diameter_mm",
    # Device info (map directly)
    "product_name": "product_name",
    "device_name": "device_name",
    "manufacturer": "manufacturer",
    "conical_category": "conical_category",
    "logic_category": "logic_category",
    "fit_logic": "fit_logic",
    "category_type": "category_type",
}

REVERSE_FIELD_MAP = {v: k for k, v in FIELD_MAP.items()}

# Category mapping: friendly names -> category_type values (precise) + conical_category fallback
CATEGORY_MAP = {
    "microcatheter": {
        "category_types": ["microcatheter", "balloon_microcatheter", "flow_dependent_microcatheter", "delivery_catheter"],
        "conical_categories": ["L3"],
    },
    "micro": {
        "category_types": ["microcatheter", "balloon_microcatheter", "flow_dependent_microcatheter", "delivery_catheter"],
        "conical_categories": ["L3"],
    },
    "sheath": {
        "category_types": ["sheath"],
        "conical_categories": ["L0"],
    },
    "guide_catheter": {
        "category_types": ["balloon_guide_catheter", "guide_intermediate_catheter"],
        "conical_categories": ["L0", "L1"],
    },
    "guide": {
        "category_types": ["balloon_guide_catheter", "guide_intermediate_catheter"],
        "conical_categories": ["L0", "L1"],
    },
    "bgc": {
        "category_types": ["balloon_guide_catheter"],
        "conical_categories": ["L1"],
    },
    "balloon_guide_catheter": {
        "category_types": ["balloon_guide_catheter"],
        "conical_categories": ["L1"],
    },
    "intermediate_catheter": {
        "category_types": ["guide_intermediate_catheter", "intermediate_catheter", "delivery_intermediate_catheter", "aspiration_intermediate_catheter"],
        "conical_categories": ["L1", "L2"],
    },
    "intermediate": {
        "category_types": ["guide_intermediate_catheter", "intermediate_catheter", "delivery_intermediate_catheter", "aspiration_intermediate_catheter"],
        "conical_categories": ["L1", "L2"],
    },
    "aspiration_catheter": {
        "category_types": ["aspiration_intermediate_catheter", "distal_access_catheter", "aspiration_system_component"],
        "conical_categories": ["L2"],
    },
    "aspiration": {
        "category_types": ["aspiration_intermediate_catheter", "distal_access_catheter", "aspiration_system_component"],
        "conical_categories": ["L2"],
    },
    "dac": {
        "category_types": ["distal_access_catheter"],
        "conical_categories": ["L2"],
    },
    "distal_access_catheter": {
        "category_types": ["distal_access_catheter"],
        "conical_categories": ["L2"],
    },
    "catheter": {
        "category_types": [],  # Too broad — fall back to conical_category
        "conical_categories": ["L1", "L2", "L3"],
    },
    "stent_retriever": {
        "category_types": ["stent_system", "stent_retriever"],
        "conical_categories": ["L4", "L5"],
    },
    "stent": {
        "category_types": ["stent_system", "stent_retriever"],
        "conical_categories": ["L4", "L5"],
    },
    "wire": {
        "category_types": ["guidewire"],
        "conical_categories": ["LW"],
    },
    "guidewire": {
        "category_types": ["guidewire"],
        "conical_categories": ["LW"],
    },
}


# =============================================================================
# QueryExecutor
# =============================================================================

class QueryExecutor:
    """Executes structured query specs against the DATABASE dict."""

    def __init__(self):
        self.helper = DeviceSearchHelper()

    # -----------------------------------------------------------------
    # Main Entry Point
    # -----------------------------------------------------------------

    def execute(self, query_spec: dict) -> dict:
        """
        Execute a query spec. Supports single action or multi-step.

        Returns:
            {"results": <final results>, "context": <all step results>, "summary": <text>}
        """
        print(f"  [QueryExecutor] Executing query spec")

        if "steps" in query_spec:
            return self._execute_multi_step(query_spec)
        else:
            results = self._run_action(query_spec)
            summary = self._generate_summary(query_spec, results)
            return {"results": results, "context": {}, "summary": summary}

    def _execute_multi_step(self, query_spec: dict) -> dict:
        context = {}

        for step in query_spec["steps"]:
            step_id = step.get("step_id", step.get("store_as", "unknown"))
            print(f"    Step {step_id}: {step['action']}")

            result = self._run_action(step, context)
            store_key = step["store_as"]
            context[store_key] = result

            if isinstance(result, list):
                print(f"      -> {len(result)} results")
            else:
                print(f"      -> {result}")

        last_key = query_spec["steps"][-1]["store_as"]
        final_results = context[last_key]
        summary = self._generate_multi_step_summary(query_spec, context)

        return {"results": final_results, "context": context, "summary": summary}

    # -----------------------------------------------------------------
    # Action Router
    # -----------------------------------------------------------------

    def _run_action(self, step: dict, context: dict = None) -> object:
        context = context or {}
        step = self._resolve_references(step, context)
        action = step["action"]

        if action == "get_device_specs":
            return self._get_device_specs(step)
        elif action == "filter_by_spec":
            return self._filter_by_spec(step)
        elif action == "find_compatible":
            return self._find_compatible(step)
        elif action == "compare_devices":
            return self._compare_devices(step)
        elif action == "extract_value":
            return self._extract_value(step, context)
        elif action == "intersect":
            return self._intersect(step, context)
        elif action == "union":
            return self._union(step, context)
        elif action == "search_both_id_od":
            return self._search_both_id_od(step)
        else:
            print(f"  [QueryExecutor] Unknown action: {action}")
            return []

    # -----------------------------------------------------------------
    # Reference Resolution
    # -----------------------------------------------------------------

    def _resolve_references(self, step: dict, context: dict) -> dict:
        resolved = copy.deepcopy(step)

        for f in resolved.get("filters", []):
            if "value_from_step" in f:
                ref = f["value_from_step"]
                if ref in context:
                    f["value"] = context[ref]
                    del f["value_from_step"]
                    print(f"      Resolved {ref} -> {f['value']}")

        if "from_step" in resolved:
            ref = resolved["from_step"]
            if ref in context:
                resolved["source_data"] = context[ref]

        return resolved

    # -----------------------------------------------------------------
    # Action: get_device_specs
    # -----------------------------------------------------------------

    def _get_device_specs(self, step: dict) -> list:
        device_ids = step.get("device_ids", [])
        results = []
        for dev_id in device_ids:
            specs = self.helper.extract_device_specs(str(dev_id))
            if specs:
                results.append(specs)
        return results

    # -----------------------------------------------------------------
    # Action: filter_by_spec
    # -----------------------------------------------------------------

    def _filter_by_spec(self, step: dict) -> list:
        category = step.get("category")
        filters = step.get("filters", [])
        database = get_database()
        results = []

        for dev_id, device in database.items():
            if category and not self._matches_category(device, category):
                continue
            if self._passes_filters(device, filters):
                specs = self.helper.extract_device_specs(str(dev_id))
                if specs:
                    results.append(specs)

        print(f"  [QueryExecutor] filter_by_spec: {len(results)} devices match")
        return results

    # -----------------------------------------------------------------
    # Action: find_compatible
    # -----------------------------------------------------------------

    def _find_compatible(self, step: dict) -> list:
        source_ids = step.get("source_device_ids", [])
        target_category = step.get("target_category")
        direction = step.get("direction", "inner")
        check_length = step.get("check_length", True)
        database = get_database()

        source_specs = []
        for sid in source_ids:
            s = self.helper.extract_device_specs(str(sid))
            if s:
                source_specs.append(s)

        if not source_specs:
            print(f"  [QueryExecutor] No source device found")
            return []

        results = []
        for dev_id, device in database.items():
            if str(dev_id) in [str(s) for s in source_ids]:
                continue
            if target_category and not self._matches_category(device, target_category):
                continue
            target_specs = self.helper.extract_device_specs(str(dev_id))
            if not target_specs:
                continue
            is_compatible, reason = self._check_single_connection(
                source_specs, target_specs, direction, check_length
            )
            if is_compatible:
                target_specs["compatibility_reason"] = reason
                results.append(target_specs)

        print(f"  [QueryExecutor] find_compatible: {len(results)} compatible devices")
        return results

    # -----------------------------------------------------------------
    # Action: compare_devices
    # -----------------------------------------------------------------

    def _compare_devices(self, step: dict) -> list:
        device_groups = step.get("device_groups", [])
        all_results = []
        for group in device_groups:
            for dev_id in group:
                specs = self.helper.extract_device_specs(str(dev_id))
                if specs:
                    all_results.append(specs)
        return all_results

    # -----------------------------------------------------------------
    # Action: extract_value
    # -----------------------------------------------------------------

    def _extract_value(self, step: dict, context: dict) -> object:
        source_data = step.get("source_data", [])
        field = step["field"]
        aggregation = step.get("aggregation", "min")

        values = []
        for device in source_data:
            specs = device.get("specifications", {})
            val = specs.get(field)
            if val is None:
                val = device.get(field)
            if val is not None:
                try:
                    values.append(float(val))
                except (ValueError, TypeError):
                    values.append(val)

        if not values:
            print(f"  [QueryExecutor] No values found for field: {field}")
            return None

        if all(isinstance(v, (int, float)) for v in values):
            if aggregation == "min":
                result = min(values)
            elif aggregation == "max":
                result = max(values)
            elif aggregation == "avg":
                result = sum(values) / len(values)
            elif aggregation == "first":
                result = values[0]
            else:
                result = values[0]
        else:
            result = values[0]

        print(f"  [QueryExecutor] extract_value: {field} ({aggregation}) = {result}")
        return result

    # -----------------------------------------------------------------
    # Action: intersect
    # -----------------------------------------------------------------

    def _intersect(self, step: dict, context: dict) -> list:
        step_refs = step.get("from_steps", [])
        if not step_refs:
            return []

        id_sets = []
        for ref in step_refs:
            devices = context.get(ref, [])
            id_set = {d.get("device_id") for d in devices if d.get("device_id")}
            id_sets.append(id_set)

        if not id_sets:
            return []

        common_ids = id_sets[0]
        for s in id_sets[1:]:
            common_ids = common_ids & s

        first_devices = context.get(step_refs[0], [])
        results = [d for d in first_devices if d.get("device_id") in common_ids]

        print(f"  [QueryExecutor] intersect: {len(results)} devices in common")
        return results

    # -----------------------------------------------------------------
    # Action: union
    # -----------------------------------------------------------------

    def _union(self, step: dict, context: dict) -> list:
        step_refs = step.get("from_steps", [])
        seen_ids = set()
        results = []

        for ref in step_refs:
            for device in context.get(ref, []):
                dev_id = device.get("device_id")
                if dev_id and dev_id not in seen_ids:
                    seen_ids.add(dev_id)
                    results.append(device)

        print(f"  [QueryExecutor] union: {len(results)} unique devices")
        return results

    # -----------------------------------------------------------------
    # Action: search_both_id_od
    # -----------------------------------------------------------------

    def _search_both_id_od(self, step: dict) -> dict:
        category = step.get("category")
        dim_value = step.get("dimension_value")
        dim_operator = step.get("dimension_operator", ">=")
        additional_filters = step.get("additional_filters", [])
        database = get_database()

        id_matches = []
        od_matches = []

        for dev_id, device in database.items():
            if category and not self._matches_category(device, category):
                continue
            if not self._passes_filters(device, additional_filters):
                continue
            specs = self.helper.extract_device_specs(str(dev_id))
            if not specs:
                continue
            spec_values = specs.get("specifications", {})

            # Check ID
            id_val = spec_values.get("ID_in")
            if id_val is not None:
                try:
                    if self._compare_values(float(id_val), dim_operator, dim_value):
                        id_match = dict(specs)
                        id_match["matched_field"] = "ID_in"
                        id_match["matched_value"] = id_val
                        id_matches.append(id_match)
                except (ValueError, TypeError):
                    pass

            # Check OD (distal)
            od_val = spec_values.get("OD_distal_in")
            if od_val is not None:
                try:
                    if self._compare_values(float(od_val), dim_operator, dim_value):
                        od_match = dict(specs)
                        od_match["matched_field"] = "OD_distal_in"
                        od_match["matched_value"] = od_val
                        od_matches.append(od_match)
                except (ValueError, TypeError):
                    pass

        print(f"  [QueryExecutor] search_both_id_od: {len(id_matches)} ID matches, {len(od_matches)} OD matches")
        return {
            "id_matches": id_matches,
            "od_matches": od_matches,
            "dimension_value": dim_value,
            "dimension_operator": dim_operator,
        }

    # -----------------------------------------------------------------
    # Helper: Category Matching
    # -----------------------------------------------------------------

    def _matches_category(self, device: dict, category: str) -> bool:
        category_lower = category.lower().replace(" ", "_")
        mapping = CATEGORY_MAP.get(category_lower)
        if mapping:
            # Prefer category_type matching (more precise)
            cat_types = mapping.get("category_types", [])
            if cat_types:
                return device.get("category_type", "") in cat_types
            # Fall back to conical_category (for broad terms like "catheter")
            conical_cats = mapping.get("conical_categories", [])
            return device.get("conical_category", "") in conical_cats
        # Unknown category — fuzzy match on logic_category
        device_logic_cat = device.get("logic_category", "").lower()
        return category_lower in device_logic_cat

    # -----------------------------------------------------------------
    # Helper: Filter Matching
    # -----------------------------------------------------------------

    def _passes_filters(self, device: dict, filters: list) -> bool:
        for f in filters:
            field = f["field"]
            operator = f["operator"]
            target_value = f["value"]

            db_field = FIELD_MAP.get(field, field)
            device_value = device.get(db_field)

            if device_value is None:
                return False

            # Try numeric comparison first
            try:
                num_device = float(device_value)
                num_target = float(target_value)
                if not self._compare_values(num_device, operator, num_target):
                    return False
            except (ValueError, TypeError):
                # String comparison (manufacturer, product_name, etc.)
                dv = str(device_value).lower()
                tv = str(target_value).lower()
                if operator == "==":
                    if dv != tv:
                        return False
                elif operator == "!=":
                    if dv == tv:
                        return False
                elif operator == "contains":
                    if tv not in dv:
                        return False
                else:
                    return False

        return True

    # -----------------------------------------------------------------
    # Helper: Value Comparison
    # -----------------------------------------------------------------

    def _compare_values(self, device_value: float, operator: str, target_value: float) -> bool:
        if operator == "<=":
            return device_value <= target_value
        elif operator == ">=":
            return device_value >= target_value
        elif operator == "<":
            return device_value < target_value
        elif operator == ">":
            return device_value > target_value
        elif operator == "==":
            return abs(device_value - target_value) < 0.0001
        elif operator == "!=":
            return abs(device_value - target_value) >= 0.0001
        return False

    # -----------------------------------------------------------------
    # Helper: Single Connection Compatibility Check
    # -----------------------------------------------------------------

    def _check_single_connection(
        self, source_specs: list, target_specs: dict,
        direction: str, check_length: bool,
    ) -> tuple:
        target_spec_values = target_specs.get("specifications", {})

        for source in source_specs:
            source_spec_values = source.get("specifications", {})

            fit_passes = False
            if direction == "inner":
                source_id = self._get_float(source_spec_values, "ID_in")
                target_od = self._get_float(target_spec_values, "OD_distal_in")
                if source_id is not None and target_od is not None:
                    fit_passes = target_od <= source_id
            elif direction == "outer":
                source_od = self._get_float(source_spec_values, "OD_distal_in")
                target_id = self._get_float(target_spec_values, "ID_in")
                if source_od is not None and target_id is not None:
                    fit_passes = target_id >= source_od

            if not fit_passes:
                continue

            if check_length:
                source_length = self._get_float(source_spec_values, "length_cm")
                target_length = self._get_float(target_spec_values, "length_cm")
                if source_length is not None and target_length is not None:
                    if target_length < source_length:
                        continue

            return True, "math_fit_pass"

        return False, "no_fit"

    def _get_float(self, specs: dict, field: str):
        val = specs.get(field)
        if val is None:
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    # -----------------------------------------------------------------
    # Summary Generation
    # -----------------------------------------------------------------

    def _generate_summary(self, query_spec: dict, results) -> str:
        action = query_spec.get("action", "")
        lines = []

        if action == "search_both_id_od":
            dim_val = results.get("dimension_value")
            dim_op = results.get("dimension_operator")
            id_matches = results.get("id_matches", [])
            od_matches = results.get("od_matches", [])

            lines.append(f'Search for devices with dimension {dim_op} {dim_val}"')
            lines.append("")

            if id_matches:
                lines.append(f"Devices matching by INNER DIAMETER (ID): {len(id_matches)}")
                for d in id_matches:
                    name = d.get("device_name", "Unknown")
                    mfr = d.get("manufacturer", "Unknown")
                    specs = d.get("specifications", {})
                    compat = d.get("compatibility", {})
                    lines.append(f"  - {name} ({mfr})")
                    for k, v in specs.items():
                        lines.append(f"      {k}: {v}")
                    if compat:
                        for k, v in compat.items():
                            lines.append(f"      {k}: {v}")
                lines.append("")

            if od_matches:
                lines.append(f"Devices matching by OUTER DIAMETER (OD): {len(od_matches)}")
                for d in od_matches:
                    name = d.get("device_name", "Unknown")
                    mfr = d.get("manufacturer", "Unknown")
                    specs = d.get("specifications", {})
                    compat = d.get("compatibility", {})
                    lines.append(f"  - {name} ({mfr})")
                    for k, v in specs.items():
                        lines.append(f"      {k}: {v}")
                    if compat:
                        for k, v in compat.items():
                            lines.append(f"      {k}: {v}")

            return "\n".join(lines)

        if isinstance(results, list):
            lines.append(f"Found {len(results)} devices")
            lines.append("")

            for d in results:
                name = d.get("device_name", "Unknown")
                product = d.get("product_name", "Unknown")
                mfr = d.get("manufacturer", "Unknown")
                specs = d.get("specifications", {})

                lines.append(f"Device: {name}")
                lines.append(f"  Product: {product}")
                lines.append(f"  Manufacturer: {mfr}")
                if specs:
                    for k, v in specs.items():
                        lines.append(f"  {k}: {v}")
                compat = d.get("compatibility", {})
                if compat:
                    lines.append(f"  Compatibility Rules:")
                    for k, v in compat.items():
                        lines.append(f"    {k}: {v}")
                reason = d.get("compatibility_reason")
                if reason:
                    lines.append(f"  Compatibility: {reason}")
                lines.append("")

        return "\n".join(lines)

    def _generate_multi_step_summary(self, query_spec: dict, context: dict) -> str:
        lines = ["Multi-step query results:", ""]

        steps = query_spec["steps"]
        last_step_idx = len(steps) - 1

        for i, step in enumerate(steps):
            store_key = step["store_as"]
            result = context.get(store_key)
            is_final = (i == last_step_idx)

            lines.append(f"Step: {step.get('step_id', store_key)} ({step['action']})")

            if isinstance(result, list):
                lines.append(f"  -> {len(result)} results")

                if is_final:
                    for d in result:
                        if isinstance(d, dict):
                            name = d.get("device_name", d.get("product_name", "Unknown"))
                            specs = d.get("specifications", {})
                            compat = d.get("compatibility", {})
                            lines.append(f"    - {name}")
                            for k, v in specs.items():
                                lines.append(f"        {k}: {v}")
                            if compat:
                                lines.append(f"        Compatibility Rules:")
                                for k, v in compat.items():
                                    lines.append(f"          {k}: {v}")

            elif isinstance(result, dict):
                if "id_matches" in result:
                    lines.append(
                        f"  -> ID matches: {len(result['id_matches'])}, "
                        f"OD matches: {len(result['od_matches'])}"
                    )
                    if is_final:
                        for d in result.get("id_matches", []):
                            if isinstance(d, dict):
                                name = d.get("device_name", d.get("product_name", "Unknown"))
                                specs = d.get("specifications", {})
                                lines.append(f"    [ID match] - {name}")
                                for k, v in specs.items():
                                    lines.append(f"        {k}: {v}")
                        for d in result.get("od_matches", []):
                            if isinstance(d, dict):
                                name = d.get("device_name", d.get("product_name", "Unknown"))
                                specs = d.get("specifications", {})
                                lines.append(f"    [OD match] - {name}")
                                for k, v in specs.items():
                                    lines.append(f"        {k}: {v}")
                else:
                    lines.append(f"  -> {result}")
            else:
                lines.append(f"  -> {result}")

            lines.append("")

        return "\n".join(lines)
