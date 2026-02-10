"""
ChainTextBuilder - Deterministic text builder for chain engine output.

Produces rich, dimensionally-detailed text summaries from already-computed
chain analysis data. Replaces sparse ChainSummaryAgent text with v1-quality
output including per-connection spec values, multi-variant breakdowns,
and failure reasons.

No LLM calls — pure Python string formatting.
"""


class ChainTextBuilder:
    """
    Builds rich text summaries from chain analysis results.

    Data sources:
        chain_summary: from ChainAnalyzerMulti.get_summary()
        processed_results: from ChainPairGenerator.process_chain_results()
        subset_analysis: optional N-1 results from decision_logic.run_n1_subsets()
    """

    def __init__(self, chain_summary: dict, processed_results: list, subset_analysis=None):
        self.chain_summary = chain_summary
        self.processed_results = processed_results
        self.subset_analysis = subset_analysis
        self.specs_cache = self._build_specs_cache()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build(self, result_type: str) -> str:
        """Dispatch to the appropriate sub-type formatter."""
        if result_type == "compatibility_check":
            return self._build_compatibility_check()
        elif result_type == "device_discovery":
            return self._build_device_discovery()
        elif result_type == "stack_validation":
            return self._build_stack_validation()
        return self._build_compatibility_check()

    # ------------------------------------------------------------------
    # Specs cache — index every device seen in processed_results
    # ------------------------------------------------------------------

    def _build_specs_cache(self) -> dict:
        """
        Walk processed_results, extract spec values for every device.
        Indexed by device_id, device_name, and product_name.
        """
        cache = {}  # key -> {product_name, device_name, manufacturer, od_in, id_in, length_cm, ...}

        for chain in self.processed_results:
            for path in chain.get("paths", []):
                for conn in path.get("connections", []):
                    for pair in conn.get("processed_pairs", []):
                        for role in ("inner", "outer"):
                            device = pair.get(role, {})
                            if not device:
                                continue
                            entry = self._extract_specs(device)
                            # Index by multiple keys
                            for key in (
                                str(device.get("id", "")),
                                device.get("device_name", ""),
                                device.get("product_name", ""),
                            ):
                                if key and key not in cache:
                                    cache[key] = entry
        return cache

    def _extract_specs(self, device: dict) -> dict:
        """Extract the key spec fields from a full device record."""
        return {
            "product_name": device.get("product_name", ""),
            "device_name": device.get("device_name", ""),
            "manufacturer": device.get("manufacturer", ""),
            "od_distal_in": self._to_float(device.get("specification_outer-diameter-distal_in")),
            "od_proximal_in": self._to_float(device.get("specification_outer-diameter-proximal_in")),
            "id_in": self._to_float(device.get("specification_inner-diameter_in")),
            "length_cm": self._to_float(device.get("specification_length_cm")),
            "od_distal_mm": self._to_float(device.get("specification_outer-diameter-distal_mm")),
            "id_mm": self._to_float(device.get("specification_inner-diameter_mm")),
        }

    # ------------------------------------------------------------------
    # Formatting helpers
    # ------------------------------------------------------------------

    def _to_float(self, val) -> float | None:
        if val is None or val == "":
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    def _fmt_in(self, val) -> str:
        """Format an inches value for display."""
        if val is None:
            return "N/A"
        return f'{val:.3f}"'

    def _fmt_cm(self, val) -> str:
        if val is None:
            return "N/A"
        return f"{val:.0f}cm"

    def _get_specs(self, name: str) -> dict | None:
        """Look up specs by device_name or product_name."""
        return self.specs_cache.get(name)

    def _format_device_inline(self, name: str) -> str:
        """Format device with inline specs: 'Vecta 46 (OD: 0.058" | ID: 0.046" | 96cm)'"""
        specs = self._get_specs(name)
        if not specs:
            return name
        parts = []
        if specs.get("manufacturer"):
            parts.append(specs["manufacturer"])
        if specs["od_distal_in"] is not None:
            parts.append(f"OD: {self._fmt_in(specs['od_distal_in'])}")
        if specs["id_in"] is not None:
            parts.append(f"ID: {self._fmt_in(specs['id_in'])}")
        if specs["length_cm"] is not None:
            parts.append(self._fmt_cm(specs["length_cm"]))
        if parts:
            return f"{name} ({' | '.join(parts)})"
        return name

    # ------------------------------------------------------------------
    # Connection-level spec extraction from pair data
    # ------------------------------------------------------------------

    def _get_connection_spec_text(self, pair_reasons: list, passes: list, failures: list) -> list:
        """
        Build per-connection spec text lines from pass/fail reason data.

        Returns a list of formatted text lines for each device-to-device pair.
        """
        lines = []

        # Process passing pairs
        for pass_group in passes:
            for pr in pass_group.get("pair_reasons", []):
                reasons = pr.get("reasons", {})
                inner_name = reasons.get("inner_device_name", "")
                outer_name = reasons.get("outer_device_name", "")

                inner_specs = self._get_specs(inner_name)
                outer_specs = self._get_specs(outer_name)

                if not inner_specs or not outer_specs:
                    lines.append(f"  {inner_name} -> {outer_name}: Compatible")
                    continue

                # Build connection detail line
                inner_od = inner_specs.get("od_distal_in")
                outer_id = outer_specs.get("id_in")

                fit_text = ""
                if inner_od is not None and outer_id is not None:
                    fit_text = f"OD {self._fmt_in(inner_od)} -> ID {self._fmt_in(outer_id)}"

                inner_len = inner_specs.get("length_cm")
                outer_len = outer_specs.get("length_cm")
                len_text = ""
                if inner_len is not None and outer_len is not None:
                    len_text = f"Length: {inner_name} {self._fmt_cm(inner_len)}, {outer_name} {self._fmt_cm(outer_len)}"

                line = f"  {inner_name} -> {outer_name}: Compatible"
                if fit_text:
                    line += f" ({fit_text})"
                lines.append(line)
                if len_text:
                    lines.append(f"    {len_text}")

                # Note geometry override if applicable
                if pr.get("pass_reason_type") == "geometry_override":
                    lines.append(f"    Note: Passed via geometry check (IFU compatibility not available)")

                # Only show one representative pair per pass group
                break

        # Process failing pairs
        for fail_group in failures:
            compat_failures = fail_group.get("compatibility_failures", [])
            geo_failures = fail_group.get("geometry_failures", [])

            for cf in compat_failures:
                inner_name = cf.get("inner_device_name", "")
                outer_name = cf.get("outer_device_name", "")
                compat_field = cf.get("compatibility_field", "")
                compat_value = cf.get("compat_value", "")
                spec_value = cf.get("spec_value", "")

                reason_text = self._format_compat_failure(
                    inner_name, outer_name, compat_field, compat_value, spec_value
                )
                lines.append(f"  {inner_name} -> {outer_name}: Not Compatible")
                lines.append(f"    {reason_text}")
                break  # One representative per group

            if not compat_failures:
                for gf in geo_failures:
                    inner_name = gf.get("inner_device_name", "")
                    outer_name = gf.get("outer_device_name", "")
                    outer_value = gf.get("outer_value", "")
                    inner_value = gf.get("inner_value", "")
                    difference = gf.get("difference", "")

                    lines.append(f"  {inner_name} -> {outer_name}: Not Compatible")
                    lines.append(f"    Geometry fail: outer {outer_value} vs inner {inner_value} (diff: {difference})")
                    break

        return lines

    def _format_compat_failure(self, inner_name, outer_name, compat_field, compat_value, spec_value) -> str:
        """Format a compatibility failure into a concise reason string."""
        if "wire_max_outer-diameter" in str(compat_field):
            return f"Max wire OD: {compat_value}, but {inner_name} OD: {spec_value}"
        elif "catheter_max_outer-diameter" in str(compat_field):
            return f"Max catheter OD: {compat_value}, but {inner_name} OD: {spec_value}"
        elif "catheter_req_inner-diameter" in str(compat_field):
            return f"Required catheter ID: {compat_value}, but {outer_name} ID: {spec_value}"
        elif "guide_or_catheter_or_sheath_min_inner-diameter" in str(compat_field):
            return f"Min guide/catheter ID: {compat_value}, but {outer_name} ID: {spec_value}"
        return f"{compat_field}: required {compat_value}, actual {spec_value}"

    # ------------------------------------------------------------------
    # COMPATIBILITY CHECK builder
    # ------------------------------------------------------------------

    def _build_compatibility_check(self) -> str:
        """
        Build text for compatibility_check result type.

        For each chain (passed + failed):
          - Header: COMPATIBLE / NOT COMPATIBLE + device path
          - Per-connection: dimensional evidence
          - Variant summary for multi-size devices
          - Failure reasons with spec values
        """
        sections = []
        all_chains = (
            self.chain_summary.get("passed_chains", [])
            + self.chain_summary.get("failed_chains", [])
        )

        total = self.chain_summary.get("total_chains", len(all_chains))
        passing = self.chain_summary.get("passing_chain_count", 0)
        failing = self.chain_summary.get("failing_chain_count", 0)

        sections.append(f"Chains tested: {total} | Passing: {passing} | Failing: {failing}\n")

        for chain in all_chains:
            chain_status = chain.get("status", "fail")
            status_label = "COMPATIBLE" if chain_status == "pass" else "NOT COMPATIBLE"

            for path in chain.get("path_results", []):
                device_path = path.get("device_path", [])
                path_str = " -> ".join(device_path) if device_path else "Unknown path"
                path_status = path.get("status", chain_status)
                path_label = "COMPATIBLE" if path_status == "pass" else "NOT COMPATIBLE"

                section_lines = [f"{path_label}: {path_str}"]

                for conn in path.get("connection_results", []):
                    inner = conn.get("inner_device", "")
                    outer = conn.get("outer_device", "")
                    conn_status = conn.get("status", "fail")
                    product_results = conn.get("product_results", [])
                    passes = conn.get("passes", [])
                    failures = conn.get("failures", [])

                    # Variant summary
                    for pr in product_results:
                        combo = pr.get("product_combination", "")
                        total_v = pr.get("total_variants", 0)
                        passing_v = pr.get("passing_variants", 0)
                        failing_v = pr.get("failing_variants", 0)

                        if total_v > 1:
                            section_lines.append(
                                f"\n  {combo}: {passing_v} of {total_v} variants compatible"
                            )
                            if failing_v > 0:
                                section_lines.append(
                                    f"    ({failing_v} variant(s) not compatible)"
                                )

                    # Per-connection spec details
                    spec_lines = self._get_connection_spec_text([], passes, failures)
                    section_lines.extend(spec_lines)

                    # Detailed failure reasons for failing variants
                    for fail_group in failures:
                        for pr in fail_group.get("pair_reasons", []):
                            reasons = pr.get("reasons", {})
                            inner_name = reasons.get("inner_device_name", "")
                            outer_name = reasons.get("outer_device_name", "")
                            summary = reasons.get("summary", "")

                            # Only show detailed reasons for failing pairs not yet shown
                            compat_reasons = reasons.get("compatibility_reasons", [])
                            geo_reasons = reasons.get("geometry_reasons", {})
                            diameter_reasons = geo_reasons.get("diameter", [])
                            length_reasons = geo_reasons.get("length", [])

                            if compat_reasons:
                                for cr in compat_reasons:
                                    section_lines.append(f"    - {cr}")
                            if diameter_reasons:
                                for dr in diameter_reasons:
                                    section_lines.append(f"    - {dr}")
                            if length_reasons:
                                for lr in length_reasons:
                                    section_lines.append(f"    - {lr}")

                sections.append("\n".join(section_lines))

        # Subset analysis (N-1 scenarios)
        if self.subset_analysis:
            sections.append(self._format_subset_analysis())

        return "\n\n".join(sections)

    # ------------------------------------------------------------------
    # DEVICE DISCOVERY builder
    # ------------------------------------------------------------------

    def _build_device_discovery(self) -> str:
        """
        Build text for device_discovery result type.

        Shows source device specs + categorized compatible device list with inline specs.
        """
        sections = []
        passed_chains = self.chain_summary.get("passed_chains", [])

        if not passed_chains:
            return "No compatible devices found."

        # Collect all unique passing device combos across chains
        source_devices = set()
        compatible_devices = {}  # product_name -> specs

        for chain in passed_chains:
            for path in chain.get("path_results", []):
                device_path = path.get("device_path", [])
                if device_path:
                    # First device in path is usually the source (distal)
                    source_devices.add(device_path[0])

                for conn in path.get("connection_results", []):
                    if conn.get("status") != "pass":
                        continue
                    for pass_group in conn.get("passes", []):
                        for pr in pass_group.get("pair_reasons", []):
                            reasons = pr.get("reasons", {})
                            outer_name = reasons.get("outer_device_name", "")
                            if outer_name:
                                specs = self._get_specs(outer_name)
                                if specs and outer_name not in source_devices:
                                    compatible_devices[outer_name] = specs

        # Source device section
        sections.append("SOURCE DEVICE(S):\n")
        for src in sorted(source_devices):
            sections.append(f"  {self._format_device_inline(src)}")

        # Compatible devices section
        if compatible_devices:
            sections.append(f"\nCOMPATIBLE DEVICES ({len(compatible_devices)} found):\n")
            for name in sorted(compatible_devices.keys()):
                sections.append(f"  {self._format_device_inline(name)}")

        # Variant failures
        failed_chains = self.chain_summary.get("failed_chains", [])
        if failed_chains:
            sections.append("\nINCOMPATIBLE CONFIGURATIONS:")
            for chain in failed_chains:
                for path in chain.get("path_results", []):
                    device_path = path.get("device_path", [])
                    path_str = " -> ".join(device_path)
                    sections.append(f"\n  NOT COMPATIBLE: {path_str}")
                    for conn in path.get("connection_results", []):
                        for fail_group in conn.get("failures", []):
                            combo = fail_group.get("device_combination", "")
                            for cf in fail_group.get("compatibility_failures", [])[:1]:
                                reason = self._format_compat_failure(
                                    cf.get("inner_device_name", ""),
                                    cf.get("outer_device_name", ""),
                                    cf.get("compatibility_field", ""),
                                    cf.get("compat_value", ""),
                                    cf.get("spec_value", ""),
                                )
                                sections.append(f"    {reason}")

        return "\n".join(sections)

    # ------------------------------------------------------------------
    # STACK VALIDATION builder
    # ------------------------------------------------------------------

    def _build_stack_validation(self) -> str:
        """
        Build text for stack_validation result type.

        Shows ordered stack with per-connection dimensional evidence.
        """
        sections = []
        passed_chains = self.chain_summary.get("passed_chains", [])
        failed_chains = self.chain_summary.get("failed_chains", [])
        total = self.chain_summary.get("total_chains", 0)
        passing = self.chain_summary.get("passing_chain_count", 0)

        if not passed_chains and not failed_chains:
            return "No chain configurations were tested."

        sections.append(f"Configurations tested: {total} | Valid: {passing}\n")

        # Passing stacks
        for chain in passed_chains:
            for path in chain.get("path_results", []):
                device_path = path.get("device_path", [])
                if not device_path:
                    continue

                path_str = " -> ".join(device_path)
                section_lines = [f"VALID CONFIGURATION: {path_str}\n"]

                # Stack order
                section_lines.append("Stack order (distal -> proximal):")
                for i, dev in enumerate(device_path):
                    position = "DISTAL" if i == 0 else ("PROXIMAL" if i == len(device_path) - 1 else "MIDDLE")
                    section_lines.append(f"  {i+1}. [{position}] {self._format_device_inline(dev)}")

                # Connection details
                section_lines.append("\nConnection details:")
                for conn in path.get("connection_results", []):
                    inner = conn.get("inner_device", "")
                    outer = conn.get("outer_device", "")
                    conn_status = "Compatible" if conn.get("status") == "pass" else "Not Compatible"

                    inner_specs = self._get_specs(inner)
                    outer_specs = self._get_specs(outer)

                    inner_od = self._fmt_in(inner_specs.get("od_distal_in")) if inner_specs else "N/A"
                    outer_id = self._fmt_in(outer_specs.get("id_in")) if outer_specs else "N/A"

                    section_lines.append(
                        f"  {inner} (OD {inner_od}) -> {outer} (ID {outer_id}): {conn_status}"
                    )

                    # Variant details if multi-size
                    for pr in conn.get("product_results", []):
                        total_v = pr.get("total_variants", 0)
                        passing_v = pr.get("passing_variants", 0)
                        if total_v > 1:
                            section_lines.append(
                                f"    {passing_v} of {total_v} variants compatible"
                            )

                    # Failure reasons
                    for fail_group in conn.get("failures", []):
                        for cf in fail_group.get("compatibility_failures", [])[:3]:
                            reason = self._format_compat_failure(
                                cf.get("inner_device_name", ""),
                                cf.get("outer_device_name", ""),
                                cf.get("compatibility_field", ""),
                                cf.get("compat_value", ""),
                                cf.get("spec_value", ""),
                            )
                            section_lines.append(f"    Fail: {reason}")

                sections.append("\n".join(section_lines))

        # Failing stacks
        for chain in failed_chains:
            for path in chain.get("path_results", []):
                device_path = path.get("device_path", [])
                path_str = " -> ".join(device_path)
                section_lines = [f"INVALID CONFIGURATION: {path_str}"]

                for conn in path.get("connection_results", []):
                    if conn.get("status") != "pass":
                        inner = conn.get("inner_device", "")
                        outer = conn.get("outer_device", "")
                        section_lines.append(f"  Failing connection: {inner} -> {outer}")

                        for fail_group in conn.get("failures", []):
                            for cf in fail_group.get("compatibility_failures", [])[:2]:
                                reason = self._format_compat_failure(
                                    cf.get("inner_device_name", ""),
                                    cf.get("outer_device_name", ""),
                                    cf.get("compatibility_field", ""),
                                    cf.get("compat_value", ""),
                                    cf.get("spec_value", ""),
                                )
                                section_lines.append(f"    {reason}")
                            for gf in fail_group.get("geometry_failures", [])[:2]:
                                section_lines.append(
                                    f"    Geometry: outer {gf.get('outer_value', '')} vs "
                                    f"inner {gf.get('inner_value', '')} (diff: {gf.get('difference', '')})"
                                )

                sections.append("\n".join(section_lines))

        # Subset analysis
        if self.subset_analysis:
            sections.append(self._format_subset_analysis())

        return "\n\n".join(sections)

    # ------------------------------------------------------------------
    # Subset analysis (N-1 scenarios)
    # ------------------------------------------------------------------

    def _format_subset_analysis(self) -> str:
        """Format N-1 subset results."""
        if not self.subset_analysis:
            return ""

        lines = ["N-1 SUBSET CONFIGURATIONS:"]
        if isinstance(self.subset_analysis, list):
            subsets = self.subset_analysis
        else:
            subsets = self.subset_analysis.get("subsets", [])

        for subset in subsets:
            excluded = subset.get("excluded_device", "unknown")
            status = subset.get("status", "unknown")
            label = "Valid" if status == "pass" else "Invalid"
            lines.append(f"\n  Excluding {excluded}: {label}")

            if status == "pass":
                chain_path = subset.get("chain_path", [])
                if chain_path:
                    lines.append(f"    Order: {' -> '.join(chain_path)}")

                # Show connection details if available
                connections = subset.get("connections", [])
                for conn in connections:
                    inner = conn.get("inner", "")
                    outer = conn.get("outer", "")
                    lines.append(f"    {inner} -> {outer}: Compatible")

        return "\n".join(lines)
