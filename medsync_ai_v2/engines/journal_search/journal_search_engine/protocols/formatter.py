"""
Protocol Formatter — converts ProtocolResult data into readable text.

P1, P7: pure Python formatting (no LLM call).
P2-P6, P8, multi: minimal LLM call for readability.

Rule 9: The LLM formats, it does not interpret.
Rule 10: NULL → "Not reported in the provided data"
"""

from __future__ import annotations
from ..models.query import ProtocolResult
from .db_access import NOT_REPORTED


def format_result(result: ProtocolResult) -> str:
    """Format a ProtocolResult into readable text. Pure Python, no LLM."""
    if not result.data_found:
        return _format_not_found(result)

    formatter = _FORMATTERS.get(result.protocol, _format_generic)
    return formatter(result)


def _format_not_found(result: ProtocolResult) -> str:
    """Format a not-found result."""
    error = result.data.get("error")
    if error:
        return error
    msg = result.data.get("message", NOT_REPORTED)
    if result.trial_acronym:
        return f"**{result.trial_acronym}**: {msg}"
    return msg


def _format_p1(result: ProtocolResult) -> str:
    """P1: Single field — simple key-value."""
    d = result.data
    trial = d.get("trial", result.trial_acronym or "")
    field = d.get("field", "")
    values = d.get("values", {})

    if isinstance(values, dict):
        parts = []
        for k, v in values.items():
            label = k.replace("_", " ").replace("min hours", "minimum").replace("max hours", "maximum")
            parts.append(f"{label}: {v}")
        value_str = ", ".join(parts) if parts else NOT_REPORTED
    else:
        value_str = str(values) if values else NOT_REPORTED

    return f"**{trial}** — {field}: {value_str}"


def _format_p2(result: ProtocolResult) -> str:
    """P2: Multi-field single row — structured output."""
    d = result.data
    trial = d.get("trial", result.trial_acronym or "")
    table = d.get("table", "")

    if "row" in d:
        row = d["row"]
        lines = [f"**{trial}** — {_table_label(table)}:\n"]
        for k, v in row.items():
            if k in ("study_id", "arm_id", "outcome_id", "safety_id"):
                continue
            label = _clean_label(k)
            lines.append(f"- **{label}**: {v}")
        if result.missing_fields:
            lines.append(f"\n*Fields not reported: {', '.join(_clean_label(f) for f in result.missing_fields[:5])}*")
        return "\n".join(lines)

    if "rows" in d:
        rows = d["rows"]
        lines = [f"**{trial}** — {_table_label(table)} ({d.get('count', len(rows))} entries):\n"]
        for i, row in enumerate(rows, 1):
            name = row.get("outcome_name") or row.get("metric_name") or f"Entry {i}"
            lines.append(f"**{i}. {name}**")
            for k, v in row.items():
                if k in ("study_id", "arm_id", "outcome_id", "outcome_rank"):
                    continue
                if k == "outcome_name" or k == "metric_name":
                    continue
                label = _clean_label(k)
                lines.append(f"  - {label}: {v}")
            lines.append("")
        return "\n".join(lines)

    return f"**{trial}** — {table}: {NOT_REPORTED}"


def _format_p3(result: ProtocolResult) -> str:
    """P3: Multi-row list — grouped output."""
    d = result.data
    trial = d.get("trial", result.trial_acronym or "")
    table = d.get("table", "")
    grouped = d.get("grouped", {})

    lines = [f"**{trial}** — {_table_label(table)} ({d.get('count', 0)} items):\n"]

    for category, items in grouped.items():
        lines.append(f"### {_clean_label(category)}")
        for item in items:
            # For inclusion/exclusion criteria, show criterion_text
            text = item.get("criterion_text") or item.get("arm_name") or item.get("variable_name") or str(item)
            if isinstance(text, dict):
                text = str(text)
            detail = ""
            # Add ranges if available
            if item.get("numeric_min") is not None or item.get("numeric_max") is not None:
                mn = item.get("numeric_min", "")
                mx = item.get("numeric_max", "")
                detail = f" [{mn}–{mx}]"
            lines.append(f"- {text}{detail}")
        lines.append("")

    return "\n".join(lines)


def _format_p4(result: ProtocolResult) -> str:
    """P4: Cross-trial comparison — side-by-side."""
    d = result.data
    trials = d.get("trials", [])
    lines = [f"**Comparison of {d.get('trial_count', len(trials))} trials:**\n"]

    for t in trials:
        tid = t.get("trial_id", "?")
        meta = t.get("metadata", {})
        year = meta.get("year", "?")
        stype = meta.get("study_type", "?")
        n = meta.get("sample_size", "?")

        lines.append(f"### {tid} ({year}, {stype}, n={n})")

        # Primary outcomes
        for po in t.get("primary_outcomes", []):
            name = po.get("outcome_name", "Primary")
            iv = po.get("intervention_result", NOT_REPORTED)
            cv = po.get("control_result", NOT_REPORTED)
            p = po.get("p_value", "")
            lines.append(f"- **{name}**: {iv} vs {cv}" + (f" (P={p})" if p else ""))

        # Safety
        for so in t.get("safety_outcomes", []):
            sich = so.get("sich_intervention_pct")
            mort = so.get("mortality_intervention_pct")
            if sich is not None:
                sich_c = so.get('sich_control_pct', '?')
                lines.append(f"- sICH: {_fmt_pct(sich)} vs {_fmt_pct(sich_c)}")
            if mort is not None:
                mort_c = so.get('mortality_control_pct', '?')
                lines.append(f"- Mortality: {_fmt_pct(mort)} vs {_fmt_pct(mort_c)}")

        lines.append("")

    not_found = d.get("not_found", [])
    if not_found:
        lines.append(f"*Not found in database: {', '.join(not_found)}*")

    return "\n".join(lines)


def _format_p5(result: ProtocolResult) -> str:
    """P5: Guideline tables."""
    d = result.data
    if "findings" in d:
        lines = ["**Guideline findings:**\n"]
        for f in d["findings"]:
            lines.append(f"### {f.get('source', '?')} ({f.get('year', '?')})")
            lines.append(f.get("key_findings", NOT_REPORTED))
            lines.append("")
        return "\n".join(lines)

    tables = d.get("tables", [])
    lines = [f"**{len(tables)} guideline table(s) found:**\n"]
    for t in tables:
        title = t.get("table_title", "Untitled")
        source = t.get("source_guideline", "")
        lines.append(f"### {title} ({source})")
        headers = t.get("headers", [])
        if headers:
            lines.append("| " + " | ".join(str(h) for h in headers) + " |")
            lines.append("| " + " | ".join("---" for _ in headers) + " |")
        for row_data in t.get("data", [])[:10]:
            if isinstance(row_data, list):
                lines.append("| " + " | ".join(str(c) for c in row_data) + " |")
        lines.append("")
    return "\n".join(lines)


def _format_p6(result: ProtocolResult) -> str:
    """P6: Management protocols — same format as P5."""
    return _format_p5(result)


def _format_p7(result: ProtocolResult) -> str:
    """P7: Definitions."""
    d = result.data
    term = d.get("term", "")
    defn = d.get("definition", {})

    if isinstance(defn, dict):
        lines = []
        if defn.get("scale"):
            lines.append(f"## {defn['scale']}")
        if defn.get("description"):
            lines.append(f"\n{defn['description']}\n")
        if defn.get("grades"):
            for grade, desc in defn["grades"].items():
                lines.append(f"- **Grade {grade}**: {desc}")
        if defn.get("ranges"):
            lines.append("")
            for rng, desc in defn["ranges"].items():
                lines.append(f"- **{rng}**: {desc}")
        if defn.get("regions"):
            lines.append(f"\n**Regions**: {defn['regions']}")
        if defn.get("notes"):
            lines.append(f"\n*{defn['notes']}*")
        return "\n".join(lines)

    # Per-trial definitions (sICH)
    if "definitions_by_trial" in d:
        lines = [f"## {d.get('description', 'sICH definitions by trial')}\n"]
        for entry in d["definitions_by_trial"]:
            trial = entry.get("trial_acronym", "?")
            defn_text = entry.get("sich_definition", NOT_REPORTED)
            rate_i = entry.get("sich_intervention_pct")
            rate_c = entry.get("sich_control_pct")
            rate = ""
            if rate_i is not None:
                rate = f" — {rate_i}% vs {rate_c}%"
            lines.append(f"- **{trial}**: {defn_text}{rate}")
        return "\n".join(lines)

    return f"**{term}**: {defn}"


def _format_p8(result: ProtocolResult) -> str:
    """P8: Extracted tables — show matching tables."""
    d = result.data
    tables = d.get("tables", [])
    trial = result.trial_acronym or ""

    lines = []
    if trial:
        lines.append(f"**{trial}** — {len(tables)} matching table(s):\n")
    else:
        lines.append(f"**{len(tables)} matching table(s) found:**\n")

    for t in tables[:5]:
        title = t.get("table_title", "Untitled")
        trial_name = t.get("trial_acronym", "")
        lines.append(f"### {title}" + (f" ({trial_name})" if trial_name and trial_name != trial else ""))
        headers = t.get("headers", [])
        if headers:
            lines.append("| " + " | ".join(str(h) for h in headers) + " |")
            lines.append("| " + " | ".join("---" for _ in headers) + " |")
        for row_data in t.get("data", [])[:10]:
            if isinstance(row_data, list):
                lines.append("| " + " | ".join(str(c) for c in row_data) + " |")
        lines.append("")

    if len(tables) > 5:
        lines.append(f"*...and {len(tables) - 5} more table(s)*")

    return "\n".join(lines)


def _format_multi(result: ProtocolResult) -> str:
    """Multi-intent: format each sub-result."""
    sub_results = result.data.get("sub_results", [])
    parts = []
    for sr in sub_results:
        sub = ProtocolResult(
            protocol=sr.get("protocol", "P8"),
            trial_acronym=sr.get("trial_acronym"),
            query=result.query,
            data=sr.get("data", {}),
            data_found=sr.get("data_found", False),
        )
        formatter = _FORMATTERS.get(sub.protocol, _format_generic)
        parts.append(formatter(sub))
    return "\n\n---\n\n".join(parts)


def _format_generic(result: ProtocolResult) -> str:
    """Generic fallback formatter."""
    return str(result.data)


# ── Helpers ───────────────────────────────────────────────────

def _clean_label(key: str) -> str:
    """Convert a DB column name to a readable label."""
    return key.replace("_", " ").replace("pct", "%").title()


def _fmt_pct(val) -> str:
    """Format a percentage value — don't double-add % sign."""
    if val is None or val == "?":
        return "?"
    s = str(val)
    if s.endswith("%"):
        return s
    return f"{s}%"


def _table_label(table_key: str) -> str:
    """Convert a table key to a readable label."""
    labels = {
        "primary_outcomes": "Primary Outcome",
        "secondary_outcomes": "Secondary Outcomes",
        "safety_outcomes": "Safety Outcomes",
        "inclusion_criteria": "Inclusion Criteria",
        "exclusion_criteria": "Exclusion Criteria",
        "imaging_criteria": "Imaging Criteria",
        "treatment_arms": "Treatment Arms",
        "subgroup_analyses": "Subgroup Analyses",
        "process_metrics": "Process Metrics",
        "reperfusion_metrics": "Reperfusion Metrics",
        "baseline_demographics": "Baseline Demographics",
    }
    return labels.get(table_key, table_key.replace("_", " ").title())


_FORMATTERS = {
    "P1": _format_p1,
    "P2": _format_p2,
    "P3": _format_p3,
    "P4": _format_p4,
    "P5": _format_p5,
    "P6": _format_p6,
    "P7": _format_p7,
    "P8": _format_p8,
    "multi": _format_multi,
}
