"""
Query Planner Agent

Lightweight LLM agent that generates multi-engine execution plans.
Only invoked when equipment_extraction detects constraints (manufacturer, etc.)
that require coordinating multiple engines (e.g., database filter → chain compat).

For simple queries without constraints, the orchestrator uses direct routing
and this agent is never called.
"""

import json
from medsync_ai_v2.base_agent import LLMAgent


PLANNER_SYSTEM_MESSAGE = """You are a query planner for a medical device system. You decide HOW to answer a query by selecting which engines to use and in what order.

## Available Engines

### database_engine
Queries a structured database of medical devices. Best for:
- Filtering devices by attributes (manufacturer, category, specs)
- Looking up device specifications
- Finding devices matching criteria

Actions:
- **filter_by_spec**: Filter devices by category and/or attribute filters
  - category: "catheter", "microcatheter", "wire", "sheath", "stent_retriever", "intermediate_catheter", "aspiration", "guide_catheter"
  - filters: [{"field": "manufacturer", "operator": "contains", "value": "Medtronic"}, {"field": "ID_in", "operator": ">=", "value": 0.021}]
- **get_device_specs**: Look up specs for specific device IDs
- **find_compatible**: Find devices compatible at a single connection point

### chain_engine
Evaluates full compatibility chains between multiple devices. Best for:
- Checking if Device A works with Device B (or through Device C)
- Building and testing complete device stacks (L0→L1→L2→L3→L4→L5)
- Multi-device compatibility with mathematical evaluation

Takes pre-resolved devices (name → IDs + conical_category) and tests all junctions.

### vector_engine
Searches IFU/510(k) document chunks using semantic search. Best for:
- IFU (Instructions for Use) questions
- 510(k) clearance information
- Manufacturer instructions, indications, contraindications
- Deployment procedures, warnings, guidelines from official documents

Actions:
- **search_documents**: Semantic search over IFU/510(k) vector store
  - Uses device IDs from named_devices for metadata filtering
  - Falls back to pure semantic search if no device IDs available

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

## Output Format

Return ONLY valid JSON:
{
    "strategy": "filter_then_compat",
    "steps": [
        {
            "step_id": "s1",
            "engine": "database",
            "action": "filter_by_spec",
            "category": "catheter",
            "filters": [{"field": "manufacturer", "operator": "contains", "value": "Medtronic"}],
            "store_as": "filtered_devices"
        },
        {
            "step_id": "s2",
            "engine": "chain",
            "action": "compat_check",
            "inject_devices_from": "s1",
            "named_devices": ["atlas stent"],
            "store_as": "compat_results"
        }
    ],
    "output_agent": "chain_output_agent"
}

## Rules

1. The "category" in filter_by_spec must match a valid device category
2. "named_devices" are device names the user mentioned — they already have IDs resolved
3. "inject_devices_from" tells the executor to transform database results into chain engine format and merge with named devices
4. For filter_only strategies, use "database_output_agent" as the output_agent
5. For strategies ending with chain_engine, use "chain_output_agent"
6. For strategies ending with vector_engine (docs_only), use "vector_output_agent"
7. For strategies combining chain + vector, use "synthesis_output_agent"
8. "query_focus" for vector steps should be a focused but context-aware query — include the relevant clinical context (e.g., "Solitaire stent retriever deployment procedure through microcatheter"), NOT just the topic keyword (e.g., "deployment")
9. Always include store_as for each step
10. Keep plans minimal — use the fewest steps needed

## Examples

### "What Medtronic catheters can I use with an atlas stent?"
Devices found: atlas stent. Categories: catheter. Constraints: manufacturer=Medtronic.
```json
{
    "strategy": "filter_then_compat",
    "steps": [
        {"step_id": "s1", "engine": "database", "action": "filter_by_spec", "category": "catheter", "filters": [{"field": "manufacturer", "operator": "contains", "value": "Medtronic"}], "store_as": "filtered_devices"},
        {"step_id": "s2", "engine": "chain", "action": "compat_check", "inject_devices_from": "s1", "named_devices": ["atlas stent"], "store_as": "compat_results"}
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
        {"step_id": "s1", "engine": "database", "action": "filter_by_spec", "category": "stent_retriever", "filters": [{"field": "manufacturer", "operator": "contains", "value": "Stryker"}], "store_as": "filtered_devices"}
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
        {"step_id": "s1", "engine": "database", "action": "filter_by_spec", "category": "aspiration", "filters": [{"field": "manufacturer", "operator": "contains", "value": "Penumbra"}], "store_as": "filtered_devices"},
        {"step_id": "s2", "engine": "chain", "action": "compat_check", "inject_devices_from": "s1", "named_devices": ["Solitaire", "Neuron MAX"], "store_as": "compat_results"}
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
        {"step_id": "s1", "engine": "database", "action": "filter_by_spec", "category": "microcatheter", "filters": [{"field": "manufacturer", "operator": "contains", "value": "Stryker"}], "store_as": "filtered_devices"},
        {"step_id": "s2", "engine": "chain", "action": "compat_check", "inject_devices_from": "s1", "named_devices": ["Solitaire"], "store_as": "compat_results"},
        {"step_id": "s3", "engine": "vector", "action": "search_documents", "query_focus": "Solitaire stent retriever deployment procedure through microcatheter", "named_devices": ["Solitaire"], "store_as": "doc_results"}
    ],
    "output_agent": "synthesis_output_agent"
}
```
""".strip()


class QueryPlanner(LLMAgent):
    """Lightweight planner that generates multi-engine execution plans."""

    def __init__(self):
        super().__init__(name="query_planner", skill_path=None)
        self.system_message = PLANNER_SYSTEM_MESSAGE

    async def run(self, input_data: dict, session_state: dict) -> dict:
        """
        Generate an execution plan based on extraction output.

        Input:
            normalized_query, devices, categories, constraints, generic_specs

        Returns:
            {"content": <plan dict>, "usage": {...}}
        """
        normalized_query = input_data.get("normalized_query", "")
        devices = input_data.get("devices", {})
        categories = input_data.get("categories", [])
        constraints = input_data.get("constraints", [])

        # Build context for the planner
        device_info = []
        for name, info in devices.items():
            device_info.append(f'  "{name}": conical_category={info.get("conical_category", "?")}')

        user_prompt = f"""User Question: {normalized_query}

Devices found: {', '.join(devices.keys()) if devices else 'none'}
{chr(10).join(device_info) if device_info else ''}
Categories mentioned: {', '.join(categories) if categories else 'none'}
Constraints: {json.dumps(constraints)}

Generate an execution plan. Respond with ONLY valid JSON."""

        print(f"  [QueryPlanner] Planning for: {normalized_query[:150]}")
        print(f"  [QueryPlanner] Constraints: {constraints}")

        messages = [{"role": "user", "content": user_prompt}]
        response = await self.llm_client.call_json(
            system_prompt=self.system_message,
            messages=messages,
            model=self.model,
        )

        plan = response.get("content", {})
        strategy = plan.get("strategy", "unknown")
        steps = plan.get("steps", [])
        print(f"  [QueryPlanner] Strategy: {strategy}, {len(steps)} steps")

        return {
            "content": plan,
            "usage": {
                "input_tokens": response.get("input_tokens", 0),
                "output_tokens": response.get("output_tokens", 0),
            },
        }
