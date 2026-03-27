# Database Engine

## Role

The database engine handles all **direct device lookups, specification queries, filtered searches, and comparisons** against the in-memory device database. It does NOT perform compatibility analysis (that is the chain engine's job) and does NOT search IFU/documentation (that is the vector engine's job).

**When to use**: spec lookups, device searches by dimension/manufacturer/category, device comparisons, extracting specific field values.

**When NOT to use**: compatibility checks ("Can I use X with Y?"), IFU/documentation lookups, clinical guidelines.

## Architecture

```
User Query
    |
    v
QuerySpecAgent (LLM, fast model)
    |  Generates structured JSON query spec
    v
QueryExecutor (Pure Python)
    |  Executes query spec against DATABASE
    v
DatabaseOutputAgent (LLM, streaming)
    |  Formats results into natural language
    v
SSE Response
```

**Filter path** (used by query planner): Bypasses the LLM QuerySpecAgent entirely. The orchestrator's query planner provides a pre-built query spec with `input_type: "filter"`, which goes directly to QueryExecutor.

---

## Database Schema

Each device record in DATABASE is a flat dict keyed by numeric string ID (e.g., `"56"`).

### Identity Fields

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `product_name` | string | Commercial product name | "Headway 21" |
| `device_name` | string | Full device descriptor | "Headway 21 Microcatheter" |
| `manufacturer` | string | Company name | "MicroVention/Terumo" |
| `id` | string | Unique numeric ID | "56" |

### Classification Fields

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `category_type` | string | Precise device type | "microcatheter" |
| `conical_category` | string | Hierarchy level (L0-L5, LW) | "L3" |
| `logic_category` | string | Compatibility logic grouping | "microcatheter" |
| `fit_logic` | string | Fit rule type for compat evaluation | "OD_ID" |

### Dimension Fields

| Field | Type | Unit | Description |
|-------|------|------|-------------|
| `specification_inner-diameter_in` | float | inches | Inner diameter |
| `specification_inner-diameter_mm` | float | mm | Inner diameter |
| `specification_inner-diameter_F` | float | French | Inner diameter |
| `specification_outer-diameter-distal_in` | float | inches | Outer diameter (distal tip) |
| `specification_outer-diameter-distal_mm` | float | mm | Outer diameter (distal tip) |
| `specification_outer-diameter-distal_F` | float | French | Outer diameter (distal tip) |
| `specification_outer-diameter-proximal_in` | float | inches | Outer diameter (proximal) |
| `specification_outer-diameter-proximal_mm` | float | mm | Outer diameter (proximal) |
| `specification_outer-diameter-proximal_F` | float | French | Outer diameter (proximal) |
| `specification_length_cm` | float | cm | Working length |

### Compatibility Rule Fields (used by chain engine)

| Field | Type | Description |
|-------|------|-------------|
| `wire_max_OD` | float | Max guidewire OD that fits inside |
| `catheter_max_OD` | float | Max catheter OD that fits inside |
| `catheter_required_ID` | float | Min catheter ID needed for this device |
| `guide_min_ID` | float | Min guide catheter ID needed |
| `catheter_min_ID` | float | Min catheter ID needed |
| `sheath_min_ID` | float | Min sheath ID needed |

---

## Category System

Devices are classified by `category_type` (precise) and `conical_category` (hierarchy level).

### Category Type Values

| category_type | Description | L-Level |
|---|---|---|
| `sheath` | Access sheaths | L0 |
| `balloon_guide_catheter` | Balloon guide catheters (BGC) | L1 |
| `guide_intermediate_catheter` | Guide/intermediate dual-role catheters | L0, L1 |
| `intermediate_catheter` | Standard intermediate catheters | L1, L2 |
| `delivery_intermediate_catheter` | Delivery intermediates | L2 |
| `aspiration_intermediate_catheter` | Aspiration intermediates | L2 |
| `distal_access_catheter` | Distal access catheters (DAC) | L2 |
| `aspiration_system_component` | Aspiration system components | L2 |
| `microcatheter` | Standard microcatheters | L3 |
| `balloon_microcatheter` | Balloon microcatheters | L3 |
| `flow_dependent_microcatheter` | Flow-dependent microcatheters | L3 |
| `delivery_catheter` | Delivery catheters | L3 |
| `stent_system` | Stent systems | L4 |
| `stent_retriever` | Stent retrievers | L5 |
| `guidewire` | Guidewires | LW |

### User-Facing Category Mappings

When users mention a device category, the executor maps it to the correct `category_type` values:

| User Term | Matches category_type values |
|---|---|
| microcatheter / micro | microcatheter, balloon_microcatheter, flow_dependent_microcatheter, delivery_catheter |
| aspiration / aspiration_catheter | aspiration_intermediate_catheter, distal_access_catheter, aspiration_system_component |
| intermediate / intermediate_catheter | guide_intermediate_catheter, intermediate_catheter, delivery_intermediate_catheter, aspiration_intermediate_catheter |
| bgc / balloon_guide_catheter | balloon_guide_catheter |
| guide / guide_catheter | balloon_guide_catheter, guide_intermediate_catheter |
| sheath | sheath |
| dac / distal_access_catheter | distal_access_catheter |
| stent / stent_retriever | stent_system, stent_retriever |
| wire / guidewire | guidewire |
| catheter (broad) | All L1-L3 types (falls back to conical_category) |

### Conical Category Hierarchy

```
L0 (outermost)  — Sheaths, guide catheters
  L1             — BGC, guide/intermediate catheters
    L2           — Aspiration, DAC, intermediate catheters
      L3         — Microcatheters, delivery catheters
        L4       — Stent systems
          L5     — Stent retrievers
        LW       — Guidewires
```

Higher L-number = goes INSIDE lower L-number.

---

## QueryExecutor Actions Reference

### get_device_specs
**Purpose**: Retrieve full specs for specific device IDs.
**Input**: `device_ids: string[]`
**Output**: Array of device spec objects with identity + specifications.

### filter_by_spec
**Purpose**: Find devices matching a category and/or dimension filters.
**Input**: `category: string` (optional), `filters: [{field, operator, value}]` (optional)
**Output**: Array of matching device specs.
**Category matching**: Uses `category_type` first (precise), falls back to `conical_category` for broad terms.

### find_compatible
**Purpose**: Find devices that physically fit with a source device at a single connection point.
**Input**: `source_device_ids: string[]`, `target_category: string`, `direction: "inner"|"outer"`, `check_length: boolean`
**Output**: Array of compatible device specs with `compatibility_reason`.
**Note**: This is a simplified OD/ID math check. For full compatibility analysis with all rules, use the chain engine.

### compare_devices
**Purpose**: Pull specs for multiple devices side by side.
**Input**: `device_groups: string[][]` — groups of device IDs to compare.
**Output**: Array of all device specs (flattened from all groups).

### extract_value
**Purpose**: Extract a specific field value from a previous step's results.
**Input**: `from_step: string`, `field: string`, `aggregation: "min"|"max"|"avg"|"first"`
**Output**: Single value (number or string).

### search_both_id_od
**Purpose**: Search for devices by a dimension value when it's ambiguous whether the user means ID or OD.
**Input**: `category: string`, `dimension_value: float`, `dimension_operator: string`, `additional_filters: [{field, operator, value}]`
**Output**: `{id_matches: [], od_matches: [], dimension_value, dimension_operator}`

### intersect
**Purpose**: Find devices common to multiple result sets.
**Input**: `from_steps: string[]`
**Output**: Array of devices present in ALL referenced steps.

### union
**Purpose**: Combine multiple result sets (deduplicated by device_id).
**Input**: `from_steps: string[]`
**Output**: Array of unique devices from all referenced steps.

---

## Field Name Mapping

The QuerySpecAgent uses friendly field names. The executor maps them to raw database fields:

| Friendly Name | Database Field |
|---|---|
| ID_in | specification_inner-diameter_in |
| ID_mm | specification_inner-diameter_mm |
| ID_Fr | specification_inner-diameter_F |
| OD_distal_in | specification_outer-diameter-distal_in |
| OD_distal_mm | specification_outer-diameter-distal_mm |
| OD_distal_Fr | specification_outer-diameter-distal_F |
| OD_proximal_in | specification_outer-diameter-proximal_in |
| OD_proximal_mm | specification_outer-diameter-proximal_mm |
| length_cm | specification_length_cm |
| product_name | product_name |
| manufacturer | manufacturer |
| conical_category | conical_category |
| category_type | category_type |

---

## Common Query Patterns

| User Query | Action | Notes |
|---|---|---|
| "What is the OD of Vecta 46?" | get_device_specs | Simple spec lookup |
| "What microcatheters are available?" | filter_by_spec (category only) | No dimension filters needed |
| "Catheters with ID > .074" | filter_by_spec with filters | Category + dimension filter |
| "Show me Medtronic aspiration catheters" | filter_by_spec with manufacturer filter | Category + string filter |
| "I need a .017 catheter" | search_both_id_od | Ambiguous dimension |
| "Compare Vecta 46 and Sofia" | compare_devices | Side-by-side specs |
| "What wire fits inside SL-10?" | find_compatible (direction=inner) | Single-point compatibility |
| "What is the min ID across these devices?" | extract_value (aggregation=min) | Value extraction from prior step |
