"""
ChainAnalyzerMulti - Analyzes processed chain results and rolls up by product/device name.

INSTRUCTIONS: Paste your exact ChainAnalyzerMulti class here.
This file should contain only the ChainAnalyzerMulti class from your production code.

Required imports are already included below.
"""

import copy
import re
from collections import defaultdict


# =============================================================================
# PASTE YOUR ChainAnalyzerMulti CLASS BELOW THIS LINE
# =============================================================================
# Copy the entire class from your production code, starting with:
#   class ChainAnalyzerMulti:
# and ending at the last method of the class.
# =============================================================================

        
class ChainAnalyzerMulti:
    """
    Analyzes processed chain results and rolls up by product/device name.
    Determines if a chain passes (at least one path where all connections pass)
    and identifies which device combinations failed and why.
    """
    
    def __init__(self, processed_results: list[dict]):
        """
        Initialize with processed results from process_chain_results().
        
        Args:
            processed_results: Output from process_chain_results()
        """
        self.processed_results = processed_results
    
    # ============== Helper methods for unit/field handling ==============
    
    def get_unit_from_field(self, field_name):
        if field_name.endswith('_in'):
            return 'inches'
        elif field_name.endswith('_mm'):
            return 'millimeters'
        elif field_name.endswith('_F'):
            return 'French'
        elif field_name.endswith('_cm'):
            return 'centimeters'
        return None
    
    def get_unit_abbrev(self, field_name):
        if field_name.endswith('_in'):
            return 'in'
        elif field_name.endswith('_mm'):
            return 'mm'
        elif field_name.endswith('_F'):
            return 'F'
        elif field_name.endswith('_cm'):
            return 'cm'
        return None
    
    def clean_field_name(self, field_name):
        name = field_name.replace('specification_', '').replace('outer_device_specification_field_', '')
        name = name.replace('_in', '').replace('_mm', '').replace('_F', '').replace('_cm', '')
        name = name.replace('-', ' ').replace('_', ' ')
        return name
    
    def select_best_unit_rows(self, rows, status_filter=None):
        """
        Select best unit rows (prefer inches, then mm, then F, then cm).
        Optionally filter by status ('pass', 'fail', etc.)
        """
        grouped = {}
        for row in rows:
            if row.get('difference') == 'NA':
                continue
            
            if status_filter and row.get('status') != status_filter:
                continue
            
            inner_field = row.get('inner_device_specification_field', '')
            outer_field = row.get('outer_device_specification_field', '')
            
            inner_base = inner_field.replace('specification_', '').replace('_in', '').replace('_mm', '').replace('_F', '').replace('_cm', '')
            outer_base = outer_field.replace('specification_', '').replace('_in', '').replace('_mm', '').replace('_F', '').replace('_cm', '')
            
            unique_key = f"{outer_base}_{inner_base}"
            unit = self.get_unit_abbrev(outer_field)
            
            if unique_key not in grouped:
                grouped[unique_key] = {}
            
            grouped[unique_key][unit] = row
        
        selected = []
        for unique_key, units in grouped.items():
            if 'in' in units:
                selected.append(units['in'])
            elif 'mm' in units:
                selected.append(units['mm'])
            elif 'F' in units:
                selected.append(units['F'])
            elif 'cm' in units:
                selected.append(units['cm'])
        
        return selected
    
    def select_best_compatibility_rows(self, supporting_rows, status_filter=None):
        """Select best unit rows for compatibility (prefer in, then mm, then F)."""
        grouped = {}
        for row in supporting_rows:
            row_status = row.get('status', '')
            
            if status_filter and row_status != status_filter:
                continue
            
            if row_status not in ['pass', 'fail']:
                continue
            
            compat_field = row.get('compatibility_field', '')
            base_field = compat_field.replace('_in', '').replace('_mm', '').replace('_F', '')
            unit = self.get_unit_abbrev(compat_field)
            
            if base_field not in grouped:
                grouped[base_field] = {}
            
            grouped[base_field][unit] = row
        
        selected_rows = []
        for base_field, units in grouped.items():
            if 'in' in units:
                selected_rows.append(units['in'])
            elif 'mm' in units:
                selected_rows.append(units['mm'])
            elif 'F' in units:
                selected_rows.append(units['F'])
        
        return selected_rows
    
    # ============== Reason generation methods ==============
    
    def create_geometry_reason(self, row, inner_device_name, outer_device_name):
        """Create a human-readable reason for a geometry result."""
        outer_field = self.clean_field_name(row['outer_device_specification_field'])
        inner_field = self.clean_field_name(row['inner_device_specification_field'])
        outer_value = row['outer_device_specification_value']
        inner_value = row['inner_device_specification_value']
        difference = row['difference']
        status = row.get('status', 'NA')
        
        unit = self.get_unit_from_field(row['outer_device_specification_field'])
        is_length = 'length' in row['outer_device_specification_field']
        
        if is_length:
            abs_diff = abs(difference)
            comparison = "longer" if difference > 0 else "shorter"
            reason = (f"The {inner_device_name} {inner_field} value of {inner_value} {unit} "
                      f"is {abs_diff:.4f} {unit} {comparison} than the "
                      f"{outer_device_name} {outer_field}'s {outer_value} {unit}. "
                      f"Status: {status}.")
        else:
            abs_diff = abs(difference)
            comparison = "larger" if difference > 0 else "smaller"
            reason = (f"The {outer_device_name} {outer_field} value of {outer_value} {unit} "
                      f"is {abs_diff:.4f} {unit} {comparison} than the "
                      f"{inner_device_name} {inner_field}'s {inner_value} {unit}. "
                      f"Status: {status}.")
        
        return reason
    
    def create_compatibility_reason(self, row):
        """Create a human-readable reason for a compatibility result."""
        device_type = row.get('type', '')
        device_name = row.get('device_name', '')
        other_device_name = row.get('other_device_name', '')
        compat_field = row.get('compatibility_field', '')
        compat_value = row.get('compat_value', '')
        spec_field = row.get('specification_field', '')
        spec_value = row.get('spec_value', '')
        status = row.get('status', 'NA')
        
        unit = self.get_unit_from_field(compat_field)
        spec_field_clean = self.clean_field_name(spec_field)
        
        if device_type == 'inner':
            device_label = f"The inner device {device_name}"
            other_device_label = f"the outer device {other_device_name}"
        else:
            device_label = f"The outer device {device_name}"
            other_device_label = f"the inner device {other_device_name}"
        
        if 'compatibility_wire_max_outer-diameter' in compat_field:
            reason = (f"{device_label} is compatible with a wire that has a maximum outer diameter of "
                      f"{compat_value} {unit} and {other_device_label} has a {spec_field_clean} of "
                      f"{spec_value} {unit}. Status: {status}.")
        
        elif 'compatibility_catheter_max_outer-diameter' in compat_field:
            reason = (f"{device_label} is compatible with a catheter that has a maximum outer diameter of "
                      f"{compat_value} {unit} and {other_device_label} has a {spec_field_clean} of "
                      f"{spec_value} {unit}. Status: {status}.")
        
        elif 'compatibility_catheter_req_inner-diameter' in compat_field:
            compat_value_str = str(compat_value)
            if '-' in compat_value_str:
                parts = compat_value_str.split('-')
                if len(parts) == 2:
                    low, high = parts[0], parts[1]
                    if low == high:
                        reason = (f"{device_label} is compatible with a catheter that has an inner diameter "
                                  f"equal to {low} {unit} and {other_device_label} has a {spec_field_clean} of "
                                  f"{spec_value} {unit}. Status: {status}.")
                    else:
                        reason = (f"{device_label} is compatible with a catheter that has an inner diameter "
                                  f">= {low} {unit} and <= {high} {unit} and {other_device_label} has a "
                                  f"{spec_field_clean} of {spec_value} {unit}. Status: {status}.")
                else:
                    reason = (f"{device_label} is compatible with a catheter that has an inner diameter "
                              f"equal to {compat_value} {unit} and {other_device_label} has a {spec_field_clean} of "
                              f"{spec_value} {unit}. Status: {status}.")
            else:
                reason = (f"{device_label} is compatible with a catheter that has an inner diameter "
                          f"equal to {compat_value} {unit} and {other_device_label} has a {spec_field_clean} of "
                          f"{spec_value} {unit}. Status: {status}.")
        
        elif 'compatibility_guide_or_catheter_or_sheath_min_inner-diameter' in compat_field:
            reason = (f"{device_label} is compatible with a guide, catheter or sheath that has a minimum "
                      f"inner diameter of {compat_value} {unit} and {other_device_label} has a "
                      f"{spec_field_clean} of {spec_value} {unit}. Status: {status}.")
        
        else:
            reason = (f"{device_label} has a {compat_field} of {compat_value} {unit} and "
                      f"{other_device_label} has a {spec_field_clean} of {spec_value} {unit}. Status: {status}.")
        
        return reason
    
    def generate_pair_reasons(self, pair):
        """
        Generate human-readable reasons for why a pair passed or failed.
        
        Returns:
            dict with compatibility_reasons, geometry_reasons, and overall summary
        """
        overall_status = pair.get('overall_status', {})
        compat_status = overall_status.get('compatibility_status', {})
        geo_status = overall_status.get('geometry_status', {})
        
        inner_name = pair.get('inner', {}).get('device_name', pair.get('inner_name', 'Unknown'))
        outer_name = pair.get('outer', {}).get('device_name', pair.get('outer_name', 'Unknown'))
        
        result = {
            'inner_device_name': inner_name,
            'outer_device_name': outer_name,
            'compatibility_reasons': [],
            'geometry_reasons': {
                'diameter': [],
                'length': []
            },
            'summary': ''
        }
        
        # Process compatibility reasons
        compat_status_value = compat_status.get('status', 'NA')
        supporting_rows = compat_status.get('supporting_rows', [])
        
        if compat_status_value in ['pass', 'fail']:
            selected_rows = self.select_best_compatibility_rows(supporting_rows, status_filter=compat_status_value)
            for row in selected_rows:
                reason = self.create_compatibility_reason(row)
                result['compatibility_reasons'].append(reason)
        
        # Process geometry reasons
        diameter_status = geo_status.get('diameter_status', {})
        length_status = geo_status.get('length_status', {})
        
        diameter_rows = diameter_status.get('supporting_rows', [])
        selected_diameter = self.select_best_unit_rows(diameter_rows)
        for row in selected_diameter:
            reason = self.create_geometry_reason(row, inner_name, outer_name)
            result['geometry_reasons']['diameter'].append(reason)
        
        length_rows = length_status.get('supporting_rows', [])
        selected_length = self.select_best_unit_rows(length_rows)
        for row in selected_length:
            reason = self.create_geometry_reason(row, inner_name, outer_name)
            result['geometry_reasons']['length'].append(reason)
        
        # Generate summary
        result['summary'] = self._generate_pair_summary(pair, compat_status_value, diameter_status, length_status)
        
        return result
      
    # def _generate_pair_summary(self, pair, compat_status_value, diameter_status, length_status):
    #     """Generate a summary explaining why this pair passed or failed."""
    #     inner_name = pair.get('inner', {}).get('device_name', pair.get('inner_name', 'Unknown'))
    #     outer_name = pair.get('outer', {}).get('device_name', pair.get('outer_name', 'Unknown'))
        
    #     dia_stat = diameter_status.get('status', 'NA')
    #     len_stat = length_status.get('status', 'NA')
        
    #     # Check for geometry override (compat failed but geometry passed)
    #     geometry_passes = 'pass' in dia_stat and 'pass' in len_stat
        
    #     if compat_status_value == 'fail':
    #         if geometry_passes:
    #             return (f"The connection between {inner_name} and {outer_name} PASSED based on geometry check "
    #                     f"(compatibility check failed but geometry override applied). "
    #                     f"Diameter status: {dia_stat}, Length status: {len_stat}.")
    #         else:
    #             return f"The connection between {inner_name} and {outer_name} FAILED based on compatibility check."
        
    #     elif compat_status_value == 'pass':
    #         return f"The connection between {inner_name} and {outer_name} PASSED based on compatibility check."
        
    #     elif compat_status_value == 'NA':
    #         if geometry_passes:
    #             return (f"The connection between {inner_name} and {outer_name} PASSED based on geometry check. "
    #                     f"Diameter status: {dia_stat}, Length status: {len_stat}.")
    #         else:
    #             return (f"The connection between {inner_name} and {outer_name} FAILED based on geometry check. "
    #                     f"Diameter status: {dia_stat}, Length status: {len_stat}.")
        
    #     return f"The connection between {inner_name} and {outer_name} has an unknown status."


    def _generate_pair_summary(self, pair, compat_status_value, diameter_status, length_status):
        """Generate a summary explaining why this pair passed or failed."""
        inner_name = pair.get('inner', {}).get('device_name', pair.get('inner_name', 'Unknown'))
        outer_name = pair.get('outer', {}).get('device_name', pair.get('outer_name', 'Unknown'))
        
        dia_stat = diameter_status.get('status', 'NA')
        len_stat = length_status.get('status', 'NA')
        
        # Check for geometry override (compat failed but geometry passed)
        geometry_passes = 'pass' in dia_stat and 'pass' in len_stat
        
        # NEW: Check for length failure override (compat passed but length failed)
        length_overrides_compat = compat_status_value == 'pass' and len_stat == 'fail'
        
        if length_overrides_compat:
            # Get length details for the message
            length_rows = length_status.get('supporting_rows', [])
            length_detail = ""
            for row in length_rows:
                if row.get('status') == 'fail':
                    inner_val = row.get('inner_device_specification_value', '?')
                    outer_val = row.get('outer_device_specification_value', '?')
                    length_detail = (f" The inner device length ({inner_val} cm) is shorter than "
                                    f"the outer device length ({outer_val} cm).")
                    break
            
            return (f"The connection between {inner_name} and {outer_name} FAILED. "
                    f"Diameter compatibility passed, but the inner device is too short "
                    f"to physically pass through the outer device.{length_detail}")
        
        elif compat_status_value == 'fail':
            if geometry_passes:
                return (f"The connection between {inner_name} and {outer_name} PASSED based on geometry check "
                        f"(compatibility check failed but geometry override applied). "
                        f"Diameter status: {dia_stat}, Length status: {len_stat}.")
            else:
                return f"The connection between {inner_name} and {outer_name} FAILED based on compatibility check."
        
        elif compat_status_value == 'pass':
            return f"The connection between {inner_name} and {outer_name} PASSED based on compatibility check."
        
        elif compat_status_value == 'NA':
            if geometry_passes:
                return (f"The connection between {inner_name} and {outer_name} PASSED based on geometry check. "
                        f"Diameter status: {dia_stat}, Length status: {len_stat}.")
            else:
                return (f"The connection between {inner_name} and {outer_name} FAILED based on geometry check. "
                        f"Diameter status: {dia_stat}, Length status: {len_stat}.")
        
        return f"The connection between {inner_name} and {outer_name} has an unknown status."


    # ============== Core analysis methods ==============
    
    def analyze(self) -> list[dict]:
        """
        Analyze all chains and return rollup results.
        
        Returns:
            List of chain analysis results
        """
        results = []
        
        for chain in self.processed_results:
            chain_result = self._analyze_chain(chain)
            results.append(chain_result)
        
        return results
    
    def _analyze_chain(self, chain: dict) -> dict:
        """
        Analyze a single chain's paths.
        
        A chain passes if at least one complete path passes.
        
        Args:
            chain: Single chain dict from processed_results
        
        Returns:
            Chain analysis with pass/fail status and failure details
        """
        chain_index = chain["chain_index"]
        active_levels = chain["active_levels"]
        total_paths = chain["total_paths"]
        paths = chain["paths"]
        
        path_results = []
        has_passing_path = False
        
        for path in paths:
            path_analysis = self._analyze_path(path)
            path_results.append(path_analysis)
            
            if path_analysis["status"] == "pass":
                has_passing_path = True
        
        return {
            "chain_index": chain_index,
            "active_levels": active_levels,
            "total_paths": total_paths,
            "status": "pass" if has_passing_path else "fail",
            "passing_paths": sum(1 for p in path_results if p["status"] == "pass"),
            "failing_paths": sum(1 for p in path_results if p["status"] == "fail"),
            "path_results": path_results
        }
    
    def _analyze_path(self, path: dict) -> dict:
        """
        Analyze a single path's connections.
        
        A path passes if all connections pass.
        
        Args:
            path: Single path dict from chain
        
        Returns:
            Path analysis with pass/fail status and failure details
        """
        path_index = path["path_index"]
        device_path = path["path"]
        connections = path["connections"]
        
        connection_results = []
        all_connections_pass = True
        
        for connection in connections:
            conn_analysis = self._analyze_connection(connection)
            connection_results.append(conn_analysis)
            
            if conn_analysis["status"] == "fail":
                all_connections_pass = False
        
        return {
            "path_index": path_index,
            "device_path": device_path,
            "status": "pass" if all_connections_pass else "fail",
            "connection_results": connection_results
        }
    
    def _analyze_connection(self, connection: dict) -> dict:
        """
        Analyze a single connection, rolling up by product name.

        A connection passes if at least one pair per product combination passes.
        Always includes failure details for any failing variants.

        SIMPLIFIED: Trusts overall_grade() as single source of truth.
        All override logic (geometry tiebreaker, length override) is in
        overall_grade() - we just read the final status here.

        Args:
            connection: Single connection dict with processed_pairs

        Returns:
            Connection analysis with status and failure details
        """
        conn_type = connection["connection_type"]
        conn_name = connection["connection"]
        inner_device = connection["inner_device"]
        outer_device = connection["outer_device"]
        processed_pairs = connection["processed_pairs"]

        pairs_by_product = defaultdict(list)

        for pair in processed_pairs:
            inner_name = pair["inner_name"]
            outer_name = pair["outer_name"]
            product_key = f"{inner_name} -> {outer_name}"
            pairs_by_product[product_key].append(pair)

        product_results = []
        all_products_pass = True
        failures = []
        passes = []

        for product_key, pairs in pairs_by_product.items():
            has_passing_pair = False
            failing_pairs = []
            passing_pairs = []

            for pair in pairs:
                overall_status = pair.get("overall_status", {})
                status = overall_status.get("status", "fail")

                # ============================================================
                # SIMPLIFIED: Just read overall_grade() result.
                # All logic (compat, geometry tiebreaker, length override)
                # is already handled in overall_grade().
                # ============================================================
                if status in ("pass", "pass_with_warning"):
                    has_passing_pair = True
                    passing_pairs.append(pair)
                else:
                    failing_pairs.append(pair)

            product_status = "pass" if has_passing_pair else "fail"

            product_result = {
                "product_combination": product_key,
                "status": product_status,
                "total_variants": len(pairs),
                "passing_variants": len(passing_pairs),
                "failing_variants": len(failing_pairs)
            }
            product_results.append(product_result)

            if not has_passing_pair:
                all_products_pass = False

            if failing_pairs:
                failure_info = self._extract_failure_reasons(product_key, failing_pairs)
                failures.append(failure_info)

            if passing_pairs:
                pass_info = self._extract_pass_reasons(product_key, passing_pairs)
                passes.append(pass_info)

        return {
            "connection": conn_name,
            "connection_type": conn_type,
            "inner_device": inner_device,
            "outer_device": outer_device,
            "status": "pass" if all_products_pass else "fail",
            "product_results": product_results,
            "failures": failures,
            "passes": passes
        }

    def _extract_failure_reasons(self, product_key: str, failing_pairs: list[dict]) -> dict:
        """
        Extract failure reasons from failing pairs with templated human-readable notes.
        
        Args:
            product_key: The product combination string
            failing_pairs: List of pairs that failed
        
        Returns:
            Failure info with reasons from compatibility_results and geometry_results
        """
        first_pair = failing_pairs[0] if failing_pairs else {}
        first_inner_device_name = first_pair.get("inner", {}).get("device_name", first_pair.get("inner_name", "Unknown"))
        first_outer_device_name = first_pair.get("outer", {}).get("device_name", first_pair.get("outer_name", "Unknown"))
        device_combination_key = f"{first_inner_device_name} -> {first_outer_device_name}"
        
        compatibility_failures = []
        geometry_failures = []
        pair_reasons = []
        
        for pair in failing_pairs:
            pair_key = pair["pair_key"]
            
            # Generate templated reasons for this pair
            reasons = self.generate_pair_reasons(pair)
            pair_reasons.append({
                'pair_key': pair_key,
                'reasons': reasons
            })
            
            inner_device_name = pair.get("inner", {}).get("device_name", pair.get("inner_name", "Unknown"))
            outer_device_name = pair.get("outer", {}).get("device_name", pair.get("outer_name", "Unknown"))
            device_name_key = f"{inner_device_name} -> {outer_device_name}"
            
            compat_status = pair.get("compatibility_status", {})
            if compat_status.get("status") == "fail":
                supporting_rows = compat_status.get("supporting_rows", [])
                for row in supporting_rows:
                    if row.get("status") == "fail":
                        note = row.get("note", "No details available")
                        compatibility_failures.append({
                            "pair_key": pair_key,
                            "device_combination": device_name_key,
                            "inner_device_name": inner_device_name,
                            "outer_device_name": outer_device_name,
                            "reason": note,
                            "compatibility_field": row.get("compatibility_field"),
                            "compat_value": row.get("compat_value"),
                            "specification_field": row.get("specification_field"),
                            "spec_value": row.get("spec_value")
                        })
            
            geo_status = pair.get("geometry_status", {})
            if geo_status.get("status") == "fail":
                supporting_rows = geo_status.get("supporting_rows", [])
                if isinstance(supporting_rows, list):
                    for row in supporting_rows:
                        if isinstance(row, dict) and row.get("status") == "fail":
                            note = row.get("note", "No details available")
                            geometry_failures.append({
                                "pair_key": pair_key,
                                "device_combination": device_name_key,
                                "inner_device_name": inner_device_name,
                                "outer_device_name": outer_device_name,
                                "reason": note,
                                "outer_field": row.get("outer_device_specification_field"),
                                "outer_value": row.get("outer_device_specification_value"),
                                "inner_field": row.get("inner_device_specification_field"),
                                "inner_value": row.get("inner_device_specification_value"),
                                "difference": row.get("difference")
                            })
                elif isinstance(supporting_rows, str):
                    geometry_failures.append({
                        "pair_key": pair_key,
                        "device_combination": device_name_key,
                        "inner_device_name": inner_device_name,
                        "outer_device_name": outer_device_name,
                        "reason": supporting_rows
                    })
        
        return {
            "device_combination": device_combination_key,
            "total_failing_pairs": len(failing_pairs),
            "compatibility_failures": compatibility_failures,
            "geometry_failures": geometry_failures,
            "pair_reasons": pair_reasons
        }
    
    def _extract_pass_reasons(self, product_key: str, passing_pairs: list[dict]) -> dict:
        """
        Extract pass reasons from passing pairs with templated human-readable notes.
        
        Args:
            product_key: The product combination string
            passing_pairs: List of pairs that passed
        
        Returns:
            Pass info with templated reasons
        """
        first_pair = passing_pairs[0] if passing_pairs else {}
        first_inner_device_name = first_pair.get("inner", {}).get("device_name", first_pair.get("inner_name", "Unknown"))
        first_outer_device_name = first_pair.get("outer", {}).get("device_name", first_pair.get("outer_name", "Unknown"))
        device_combination_key = f"{first_inner_device_name} -> {first_outer_device_name}"
        
        pair_reasons = []
        
        for pair in passing_pairs:
            pair_key = pair["pair_key"]
            reasons = self.generate_pair_reasons(pair)
            
            # Check if this passed due to geometry despite compatibility failure
            overall_status = pair.get("overall_status", {})
            compat_status = overall_status.get("compatibility_status", {}).get("status", "NA")
            geo_status = overall_status.get("geometry_status", {})
            diameter_status = geo_status.get("diameter_status", {}).get("status", "NA")
            length_status = geo_status.get("length_status", {}).get("status", "NA")
            
            pass_reason_type = "geometry_override" if compat_status == "fail" else "standard"
            
            if compat_status == "fail" and "pass" in diameter_status and "pass" in length_status:
                override_note = (
                    f"Note: Compatibility check failed, but geometry check passed "
                    f"(diameter: {diameter_status}, length: {length_status}). "
                    f"Connection marked as PASS based on geometry."
                )
            else:
                override_note = None
            
            pair_reasons.append({
                'pair_key': pair_key,
                'reasons': reasons,
                'pass_reason_type': pass_reason_type,
                'override_note': override_note
            })
        
        return {
            "device_combination": device_combination_key,
            "total_passing_pairs": len(passing_pairs),
            "pair_reasons": pair_reasons
        }
    # ============== Summary methods ==============
    
    def get_summary(self) -> dict:
        """
        Get a high-level summary of all chains, separated by pass/fail status.
        
        Returns:
            Summary dict with counts and chains grouped by status
        """
        analysis = self.analyze()
        
        passed_chains = []
        failed_chains = []
        
        for chain in analysis:
            if chain["status"] == "pass":
                passed_chains.append(chain)
            else:
                failed_chains.append(chain)
        
        return {
            "total_chains": len(analysis),
            "passing_chain_count": len(passed_chains),
            "failing_chain_count": len(failed_chains),
            "passed_chains": passed_chains,
            "failed_chains": failed_chains
        }
    
    def get_passing_paths(self) -> list[dict]:
        """
        Get only the passing paths across all chains.
        
        Returns:
            List of passing paths with their device orderings
        """
        analysis = self.analyze()
        passing_paths = []
        
        for chain in analysis:
            for path_result in chain["path_results"]:
                if path_result["status"] == "pass":
                    passing_paths.append({
                        "chain_index": chain["chain_index"],
                        "path_index": path_result["path_index"],
                        "device_path": path_result["device_path"]
                    })
        
        return passing_paths
