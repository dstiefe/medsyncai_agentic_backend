#!/usr/bin/env python3
"""Parse Tables 4-7 from guideline_knowledge.json into individual RSS entries.

Each table's synopsis is split into individual paragraphs. Each paragraph
becomes an RSS entry so the LLM can select specific items and Python can
render them verbatim.

Usage:
    python scripts/parse_tables_4_7.py          # dry run
    python scripts/parse_tables_4_7.py --write  # update the file
"""

import json
import os
import re
import sys

DATA_PATH = os.path.join(
    os.path.dirname(__file__), os.pardir,
    "app", "agents", "clinical", "ais_clinical_engine", "data",
    "guideline_knowledge.json",
)


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"[\s]+", "-", text)
    return text[:60]


def strip_abbreviations(text: str) -> str:
    """Remove trailing abbreviation block (starts with a line like 'AIS indicates...')."""
    for marker in ["\nAIS indicates", "\nACE indicates", "\nNIHSS indicates"]:
        idx = text.find(marker)
        if idx > 0:
            text = text[:idx]
    return text.strip()


def parse_table4(synopsis: str):
    """Table 4: Disabling deficits guidance.

    Structure: intro paragraphs, then two labeled lists.
    Split into: guidance intro, clearly disabling list, may-not-be-disabling list.
    """
    entries = []
    text = strip_abbreviations(synopsis)

    # Remove the table header line
    lines = text.split("\n\n")
    if lines and lines[0].startswith("Table 4"):
        lines = lines[1:]

    # Find the two list sections
    full = "\n\n".join(lines)

    # Split at the two list headers
    parts = re.split(
        r"(The following deficits would typically be considered clearly disabling:|"
        r"The following deficits may not be clearly disabling in an individual patient:)",
        full,
    )

    # parts[0] = intro, parts[1] = header1, parts[2] = list1, parts[3] = header2, parts[4] = list2
    if len(parts) >= 5:
        # Intro/guidance
        intro = parts[0].strip()
        if intro:
            entries.append({
                "recNumber": "guidance",
                "category": "assessment_guidance",
                "condition": "Assessment Guidance",
                "text": intro,
            })

        # Clearly disabling
        entries.append({
            "recNumber": "clearly-disabling",
            "category": "clearly_disabling",
            "condition": "Clearly Disabling Deficits",
            "text": (parts[1] + parts[2]).strip(),
        })

        # May not be disabling
        entries.append({
            "recNumber": "may-not-be-disabling",
            "category": "may_not_be_disabling",
            "condition": "Deficits That May Not Be Clearly Disabling",
            "text": (parts[3] + parts[4]).strip(),
        })
    else:
        # Fallback: split by paragraph
        for i, para in enumerate(lines):
            para = para.strip()
            if para:
                entries.append({
                    "recNumber": f"item-{i+1}",
                    "category": "guidance",
                    "condition": f"Item {i+1}",
                    "text": para,
                })

    return entries


def parse_sequential_table(synopsis: str, table_name: str, category: str):
    """Parse tables that are sequential steps (Tables 5, 6, 7).

    Each paragraph becomes an individual entry.
    """
    entries = []
    text = strip_abbreviations(synopsis)

    paragraphs = text.split("\n\n")
    # Skip the table header line
    if paragraphs and paragraphs[0].startswith(table_name):
        paragraphs = paragraphs[1:]

    step = 0
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        step += 1

        # Use first few words as condition name
        first_line = para.split("\n")[0]
        if len(first_line) > 80:
            condition = first_line[:77] + "..."
        else:
            condition = first_line

        # For section headers (e.g., "Maintain Airway:"), use as-is
        slug = slugify(condition)
        if not slug:
            slug = f"step-{step}"

        entries.append({
            "recNumber": slug,
            "category": category,
            "condition": condition,
            "text": para,
        })

    return entries


def main():
    write = "--write" in sys.argv

    with open(DATA_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    sections = data["sections"]

    table_parsers = {
        "Table 4": (
            parse_table4,
            "Guidance for determining whether deficits are clearly disabling at presentation.",
        ),
        "Table 5": (
            lambda s: parse_sequential_table(s, "Table 5", "sich_management"),
            "Step-by-step management of symptomatic intracranial bleeding after IVT.",
        ),
        "Table 6": (
            lambda s: parse_sequential_table(s, "Table 6", "angioedema_management"),
            "Step-by-step management of orolingual angioedema after IVT.",
        ),
        "Table 7": (
            lambda s: parse_sequential_table(s, "Table 7", "ivt_protocol"),
            "IVT dosing and administration protocol for AIS in adults.",
        ),
    }

    for table_key, (parser, new_synopsis) in table_parsers.items():
        if table_key not in sections:
            print(f"WARNING: {table_key} not found in sections")
            continue

        sec = sections[table_key]
        old_synopsis = sec.get("synopsis", "")
        if not old_synopsis:
            print(f"WARNING: {table_key} has no synopsis")
            continue

        entries = parser(old_synopsis)
        print(f"\n=== {table_key}: {sec.get('sectionTitle', '')} ===")
        print(f"Parsed {len(entries)} entries\n")

        for e in entries:
            text_preview = e["text"][:100] + "..." if len(e["text"]) > 100 else e["text"]
            print(f"  [{e['category']}] {e['condition']}")
            print(f"    {text_preview}")
            print()

        if write:
            sec["synopsis"] = new_synopsis
            sec["rss"] = entries

    if write:
        with open(DATA_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"\nWrote updated JSON to {DATA_PATH}")
    else:
        print("\nDry run — pass --write to update the file.")


if __name__ == "__main__":
    main()
