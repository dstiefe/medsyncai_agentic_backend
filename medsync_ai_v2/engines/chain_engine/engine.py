"""
Chain Engine - Main Engine

Self-contained sub-orchestrator for all device compatibility questions.
Runs a deterministic pipeline: classify -> build chains -> evaluate -> decide -> analyze -> summarize -> quality check.
Returns structured data via the standard return contract.
"""

import os
import copy
import asyncio

from medsync_ai_v2.base_engine import BaseEngine
from medsync_ai_v2.engines.contracts import find_prior_result, transform_device_list_to_category_package
from medsync_ai_v2.engines.chain_engine.query_classifier import QueryClassifier
from medsync_ai_v2.engines.chain_engine.chain_builder import ChainBuilder, map_device_categories
from medsync_ai_v2.engines.chain_engine.compat_evaluator import ChainPairGenerator, ChainFlattenerMulti
from medsync_ai_v2.engines.chain_engine.chain_analyzer import ChainAnalyzerMulti
from medsync_ai_v2.engines.chain_engine.chain_summary import ChainSummaryAgent
from medsync_ai_v2.engines.chain_engine.decision_logic import decide_next_action, run_n1_subsets
from medsync_ai_v2.engines.chain_engine.quality_check import check_quality
from medsync_ai_v2.shared.device_search import get_database


SKILL_PATH = os.path.join(os.path.dirname(__file__), "SKILL.md")


class ChainEngine(BaseEngine):
    """
    Sub-orchestrator for device compatibility checking.

    Pipeline:
    1. prepare inputs (Python) -> resolve prior_results, map categories
    2. query_classifier + chain_builder (parallel LLM) -> classification + chain configs
    3. compat_evaluator (Python) -> pair results
    4. decision_logic (Python) -> enriched results
    5. chain_analyzer (Python) -> rollup analysis
    6. chain_summary (Python) -> narrative summary
    7. quality_check (Python) -> validation
    """

    def __init__(self):
        super().__init__(name="chain_engine", skill_path=SKILL_PATH)

        # Register sub-agents
        self.query_classifier = QueryClassifier()
        self.chain_builder = ChainBuilder()
        self.pair_generator = ChainPairGenerator()

        self.register_agent(self.query_classifier)
        self.register_agent(self.chain_builder)

    def _resolve_input(self, input_data: dict) -> dict:
        """
        Auto-transform prior DB results into category expansion format.

        If prior_results contains a database_engine result with a device_list,
        transform it into a virtual category with pre-resolved product names.
        The existing expand_chains() + update_devices_lookup() pipeline handles
        name resolution — product names come from DB, so exact match is guaranteed.
        """
        prior_results = input_data.get("prior_results", [])
        if not prior_results:
            return input_data

        db_result = find_prior_result(prior_results, "database_engine")
        if not db_result:
            return input_data

        device_list = db_result.get("data", {}).get("device_list", [])
        if not device_list:
            return input_data

        # Use the planner's original category name if available
        category_label = input_data.get("metadata", {}).get("filter_category", "db_filtered")

        package = transform_device_list_to_category_package(device_list, category_label)

        # Merge category_mappings into input
        existing_mappings = dict(input_data.get("category_mappings", {}))
        existing_mappings.update(package["category_mappings"])
        input_data["category_mappings"] = existing_mappings

        # Merge categories list
        existing_cats = list(input_data.get("categories", []))
        for cat in package["categories"]:
            if cat not in existing_cats:
                existing_cats.append(cat)
        input_data["categories"] = existing_cats

        print(f"  [ChainEngine] Resolved prior DB result: {len(device_list)} devices "
              f"-> virtual category '{category_label}' "
              f"with {len(package['category_mappings'][category_label].get('products', []))} products")

        return input_data

    async def run(self, input_data: dict, session_state: dict) -> dict:
        """
        Execute the full chain engine pipeline.

        Args:
            input_data: {
                "normalized_query": str,
                "devices": {"DeviceName": {"ids": [...], "conical_category": "L2"}},
                "categories": ["microcatheter", ...],
                "prior_results": [<EngineOutput dicts>],  (optional)
                "category_mappings": {...},  (optional, pre-built)
                "metadata": {"filter_category": "catheter"},  (optional)
            }
            session_state: Current session state

        Returns:
            Standard return contract dict
        """
        token_usage = {"input_tokens": 0, "output_tokens": 0}

        try:
            # ----------------------------------------------------------
            # Step 1: Prepare inputs (Python — instant)
            # ----------------------------------------------------------
            input_data = self._resolve_input(input_data)
            database = input_data.get("database") or get_database()

            categories = input_data.get("categories", [])
            category_mappings = input_data.get("category_mappings", {})
            if categories and not category_mappings:
                category_mappings = map_device_categories(categories)
            elif categories:
                unmapped = [c for c in categories if c not in category_mappings]
                if unmapped:
                    standard = map_device_categories(unmapped)
                    standard.update(category_mappings)  # pre-built overrides
                    category_mappings = standard

            builder_input = {
                "normalized_query": input_data.get("normalized_query", ""),
                "devices": input_data.get("devices", {}),
                "categories": categories,
                "category_mappings": category_mappings,
                "database": database,
            }

            # ----------------------------------------------------------
            # Step 2: query_classifier + chain_builder (parallel LLM)
            # ----------------------------------------------------------
            print(f"  [ChainEngine] Steps 1+2: query_classifier + chain_builder (parallel)")
            classifier_result, builder_result = await asyncio.gather(
                self.query_classifier.run(input_data, session_state),
                self.chain_builder.run(builder_input, session_state),
            )

            classification = classifier_result.get("content", {})
            self._accumulate_tokens(token_usage, classifier_result.get("usage", {}))

            chains_data = builder_result.get("content", {})
            self._accumulate_tokens(token_usage, builder_result.get("usage", {}))

            chains_to_check = chains_data.get("chains_to_check", [])
            if not chains_to_check:
                return self._build_return(
                    status="error",
                    result_type="compatibility_check",
                    data={"error": "No valid chains could be generated"},
                    classification=classification,
                    confidence=0.0,
                )

            # Merge expanded devices back if category expansion happened
            devices = dict(input_data.get("devices", {}))
            if chains_data.get("expanded_devices"):
                devices.update(chains_data["expanded_devices"])

            # ----------------------------------------------------------
            # Step 4: Evaluate compatibility (Python - pure math)
            # ----------------------------------------------------------
            chain_results = self.pair_generator.generate_chain_pairs(
                chains_to_check, devices, database
            )
            processed_results = self.pair_generator.process_chain_results(chain_results)

            # ----------------------------------------------------------
            # Step 5: Analyze chains (Python - rollup)
            # ----------------------------------------------------------
            analyzer = ChainAnalyzerMulti(processed_results)
            chain_summary = analyzer.get_summary()

            # ----------------------------------------------------------
            # Step 6: Decision logic (Python - business rules)
            # ----------------------------------------------------------
            decision = decide_next_action(classification, chain_summary)
            subset_analysis = None

            if decision["action"] == "run_n1_subsets":
                subset_analysis = run_n1_subsets(chains_to_check, devices, database)

            # ----------------------------------------------------------
            # Step 7: Generate rich text summary (Python - deterministic)
            # ----------------------------------------------------------
            from medsync_ai_v2.engines.chain_engine.chain_text_builder import ChainTextBuilder

            result_type = self._determine_result_type(classification)
            text_builder = ChainTextBuilder(chain_summary, processed_results, subset_analysis)
            text_summary = ""
            try:
                text_summary = text_builder.build(result_type)
            except Exception as e:
                print(f"  [ChainEngine] Text builder error: {e}")
                text_summary = f"Summary generation error: {str(e)}"

            # ----------------------------------------------------------
            # Step 8: Flatten for output
            # ----------------------------------------------------------
            flattener = ChainFlattenerMulti(processed_results)
            flat_data = flattener.flatten().get("data", [])

            # ----------------------------------------------------------
            # Step 9: Quality check (Python)
            # ----------------------------------------------------------
            result_data = {
                "chain_summary": chain_summary,
                "flat_data": flat_data,
                "text_summary": text_summary,
                "chains_tested": chains_to_check,
                "decision": decision,
                "subset_analysis": subset_analysis,
                "token_usage": token_usage,
            }

            result = self._build_return(
                status="complete",
                result_type=self._determine_result_type(classification),
                data=result_data,
                classification=classification,
                confidence=classification.get("confidence", 0.9),
            )

            quality = check_quality(input_data, result)
            result["quality_check"] = quality

            return result

        except Exception as e:
            return self._build_return(
                status="error",
                result_type="compatibility_check",
                data={"error": str(e)},
                classification=classification if 'classification' in dir() else {},
                confidence=0.0,
            )

    def _determine_result_type(self, classification: dict) -> str:
        """Map classification to result_type."""
        sub_type = classification.get("sub_type", "")
        if sub_type:
            return sub_type.lower()

        mode = classification.get("query_mode", "specific")
        structure = classification.get("structure", "two_device")

        if mode == "stack_validation" or structure == "multi_device":
            return "stack_validation"
        elif mode in ("exploratory", "discovery"):
            return "device_discovery"
        else:
            return "compatibility_check"

    def _accumulate_tokens(self, total: dict, usage: dict):
        total["input_tokens"] += usage.get("input_tokens", 0)
        total["output_tokens"] += usage.get("output_tokens", 0)
