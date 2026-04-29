"""
Extract structured clinical criteria from 202 guideline recommendations.

Reads each recommendation's text and uses Claude to extract:
  - intervention (EVT, IVT, etc.)
  - circulation (anterior, basilar)
  - vessel_occlusion (ICA, M1, M2, etc.)
  - time_window_hours (min, max)
  - aspects_range / pc_aspects_range (min, max)
  - nihss_range (min, max)
  - age_range (min, max)
  - premorbid_mrs (min, max)
  - core_volume_ml (min, max)

Output: data/recommendation_criteria.json

Usage:
    python3 scripts/extract_rec_criteria.py
    python3 scripts/extract_rec_criteria.py --dry-run  # show first 5 only
"""

import argparse
import json
import os
import sys
import time

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from anthropic import Anthropic
from app.agents.clinical.ais_clinical_engine.data.loader import load_recommendations_by_id


SYSTEM_PROMPT = """You are a clinical criteria extraction assistant. Given a guideline recommendation, extract any explicit clinical criteria mentioned in the text.

Extract ONLY criteria that are explicitly stated. Do NOT infer or assume values.

Return a JSON object with these fields (use null if not mentioned):

{
  "intervention": "EVT" | "IVT" | "alteplase" | "tenecteplase" | null,
  "circulation": "anterior" | "basilar" | null,
  "vessel_occlusion": ["ICA", "M1", "M2", "M3", "basilar", "ACA", "PCA"] | null,
  "time_window_hours": {"min": number|null, "max": number|null} | null,
  "aspects_range": {"min": number|null, "max": number|null} | null,
  "pc_aspects_range": {"min": number|null, "max": number|null} | null,
  "nihss_range": {"min": number|null, "max": number|null} | null,
  "age_range": {"min": number|null, "max": number|null} | null,
  "premorbid_mrs": {"min": number|null, "max": number|null} | null,
  "core_volume_ml": {"min": number|null, "max": number|null} | null,
  "mismatch_ratio": {"min": number|null, "max": number|null} | null
}

Rules:
- "within 6 hours" → time_window_hours: {"min": 0, "max": 6}
- "between 6 and 24 hours" → time_window_hours: {"min": 6, "max": 24}
- "within 24 hours" → time_window_hours: {"min": 0, "max": 24}
- "NIHSS >=6" → nihss_range: {"min": 6, "max": null}
- "NIHSS 6 to 9" → nihss_range: {"min": 6, "max": 9}
- "ASPECTS 3 to 10" → aspects_range: {"min": 3, "max": 10}
- "ASPECTS >=6" → aspects_range: {"min": 6, "max": null}
- "age <80" → age_range: {"min": null, "max": 79}
- "prestroke mRS 0 to 1" → premorbid_mrs: {"min": 0, "max": 1}
- "proximal LVO of the ICA or M1" → vessel_occlusion: ["ICA", "M1"]
- "basilar artery occlusion" → vessel_occlusion: ["basilar"], circulation: "basilar"
- "dominant proximal M2" → vessel_occlusion: ["M2"]
- "distal MCA, ACA, or PCA" → vessel_occlusion: ["M3", "ACA", "PCA"]
- PC-ASPECTS → use pc_aspects_range (not aspects_range)
- If the recommendation is about a general process/system with no patient criteria, return all null.

Return ONLY the JSON object, no other text."""


def extract_criteria(client, rec_text: str, rec_id: str) -> dict:
    """Extract criteria from a single recommendation using Claude."""
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=500,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"Recommendation ID: {rec_id}\nText: {rec_text}",
            }
        ],
    )

    for block in response.content:
        if hasattr(block, "text"):
            text = block.text.strip()
            # Parse JSON from response
            if text.startswith("{"):
                return json.loads(text)
            # Try to find JSON in the response
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(text[start:end])

    return {}


def count_criteria(criteria: dict) -> int:
    """Count how many non-null criteria fields are present."""
    count = 0
    for key in [
        "intervention", "circulation", "vessel_occlusion",
        "time_window_hours", "aspects_range", "pc_aspects_range",
        "nihss_range", "age_range", "premorbid_mrs",
        "core_volume_ml", "mismatch_ratio",
    ]:
        val = criteria.get(key)
        if val is not None:
            if isinstance(val, dict):
                if val.get("min") is not None or val.get("max") is not None:
                    count += 1
            elif isinstance(val, list) and len(val) > 0:
                count += 1
            elif isinstance(val, str):
                count += 1
    return count


def main():
    parser = argparse.ArgumentParser(description="Extract recommendation criteria")
    parser.add_argument("--dry-run", action="store_true", help="Process first 5 only")
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: Set ANTHROPIC_API_KEY environment variable")
        sys.exit(1)

    client = Anthropic(api_key=api_key)
    recs = load_recommendations_by_id()
    print(f"Loaded {len(recs)} recommendations")

    output = {}
    errors = []
    items = list(recs.items())
    if args.dry_run:
        # In dry-run, pick a mix: some EVT recs (4.7.x) and some general recs
        sample_ids = [
            "rec-4.7.2-001", "rec-4.7.2-002", "rec-4.7.3-001",
            "rec-2.1-001", "rec-4.6.1-001",
        ]
        items = [(k, v) for k, v in items if k in sample_ids]

    for i, (rec_id, rec) in enumerate(items):
        rec_dict = (
            rec if isinstance(rec, dict)
            else (rec.model_dump() if hasattr(rec, "model_dump") else vars(rec))
        )
        rec_text = rec_dict.get("text", "")

        try:
            criteria = extract_criteria(client, rec_text, rec_id)
            criteria["rec_id"] = rec_id
            criteria["section"] = rec_dict.get("section", "")
            criteria["cor"] = rec_dict.get("cor", "")
            criteria["loe"] = rec_dict.get("loe", "")
            criteria["criteria_count"] = count_criteria(criteria)
            output[rec_id] = criteria

            n_criteria = criteria["criteria_count"]
            print(f"  [{i+1}/{len(items)}] {rec_id} → {n_criteria} criteria")

        except Exception as e:
            print(f"  [{i+1}/{len(items)}] {rec_id} → ERROR: {e}")
            errors.append({"rec_id": rec_id, "error": str(e)})
            # Still add with empty criteria
            output[rec_id] = {
                "rec_id": rec_id,
                "section": rec_dict.get("section", ""),
                "cor": rec_dict.get("cor", ""),
                "loe": rec_dict.get("loe", ""),
                "criteria_count": 0,
            }

        # Rate limiting
        if not args.dry_run and i % 10 == 9:
            time.sleep(0.5)

    # Write output
    out_path = os.path.join(
        os.path.dirname(__file__), "..",
        "app", "agents", "clinical", "ais_clinical_engine",
        "data", "recommendation_criteria.json",
    )

    if args.dry_run:
        print("\n=== DRY RUN OUTPUT ===")
        print(json.dumps(output, indent=2))
    else:
        with open(out_path, "w") as f:
            json.dump(output, f, indent=2)
        print(f"\nWrote {len(output)} criteria to {out_path}")

    if errors:
        print(f"\n{len(errors)} errors:")
        for e in errors:
            print(f"  {e['rec_id']}: {e['error']}")

    # Summary
    with_criteria = sum(1 for v in output.values() if v.get("criteria_count", 0) > 0)
    print(f"\nSummary: {with_criteria}/{len(output)} recs have extractable criteria")


if __name__ == "__main__":
    main()
