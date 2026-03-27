## Strategy Patterns

### filter_then_compat
Use when the query combines attribute filtering with compatibility checking.
Example: "What Medtronic catheters can I use with an atlas stent?"
1. database_engine: filter by manufacturer + category
2. chain_engine: check each filtered device against named device(s)

### filter_only
Use when the query only needs database filtering (no compatibility).
Example: "Show me all Stryker intermediate catheters"
1. database_engine: filter by constraints

### compat_only
Use when the query only needs compatibility checking (no filtering).
Example: "Can I use Solitaire with Vecta?"
→ This should NOT reach the planner (no constraints). But if it does, just use chain_engine.

### compat_then_docs
Use when the query combines compatibility checking with documentation lookup.
Example: "What Stryker microcatheters work with Solitaire, and what does the IFU say about Solitaire deployment?"
1. database_engine: filter by manufacturer + category
2. chain_engine: check filtered devices against named device(s)
3. vector_engine: search IFU/510(k) for deployment information

### filter_then_docs
Use when the query combines filtering with documentation (no compatibility).
Example: "Show me Medtronic stent retrievers and what are the IFU contraindications?"
1. database_engine: filter by constraints
2. vector_engine: search documents for the asked information

### docs_only
Use when the query only needs document search (no filtering or compatibility).
Example: "What does the IFU say about Solitaire deployment temperature?"
→ This should NOT reach the planner (single intent). But if it does, just use vector_engine.

## Examples

### "What Medtronic catheters can I use with an atlas stent?"
Devices found: atlas stent. Categories: catheter. Constraints: manufacturer=Medtronic.
```json
{
    "strategy": "filter_then_compat",
    "steps": [
        {"step_id": "s1", "engine": "database", "action": "filter_by_spec", "category": "catheter", "filters": [{"field": "manufacturer", "operator": "contains", "value": "Medtronic"}], "store_as": "filtered_devices", "depends_on": []},
        {"step_id": "s2", "engine": "chain", "action": "compat_check", "inject_devices_from": "s1", "named_devices": ["atlas stent"], "store_as": "compat_results", "depends_on": ["s1"]}
    ],
    "output_agent": "chain_output_agent"
}
```

### "Show me all Stryker stent retrievers"
Devices found: none. Categories: stent retriever. Constraints: manufacturer=Stryker.
```json
{
    "strategy": "filter_only",
    "steps": [
        {"step_id": "s1", "engine": "database", "action": "filter_by_spec", "category": "stent_retriever", "filters": [{"field": "manufacturer", "operator": "contains", "value": "Stryker"}], "store_as": "filtered_devices", "depends_on": []}
    ],
    "output_agent": "database_output_agent"
}
```

### "What Penumbra aspiration catheters work with Solitaire through Neuron MAX?"
Devices found: Solitaire, Neuron MAX. Categories: aspiration catheter. Constraints: manufacturer=Penumbra.
```json
{
    "strategy": "filter_then_compat",
    "steps": [
        {"step_id": "s1", "engine": "database", "action": "filter_by_spec", "category": "aspiration", "filters": [{"field": "manufacturer", "operator": "contains", "value": "Penumbra"}], "store_as": "filtered_devices", "depends_on": []},
        {"step_id": "s2", "engine": "chain", "action": "compat_check", "inject_devices_from": "s1", "named_devices": ["Solitaire", "Neuron MAX"], "store_as": "compat_results", "depends_on": ["s1"]}
    ],
    "output_agent": "chain_output_agent"
}
```

### "What Stryker microcatheters work with Solitaire, and what does the IFU say about deployment?"
Devices found: Solitaire. Categories: microcatheter. Constraints: manufacturer=Stryker.
```json
{
    "strategy": "compat_then_docs",
    "steps": [
        {"step_id": "s1", "engine": "database", "action": "filter_by_spec", "category": "microcatheter", "filters": [{"field": "manufacturer", "operator": "contains", "value": "Stryker"}], "store_as": "filtered_devices", "depends_on": []},
        {"step_id": "s2", "engine": "chain", "action": "compat_check", "inject_devices_from": "s1", "named_devices": ["Solitaire"], "store_as": "compat_results", "depends_on": ["s1"]},
        {"step_id": "s3", "engine": "vector", "action": "search_documents", "query_focus": "Solitaire stent retriever deployment procedure through microcatheter", "named_devices": ["Solitaire"], "store_as": "doc_results", "depends_on": []}
    ],
    "output_agent": "synthesis_output_agent"
}
```