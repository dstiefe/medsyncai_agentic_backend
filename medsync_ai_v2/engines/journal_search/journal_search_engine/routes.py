"""
REST API routes for the Journal Search Engine.

Endpoints:
  POST /journal/search          — Natural language search (LLM parsing + matching)
  POST /journal/search/structured — Direct structured search (bypass LLM parsing)
  GET  /journal/trials          — List all trials in the database
  GET  /journal/figures/{filename} — Serve a figure image
  GET  /journal/health          — Health check
"""

from __future__ import annotations

import os
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from typing import Optional, List

from .engine import JournalSearchEngine
from .services.trial_matcher import TrialMatcher
from .models.query import ParsedQuery, RangeFilter, TimeWindowFilter
from .data.loader import load_trials, get_database_summary

router = APIRouter(prefix="/journal", tags=["journal_search"])

# Lazy engine instance
_engine: JournalSearchEngine | None = None


def _get_engine() -> JournalSearchEngine:
    global _engine
    if _engine is None:
        _engine = JournalSearchEngine()
    return _engine


# ── Request/Response Models ──────────────────────────────────────


class SearchRequest(BaseModel):
    """Natural language search request."""
    query: str
    session_id: Optional[str] = None


class StructuredSearchRequest(BaseModel):
    """Direct structured search request (bypass LLM parsing)."""
    aspects_range: Optional[dict] = None
    pc_aspects_range: Optional[dict] = None
    nihss_range: Optional[dict] = None
    age_range: Optional[dict] = None
    time_window_hours: Optional[dict] = None
    core_volume_ml: Optional[dict] = None
    mismatch_ratio: Optional[dict] = None
    premorbid_mrs: Optional[dict] = None
    vessel_occlusion: Optional[List[str]] = None
    imaging_required: Optional[List[str]] = None
    intervention: Optional[str] = None
    comparator: Optional[str] = None
    study_type: Optional[str] = None
    circulation: Optional[str] = None


class SearchResponse(BaseModel):
    """Search response."""
    status: str
    synthesis: str = ""
    tier_counts: dict = Field(default_factory=dict)
    matched_trials: list = Field(default_factory=list)
    total_trials_searched: int = 0
    confidence: float = 0.0
    clarification_menu: Optional[dict] = None


# ── Endpoints ────────────────────────────────────────────────────


@router.post("/search", response_model=SearchResponse)
async def search_trials(request: SearchRequest):
    """Search trial database with a natural language clinical question."""
    engine = _get_engine()
    result = await engine.run(
        {"raw_query": request.query, "normalized_query": request.query},
        {},  # session_state
    )

    data = result.get("data", {})
    result_type = result.get("result_type", "")

    # Handle comparison results — flatten into the standard response format
    if result_type == "journal_search_comparison":
        comp = data.get("comparison_result", {})
        result_a = comp.get("result_a", {})
        result_b = comp.get("result_b", {})
        # Merge matched trials from both sides
        all_trials = result_a.get("matched_trials", []) + result_b.get("matched_trials", [])
        # Merge tier counts
        tc_a = result_a.get("tier_counts", {})
        tc_b = result_b.get("tier_counts", {})
        merged_tiers = {}
        for k in set(list(tc_a.keys()) + list(tc_b.keys())):
            merged_tiers[k] = tc_a.get(k, 0) + tc_b.get(k, 0)

        return SearchResponse(
            status=result.get("status", "error"),
            synthesis=data.get("formatted_text", ""),
            tier_counts=merged_tiers,
            matched_trials=all_trials,
            total_trials_searched=result_a.get("total_trials_searched", 45),
            confidence=result.get("confidence", 0.0),
        )

    # Handle clarification
    if result_type in ("journal_search_clarification", "journal_search_clarification_menu"):
        return SearchResponse(
            status=result.get("status", "needs_clarification"),
            synthesis=data.get("formatted_text", ""),
            clarification_menu=data.get("menu"),
            tier_counts={},
            matched_trials=[],
            total_trials_searched=0,
            confidence=result.get("confidence", 0.0),
        )

    # Standard result
    search_result = data.get("search_result", {})
    return SearchResponse(
        status=result.get("status", "error"),
        synthesis=data.get("formatted_text", ""),
        tier_counts=search_result.get("tier_counts", {}),
        matched_trials=search_result.get("matched_trials", []),
        total_trials_searched=search_result.get("total_trials_searched", 0),
        confidence=result.get("confidence", 0.0),
    )


@router.post("/search/structured", response_model=SearchResponse)
async def search_structured(request: StructuredSearchRequest):
    """Search with pre-parsed structured variables (bypass LLM parsing)."""

    def _to_range(val):
        if val is None:
            return None
        return RangeFilter(min=val.get("min"), max=val.get("max"))

    def _to_tw(val):
        if val is None:
            return None
        return TimeWindowFilter(min=val.get("min"), max=val.get("max"), reference=val.get("reference"))

    parsed = ParsedQuery(
        aspects_range=_to_range(request.aspects_range),
        pc_aspects_range=_to_range(request.pc_aspects_range),
        nihss_range=_to_range(request.nihss_range),
        age_range=_to_range(request.age_range),
        time_window_hours=_to_tw(request.time_window_hours),
        core_volume_ml=_to_range(request.core_volume_ml),
        mismatch_ratio=_to_range(request.mismatch_ratio),
        premorbid_mrs=_to_range(request.premorbid_mrs),
        vessel_occlusion=request.vessel_occlusion,
        imaging_required=request.imaging_required,
        intervention=request.intervention,
        comparator=request.comparator,
        study_type=request.study_type,
        circulation=request.circulation,
        clinical_question="Structured search",
    )

    matcher = TrialMatcher()
    matches = matcher.match(parsed)

    tier_counts = {1: 0, 2: 0, 3: 0, 4: 0}
    for m in matches:
        tier_counts[m.tier] += 1

    return SearchResponse(
        status="complete",
        tier_counts=tier_counts,
        matched_trials=[
            m.model_dump(exclude={"methods_text", "results_text"})
            for m in matches
        ],
        total_trials_searched=matcher.trial_count,
        confidence=0.85 if tier_counts.get(1, 0) > 0 else 0.7,
    )


@router.post("/search/fast", response_model=SearchResponse)
async def search_fast(request: SearchRequest):
    """
    Fast search: LLM parses query → Python matches → Python formats summary.
    No LLM synthesis. Returns in 2-4 seconds.

    The frontend calls this first, displays the result immediately,
    then calls /search/deep for the LLM narrative (expandable section).
    """
    engine = _get_engine()
    parsed_result, _ = await engine._query_parser.parse_query(request.query)

    # Handle clarification
    if isinstance(parsed_result, dict) and parsed_result.get("is_comparison"):
        # For comparisons, fall through to the full search
        return await search_trials(request)

    parsed = parsed_result
    if not isinstance(parsed, ParsedQuery):
        return SearchResponse(
            status="needs_clarification",
            synthesis=str(parsed_result),
            tier_counts={},
            matched_trials=[],
            total_trials_searched=0,
            confidence=0.3,
        )

    if parsed.needs_clarification:
        matches = engine._trial_matcher.match(parsed)
        tier1_count = sum(1 for m in matches if m.tier == 1)
        menu = engine._build_clarification_menu(parsed, matches, tier1_count)
        return SearchResponse(
            status="needs_clarification",
            synthesis=engine._format_menu(menu),
            clarification_menu=menu.model_dump(),
            tier_counts={},
            matched_trials=[],
            total_trials_searched=0,
            confidence=0.3,
        )

    # Match trials
    matches = engine._trial_matcher.match(parsed)
    top_matches = engine._select_top_matches(matches, max_trials=8)

    # Python-formatted summary (no LLM)
    summary = _python_format_summary(parsed, top_matches)

    tier_counts = {1: 0, 2: 0, 3: 0, 4: 0}
    for m in matches:
        tier_counts[m.tier] += 1

    return SearchResponse(
        status="fast_complete",
        synthesis=summary,
        tier_counts=tier_counts,
        matched_trials=[
            m.model_dump(exclude={"methods_text", "results_text"})
            for m in matches
        ],
        total_trials_searched=engine._trial_matcher.trial_count,
        confidence=0.85 if tier_counts.get(1, 0) > 0 else 0.7,
    )


@router.post("/search/deep", response_model=SearchResponse)
async def search_deep(request: SearchRequest):
    """
    Deep search: Full pipeline including LLM narrative synthesis.
    Takes 8-15 seconds. Frontend shows this in the expandable section
    with notification dot when it arrives.
    """
    return await search_trials(request)


def _python_format_summary(parsed: ParsedQuery, matches: list) -> str:
    """Format a structured summary from matched trials — no LLM, pure Python."""
    if not matches:
        return "No trials in the database match the specified criteria."

    lines = []

    # Group by tier
    tier1 = [m for m in matches if m.tier == 1]
    tier2 = [m for m in matches if m.tier == 2]

    if tier1:
        lines.append(f"**{len(tier1)} Tier 1 match{'es' if len(tier1) > 1 else ''}** (exact criteria match):\n")
        for m in tier1:
            year = m.metadata.get("year", "?")
            stype = m.metadata.get("study_type", "?")
            journal = m.metadata.get("journal", "")

            line = f"- **{m.trial_id}** ({year}, {stype}"
            if journal:
                line += f", {journal}"
            line += ")"

            # Primary outcome
            primary = m.results.get("primary_outcome", {})
            if primary and primary.get("metric"):
                iv = primary.get("intervention_value", "?")
                cv = primary.get("control_value", "?")
                line += f"\n  {primary['metric']}: {iv} vs {cv}"
                if primary.get("p_value"):
                    line += f" (P={primary['p_value']})"

            # Safety
            safety = m.results.get("safety", {})
            safety_parts = []
            if safety.get("sich_intervention"):
                safety_parts.append(f"sICH: {safety['sich_intervention']} vs {safety.get('sich_control', '?')}")
            if safety.get("mortality_90d_intervention"):
                safety_parts.append(f"Mortality: {safety['mortality_90d_intervention']} vs {safety.get('mortality_90d_control', '?')}")
            if safety_parts:
                line += f"\n  {'; '.join(safety_parts)}"

            lines.append(line)

    if tier2:
        lines.append(f"\n**{len(tier2)} Tier 2 match{'es' if len(tier2) > 1 else ''}** with overlapping criteria available.")

    return "\n".join(lines)


@router.get("/trials")
async def list_trials():
    """List all trials in the database with metadata."""
    trials = load_trials()
    return [
        {
            "trial_id": t.get("trial_id"),
            "metadata": t.get("metadata"),
            "intervention": t.get("intervention"),
            "inclusion_criteria": t.get("inclusion_criteria"),
            "confidence_flags": t.get("confidence_flags"),
        }
        for t in trials
    ]


@router.get("/figures/{filename}")
async def serve_figure(filename: str):
    """Serve a figure image from the figures directory."""
    figures_dir = os.path.normpath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..", "..", "..", "..", "..", "..", "..",
        "MedSync-Journal-Search", "figures",
    ))
    # Allow env var override
    figures_dir = os.getenv("JOURNAL_FIGURES_DIR", figures_dir)

    # Security: only allow PNG/JPG filenames, no path traversal
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    if not filename.endswith((".png", ".jpg", ".jpeg")):
        raise HTTPException(status_code=400, detail="Only PNG/JPG files supported")

    file_path = os.path.join(figures_dir, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Figure not found")

    return FileResponse(file_path, media_type="image/png")


@router.get("/health")
async def health():
    """Health check — returns database summary."""
    summary = get_database_summary()
    return {"status": "ok", **summary}
