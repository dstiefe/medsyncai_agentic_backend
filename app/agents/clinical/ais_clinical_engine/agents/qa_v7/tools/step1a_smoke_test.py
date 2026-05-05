"""qa_v7 Step 1a smoke test.

Dev-only script. Not a test-suite entry, not wired to anything.
Runs the v7 extraction parser against one or more questions and
prints the output so you can eyeball whether anchors, scenario
variables, scope, summary, and confidence look right.

Usage from repo root:
    # Single question
    python -m app.agents.clinical.ais_clinical_engine.agents.qa_v7.tools.step1a_smoke_test \\
        "what defines a non-disabling deficit"

    # The built-in test set (no args)
    python -m app.agents.clinical.ais_clinical_engine.agents.qa_v7.tools.step1a_smoke_test

Requires ANTHROPIC_API_KEY in the environment.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import List

# Default test questions — cover the intent diversity we care about
# for Step 1a verification. Keep short and eyeball-friendly.
_DEFAULT_QUESTIONS: List[str] = [
    "What defines a non-disabling deficit",
    "Can I give IVT to a patient on DOACs",
    "78yo NIHSS 18 LKW 2h on apixaban, M1 occlusion — EVT?",
    "What's the capital of France",
    "Tell me about stroke",
    "What are the absolute contraindications for IVT",
    "What does Figure 3 in the guideline show",
]


def _build_client():
    """Create an Anthropic client from env. Exit cleanly when missing."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print(
            "ERROR: ANTHROPIC_API_KEY not set in environment. "
            "Set it and retry.",
            file=sys.stderr,
        )
        sys.exit(2)
    try:
        from anthropic import Anthropic
    except ImportError:
        print(
            "ERROR: anthropic package not installed. "
            "Run `pip install anthropic`.",
            file=sys.stderr,
        )
        sys.exit(2)
    return Anthropic(api_key=api_key)


def _format_output(question: str, parsed_dict: dict, usage: dict) -> str:
    """Human-readable dump of one parse result."""
    lines = [
        "─" * 72,
        f"Q: {question}",
        "─" * 72,
    ]
    # Ordered display so the most important fields come first
    order = [
        "scope",
        "extraction_confidence",
        "clarification",
        "question_summary",
        "intent",              # will be null until Step 1b lands
        "intent_description",  # will be null until Step 1b lands
        "anchor_terms",
        "scenario_variables",
    ]
    for key in order:
        val = parsed_dict.get(key)
        if isinstance(val, (dict, list)):
            pretty = json.dumps(val, indent=2, ensure_ascii=False)
            lines.append(f"{key}:")
            for ln in pretty.splitlines():
                lines.append(f"  {ln}")
        else:
            lines.append(f"{key}: {val}")
    lines.append(
        f"tokens: input={usage.get('input_tokens', 0)} "
        f"output={usage.get('output_tokens', 0)}"
    )
    return "\n".join(lines)


async def _run(questions: List[str]) -> None:
    from app.agents.clinical.ais_clinical_engine.agents.qa_v7.query_parser import (
        QueryParserV7,
    )

    client = _build_client()
    parser = QueryParserV7(nlp_client=client)

    total_in = 0
    total_out = 0
    for q in questions:
        parsed, usage = await parser.parse(q)
        print(_format_output(q, parsed.to_dict(), usage))
        total_in += usage.get("input_tokens", 0)
        total_out += usage.get("output_tokens", 0)

    print("─" * 72)
    print(
        f"Totals across {len(questions)} questions: "
        f"input_tokens={total_in} output_tokens={total_out}"
    )


def main() -> None:
    if len(sys.argv) > 1:
        questions = [" ".join(sys.argv[1:])]
    else:
        questions = _DEFAULT_QUESTIONS
    asyncio.run(_run(questions))


if __name__ == "__main__":
    main()
