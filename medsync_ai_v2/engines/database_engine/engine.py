"""
Database Engine

Sub-orchestrator for database queries (spec lookups, filtered searches,
2-device compat checks, comparisons).

Pipeline:
  Default (query_spec): QuerySpecAgent (LLM) -> QueryExecutor (Python) -> _build_return()
  Filter mode:          QueryExecutor (Python) directly -> _build_return()

Ported from vs2/agents/direct_query_agents.py
"""

import os
from medsync_ai_v2.base_engine import BaseEngine
from medsync_ai_v2.engines.database_engine.query_spec_agent import QuerySpecAgent
from medsync_ai_v2.engines.database_engine.query_executor import QueryExecutor

SKILL_PATH = os.path.join(os.path.dirname(__file__), "SKILL.md")


class DatabaseEngine(BaseEngine):
    """Engine for database queries: spec lookups, filters, comparisons, compat checks."""

    def __init__(self):
        super().__init__(name="database_engine", skill_path=SKILL_PATH)
        self.query_spec_agent = QuerySpecAgent()
        self.query_executor = QueryExecutor()

    async def run(self, input_data: dict, session_state: dict) -> dict:
        """
        Run the database engine pipeline.

        Input:
            normalized_query, devices, categories, generic_specs
            Optional: input_type ("query_spec" | "filter")
                - "query_spec" (default): Full LLM path (QuerySpecAgent -> QueryExecutor)
                - "filter": Direct QueryExecutor (bypass LLM), expects query_spec in input_data

        Returns standard engine contract via _build_return().
        """
        input_type = input_data.get("input_type", "query_spec")

        if input_type == "filter":
            return self._run_filter_path(input_data)
        return await self._run_llm_path(input_data, session_state)

    async def _run_llm_path(self, input_data: dict, session_state: dict) -> dict:
        """Full LLM path: QuerySpecAgent -> QueryExecutor."""
        print(f"  [DatabaseEngine] Starting LLM pipeline")

        # Step 1: Generate query spec via LLM
        spec_result = await self.query_spec_agent.run(input_data, session_state)
        query_spec = spec_result.get("content", {})
        spec_usage = spec_result.get("usage", {})

        # Step 2: Execute the query spec against DATABASE
        execution_result = self.query_executor.execute(query_spec)
        device_list = self._extract_device_list(execution_result)

        print(f"  [DatabaseEngine] LLM pipeline complete: {len(device_list)} devices in results")

        return self._build_return(
            status="complete",
            result_type="database_query",
            data={
                "query_spec": query_spec,
                "execution_result": execution_result,
                "device_list": device_list,
                "summary": execution_result.get("summary", ""),
            },
            classification=input_data.get("classification", {}),
            confidence=0.9,
            usage=spec_usage,
        )

    def _run_filter_path(self, input_data: dict) -> dict:
        """
        Direct filter path: bypass LLM, execute query_spec directly.
        Used by the planned path when the planner has already specified the exact filter.
        """
        query_spec = input_data.get("query_spec", {})
        print(f"  [DatabaseEngine] Starting filter pipeline (bypass LLM)")
        print(f"  [DatabaseEngine] Query spec: action={query_spec.get('action')}, "
              f"category={query_spec.get('category')}")

        execution_result = self.query_executor.execute(query_spec)
        device_list = self._extract_device_list(execution_result)

        print(f"  [DatabaseEngine] Filter pipeline complete: {len(device_list)} devices")

        return self._build_return(
            status="complete",
            result_type="database_query",
            data={
                "query_spec": query_spec,
                "execution_result": execution_result,
                "device_list": device_list,
                "summary": execution_result.get("summary", ""),
            },
            classification=input_data.get("classification", {}),
            confidence=0.9,
            usage={"input_tokens": 0, "output_tokens": 0},
        )

    def _extract_device_list(self, execution_result: dict) -> list:
        """Extract device list from query executor results."""
        results = execution_result.get("results", [])
        if isinstance(results, list):
            return results
        elif isinstance(results, dict) and "id_matches" in results:
            return results.get("id_matches", []) + results.get("od_matches", [])
        return []

    def _build_return(
        self,
        status: str,
        result_type: str,
        data: dict,
        classification: dict,
        confidence: float = 0.9,
        usage: dict = None,
    ) -> dict:
        """Extended _build_return that includes usage tracking."""
        result = super()._build_return(status, result_type, data, classification, confidence)
        result["usage"] = usage or {"input_tokens": 0, "output_tokens": 0}
        return result
