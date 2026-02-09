"""
Compatibility Evaluator - Core business logic for device compatibility checking.

Contains:
    - CompatEvaluatorMulti: OD/ID checking for a single device pair
    - ChainFlattenerMulti: Flattens results for clean output
    - ChainPairGenerator: Generates all ID pair combinations for chains

Ported from production code VERBATIM. Pure Python - no async, no broker.
"""

import copy
import json
import csv
import io
import re
from collections import defaultdict
from itertools import product

# =============================================================================
# CompatEvaluatorMulti (production code - verbatim)
# =============================================================================

class CompatEvaluatorMulti: 
    
    length_delta = 5

    compat_field_logic = {
        "compatibility_wire_max_outer-diameter_in": {
            "fields": ["specification_outer-diameter-distal_in", "specification_outer-diameter-proximal_in"],
            "logic_category": ["wire"],
            "operator": "<="
        },
        "compatibility_wire_max_outer-diameter_mm": {
            "fields": ["specification_outer-diameter-distal_mm", "specification_outer-diameter-proximal_mm"],
            "logic_category": ["wire"],
            "operator": "<="
        },
        "compatibility_wire_max_outer-diameter_F": {
            "fields": ["specification_outer-diameter-distal_F", "specification_outer-diameter-proximal_F"],
            "logic_category": ["wire"],
            "operator": "<="
        },
        "compatibility_catheter_max_outer-diameter_in": {
            "fields": ["specification_outer-diameter-distal_in", "specification_outer-diameter-proximal_in"],
            "logic_category": ["catheter"],
            "operator": "<="
        },
        "compatibility_catheter_max_outer-diameter_mm": {
            "fields": ["specification_outer-diameter-distal_mm", "specification_outer-diameter-proximal_mm"],
            "logic_category": ["catheter"],
            "operator": "<="
        },
        "compatibility_catheter_max_outer-diameter_F": {
            "fields": ["specification_outer-diameter-distal_F", "specification_outer-diameter-proximal_F"],
            "logic_category": ["catheter"],
            "operator": "<="
        },
        "compatibility_catheter_req_inner-diameter_in": {
            "fields": ["specification_inner-diameter_in"],
            "logic_category": ["catheter"],
            "operator": "="
        },
        "compatibility_catheter_req_inner-diameter_mm": {
            "fields": ["specification_inner-diameter_mm"],
            "logic_category": ["catheter"],
            "operator": "="
        },
        "compatibility_catheter_req_inner-diameter_F": {
            "fields": ["specification_inner-diameter_F"],
            "logic_category": ["catheter"],
            "operator": "="
        },
        "compatibility_guide_or_catheter_or_sheath_min_inner-diameter_in": {
            "fields": ["specification_inner-diameter_in"],
            "logic_category": ["catheter", "guide", "sheath"],
            "operator": ">="
        },
        "compatibility_guide_or_catheter_or_sheath_min_inner-diameter_mm": {
            "fields": ["specification_inner-diameter_mm"],
            "logic_category": ["catheter", "guide", "sheath"],
            "operator": ">="
        },
        "compatibility_guide_or_catheter_or_sheath_min_inner-diameter_F": {
            "fields": ["specification_inner-diameter_F"],
            "logic_category": ["catheter", "guide", "sheath"],
            "operator": ">="
        }
    }

    geometry_logic = {
        "specification_inner-diameter_in": {
            "fields": ["specification_outer-diameter-distal_in", "specification_outer-diameter-proximal_in"]
        },
        "specification_inner-diameter_mm": {
            "fields": ["specification_outer-diameter-distal_mm", "specification_outer-diameter-proximal_mm"]
        },
        "specification_inner-diameter_F": {
            "fields": ["specification_outer-diameter-distal_F", "specification_outer-diameter-proximal_F"]
        },
        "specification_length_cm": {
            "fields": ["specification_length_cm"]
        }
    }

    DIAMETER_THRESHOLDS = {
        'in': 0.003,
        'mm': 0.0762,
        'F': 0.23091
    }
    LENGTH_THRESHOLD_CM = 5

    def __init__(self, pair):
        self.pair = pair
        self.holder = []
        self.length_delta = 5

    def prep_inner(self, inner, outer):
        holder = []
        for compat_field, info in self.compat_field_logic.items():
            d = {}
            d['type'] = 'inner'
            d['id'] = inner['id']
            d['device_name'] = inner['device_name']
            d['logic_category'] = inner['logic_category']
            d['compatibility_field'] = compat_field
            d['compat_value'] = inner.get(compat_field)
            d['fit_logic'] = inner['fit_logic']
            fields = self.compat_field_logic[compat_field]['fields']

            t = []
            for field in fields:
                clone = copy.deepcopy(d)
                clone['other_id'] = outer['id']
                clone['other_device_name'] = outer['device_name']
                clone['other_logic_category'] = outer['logic_category']
                clone['specification_field'] = field
                clone['spec_value'] = outer.get(field)

                inner_logic_category_list = self.compat_field_logic[compat_field]['logic_category']
                outer_logic_category = outer['logic_category']
                outer_logic_category_list = outer_logic_category.split(" ")
                result = any(item in outer_logic_category_list for item in inner_logic_category_list)
                clone['applicable_category'] = result

                if 'outer-diameter' in field:
                    clone['applicable_spec_field'] = False
                else:
                    clone['applicable_spec_field'] = True

                t.append(clone)
            holder.extend(t)
        return holder
    
    def prep_outer(self, inner, outer):
        holder = []
        for compat_field, info in self.compat_field_logic.items():
            d = {}
            d['type'] = 'outer'
            d['id'] = outer['id']
            d['device_name'] = outer['device_name']
            d['logic_category'] = outer['logic_category']
            d['compatibility_field'] = compat_field
            d['compat_value'] = outer.get(compat_field)
            d['fit_logic'] = outer['fit_logic']
            fields = self.compat_field_logic[compat_field]['fields']

            t = []
            for field in fields:
                clone = copy.deepcopy(d)
                clone['other_id'] = inner['id']
                clone['other_device_name'] = inner['device_name']
                clone['other_logic_category'] = inner['logic_category']
                clone['specification_field'] = field
                clone['spec_value'] = inner.get(field)

                outer_logic_category_list = self.compat_field_logic[compat_field]['logic_category']
                inner_logic_category = inner['logic_category']
                inner_logic_category_list = inner_logic_category.split(" ")
                result = any(item in inner_logic_category_list for item in outer_logic_category_list)
                clone['applicable_category'] = result

                if 'inner-diameter' in field:
                    clone['applicable_spec_field'] = False
                else:
                    clone['applicable_spec_field'] = True

                t.append(clone)
            holder.extend(t)
        return holder
    
    def evluate(self):
        for row in self.holder:
            if row['applicable_spec_field'] == True and row['applicable_category'] == True:
                compat_val = row['compat_value']
                spec_val = row['spec_value']
                
                if compat_val is None or spec_val is None or compat_val == '' or spec_val == '':
                    row['status'] = 'NA'
                    continue
                    
                operator = self.compat_field_logic[row['compatibility_field']]['operator']
                if operator == '<=':
                    if float(spec_val) <= float(compat_val):
                        row['status'] = 'pass'
                    else:
                        row['status'] = 'fail'
                elif operator == '>=':
                    if float(spec_val) >= float(compat_val):
                        row['status'] = 'pass'
                    else:
                        row['status'] = 'fail'
                elif operator == '=':
                    compat_value_str = str(compat_val)
                    if '-' in compat_value_str:
                        compat_value_split = compat_value_str.split('-')
                        low = float(compat_value_split[0])
                        high = float(compat_value_split[1])
                        if float(spec_val) >= low and float(spec_val) <= high:
                            row['status'] = 'pass'
                        else:
                            row['status'] = 'fail'
                    else:
                        if float(spec_val) == float(compat_val):
                            row['status'] = 'pass'
                        else:
                            row['status'] = 'fail'
                else:
                    print('error')
            else:
                row['status'] = 'NA'
    
    def geometry_check(self, inner, outer):
        holder = []
        for compat_field, info in self.geometry_logic.items():
            d = {}
            d['type'] = 'outer'
            d['outer_device_id'] = outer['id']
            d['outer_device_name'] = outer['device_name']
            d['outer_device_logic_category'] = outer['logic_category']
            d['outer_device_specification_field'] = compat_field
            d['outer_device_specification_value'] = outer.get(compat_field)
            fields = self.geometry_logic[compat_field]['fields']

            t = []
            for field in fields:
                clone = copy.deepcopy(d)
                clone['inner_device_id'] = inner['id']
                clone['inner_device_name'] = inner['device_name']
                clone['inner_device_logic_category'] = inner['logic_category']
                clone['inner_device_specification_field'] = field
                clone['inner_device_specification_value'] = inner.get(field)
                t.append(clone)
            holder.extend(t)
        return holder
    
    def geometry_math(self, geometry_holder):
        for g in geometry_holder:
            outer_val = g['outer_device_specification_value']
            inner_val = g['inner_device_specification_value']
            
            if outer_val is None or inner_val is None or outer_val == '' or inner_val == '':
                g['difference'] = 'NA'
            else:
                if 'length' not in g['outer_device_specification_field']:
                    delta = float(outer_val) - float(inner_val)
                    g['difference'] = delta
                else:
                    delta = float(inner_val) - float(outer_val)
                    g['difference'] = delta
        return geometry_holder

    def compatibility_grade(self):
        status_list = [r['status'] for r in self.holder]
        status_set = list(set(status_list))

        if 'pass' in status_set:
            supporting_rows = []
            for r in self.holder:
                if r['status'] == 'pass':
                    if r['type'] == 'outer':
                        note = (
                            f"The outer device named {r['device_name']} compatibility "
                            f"with the inner device named {r['other_device_name']} has passed!. "
                            f" The outer device has a compatibility field of {r['compatibility_field']} "
                            f"with a value of {r['compat_value']} and the inner device has a "
                            f"specification field of {r['specification_field']} with a value of "
                            f"{r['spec_value']} - which makes is compatible."
                        )
                    else:
                        note = (
                            f"The inner device named {r['device_name']} compatibility "
                            f"with the outer device named {r['other_device_name']} has passed!. "
                            f" The inner device has a compatibility field of {r['compatibility_field']} "
                            f"with a value of {r['compat_value']} but the outer device has a "
                            f"specification field of {r['specification_field']} with a value of "
                            f"{r['spec_value']} - which makes is compatible."
                        )
                    r['note'] = note
                    supporting_rows.append(r)

            self.pair['compatibility_status'] = {}
            self.pair['compatibility_status']['status'] = 'pass'
            self.pair['compatibility_status']['supporting_rows'] = supporting_rows

        elif 'fail' in status_set:
            supporting_rows = []
            for r in self.holder:
                if r['status'] == 'fail':
                    if r['type'] == 'outer':
                        note = (
                            f"The outer device named {r['device_name']} has a compatibility "
                            f"issue with the inner device named {r['other_device_name']}. "
                            f" The outer device has a compatibility field of {r['compatibility_field']} "
                            f"with a value of {r['compat_value']} but the inner device has a "
                            f"specification field of {r['specification_field']} with a value of "
                            f"{r['spec_value']}."
                        )
                    else:
                        note = (
                            f"The inner device named {r['device_name']} has a compatibility "
                            f"issue with the outer device named {r['other_device_name']}. "
                            f" The inner device has a compatibility field of {r['compatibility_field']} "
                            f"with a value of {r['compat_value']} but the outer device has a "
                            f"specification field of {r['specification_field']} with a value of "
                            f"{r['spec_value']}."
                        )
                    r['note'] = note
                    supporting_rows.append(r)

            self.pair['compatibility_status'] = {}
            self.pair['compatibility_status']['status'] = 'fail'
            self.pair['compatibility_status']['supporting_rows'] = supporting_rows

        elif 'NA' in status_set and len(status_set) == 1:
            supporting_rows = [r for r in self.holder]
            self.pair['compatibility_status'] = {}
            self.pair['compatibility_status']['status'] = 'NA'
            self.pair['compatibility_status']['notes'] = [
                "All the fields were NA which means either the devices were not "
                "the correct device category or the compatibility field was not "
                "applicable or the compatibility field and/or the specification "
                "field were null"
            ]
            self.pair['compatibility_status']['supporting_rows'] = supporting_rows

    def _get_unit_type(self, field_name):
        if field_name.endswith('_in'):
            return 'in'
        elif field_name.endswith('_mm'):
            return 'mm'
        elif field_name.endswith('_F'):
            return 'F'
        elif field_name.endswith('_cm'):
            return 'cm'
        return None

    def _is_length_field(self, field_name):
        return 'length' in field_name or field_name.endswith('_cm')

    def _grade_single_geometry_result(self, r):
        inner_field = r['inner_device_specification_field']
        unit_type = self._get_unit_type(inner_field)
        if r['difference'] == 'NA':
            return 'NA'
        delta = float(r['difference'])
        if self._is_length_field(inner_field):
            threshold = self.LENGTH_THRESHOLD_CM
        else:
            threshold = self.DIAMETER_THRESHOLDS.get(unit_type, 0)
        if delta >= threshold:
            return 'pass'
        elif delta > 0 and delta < threshold:
            return 'warning'
        elif delta <= 0:
            return 'fail'
        else:
            return 'NA'

    def _generate_geometry_note(self, r, is_length=False):
        inner_field = r['inner_device_specification_field']
        unit_type = self._get_unit_type(inner_field)
        status = r['status']
        diff = r['difference']
        if is_length:
            threshold = self.LENGTH_THRESHOLD_CM
            if status == 'pass':
                return f"The length of the inner device was {diff} cm longer than the outer device, which is >= {threshold} cm. That is why it passed."
            elif status == 'warning':
                return f"The length of the inner device was {diff} cm longer than the outer device, which is > 0 and < {threshold} cm. That is why it has a warning."
            elif status == 'fail':
                return f"The length of the inner device was {diff} cm relative to the outer device, which is <= 0. That is why it failed."
        else:
            threshold = self.DIAMETER_THRESHOLDS.get(unit_type, 0)
            if status == 'pass':
                return f"The space between the outer diameter and the inner diameter was {diff} {unit_type} which is >= {threshold}. That is why it passed."
            elif status == 'warning':
                return f"The space between the outer diameter and the inner diameter was {diff} {unit_type} which is > 0 and < {threshold}. That is why it has a warning."
            elif status == 'fail':
                return f"The space between the outer diameter and the inner diameter was {diff} {unit_type} which is <= 0. That is why it failed."
        return None

    def _grade_geometry_subset(self, results, subset_type):
        if not results:
            return {'status': 'NA', 'notes': [f'No {subset_type} results to evaluate'], 'supporting_rows': []}
        status_list = [r['status'] for r in results]
        status_set = set(status_list)
        if subset_type == 'diameter':
            pass_count = sum(1 for s in status_list if s == 'pass')
            warning_count = sum(1 for s in status_list if s == 'warning')
            if 'fail' not in status_set and pass_count < 2 and (pass_count + warning_count) < 2:
                if status_set == {'NA'}:
                    return {'status': 'NA', 'notes': ['Not enough diameter data to evaluate'], 'supporting_rows': results}
        is_length = (subset_type == 'length')
        for r in results:
            if r['status'] != 'NA':
                r['note'] = self._generate_geometry_note(r, is_length=is_length)
        if 'fail' in status_set:
            failing_rows = [r for r in results if r['status'] == 'fail']
            return {'status': 'fail', 'supporting_rows': failing_rows}
        elif 'pass' in status_set:
            has_warning = 'warning' in status_set
            relevant_rows = [r for r in results if r['status'] in ('pass', 'warning')]
            return {'status': 'pass_with_warning' if has_warning else 'pass', 'supporting_rows': relevant_rows}
        elif 'warning' in status_set:
            warning_rows = [r for r in results if r['status'] == 'warning']
            return {'status': 'warning', 'supporting_rows': warning_rows}
        else:
            return {'status': 'NA', 'notes': [f'All {subset_type} fields were NA - specification values may be null'], 'supporting_rows': results}

    def _combine_geometry_statuses(self, diameter_status, length_status):
        d_stat = diameter_status.get('status', 'NA')
        l_stat = length_status.get('status', 'NA')
        if d_stat == 'fail' or l_stat == 'fail':
            return 'fail'
        if d_stat == 'NA' and l_stat == 'NA':
            return 'NA'
        if 'warning' in d_stat or 'warning' in l_stat:
            return 'pass_with_warning'
        if d_stat == 'pass' or l_stat == 'pass':
            return 'pass'
        return 'NA'

    def geometry_grade(self):
        geo_results = self.pair.get('geometry_results', [])
        diameter_results = []
        length_results = []
        for r in geo_results:
            r['status'] = self._grade_single_geometry_result(r)
            if self._is_length_field(r['inner_device_specification_field']):
                length_results.append(r)
            else:
                diameter_results.append(r)
        diameter_status = self._grade_geometry_subset(diameter_results, 'diameter')
        length_status = self._grade_geometry_subset(length_results, 'length')
        overall_geo_status = self._combine_geometry_statuses(diameter_status, length_status)
        self.pair['geometry_status'] = {
            'status': overall_geo_status,
            'diameter_status': diameter_status,
            'length_status': length_status,
            'supporting_rows': geo_results
        }

    def overall_grade(self):
        compatibility_status = self.pair.get('compatibility_status', {})
        geometry_status = self.pair.get('geometry_status', {})
        inner_fit_logic = self.pair['inner'].get('fit_logic', 'compat')
        outer_fit_logic = self.pair['outer'].get('fit_logic', 'compat')
        diameter_stat = geometry_status.get('diameter_status', {}).get('status', 'NA')
        length_stat = geometry_status.get('length_status', {}).get('status', 'NA')
        geo_stat = geometry_status.get('status', 'NA')

        if inner_fit_logic == 'math' and outer_fit_logic == 'math':
            logic_type = 'math'
            if geo_stat == 'fail':
                overall_status = 'fail'
            elif geo_stat == 'pass_with_warning':
                overall_status = 'pass_with_warning'
            elif geo_stat == 'pass':
                overall_status = 'pass'
            else:
                overall_status = 'fail'
        else:
            logic_type = 'compat'
            compat_stat = compatibility_status.get('status', 'NA')

            if compat_stat == 'fail':
                overall_status = 'fail'
            elif compat_stat == 'NA':
                logic_type = 'geometry_fallback'
                if 'pass' in diameter_stat and 'pass' in length_stat:
                    if 'warning' in diameter_stat or 'warning' in length_stat:
                        overall_status = 'pass_with_warning'
                    else:
                        overall_status = 'pass'
                else:
                    overall_status = 'fail'
            elif compat_stat == 'pass':
                overall_status = 'pass'
                if length_stat == 'fail':
                    overall_status = 'fail'
                    logic_type = 'compat+length_fail'
                elif diameter_stat == 'fail':
                    overall_status = 'pass_with_warning'
                    logic_type = 'compat+geometry_warning'
                elif 'warning' in diameter_stat or 'warning' in length_stat:
                    overall_status = 'pass_with_warning'
                    logic_type = 'compat+geometry_warning'
            else:
                overall_status = compat_stat

        self.pair['overall_status'] = {
            "status": overall_status,
            "logic_type": logic_type,
            "compatibility_status": compatibility_status,
            "geometry_status": geometry_status
        }

    def go(self):
        inner = self.pair['inner']
        outer = self.pair['outer']
        inner_holder = self.prep_inner(inner=inner, outer=outer)
        outer_holder = self.prep_outer(inner=inner, outer=outer)
        self.holder.extend(inner_holder)
        self.holder.extend(outer_holder)
        self.evluate()
        self.pair['compatibility_results'] = self.holder
        geometry_holder = self.geometry_check(inner=inner, outer=outer)
        geometry_holder = self.geometry_math(geometry_holder)
        self.pair['geometry_results'] = geometry_holder
        self.compatibility_grade()
        self.geometry_grade()
        self.overall_grade()
        return self.pair



# =============================================================================
# ChainFlattenerMulti
# =============================================================================

class ChainFlattenerMulti:
    """Flattens chain evaluation data into a list of dictionaries."""

    UNIT_PRIORITY = {'_in': 1, '_mm': 2, '_F': 3}

    def __init__(self, chains):
        self.chains = chains

    def flatten(self):
        data = []
        for chain in self.chains:
            chain_index = chain.get('chain_index')
            for path_obj in chain.get('paths', []):
                path_str = ' - '.join(path_obj.get('path', []))
                for conn_idx, connection in enumerate(path_obj.get('connections', []), start=1):
                    inner_device = connection.get('inner_device', '')
                    outer_device = connection.get('outer_device', '')
                    for pair in connection.get('processed_pairs', []):
                        flat_record = self._flatten_pair(chain_index, path_str, conn_idx, f"{inner_device} - {outer_device}", pair)
                        data.append(flat_record)
        return {'data': data}

    def _flatten_pair(self, chain_index, path_str, connection_index, link, pair):
        inner = pair.get('inner', {})
        outer = pair.get('outer', {})
        overall_status = pair.get('overall_status', {})
        logic_type = overall_status.get('logic_type', '')
        status = overall_status.get('status', '')

        if 'pass' in status.lower():
            compatibility_result = 'Compatible'
        elif status == 'fail':
            compatibility_result = 'Not Compatible'
        else:
            compatibility_result = status

        if logic_type == 'compat':
            evaluation_method = 'IFU'
        elif logic_type == 'math':
            evaluation_method = 'Specifications'
        else:
            evaluation_method = logic_type

        return {
            'construct_option_id': chain_index,
            'construct_devices': path_str,
            'interface_order': connection_index,
            'device_to_device_connection': link,
            'distal_device_family': inner.get('product_name', ''),
            'distal_device_model': inner.get('device_name', ''),
            'proximal_device_family': outer.get('product_name', ''),
            'proximal_device_model': outer.get('device_name', ''),
            'evaluation_method': evaluation_method,
            'compatibility_result': compatibility_result,
            # Enriched spec fields for UI
            'distal_od_in': inner.get('specification_outer-diameter-distal_in', ''),
            'distal_id_in': inner.get('specification_inner-diameter_in', ''),
            'distal_length_cm': inner.get('specification_length_cm', ''),
            'distal_manufacturer': inner.get('manufacturer', ''),
            'proximal_od_in': outer.get('specification_outer-diameter-distal_in', ''),
            'proximal_id_in': outer.get('specification_inner-diameter_in', ''),
            'proximal_length_cm': outer.get('specification_length_cm', ''),
            'proximal_manufacturer': outer.get('manufacturer', ''),
            'logic_type': logic_type,
        }


# =============================================================================
# ChainPairGenerator (extracted from CreateChainsAgentMulti)
# =============================================================================

class ChainPairGenerator:
    """Generates all ID pair combinations for chain compatibility checking."""

    def generate_chain_pairs(self, chains_to_check, devices, database):
        results = []
        for chain_idx, chain in enumerate(chains_to_check, start=1):
            sequence = chain.get("sequence", [])
            levels = chain.get("levels", [])
            if len(sequence) < 2 or len(sequence) != len(levels):
                continue

            all_path_results = []
            path = sequence

            path_connections = []
            for i in range(len(sequence) - 1):
                inner_device = sequence[i]
                outer_device = sequence[i + 1]
                inner_ids = devices.get(inner_device, {}).get("ids", [])
                outer_ids = devices.get(outer_device, {}).get("ids", [])

                if not inner_ids:
                    print(f"  [WARNING] generate_chain_pairs: No IDs for inner device '{inner_device}'. "
                          f"Available: {list(devices.keys())[:10]}")
                if not outer_ids:
                    print(f"  [WARNING] generate_chain_pairs: No IDs for outer device '{outer_device}'. "
                          f"Available: {list(devices.keys())[:10]}")

                inner_level = levels[i]
                outer_level = levels[i + 1]

                if inner_level == outer_level:
                    connection_type = "intra_level"
                    connection_str = f"{inner_level}<->{outer_level}"
                else:
                    connection_type = "inter_level"
                    connection_str = f"{inner_level}->{outer_level}"

                pairs = []
                for inner_id, outer_id in product(inner_ids, outer_ids):
                    pair_info = {
                        "pair_key": f"{inner_id}-{outer_id}",
                        "inner": database.get(str(inner_id), database.get(inner_id, {})),
                        "outer": database.get(str(outer_id), database.get(outer_id, {})),
                        "inner_id": inner_id,
                        "outer_id": outer_id,
                        "inner_name": inner_device,
                        "outer_name": outer_device
                    }
                    pairs.append(pair_info)

                path_connections.append({
                    "connection": connection_str,
                    "connection_type": connection_type,
                    "inner_device": inner_device,
                    "outer_device": outer_device,
                    "pairs": pairs
                })

            all_path_results.append({
                "path_index": 0,
                "path": path,
                "connections": path_connections
            })

            results.append({
                "chain_index": chain_idx,
                "active_levels": levels,
                "sequence": sequence,
                "levels": levels,
                "total_paths": 1,
                "paths": all_path_results
            })
        return results

    def process_chain_results(self, chain_results):
        processed_results = []
        for chain in chain_results:
            processed_chain = {
                "chain_index": chain["chain_index"],
                "active_levels": chain["active_levels"],
                "total_paths": chain["total_paths"],
                "paths": []
            }
            for path in chain["paths"]:
                processed_path = {
                    "path_index": path["path_index"],
                    "path": path["path"],
                    "connections": []
                }
                for connection in path["connections"]:
                    processed_connection = {
                        "connection": connection["connection"],
                        "connection_type": connection["connection_type"],
                        "inner_device": connection["inner_device"],
                        "outer_device": connection["outer_device"]
                    }
                    processed_pairs = []
                    for pair in connection["pairs"]:
                        evaluator = CompatEvaluatorMulti(copy.deepcopy(pair))
                        processed_pair = evaluator.go()
                        processed_pairs.append(processed_pair)
                    processed_connection["processed_pairs"] = processed_pairs
                    processed_path["connections"].append(processed_connection)
                processed_chain["paths"].append(processed_path)
            processed_results.append(processed_chain)
        return processed_results

    def analyze_chains(self, processed_results):
        from medsync_ai_v2.engines.chain_engine.chain_analyzer import ChainAnalyzerMulti
        analyzer = ChainAnalyzerMulti(processed_results)
        return analyzer.get_summary()

    def flatten_chains(self, chains):
        flattener = ChainFlattenerMulti(chains)
        return flattener.flatten()


