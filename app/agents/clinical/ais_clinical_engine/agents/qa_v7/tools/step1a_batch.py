"""qa_v7 Step 1a batch runner.

Takes a list of questions (from a docx file or JSON list), runs the
v7 Step 1a parser against each, saves raw results to JSON, and emits
an aggregate analysis markdown.

Dev-only. Not wired into the pipeline. Used for verification before
moving to Step 1b.

Usage (from repo root):
    python -m app.agents.clinical.ais_clinical_engine.agents.qa_v7.tools.step1a_batch \\
        --input "/path/to/test_questions.docx" \\
        --sample-every 10 \\
        --output-dir /tmp/v7_step1a_run

Requires ANTHROPIC_API_KEY in environment.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from collections import Counter
from typing import Any, Dict, List


def _load_questions(path: str) -> List[str]:
    """Load questions from a docx or text/json file.

    docx: one question per non-empty paragraph; strips a leading
    "<N>. " prefix when present.
    json: flat list of strings.
    txt: one question per line.
    """
    if path.endswith(".docx"):
        try:
            from docx import Document
        except ImportError:
            print(
                "ERROR: python-docx not installed. "
                "Run `pip install python-docx`.",
                file=sys.stderr,
            )
            sys.exit(2)
        doc = Document(path)
        raw = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    elif path.endswith(".json"):
        with open(path, "r") as f:
            raw = json.load(f)
    else:
        with open(path, "r") as f:
            raw = [ln.strip() for ln in f if ln.strip()]

    # Strip leading "<N>. " numbering, skip the title line
    cleaned: List[str] = []
    for line in raw:
        if not line:
            continue
        # Drop a leading integer + period + space, e.g. "1. Should ..."
        # No regex — string ops only (project rule)
        s = line
        idx = 0
        while idx < len(s) and s[idx].isdigit():
            idx += 1
        if idx > 0 and idx < len(s) and s[idx] == "." and idx + 1 < len(s) and s[idx + 1] == " ":
            s = s[idx + 2:].strip()
        cleaned.append(s)

    # Drop a title line like "Test Questions (500)" that isn't a
    # question (no question mark, no "how/what/which/is/can/..." lead)
    # We detect by the simpler heuristic: first line has no "?" and
    # the rest mostly do.
    if len(cleaned) >= 2:
        total_qmarks = sum(1 for q in cleaned if "?" in q)
        if total_qmarks >= len(cleaned) * 0.5 and "?" not in cleaned[0]:
            cleaned = cleaned[1:]
    return cleaned


def _build_client():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set.", file=sys.stderr)
        sys.exit(2)
    from anthropic import Anthropic
    return Anthropic(api_key=api_key)


async def _run(
    questions: List[str], output_dir: str,
) -> Dict[str, Any]:
    from app.agents.clinical.ais_clinical_engine.agents.qa_v7.query_parser import (
        QueryParserV7,
    )

    os.makedirs(output_dir, exist_ok=True)
    client = _build_client()
    parser = QueryParserV7(nlp_client=client)

    results: List[Dict[str, Any]] = []
    total_in = 0
    total_out = 0
    start = time.time()

    for i, q in enumerate(questions, 1):
        t0 = time.time()
        parsed, usage = await parser.parse(q)
        elapsed = time.time() - t0
        total_in += usage.get("input_tokens", 0)
        total_out += usage.get("output_tokens", 0)
        results.append({
            "idx": i,
            "question": q,
            "parsed": parsed.to_dict(),
            "usage": usage,
            "elapsed_sec": round(elapsed, 2),
        })
        # Progress line per question — sent to stderr so stdout stays
        # clean for any piped consumer.
        print(
            f"[{i:3}/{len(questions)}] scope={parsed.scope} "
            f"conf={parsed.extraction_confidence:.2f} "
            f"anchors={len(parsed.anchor_terms)} "
            f"vars={len(parsed.scenario_variables)} "
            f"({elapsed:.1f}s)",
            file=sys.stderr,
        )

    total_elapsed = time.time() - start

    # ── Save raw results ──
    raw_path = os.path.join(output_dir, "step1a_results.json")
    with open(raw_path, "w") as f:
        json.dump({
            "meta": {
                "model": QueryParserV7.MODEL,
                "question_count": len(questions),
                "total_input_tokens": total_in,
                "total_output_tokens": total_out,
                "total_elapsed_sec": round(total_elapsed, 1),
            },
            "results": results,
        }, f, indent=2)

    # ── Build analysis ──
    analysis = _analyze(results, total_in, total_out, total_elapsed)
    analysis_path = os.path.join(output_dir, "step1a_analysis.md")
    with open(analysis_path, "w") as f:
        f.write(analysis)

    # ── Build flagged-cases CSV for quick eyeball ──
    flagged = _flagged_cases(results)
    flagged_path = os.path.join(output_dir, "step1a_flagged.md")
    with open(flagged_path, "w") as f:
        f.write(flagged)

    return {
        "raw": raw_path,
        "analysis": analysis_path,
        "flagged": flagged_path,
        "total_input_tokens": total_in,
        "total_output_tokens": total_out,
        "total_elapsed_sec": total_elapsed,
    }


def _analyze(
    results: List[Dict[str, Any]],
    total_in: int,
    total_out: int,
    total_elapsed: float,
) -> str:
    """Aggregate markdown summary."""
    n = len(results)
    scope_counts: Counter = Counter()
    conf_buckets = Counter()
    has_clarification = 0
    anchor_frequency: Counter = Counter()
    scenario_var_frequency: Counter = Counter()
    anchor_count_hist: Counter = Counter()
    scenario_var_count_hist: Counter = Counter()
    anchor_values_emitted = 0
    dual_emitted_terms: Counter = Counter()  # term → count
    out_of_vocab_anchors: Counter = Counter()

    # Load anchor vocab to detect out-of-vocab emissions
    vocab_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "references",
        "anchor_vocabulary.json",
    )
    with open(vocab_path) as f:
        vocab_data = json.load(f)
    known_anchors = set()
    for terms in vocab_data["categories"].values():
        for t in terms:
            known_anchors.add(t.lower())

    for r in results:
        p = r["parsed"]
        scope_counts[p["scope"]] += 1
        conf = float(p["extraction_confidence"])
        bucket = (
            "1.0" if conf >= 0.95
            else "0.9–0.95" if conf >= 0.9
            else "0.7–0.9" if conf >= 0.7
            else "0.5–0.7" if conf >= 0.5
            else "<0.5"
        )
        conf_buckets[bucket] += 1
        if p.get("clarification"):
            has_clarification += 1

        anchors = p.get("anchor_terms") or {}
        scvars = p.get("scenario_variables") or {}
        anchor_count_hist[len(anchors)] += 1
        scenario_var_count_hist[len(scvars)] += 1
        for a, v in anchors.items():
            anchor_frequency[a] += 1
            if v is not None:
                anchor_values_emitted += 1
            if a.lower() not in known_anchors:
                out_of_vocab_anchors[a] += 1
            # Dual emission detection: same concept name in both
            if a in scvars or a.lower().replace(" ", "_") in scvars:
                dual_emitted_terms[a] += 1
        for k in scvars.keys():
            scenario_var_frequency[k] += 1

    lines: List[str] = []
    lines.append("# Step 1a batch analysis")
    lines.append("")
    lines.append(f"- **Questions processed**: {n}")
    lines.append(f"- **Total input tokens**: {total_in:,}")
    lines.append(f"- **Total output tokens**: {total_out:,}")
    est_cost = total_in / 1_000_000 * 3 + total_out / 1_000_000 * 15
    lines.append(f"- **Estimated cost (Sonnet pricing)**: ~${est_cost:.2f}")
    lines.append(f"- **Total elapsed**: {total_elapsed:.1f}s "
                 f"(~{total_elapsed/max(n,1):.1f}s per question)")
    lines.append("")

    lines.append("## Scope distribution")
    lines.append("")
    for scope, c in sorted(scope_counts.items(), key=lambda x: -x[1]):
        lines.append(f"- `{scope}`: {c} ({c*100/n:.0f}%)")
    lines.append("")

    lines.append("## Extraction confidence buckets")
    lines.append("")
    bucket_order = ["1.0", "0.9–0.95", "0.7–0.9", "0.5–0.7", "<0.5"]
    for b in bucket_order:
        c = conf_buckets.get(b, 0)
        lines.append(f"- `{b}`: {c} ({c*100/n:.0f}%)")
    lines.append(f"- Populated `clarification`: {has_clarification} "
                 f"({has_clarification*100/n:.0f}%)")
    lines.append("")

    lines.append("## Anchor terms")
    lines.append("")
    lines.append(f"- Questions with 0 anchors: {anchor_count_hist.get(0, 0)}")
    lines.append(f"- Avg anchors per question: "
                 f"{sum(k*v for k, v in anchor_count_hist.items()) / max(n, 1):.1f}")
    lines.append(f"- Anchor terms with a value attached: {anchor_values_emitted}")
    lines.append("")
    lines.append("### Top 30 anchor terms")
    lines.append("")
    for a, c in anchor_frequency.most_common(30):
        flag = "" if a.lower() in known_anchors else "  ⚠ not in vocab"
        lines.append(f"- `{a}`: {c}{flag}")
    lines.append("")
    if out_of_vocab_anchors:
        lines.append("### Out-of-vocabulary anchors emitted")
        lines.append("")
        lines.append(
            "The parser is allowed to emit terms not in the vocabulary "
            "(per prompt). These are candidates for adding to the "
            "vocab or for prompt tightening if they look like "
            "hallucinations."
        )
        lines.append("")
        for a, c in out_of_vocab_anchors.most_common(30):
            lines.append(f"- `{a}`: {c}")
        lines.append("")

    lines.append("## Scenario variables")
    lines.append("")
    lines.append(f"- Questions with 0 scenario_variables: "
                 f"{scenario_var_count_hist.get(0, 0)}")
    lines.append(f"- Questions with ≥3 scenario_variables (scenario-heavy): "
                 f"{sum(c for k, c in scenario_var_count_hist.items() if k >= 3)}")
    lines.append("")
    lines.append("### Scenario variable frequency")
    lines.append("")
    for k, c in scenario_var_frequency.most_common():
        lines.append(f"- `{k}`: {c}")
    lines.append("")

    if dual_emitted_terms:
        lines.append("## Dual-emitted terms (anchor + scenario variable)")
        lines.append("")
        lines.append(
            "These are terms that appeared in BOTH `anchor_terms` and "
            "`scenario_variables` for the same question. This is "
            "expected behavior per the Step 1 design — the parser "
            "extracts into all applicable forms without pruning."
        )
        lines.append("")
        for a, c in dual_emitted_terms.most_common(20):
            lines.append(f"- `{a}`: {c}")
        lines.append("")

    lines.append("## Notes for review")
    lines.append("")
    lines.append(
        "See `step1a_flagged.md` for a question-by-question list of "
        "cases that warrant eyeball review (low confidence, "
        "out-of-scope decisions, no anchors extracted from in-scope "
        "questions, and anchor/scenario-variable mismatches)."
    )
    return "\n".join(lines)


def _flagged_cases(results: List[Dict[str, Any]]) -> str:
    """Per-question flags for manual review."""
    lines = ["# Step 1a flagged cases", "",
             "Each entry is a question whose parser output warrants "
             "review. Categories:",
             "",
             "- **LOW_CONF**: extraction_confidence < 0.7",
             "- **CLARIFIED**: a clarification was populated",
             "- **OUT_OF_SCOPE**: marked out_of_scope",
             "- **EMPTY_ANCHORS_IN_SCOPE**: in_scope question with 0 anchors",
             "- **CLASSIFICATION_EXPANSION_SUSPECTED**: both a specific "
             "term and its likely category appear (e.g. M1 + LVO, "
             "apixaban + DOAC)",
             ""]

    # Pairs suggesting a classification expansion. First element is
    # the SPECIFIC, second is the CATEGORY. Presence of both in the
    # same question's anchor_terms is a flag.
    expansion_pairs = [
        ("M1", "LVO"), ("M2", "LVO"), ("ICA", "LVO"),
        ("basilar", "LVO"), ("basilar", "posterior LVO"),
        ("apixaban", "DOAC"), ("rivaroxaban", "DOAC"),
        ("edoxaban", "DOAC"), ("dabigatran", "DOAC"),
        ("alteplase", "IVT"), ("tenecteplase", "IVT"),
    ]

    for r in results:
        p = r["parsed"]
        flags: List[str] = []
        conf = float(p["extraction_confidence"])
        if conf < 0.7:
            flags.append(f"LOW_CONF({conf:.2f})")
        if p.get("clarification"):
            flags.append("CLARIFIED")
        if p["scope"] == "out_of_scope":
            flags.append("OUT_OF_SCOPE")
        anchors = p.get("anchor_terms") or {}
        if p["scope"] == "in_scope" and len(anchors) == 0:
            flags.append("EMPTY_ANCHORS_IN_SCOPE")
        anchor_lower = {a.lower() for a in anchors.keys()}
        for spec, cat in expansion_pairs:
            if spec.lower() in anchor_lower and cat.lower() in anchor_lower:
                flags.append(f"CLASSIFICATION_EXPANSION({spec}+{cat})")

        if not flags:
            continue
        lines.append(f"## [{r['idx']}] {r['question']}")
        lines.append(f"- flags: {', '.join(flags)}")
        lines.append(f"- scope: {p['scope']}")
        lines.append(f"- confidence: {p['extraction_confidence']}")
        if p.get("clarification"):
            lines.append(f"- clarification: {p['clarification']}")
        if anchors:
            lines.append(f"- anchor_terms: {json.dumps(anchors, ensure_ascii=False)}")
        scvars = p.get("scenario_variables") or {}
        if scvars:
            lines.append(f"- scenario_variables: {json.dumps(scvars, ensure_ascii=False)}")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser_cli = argparse.ArgumentParser()
    parser_cli.add_argument(
        "--input", required=True,
        help="Path to .docx, .json (list of strings), or .txt file",
    )
    parser_cli.add_argument(
        "--sample-every", type=int, default=1,
        help="Take every Nth question (1 = all). 10 = stratified sample.",
    )
    parser_cli.add_argument(
        "--output-dir", required=True,
        help="Directory to write step1a_results.json + step1a_analysis.md",
    )
    parser_cli.add_argument(
        "--limit", type=int, default=0,
        help="Cap total questions processed (0 = no cap). For quick "
             "spot checks.",
    )
    args = parser_cli.parse_args()

    questions = _load_questions(args.input)
    print(f"Loaded {len(questions)} questions from {args.input}",
          file=sys.stderr)

    if args.sample_every > 1:
        # Stratified: every Nth starting from index 0
        questions = questions[::args.sample_every]
        print(f"Stratified sample (every {args.sample_every}): "
              f"{len(questions)} questions", file=sys.stderr)
    if args.limit and args.limit < len(questions):
        questions = questions[:args.limit]
        print(f"Capped at {args.limit} questions", file=sys.stderr)

    print(
        f"Running {len(questions)} questions "
        f"(~${len(questions) * 0.035:.2f} estimated)...",
        file=sys.stderr,
    )
    summary = asyncio.run(_run(questions, args.output_dir))
    print("", file=sys.stderr)
    print(
        f"Done. {summary['total_elapsed_sec']:.1f}s elapsed. "
        f"Wrote:\n"
        f"  {summary['raw']}\n"
        f"  {summary['analysis']}\n"
        f"  {summary['flagged']}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
