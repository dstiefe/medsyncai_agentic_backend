"""
Restructure metrics in guideline_anchor_words.json.

Transforms flat string metrics like "SBP <185 mmHg" into structured
objects with anchor_word + threshold/range. Conceptual entries without
numeric values move to the concepts category.

No regex — uses string operations and token walks.
"""

import json
import copy
from pathlib import Path


SRC = Path(__file__).resolve().parent.parent / (
    "app/agents/clinical/ais_clinical_engine/agents/qa_v6/"
    "references/guideline_anchor_words.json"
)

OPERATORS = ("≥", "≤", "<", ">", "=")
UNITS = ("mmHg", "mg/kg", "mg/dL", "mg", "mL", "sec", "seconds",
         "minutes", "hours", "days", "years", "%")


def _strip_unit(token: str):
    """Remove a trailing unit from a token, return (number_str, unit)."""
    for u in sorted(UNITS, key=len, reverse=True):
        if token.endswith(u):
            return token[:-len(u)].strip(), u
    return token, None


def _try_float(s: str):
    """Parse a string as float, return None on failure."""
    s = s.strip().replace(",", "")
    try:
        v = float(s)
        return int(v) if v == int(v) else v
    except (ValueError, OverflowError):
        return None


def _parse_range(s: str):
    """Try to parse 'X-Y' as a numeric range. Returns (min, max) or None."""
    if "-" not in s:
        return None
    parts = s.split("-")
    if len(parts) != 2:
        return None
    lo = _try_float(parts[0])
    hi = _try_float(parts[1])
    if lo is not None and hi is not None:
        return (lo, hi)
    return None


def _find_unit_in_tokens(tokens, start_idx):
    """Find a unit in tokens starting at start_idx."""
    for i in range(start_idx, min(start_idx + 2, len(tokens))):
        tok = tokens[i].strip().rstrip(".,;")
        for u in UNITS:
            if tok.lower() == u.lower() or tok == u:
                return u
    return None


def _find_operator_in_token(token):
    """Check if a token starts with an operator. Returns (op, rest) or None."""
    for op in OPERATORS:
        if token.startswith(op):
            return op, token[len(op):]
    return None


def parse_metric(raw: str):
    """Parse a metric string into a structured dict.

    Strategy: scan tokens left-to-right looking for an operator or a
    numeric range. Everything before it is the term. Everything after
    is the value + optional unit.

    Returns:
        dict with keys: term, value/min/max/operator, unit, raw
        OR None if the entry is conceptual (no numeric content)
    """
    raw_stripped = raw.strip()
    tokens = raw_stripped.split()

    if not tokens:
        return None

    # --- Scan for operator in any token position ---
    for i, tok in enumerate(tokens):
        op_result = _find_operator_in_token(tok)
        if op_result:
            op, rest = op_result
            # Term is everything before this token
            term = " ".join(tokens[:i]).strip() if i > 0 else None

            # Value is rest of this token (possibly with unit) + next tokens
            val_str, unit = _strip_unit(rest)
            val = _try_float(val_str)

            if val is not None:
                if not unit:
                    unit = _find_unit_in_tokens(tokens, i + 1)

                # If no explicit term, try to infer from unit
                if not term:
                    if unit in ("hours", "minutes", "seconds", "days"):
                        term = "time_window"
                    else:
                        term = "threshold"

                result = {"term": term, "operator": op,
                          "value": val, "raw": raw_stripped}
                if unit:
                    result["unit"] = unit
                return result

    # --- Scan for "TERM X-Y" range pattern ---
    for i, tok in enumerate(tokens):
        range_str, unit = _strip_unit(tok)
        rng = _parse_range(range_str)
        if rng:
            term = " ".join(tokens[:i]).strip() if i > 0 else None
            if not unit:
                unit = _find_unit_in_tokens(tokens, i + 1)

            if not term:
                if unit in ("hours", "minutes", "seconds", "days"):
                    term = "time_window"
                elif unit == "min" or (not unit and i + 1 < len(tokens)
                                       and tokens[i + 1].lower() == "min"):
                    term = "time_window"
                    unit = "minutes"
                else:
                    term = "range"

            result = {"term": term, "min": rng[0], "max": rng[1],
                      "raw": raw_stripped}
            if unit:
                result["unit"] = unit
            return result

    # --- "within X UNIT" pattern ---
    lower = raw_stripped.lower()
    if "within" in lower:
        # Find "within" position and look for number after it
        idx = lower.find("within")
        after = raw_stripped[idx + 6:].strip()
        after_tokens = after.split()
        for j, at in enumerate(after_tokens):
            val_str, unit = _strip_unit(at)
            val = _try_float(val_str)
            if val is not None:
                if not unit:
                    unit = _find_unit_in_tokens(after_tokens, j + 1)
                # Term is everything before "within"
                prefix = raw_stripped[:idx].strip()
                if prefix:
                    term = prefix
                elif unit in ("hours", "minutes", "seconds", "days"):
                    term = "time_window"
                else:
                    term = "time_window"
                result = {"term": term, "operator": "≤",
                          "value": val, "raw": raw_stripped}
                if unit:
                    result["unit"] = unit
                return result

    # --- Last resort: find any standalone number ---
    for i, tok in enumerate(tokens):
        val_str, unit = _strip_unit(tok)
        val = _try_float(val_str)
        if val is not None:
            term = " ".join(tokens[:i]).strip() if i > 0 else "dose"
            if not unit:
                unit = _find_unit_in_tokens(tokens, i + 1)
            result = {"term": term, "value": val, "raw": raw_stripped}
            if unit:
                result["unit"] = unit
            return result

    # --- No numeric content — conceptual entry ---
    return None


def restructure():
    with open(SRC) as f:
        data = json.load(f)

    out = copy.deepcopy(data)

    # Update metadata
    out["metadata"]["schema_version"] = "2.0.0"
    out["metadata"]["categories"]["metrics"] = (
        "Structured thresholds, ranges, time windows, dosing — "
        "each entry has term + value/range"
    )

    conceptual_moved = 0
    structured_count = 0

    for sec_id, sec in out.get("sections", {}).items():
        aw = sec.get("anchor_words", {})
        old_metrics = aw.get("metrics", [])
        if not old_metrics:
            continue

        new_metrics = []
        concepts_to_add = []

        for raw in old_metrics:
            parsed = parse_metric(raw)
            if parsed:
                new_metrics.append(parsed)
                structured_count += 1
            else:
                concepts_to_add.append(raw)
                conceptual_moved += 1

        aw["metrics"] = new_metrics

        if concepts_to_add:
            existing = set(aw.get("concepts", []))
            for c in concepts_to_add:
                if c not in existing:
                    aw.setdefault("concepts", []).append(c)
                    existing.add(c)

    print(f"Structured: {structured_count}")
    print(f"Moved to concepts: {conceptual_moved}")
    print(f"Total processed: {structured_count + conceptual_moved}")

    with open(SRC, "w") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"\nWritten to {SRC}")


if __name__ == "__main__":
    restructure()
