"""
ChainSummaryAgent - Creates structured summaries of chain analysis results.

INSTRUCTIONS: Paste your exact ChainSummaryAgent class here.
This file should contain only the ChainSummaryAgent class from your production code.

Required imports are already included below.
"""

import copy
import re
from collections import defaultdict


# =============================================================================
# PASTE YOUR ChainSummaryAgent CLASS BELOW THIS LINE
# =============================================================================
# Copy the entire class from your production code, starting with:
#   class ChainSummaryAgent:
# and ending at the last method of the class.
# =============================================================================



class ChainSummaryAgent:
    """
    Creates structured summaries of chain analysis results.
    Generates detailed records for passing chains with device connections.
    """
    
    def __init__(self, analysis_results, processed_results: list[dict]):
        """
        Initialize with analysis results from ChainAnalyzerMulti.
        
        Args:
            analysis_results: Output from ChainAnalyzerMulti.analyze() or get_summary()
            processed_results: Original processed results (for accessing pair details)
        """
        # Handle both formats: list of chains or dict with passed_chains/failed_chains
        if isinstance(analysis_results, dict) and "passed_chains" in analysis_results:
            # It's from get_summary(), extract the chains
            self.analysis_results = analysis_results.get("passed_chains", []) + analysis_results.get("failed_chains", [])
            self.summary_stats = {
                "total_chains": analysis_results.get("total_chains", 0),
                "passing_chain_count": analysis_results.get("passing_chain_count", 0),
                "failing_chain_count": analysis_results.get("failing_chain_count", 0)
            }
        else:
            # It's a list from analyze()
            self.analysis_results = analysis_results
            self.summary_stats = None
        
        self.processed_results = processed_results
    
    def get_mentioned_device_requirements(self, mentioned_devices: dict) -> dict:
        """
        Extract compatibility/specification requirements for user-mentioned devices in successful chains.
        
        Handles BOTH fit_logic types:
        - "compat": Extracts compatibility fields (what ID the device requires from adjacent devices)
        - "math": Extracts specification fields (ID for what can fit inside, OD for what it can fit into)
        
        Args:
            mentioned_devices: Dict in format:
                {
                    "mentioned_devices": {
                        "AXS Vecta 46": {"ids": ["56"], "conical_category": "L2"},
                        "Solitaire": {"ids": ["192", "196", ...], "conical_category": "L4"}
                    }
                }
        
        Returns:
            Dict with requirements for each mentioned device in successful chains
        """
        # Extract the inner dict if nested
        if "mentioned_devices" in mentioned_devices:
            devices_dict = mentioned_devices["mentioned_devices"]
        else:
            devices_dict = mentioned_devices
        
        # Build lookup for mentioned device IDs
        mentioned_ids = {}
        for product_name, info in devices_dict.items():
            for device_id in info.get("ids", []):
                mentioned_ids[str(device_id)] = {
                    "product_name": product_name,
                    "conical_category": info.get("conical_category", "Unknown")
                }
        
        results = {
            "successful_chains": [],
            "summary": {
                "total_successful_chains_analyzed": 0,
                "chains_with_mentioned_devices": 0,
                "mentioned_devices_found": []
            }
        }
        
        # Loop through successful chains only
        for chain in self.analysis_results:
            if chain.get("status") != "pass":
                continue
            
            results["summary"]["total_successful_chains_analyzed"] += 1
            
            # Process each passing path in this chain
            for path in chain.get("path_results", []):
                if path.get("status") != "pass":
                    continue
                
                device_path = path.get("device_path", [])
                chain_record = {
                    "chain_index": chain.get("chain_index"),
                    "device_path": device_path,
                    "mentioned_device_requirements": []
                }
                
                connection_results = path.get("connection_results", [])
                
                # Examine each connection to find mentioned devices
                for interface_index, conn_result in enumerate(connection_results, start=1):
                    # Get all passing pairs for this connection
                    all_passing_pairs = self._get_all_passing_pairs_for_requirements(conn_result)
                    
                    for pair_data in all_passing_pairs:
                        pair = pair_data["pair"]
                        inner = pair.get("inner", {})
                        outer = pair.get("outer", {})
                        
                        inner_id = str(inner.get("id", pair.get("inner_id", "")))
                        outer_id = str(outer.get("id", pair.get("outer_id", "")))
                        inner_fit_logic = inner.get("fit_logic", "")
                        outer_fit_logic = outer.get("fit_logic", "")
                        
                        # Check INNER device (distal position - fits INTO the outer device)
                        if inner_id in mentioned_ids:
                            if inner_fit_logic == "compat":
                                req = self._extract_compat_requirements(
                                    device=inner,
                                    mentioned_info=mentioned_ids[inner_id],
                                    position="distal",
                                    interface_index=interface_index,
                                    connected_to=outer.get("product_name", pair.get("outer_name", "Unknown")),
                                    device_path=device_path,
                                    pair=pair
                                )
                                if req:
                                    chain_record["mentioned_device_requirements"].append(req)
                            elif inner_fit_logic == "math":
                                req = self._extract_math_requirements(
                                    device=inner,
                                    mentioned_info=mentioned_ids[inner_id],
                                    position="distal",
                                    interface_index=interface_index,
                                    connected_to=outer.get("product_name", pair.get("outer_name", "Unknown")),
                                    connected_device=outer,
                                    device_path=device_path,
                                    pair=pair
                                )
                                if req:
                                    chain_record["mentioned_device_requirements"].append(req)
                        
                        # Check OUTER device (proximal position - inner device fits INTO this)
                        if outer_id in mentioned_ids:
                            if outer_fit_logic == "compat":
                                req = self._extract_compat_requirements(
                                    device=outer,
                                    mentioned_info=mentioned_ids[outer_id],
                                    position="proximal",
                                    interface_index=interface_index,
                                    connected_to=inner.get("product_name", pair.get("inner_name", "Unknown")),
                                    device_path=device_path,
                                    pair=pair
                                )
                                if req:
                                    chain_record["mentioned_device_requirements"].append(req)
                            elif outer_fit_logic == "math":
                                req = self._extract_math_requirements(
                                    device=outer,
                                    mentioned_info=mentioned_ids[outer_id],
                                    position="proximal",
                                    interface_index=interface_index,
                                    connected_to=inner.get("product_name", pair.get("inner_name", "Unknown")),
                                    connected_device=inner,
                                    device_path=device_path,
                                    pair=pair
                                )
                                if req:
                                    chain_record["mentioned_device_requirements"].append(req)
                
                # Only add chains that have mentioned devices
                if chain_record["mentioned_device_requirements"]:
                    results["successful_chains"].append(chain_record)
                    results["summary"]["chains_with_mentioned_devices"] += 1
        
        # Build summary of unique devices found
        seen_devices = set()
        for chain in results["successful_chains"]:
            for req in chain["mentioned_device_requirements"]:
                key = (req["product_name"], req["device_name"])
                if key not in seen_devices:
                    seen_devices.add(key)
                    results["summary"]["mentioned_devices_found"].append({
                        "product_name": req["product_name"],
                        "device_name": req["device_name"],
                        "conical_category": req["conical_category"],
                        "fit_logic": req["fit_logic"]
                    })
        
        return results
    
    def _extract_math_requirements(self, device: dict, mentioned_info: dict,
                                    position: str, interface_index: int,
                                    connected_to: str, connected_device: dict,
                                    device_path: list, pair: dict) -> dict | None:
        """
        Extract specification requirements from a device with fit_logic="math".
        
        For "math" devices, we look at:
        - If device is in PROXIMAL position (something fits INTO it): extract ID (inner diameter)
        - If device is in DISTAL position (it fits INTO something): extract OD (outer diameter)
        
        Args:
            device: The device dict
            mentioned_info: Info about this device from mentioned_devices
            position: "distal" (inner) or "proximal" (outer)
            interface_index: Position in the chain
            connected_to: Name of the device it connects to
            connected_device: The connected device dict
            device_path: Full device path list
            pair: The full pair dict for additional context
        
        Returns:
            Dict with extracted requirements or None if no relevant specs found
        """
        requirements = {
            "product_name": mentioned_info["product_name"],
            "device_name": device.get("device_name", "Unknown"),
            "device_id": device.get("id"),
            "conical_category": mentioned_info["conical_category"],
            "position_in_chain": position,
            "chain_position_description": self._describe_position(position, device_path, interface_index),
            "interface_index": interface_index,
            "fit_logic": "math",
            "logic_category": device.get("logic_category", "Unknown"),
            "connected_to": connected_to,
            "specifications": {},
            "working_range": {}
        }
        
        if position == "proximal":
            # This device has something fitting INTO it
            # We need to know the ID (inner diameter) - what OD range can fit inside
            requirements["role"] = "receiving"
            requirements["role_description"] = "Devices fit INTO this device"
            
            # Extract ID specifications
            id_specs = self._extract_id_specs(device)
            if id_specs:
                requirements["specifications"]["inner_diameter"] = id_specs
                
                # Calculate the range of ODs that can fit (ID minus clearance)
                # Based on the math logic, typically need 0.003" or 0.0762mm clearance
                requirements["working_range"]["accepts_outer_diameter"] = self._calculate_acceptable_od_range(id_specs)
            
            # Also show what actually fit in successful chain
            connected_od = self._extract_od_specs(connected_device)
            if connected_od:
                requirements["actual_connection"] = {
                    "connected_device": connected_to,
                    "connected_device_od": connected_od
                }
        
        else:  # position == "distal"
            # This device fits INTO something else
            # We need to know the OD (outer diameter) - what ID range it can fit into
            requirements["role"] = "inserting"
            requirements["role_description"] = "This device fits INTO other devices"
            
            # Extract OD specifications
            od_specs = self._extract_od_specs(device)
            if od_specs:
                requirements["specifications"]["outer_diameter"] = od_specs
                
                # Calculate the range of IDs this can fit into (OD plus clearance)
                requirements["working_range"]["requires_inner_diameter"] = self._calculate_required_id_range(od_specs)
            
            # Also show what it actually fit into in successful chain
            connected_id = self._extract_id_specs(connected_device)
            if connected_id:
                requirements["actual_connection"] = {
                    "connected_device": connected_to,
                    "connected_device_id": connected_id
                }
        
        # Only return if we found some specifications
        if requirements["specifications"]:
            return requirements
        return None
    
    def _extract_id_specs(self, device: dict) -> dict:
        """Extract inner diameter specifications from a device."""
        specs = {}
        
        id_fields = [
            ("specification_inner-diameter_in", "inches"),
            ("specification_inner-diameter_mm", "mm"),
            ("specification_inner-diameter_F", "French"),
        ]
        
        for field, unit in id_fields:
            value = device.get(field)
            if value and value != "":
                specs[unit] = value
        
        return specs
    
    def _extract_od_specs(self, device: dict) -> dict:
        """Extract outer diameter specifications from a device."""
        specs = {}
        
        # Check both distal and proximal OD
        od_fields = [
            ("specification_outer-diameter-distal_in", "distal_inches"),
            ("specification_outer-diameter-distal_mm", "distal_mm"),
            ("specification_outer-diameter-distal_F", "distal_French"),
            ("specification_outer-diameter-proximal_in", "proximal_inches"),
            ("specification_outer-diameter-proximal_mm", "proximal_mm"),
            ("specification_outer-diameter-proximal_F", "proximal_French"),
        ]
        
        for field, key in od_fields:
            value = device.get(field)
            if value and value != "":
                specs[key] = value
        
        return specs
    
    def _calculate_acceptable_od_range(self, id_specs: dict) -> dict:
        """
        Calculate the range of outer diameters that can fit into this ID.
        Uses the math logic clearance requirements (0.003" or 0.0762mm minimum).
        """
        result = {}
        
        if "inches" in id_specs:
            id_val = float(id_specs["inches"])
            max_od = id_val - 0.003  # Minimum clearance
            result["max_od_inches"] = round(max_od, 4)
            result["description_inches"] = f"Accepts OD up to {max_od:.4f} inches (ID {id_val} - 0.003 clearance)"
        
        if "mm" in id_specs:
            id_val = float(id_specs["mm"])
            max_od = id_val - 0.0762  # Minimum clearance in mm
            result["max_od_mm"] = round(max_od, 4)
            result["description_mm"] = f"Accepts OD up to {max_od:.4f} mm (ID {id_val} - 0.0762 clearance)"
        
        return result
    
    def _calculate_required_id_range(self, od_specs: dict) -> dict:
        """
        Calculate the range of inner diameters this device can fit into.
        Uses the largest OD (proximal) plus clearance requirements.
        """
        result = {}
        
        # Use proximal OD if available (larger), otherwise distal
        od_in = od_specs.get("proximal_inches") or od_specs.get("distal_inches")
        od_mm = od_specs.get("proximal_mm") or od_specs.get("distal_mm")
        
        if od_in:
            od_val = float(od_in)
            min_id = od_val + 0.003  # Minimum clearance
            result["min_id_inches"] = round(min_id, 4)
            result["device_od_inches"] = od_val
            result["description_inches"] = f"Requires ID of at least {min_id:.4f} inches (OD {od_val} + 0.003 clearance)"
        
        if od_mm:
            od_val = float(od_mm)
            min_id = od_val + 0.0762  # Minimum clearance in mm
            result["min_id_mm"] = round(min_id, 4)
            result["device_od_mm"] = od_val
            result["description_mm"] = f"Requires ID of at least {min_id:.4f} mm (OD {od_val} + 0.0762 clearance)"
        
        return result
    
    def _extract_compat_requirements(self, device: dict, mentioned_info: dict, 
                                      position: str, interface_index: int,
                                      connected_to: str, device_path: list,
                                      pair: dict) -> dict | None:
        """
        Extract the compatibility requirements from a device with fit_logic="compat".
        
        Args:
            device: The device dict (inner or outer)
            mentioned_info: Info about this device from mentioned_devices
            position: "distal" (inner) or "proximal" (outer)
            interface_index: Position in the chain
            connected_to: Name of the device it connects to
            device_path: Full device path list
            pair: The full pair dict for additional context
        
        Returns:
            Dict with extracted requirements or None if no compat fields found
        """
        requirements = {
            "product_name": mentioned_info["product_name"],
            "device_name": device.get("device_name", "Unknown"),
            "device_id": device.get("id"),
            "conical_category": mentioned_info["conical_category"],
            "position_in_chain": position,
            "chain_position_description": self._describe_position(position, device_path, interface_index),
            "interface_index": interface_index,
            "fit_logic": "compat",
            "logic_category": device.get("logic_category", "Unknown"),
            "connected_to": connected_to,
            "compatibility_requirements": []
        }
        
        # Extract all compatibility fields and their values
        compat_fields = [
            ("compatibility_catheter_req_inner-diameter_in", "Requires catheter with inner diameter (inches)"),
            ("compatibility_catheter_req_inner-diameter_mm", "Requires catheter with inner diameter (mm)"),
            ("compatibility_catheter_req_inner-diameter_F", "Requires catheter with inner diameter (French)"),
            ("compatibility_catheter_max_outer-diameter_in", "Max catheter outer diameter (inches)"),
            ("compatibility_catheter_max_outer-diameter_mm", "Max catheter outer diameter (mm)"),
            ("compatibility_catheter_max_outer-diameter_F", "Max catheter outer diameter (French)"),
            ("compatibility_wire_max_outer-diameter_in", "Max wire outer diameter (inches)"),
            ("compatibility_wire_max_outer-diameter_mm", "Max wire outer diameter (mm)"),
            ("compatibility_wire_max_outer-diameter_F", "Max wire outer diameter (French)"),
            ("compatibility_guide_or_catheter_or_sheath_min_inner-diameter_in", "Min guide/catheter/sheath inner diameter (inches)"),
            ("compatibility_guide_or_catheter_or_sheath_min_inner-diameter_mm", "Min guide/catheter/sheath inner diameter (mm)"),
            ("compatibility_guide_or_catheter_or_sheath_min_inner-diameter_F", "Min guide/catheter/sheath inner diameter (French)"),
        ]
        
        for field, description in compat_fields:
            value = device.get(field)
            if value and value != "":
                requirements["compatibility_requirements"].append({
                    "field": field,
                    "value": value,
                    "description": f"{description}: {value}"
                })
        
        # Also extract from compatibility_results if available
        compat_results = pair.get("compatibility_results", [])
        for result in compat_results:
            if result.get("fit_logic") == "compat" and result.get("status") == "pass":
                compat_field = result.get("compatibility_field")
                compat_value = result.get("compat_value")
                if compat_field and compat_value:
                    # Check if we already have this field
                    existing = [r for r in requirements["compatibility_requirements"] 
                               if r["field"] == compat_field]
                    if not existing:
                        requirements["compatibility_requirements"].append({
                            "field": compat_field,
                            "value": compat_value,
                            "description": f"From IFU: {compat_field} = {compat_value}",
                            "matched_spec_field": result.get("specification_field"),
                            "matched_spec_value": result.get("spec_value")
                        })
        
        # Only return if we found some requirements
        if requirements["compatibility_requirements"]:
            return requirements
        return None
    
    def _describe_position(self, position: str, device_path: list, interface_index: int) -> str:
        """
        Create a human-readable description of where the device is in the chain.
        
        Args:
            position: "distal" or "proximal"
            device_path: The full device path
            interface_index: The interface number
        
        Returns:
            Description string
        """
        total_interfaces = len(device_path) - 1
        
        if position == "distal":
            if interface_index == 1:
                return f"Most distal device (innermost), at interface 1 of {total_interfaces}"
            else:
                return f"Distal side of interface {interface_index} of {total_interfaces}"
        else:  # proximal
            if interface_index == total_interfaces:
                return f"Most proximal device (outermost), at interface {interface_index} of {total_interfaces}"
            else:
                return f"Proximal side of interface {interface_index} of {total_interfaces}"
    
    def _get_all_passing_pairs_for_requirements(self, conn_result: dict) -> list[dict]:
        """
        Get ALL passing pairs from the connection result for requirement extraction.
        
        Args:
            conn_result: Connection result dict from analysis
        
        Returns:
            List of dicts with pair info
        """
        all_pairs = []
        passes = conn_result.get("passes", [])
        
        for pass_group in passes:
            pair_reasons_list = pass_group.get("pair_reasons", [])
            
            for pair_reasons in pair_reasons_list:
                pair_key = pair_reasons.get("pair_key")
                reasons = pair_reasons.get("reasons", {})
                pass_reason_type = pair_reasons.get("pass_reason_type", "standard")
                override_note = pair_reasons.get("override_note")
                
                pair = self._find_pair_by_key(pair_key)
                
                if pair:
                    all_pairs.append({
                        "pair": pair,
                        "reasons": reasons,
                        "pair_key": pair_key,
                        "pass_reason_type": pass_reason_type,
                        "override_note": override_note
                    })
        
        return all_pairs

    def get_compat_device_summary(self, mentioned_devices: dict) -> dict:
        """
        Simplified summary focusing on what each mentioned device requires/provides.
        Handles both "compat" and "math" fit_logic types.
        
        Args:
            mentioned_devices: Same format as get_mentioned_device_requirements
        
        Returns:
            Simplified dict showing requirements per device
        """
        full_results = self.get_mentioned_device_requirements(mentioned_devices)
        
        # Consolidate by device
        device_requirements = {}
        
        for chain in full_results["successful_chains"]:
            for req in chain["mentioned_device_requirements"]:
                device_key = req["device_name"]
                
                if device_key not in device_requirements:
                    device_requirements[device_key] = {
                        "product_name": req["product_name"],
                        "device_name": req["device_name"],
                        "device_id": req["device_id"],
                        "conical_category": req["conical_category"],
                        "logic_category": req["logic_category"],
                        "fit_logic": req["fit_logic"],
                        "successful_chains_found_in": [],
                        "requirements": {},  # For compat devices
                        "specifications": {},  # For math devices
                        "working_range": {}  # For math devices
                    }
                
                # Add chain info
                chain_info = {
                    "chain_index": chain["chain_index"],
                    "device_path": " -> ".join(chain["device_path"]),
                    "position": req["position_in_chain"],
                    "connected_to": req["connected_to"]
                }
                if chain_info not in device_requirements[device_key]["successful_chains_found_in"]:
                    device_requirements[device_key]["successful_chains_found_in"].append(chain_info)
                
                # Handle compat devices
                if req["fit_logic"] == "compat":
                    for compat_req in req.get("compatibility_requirements", []):
                        field = compat_req["field"]
                        if field not in device_requirements[device_key]["requirements"]:
                            device_requirements[device_key]["requirements"][field] = {
                                "value": compat_req["value"],
                                "description": compat_req["description"]
                            }
                
                # Handle math devices
                elif req["fit_logic"] == "math":
                    # Store specifications
                    for spec_type, spec_values in req.get("specifications", {}).items():
                        if spec_type not in device_requirements[device_key]["specifications"]:
                            device_requirements[device_key]["specifications"][spec_type] = spec_values
                    
                    # Store working range
                    for range_type, range_values in req.get("working_range", {}).items():
                        if range_type not in device_requirements[device_key]["working_range"]:
                            device_requirements[device_key]["working_range"][range_type] = range_values
                    
                    # Store role info
                    if "role" in req and "role" not in device_requirements[device_key]:
                        device_requirements[device_key]["role"] = req["role"]
                        device_requirements[device_key]["role_description"] = req["role_description"]
        
        return {
            "device_requirements": device_requirements,
            "total_devices_found": len(device_requirements),
            "summary_text": self._generate_requirement_summary_text(device_requirements)
        }
    
    def _generate_requirement_summary_text(self, device_requirements: dict) -> str:
        """
        Generate a human-readable summary of requirements.
        """
        lines = []
        lines.append("=== Device Requirements for Mentioned Devices ===\n")
        
        for device_name, info in device_requirements.items():
            lines.append(f"\n{info['product_name']} - {device_name}")
            lines.append(f"  Category: {info['conical_category']} ({info['logic_category']})")
            lines.append(f"  Fit Logic: {info['fit_logic']}")
            lines.append(f"  Found in {len(info['successful_chains_found_in'])} successful chain(s)")
            
            # Handle compat devices
            if info["fit_logic"] == "compat" and info["requirements"]:
                lines.append("  Requirements (from IFU):")
                for field, req in info["requirements"].items():
                    if "catheter_req_inner-diameter" in field:
                        unit = field.split("_")[-1]
                        lines.append(f"    - Requires catheter ID ({unit}): {req['value']}")
                    elif "guide_or_catheter_or_sheath_min_inner-diameter" in field:
                        unit = field.split("_")[-1]
                        lines.append(f"    - Min guide/catheter/sheath ID ({unit}): {req['value']}")
                    elif "wire_max_outer-diameter" in field:
                        unit = field.split("_")[-1]
                        lines.append(f"    - Max compatible wire OD ({unit}): {req['value']}")
                    else:
                        lines.append(f"    - {field}: {req['value']}")
            
            # Handle math devices
            elif info["fit_logic"] == "math":
                role = info.get("role", "unknown")
                role_desc = info.get("role_description", "")
                lines.append(f"  Role: {role} - {role_desc}")
                
                if info["specifications"]:
                    lines.append("  Specifications:")
                    for spec_type, specs in info["specifications"].items():
                        if spec_type == "inner_diameter":
                            lines.append(f"    Inner Diameter (ID):")
                            for unit, value in specs.items():
                                lines.append(f"      - {unit}: {value}")
                        elif spec_type == "outer_diameter":
                            lines.append(f"    Outer Diameter (OD):")
                            for key, value in specs.items():
                                lines.append(f"      - {key}: {value}")
                
                if info["working_range"]:
                    lines.append("  Working Range:")
                    for range_type, range_info in info["working_range"].items():
                        if range_type == "accepts_outer_diameter":
                            lines.append(f"    Can Accept (max OD that fits inside):")
                            if "description_inches" in range_info:
                                lines.append(f"      - {range_info['description_inches']}")
                            if "description_mm" in range_info:
                                lines.append(f"      - {range_info['description_mm']}")
                        elif range_type == "requires_inner_diameter":
                            lines.append(f"    Requires (min ID to fit into):")
                            if "description_inches" in range_info:
                                lines.append(f"      - {range_info['description_inches']}")
                            if "description_mm" in range_info:
                                lines.append(f"      - {range_info['description_mm']}")
            
            lines.append("")
        
        return "\n".join(lines)

    def _get_all_pairs_for_requirements(self, conn_result: dict) -> list[dict]:
        """
        Get ALL pairs (passing and failing) from the connection result.
        Used when include_failing=True.
        
        Args:
            conn_result: Connection result dict from analysis
        
        Returns:
            List of dicts with pair info including status
        """
        all_pairs = []
        
        # Get passing pairs
        passes = conn_result.get("passes", [])
        for pass_group in passes:
            for pair_reasons in pass_group.get("pair_reasons", []):
                pair_key = pair_reasons.get("pair_key")
                reasons = pair_reasons.get("reasons", {})
                pass_reason_type = pair_reasons.get("pass_reason_type", "standard")
                override_note = pair_reasons.get("override_note")
                pair = self._find_pair_by_key(pair_key)
                if pair:
                    all_pairs.append({
                        "pair": pair,
                        "reasons": reasons,
                        "pair_key": pair_key,
                        "pass_reason_type": pass_reason_type,
                        "override_note": override_note,
                        "status": "pass"
                    })
        
        # Get failing pairs
        failures = conn_result.get("failures", [])
        for fail_group in failures:
            for pair_reasons in fail_group.get("pair_reasons", []):
                pair_key = pair_reasons.get("pair_key")
                reasons = pair_reasons.get("reasons", {})
                pair = self._find_pair_by_key(pair_key)
                if pair:
                    all_pairs.append({
                        "pair": pair,
                        "reasons": reasons,
                        "pair_key": pair_key,
                        "pass_reason_type": "standard",
                        "override_note": None,
                        "status": "fail"
                    })
        
        return all_pairs

    def _match_chain_pattern(self, device_path: list, chains: list, 
                             named_device_names: set, categories: list) -> dict | None:
        """Check if device_path matches one of the chain patterns."""
        for chain_pattern in chains:
            sequence = chain_pattern.get("sequence", [])
            if len(sequence) != len(device_path):
                continue
            
            match = True
            for i, pattern_item in enumerate(sequence):
                actual_device = device_path[i]
                
                # Check if pattern item is a named device or category
                if pattern_item in named_device_names:
                    # Must match exactly (by product name)
                    if actual_device != pattern_item:
                        match = False
                        break
                elif pattern_item in categories:
                    # It's a category - any device is fine (already validated by chain analysis)
                    pass
                else:
                    # Unknown pattern item
                    match = False
                    break
            
            if match:
                return chain_pattern
        
        return None
    
    def _get_named_device_constraints(self, device_name: str, pos_idx: int,
                                    all_pairs_by_interface: dict, mentioned_ids: dict,
                                    is_distal: bool, is_proximal: bool) -> dict:
        """Get constraints for a named device based on its fit_logic and position.
        
        For distal compat devices, groups requirements by value and tracks which variants
        have each requirement and what devices are compatible with each group.
        
        UPDATED: Now extracts length for all positions.
        """
        constraints = {
            "fit_logic": None,
            "requirements": {},
            "requires_catheter_id_groups": []
        }
        
        # Find this device in the pairs
        device_data = None
        
        if is_distal and 0 in all_pairs_by_interface:
            for pair_data in all_pairs_by_interface[0]:
                inner = pair_data["pair"].get("inner", {})
                if inner.get("product_name") == device_name:
                    device_data = inner
                    break
        elif is_proximal:
            last_idx = max(all_pairs_by_interface.keys()) if all_pairs_by_interface else -1
            if last_idx >= 0:
                for pair_data in all_pairs_by_interface[last_idx]:
                    outer = pair_data["pair"].get("outer", {})
                    if outer.get("product_name") == device_name:
                        device_data = outer
                        break
        else:
            if pos_idx - 1 in all_pairs_by_interface:
                for pair_data in all_pairs_by_interface[pos_idx - 1]:
                    outer = pair_data["pair"].get("outer", {})
                    if outer.get("product_name") == device_name:
                        device_data = outer
                        break
        
        if not device_data:
            return constraints
        
        fit_logic = device_data.get("fit_logic", "")
        constraints["fit_logic"] = fit_logic
        constraints["logic_category"] = device_data.get("logic_category", "")
        
        # ============================================================
        # NEW: Always extract length regardless of position/fit_logic
        # ============================================================
        length_cm = device_data.get("specification_length_cm")
        if length_cm and length_cm != '':
            constraints["requirements"]["device_length_cm"] = length_cm
        
        if is_distal:
            if fit_logic == "compat":
                req_groups = {}
                
                for pair_data in all_pairs_by_interface.get(0, []):
                    inner = pair_data["pair"].get("inner", {})
                    outer = pair_data["pair"].get("outer", {})
                    
                    if inner.get("product_name") == device_name:
                        id_req = self._get_compat_id_requirement(inner)
                        if id_req and "inches" in id_req:
                            req_key = id_req["inches"]
                            inner_device_name = inner.get("device_name", "Unknown")
                            outer_device_name = outer.get("device_name", outer.get("product_name", "Unknown"))
                            
                            if req_key not in req_groups:
                                req_groups[req_key] = {
                                    "requirement": id_req,
                                    "variants": set(),
                                    "compatible_outer_devices": set()
                                }
                            req_groups[req_key]["variants"].add(inner_device_name)
                            req_groups[req_key]["compatible_outer_devices"].add(outer_device_name)
                
                for req_key, group_data in sorted(req_groups.items()):
                    constraints["requires_catheter_id_groups"].append({
                        "requirement_key": req_key,
                        "requirement": group_data["requirement"],
                        "variants": sorted(group_data["variants"]),
                        "variant_count": len(group_data["variants"]),
                        "compatible_outer_devices": sorted(group_data["compatible_outer_devices"]),
                        "compatible_outer_count": len(group_data["compatible_outer_devices"])
                    })
                
                if req_groups:
                    first_req = list(req_groups.values())[0]["requirement"]
                    constraints["requirements"]["requires_catheter_id"] = first_req
            else:  # math or empty
                od_specs = self._extract_od_specs(device_data)
                if od_specs:
                    constraints["requirements"]["device_od"] = od_specs
        
        elif is_proximal:
            if fit_logic == "compat":
                od_req = self._get_compat_od_requirement(device_data)
                if od_req:
                    constraints["requirements"]["accepts_catheter_od"] = od_req
                else:
                    id_specs = self._extract_id_specs(device_data)
                    if id_specs:
                        constraints["requirements"]["device_id"] = id_specs
                        constraints["requirements"]["accepts_max_od"] = self._calculate_max_od_from_id(id_specs)
            else:  # math
                id_specs = self._extract_id_specs(device_data)
                if id_specs:
                    constraints["requirements"]["device_id"] = id_specs
                    constraints["requirements"]["accepts_max_od"] = self._calculate_max_od_from_id(id_specs)
        
        else:
            # Middle named device
            id_specs = self._extract_id_specs(device_data)
            od_specs = self._extract_od_specs(device_data)
            if id_specs:
                constraints["requirements"]["device_id"] = id_specs
            if od_specs:
                constraints["requirements"]["device_od"] = od_specs
        
        return constraints

    def _get_category_device_constraints(self, pos_idx: int, all_pairs_by_interface: dict,
                                          device_path: list, is_distal: bool, is_proximal: bool) -> dict:
        """
        Get the range constraints a category device must satisfy.
        
        This looks at what the adjacent devices require:
        - From the device before (distal): What ID must this device have?
        - From the device after (proximal): What OD must this device have?
        
        ALSO for distal category devices (like stents):
        - What catheter ID does this device require? (compat requirement)
        
        Groups requirements by value and tracks which devices have each requirement.
        """
        constraints = {
            "must_have_id": {},
            "must_have_od": {},
            "id_range_from_pairs": {},
            "od_range_from_pairs": {},
            "requires_catheter_id_groups": [],  # Grouped by requirement value
            "must_have_id_groups": [],  # For middle devices - grouped by distal requirement
            "compatible_devices_by_group": {}  # Track which outer devices work with each group
        }
        
        # For DISTAL category devices (like stents), extract and GROUP their compat requirements
        if is_distal and pos_idx in all_pairs_by_interface:
            # Group by requirement value
            req_groups = {}  # key: "0.017-0.021" -> {devices: set(), outer_devices: set()}
            
            for pair_data in all_pairs_by_interface[pos_idx]:
                inner = pair_data["pair"].get("inner", {})
                outer = pair_data["pair"].get("outer", {})
                inner_fit_logic = inner.get("fit_logic", "")
                
                if inner_fit_logic == "compat":
                    id_req = self._get_compat_id_requirement(inner)
                    if id_req and "inches" in id_req:
                        req_key = id_req["inches"]  # e.g., "0.017-0.021"
                        inner_name = inner.get("device_name", inner.get("product_name", "Unknown"))
                        outer_name = outer.get("device_name", outer.get("product_name", "Unknown"))
                        
                        if req_key not in req_groups:
                            req_groups[req_key] = {
                                "requirement": id_req,
                                "devices": set(),
                                "compatible_outer_devices": set()
                            }
                        req_groups[req_key]["devices"].add(inner_name)
                        req_groups[req_key]["compatible_outer_devices"].add(outer_name)
            
            # Convert to list format
            for req_key, group_data in sorted(req_groups.items()):
                constraints["requires_catheter_id_groups"].append({
                    "requirement_key": req_key,
                    "requirement": group_data["requirement"],
                    "devices": sorted(group_data["devices"]),
                    "device_count": len(group_data["devices"]),
                    "compatible_outer_devices": sorted(group_data["compatible_outer_devices"]),
                    "compatible_outer_count": len(group_data["compatible_outer_devices"])
                })
        
        # Collect ID requirements for MIDDLE devices (what the distal device requires)
        # Group by the distal device's requirement
        if pos_idx > 0 and (pos_idx - 1) in all_pairs_by_interface:
            req_groups = {}
            
            for pair_data in all_pairs_by_interface[pos_idx - 1]:
                inner = pair_data["pair"].get("inner", {})
                outer = pair_data["pair"].get("outer", {})
                inner_fit_logic = inner.get("fit_logic", "")
                
                if inner_fit_logic == "compat":
                    id_req = self._get_compat_id_requirement(inner)
                    if id_req and "inches" in id_req:
                        req_key = id_req["inches"]
                        inner_name = inner.get("device_name", inner.get("product_name", "Unknown"))
                        outer_name = outer.get("device_name", outer.get("product_name", "Unknown"))
                        
                        if req_key not in req_groups:
                            req_groups[req_key] = {
                                "requirement": id_req,
                                "distal_devices": set(),
                                "compatible_middle_devices": set()
                            }
                        req_groups[req_key]["distal_devices"].add(inner_name)
                        req_groups[req_key]["compatible_middle_devices"].add(outer_name)
            
            for req_key, group_data in sorted(req_groups.items()):
                constraints["must_have_id_groups"].append({
                    "requirement_key": req_key,
                    "requirement": group_data["requirement"],
                    "distal_devices": sorted(group_data["distal_devices"]),
                    "distal_device_count": len(group_data["distal_devices"]),
                    "compatible_middle_devices": sorted(group_data["compatible_middle_devices"]),
                    "compatible_middle_count": len(group_data["compatible_middle_devices"])
                })
        
        # Also collect actual ID values from the pairs (what actually worked)
        if pos_idx - 1 in all_pairs_by_interface:
            id_values = []
            for pair_data in all_pairs_by_interface[pos_idx - 1]:
                outer = pair_data["pair"].get("outer", {})
                id_specs = self._extract_id_specs(outer)
                if id_specs:
                    id_values.append(id_specs)
            
            if id_values:
                constraints["id_range_from_pairs"] = self._consolidate_spec_range(id_values, "id")
        
        # Collect OD requirements (what this device's OD must be to fit into the next device)
        # This comes from the proximal (outer) device
        if pos_idx < len(device_path) - 1 and pos_idx in all_pairs_by_interface:
            for pair_data in all_pairs_by_interface[pos_idx]:
                outer = pair_data["pair"].get("outer", {})
                outer_fit_logic = outer.get("fit_logic", "")
                
                if outer_fit_logic == "compat":
                    od_req = self._get_compat_od_requirement(outer)
                    if od_req:
                        constraints["must_have_od"]["from_proximal_compat"] = od_req
                        constraints["must_have_od"]["reason"] = f"Must satisfy {outer.get('product_name', 'proximal device')} compat requirement"
                else:  # math
                    id_specs = self._extract_id_specs(outer)
                    if id_specs:
                        max_od = self._calculate_max_od_from_id(id_specs)
                        constraints["must_have_od"]["max_od_to_fit"] = max_od
                        constraints["must_have_od"]["reason"] = f"Must fit into {outer.get('product_name', 'proximal device')} (ID: {id_specs})"
        
        # Also collect actual OD values from the pairs
        if pos_idx - 1 in all_pairs_by_interface:
            od_values = []
            for pair_data in all_pairs_by_interface[pos_idx - 1]:
                outer = pair_data["pair"].get("outer", {})
                od_specs = self._extract_od_specs(outer)
                if od_specs:
                    od_values.append(od_specs)
            
            if od_values:
                constraints["od_range_from_pairs"] = self._consolidate_spec_range(od_values, "od")
        
        return constraints
    
    def _consolidate_spec_range(self, spec_values: list, spec_type: str) -> dict:
        """Consolidate a list of spec values into min/max range."""
        if not spec_values:
            return {}
        
        result = {}
        
        if spec_type == "id":
            inches_vals = [float(s["inches"]) for s in spec_values if s.get("inches")]
            mm_vals = [float(s["mm"]) for s in spec_values if s.get("mm")]
            
            if inches_vals:
                result["min_inches"] = min(inches_vals)
                result["max_inches"] = max(inches_vals)
            if mm_vals:
                result["min_mm"] = min(mm_vals)
                result["max_mm"] = max(mm_vals)
        else:  # od - use proximal (larger) values
            prox_in = [float(s["proximal_inches"]) for s in spec_values if s.get("proximal_inches")]
            prox_mm = [float(s["proximal_mm"]) for s in spec_values if s.get("proximal_mm")]
            
            if prox_in:
                result["min_proximal_inches"] = min(prox_in)
                result["max_proximal_inches"] = max(prox_in)
            if prox_mm:
                result["min_proximal_mm"] = min(prox_mm)
                result["max_proximal_mm"] = max(prox_mm)
        
        return result
    
    def _consolidate_compat_id_requirements(self, compat_id_reqs: list) -> dict:
        """Consolidate multiple compat ID requirements into min/max range."""
        result = {}
        
        inches_mins = []
        inches_maxs = []
        mm_mins = []
        mm_maxs = []
        french_mins = []
        french_maxs = []
        
        for req in compat_id_reqs:
            for unit, values in req.items():
                if isinstance(values, str) and "-" in values:
                    parts = values.split("-")
                    min_val = float(parts[0])
                    max_val = float(parts[1])
                else:
                    min_val = max_val = float(values)
                
                if unit == "inches":
                    inches_mins.append(min_val)
                    inches_maxs.append(max_val)
                elif unit == "mm":
                    mm_mins.append(min_val)
                    mm_maxs.append(max_val)
                elif unit == "French":
                    french_mins.append(min_val)
                    french_maxs.append(max_val)
        
        if inches_mins:
            result["min_inches"] = min(inches_mins)
            result["max_inches"] = max(inches_maxs)
        if mm_mins:
            result["min_mm"] = min(mm_mins)
            result["max_mm"] = max(mm_maxs)
        if french_mins:
            result["min_French"] = min(french_mins)
            result["max_French"] = max(french_maxs)
        
        return result

    def _generate_chain_requirement_text(self, chain_summaries: list, include_status: bool = False) -> list:
        """Generate human-readable text summaries for LLM consumption - consolidated by pattern.
        
        UPDATED: Now shows length for all devices and failure reasons for failing chains.
        Status is determined by whether ANY variant passes (not just the first chain).
        """
        
        # Group chains by their pattern (sequence)
        pattern_groups = {}
        for chain in chain_summaries:
            pattern = chain.get("pattern", {})
            sequence = tuple(pattern.get("sequence", []))
            
            if sequence not in pattern_groups:
                pattern_groups[sequence] = {
                    "pattern": pattern,
                    "chains": []
                }
            pattern_groups[sequence]["chains"].append(chain)
        
        texts = []
        
        for sequence, group in pattern_groups.items():
            pattern = group["pattern"]
            chains = group["chains"]
            
            lines = []
            
            # Build header with category markers
            path_display = []
            named_devices = set()
            for item in sequence:
                is_named = False
                for chain in chains:
                    for pos in chain.get("positions", []):
                        if pos["device_name"] == item and pos["is_named_device"]:
                            is_named = True
                            named_devices.add(item)
                            break
                    if is_named:
                        break
                
                if item in named_devices:
                    path_display.append(item)
                else:
                    path_display.append(f"[{item}]")
            
            # ADD STATUS INDICATOR if include_status is True
            if include_status:
                # If ANY chain in this group passes, the group passes
                has_passing = any(c.get("status") == "pass" for c in chains)
                chain_status = "pass" if has_passing else "fail"
                status_icon = "✅" if chain_status == "pass" else "❌"
                status_text = "Compatible" if chain_status == "pass" else "Not Compatible"
                lines.append(f"{status_icon} Chain: {' -> '.join(path_display)}")
                lines.append(f"Status: {status_text}")
            else:
                lines.append(f"Chain: {' -> '.join(path_display)}")
            
            lines.append("")
            
            # Consolidate data across all chains for this pattern
            consolidated_positions = self._consolidate_positions(chains, sequence)
            
            for pos_idx, pos_data in enumerate(consolidated_positions):
                device_name = pos_data["device_name"]
                is_named = pos_data["is_named_device"]
                is_distal = pos_data["is_distal"]
                is_proximal = pos_data["is_proximal"]
                
                if is_distal:
                    position_label = "DISTAL"
                elif is_proximal:
                    position_label = "PROXIMAL"
                else:
                    total_positions = len(consolidated_positions)
                    position_label = f"MIDDLE (position {pos_idx + 1} of {total_positions})"
                
                if is_named:
                    fit_logic = pos_data.get("fit_logic", "unknown")
                    lines.append(f"{device_name} ({position_label}, fit_logic={fit_logic}):")
                    
                    # Check for grouped requirements first (for distal compat devices)
                    req_groups = pos_data.get("requires_catheter_id_groups", [])
                    if req_groups:
                        for group_item in req_groups:
                            req_key = group_item.get("requirement_key", "")
                            variant_count = group_item.get("variant_count", 0)
                            variants = group_item.get("variants", [])
                            compat_count = group_item.get("compatible_outer_count", 0)
                            
                            if variant_count <= 5:
                                variant_str = ", ".join(self._shorten_device_names(variants))
                                lines.append(f"  - Requires catheter ID {req_key} inches ({variant_str}): {compat_count} compatible")
                            else:
                                lines.append(f"  - Requires catheter ID {req_key} inches ({variant_count} variants): {compat_count} compatible")
                    else:
                        reqs = pos_data.get("requirements", {})
                        if "requires_catheter_id" in reqs:
                            id_req = reqs["requires_catheter_id"]
                            val = self._get_preferred_unit_value(id_req, ["inches", "mm", "French"])
                            if val:
                                lines.append(f"  - Requires catheter with ID: {val}")
                    
                    reqs = pos_data.get("requirements", {})
                    if "device_id" in reqs:
                        id_spec = reqs["device_id"]
                        max_od = reqs.get("accepts_max_od", {})
                        id_val = self._get_preferred_unit_value(id_spec, ["inches", "mm"])
                        od_val = self._get_preferred_unit_value_from_max(max_od)
                        if id_val and od_val:
                            lines.append(f"  - Has ID of: {id_val} (accepts OD up to ~{od_val})")
                        elif id_val:
                            lines.append(f"  - Has ID of: {id_val}")
                    
                    if "device_od" in reqs:
                        od_spec = reqs["device_od"]
                        od_val = self._get_preferred_unit_value_od(od_spec)
                        if od_val:
                            lines.append(f"  - Has OD (proximal): {od_val}")
                    
                    # Show length
                    if "device_length_cm" in reqs:
                        lines.append(f"  - Has length: {reqs['device_length_cm']} cm")
                
                else:
                    # Category device - show grouped requirements
                    lines.append(f"{device_name} ({position_label}) requirements:")
                    
                    if is_distal:
                        req_groups = pos_data.get("requires_catheter_id_groups", [])
                        if req_groups:
                            for group_item in req_groups:
                                req_key = group_item.get("requirement_key", "")
                                device_count = group_item.get("device_count", 0)
                                compat_count = group_item.get("compatible_outer_count", 0)
                                lines.append(f"  - Requires catheter ID {req_key} inches ({device_count} variants): {compat_count} compatible")
                        elif pos_data.get("requires_catheter_id_range"):
                            id_range = pos_data["requires_catheter_id_range"]
                            val = self._format_range(id_range, "id")
                            if val:
                                lines.append(f"  - Requires catheter ID: {val}")
                    
                    if not is_distal:
                        must_have_groups = pos_data.get("must_have_id_groups", [])
                        if must_have_groups:
                            for group_item in must_have_groups:
                                req_key = group_item.get("requirement_key", "")
                                distal_count = group_item.get("distal_device_count", 0)
                                compat_count = group_item.get("compatible_middle_count", 0)
                                lines.append(f"  - For devices needing ID {req_key}\": {compat_count} compatible")
                        elif pos_data.get("must_have_id_range"):
                            id_range = pos_data["must_have_id_range"]
                            val = self._format_range(id_range, "id")
                            if val:
                                lines.append(f"  - Must have ID: {val}")
                        
                        if pos_data.get("actual_id_range"):
                            id_range = pos_data["actual_id_range"]
                            val = self._format_range(id_range, "id")
                            if val:
                                lines.append(f"  - Actual ID range: {val}")
                    
                    if not is_distal:
                        if pos_data.get("must_have_od_max"):
                            od_max = pos_data["must_have_od_max"]
                            val = self._get_preferred_unit_value_from_max(od_max)
                            if val:
                                lines.append(f"  - Must have OD up to: {val}")
                        
                        if pos_data.get("actual_od_range"):
                            od_range = pos_data["actual_od_range"]
                            val = self._format_range(od_range, "od")
                            if val:
                                lines.append(f"  - Actual OD range: {val}")
                
                lines.append("")
            
            # For failing chains, show WHY it failed
            if include_status:
                has_passing = any(c.get("status") == "pass" for c in chains)
                chain_status = "pass" if has_passing else "fail"
                if chain_status == "fail":
                    failure_reasons = self._extract_failure_reasons_for_text(chains)
                    if failure_reasons:
                        lines.append("Failure reason(s):")
                        for reason in failure_reasons:
                            lines.append(f"  ⚠ {reason}")
                        lines.append("")
            
            texts.append("\n".join(lines))
        
        return texts

    def _extract_failure_reasons_for_text(self, chains: list) -> list:
        """
        Extract human-readable failure reasons from failing chains.
        
        Looks at the actual pair data to find what failed and why.
        Returns a list of reason strings.
        """
        reasons = []
        seen = set()
        
        for chain in chains:
            chain_index = chain.get("chain_index")
            
            # Find the matching chain in processed_results
            for proc_chain in self.processed_results:
                if proc_chain.get("chain_index") != chain_index:
                    continue
                
                for path in proc_chain.get("paths", []):
                    for connection in path.get("connections", []):
                        for pair in connection.get("processed_pairs", []):
                            overall = pair.get("overall_status", {})
                            status = overall.get("status", "")
                            
                            if status == "fail" or "fail" in str(overall.get("logic_type", "")):
                                inner = pair.get("inner", {})
                                outer = pair.get("outer", {})
                                inner_name = inner.get("device_name", pair.get("inner_name", "?"))
                                outer_name = outer.get("device_name", pair.get("outer_name", "?"))
                                
                                geo = overall.get("geometry_status", {})
                                compat = overall.get("compatibility_status", {})
                                length_stat = geo.get("length_status", {})
                                diameter_stat = geo.get("diameter_status", {})
                                
                                # Check length failure
                                if length_stat.get("status") == "fail":
                                    for row in length_stat.get("supporting_rows", []):
                                        if row.get("status") == "fail":
                                            inner_len = row.get("inner_device_specification_value", "?")
                                            outer_len = row.get("outer_device_specification_value", "?")
                                            
                                            reason_key = f"length_{inner_name}_{outer_name}"
                                            if reason_key not in seen:
                                                seen.add(reason_key)
                                                
                                                if inner_len != "?" and outer_len != "?" and inner_len != "" and outer_len != "":
                                                    try:
                                                        diff = float(outer_len) - float(inner_len)
                                                        reasons.append(
                                                            f"{inner_name} length ({inner_len} cm) is shorter than "
                                                            f"{outer_name} length ({outer_len} cm) — "
                                                            f"the inner device must be at least as long as the outer device "
                                                            f"(needs {diff:.0f} cm more)"
                                                        )
                                                    except (ValueError, TypeError):
                                                        reasons.append(
                                                            f"{inner_name} is too short to pass through {outer_name}"
                                                        )
                                                else:
                                                    reasons.append(
                                                        f"{inner_name} is too short to pass through {outer_name}"
                                                    )
                                            break
                                
                                # Check diameter failure  
                                if diameter_stat.get("status") == "fail":
                                    for row in diameter_stat.get("supporting_rows", []):
                                        if row.get("status") == "fail":
                                            reason_key = f"diameter_{inner_name}_{outer_name}"
                                            if reason_key not in seen:
                                                seen.add(reason_key)
                                                
                                                inner_val = row.get("inner_device_specification_value", "?")
                                                outer_val = row.get("outer_device_specification_value", "?")
                                                inner_field = row.get("inner_device_specification_field", "")
                                                outer_field = row.get("outer_device_specification_field", "")
                                                
                                                reasons.append(
                                                    f"{inner_name} OD ({inner_val}) does not fit inside "
                                                    f"{outer_name} ID ({outer_val})"
                                                )
                                            break
                                
                                # Check compat failure (if no geometry failure found)
                                if not reasons or (length_stat.get("status") != "fail" and diameter_stat.get("status") != "fail"):
                                    if compat.get("status") == "fail":
                                        for row in compat.get("supporting_rows", []):
                                            if row.get("status") == "fail":
                                                reason_key = f"compat_{inner_name}_{outer_name}"
                                                if reason_key not in seen:
                                                    seen.add(reason_key)
                                                    note = row.get("note", "Compatibility check failed")
                                                    reasons.append(note)
                                                break
        
        return reasons

    def _shorten_device_names(self, names: list) -> list:
        """Shorten device names for display (e.g., 'Solitaire X Retriever 3 x 20 mm' -> '3x20')."""
        shortened = []
        for name in names:
            # Try to extract size from name
            import re
            match = re.search(r'(\d+)\s*x\s*(\d+)', name)
            if match:
                shortened.append(f"{match.group(1)}x{match.group(2)}")
            else:
                # Just take last part of name
                parts = name.split()
                if len(parts) > 2:
                    shortened.append(" ".join(parts[-2:]))
                else:
                    shortened.append(name)
        return shortened
    
    def _consolidate_positions(self, chains: list, sequence: tuple) -> list:
        """Consolidate position data across multiple chains for the same pattern.
        
        For named devices with grouped requirements, merges groups from all chains.
        """
        consolidated = []
        
        for pos_idx, device_name in enumerate(sequence):
            is_distal = (pos_idx == 0)
            is_proximal = (pos_idx == len(sequence) - 1)
            
            # Collect data from all chains for this position
            all_constraints = []
            is_named = None
            fit_logic = None
            
            for chain in chains:
                for pos in chain.get("positions", []):
                    if pos["position_index"] == pos_idx:
                        all_constraints.append(pos.get("constraints", {}))
                        if is_named is None:
                            is_named = pos["is_named_device"]
                        if fit_logic is None:
                            fit_logic = pos.get("constraints", {}).get("fit_logic")
            
            pos_data = {
                "device_name": device_name,
                "is_named_device": is_named or False,
                "is_distal": is_distal,
                "is_proximal": is_proximal,
                "fit_logic": fit_logic
            }
            
            if is_named:
                # For named devices, merge grouped requirements from all chains
                if all_constraints:
                    pos_data["requirements"] = all_constraints[0].get("requirements", {})
                    
                    # Merge requires_catheter_id_groups from all constraints
                    req_groups_merged = {}
                    for constraints in all_constraints:
                        for group in constraints.get("requires_catheter_id_groups", []):
                            req_key = group.get("requirement_key", "")
                            if req_key not in req_groups_merged:
                                req_groups_merged[req_key] = {
                                    "requirement_key": req_key,
                                    "requirement": group.get("requirement", {}),
                                    "variants": set(),
                                    "compatible_outer_devices": set()
                                }
                            req_groups_merged[req_key]["variants"].update(group.get("variants", []))
                            req_groups_merged[req_key]["compatible_outer_devices"].update(
                                group.get("compatible_outer_devices", [])
                            )
                    
                    # Convert to list format
                    pos_data["requires_catheter_id_groups"] = []
                    for req_key, group_data in sorted(req_groups_merged.items()):
                        pos_data["requires_catheter_id_groups"].append({
                            "requirement_key": req_key,
                            "requirement": group_data["requirement"],
                            "variants": sorted(group_data["variants"]),
                            "variant_count": len(group_data["variants"]),
                            "compatible_outer_devices": sorted(group_data["compatible_outer_devices"]),
                            "compatible_outer_count": len(group_data["compatible_outer_devices"])
                        })
            else:
                # For category devices, consolidate ranges
                pos_data.update(self._consolidate_category_constraints(all_constraints))
            
            consolidated.append(pos_data)
        
        return consolidated
    
    def _consolidate_category_constraints(self, all_constraints: list) -> dict:
        """Consolidate constraints for a category device across multiple chains.
        
        Now handles grouped requirements - merges groups from all chains.
        """
        result = {
            "must_have_id_range": {},
            "actual_id_range": {},
            "must_have_od_max": {},
            "actual_od_range": {},
            "requires_catheter_id_range": {},  # Legacy - consolidated range
            "requires_catheter_id_groups": [],  # NEW - grouped by requirement value
            "must_have_id_groups": []  # NEW - for middle devices
        }
        
        # Merge grouped data from all constraints
        req_groups_merged = {}  # For distal devices
        must_have_groups_merged = {}  # For middle devices
        
        # Collect all values (legacy)
        id_req_values = {"inches": [], "mm": [], "French": []}
        actual_id_values = {"inches": [], "mm": []}
        od_max_values = {"inches": [], "mm": []}
        actual_od_values = {"inches": [], "mm": []}
        
        for constraints in all_constraints:
            # NEW: Merge requires_catheter_id_groups
            for group in constraints.get("requires_catheter_id_groups", []):
                req_key = group.get("requirement_key", "")
                if req_key not in req_groups_merged:
                    req_groups_merged[req_key] = {
                        "requirement_key": req_key,
                        "requirement": group.get("requirement", {}),
                        "devices": set(),
                        "compatible_outer_devices": set()
                    }
                req_groups_merged[req_key]["devices"].update(group.get("devices", []))
                req_groups_merged[req_key]["compatible_outer_devices"].update(
                    group.get("compatible_outer_devices", [])
                )
            
            # NEW: Merge must_have_id_groups
            for group in constraints.get("must_have_id_groups", []):
                req_key = group.get("requirement_key", "")
                if req_key not in must_have_groups_merged:
                    must_have_groups_merged[req_key] = {
                        "requirement_key": req_key,
                        "requirement": group.get("requirement", {}),
                        "distal_devices": set(),
                        "compatible_middle_devices": set()
                    }
                must_have_groups_merged[req_key]["distal_devices"].update(
                    group.get("distal_devices", [])
                )
                must_have_groups_merged[req_key]["compatible_middle_devices"].update(
                    group.get("compatible_middle_devices", [])
                )
            
            # Legacy: ID requirements from distal compat
            if constraints.get("must_have_id"):
                id_info = constraints["must_have_id"]
                if "from_distal_compat" in id_info:
                    req = id_info["from_distal_compat"]
                    for unit in ["inches", "mm", "French"]:
                        if unit in req:
                            id_req_values[unit].append(req[unit])
            
            # Actual ID values
            if constraints.get("id_range_from_pairs"):
                id_range = constraints["id_range_from_pairs"]
                if "min_inches" in id_range:
                    actual_id_values["inches"].append(id_range["min_inches"])
                if "max_inches" in id_range:
                    actual_id_values["inches"].append(id_range["max_inches"])
                if "min_mm" in id_range:
                    actual_id_values["mm"].append(id_range["min_mm"])
                if "max_mm" in id_range:
                    actual_id_values["mm"].append(id_range["max_mm"])
            
            # OD max from proximal
            if constraints.get("must_have_od"):
                od_info = constraints["must_have_od"]
                if "max_od_to_fit" in od_info:
                    max_od = od_info["max_od_to_fit"]
                    if "max_inches" in max_od:
                        od_max_values["inches"].append(max_od["max_inches"])
                    if "max_mm" in max_od:
                        od_max_values["mm"].append(max_od["max_mm"])
            
            # Actual OD values
            if constraints.get("od_range_from_pairs"):
                od_range = constraints["od_range_from_pairs"]
                if "min_proximal_inches" in od_range:
                    actual_od_values["inches"].append(od_range["min_proximal_inches"])
                if "max_proximal_inches" in od_range:
                    actual_od_values["inches"].append(od_range["max_proximal_inches"])
                if "min_proximal_mm" in od_range:
                    actual_od_values["mm"].append(od_range["min_proximal_mm"])
                if "max_proximal_mm" in od_range:
                    actual_od_values["mm"].append(od_range["max_proximal_mm"])
        
        # Convert merged groups to list format
        for req_key, group_data in sorted(req_groups_merged.items()):
            result["requires_catheter_id_groups"].append({
                "requirement_key": req_key,
                "requirement": group_data["requirement"],
                "devices": sorted(group_data["devices"]),
                "device_count": len(group_data["devices"]),
                "compatible_outer_devices": sorted(group_data["compatible_outer_devices"]),
                "compatible_outer_count": len(group_data["compatible_outer_devices"])
            })
        
        for req_key, group_data in sorted(must_have_groups_merged.items()):
            result["must_have_id_groups"].append({
                "requirement_key": req_key,
                "requirement": group_data["requirement"],
                "distal_devices": sorted(group_data["distal_devices"]),
                "distal_device_count": len(group_data["distal_devices"]),
                "compatible_middle_devices": sorted(group_data["compatible_middle_devices"]),
                "compatible_middle_count": len(group_data["compatible_middle_devices"])
            })
        
        # Legacy: Build consolidated ranges
        for unit in ["inches", "mm", "French"]:
            if id_req_values[unit]:
                all_mins = []
                all_maxs = []
                for val in id_req_values[unit]:
                    if isinstance(val, str) and "-" in val:
                        parts = val.split("-")
                        all_mins.append(float(parts[0]))
                        all_maxs.append(float(parts[1]))
                    else:
                        all_mins.append(float(val))
                        all_maxs.append(float(val))
                if all_mins:
                    result["must_have_id_range"][f"min_{unit}"] = min(all_mins)
                    result["must_have_id_range"][f"max_{unit}"] = max(all_maxs)
        
        # Actual ID range
        for unit in ["inches", "mm"]:
            if actual_id_values[unit]:
                result["actual_id_range"][f"min_{unit}"] = min(actual_id_values[unit])
                result["actual_id_range"][f"max_{unit}"] = max(actual_id_values[unit])
        
        # OD max (should be same across all, just take first)
        for unit in ["inches", "mm"]:
            if od_max_values[unit]:
                result["must_have_od_max"][f"max_{unit}"] = od_max_values[unit][0]
        
        # Actual OD range
        for unit in ["inches", "mm"]:
            if actual_od_values[unit]:
                result["actual_od_range"][f"min_{unit}"] = min(actual_od_values[unit])
                result["actual_od_range"][f"max_{unit}"] = max(actual_od_values[unit])
        
        return result
    
    def _get_preferred_unit_value(self, data: dict, unit_order: list) -> str | None:
        """Get value in preferred unit order: inches > mm > French."""
        for unit in unit_order:
            if unit in data and data[unit]:
                return f"{data[unit]} {unit}"
        return None
    
    def _get_preferred_unit_value_from_max(self, data: dict) -> str | None:
        """Get max value in preferred unit order."""
        if "max_inches" in data:
            return f"{data['max_inches']} inches"
        if "max_mm" in data:
            return f"{data['max_mm']} mm"
        return None
    
    def _get_preferred_unit_value_od(self, data: dict) -> str | None:
        """Get OD value in preferred unit order."""
        if data.get("proximal_inches"):
            return f"{data['proximal_inches']} inches"
        if data.get("proximal_mm"):
            return f"{data['proximal_mm']} mm"
        return None
    
    def _format_range(self, range_data: dict, range_type: str) -> str | None:
        """Format a range with preferred unit."""
        if range_type == "id":
            if "min_inches" in range_data and "max_inches" in range_data:
                if range_data["min_inches"] == range_data["max_inches"]:
                    return f"{range_data['min_inches']} inches"
                return f"{range_data['min_inches']}-{range_data['max_inches']} inches"
            if "min_mm" in range_data and "max_mm" in range_data:
                if range_data["min_mm"] == range_data["max_mm"]:
                    return f"{range_data['min_mm']} mm"
                return f"{range_data['min_mm']}-{range_data['max_mm']} mm"
            if "min_French" in range_data and "max_French" in range_data:
                if range_data["min_French"] == range_data["max_French"]:
                    return f"{range_data['min_French']} French"
                return f"{range_data['min_French']}-{range_data['max_French']} French"
        else:  # od
            if "min_inches" in range_data and "max_inches" in range_data:
                if range_data["min_inches"] == range_data["max_inches"]:
                    return f"{range_data['min_inches']} inches"
                return f"{range_data['min_inches']}-{range_data['max_inches']} inches"
            if "min_mm" in range_data and "max_mm" in range_data:
                if range_data["min_mm"] == range_data["max_mm"]:
                    return f"{range_data['min_mm']} mm"
                return f"{range_data['min_mm']}-{range_data['max_mm']} mm"
        return None

    def get_chain_constraints_for_llm(self, mentioned_devices: dict) -> dict:
        """
        Generate LLM-friendly constraint summaries for successful chains.
        
        For each successful chain, describes:
        - What the innermost (distal) named device requires
        - What range of specs the middle devices need to satisfy
        - What the outermost (proximal) named device accepts/requires
        
        Args:
            mentioned_devices: Dict with device info:
                {
                    "mentioned_devices": {
                        "AXS Vecta 46": {"ids": ["56"], "conical_category": "L2"},
                        "Solitaire": {"ids": ["192", ...], "conical_category": "L4"}
                    }
                }
        
        Returns:
            Dict with chain constraints organized for LLM consumption
        """
        # Extract the inner dict if nested
        if "mentioned_devices" in mentioned_devices:
            devices_dict = mentioned_devices["mentioned_devices"]
        else:
            devices_dict = mentioned_devices
        
        # Build lookup for mentioned device IDs and categories
        mentioned_ids = {}
        mentioned_categories = {}
        for product_name, info in devices_dict.items():
            category = info.get("conical_category", "Unknown")
            mentioned_categories[category] = product_name
            for device_id in info.get("ids", []):
                mentioned_ids[str(device_id)] = {
                    "product_name": product_name,
                    "conical_category": category
                }
        
        results = {
            "chain_constraints": [],
            "summary_for_llm": []
        }
        
        # Process each successful chain
        for chain in self.analysis_results:
            if chain.get("status") != "pass":
                continue
            
            for path in chain.get("path_results", []):
                if path.get("status") != "pass":
                    continue
                
                device_path = path.get("device_path", [])
                connection_results = path.get("connection_results", [])
                
                # Identify which devices are mentioned vs category-based
                chain_constraint = {
                    "chain_index": chain.get("chain_index"),
                    "device_path": device_path,
                    "distal_device": None,  # Innermost (first in path)
                    "proximal_device": None,  # Outermost (last in path)
                    "middle_devices": [],  # Everything in between
                    "constraints": {}
                }
                
                # Get all passing pairs to analyze
                all_pairs_by_interface = {}
                for idx, conn_result in enumerate(connection_results):
                    pairs = self._get_all_passing_pairs_for_requirements(conn_result)
                    all_pairs_by_interface[idx] = pairs
                
                if not all_pairs_by_interface or not all_pairs_by_interface.get(0):
                    continue
                
                # Analyze the DISTAL (innermost) device - first device in path
                first_pairs = all_pairs_by_interface.get(0, [])
                if first_pairs:
                    first_pair = first_pairs[0]["pair"]
                    inner_device = first_pair.get("inner", {})
                    distal_info = self._get_device_constraint_info(
                        device=inner_device,
                        position="distal",
                        mentioned_ids=mentioned_ids
                    )
                    chain_constraint["distal_device"] = distal_info
                
                # Analyze the PROXIMAL (outermost) device - last device in path
                last_interface_idx = len(connection_results) - 1
                last_pairs = all_pairs_by_interface.get(last_interface_idx, [])
                if last_pairs:
                    last_pair = last_pairs[0]["pair"]
                    outer_device = last_pair.get("outer", {})
                    proximal_info = self._get_device_constraint_info(
                        device=outer_device,
                        position="proximal",
                        mentioned_ids=mentioned_ids
                    )
                    chain_constraint["proximal_device"] = proximal_info
                
                # Analyze MIDDLE devices - collect the range of specs that worked
                if len(device_path) > 2:
                    middle_device_names = device_path[1:-1]
                    middle_specs = self._collect_middle_device_specs(
                        all_pairs_by_interface, 
                        connection_results,
                        mentioned_ids
                    )
                    chain_constraint["middle_devices"] = middle_specs
                
                # Build the constraint summary
                chain_constraint["constraints"] = self._build_constraint_summary(chain_constraint)
                
                results["chain_constraints"].append(chain_constraint)
        
        # Generate LLM-friendly text summaries
        results["summary_for_llm"] = self._generate_llm_summaries(results["chain_constraints"])
        
        return results
    
    def _get_device_constraint_info(self, device: dict, position: str, mentioned_ids: dict) -> dict:
        """
        Extract constraint info for a device based on its fit_logic and position.
        
        Args:
            device: Device dict
            position: "distal" (innermost) or "proximal" (outermost)
            mentioned_ids: Lookup dict for mentioned device IDs
        
        Returns:
            Dict with device constraint info
        """
        device_id = str(device.get("id", ""))
        fit_logic = device.get("fit_logic", "")
        is_mentioned = device_id in mentioned_ids
        
        info = {
            "product_name": device.get("product_name", "Unknown"),
            "device_name": device.get("device_name", "Unknown"),
            "device_id": device.get("id"),
            "conical_category": device.get("conical_category", "Unknown"),
            "logic_category": device.get("logic_category", "Unknown"),
            "fit_logic": fit_logic,
            "position": position,
            "is_mentioned": is_mentioned,
            "constraints": {}
        }
        
        if position == "distal":
            # Innermost device - we care about what ID it needs from the next device
            if fit_logic == "compat":
                # Get the required catheter ID from compatibility fields
                id_req = self._get_compat_id_requirement(device)
                if id_req:
                    info["constraints"]["requires_catheter_id"] = id_req
            else:  # fit_logic == "math"
                # Get its OD so we know what ID it needs to fit into
                od_specs = self._extract_od_specs(device)
                if od_specs:
                    info["constraints"]["device_od"] = od_specs
                    # Calculate min ID needed
                    info["constraints"]["requires_min_id"] = self._calculate_min_id_from_od(od_specs)
        
        else:  # position == "proximal"
            # Outermost device - we care about what OD can fit into it
            if fit_logic == "compat":
                # Check for OD compatibility requirement first
                od_req = self._get_compat_od_requirement(device)
                if od_req:
                    info["constraints"]["accepts_catheter_od"] = od_req
                else:
                    # Fall back to ID specification
                    id_specs = self._extract_id_specs(device)
                    if id_specs:
                        info["constraints"]["device_id"] = id_specs
                        info["constraints"]["accepts_max_od"] = self._calculate_max_od_from_id(id_specs)
            else:  # fit_logic == "math"
                # Get its ID so we know what max OD can fit inside
                id_specs = self._extract_id_specs(device)
                if id_specs:
                    info["constraints"]["device_id"] = id_specs
                    info["constraints"]["accepts_max_od"] = self._calculate_max_od_from_id(id_specs)
        
        return info
    
    def _get_compat_id_requirement(self, device: dict) -> dict | None:
        """Extract catheter ID requirement from compatibility fields."""
        result = {}
        
        fields = [
            ("compatibility_catheter_req_inner-diameter_in", "inches"),
            ("compatibility_catheter_req_inner-diameter_mm", "mm"),
            ("compatibility_catheter_req_inner-diameter_F", "French"),
        ]
        
        for field, unit in fields:
            value = device.get(field)
            if value and value != "":
                result[unit] = value
        
        return result if result else None
    
    def _get_compat_od_requirement(self, device: dict) -> dict | None:
        """Extract OD requirement/acceptance from compatibility fields."""
        result = {}
        
        fields = [
            ("compatibility_catheter_max_outer-diameter_in", "max_inches"),
            ("compatibility_catheter_max_outer-diameter_mm", "max_mm"),
            ("compatibility_catheter_max_outer-diameter_F", "max_French"),
        ]
        
        for field, unit in fields:
            value = device.get(field)
            if value and value != "":
                result[unit] = value
        
        return result if result else None
    
    def _calculate_min_id_from_od(self, od_specs: dict) -> dict:
        """Calculate minimum ID needed based on device OD."""
        result = {}
        clearance_in = 0.003
        clearance_mm = 0.0762
        
        # Use proximal OD (larger) if available
        od_in = od_specs.get("proximal_inches") or od_specs.get("distal_inches")
        od_mm = od_specs.get("proximal_mm") or od_specs.get("distal_mm")
        
        if od_in:
            min_id = float(od_in) + clearance_in
            result["min_inches"] = round(min_id, 4)
            result["based_on_od_inches"] = od_in
        
        if od_mm:
            min_id = float(od_mm) + clearance_mm
            result["min_mm"] = round(min_id, 4)
            result["based_on_od_mm"] = od_mm
        
        return result
    
    def _calculate_max_od_from_id(self, id_specs: dict) -> dict:
        """Calculate maximum OD that can fit based on device ID."""
        result = {}
        clearance_in = 0.003
        clearance_mm = 0.0762
        
        if "inches" in id_specs:
            max_od = float(id_specs["inches"]) - clearance_in
            result["max_inches"] = round(max_od, 4)
            result["based_on_id_inches"] = id_specs["inches"]
        
        if "mm" in id_specs:
            max_od = float(id_specs["mm"]) - clearance_mm
            result["max_mm"] = round(max_od, 4)
            result["based_on_id_mm"] = id_specs["mm"]
        
        return result
    
    def _collect_middle_device_specs(self, all_pairs_by_interface: dict, 
                                      connection_results: list,
                                      mentioned_ids: dict) -> list:
        """
        Collect the range of specs for middle devices that worked.
        
        Returns list of middle device info with ID/OD ranges.
        """
        middle_specs = []
        
        # Middle devices appear as:
        # - outer device in interface 0
        # - inner device in interface 1 (if 3+ devices)
        # etc.
        
        num_interfaces = len(connection_results)
        
        if num_interfaces < 1:
            return middle_specs
        
        # For a 3-device chain (A -> B -> C), B is the middle device
        # B appears as outer in interface 0 (A->B) and inner in interface 1 (B->C)
        
        # Collect all unique middle devices and their specs
        middle_device_specs = {}
        
        for interface_idx, pairs in all_pairs_by_interface.items():
            for pair_data in pairs:
                pair = pair_data["pair"]
                
                # Check outer device of this interface (if not the last interface)
                if interface_idx < num_interfaces - 1:
                    outer = pair.get("outer", {})
                    outer_id = str(outer.get("id", ""))
                    outer_name = outer.get("product_name", "Unknown")
                    
                    if outer_name not in middle_device_specs:
                        middle_device_specs[outer_name] = {
                            "product_name": outer_name,
                            "conical_category": outer.get("conical_category", "Unknown"),
                            "is_mentioned": outer_id in mentioned_ids,
                            "id_values": [],
                            "od_values": []
                        }
                    
                    # Collect ID specs (what can fit inside this device)
                    id_specs = self._extract_id_specs(outer)
                    if id_specs:
                        middle_device_specs[outer_name]["id_values"].append(id_specs)
                    
                    # Collect OD specs (what this device needs to fit into)
                    od_specs = self._extract_od_specs(outer)
                    if od_specs:
                        middle_device_specs[outer_name]["od_values"].append(od_specs)
                
                # Check inner device of this interface (if not the first interface)
                if interface_idx > 0:
                    inner = pair.get("inner", {})
                    inner_id = str(inner.get("id", ""))
                    inner_name = inner.get("product_name", "Unknown")
                    
                    # Skip if this is the distal device (handled separately)
                    if interface_idx == 0:
                        continue
                    
                    if inner_name not in middle_device_specs:
                        middle_device_specs[inner_name] = {
                            "product_name": inner_name,
                            "conical_category": inner.get("conical_category", "Unknown"),
                            "is_mentioned": inner_id in mentioned_ids,
                            "id_values": [],
                            "od_values": []
                        }
                    
                    id_specs = self._extract_id_specs(inner)
                    if id_specs:
                        middle_device_specs[inner_name]["id_values"].append(id_specs)
                    
                    od_specs = self._extract_od_specs(inner)
                    if od_specs:
                        middle_device_specs[inner_name]["od_values"].append(od_specs)
        
        # Calculate ranges for each middle device
        for name, specs in middle_device_specs.items():
            id_range = self._calculate_spec_range(specs["id_values"], "id")
            od_range = self._calculate_spec_range(specs["od_values"], "od")
            
            middle_specs.append({
                "product_name": name,
                "conical_category": specs["conical_category"],
                "is_mentioned": specs["is_mentioned"],
                "id_range": id_range,
                "od_range": od_range
            })
        
        return middle_specs
    
    def _calculate_spec_range(self, spec_values: list, spec_type: str) -> dict:
        """Calculate min/max range from a list of spec values."""
        if not spec_values:
            return {}
        
        result = {}
        
        if spec_type == "id":
            inches_vals = [s.get("inches") for s in spec_values if s.get("inches")]
            mm_vals = [s.get("mm") for s in spec_values if s.get("mm")]
            
            if inches_vals:
                result["min_inches"] = min(inches_vals)
                result["max_inches"] = max(inches_vals)
            if mm_vals:
                result["min_mm"] = min(mm_vals)
                result["max_mm"] = max(mm_vals)
        
        else:  # od
            # Check both distal and proximal
            distal_in = [s.get("distal_inches") for s in spec_values if s.get("distal_inches")]
            distal_mm = [s.get("distal_mm") for s in spec_values if s.get("distal_mm")]
            prox_in = [s.get("proximal_inches") for s in spec_values if s.get("proximal_inches")]
            prox_mm = [s.get("proximal_mm") for s in spec_values if s.get("proximal_mm")]
            
            if distal_in:
                result["distal_min_inches"] = min(distal_in)
                result["distal_max_inches"] = max(distal_in)
            if distal_mm:
                result["distal_min_mm"] = min(distal_mm)
                result["distal_max_mm"] = max(distal_mm)
            if prox_in:
                result["proximal_min_inches"] = min(prox_in)
                result["proximal_max_inches"] = max(prox_in)
            if prox_mm:
                result["proximal_min_mm"] = min(prox_mm)
                result["proximal_max_mm"] = max(prox_mm)
        
        return result
    
    def _build_constraint_summary(self, chain_constraint: dict) -> dict:
        """Build a summary of the constraints for a chain."""
        summary = {
            "distal_requires": {},
            "proximal_accepts": {},
            "middle_must_have": {}
        }
        
        distal = chain_constraint.get("distal_device", {})
        proximal = chain_constraint.get("proximal_device", {})
        middle = chain_constraint.get("middle_devices", [])
        
        # Distal device requirements
        if distal:
            constraints = distal.get("constraints", {})
            if "requires_catheter_id" in constraints:
                summary["distal_requires"]["catheter_id"] = constraints["requires_catheter_id"]
            elif "requires_min_id" in constraints:
                summary["distal_requires"]["min_id"] = constraints["requires_min_id"]
        
        # Proximal device acceptance
        if proximal:
            constraints = proximal.get("constraints", {})
            if "accepts_catheter_od" in constraints:
                summary["proximal_accepts"]["catheter_od"] = constraints["accepts_catheter_od"]
            elif "accepts_max_od" in constraints:
                summary["proximal_accepts"]["max_od"] = constraints["accepts_max_od"]
            if "device_id" in constraints:
                summary["proximal_accepts"]["device_id"] = constraints["device_id"]
        
        # Middle device requirements
        if middle:
            for m in middle:
                name = m.get("product_name", "Unknown")
                summary["middle_must_have"][name] = {
                    "id_range": m.get("id_range", {}),
                    "od_range": m.get("od_range", {})
                }
        
        return summary
    
    def _generate_llm_summaries(self, chain_constraints: list) -> list:
        """Generate human-readable summaries for LLM consumption."""
        summaries = []
        
        for chain in chain_constraints:
            lines = []
            device_path = chain.get("device_path", [])
            chain_idx = chain.get("chain_index")
            
            lines.append(f"Chain {chain_idx}: {' -> '.join(device_path)}")
            lines.append("")
            
            # Distal device
            distal = chain.get("distal_device", {})
            if distal:
                name = distal.get("product_name", "Unknown")
                fit_logic = distal.get("fit_logic", "unknown")
                category = distal.get("conical_category", "?")
                
                lines.append(f"DISTAL (innermost): {name} [{category}] (fit_logic={fit_logic})")
                
                constraints = distal.get("constraints", {})
                if "requires_catheter_id" in constraints:
                    req = constraints["requires_catheter_id"]
                    if "inches" in req:
                        lines.append(f"  → Requires catheter with ID: {req['inches']} inches")
                    if "mm" in req:
                        lines.append(f"  → Requires catheter with ID: {req['mm']} mm")
                elif "requires_min_id" in constraints:
                    req = constraints["requires_min_id"]
                    if "min_inches" in req:
                        lines.append(f"  → Has OD of {req.get('based_on_od_inches')} inches, needs catheter ID ≥ {req['min_inches']} inches")
                    if "min_mm" in req:
                        lines.append(f"  → Has OD of {req.get('based_on_od_mm')} mm, needs catheter ID ≥ {req['min_mm']} mm")
            
            lines.append("")
            
            # Middle devices
            middle = chain.get("middle_devices", [])
            if middle:
                lines.append("MIDDLE DEVICE(S) must satisfy:")
                for m in middle:
                    name = m.get("product_name", "Unknown")
                    category = m.get("conical_category", "?")
                    id_range = m.get("id_range", {})
                    od_range = m.get("od_range", {})
                    
                    lines.append(f"  {name} [{category}]:")
                    
                    if id_range:
                        if "min_inches" in id_range and "max_inches" in id_range:
                            if id_range["min_inches"] == id_range["max_inches"]:
                                lines.append(f"    - ID: {id_range['min_inches']} inches")
                            else:
                                lines.append(f"    - ID range: {id_range['min_inches']} - {id_range['max_inches']} inches")
                        if "min_mm" in id_range and "max_mm" in id_range:
                            if id_range["min_mm"] == id_range["max_mm"]:
                                lines.append(f"    - ID: {id_range['min_mm']} mm")
                            else:
                                lines.append(f"    - ID range: {id_range['min_mm']} - {id_range['max_mm']} mm")
                    
                    if od_range:
                        if "proximal_max_inches" in od_range:
                            lines.append(f"    - OD (proximal): up to {od_range['proximal_max_inches']} inches")
                        if "proximal_max_mm" in od_range:
                            lines.append(f"    - OD (proximal): up to {od_range['proximal_max_mm']} mm")
                
                lines.append("")
            
            # Proximal device
            proximal = chain.get("proximal_device", {})
            if proximal:
                name = proximal.get("product_name", "Unknown")
                fit_logic = proximal.get("fit_logic", "unknown")
                category = proximal.get("conical_category", "?")
                
                lines.append(f"PROXIMAL (outermost): {name} [{category}] (fit_logic={fit_logic})")
                
                constraints = proximal.get("constraints", {})
                if "accepts_catheter_od" in constraints:
                    req = constraints["accepts_catheter_od"]
                    if "max_inches" in req:
                        lines.append(f"  → Accepts catheter with OD up to: {req['max_inches']} inches")
                    if "max_mm" in req:
                        lines.append(f"  → Accepts catheter with OD up to: {req['max_mm']} mm")
                elif "device_id" in constraints:
                    id_spec = constraints["device_id"]
                    max_od = constraints.get("accepts_max_od", {})
                    if "inches" in id_spec:
                        max_od_in = max_od.get("max_inches", "?")
                        lines.append(f"  → Has ID of {id_spec['inches']} inches (accepts OD up to ~{max_od_in} inches)")
                    if "mm" in id_spec:
                        max_od_mm = max_od.get("max_mm", "?")
                        lines.append(f"  → Has ID of {id_spec['mm']} mm (accepts OD up to ~{max_od_mm} mm)")
            
            lines.append("")
            lines.append("-" * 60)
            
            summaries.append("\n".join(lines))
        
        return summaries

    # ========== Original methods below ==========
    
    def get_overall_summary(self) -> dict:
        """
        Get high-level summary of all chains processed.
        
        Returns:
            Summary with total chains, variants, pass/fail counts
        """
        # Use pre-computed stats if available
        if self.summary_stats:
            total_chains = self.summary_stats["total_chains"]
            passing_chains = self.summary_stats["passing_chain_count"]
            failing_chains = self.summary_stats["failing_chain_count"]
        else:
            total_chains = len(self.analysis_results)
            passing_chains = sum(1 for c in self.analysis_results if c["status"] == "pass")
            failing_chains = sum(1 for c in self.analysis_results if c["status"] == "fail")
        
        total_paths = sum(c["total_paths"] for c in self.analysis_results)
        passing_paths = sum(c["passing_paths"] for c in self.analysis_results)
        failing_paths = sum(c["failing_paths"] for c in self.analysis_results)
        
        # Count total variants across all connections
        total_variants = 0
        passing_variants = 0
        failing_variants = 0
        
        for chain in self.analysis_results:
            for path in chain["path_results"]:
                for conn in path["connection_results"]:
                    for product in conn["product_results"]:
                        total_variants += product["total_variants"]
                        passing_variants += product["passing_variants"]
                        failing_variants += product["failing_variants"]
        
        return {
            "total_chains": total_chains,
            "passing_chains": passing_chains,
            "failing_chains": failing_chains,
            "total_paths": total_paths,
            "passing_paths": passing_paths,
            "failing_paths": failing_paths,
            "total_variants": total_variants,
            "passing_variants": passing_variants,
            "failing_variants": failing_variants
        }
    
    def get_passing_chain_records(self) -> list[dict]:
        """
        Generate detailed records for each passing chain.
        
        Returns:
            List of structured records for passing chains
        """
        records = []
        
        for chain in self.analysis_results:
            if chain["status"] != "pass":
                continue
            
            # Get passing paths for this chain
            for path in chain["path_results"]:
                if path["status"] != "pass":
                    continue
                
                chain_records = self._create_chain_records(chain, path)
                records.extend(chain_records)
        
        return records
    
    def _extract_device_fields(self, device: dict, prefix: str) -> dict:
        """Extract all device fields with a prefix."""
        
        # Core device fields
        core_fields = [
            "id",
            "manufacturer",
            "device_name",
            "product_name",
            "category_type",
        ]
        
        # Specification fields
        spec_fields = [
            "specification_inner-diameter_in",
            "specification_inner-diameter_mm",
            "specification_inner-diameter_F",
            "specification_outer-diameter-distal_in",
            "specification_outer-diameter-distal_mm",
            "specification_outer-diameter-distal_F",
            "specification_outer-diameter-proximal_in",
            "specification_outer-diameter-proximal_mm",
            "specification_outer-diameter-proximal_F",
            "specification_length_cm",
        ]
        
        # Compatibility fields
        compat_fields = [
            "compatibility_wire_max_outer-diameter_in",
            "compatibility_wire_max_outer-diameter_mm",
            "compatibility_wire_max_outer-diameter_F",
            "compatibility_catheter_max_outer-diameter_in",
            "compatibility_catheter_max_outer-diameter_mm",
            "compatibility_catheter_max_outer-diameter_F",
            "compatibility_catheter_req_inner-diameter_in",
            "compatibility_catheter_req_inner-diameter_mm",
            "compatibility_catheter_req_inner-diameter_F",
            "compatibility_guide_or_catheter_or_sheath_min_inner-diameter_in",
            "compatibility_guide_or_catheter_or_sheath_min_inner-diameter_mm",
            "compatibility_guide_or_catheter_or_sheath_min_inner-diameter_F",
        ]
        
        # Source/file path fields
        source_fields = [
            "file_path_source_FDA_has_doc",
            "file_path_source_FDA_source",
            "file_path_source_FDA_openai_id",
            "file_path_source_FDA_local_source_path",
            "file_path_source_FDA_s3_url",
            "Specifications_Pic_has_pic",
            "file_path_source_has_doc",
            "file_path_source_source",
            "file_path_source_openai_id",
            "file_path_source_local_source_path",
            "file_path_source_s3_url",
            "Specifications_Pic_local_source_path",
            "Specifications_Pic_s3_url",
        ]
        
        all_fields = core_fields + spec_fields + compat_fields + source_fields
        
        return {f"{prefix}_{field}": device.get(field) for field in all_fields}

    def _create_chain_records(self, chain: dict, path: dict) -> list[dict]:
        """
        Create records for a single passing path within a chain.
        
        Args:
            chain: The chain dict from analysis results
            path: The passing path dict
        
        Returns:
            List of records for each connection in the path
        """
        records = []
        chain_index = chain["chain_index"]
        device_path = path["device_path"]
        connection_results = path["connection_results"]
        
        # Build construct_devices string (full path)
        construct_devices = " -> ".join(device_path)
        
        for interface_index, conn_result in enumerate(connection_results, start=1):
            # Get ALL passing pairs for this connection
            all_passing_pairs = self._get_all_passing_pairs(conn_result)
            
            for passing_pair in all_passing_pairs:
                pair = passing_pair["pair"]
                pair_reasons = passing_pair["reasons"]
                pass_reason_type = passing_pair.get("pass_reason_type", "standard")
                override_note = passing_pair.get("override_note")
                
                record = self._build_record(
                    chain_index, construct_devices, interface_index,
                    pair, pair_reasons, "Compatible",
                    pass_reason_type, override_note
                )
                records.append(record)
        
        return records

    def _get_all_passing_pairs(self, conn_result: dict) -> list[dict]:
        """
        Get ALL passing pairs from the connection result.
        
        Args:
            conn_result: Connection result dict from analysis
        
        Returns:
            List of dicts with pair, reasons, and pass metadata for each passing pair
        """
        all_pairs = []
        passes = conn_result.get("passes", [])
        
        for pass_group in passes:
            pair_reasons_list = pass_group.get("pair_reasons", [])
            
            for pair_reasons in pair_reasons_list:
                pair_key = pair_reasons.get("pair_key")
                reasons = pair_reasons.get("reasons", {})
                pass_reason_type = pair_reasons.get("pass_reason_type", "standard")
                override_note = pair_reasons.get("override_note")
                
                pair = self._find_pair_by_key(pair_key)
                
                if pair:
                    all_pairs.append({
                        "pair": pair,
                        "reasons": reasons,
                        "pass_reason_type": pass_reason_type,
                        "override_note": override_note
                    })
        
        return all_pairs

    def _get_passing_pair(self, conn_result: dict) -> dict | None:
        """
        Get a passing pair from the connection result (first one only).
        
        Args:
            conn_result: Connection result dict from analysis
        
        Returns:
            Dict with pair and reasons, or None if no passing pair found
        """
        passes = conn_result.get("passes", [])
        
        if not passes:
            return None
        
        # Get the first passing product combination
        first_pass = passes[0]
        pair_reasons_list = first_pass.get("pair_reasons", [])
        
        if not pair_reasons_list:
            return None
        
        # Get the first passing pair's reasons
        first_pair_reasons = pair_reasons_list[0]
        pair_key = first_pair_reasons.get("pair_key")
        reasons = first_pair_reasons.get("reasons", {})
        
        # Find the actual pair data from processed results
        pair = self._find_pair_by_key(pair_key)
        
        return {
            "pair": pair,
            "reasons": reasons
        }
    
    def _find_pair_by_key(self, pair_key: str) -> dict:
        """
        Find the original pair data by pair_key.
        
        Args:
            pair_key: The pair key to search for
        
        Returns:
            The pair dict or empty dict if not found
        """
        for chain in self.processed_results:
            for path in chain.get("paths", []):
                for conn in path.get("connections", []):
                    for pair in conn.get("processed_pairs", []):
                        if pair.get("pair_key") == pair_key:
                            return pair
        return {}
    
    def _build_compatibility_evidence(self, pair_reasons: dict, override_note: str = None) -> dict:
        """
        Build the compatibility evidence from pair reasons.
        
        Args:
            pair_reasons: The reasons dict from generate_pair_reasons
            override_note: Optional note explaining geometry override
        
        Returns:
            Structured compatibility evidence
        """
        compatibility_reasons = pair_reasons.get("compatibility_reasons", [])
        geometry_reasons = pair_reasons.get("geometry_reasons", {})
        summary = pair_reasons.get("summary", "")
        
        diameter_reasons = geometry_reasons.get("diameter", [])
        length_reasons = geometry_reasons.get("length", [])
        
        evidence = {
            "summary": summary,
            "compatibility": {
                "reasons": compatibility_reasons
            },
            "geometry": {
                "fit": {
                    "reasons": diameter_reasons
                },
                "length": {
                    "reasons": length_reasons
                }
            }
        }
        
        # Add override note if present
        if override_note:
            evidence["override_note"] = override_note
        
        return evidence

    def get_failing_chain_records(self) -> list[dict]:
        """
        Generate detailed records for each failing chain.
        
        Returns:
            List of structured records for failing chains
        """
        records = []
        
        for chain in self.analysis_results:
            if chain["status"] != "fail":
                continue
            
            # Process all paths (they're all failing or we wouldn't be here)
            for path in chain["path_results"]:
                chain_records = self._create_failing_chain_records(chain, path)
                records.extend(chain_records)
        
        return records
    
    def _create_failing_chain_records(self, chain: dict, path: dict) -> list[dict]:
        """
        Create records for a failing path within a chain.
        
        Args:
            chain: The chain dict from analysis results
            path: The path dict (could be passing or failing)
        
        Returns:
            List of records for each connection in the path
        """
        records = []
        chain_index = chain["chain_index"]
        device_path = path["device_path"]
        connection_results = path["connection_results"]
        
        construct_devices = " -> ".join(device_path)
        
        for interface_index, conn_result in enumerate(connection_results, start=1):
            conn_status = conn_result.get("status", "fail")
            
            if conn_status == "pass":
                # This connection passed, get all passing pairs
                all_passing_pairs = self._get_all_passing_pairs(conn_result)
                for passing_pair in all_passing_pairs:
                    pair = passing_pair["pair"]
                    pair_reasons = passing_pair["reasons"]
                    pass_reason_type = passing_pair.get("pass_reason_type", "standard")
                    override_note = passing_pair.get("override_note")
                    
                    record = self._build_record(
                        chain_index, construct_devices, interface_index,
                        pair, pair_reasons, "Compatible",
                        pass_reason_type, override_note
                    )
                    records.append(record)
            else:
                # This connection failed, get all failing pairs
                all_failing_pairs = self._get_all_failing_pairs(conn_result)
                for failing_pair in all_failing_pairs:
                    pair = failing_pair["pair"]
                    pair_reasons = failing_pair["reasons"]
                    
                    record = self._build_record(
                        chain_index, construct_devices, interface_index,
                        pair, pair_reasons, "Not Compatible",
                        "standard", None  # Failing pairs don't have override
                    )
                    records.append(record)
        
        return records

    def _build_record(self, chain_index: int, construct_devices: str, interface_index: int,
                    pair: dict, pair_reasons: dict, compatibility_result: str,
                    pass_reason_type: str = "standard", override_note: str = None) -> dict:
        """
        Build a single record from pair data.
        """
        inner = pair.get("inner", {})
        outer = pair.get("outer", {})
        
        # Fallback for device_to_device_connection string
        inner_product_name = inner.get("product_name") or pair.get("inner_name", "Unknown")
        outer_product_name = outer.get("product_name") or pair.get("outer_name", "Unknown")
        
        # Determine evaluation method
        if pass_reason_type == "geometry_override":
            evaluation_method = "Specifications (Geometry Override)"
        else:
            overall_status = pair.get("overall_status", {})
            compat_status = overall_status.get("compatibility_status", {}).get("status", "NA")
            
            if compat_status in ["pass", "fail"]:
                evaluation_method = "IFU"
            elif compat_status == "NA":
                evaluation_method = "Specifications"
            else:
                evaluation_method = "Unknown"
        
        compatibility_evidence = self._build_compatibility_evidence(pair_reasons, override_note)
        
        record = {
            "construct_option_id": chain_index,
            "construct_devices": construct_devices,
            "interface_order": interface_index,
            "device_to_device_connection": f"{inner_product_name} -> {outer_product_name}",
            "evaluation_method": evaluation_method,
            "compatibility_result": compatibility_result,
            "compatibility_evidence": compatibility_evidence,
            "pass_reason_type": pass_reason_type
        }
        
        # Add all distal (inner) device fields
        record.update(self._extract_device_fields(inner, "distal"))
        
        # Add all proximal (outer) device fields
        record.update(self._extract_device_fields(outer, "proximal"))
        
        return record

    def _get_all_failing_pairs(self, conn_result: dict) -> list[dict]:
        """
        Get ALL failing pairs from the connection result.
        
        Args:
            conn_result: Connection result dict from analysis
        
        Returns:
            List of dicts with pair and reasons for each failing pair
        """
        all_pairs = []
        failures = conn_result.get("failures", [])
        
        for fail_group in failures:
            pair_reasons_list = fail_group.get("pair_reasons", [])
            
            for pair_reasons in pair_reasons_list:
                pair_key = pair_reasons.get("pair_key")
                reasons = pair_reasons.get("reasons", {})
                
                pair = self._find_pair_by_key(pair_key)
                
                if pair:
                    all_pairs.append({
                        "pair": pair,
                        "reasons": reasons
                    })
        
        return all_pairs
    
    def _get_failing_pair(self, conn_result: dict) -> dict | None:
        """
        Get a failing pair from the connection result (first one only).
        
        Args:
            conn_result: Connection result dict from analysis
        
        Returns:
            Dict with pair and reasons, or None if no failing pair found
        """
        failures = conn_result.get("failures", [])
        
        if not failures:
            return None
        
        first_failure = failures[0]
        pair_reasons_list = first_failure.get("pair_reasons", [])
        
        if not pair_reasons_list:
            return None
        
        first_pair_reasons = pair_reasons_list[0]
        pair_key = first_pair_reasons.get("pair_key")
        reasons = first_pair_reasons.get("reasons", {})
        
        pair = self._find_pair_by_key(pair_key)
        
        return {
            "pair": pair,
            "reasons": reasons
        }
    
    def get_full_summary(self) -> dict:
        """
        Get complete summary with overall stats and all chain records.
        
        Returns:
            Full summary dict
        """
        return {
            "overall_summary": self.get_overall_summary(),
            "passing_chain_records": self.get_passing_chain_records(),
            "failing_chain_records": self.get_failing_chain_records()
        }

    def _generate_compatibility_check_text(self, chain_summaries: list) -> list:
        """
        Generate text for COMPATIBILITY_CHECK sub-type.
        
        Focus: Direct yes/no answer with dimensional evidence for each chain.
        Shows pass/fail status prominently, with specific measurements.
        """
        # Group by pattern
        pattern_groups = {}
        for chain in chain_summaries:
            pattern = chain.get("pattern", {})
            sequence = tuple(pattern.get("sequence", []))
            status = chain.get("status", "fail")
            key = (sequence, status)
            
            if key not in pattern_groups:
                pattern_groups[key] = {
                    "pattern": pattern,
                    "status": status,
                    "chains": []
                }
            pattern_groups[key]["chains"].append(chain)
        
        texts = []
        
        for (sequence, status), group in pattern_groups.items():
            chains = group["chains"]
            lines = []
            
            # Status header
            status_icon = "✅" if status == "pass" else "❌"
            status_word = "COMPATIBLE" if status == "pass" else "NOT COMPATIBLE"
            path_display = " → ".join(sequence)
            
            lines.append(f"{status_icon} {status_word}: {path_display}")
            lines.append("")
            
            # Consolidate positions
            consolidated_positions = self._consolidate_positions(chains, sequence)
            
            # Show each connection with dimensional evidence
            for pos_idx in range(len(consolidated_positions) - 1):
                inner = consolidated_positions[pos_idx]
                outer = consolidated_positions[pos_idx + 1]
                
                inner_name = inner["device_name"]
                outer_name = outer["device_name"]
                
                # Get relevant specs for this connection
                inner_reqs = inner.get("requirements", {})
                outer_reqs = outer.get("requirements", {})
                
                # Inner device OD or compat requirement
                inner_spec = ""
                if "device_od" in inner_reqs:
                    od = inner_reqs["device_od"]
                    od_val = self._get_preferred_unit_value_od(od)
                    if od_val:
                        inner_spec = f"OD {od_val}"
                elif "requires_catheter_id" in inner_reqs:
                    id_req = inner_reqs["requires_catheter_id"]
                    id_val = self._get_preferred_unit_value(id_req, ["inches", "mm"])
                    if id_val:
                        inner_spec = f"requires catheter ID {id_val}"
                
                # Outer device ID
                outer_spec = ""
                if "device_id" in outer_reqs:
                    id_spec = outer_reqs["device_id"]
                    id_val = self._get_preferred_unit_value(id_spec, ["inches", "mm"])
                    if id_val:
                        outer_spec = f"ID {id_val}"
                elif "accepts_catheter_od" in outer_reqs:
                    od_req = outer_reqs["accepts_catheter_od"]
                    od_val = self._get_preferred_unit_value_from_max(od_req)
                    if od_val:
                        outer_spec = f"accepts OD up to {od_val}"
                
                # Connection line
                connection_icon = "✓" if status == "pass" else "✗"
                if inner_spec and outer_spec:
                    lines.append(f"  {connection_icon} {inner_name} ({inner_spec}) → {outer_name} ({outer_spec})")
                else:
                    lines.append(f"  {connection_icon} {inner_name} → {outer_name}")
                
                # Length info
                inner_length = inner_reqs.get("device_length_cm")
                outer_length = outer_reqs.get("device_length_cm")
                if inner_length and outer_length:
                    lines.append(f"    Length: {inner_name} {inner_length}cm, {outer_name} {outer_length}cm")
            
            # Failure reasons
            if status == "fail":
                failure_reasons = self._extract_failure_reasons_for_text(chains)
                if failure_reasons:
                    lines.append("")
                    lines.append("Reason:")
                    for reason in failure_reasons:
                        lines.append(f"  ⚠ {reason}")
            
            lines.append("")
            texts.append("\n".join(lines))
        
        return texts


    # ============================================================
    # SUB-TYPE 2: DEVICE_DISCOVERY
    # ============================================================
    # "What microcatheters work with Vecta 46?"
    # "What catheter do I use with an Atlas stent?"
    # "List catheters I can use with a Vecta 71"
    #
    # Focus: Source device context + grouped list of compatible devices
    # Mix of named devices and categories
    # Only shows passing chains
    # Output should help LLM give a recommendation
    # ============================================================

    def _generate_device_discovery_text(self, chain_summaries: list, 
                                        named_device_names: set,
                                        categories: list) -> list:
        """
        Generate text for DEVICE_DISCOVERY sub-type.
        
        Focus: Source device specs for context, then a clean list of compatible devices
        grouped by category. Designed so the output LLM can explain WHY these devices
        work and potentially recommend options.
        """
        if not chain_summaries:
            return ["No compatible devices found."]
        
        lines = []
        
        # ---- Section 1: Source device context ----
        # Find all named devices and their specs
        lines.append("SOURCE DEVICE(S):")
        lines.append("")
        
        source_devices_shown = set()
        for chain in chain_summaries:
            for pos in chain.get("positions", []):
                if pos["is_named_device"] and pos["device_name"] not in source_devices_shown:
                    source_devices_shown.add(pos["device_name"])
                    name = pos["device_name"]
                    constraints = pos.get("constraints", {})
                    reqs = constraints.get("requirements", {})
                    fit_logic = constraints.get("fit_logic", "unknown")
                    
                    lines.append(f"  {name} (fit_logic={fit_logic}):")
                    
                    # Show relevant specs
                    if "device_id" in reqs:
                        id_val = self._get_preferred_unit_value(reqs["device_id"], ["inches", "mm"])
                        if id_val:
                            lines.append(f"    - ID: {id_val}")
                    
                    if "device_od" in reqs:
                        od_val = self._get_preferred_unit_value_od(reqs["device_od"])
                        if od_val:
                            lines.append(f"    - OD: {od_val}")
                    
                    if "requires_catheter_id" in reqs:
                        id_req = reqs["requires_catheter_id"]
                        id_val = self._get_preferred_unit_value(id_req, ["inches", "mm"])
                        if id_val:
                            lines.append(f"    - Requires catheter ID: {id_val}")
                    
                    if "accepts_max_od" in reqs:
                        od_max = self._get_preferred_unit_value_from_max(reqs["accepts_max_od"])
                        if od_max:
                            lines.append(f"    - Accepts OD up to: {od_max}")
                    
                    if "accepts_catheter_od" in reqs:
                        od_req = self._get_preferred_unit_value_from_max(reqs["accepts_catheter_od"])
                        if od_req:
                            lines.append(f"    - Accepts catheter OD up to: {od_req}")
                    
                    if "device_length_cm" in reqs:
                        lines.append(f"    - Length: {reqs['device_length_cm']}cm")
                    
                    lines.append("")
        
        # ---- Section 2: Compatible devices found ----
        # Collect all unique compatible devices by category position
        compatible_by_category = {}  # category_name -> set of device names
        
        for chain in chain_summaries:
            if chain.get("status") != "pass":
                continue
            
            for pos in chain.get("positions", []):
                if not pos["is_named_device"]:
                    # This is a category position - collect the actual device name
                    device_name = pos["device_name"]
                    # Find which category this belongs to
                    category_key = None
                    pattern_sequence = chain.get("pattern", {}).get("sequence", [])
                    if pos["position_index"] < len(pattern_sequence):
                        pattern_item = pattern_sequence[pos["position_index"]]
                        if pattern_item in categories:
                            category_key = pattern_item
                    
                    if not category_key:
                        category_key = "devices"
                    
                    if category_key not in compatible_by_category:
                        compatible_by_category[category_key] = set()
                    compatible_by_category[category_key].add(device_name)
        
        # Also collect from chain device paths directly
        # (more reliable since positions might show the actual device name)
        for chain in chain_summaries:
            if chain.get("status") != "pass":
                continue
            
            device_path = chain.get("device_path", [])
            pattern_sequence = chain.get("pattern", {}).get("sequence", [])
            
            for idx, device_name in enumerate(device_path):
                if device_name not in named_device_names:
                    category_key = pattern_sequence[idx] if idx < len(pattern_sequence) else "devices"
                    if category_key not in named_device_names:
                        if category_key not in compatible_by_category:
                            compatible_by_category[category_key] = set()
                        compatible_by_category[category_key].add(device_name)
        
        lines.append("COMPATIBLE DEVICES FOUND:")
        lines.append("")
        
        total_found = 0
        for category, devices in compatible_by_category.items():
            sorted_devices = sorted(devices)
            total_found += len(sorted_devices)
            lines.append(f"  {category} ({len(sorted_devices)} compatible):")
            for device in sorted_devices:
                lines.append(f"    - {device}")
            lines.append("")
        
        if total_found == 0:
            lines.append("  No compatible devices found.")
            lines.append("")
        
        lines.append(f"Total: {total_found} compatible device(s) found")
        
        # ---- Section 3: Requirement groups (if relevant) ----
        # Show if different variants of the source device have different requirements
        has_groups = False
        for chain in chain_summaries:
            for pos in chain.get("positions", []):
                if pos["is_named_device"]:
                    groups = pos.get("constraints", {}).get("requires_catheter_id_groups", [])
                    if len(groups) > 1:
                        has_groups = True
                        break
        
        if has_groups:
            lines.append("")
            lines.append("NOTE: Source device variants have different requirements:")
            for chain in chain_summaries:
                for pos in chain.get("positions", []):
                    if pos["is_named_device"]:
                        groups = pos.get("constraints", {}).get("requires_catheter_id_groups", [])
                        if len(groups) > 1:
                            for group in groups:
                                req_key = group.get("requirement_key", "")
                                variant_count = group.get("variant_count", 0)
                                compat_count = group.get("compatible_outer_count", 0)
                                lines.append(f"  - Variants requiring ID {req_key}\": {variant_count} variant(s), {compat_count} compatible device(s)")
        
        return ["\n".join(lines)]


    # ============================================================
    # SUB-TYPE 3: STACK_VALIDATION
    # ============================================================
    # "What order do I use Trak 21, Neuron Max, Paragon, Vecta 71?"
    # "Can I use Vecta 46, Neuron Max, Paragon, Vecta 71, .014" wire?"
    #
    # Focus: Correct ordering from distal to proximal
    # Connection-by-connection validation
    # All devices typically named
    # Shows the "stack" as a visual chain
    # ============================================================

    def _generate_stack_validation_text(self, chain_summaries: list) -> list:
        """
        Generate text for STACK_VALIDATION sub-type.
        
        Focus: Clear ordered stack from distal (innermost) to proximal (outermost),
        with connection-by-connection pass/fail and dimensional evidence.
        Designed for "what order" and "can I use all of these together" questions.
        """
        # Group by pattern + status
        pattern_groups = {}
        for chain in chain_summaries:
            pattern = chain.get("pattern", {})
            sequence = tuple(pattern.get("sequence", []))
            status = chain.get("status", "fail")
            key = (sequence, status)
            
            if key not in pattern_groups:
                pattern_groups[key] = {
                    "pattern": pattern,
                    "status": status,
                    "chains": []
                }
            pattern_groups[key]["chains"].append(chain)
        
        texts = []
        
        for (sequence, status), group in pattern_groups.items():
            chains = group["chains"]
            lines = []
            
            # Overall status
            status_icon = "✅" if status == "pass" else "❌"
            status_word = "VALID STACK" if status == "pass" else "INVALID STACK"
            
            lines.append(f"{status_icon} {status_word}")
            lines.append("")
            
            # Show the ordered stack
            lines.append("STACK ORDER (distal/innermost → proximal/outermost):")
            lines.append("")
            
            consolidated_positions = self._consolidate_positions(chains, sequence)
            
            for pos_idx, pos_data in enumerate(consolidated_positions):
                name = pos_data["device_name"]
                reqs = pos_data.get("requirements", {})
                
                # Position label
                if pos_data["is_distal"]:
                    pos_label = "DISTAL"
                elif pos_data["is_proximal"]:
                    pos_label = "PROXIMAL"
                else:
                    pos_label = f"POSITION {pos_idx + 1}"
                
                # Build spec summary
                specs = []
                if "device_od" in reqs:
                    od_val = self._get_preferred_unit_value_od(reqs["device_od"])
                    if od_val:
                        specs.append(f"OD: {od_val}")
                if "device_id" in reqs:
                    id_val = self._get_preferred_unit_value(reqs["device_id"], ["inches", "mm"])
                    if id_val:
                        specs.append(f"ID: {id_val}")
                if "device_length_cm" in reqs:
                    specs.append(f"Length: {reqs['device_length_cm']}cm")
                
                spec_str = f" ({', '.join(specs)})" if specs else ""
                lines.append(f"  {pos_idx + 1}. [{pos_label}] {name}{spec_str}")
            
            lines.append("")
            
            # Show connection-by-connection results
            lines.append("CONNECTION DETAILS:")
            lines.append("")
            
            for pos_idx in range(len(consolidated_positions) - 1):
                inner = consolidated_positions[pos_idx]
                outer = consolidated_positions[pos_idx + 1]
                
                inner_name = inner["device_name"]
                outer_name = outer["device_name"]
                inner_reqs = inner.get("requirements", {})
                outer_reqs = outer.get("requirements", {})
                
                # Determine if this specific connection passes
                # For now, mark all as pass for passing chains, 
                # and identify the failing connection for failing chains
                conn_icon = "✓" if status == "pass" else "?"
                
                lines.append(f"  Interface {pos_idx + 1}: {inner_name} → {outer_name}")
                
                # Inner device OD
                if "device_od" in inner_reqs:
                    od_val = self._get_preferred_unit_value_od(inner_reqs["device_od"])
                    if od_val:
                        lines.append(f"    {inner_name} OD: {od_val}")
                elif "requires_catheter_id" in inner_reqs:
                    id_req = self._get_preferred_unit_value(inner_reqs["requires_catheter_id"], ["inches", "mm"])
                    if id_req:
                        lines.append(f"    {inner_name} requires catheter ID: {id_req}")
                
                # Outer device ID
                if "device_id" in outer_reqs:
                    id_val = self._get_preferred_unit_value(outer_reqs["device_id"], ["inches", "mm"])
                    max_od = self._get_preferred_unit_value_from_max(outer_reqs.get("accepts_max_od", {}))
                    if id_val:
                        if max_od:
                            lines.append(f"    {outer_name} ID: {id_val} (accepts OD up to ~{max_od})")
                        else:
                            lines.append(f"    {outer_name} ID: {id_val}")
                
                # Length comparison
                inner_len = inner_reqs.get("device_length_cm")
                outer_len = outer_reqs.get("device_length_cm")
                if inner_len and outer_len:
                    try:
                        inner_float = float(inner_len)
                        outer_float = float(outer_len)
                        len_status = "✓" if inner_float >= outer_float else "✗"
                        lines.append(f"    Length: {inner_name} {inner_len}cm vs {outer_name} {outer_len}cm {len_status}")
                    except (ValueError, TypeError):
                        lines.append(f"    Length: {inner_name} {inner_len}cm, {outer_name} {outer_len}cm")
                
                lines.append("")
            
            # Failure reasons for failing stacks
            if status == "fail":
                failure_reasons = self._extract_failure_reasons_for_text(chains)
                if failure_reasons:
                    lines.append("FAILURE REASON(S):")
                    for reason in failure_reasons:
                        lines.append(f"  ⚠ {reason}")
                    lines.append("")
            
            texts.append("\n".join(lines))
        
        return texts

    def get_chain_requirements_summary(self, input_data: dict, mentioned_devices: dict = None, 
                                        mentioned_categories: list = None,
                                        include_failing: bool = False,
                                        chain_sub_type: str = None,
                                        classification: dict = None) -> dict:
        """
        Generate LLM-friendly summaries showing what each position in the chain requires.
        
        Accepts either:
            - chain_sub_type: Legacy routing ("COMPATIBILITY_CHECK", "DEVICE_DISCOVERY", "STACK_VALIDATION")
            - classification: New classification dict from query_classification_agent
        
        If classification is provided, it takes precedence over chain_sub_type.
        
        Args:
            input_data: Combined dict or chains_to_check dict
            mentioned_devices: (Optional) Dict with named device info
            mentioned_categories: (Optional) List of category names
            include_failing: If True, include failing chains (can be overridden by classification)
            chain_sub_type: Legacy sub_type for backward compatibility
            classification: NEW - Dict from query_classification_agent with:
                - query_mode: exploratory | comparison | discovery
                - response_framing: positive | negative | neutral
                - query_structure: two_device | multi_device | named_plus_category | etc.
        
        Returns:
            Dict with chain_summaries and llm_text_summaries
        """
        
        # ============================================================
        # EXTRACT CLASSIFICATION (if provided)
        # ============================================================
        if classification:
            query_mode = classification.get("query_mode", "exploratory")
            response_framing = classification.get("response_framing", "neutral")
            query_structure = classification.get("query_structure", "two_device")
            
            # Override include_failing based on classification
            if query_structure in ["two_device", "multi_device"]:
                include_failing = True
            elif query_mode == "discovery" and response_framing != "negative":
                include_failing = False
            elif query_mode == "comparison":
                include_failing = True
            elif response_framing == "negative":
                include_failing = True
        else:
            query_mode = None
            response_framing = None
            query_structure = None
            
            # Legacy: Auto-set include_failing based on chain_sub_type
            if chain_sub_type == "COMPATIBILITY_CHECK":
                include_failing = True
            elif chain_sub_type == "STACK_VALIDATION":
                include_failing = True
            elif chain_sub_type == "DEVICE_DISCOVERY":
                include_failing = False
        
        # ============================================================
        # HANDLE INPUT FORMAT
        # ============================================================
        if "mentioned_devices" in input_data and mentioned_devices is None:
            chains = input_data.get("chains_to_check", [])
            devices_dict = input_data.get("mentioned_devices", {})
            categories = input_data.get("mentioned_categories", [])
        else:
            chains = input_data.get("chains_to_check", input_data)
            devices_dict = mentioned_devices.get("mentioned_devices", mentioned_devices) if mentioned_devices else {}
            categories = mentioned_categories or []
        
        if isinstance(chains, dict):
            chains = [chains]
        
        # Auto-detect categories if not provided
        if not categories:
            named_device_names = set(devices_dict.keys())
            for chain in chains:
                for item in chain.get("sequence", []):
                    if item not in named_device_names:
                        categories.append(item)
            categories = list(set(categories))
        
        # Build lookup for mentioned device IDs
        mentioned_ids = {}
        named_device_names = set()
        for product_name, info in devices_dict.items():
            named_device_names.add(product_name)
            for device_id in info.get("ids", []):
                mentioned_ids[str(device_id)] = {
                    "product_name": product_name,
                    "conical_category": info.get("conical_category", "Unknown")
                }
        
        # ============================================================
        # INITIALIZE RESULTS
        # ============================================================
        results = {
            "chain_summaries": [],
            "llm_text_summaries": [],
            "classification_used": {
                "query_mode": query_mode,
                "response_framing": response_framing,
                "query_structure": query_structure,
                "chain_sub_type": chain_sub_type,
                "include_failing": include_failing
            }
        }
        
        # ============================================================
        # PROCESS CHAINS
        # ============================================================
        for chain in self.analysis_results:
            chain_status = chain.get("status", "fail")
            
            # Skip failing chains unless include_failing is True
            if chain_status != "pass" and not include_failing:
                continue
            
            for path in chain.get("path_results", []):
                path_status = path.get("status", "fail")
                
                # For passing chains, only process passing paths
                if chain_status == "pass" and path_status != "pass":
                    continue
                
                device_path = path.get("device_path", [])
                connection_results = path.get("connection_results", [])
                
                # Match this chain to one of the chains_to_check patterns
                chain_pattern = self._match_chain_pattern(device_path, chains, named_device_names, categories)
                if not chain_pattern:
                    continue
                
                # ============================================================
                # COMPUTE EFFECTIVE STATUS from connection-level data
                # A chain is "pass" if every connection has at least one passing pair
                # ============================================================
                effective_status = "pass"
                for conn_result in connection_results:
                    passing_pairs = self._get_all_passing_pairs_for_requirements(conn_result)
                    if not passing_pairs:
                        effective_status = "fail"
                        break
                
                # Decide which pairs to collect based on effective_status
                all_pairs_by_interface = {}
                for idx, conn_result in enumerate(connection_results):
                    if effective_status == "pass":
                        pairs = self._get_all_passing_pairs_for_requirements(conn_result)
                    else:
                        pairs = self._get_all_pairs_for_requirements(conn_result)
                    all_pairs_by_interface[idx] = pairs
                
                # Build the chain summary
                chain_summary = {
                    "chain_index": chain.get("chain_index"),
                    "device_path": device_path,
                    "pattern": chain_pattern,
                    "status": effective_status,
                    "positions": []
                }
                
                # Analyze each position in the chain
                for pos_idx, device_name in enumerate(device_path):
                    is_named = device_name in named_device_names
                    is_distal = (pos_idx == 0)
                    is_proximal = (pos_idx == len(device_path) - 1)
                    
                    position_info = {
                        "position_index": pos_idx,
                        "device_name": device_name,
                        "is_named_device": is_named,
                        "is_distal": is_distal,
                        "is_proximal": is_proximal,
                        "constraints": {}
                    }
                    
                    if is_named:
                        position_info["constraints"] = self._get_named_device_constraints(
                            device_name, pos_idx, all_pairs_by_interface,
                            mentioned_ids, is_distal, is_proximal
                        )
                    else:
                        position_info["constraints"] = self._get_category_device_constraints(
                            pos_idx, all_pairs_by_interface, device_path,
                            is_distal, is_proximal
                        )
                    
                    chain_summary["positions"].append(position_info)
                
                results["chain_summaries"].append(chain_summary)
        
        # ============================================================
        # DISPATCH TO TEXT GENERATOR
        # Classification takes precedence over chain_sub_type
        # ============================================================
        if classification:
            results["llm_text_summaries"] = self._generate_text_from_classification(
                results["chain_summaries"],
                classification,
                named_device_names,
                categories
            )
        elif chain_sub_type == "COMPATIBILITY_CHECK":
            results["llm_text_summaries"] = self._generate_compatibility_check_text(results["chain_summaries"])
        elif chain_sub_type == "DEVICE_DISCOVERY":
            results["llm_text_summaries"] = self._generate_device_discovery_text(
                results["chain_summaries"], named_device_names, categories
            )
        elif chain_sub_type == "STACK_VALIDATION":
            results["llm_text_summaries"] = self._generate_chain_requirement_text(
                results["chain_summaries"], include_status=include_failing
            )
        else:
            results["llm_text_summaries"] = self._generate_chain_requirement_text(
                results["chain_summaries"], include_status=include_failing
            )
        
        return results

    def _generate_text_from_classification(self, chain_summaries: list, classification: dict,
                                            named_device_names: set, categories: list) -> list:
        """
        Dispatch to the appropriate text generator based on classification.
        
        Maps classification dimensions to existing text generators.
        """
        query_mode = classification.get("query_mode", "exploratory")
        response_framing = classification.get("response_framing", "neutral")
        query_structure = classification.get("query_structure", "two_device")
        
        # ============================================================
        # EXPLORATORY MODE
        # ============================================================
        if query_mode == "exploratory":
            if query_structure == "two_device":
                # Two devices - use compatibility check text
                return self._generate_compatibility_check_text(chain_summaries)
            
            elif query_structure == "multi_device":
                # Multi-device stack - use rich chain requirement text
                return self._generate_chain_requirement_text(chain_summaries, include_status=True)
            
            elif query_structure in ["named_plus_category", "named_plus_generic_spec"]:
                # Mix of named + category - use discovery text
                return self._generate_device_discovery_text(chain_summaries, named_device_names, categories)
            
            elif query_structure == "category_only":
                # Pure category filter - use discovery text
                return self._generate_device_discovery_text(chain_summaries, named_device_names, categories)
            
            else:
                # Fallback
                return self._generate_chain_requirement_text(chain_summaries, include_status=True)
        
        # ============================================================
        # COMPARISON MODE
        # ============================================================
        elif query_mode == "comparison":
            # Comparison - use compatibility check text (shows both options with pass/fail)
            return self._generate_compatibility_check_text(chain_summaries)
        
        # ============================================================
        # DISCOVERY MODE
        # ============================================================
        elif query_mode == "discovery":
            # Discovery - use discovery text
            return self._generate_device_discovery_text(chain_summaries, named_device_names, categories)
        
        # ============================================================
        # FALLBACK
        # ============================================================
        else:
            return self._generate_chain_requirement_text(chain_summaries, include_status=True)
