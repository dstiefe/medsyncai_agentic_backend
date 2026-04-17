"""
LLM-classify anchor_terms and intent_affinity for every atom.

Reads atoms_intermediate.json (907 atoms from Stage 1), sends batches
of atoms to Claude Sonnet, and updates each atom with:
  - anchor_terms: list of clinical terms/concepts mentioned
  - intent_affinity: list of intents from the 44-intent schema this
                     atom helps answer

Uses the intent map and anchor vocabulary as reference context in
the system prompt so the LLM's output stays grounded in the
controlled vocabulary.

Output: writes back to atoms_intermediate.json with metadata populated.

Run: python scripts/classify_atom_metadata.py
     python scripts/classify_atom_metadata.py --batch-size 10
     python scripts/classify_atom_metadata.py --dry-run   # 5 atoms only
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any, Dict, List

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND_ROOT = os.path.dirname(_HERE)
_DATA_DIR = os.path.join(
    _BACKEND_ROOT,
    "app/agents/clinical/ais_clinical_engine/data",
)
_REFS_DIR = os.path.join(
    _BACKEND_ROOT,
    "app/agents/clinical/ais_clinical_engine/agents/qa_v6/references",
)
_INTERMEDIATE_PATH = os.path.join(_DATA_DIR, "atoms_intermediate.json")


def _load_intent_vocabulary() -> List[Dict[str, str]]:
    """Return the 44 intents with their short descriptions."""
    with open(
        os.path.join(_REFS_DIR, "intent_content_source_map.json"),
    ) as f:
        data = json.load(f)
    return [
        {
            "intent": e["intent"],
            "user_is_asking": e.get("user_is_asking", ""),
        }
        for e in data.get("intents", [])
    ]


def _load_anchor_vocabulary() -> List[str]:
    """Return the flat list of canonical anchor terms."""
    with open(
        os.path.join(_REFS_DIR, "guideline_anchor_words.json"),
    ) as f:
        data = json.load(f)
    terms = set()
    for sec_body in data.get("sections", {}).values():
        if not isinstance(sec_body, dict):
            continue
        anchor_words = sec_body.get("anchor_words", {})
        if isinstance(anchor_words, dict):
            for entries in anchor_words.values():
                if not isinstance(entries, list):
                    continue
                for entry in entries:
                    if isinstance(entry, dict):
                        t = entry.get("term", "")
                        if t:
                            terms.add(t)
                    elif isinstance(entry, str):
                        terms.add(entry)
    return sorted(terms)


def build_system_prompt() -> str:
    """Build the classifier prompt with controlled vocabulary."""
    intents = _load_intent_vocabulary()
    anchors = _load_anchor_vocabulary()

    intent_block = "\n".join(
        f"  - {i['intent']}: {i['user_is_asking']}"
        for i in intents
    )

    return f"""You are a clinical content classifier for acute ischemic stroke (AIS) guidelines.

For each atom of clinical text, output:
  - anchor_terms: list of clinical terms/concepts explicitly discussed in the text. Use terms from the anchor vocabulary where possible. Add novel clinical terms only if the text discusses them and no vocabulary match exists.
  - intent_affinity: list of intents (from the 44-intent schema below) that this atom helps answer. An atom can have multiple intent affinities.

INTENT SCHEMA (44 intents):
{intent_block}

GUIDANCE:
- anchor_terms should be 2-8 items per atom. Clinical concepts only — not filler words.
- intent_affinity should be 1-5 items per atom. Only list intents where this atom directly provides information to answer that kind of question.
- For a recommendation that says "do not administer aspirin within 90 min of IVT": anchor_terms=["aspirin", "IVT", "90 minutes", "hemorrhage risk"], intent_affinity=["harm_query", "time_window", "recommendation_lookup"]
- For a synopsis paragraph describing antiplatelet therapy overview: anchor_terms=["antiplatelet therapy", "aspirin", "clopidogrel", "DAPT"], intent_affinity=["clinical_overview", "drug_choice"]
- For a knowledge gap about ticagrelor monotherapy: anchor_terms=["ticagrelor", "monotherapy", "secondary prevention"], intent_affinity=["knowledge_gap", "current_understanding_and_gaps"]

Output format: JSON array of classification objects, one per atom, in the same order received. Each object has exactly two keys: anchor_terms and intent_affinity.
"""


def classify_batch(
    atoms_batch: List[Dict[str, Any]],
    client,
    system_prompt: str,
) -> List[Dict[str, List[str]]]:
    """Send a batch of atoms to the LLM, get back classifications."""
    # Build user message: numbered list of atoms
    lines = ["Classify these atoms. Return a JSON array of objects, one per atom.\n"]
    for i, atom in enumerate(atoms_batch, start=1):
        text = atom.get("text", "")
        atom_type = atom.get("atom_type", "")
        section = atom.get("parent_section", "")
        lines.append(f"Atom {i} [{atom_type} | §{section}]:")
        lines.append(text[:1500])  # cap length to keep prompts tight
        lines.append("")
    user_msg = "\n".join(lines)

    response = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=3000,
        system=system_prompt,
        messages=[{"role": "user", "content": user_msg}],
    )

    raw = response.content[0].text.strip()
    # Strip code fences if present
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json\n"):
            raw = raw[5:]
        raw = raw.rsplit("```", 1)[0]

    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict) and "classifications" in parsed:
            parsed = parsed["classifications"]
        if not isinstance(parsed, list):
            raise ValueError("expected JSON array")
        return parsed
    except Exception as e:
        print(f"  ERROR parsing LLM response: {e}")
        print(f"  Raw: {raw[:500]}")
        return [{"anchor_terms": [], "intent_affinity": []}] * len(atoms_batch)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Classify only the first 5 atoms for testing",
    )
    parser.add_argument(
        "--resume", action="store_true",
        help="Skip atoms that already have non-empty anchor_terms",
    )
    args = parser.parse_args()

    with open(_INTERMEDIATE_PATH, "r") as f:
        data = json.load(f)
    atoms = data["atoms"]
    print(f"Loaded {len(atoms)} atoms")

    if args.dry_run:
        atoms_to_classify = atoms[:5]
    elif args.resume:
        atoms_to_classify = [
            a for a in atoms
            if not a.get("anchor_terms") and not a.get("intent_affinity")
        ]
        print(f"Resume mode: {len(atoms_to_classify)} atoms need classification")
    else:
        atoms_to_classify = atoms

    if not atoms_to_classify:
        print("Nothing to classify.")
        return 0

    # Initialize Anthropic client
    try:
        from anthropic import Anthropic
    except ImportError:
        print("ERROR: anthropic package not installed")
        return 1

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set")
        return 1

    client = Anthropic(api_key=api_key)
    system_prompt = build_system_prompt()
    print(f"System prompt length: {len(system_prompt)} chars")

    batch_size = args.batch_size
    total = len(atoms_to_classify)
    done = 0
    start = time.time()

    # Index for writing back to the full atoms list
    atom_id_to_idx = {a["atom_id"]: i for i, a in enumerate(atoms)}

    for batch_start in range(0, total, batch_size):
        batch = atoms_to_classify[batch_start:batch_start + batch_size]
        try:
            results = classify_batch(batch, client, system_prompt)
        except Exception as e:
            print(f"  batch {batch_start}: LLM call failed: {e}")
            results = [{"anchor_terms": [], "intent_affinity": []}] * len(batch)

        # Write results back to atoms list
        for atom, result in zip(batch, results):
            if not isinstance(result, dict):
                continue
            idx = atom_id_to_idx.get(atom["atom_id"])
            if idx is None:
                continue
            atoms[idx]["anchor_terms"] = result.get("anchor_terms", []) or []
            atoms[idx]["intent_affinity"] = result.get("intent_affinity", []) or []

        done += len(batch)
        elapsed = time.time() - start
        rate = done / elapsed if elapsed > 0 else 0
        eta = (total - done) / rate if rate > 0 else 0
        print(
            f"  {done}/{total} atoms classified | "
            f"elapsed={elapsed:.1f}s | eta={eta:.1f}s"
        )

        # Save progress every 10 batches in case of interruption
        if (batch_start // batch_size) % 10 == 9:
            with open(_INTERMEDIATE_PATH, "w") as f:
                json.dump({"atoms": atoms}, f, indent=2)

    # Final save
    with open(_INTERMEDIATE_PATH, "w") as f:
        json.dump({"atoms": atoms}, f, indent=2)

    print(f"\nDone. {done} atoms classified in {time.time() - start:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
