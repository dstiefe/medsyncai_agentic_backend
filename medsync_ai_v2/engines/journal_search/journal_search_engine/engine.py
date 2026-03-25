"""
JournalSearchEngine — Main engine for searching clinical trial evidence.

Pipeline:
  1. QueryParsingAgent (LLM) → structured query variables
     - Detects comparison queries (two populations)
     - Detects vague queries (triggers clarification)
  2. TrialMatcher (Python/CMI) → tiered trial matches
     - For comparisons: runs two separate searches
     - If too many matches + few variables: generates clarification menu
  3. EvidenceSynthesizer (LLM) → evidence-based answer (database only)
  4. Figure matching → attach relevant figures from matched trials

Follows the BaseEngine pattern with _build_return() contract.
"""

from __future__ import annotations

import json
from medsync_ai_v2.base_engine import BaseEngine
from .agents.query_parsing_agent import QueryParsingAgent
from .agents.evidence_synthesizer import EvidenceSynthesizer
from .services.trial_matcher import TrialMatcher
from .protocols.intent_classifier import IntentClassifier
from .protocols.protocol_router import route_protocol
from .protocols.formatter import format_result as format_protocol_result
from .models.query import (
    SearchResult, ComparisonResult, ParsedQuery,
    ClarificationMenu, ClarificationGroup, ClarificationOption,
    RangeFilter,
)

# Threshold: if Tier 1 matches exceed this and query has few variables, clarify
CLARIFICATION_THRESHOLD = 8


class JournalSearchEngine(BaseEngine):
    """Search clinical trial evidence using LLM-parsed queries and CMI matching."""

    def __init__(self):
        super().__init__(name="journal_search_engine", skill_path=None)
        self._intent_classifier = IntentClassifier()
        self._query_parser = QueryParsingAgent()
        self._trial_matcher = TrialMatcher()
        self._synthesizer = EvidenceSynthesizer()

        self.register_agent(self._intent_classifier)
        self.register_agent(self._query_parser)
        self.register_agent(self._synthesizer)

    async def run(self, input_data: dict, session_state: dict) -> dict:
        """Run the full journal search pipeline."""
        raw_query = input_data.get("raw_query", "")
        query_text = input_data.get("normalized_query", raw_query)

        token_usage = {"input_tokens": 0, "output_tokens": 0}

        # ── Check if this is a clarification reply (e.g., "A1") ──
        pending_clarification = session_state.get("journal_clarification")
        if pending_clarification and self._is_clarification_reply(query_text):
            return await self._handle_clarification_reply(
                query_text, pending_clarification, session_state, token_usage
            )

        # ── Step 0: Classify intent (CMI vs extraction protocol) ──
        classified, classify_usage = await self._intent_classifier.classify(query_text)
        self._add_usage(token_usage, classify_usage)

        if classified.intent_type == "extraction" and classified.protocol:
            # Route to extraction protocol — bypasses CMI entirely
            result = await route_protocol(classified)
            formatted = format_protocol_result(result)

            return self._build_return(
                status="complete",
                result_type="journal_extraction_result",
                data={
                    "formatted_text": formatted,
                    "protocol": result.protocol,
                    "extraction_data": result.data,
                    "data_found": result.data_found,
                    "missing_fields": result.missing_fields,
                    "trial_acronym": result.trial_acronym,
                    "token_usage": token_usage,
                },
                classification={
                    "query_type": "journal_extraction",
                    "protocol": result.protocol,
                },
                confidence=0.95 if result.data_found else 0.40,
            )

        # ── Step 1: Parse query (LLM) — CMI pathway ──
        parsed_result, parse_usage = await self._query_parser.parse_query(query_text)
        self._add_usage(token_usage, parse_usage)

        # Handle comparison queries
        if isinstance(parsed_result, dict) and parsed_result.get("is_comparison"):
            return await self._handle_comparison(parsed_result, session_state, token_usage)

        parsed = parsed_result
        if not isinstance(parsed, ParsedQuery):
            parsed = parsed_result

        # ── Step 2: Match (CMI) — run even for vague queries to inform the menu ──
        matches = self._trial_matcher.match(parsed)
        tier1_count = sum(1 for m in matches if m.tier == 1)
        scenario_vars = self._trial_matcher._get_scenario_variables(parsed)

        # ── Check if clarification needed ──
        needs_menu = (
            parsed.needs_clarification or
            (tier1_count > CLARIFICATION_THRESHOLD and len(scenario_vars) <= 2)
        )

        if needs_menu:
            menu = self._build_clarification_menu(parsed, matches, tier1_count)
            # Store in session for reply handling
            session_state["journal_clarification"] = {
                "menu": menu.model_dump(),
                "partial_query": parsed.model_dump(),
            }
            return self._build_return(
                status="needs_clarification",
                result_type="journal_search_clarification_menu",
                data={
                    "formatted_text": self._format_menu(menu),
                    "menu": menu.model_dump(),
                    "token_usage": token_usage,
                },
                classification={"query_type": "journal_search"},
                confidence=0.5,
            )

        # ── Step 3: Synthesize (LLM, database only) ──
        top_matches = self._select_top_matches(matches, max_trials=8)
        synthesis, synth_usage = await self._synthesizer.synthesize(parsed, top_matches)
        self._add_usage(token_usage, synth_usage)

        # ── Step 4: Collect relevant figures ──
        figures = self._collect_figures(top_matches, parsed)

        # ── Build result ──
        tier_counts = {1: 0, 2: 0, 3: 0, 4: 0}
        for m in matches:
            tier_counts[m.tier] += 1

        result = SearchResult(
            query=parsed,
            matched_trials=[
                m.model_copy(update={"methods_text": "", "results_text": ""})
                for m in matches
            ],
            tier_counts=tier_counts,
            synthesis=synthesis,
            total_trials_searched=self._trial_matcher.trial_count,
            figures=figures,
        )

        confidence = 0.90 if tier_counts[1] > 0 else 0.75 if tier_counts[2] > 0 else 0.50

        # Clear any pending clarification
        session_state.pop("journal_clarification", None)

        return self._build_return(
            status="complete",
            result_type="journal_search_result",
            data={
                "formatted_text": synthesis,
                "search_result": result.model_dump(),
                "token_usage": token_usage,
            },
            classification={"query_type": "journal_search"},
            confidence=confidence,
        )

    # ── Comparison handling ──────────────────────────────────────

    async def _handle_comparison(self, comp_data: dict, session_state: dict, token_usage: dict) -> dict:
        """Handle a comparison query by running two CMI searches."""
        from .agents.query_parsing_agent import QueryParsingAgent

        query_a_data = comp_data.get("query_a", {})
        query_b_data = comp_data.get("query_b", {})

        query_a = QueryParsingAgent._build_parsed_query(query_a_data, query_a_data.get("clinical_question", ""))
        query_b = QueryParsingAgent._build_parsed_query(query_b_data, query_b_data.get("clinical_question", ""))

        matches_a = self._trial_matcher.match(query_a)
        matches_b = self._trial_matcher.match(query_b)

        top_a = self._select_top_matches(matches_a, max_trials=6)
        top_b = self._select_top_matches(matches_b, max_trials=6)

        # Synthesize comparison
        synthesis, synth_usage = await self._synthesizer.synthesize_comparison(
            query_a, query_b,
            top_a, top_b,
            comp_data.get("comparison_label_a", "Population A"),
            comp_data.get("comparison_label_b", "Population B"),
        )
        self._add_usage(token_usage, synth_usage)

        figures_a = self._collect_figures(top_a, query_a)
        figures_b = self._collect_figures(top_b, query_b)

        tier_counts_a = {1: 0, 2: 0, 3: 0, 4: 0}
        for m in matches_a:
            tier_counts_a[m.tier] += 1
        tier_counts_b = {1: 0, 2: 0, 3: 0, 4: 0}
        for m in matches_b:
            tier_counts_b[m.tier] += 1

        result = ComparisonResult(
            label_a=comp_data.get("comparison_label_a", ""),
            label_b=comp_data.get("comparison_label_b", ""),
            result_a=SearchResult(
                query=query_a,
                matched_trials=[m.model_copy(update={"methods_text": "", "results_text": ""}) for m in matches_a],
                tier_counts=tier_counts_a,
                total_trials_searched=self._trial_matcher.trial_count,
                figures=figures_a,
            ),
            result_b=SearchResult(
                query=query_b,
                matched_trials=[m.model_copy(update={"methods_text": "", "results_text": ""}) for m in matches_b],
                tier_counts=tier_counts_b,
                total_trials_searched=self._trial_matcher.trial_count,
                figures=figures_b,
            ),
            synthesis=synthesis,
        )

        return self._build_return(
            status="complete",
            result_type="journal_search_comparison",
            data={
                "formatted_text": synthesis,
                "comparison_result": result.model_dump(),
                "token_usage": token_usage,
            },
            classification={"query_type": "journal_search_comparison"},
            confidence=0.85,
        )

    # ── Clarification menu ───────────────────────────────────────

    def _build_clarification_menu(
        self, query: ParsedQuery, matches: list, tier1_count: int
    ) -> ClarificationMenu:
        """Build a lettered/numbered clarification menu based on what's missing."""
        groups = []

        # Determine what the user already specified
        has_intervention = query.intervention is not None
        has_circulation = query.circulation is not None
        has_aspects = query.aspects_range is not None
        has_time = query.time_window_hours is not None
        has_vessel = query.vessel_occlusion is not None

        # Intervention — if not specified
        if not has_intervention:
            groups.append(ClarificationGroup(
                label="What treatment?",
                options=[
                    ClarificationOption(key="A", label="EVT (thrombectomy)", variable="intervention", value={"intervention": "EVT"}),
                    ClarificationOption(key="B", label="IVT (thrombolysis)", variable="intervention", value={"intervention": "IVT"}),
                    ClarificationOption(key="C", label="Tenecteplase", variable="intervention", value={"intervention": "tenecteplase"}),
                ],
            ))

        # Circulation — if not specified and intervention is EVT-related
        if not has_circulation and not has_vessel:
            groups.append(ClarificationGroup(
                label="Which circulation?",
                options=[
                    ClarificationOption(key="D", label="Anterior", variable="circulation", value={"circulation": "anterior"}),
                    ClarificationOption(key="E", label="Posterior (basilar)", variable="circulation", value={"circulation": "basilar"}),
                    ClarificationOption(key="F", label="Either", variable="circulation", value={}),
                ],
            ))

        # ASPECTS — if not specified
        if not has_aspects:
            groups.append(ClarificationGroup(
                label="ASPECTS range?",
                options=[
                    ClarificationOption(key="1", label="≥6 (favorable)", variable="aspects_range", value={"aspects_range": {"min": 6, "max": 10}}),
                    ClarificationOption(key="2", label="3-5 (large core)", variable="aspects_range", value={"aspects_range": {"min": 3, "max": 5}}),
                    ClarificationOption(key="3", label="0-2 (very large core)", variable="aspects_range", value={"aspects_range": {"min": 0, "max": 2}}),
                    ClarificationOption(key="4", label="Any", variable="aspects_range", value={}),
                ],
            ))

        # Time window — if not specified
        if not has_time:
            groups.append(ClarificationGroup(
                label="Time window?",
                options=[
                    ClarificationOption(key="5", label="Within 6 hours", variable="time_window_hours", value={"time_window_hours": {"min": 0, "max": 6}}),
                    ClarificationOption(key="6", label="6-24 hours", variable="time_window_hours", value={"time_window_hours": {"min": 6, "max": 24}}),
                    ClarificationOption(key="7", label="Any", variable="time_window_hours", value={}),
                ],
            ))

        # Build message
        if tier1_count > 0:
            msg = f"Your query matches {tier1_count} trials. To give you a focused answer, which applies?"
        else:
            msg = "I need a bit more detail to search the trial database. Which applies?"

        return ClarificationMenu(
            message=msg,
            groups=groups,
            partial_query=query,
            tier1_count=tier1_count,
        )

    @staticmethod
    def _format_menu(menu: ClarificationMenu) -> str:
        """Format the clarification menu as text for the user."""
        lines = [menu.message, ""]
        for group in menu.groups:
            lines.append(f"**{group.label}**")
            for opt in group.options:
                lines.append(f"  {opt.key}. {opt.label}")
            lines.append("")
        lines.append("Enter your choices (e.g., \"A1\" or \"B2, 6\").")
        return "\n".join(lines)

    @staticmethod
    def _is_clarification_reply(text: str) -> bool:
        """Check if user input looks like a clarification reply (e.g., 'A1', 'B, 2')."""
        clean = text.strip().upper().replace(",", "").replace(" ", "")
        if len(clean) <= 6 and all(c.isalnum() for c in clean):
            return True
        return False

    async def _handle_clarification_reply(
        self, reply: str, pending: dict, session_state: dict, token_usage: dict
    ) -> dict:
        """Parse a clarification reply like 'A1' and re-run with refined query."""
        menu_data = pending.get("menu", {})
        partial_data = pending.get("partial_query", {})

        # Parse reply characters
        clean = reply.strip().upper().replace(",", "").replace(" ", "")

        # Build option lookup from menu
        option_map = {}
        for group in menu_data.get("groups", []):
            for opt in group.get("options", []):
                option_map[opt["key"].upper()] = opt.get("value", {})

        # Apply selected options to the partial query
        updates = {}
        for char in clean:
            if char in option_map:
                updates.update(option_map[char])

        # Rebuild query with updates
        for key, val in updates.items():
            if isinstance(val, dict) and val:
                if key in ("aspects_range", "nihss_range", "age_range", "core_volume_ml", "mismatch_ratio", "premorbid_mrs"):
                    partial_data[key] = val
                elif key == "time_window_hours":
                    partial_data[key] = val
            elif isinstance(val, str):
                partial_data[key] = val

        # Clear clarification state
        session_state.pop("journal_clarification", None)

        # Re-run with the refined query
        from .agents.query_parsing_agent import QueryParsingAgent
        refined_query = QueryParsingAgent._build_parsed_query(partial_data, partial_data.get("clinical_question", ""))

        matches = self._trial_matcher.match(refined_query)
        top_matches = self._select_top_matches(matches, max_trials=8)
        synthesis, synth_usage = await self._synthesizer.synthesize(refined_query, top_matches)
        self._add_usage(token_usage, synth_usage)

        figures = self._collect_figures(top_matches, refined_query)

        tier_counts = {1: 0, 2: 0, 3: 0, 4: 0}
        for m in matches:
            tier_counts[m.tier] += 1

        result = SearchResult(
            query=refined_query,
            matched_trials=[m.model_copy(update={"methods_text": "", "results_text": ""}) for m in matches],
            tier_counts=tier_counts,
            synthesis=synthesis,
            total_trials_searched=self._trial_matcher.trial_count,
            figures=figures,
        )

        return self._build_return(
            status="complete",
            result_type="journal_search_result",
            data={
                "formatted_text": synthesis,
                "search_result": result.model_dump(),
                "token_usage": token_usage,
            },
            classification={"query_type": "journal_search"},
            confidence=0.85 if tier_counts[1] > 0 else 0.65,
        )

    # ── Figure collection ────────────────────────────────────────

    @staticmethod
    def _collect_figures(matches: list, query: ParsedQuery) -> list[dict]:
        """Collect relevant figures from matched trials."""
        figures = []
        outcome_focus = (query.outcome_focus or "").lower()

        for m in matches:
            # Figures are stored in the trial data (added by extract_tables_and_figures)
            # We need to get them from the raw trial data, not the MatchedTrial model
            # For now, collect from results if they reference figures
            pass

        # TODO: Pull figures from trial database entries based on match
        return figures

    # ── Helpers ───────────────────────────────────────────────────

    @staticmethod
    def _select_top_matches(matches, max_trials=8):
        """Select highest-tier matches up to max, preferring Tier 1 and RCTs."""
        selected = []
        for tier in [1, 2, 3, 4]:
            tier_matches = [m for m in matches if m.tier == tier]
            for m in tier_matches:
                if len(selected) >= max_trials:
                    return selected
                selected.append(m)
        return selected

    @staticmethod
    def _add_usage(total: dict, usage: dict):
        total["input_tokens"] += usage.get("input_tokens", 0)
        total["output_tokens"] += usage.get("output_tokens", 0)
