"""
Orchestrator Tool Definitions

Defines the tools available to the orchestrator LLM for function calling.
Each tool maps to a pre-processing agent, engine, or output agent.
"""

TOOL_DEFINITIONS = [
    # ── Pre-processing ──────────────────────────────────────────
    {
        "name": "input_rewriter",
        "description": (
            "Normalize and rewrite the user's raw query. Resolves follow-up references "
            "using conversation history, preserves sentiment, and identifies any explicit "
            "source mentions (IFU, 510k, etc.). ALWAYS call this first for device queries."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "raw_query": {
                    "type": "string",
                    "description": "The user's raw input message",
                },
            },
            "required": ["raw_query"],
        },
    },
    {
        "name": "equipment_extraction",
        "description": (
            "Extract device names, categories, and generic specs from a normalized query. "
            "Resolves device names to database IDs using search. "
            "ALWAYS call this after input_rewriter and before any engine."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "normalized_query": {
                    "type": "string",
                    "description": "The rewritten/normalized query from input_rewriter",
                },
            },
            "required": ["normalized_query"],
        },
    },
    # ── Engines ─────────────────────────────────────────────────
    {
        "name": "chain_engine",
        "description": (
            "Run the full compatibility checking pipeline. Classifies the query, builds "
            "device chain configurations, evaluates OD/ID compatibility, runs decision "
            "logic, and generates a structured summary. Use for compatibility checks, "
            "stack validation, and device discovery questions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "normalized_query": {
                    "type": "string",
                    "description": "The normalized query",
                },
                "devices": {
                    "type": "object",
                    "description": "Device data from equipment_extraction (name -> {ids, conical_category, ...})",
                },
                "categories": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Device category mentions (e.g., ['microcatheter', 'sheath'])",
                },
                "generic_specs": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "Generic spec requirements (e.g., [{category: 'wire', spec: '.014'}])",
                },
            },
            "required": ["normalized_query", "devices"],
        },
    },
    {
        "name": "database_engine",
        "description": (
            "Query the device database for spec lookups, category listings, and filtered "
            "searches. Use when the user asks about device specifications, available devices "
            "in a category, or filtered searches by dimension. (NOT YET IMPLEMENTED)"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "normalized_query": {
                    "type": "string",
                    "description": "The normalized query",
                },
                "devices": {
                    "type": "object",
                    "description": "Device data from equipment_extraction",
                },
                "query_params": {
                    "type": "object",
                    "description": "Search/filter parameters",
                },
            },
            "required": ["normalized_query"],
        },
    },
    {
        "name": "vector_engine",
        "description": (
            "Search IFU documents, clinical documentation, and technique guidelines "
            "using vector search. Use for questions about device instructions for use, "
            "deployment techniques, contraindications, and clinical guidelines. (NOT YET IMPLEMENTED)"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "normalized_query": {
                    "type": "string",
                    "description": "The normalized query",
                },
                "search_terms": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Key terms to search for",
                },
            },
            "required": ["normalized_query"],
        },
    },
    # ── Output Agents ───────────────────────────────────────────
    {
        "name": "chain_output_agent",
        "description": (
            "Format chain engine compatibility results into a user-facing markdown response. "
            "Handles 2-device inline, stack tables, discovery lists, and N-1 subset results. "
            "Call AFTER chain_engine returns results."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "user_query": {
                    "type": "string",
                    "description": "The original user question",
                },
                "response_framing": {
                    "type": "string",
                    "enum": ["neutral", "confirmatory", "cautious"],
                    "description": "Tone framing for the response",
                },
                "classification": {
                    "type": "object",
                    "description": "Query classification from chain engine",
                },
                "chain_summary": {
                    "type": "object",
                    "description": "Chain analysis summary",
                },
                "text_summary": {
                    "type": "string",
                    "description": "Pre-generated text summary",
                },
                "flat_data": {
                    "type": "array",
                    "description": "Flattened compatibility results",
                },
                "chains_tested": {
                    "type": "array",
                    "description": "Chain configurations tested",
                },
                "decision": {
                    "type": "object",
                    "description": "Decision logic output",
                },
                "subset_analysis": {
                    "type": "object",
                    "description": "N-1 subset results (if applicable)",
                },
            },
            "required": ["user_query", "response_framing"],
        },
    },
    {
        "name": "database_output_agent",
        "description": (
            "Format database engine results into a user-facing response. "
            "(NOT YET IMPLEMENTED)"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "user_query": {"type": "string"},
                "data": {"type": "object"},
            },
            "required": ["user_query"],
        },
    },
    {
        "name": "vector_output_agent",
        "description": (
            "Format vector engine IFU/documentation results into a user-facing response. "
            "(NOT YET IMPLEMENTED)"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "user_query": {"type": "string"},
                "data": {"type": "object"},
            },
            "required": ["user_query"],
        },
    },
    {
        "name": "synthesis_output_agent",
        "description": (
            "Combine results from multiple engines into a unified response. "
            "Use when a query required both chain_engine and vector_engine (or other combos). "
            "(NOT YET IMPLEMENTED)"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "user_query": {"type": "string"},
                "engine_results": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "Results from multiple engines",
                },
            },
            "required": ["user_query", "engine_results"],
        },
    },
    {
        "name": "general_output_agent",
        "description": (
            "Handle greetings, scope questions, off-topic queries, and general clarifications. "
            "Use when no engine is needed — the user is greeting, asking what you can do, "
            "or asking something outside your scope."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "user_query": {
                    "type": "string",
                    "description": "The user's message",
                },
            },
            "required": ["user_query"],
        },
    },
]
