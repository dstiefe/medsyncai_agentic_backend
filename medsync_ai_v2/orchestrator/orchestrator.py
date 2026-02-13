"""
Orchestrator - Intent-Based Pipeline

Runs a fixed agent sequence:
  1. input_rewriter → normalize query
  2. intent_classifier → classify user intent
  3. equipment_extraction → resolve device names to DB IDs
  3b-3d. (if generic_specs + compat intent) generic pipeline
  4. Route by INTENT to engine (chain / database / vector / planned / general)
  5. Route to output agent
  6. Return formatted response + structured data

Emits per-agent status events through the StreamingBroker.
"""

import asyncio
import json
import os
from datetime import datetime, timezone
from medsync_ai_v2 import config

# Lazy imports for tool executors (avoid circular imports)
_tool_registry = None


def _get_tool_registry():
    """Lazy-load all tool executors."""
    global _tool_registry
    if _tool_registry is not None:
        return _tool_registry

    from medsync_ai_v2.orchestrator.input_rewriter import InputRewriter
    from medsync_ai_v2.orchestrator.equipment_extraction import EquipmentExtraction
    from medsync_ai_v2.orchestrator.generic_device_structuring import GenericDeviceStructuring
    from medsync_ai_v2.orchestrator.generic_prep import GenericPrep
    from medsync_ai_v2.orchestrator.generic_prep_python import GenericPrepPython
    from medsync_ai_v2.orchestrator.intent_classifier import IntentClassifier
    from medsync_ai_v2.orchestrator.query_planner import QueryPlanner
    from medsync_ai_v2.engines.chain_engine.engine import ChainEngine
    from medsync_ai_v2.engines.database_engine.engine import DatabaseEngine
    from medsync_ai_v2.engines.vector_engine.engine import VectorEngine
    from medsync_ai_v2.engines.clinical_support_engine.engine import ClinicalSupportEngine
    from medsync_ai_v2.output_agents.chain_output_agent import ChainOutputAgent
    from medsync_ai_v2.output_agents.database_output_agent import DatabaseOutputAgent
    from medsync_ai_v2.output_agents.vector_output_agent import VectorOutputAgent
    from medsync_ai_v2.output_agents.synthesis_output_agent import SynthesisOutputAgent
    from medsync_ai_v2.output_agents.general_output_agent import GeneralOutputAgent
    from medsync_ai_v2.output_agents.clarification_output_agent import ClarificationOutputAgent
    from medsync_ai_v2.output_agents.clinical_output_agent import ClinicalOutputAgent

    _tool_registry = {
        "input_rewriter": InputRewriter(),
        "intent_classifier": IntentClassifier(),
        "equipment_extraction": EquipmentExtraction(),
        "generic_device_structuring": GenericDeviceStructuring(),
        "generic_prep": GenericPrep(),
        "generic_prep_python": GenericPrepPython(),
        "query_planner": QueryPlanner(),
        "chain_engine": ChainEngine(),
        "database_engine": DatabaseEngine(),
        "vector_engine": VectorEngine(),
        "clinical_support_engine": ClinicalSupportEngine(),
        "chain_output_agent": ChainOutputAgent(),
        "database_output_agent": DatabaseOutputAgent(),
        "vector_output_agent": VectorOutputAgent(),
        "synthesis_output_agent": SynthesisOutputAgent(),
        "general_output_agent": GeneralOutputAgent(),
        "clarification_output_agent": ClarificationOutputAgent(),
        "clinical_output_agent": ClinicalOutputAgent(),
    }
    return _tool_registry


class Orchestrator:
    """
    Intent-based orchestrator pipeline.

    Runs pre-processing → intent classification → extraction → engine → output agent.
    Routing is based on classified user intent, not extraction output shape.
    """

    # Maps intent types to engine paths
    INTENT_ENGINE_MAP = {
        "equipment_compatibility": "chain",
        "device_discovery": "chain",
        "specification_lookup": "database",
        "spec_reasoning": "database",
        "device_search": "database",
        "device_comparison": "database",
        "manufacturer_lookup": "database",
        "filtered_discovery": "planned",
        "documentation": "vector",
        "knowledge_base": "vector",
        "device_definition": "vector",
        "clinical_support": "clinical",
        "deep_research": "research",
        "general": "general",
    }

    # Intents that require synthetic devices from the generic pipeline
    COMPAT_INTENTS = {
        "equipment_compatibility",
        "device_discovery",
        "filtered_discovery",
    }

    # Intents where ALL named devices must be resolved (partial results are misleading)
    RELATIONAL_INTENTS = {
        "equipment_compatibility",
        "device_discovery",
        "device_comparison",
        "filtered_discovery",
    }

    def __init__(self):
        pass

    async def run(
        self,
        conversation_history: list,
        session_state: dict = None,
        broker=None,
    ) -> tuple:
        """
        Run the deterministic orchestrator pipeline.

        Returns:
            tuple of (final_response_text, tool_log, token_usage, chain_data)
            chain_data: flat device records for chain_category_chunk SSE, or None
        """
        if session_state is None:
            session_state = {}

        registry = _get_tool_registry()
        tool_log = []
        token_usage = {
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "sub_agent_calls": [],
        }

        # Get the latest user message
        user_message = ""
        for m in reversed(conversation_history):
            if m.get("role") == "user" and m.get("content"):
                user_message = m["content"]
                break

        # ==============================================================
        # Step 1: Input Rewriter
        # ==============================================================
        await self._emit_status(broker, "input_rewriter", "Reading\u2026")
        print(f"  [Pipeline] Step 1: input_rewriter")

        rewriter = registry["input_rewriter"]
        rewriter_result = await rewriter.run(
            {"raw_query": user_message}, session_state
        )
        self._track_usage(token_usage, "input_rewriter", rewriter_result)
        tool_log.append({"step": 1, "tool": "input_rewriter"})

        rewriter_content = rewriter_result.get("content", {})
        normalized_query = rewriter_content.get(
            "rewritten_user_prompt", user_message
        )
        print(f"  [Pipeline] Normalized query: {normalized_query[:150]}")

        # ==============================================================
        # Step 1b: Clinical clarification follow-up detection (deterministic)
        # ==============================================================
        clinical_followup = False
        pending_clinical = session_state.get("pending_clinical_clarification")
        if pending_clinical:
            merged = self._merge_clinical_followup(
                pending_clinical, normalized_query, user_message
            )
            if merged:
                normalized_query = merged
                clinical_followup = True
                print(f"  [Pipeline] Clinical follow-up merged: {normalized_query[:150]}")
            else:
                # User changed topic — clear stale pending context
                session_state.pop("pending_clinical_clarification", None)
                print(f"  [Pipeline] Pending clinical context cleared (topic change)")

        # ==============================================================
        # Step 1d: Post-assessment guideline query enrichment (deterministic)
        # ==============================================================
        guideline_enriched = False
        last_clinical = session_state.get("last_clinical_assessment")

        if last_clinical and not clinical_followup:
            enriched_query = self._enrich_guideline_query(
                normalized_query, raw_query=user_message,
                clinical_context=last_clinical,
            )
            if enriched_query:
                normalized_query = enriched_query
                guideline_enriched = True
                print(f"  [Pipeline] Guideline query enriched with clinical context")

        # ==============================================================
        # Steps 2+3: Intent Classification + Equipment Extraction (parallel)
        # ==============================================================
        await self._emit_status(broker, "intent_classifier", "Understanding Intent\u2026")
        await self._emit_status(broker, "equipment_extraction", "Extracting Devices\u2026")
        print(f"  [Pipeline] Steps 2+3: intent_classifier + equipment_extraction (parallel)")

        classifier = registry["intent_classifier"]
        extractor = registry["equipment_extraction"]

        intent_result, extraction_result = await asyncio.gather(
            classifier.run({"normalized_query": normalized_query}, session_state),
            extractor.run({"normalized_query": normalized_query}, session_state),
        )

        self._track_usage(token_usage, "intent_classifier", intent_result)
        tool_log.append({"step": 2, "tool": "intent_classifier"})
        self._track_usage(token_usage, "equipment_extraction", extraction_result)
        tool_log.append({"step": 3, "tool": "equipment_extraction"})

        # Parse intent results
        intent_data = intent_result.get("content", {})
        intents = intent_data.get("intents", [])
        primary_intent = intents[0]["type"] if intents else "general"
        is_multi_intent = intent_data.get("is_multi_intent", False)
        needs_planning = intent_data.get("needs_planning", False)

        print(f"  [Pipeline] Intent: {primary_intent}, "
              f"multi={is_multi_intent}, planning={needs_planning}")

        # Override intent for clinical follow-up (deterministic)
        if clinical_followup:
            primary_intent = "clinical_support"
            print(f"  [Pipeline] Force route: clinical (follow-up)")

        # ----------------------------------------------------------
        # Fast exit: general intent → skip extraction parsing
        # ----------------------------------------------------------
        if primary_intent == "general":
            return await self._run_general_path(
                registry, user_message, session_state, broker,
                tool_log, token_usage,
            )

        # Parse extraction results
        extraction = extraction_result.get("content", {})
        devices = extraction.get("devices", {})
        categories = extraction.get("categories", [])
        generic_specs = extraction.get("generic_specs", [])
        not_found = extraction.get("not_found", [])

        # ==============================================================
        # Validation Gate: Unresolved Device Clarification
        # ==============================================================
        if not_found:
            suggestions = self._get_fuzzy_suggestions(not_found)

            if primary_intent in self.RELATIONAL_INTENTS:
                # Full stop — relational intents need all devices
                print(f"  [Pipeline] STOP: unresolved devices {not_found} "
                      f"in relational intent={primary_intent}")
                return await self._run_clarification_path(
                    registry, user_message, devices, not_found, suggestions,
                    session_state, broker, tool_log, token_usage,
                )
            else:
                # Proceed with partial — enrich extraction for inline note
                print(f"  [Pipeline] PARTIAL: unresolved devices {not_found} "
                      f"in lookup intent={primary_intent}, proceeding with found devices")
                extraction["not_found_suggestions"] = suggestions

        # ==============================================================
        # Step 3b-3d: Generic Device Pipeline (conditional on intent)
        # ==============================================================
        # Only run when generic_specs exist AND the intent requires
        # synthetic devices for compatibility evaluation.
        request_db = None
        if generic_specs and primary_intent in self.COMPAT_INTENTS:
            generic_result = await self._run_generic_pipeline(
                registry, user_message, generic_specs, devices,
                session_state, broker, tool_log, token_usage,
            )
            if generic_result.get("synthetic_devices"):
                devices.update(generic_result["synthetic_devices"])
            if generic_result.get("insufficient_devices"):
                session_state["generic_insufficient"] = generic_result["insufficient_devices"]
            request_db = generic_result.get("request_db")
        elif generic_specs:
            print(f"  [Pipeline] Skipping generic pipeline: "
                  f"intent={primary_intent} does not require synthetic devices")

        # ==============================================================
        # Step 4: Route by intent
        # ==============================================================
        return await self._route_by_intent(
            registry, primary_intent, is_multi_intent, needs_planning,
            normalized_query, devices, categories, extraction,
            session_state, broker, tool_log, token_usage, user_message,
            request_db=request_db,
            clinical_followup=clinical_followup,
        )

    # ------------------------------------------------------------------
    # Intent-Based Routing
    # ------------------------------------------------------------------

    async def _route_by_intent(
        self, registry, primary_intent, is_multi_intent, needs_planning,
        normalized_query, devices, categories, extraction,
        session_state, broker, tool_log, token_usage, user_message,
        request_db=None, clinical_followup=False,
    ) -> tuple:
        """Route to the correct engine path based on classified intent."""

        constraints = extraction.get("constraints", [])

        # Planning path: filtered_discovery, needs_planning flag,
        # or constraints detected (backward-compat safety net)
        if primary_intent == "filtered_discovery" or needs_planning or constraints:
            print(f"  [Pipeline] Route: planned path "
                  f"(intent={primary_intent}, planning={needs_planning}, "
                  f"constraints={bool(constraints)})")
            return await self._run_planned_path(
                registry, normalized_query, devices, categories,
                constraints, extraction, session_state, broker,
                tool_log, token_usage, user_message,
                request_db=request_db,
            )

        engine = self.INTENT_ENGINE_MAP.get(primary_intent, "general")

        if engine == "chain":
            print(f"  [Pipeline] Route: chain path (intent={primary_intent})")
            return await self._run_chain_path(
                registry, normalized_query, devices, categories,
                extraction, session_state, broker, tool_log, token_usage,
                user_message, request_db=request_db,
            )

        if engine == "database":
            print(f"  [Pipeline] Route: database path (intent={primary_intent})")
            return await self._run_database_path(
                registry, normalized_query, devices, categories,
                extraction, session_state, broker, tool_log, token_usage,
                user_message,
            )

        if engine == "vector":
            print(f"  [Pipeline] Route: vector path (intent={primary_intent})")
            return await self._run_vector_path(
                registry, normalized_query, devices, categories,
                extraction, session_state, broker, tool_log, token_usage,
                user_message,
            )

        if engine == "clinical":
            print(f"  [Pipeline] Route: clinical path (intent={primary_intent})")
            return await self._run_clinical_path(
                registry, normalized_query, devices, categories,
                extraction, session_state, broker, tool_log, token_usage,
                user_message, clinical_followup=clinical_followup,
            )

        if engine == "research":
            print(f"  [Pipeline] Route: research path (stubbed)")
            return await self._run_research_stub(
                registry, user_message, session_state, broker,
                tool_log, token_usage,
            )

        # Fallback
        print(f"  [Pipeline] Route: general path (intent={primary_intent})")
        return await self._run_general_path(
            registry, user_message, session_state, broker,
            tool_log, token_usage,
        )

    # ------------------------------------------------------------------
    # Chain Engine Path
    # ------------------------------------------------------------------

    async def _run_chain_path(
        self, registry, normalized_query, devices, categories,
        extraction, session_state, broker, tool_log, token_usage,
        user_message, request_db=None,
    ) -> tuple:
        """Run: chain_engine → chain_output_agent → return."""

        # Step 3: Chain Engine
        await self._emit_status(broker, "chain_engine", "Processing Connections\u2026")
        print(f"  [Pipeline] Step 3: chain_engine")

        engine = registry["chain_engine"]
        engine_input = {
            "normalized_query": normalized_query,
            "devices": devices,
            "categories": categories,
            "generic_specs": extraction.get("generic_specs", []),
        }
        if request_db is not None:
            engine_input["database"] = request_db
        engine_result = await engine.run(engine_input, session_state)
        self._track_usage(token_usage, "chain_engine", engine_result)
        tool_log.append({"step": 3, "tool": "chain_engine"})

        engine_data = engine_result.get("data", {})
        classification = engine_result.get("classification", {})
        result_type = engine_result.get("result_type", "compatibility_check")
        flat_data = engine_data.get("flat_data", [])

        # Step 4: Chain Output Agent
        await self._emit_status(broker, "chain_output_agent", "Generating Answer\u2026")
        print(f"  [Pipeline] Step 4: chain_output_agent")

        output_agent = registry["chain_output_agent"]
        output_input = {
            "user_query": user_message,
            "response_framing": classification.get("framing", "neutral"),
            "result_type": result_type,
            "classification": classification,
            "chain_summary": engine_data.get("chain_summary", {}),
            "text_summary": engine_data.get("text_summary", ""),
            "flat_data": flat_data,
            "chains_tested": engine_data.get("chains_tested", []),
            "decision": engine_data.get("decision", {}),
            "subset_analysis": engine_data.get("subset_analysis"),
            "not_found": extraction.get("not_found", []),
            "not_found_suggestions": extraction.get("not_found_suggestions", {}),
        }
        output_result = await output_agent.run(output_input, session_state, broker=broker)
        self._track_usage(token_usage, "chain_output_agent", output_result)
        tool_log.append({"step": 4, "tool": "chain_output_agent"})

        output_content = output_result.get("content", {})
        final_text = output_content.get(
            "formatted_response",
            output_content.get("raw_text", "Unable to format response."),
        )

        total = token_usage["total_input_tokens"] + token_usage["total_output_tokens"]
        print(f"  [Pipeline] Complete. {total} total tokens")

        return final_text, tool_log, token_usage, flat_data

    # ------------------------------------------------------------------
    # Database Engine Path
    # ------------------------------------------------------------------

    async def _run_database_path(
        self, registry, normalized_query, devices, categories,
        extraction, session_state, broker, tool_log, token_usage,
        user_message,
    ) -> tuple:
        """Run: database_engine → database_output_agent → return."""

        # Step 3: Database Engine
        await self._emit_status(broker, "database_engine", "Searching Database\u2026")
        print(f"  [Pipeline] Step 3: database_engine")

        engine = registry["database_engine"]
        engine_input = {
            "normalized_query": normalized_query,
            "devices": devices,
            "categories": categories,
            "generic_specs": extraction.get("generic_specs", []),
        }
        engine_result = await engine.run(engine_input, session_state)
        self._track_usage(token_usage, "database_engine", engine_result)
        tool_log.append({"step": 3, "tool": "database_engine"})

        engine_data = engine_result.get("data", {})
        device_list = engine_data.get("device_list", [])

        # Step 4: Database Output Agent
        await self._emit_status(broker, "database_output_agent", "Generating Answer\u2026")
        print(f"  [Pipeline] Step 4: database_output_agent")

        output_agent = registry["database_output_agent"]
        output_input = {
            "user_query": user_message,
            "query_spec": engine_data.get("query_spec", {}),
            "summary": engine_data.get("summary", ""),
            "device_list": device_list,
            "not_found": extraction.get("not_found", []),
            "not_found_suggestions": extraction.get("not_found_suggestions", {}),
            "generic_specs": extraction.get("generic_specs", []),
        }
        output_result = await output_agent.run(output_input, session_state, broker=broker)
        self._track_usage(token_usage, "database_output_agent", output_result)
        tool_log.append({"step": 4, "tool": "database_output_agent"})

        output_content = output_result.get("content", {})
        final_text = output_content.get(
            "formatted_response",
            output_content.get("raw_text", "Unable to format response."),
        )

        total = token_usage["total_input_tokens"] + token_usage["total_output_tokens"]
        print(f"  [Pipeline] Complete. {total} total tokens")

        # device_list already streamed as query_result_device_chunk by database_output_agent
        return final_text, tool_log, token_usage, None

    # ------------------------------------------------------------------
    # Planned Path (multi-engine, constraint-driven)
    # ------------------------------------------------------------------

    async def _run_planned_path(
        self, registry, normalized_query, devices, categories,
        constraints, extraction, session_state, broker,
        tool_log, token_usage, user_message,
        request_db=None,
    ) -> tuple:
        """
        Run a planner-driven multi-engine execution.

        1. QueryPlanner (LLM, fast) → execution plan
        2. Execute plan steps sequentially (database → chain, etc.)
        3. Run the specified output agent
        """
        # Step 3a: Query Planner
        await self._emit_status(broker, "query_planner", "Planning Approach\u2026")
        print(f"  [Pipeline] Step 3a: query_planner")

        planner = registry["query_planner"]
        planner_input = {
            "normalized_query": normalized_query,
            "devices": devices,
            "categories": categories,
            "constraints": constraints,
            "generic_specs": extraction.get("generic_specs", []),
        }
        planner_result = await planner.run(planner_input, session_state)
        self._track_usage(token_usage, "query_planner", planner_result)
        tool_log.append({"step": "3a", "tool": "query_planner"})

        plan = planner_result.get("content", {})
        steps = plan.get("steps", [])
        output_agent_name = plan.get("output_agent", "database_output_agent")

        if not steps:
            print("  [Pipeline] Planner returned no steps, falling back to database path")
            return await self._run_database_path(
                registry, normalized_query, devices, categories,
                extraction, session_state, broker, tool_log, token_usage,
                user_message,
            )

        # Execute plan steps (wave-based parallel execution)
        step_results = {}

        # Infer depends_on from inject_devices_from for backward compatibility
        for step in steps:
            if "depends_on" not in step:
                inject_from = step.get("inject_devices_from")
                step["depends_on"] = [inject_from] if inject_from else []

        async def execute_step(step):
            """Execute a single plan step. Closure captures all pipeline locals."""
            step_id = step.get("step_id", "?")
            engine_type = step.get("engine", "")
            action = step.get("action", "")
            store_as = step.get("store_as", step_id)

            if engine_type == "database":
                await self._emit_status(broker, "database_engine", "Searching Database\u2026")
                print(f"  [Pipeline] Plan step {step_id}: database_engine ({action})")

                db_engine = registry["database_engine"]
                db_input = {
                    "input_type": "filter",
                    "query_spec": {
                        "action": action,
                        "category": step.get("category"),
                        "filters": step.get("filters", []),
                    },
                }

                # Safety net: inject extraction constraints the planner may have missed
                existing_fields = {f.get("field") for f in db_input["query_spec"]["filters"]}
                for constraint in constraints:
                    c_field = constraint.get("field")
                    c_value = constraint.get("value")
                    if c_field and c_value and c_field not in existing_fields:
                        db_input["query_spec"]["filters"].append({
                            "field": c_field,
                            "operator": "contains",
                            "value": c_value,
                        })
                        print(f"    Injected constraint: {c_field} contains {c_value}")

                db_result = await db_engine.run(db_input, session_state)
                self._track_usage(token_usage, "database_engine", db_result)
                tool_log.append({"step": f"3b_{step_id}", "tool": "database_engine"})

                step_results[store_as] = db_result
                step_results[step_id] = db_result

                device_list = db_result.get("data", {}).get("device_list", [])
                print(f"    -> {len(device_list)} devices")
                sample = [d.get("product_name", "?") for d in device_list[:5]]
                print(f"    -> Sample products: {sample}")

            elif engine_type == "chain":
                await self._emit_status(broker, "chain_engine", "Processing Connections\u2026")
                print(f"  [Pipeline] Plan step {step_id}: chain_engine ({action})")

                prior_results = []
                inject_from = step.get("inject_devices_from")
                if inject_from and inject_from in step_results:
                    prior_results.append(step_results[inject_from])
                    db_count = len(step_results[inject_from].get("data", {}).get("device_list", []))
                    print(f"    Passing {db_count} DB-filtered devices via prior_results")

                filter_category = steps[0].get("category", "device") if steps else "device"

                chain_engine = registry["chain_engine"]
                chain_input = {
                    "normalized_query": normalized_query,
                    "devices": devices,
                    "categories": [] if prior_results else (categories if categories else []),
                    "prior_results": prior_results,
                    "metadata": {"filter_category": filter_category},
                }
                if request_db is not None:
                    chain_input["database"] = request_db
                chain_result = await chain_engine.run(chain_input, session_state)
                self._track_usage(token_usage, "chain_engine", chain_result)
                tool_log.append({"step": f"3b_{step_id}", "tool": "chain_engine"})

                chain_eng_data = chain_result.get("data", {})
                print(f"    Chain engine status: {chain_result.get('status')}")
                print(f"    flat_data length: {len(chain_eng_data.get('flat_data', []))}")

                step_results[store_as] = chain_result
                step_results[step_id] = chain_result

            elif engine_type == "vector":
                await self._emit_status(broker, "vector_engine", "Searching Documents\u2026")
                print(f"  [Pipeline] Plan step {step_id}: vector_engine ({action})")

                vector_engine = registry["vector_engine"]

                vector_devices = {}
                named = step.get("named_devices", [])
                for dev_name in named:
                    if dev_name in devices:
                        vector_devices[dev_name] = devices[dev_name]

                inject_from = step.get("inject_devices_from")
                if inject_from and inject_from in step_results:
                    prior = step_results[inject_from]
                    prior_devices = prior.get("data", {}).get("device_list", [])
                    for dev in prior_devices:
                        dev_name = dev.get("product_name", dev.get("device_name", ""))
                        dev_id = dev.get("id")
                        if dev_name and dev_id:
                            if dev_name not in vector_devices:
                                vector_devices[dev_name] = {"ids": []}
                            vector_devices[dev_name]["ids"].append(dev_id)

                vector_query = step.get("query_focus", normalized_query)

                vector_input = {
                    "normalized_query": vector_query,
                    "devices": vector_devices,
                    "classification": {},
                }
                vector_result = await vector_engine.run(vector_input, session_state)
                self._track_usage(token_usage, "vector_engine", vector_result)
                tool_log.append({"step": f"3b_{step_id}", "tool": "vector_engine"})

                chunk_count = len(vector_result.get("data", {}).get("chunks", []))
                print(f"    -> {chunk_count} document chunks")

                step_results[store_as] = vector_result
                step_results[step_id] = vector_result

        # Wave-based execution: run independent steps in parallel
        completed = set()
        remaining = list(steps)

        while remaining:
            ready = [s for s in remaining
                     if all(d in completed for d in s.get("depends_on", []))]

            if not ready:
                print(f"  [Pipeline] WARNING: {len(remaining)} steps stuck (circular deps?), running sequentially")
                for s in remaining:
                    await execute_step(s)
                break

            if len(ready) > 1:
                print(f"  [Pipeline] Running {len(ready)} steps in parallel: {[s['step_id'] for s in ready]}")
                await asyncio.gather(*[execute_step(s) for s in ready])
            else:
                await execute_step(ready[0])

            for s in ready:
                completed.add(s.get("step_id", ""))
            remaining = [s for s in remaining if s.get("step_id", "") not in completed]

        # Step 4: Output agent
        last_store_as = steps[-1].get("store_as", "")
        last_result = step_results.get(last_store_as, {})

        if output_agent_name == "chain_output_agent" and isinstance(last_result, dict):
            # Chain engine result — use chain output agent
            await self._emit_status(broker, "chain_output_agent", "Generating Answer\u2026")
            print(f"  [Pipeline] Step 4: chain_output_agent")

            engine_data = last_result.get("data", {})
            classification = last_result.get("classification", {})
            result_type = last_result.get("result_type", "compatibility_check")
            flat_data = engine_data.get("flat_data", [])

            output_agent = registry["chain_output_agent"]
            output_input = {
                "user_query": user_message,
                "response_framing": classification.get("framing", "neutral"),
                "result_type": result_type,
                "classification": classification,
                "chain_summary": engine_data.get("chain_summary", {}),
                "text_summary": engine_data.get("text_summary", ""),
                "flat_data": flat_data,
                "chains_tested": engine_data.get("chains_tested", []),
                "decision": engine_data.get("decision", {}),
                "subset_analysis": engine_data.get("subset_analysis"),
                "not_found": extraction.get("not_found", []),
                "not_found_suggestions": extraction.get("not_found_suggestions", {}),
            }
            output_result = await output_agent.run(output_input, session_state, broker=broker)
            self._track_usage(token_usage, "chain_output_agent", output_result)
            tool_log.append({"step": 4, "tool": "chain_output_agent"})

            output_content = output_result.get("content", {})
            final_text = output_content.get(
                "formatted_response",
                output_content.get("raw_text", "Unable to format response."),
            )

            total = token_usage["total_input_tokens"] + token_usage["total_output_tokens"]
            print(f"  [Pipeline] Complete. {total} total tokens")
            print(f"  [Pipeline] Returning flat_data with {len(flat_data)} records (truthy: {bool(flat_data)})")

            return final_text, tool_log, token_usage, flat_data

        elif output_agent_name == "vector_output_agent" and isinstance(last_result, dict):
            # Vector-only result — use vector output agent
            await self._emit_status(broker, "vector_output_agent", "Generating Answer\u2026")
            print(f"  [Pipeline] Step 4: vector_output_agent")

            output_agent = registry["vector_output_agent"]
            output_input = {
                "user_query": user_message,
                "normalized_query": normalized_query,
                "data": last_result.get("data", {}),
                "classification": last_result.get("classification", {}),
                "not_found": extraction.get("not_found", []),
                "not_found_suggestions": extraction.get("not_found_suggestions", {}),
            }
            output_result = await output_agent.run(output_input, session_state, broker=broker)
            self._track_usage(token_usage, "vector_output_agent", output_result)
            tool_log.append({"step": 4, "tool": "vector_output_agent"})

            output_content = output_result.get("content", {})
            final_text = output_content.get(
                "formatted_response",
                output_content.get("raw_text", "Unable to format response."),
            )

            total = token_usage["total_input_tokens"] + token_usage["total_output_tokens"]
            print(f"  [Pipeline] Complete. {total} total tokens")

            return final_text, tool_log, token_usage, None

        elif output_agent_name == "synthesis_output_agent":
            # Multi-engine synthesis — combine all step results
            await self._emit_status(broker, "synthesis_output_agent", "Synthesizing Answer\u2026")
            print(f"  [Pipeline] Step 4: synthesis_output_agent")

            output_agent = registry["synthesis_output_agent"]
            output_input = {
                "user_query": user_message,
                "normalized_query": normalized_query,
                "step_results": step_results,
                "plan": plan,
                "extraction": extraction,
            }
            output_result = await output_agent.run(output_input, session_state, broker=broker)
            self._track_usage(token_usage, "synthesis_output_agent", output_result)
            tool_log.append({"step": 4, "tool": "synthesis_output_agent"})

            output_content = output_result.get("content", {})
            final_text = output_content.get(
                "formatted_response",
                output_content.get("raw_text", "Unable to format response."),
            )

            # Extract flat_data from chain step if present
            flat_data = None
            for step in steps:
                if step.get("engine") == "chain":
                    chain_store = step.get("store_as", "")
                    chain_result = step_results.get(chain_store, {})
                    flat_data = chain_result.get("data", {}).get("flat_data", []) or None
                    break

            total = token_usage["total_input_tokens"] + token_usage["total_output_tokens"]
            print(f"  [Pipeline] Complete. {total} total tokens")

            return final_text, tool_log, token_usage, flat_data

        else:
            # Database-only result — use database output agent
            await self._emit_status(broker, "database_output_agent", "Generating Answer\u2026")
            print(f"  [Pipeline] Step 4: database_output_agent")

            last_data = last_result.get("data", {}) if isinstance(last_result, dict) else {}
            device_list = last_data.get("device_list", [])

            output_agent = registry["database_output_agent"]
            output_input = {
                "user_query": user_message,
                "query_spec": last_data.get("query_spec", {}),
                "summary": last_data.get("summary", ""),
                "device_list": device_list,
                "not_found": extraction.get("not_found", []),
                "not_found_suggestions": extraction.get("not_found_suggestions", {}),
                "generic_specs": extraction.get("generic_specs", []),
            }
            output_result = await output_agent.run(output_input, session_state, broker=broker)
            self._track_usage(token_usage, "database_output_agent", output_result)
            tool_log.append({"step": 4, "tool": "database_output_agent"})

            output_content = output_result.get("content", {})
            final_text = output_content.get(
                "formatted_response",
                output_content.get("raw_text", "Unable to format response."),
            )

            total = token_usage["total_input_tokens"] + token_usage["total_output_tokens"]
            print(f"  [Pipeline] Complete. {total} total tokens")

            # device_list already streamed as query_result_device_chunk by database_output_agent
            return final_text, tool_log, token_usage, None

    # ------------------------------------------------------------------
    # Helper: Transform DB results → Chain device format
    # DEPRECATED: Use engine composition via prior_results instead.
    # The chain engine's _resolve_input() now handles this automatically.
    # Kept for one release cycle as a safety net.
    # ------------------------------------------------------------------

    def _db_results_to_chain_devices(self, device_list: list) -> dict:
        """Convert database filter results into chain engine device format."""
        by_product = {}
        for device in device_list:
            product = device.get("product_name", "Unknown")
            if product == "Unknown":
                continue
            if product not in by_product:
                by_product[product] = {
                    "ids": [],
                    "conical_category": device.get("conical_category", "Unknown"),
                }
            dev_id = device.get("device_id")
            if dev_id and dev_id not in by_product[product]["ids"]:
                by_product[product]["ids"].append(dev_id)
        return by_product

    # ------------------------------------------------------------------
    # Generic Device Pipeline
    # ------------------------------------------------------------------

    async def _run_generic_pipeline(
        self, registry, user_message, generic_specs, existing_devices,
        session_state, broker, tool_log, token_usage,
    ) -> dict:
        """
        Run the 3-step generic device pipeline:
          2b. GenericDeviceStructuring — merge fragments into structured devices
          2c. GenericPrep — map to DB fields, check sufficiency
          2d. GenericPrepPython — create synthetic DB records

        Returns:
            {
                "synthetic_devices": dict (product_name -> {ids, conical_category}),
                "insufficient_devices": list (devices with has_info=False)
            }
        """
        result = {"synthetic_devices": {}, "insufficient_devices": []}

        # Step 2b: Structure raw fragments
        await self._emit_status(broker, "generic_device_structuring", "Understanding Generic Devices\u2026")
        print(f"  [Pipeline] Step 2b: generic_device_structuring")

        structuring_agent = registry["generic_device_structuring"]
        structuring_result = await structuring_agent.run(
            {"original_question": user_message, "generic_specs": generic_specs},
            session_state,
        )
        self._track_usage(token_usage, "generic_device_structuring", structuring_result)
        tool_log.append({"step": "2b", "tool": "generic_device_structuring"})

        structured_devices = structuring_result.get("content", {}).get("generic_devices", [])
        if not structured_devices:
            print("  [Pipeline] No structured generic devices, skipping prep steps")
            return result

        # Step 2c: Map to DB fields + check sufficiency
        await self._emit_status(broker, "generic_prep", "Structuring Generics\u2026")
        print(f"  [Pipeline] Step 2c: generic_prep")

        prep_agent = registry["generic_prep"]
        prep_result = await prep_agent.run(
            {"original_question": user_message, "generic_devices": structured_devices},
            session_state,
        )
        self._track_usage(token_usage, "generic_prep", prep_result)
        tool_log.append({"step": "2c", "tool": "generic_prep"})

        prep_content = prep_result.get("content", {})
        prep_devices = prep_content.get("devices", [])

        # Separate sufficient vs insufficient devices
        sufficient = [d for d in prep_devices if d.get("has_info", False)]
        insufficient = [d for d in prep_devices if not d.get("has_info", False)]
        result["insufficient_devices"] = insufficient

        if not sufficient:
            print("  [Pipeline] No generic devices with sufficient info, skipping python step")
            return result

        # Step 2d: Create synthetic DB records
        # Create request-scoped database copy for synthetic injection
        # (prevents cross-request contamination of the global DATABASE)
        from medsync_ai_v2.shared.device_search import get_database
        request_db = dict(get_database())

        await self._emit_status(broker, "generic_prep_python", "Reasoning Over Generics\u2026")
        print(f"  [Pipeline] Step 2d: generic_prep_python")

        python_agent = registry["generic_prep_python"]
        python_result = await python_agent.run(
            {
                "devices": sufficient,
                "uid": session_state.get("uid", "0000"),
                "session_id": session_state.get("session_id", "0000"),
                "database": request_db,
            },
            session_state,
        )
        self._track_usage(token_usage, "generic_prep_python", python_result)
        tool_log.append({"step": "2d", "tool": "generic_prep_python"})

        # Package synthetic devices in the same format as equipment_extraction
        # (product_name -> {ids: [...], conical_category: ...})
        synthetic_records = python_result.get("content", {}).get("synthetic_devices", {})
        for record_id, record in synthetic_records.items():
            device_name = record.get("device_name", record.get("raw", "generic device"))
            product_name = record.get("product_name", device_name)
            logic_cat = record.get("logic_category", "")
            result["synthetic_devices"][product_name] = {
                "ids": [record_id],
                "conical_category": logic_cat,
            }

        result["request_db"] = request_db

        print(f"  [Pipeline] Generic pipeline complete: {len(result['synthetic_devices'])} synthetic, "
              f"{len(insufficient)} insufficient")

        return result

    # ------------------------------------------------------------------
    # General Path (greetings, scope, off-topic)
    # ------------------------------------------------------------------

    async def _run_general_path(
        self, registry, user_message, session_state, broker,
        tool_log, token_usage,
    ) -> tuple:
        """Run: general_output_agent → return."""

        await self._emit_status(broker, "general_output_agent", "Generating Answer\u2026")
        print(f"  [Pipeline] Step 3: general_output_agent (no devices found)")

        output_agent = registry["general_output_agent"]
        output_result = await output_agent.run(
            {"user_query": user_message}, session_state, broker=broker
        )
        self._track_usage(token_usage, "general_output_agent", output_result)
        tool_log.append({"step": 3, "tool": "general_output_agent"})

        output_content = output_result.get("content", {})
        final_text = output_content.get(
            "formatted_response",
            output_content.get("raw_text", "I can help with medical device compatibility questions."),
        )

        total = token_usage["total_input_tokens"] + token_usage["total_output_tokens"]
        print(f"  [Pipeline] Complete. {total} total tokens")

        return final_text, tool_log, token_usage, None

    # ------------------------------------------------------------------
    # Vector Engine Path (stub)
    # ------------------------------------------------------------------

    async def _run_vector_path(
        self, registry, normalized_query, devices, categories,
        extraction, session_state, broker, tool_log, token_usage,
        user_message,
    ) -> tuple:
        """Run: vector_engine → vector_output_agent → return."""

        await self._emit_status(broker, "vector_engine", "Searching Documents\u2026")
        print(f"  [Pipeline] vector_engine")

        engine = registry["vector_engine"]
        engine_input = {
            "normalized_query": normalized_query,
            "devices": devices,
            "categories": categories,
            "classification": extraction.get("classification", {}),
        }
        engine_result = await engine.run(engine_input, session_state)
        self._track_usage(token_usage, "vector_engine", engine_result)
        tool_log.append({"step": "engine", "tool": "vector_engine"})

        await self._emit_status(broker, "vector_output_agent", "Generating Answer\u2026")
        print(f"  [Pipeline] vector_output_agent")

        output_agent = registry["vector_output_agent"]
        output_input = {
            "user_query": user_message,
            "normalized_query": normalized_query,
            "data": engine_result.get("data", {}),
            "classification": engine_result.get("classification", {}),
            "not_found": extraction.get("not_found", []),
            "not_found_suggestions": extraction.get("not_found_suggestions", {}),
        }
        output_result = await output_agent.run(output_input, session_state, broker=broker)
        self._track_usage(token_usage, "vector_output_agent", output_result)
        tool_log.append({"step": "output", "tool": "vector_output_agent"})

        output_content = output_result.get("content", {})
        final_text = output_content.get(
            "formatted_response",
            output_content.get("raw_text", "Document search is not yet available."),
        )

        total = token_usage["total_input_tokens"] + token_usage["total_output_tokens"]
        print(f"  [Pipeline] Complete. {total} total tokens")

        return final_text, tool_log, token_usage, None

    # ------------------------------------------------------------------
    # Clinical Support Path
    # ------------------------------------------------------------------

    async def _run_clinical_path(
        self, registry, normalized_query, devices, categories,
        extraction, session_state, broker, tool_log, token_usage,
        user_message, clinical_followup=False,
    ) -> tuple:
        """Run: clinical_support_engine → [clarification | clinical_output_agent] → return."""

        # Step: Clinical Support Engine
        await self._emit_status(broker, "clinical_support_engine", "Evaluating Eligibility\u2026")
        print(f"  [Pipeline] clinical_support_engine")

        engine = registry["clinical_support_engine"]
        engine_input = {
            "normalized_query": normalized_query,
            # On follow-up, normalized_query IS the merged patient data — use it for parsing
            "raw_query": normalized_query if clinical_followup else user_message,
        }
        engine_result = await engine.run(engine_input, session_state)
        self._track_usage(token_usage, "clinical_support_engine", engine_result)
        tool_log.append({"step": "engine", "tool": "clinical_support_engine"})

        engine_data = engine_result.get("data", {})

        # Branch: needs_clarification → deterministic formatting, no LLM
        if engine_result.get("status") == "needs_clarification":
            await self._emit_status(broker, "clinical_support_engine", "Missing Information\u2026")
            print(f"  [Pipeline] Clinical clarification (deterministic, no LLM)")

            clarification_text = self._format_clinical_clarification(engine_data)

            if broker:
                await broker.put({
                    "type": "final_chunk",
                    "data": {
                        "agent": "clinical_support_engine",
                        "content": clarification_text,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                })

            # Store clinical context for follow-up merge
            session_state["pending_clinical_clarification"] = {
                "patient": engine_data.get("patient", {}),
                "completeness": engine_data.get("completeness", {}),
                "original_query": user_message,
            }

            total = token_usage["total_input_tokens"] + token_usage["total_output_tokens"]
            print(f"  [Pipeline] Clarification complete. {total} total tokens")
            return clarification_text, tool_log, token_usage, None

        # Normal path: Clinical Output Agent
        await self._emit_status(broker, "clinical_output_agent", "Generating Assessment\u2026")
        print(f"  [Pipeline] clinical_output_agent")

        output_agent = registry["clinical_output_agent"]
        output_input = {
            "user_query": normalized_query if clinical_followup else user_message,
            "patient": engine_data.get("patient", {}),
            "eligibility": engine_data.get("eligibility", []),
            "trial_context": engine_data.get("trial_context", {}),
            "vector_context": engine_data.get("vector_context", []),
            "completeness": engine_data.get("completeness", {}),
        }
        output_result = await output_agent.run(output_input, session_state, broker=broker)
        self._track_usage(token_usage, "clinical_output_agent", output_result)
        tool_log.append({"step": "output", "tool": "clinical_output_agent"})

        output_content = output_result.get("content", {})
        final_text = output_content.get(
            "formatted_response",
            output_content.get("raw_text", "Clinical assessment could not be generated."),
        )

        # Clear pending clarification — assessment is complete
        session_state.pop("pending_clinical_clarification", None)

        # Store clinical assessment context for post-assessment follow-ups
        session_state["last_clinical_assessment"] = {
            "patient": engine_data.get("patient", {}),
            "eligibility": engine_data.get("eligibility", []),
        }

        total = token_usage["total_input_tokens"] + token_usage["total_output_tokens"]
        print(f"  [Pipeline] Complete. {total} total tokens")

        return final_text, tool_log, token_usage, None

    # ------------------------------------------------------------------
    # Research Loop Path (stub)
    # ------------------------------------------------------------------

    async def _run_research_stub(
        self, registry, user_message, session_state, broker,
        tool_log, token_usage,
    ) -> tuple:
        """Stub: falls back to general output with a research note."""

        print(f"  [Pipeline] Research loop not yet implemented, using general path")

        await self._emit_status(broker, "general_output_agent", "Generating Answer\u2026")

        output_agent = registry["general_output_agent"]
        augmented_query = (
            f"The user asked a complex research question. The deep research "
            f"feature is not yet available. Please acknowledge the complexity "
            f"and offer to help with specific sub-questions instead.\n\n"
            f"User question: {user_message}"
        )
        output_result = await output_agent.run(
            {"user_query": augmented_query}, session_state, broker=broker
        )
        self._track_usage(token_usage, "general_output_agent", output_result)
        tool_log.append({"step": "output", "tool": "general_output_agent"})

        output_content = output_result.get("content", {})
        final_text = output_content.get(
            "formatted_response",
            output_content.get("raw_text", "Deep research is not yet available."),
        )

        total = token_usage["total_input_tokens"] + token_usage["total_output_tokens"]
        print(f"  [Pipeline] Complete. {total} total tokens")

        return final_text, tool_log, token_usage, None

    # ------------------------------------------------------------------
    # Clarification Path (unresolved devices)
    # ------------------------------------------------------------------

    async def _run_clarification_path(
        self, registry, user_message, devices, not_found, suggestions,
        session_state, broker, tool_log, token_usage,
    ) -> tuple:
        """Full stop: stream a clarification message for unresolved devices."""

        resolved_devices = list(devices.keys()) if devices else []

        await self._emit_status(broker, "clarification_output_agent", "Clarifying\u2026")
        print(f"  [Pipeline] clarification_output_agent "
              f"(not_found={not_found}, resolved={resolved_devices})")

        output_agent = registry["clarification_output_agent"]
        output_input = {
            "user_query": user_message,
            "resolved_devices": resolved_devices,
            "not_found": not_found,
            "suggestions": suggestions,
        }
        output_result = await output_agent.run(
            output_input, session_state, broker=broker
        )
        self._track_usage(token_usage, "clarification_output_agent", output_result)
        tool_log.append({"step": "clarification", "tool": "clarification_output_agent"})

        output_content = output_result.get("content", {})
        final_text = output_content.get(
            "formatted_response",
            "Could you clarify which devices you mean?",
        )

        total = token_usage["total_input_tokens"] + token_usage["total_output_tokens"]
        print(f"  [Pipeline] Clarification complete. {total} total tokens")

        return final_text, tool_log, token_usage, None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _format_clinical_clarification(self, engine_data: dict) -> str:
        """Format a deterministic clarification message for missing clinical data.

        No LLM needed — the questions are pre-built by assess_completeness().
        """
        completeness = engine_data.get("completeness", {})
        patient = engine_data.get("patient", {})

        parts = []

        # Questions — direct, no preamble
        questions = completeness.get("clarification_questions", [])
        for q in questions:
            parts.append(q)

        # Compact patient summary so the doctor can verify what was parsed
        parsed_fields = []
        if patient.get("age") is not None:
            sex_abbr = ""
            if patient.get("sex"):
                sex_abbr = patient["sex"][0].upper()  # "female" → "F"
            parsed_fields.append(f"{patient['age']}{sex_abbr}")
        if patient.get("nihss") is not None:
            parsed_fields.append(f"NIHSS {patient['nihss']}")
        if patient.get("aspects") is not None:
            parsed_fields.append(f"ASPECTS {patient['aspects']}")
        if patient.get("last_known_well_hours") is not None:
            parsed_fields.append(f"LKW {patient['last_known_well_hours']}h")
        if patient.get("occlusion_location"):
            parsed_fields.append(patient["occlusion_location"])
        if patient.get("mrs_pre") is not None:
            parsed_fields.append(f"mRS {patient['mrs_pre']}")
        if patient.get("dementia"):
            parsed_fields.append("dementia")
        if patient.get("on_anticoagulation"):
            parsed_fields.append(
                f"on {patient.get('anticoagulant_type', 'anticoagulation')}"
            )

        if parsed_fields:
            parts.append(f"\n**Patient data received:** {', '.join(parsed_fields)}")

        return "\n".join(parts)

    def _merge_clinical_followup(
        self, pending: dict, normalized_query: str, raw_query: str
    ) -> str | None:
        """Merge a clinical clarification response with the original patient presentation.

        If the follow-up looks like it's providing the missing clinical parameters
        (NIHSS, ASPECTS, LKW, etc.), merge Turn 1 patient data + Turn 2 new data
        into a single combined query.

        Returns merged query string, or None if this doesn't look like a clinical follow-up.
        """
        import re

        patient = pending.get("patient", {})
        print(f"  [ClinicalMerge] Pending patient dict: {patient}")
        print(f"  [ClinicalMerge] Turn 2 raw_query: {raw_query}")

        # Check if follow-up contains clinical parameter keywords
        query_lower = raw_query.lower()
        clinical_keywords = {
            "nihss", "aspects", "aspect", "lkw", "last known well",
            "mca", "occlusion", "lvo", "mrs", "hour", "hr",
            "wake-up", "wake up", "cta", "perfusion",
            "m1", "m2", "m3", "ica", "basilar", "vertebral", "pca",
            "carotid",
        }
        has_clinical_content = any(kw in query_lower for kw in clinical_keywords)

        # Also check for bare numeric patterns common in clinical follow-ups
        # e.g., "15, 9, 3 hours" — terse responses to clarification questions
        has_numeric_clinical = bool(re.search(r'\d+\s*[,;]\s*\d+', raw_query))

        if not has_clinical_content and not has_numeric_clinical:
            print(f"  [ClinicalMerge] No clinical content detected, returning None (topic change)")
            return None

        # Reconstruct what we already know from Turn 1 patient dict
        known_parts = []
        if patient.get("age"):
            sex = patient.get("sex", "")
            known_parts.append(f"{patient['age']}yo {sex}".strip())
        if patient.get("occlusion_location"):
            known_parts.append(f"{patient['occlusion_location']} occlusion")
        if patient.get("lvo"):
            known_parts.append("LVO confirmed")
        if patient.get("wake_up_stroke"):
            known_parts.append("wake-up stroke")
        elif patient.get("unknown_onset"):
            known_parts.append("unknown onset")
        if patient.get("last_known_well_hours") is not None:
            known_parts.append(f"LKW {patient['last_known_well_hours']}h")
        if patient.get("nihss") is not None:
            known_parts.append(f"NIHSS {patient['nihss']}")
        if patient.get("aspects") is not None:
            known_parts.append(f"ASPECTS {patient['aspects']}")
        if patient.get("mrs_pre") is not None:
            known_parts.append(f"mRS {patient['mrs_pre']}")
        if patient.get("on_anticoagulation"):
            known_parts.append(f"on {patient.get('anticoagulant_type', 'anticoagulation')}")
        if patient.get("has_perfusion_imaging"):
            known_parts.append("perfusion imaging available")

        # Combine: Turn 1 known data + Turn 2 new data (raw_query, not normalized)
        known_str = ", ".join(known_parts) if known_parts else ""
        if known_str:
            merged = f"{known_str}, {raw_query}"
        else:
            merged = raw_query

        print(f"  [ClinicalMerge] Known parts: {known_parts}")
        print(f"  [ClinicalMerge] Final merged: {merged}")
        return merged

    def _enrich_guideline_query(
        self, normalized_query: str, raw_query: str, clinical_context: dict
    ) -> str | None:
        """Enrich a guideline question with clinical context from previous assessment.

        Returns enriched query string, or None if this isn't a guideline follow-up.
        """
        query_lower = raw_query.lower()

        # Must look like a guideline/evidence question
        guideline_keywords = [
            "guideline", "evidence", "trial", "study", "data",
            "cor ", "loe ", "class of recommendation", "level of evidence",
            "what did", "what does", "what about", "tell me more",
            "show me", "explain", "can you elaborate",
            "subgroup", "analysis", "outcome", "result",
            "hermes", "dawn", "defuse", "select2", "angel", "tension",
            "trace", "timeless", "ninds", "ecass", "escape", "revascat",
            "enchanted", "baoche", "attention", "basics",
            "wake-up", "extend", "rescue",
        ]
        has_guideline_intent = any(kw in query_lower for kw in guideline_keywords)

        if not has_guideline_intent:
            return None

        # Must NOT have patient parameters (that would be Scenario A or C)
        patient_keywords = [
            "nihss", "aspects", "lkw", "last known well",
            "year-old", "yo ", "occlusion", "cta shows",
        ]
        if any(kw in query_lower for kw in patient_keywords):
            return None

        # Must NOT have device intent (that would be Scenario B)
        device_keywords = [
            "device", "catheter", "microcatheter", "stent retriever",
            "configuration", "compatible", "vecta", "headway", "solitaire",
        ]
        if any(kw in query_lower for kw in device_keywords):
            return None

        # Build enrichment context from previous assessment
        patient = clinical_context.get("patient", {})
        eligibility = clinical_context.get("eligibility", [])

        context_parts = []

        if patient.get("mrs_pre") is not None:
            context_parts.append(f"pre-stroke mRS {patient['mrs_pre']}")
        if patient.get("last_known_well_hours") is not None:
            context_parts.append(f"LKW {patient['last_known_well_hours']}h")
        if patient.get("aspects") is not None:
            context_parts.append(f"ASPECTS {patient['aspects']}")
        if patient.get("occlusion_location"):
            context_parts.append(f"{patient['occlusion_location']} occlusion")
        if patient.get("age"):
            context_parts.append(f"age {patient['age']}")

        # Add uncertain/conditional pathways
        uncertain_paths = []
        for e in eligibility:
            elig = e.get("eligibility", "")
            if elig in ("UNCERTAIN", "CONDITIONAL"):
                uncertain_paths.append(e.get("treatment", ""))
        if uncertain_paths:
            context_parts.append(f"pathways flagged: {', '.join(uncertain_paths)}")

        if not context_parts:
            return None

        context_str = "; ".join(context_parts)
        enriched = f"{raw_query} [Clinical context: {context_str}]"
        print(f"  [GuidelineEnrich] Enriched query: {enriched[:200]}")
        return enriched

    def _get_fuzzy_suggestions(self, not_found: list) -> dict:
        """Get fuzzy match suggestions for each unresolved device name."""
        from medsync_ai_v2.shared.device_search import DeviceSearchHelper
        helper = DeviceSearchHelper()
        suggestions = {}
        for name in not_found:
            matches = helper.suggest_close_matches(name, max_suggestions=3)
            suggestions[name] = matches
            if matches:
                print(f"    Suggestions for '{name}': {[m['product_name'] for m in matches]}")
            else:
                print(f"    No suggestions for '{name}'")
        return suggestions

    async def _emit_status(self, broker, agent_name: str, content: str):
        """Emit a status event through the broker."""
        if broker is None:
            return
        await broker.put({
            "type": "status",
            "data": {
                "agent": agent_name,
                "content": content,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        })

    def _track_usage(self, token_usage: dict, tool_name: str, result: dict):
        """Accumulate token usage from an agent result."""
        usage = result.get("usage", {})
        inp = usage.get("input_tokens", 0)
        out = usage.get("output_tokens", 0)
        token_usage["total_input_tokens"] += inp
        token_usage["total_output_tokens"] += out
        token_usage["sub_agent_calls"].append({
            "tool": tool_name,
            "input_tokens": inp,
            "output_tokens": out,
        })
