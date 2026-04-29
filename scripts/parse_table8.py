#!/usr/bin/env python3
"""
parse_table8.py

Restructures Table 8 in guideline_knowledge.json from a single synopsis
string into individual RSS entries, one per condition.

Three categories:
  1. benefit_greater_than_risk
  2. relative_contraindication
  3. absolute_contraindication

Each RSS entry:
  {
    "recNumber": "condition-name-slug",
    "category": "<one of the three above>",
    "condition": "Human-readable condition name",
    "text": "Verbatim description text from the synopsis"
  }

Usage:
  python scripts/parse_table8.py          # dry-run, prints parsed entries
  python scripts/parse_table8.py --write  # writes updated JSON back to file
"""

import json
import re
import sys
from pathlib import Path

DATA_PATH = Path(__file__).resolve().parent.parent / (
    "app/agents/clinical/ais_clinical_engine/data/guideline_knowledge.json"
)

# --- Category headers exactly as they appear in the synopsis ---
CATEGORY_HEADERS = [
    (
        "Conditions in Which Benefits of Intravenous Thrombolysis Generally are Greater Than Risks of Bleeding:",
        "benefit_greater_than_risk",
    ),
    (
        "Conditions That are Relative Contraindications:",
        "relative_contraindication",
    ),
    (
        "Conditions that are Considered Absolute Contraindications:",
        "absolute_contraindication",
    ),
]

# The abbreviation block at the end starts with "AIS indicates"
ABBREV_SENTINEL = "\n\nAIS indicates"


def slugify(name: str) -> str:
    """Convert a condition name to a kebab-case slug."""
    s = name.lower().strip()
    s = re.sub(r"[^a-z0-9\s-]", "", s)   # drop special chars
    s = re.sub(r"\s+", "-", s)            # spaces to hyphens
    s = re.sub(r"-+", "-", s)             # collapse multiple hyphens
    return s.strip("-")


def split_conditions(block: str) -> list[tuple[str, str]]:
    """
    Split a category block into (condition_name, description) pairs.

    Each condition follows the pattern:
        Condition name: Description text that may span multiple sentences.

    We split on lines that start with a capitalized phrase followed by a colon,
    but we need to be careful because description text can also contain colons.
    The key insight: each new condition starts after a double newline (\n\n)
    or is the first entry in the block.
    """
    # Split on double-newline boundaries — each condition is its own paragraph
    paragraphs = [p.strip() for p in block.strip().split("\n\n") if p.strip()]

    results = []
    for para in paragraphs:
        # Find the first colon that separates condition name from description
        colon_idx = para.index(":")
        condition_name = para[:colon_idx].strip()
        description = para[colon_idx + 1:].strip()
        results.append((condition_name, description))

    return results


def parse_table8_synopsis(synopsis: str) -> tuple[list[dict], str]:
    """
    Parse the Table 8 synopsis into individual RSS entries.

    Returns:
        (rss_entries, new_synopsis)
    """
    # Strip the abbreviation block
    abbrev_start = synopsis.find("AIS indicates")
    if abbrev_start == -1:
        raise ValueError("Could not find abbreviation block in synopsis")
    body = synopsis[:abbrev_start].strip()

    # Find the positions of each category header
    header_positions = []
    for header_text, category_key in CATEGORY_HEADERS:
        # The header appears with \n\n before it (except possibly the first)
        pos = body.find(header_text)
        if pos == -1:
            raise ValueError(f"Could not find category header: {header_text}")
        header_positions.append((pos, header_text, category_key))

    # Sort by position (should already be in order)
    header_positions.sort(key=lambda x: x[0])

    rss_entries = []

    for i, (pos, header_text, category_key) in enumerate(header_positions):
        # Content starts after the header
        content_start = pos + len(header_text)

        # Content ends at the start of the next header, or end of body
        if i + 1 < len(header_positions):
            content_end = header_positions[i + 1][0]
        else:
            content_end = len(body)

        block = body[content_start:content_end].strip()

        conditions = split_conditions(block)
        for condition_name, description in conditions:
            slug = slugify(condition_name)
            rss_entries.append({
                "recNumber": slug,
                "category": category_key,
                "condition": condition_name,
                "text": description,
            })

    # Build a short summary synopsis (just the title + category names)
    new_synopsis = (
        "Table 8. Other Situations Wherein Thrombolysis is Deemed to Be Considered\n\n"
        "Three categories of conditions:\n"
        "1. Conditions in Which Benefits of Intravenous Thrombolysis Generally are Greater Than Risks of Bleeding\n"
        "2. Conditions That are Relative Contraindications\n"
        "3. Conditions that are Considered Absolute Contraindications\n\n"
        "Individual conditions are available as separate RSS entries."
    )

    return rss_entries, new_synopsis


def main():
    write_mode = "--write" in sys.argv

    with open(DATA_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    table8 = data["sections"]["Table 8"]
    synopsis = table8["synopsis"]

    rss_entries, new_synopsis = parse_table8_synopsis(synopsis)

    # Print parsed results for verification
    print(f"Parsed {len(rss_entries)} conditions from Table 8\n")
    print("=" * 80)

    current_category = None
    for entry in rss_entries:
        if entry["category"] != current_category:
            current_category = entry["category"]
            print(f"\n--- {current_category} ---\n")

        print(f"  recNumber:  {entry['recNumber']}")
        print(f"  condition:  {entry['condition']}")
        print(f"  text:       {entry['text'][:120]}...")
        print()

    print("=" * 80)
    print(f"\nNew synopsis:\n{new_synopsis}")
    print()

    if write_mode:
        table8["synopsis"] = new_synopsis
        table8["rss"] = rss_entries

        with open(DATA_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")

        print(f"Wrote updated JSON to {DATA_PATH}")
    else:
        print("Dry run — pass --write to update the file.")


if __name__ == "__main__":
    main()
