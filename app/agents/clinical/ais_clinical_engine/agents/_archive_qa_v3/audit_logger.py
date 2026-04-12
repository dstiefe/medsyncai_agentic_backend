# ─── v3 (Q&A v3 namespace) ─────────────────────────────────────────────
# This file lives under agents/qa_v3/ and is the active v3 copy of the
# Guideline Q&A pipeline. The previous location agents/qa/ has been archived to
# agents/_archive_qa_v2/ and is no longer imported anywhere. To switch the live route to v3,
# update the import at services/qa_service.py or routes.py accordingly.
# ───────────────────────────────────────────────────────────────────────
"""
Audit Logger — writes a readable audit file for every QA question.

Each question creates its own JSON file in logs/qa_audits/:
    2026-04-07_143022_can_i_give_tpa_to_a_patient_on_aspirin.json

Files are human-readable (indented JSON) and contain the full
pipeline trace: LLM classifier output, section routing, rec
retrieval, focused agent outputs, and assembly result.

Browse the folder to review any question's pipeline.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# Audit folder at project root: logs/qa_audits/
_PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "..", "..")
)
_AUDIT_DIR = os.path.join(_PROJECT_ROOT, "logs", "qa_audits")


def _slugify(text: str, max_len: int = 60) -> str:
    """Convert question text to a safe filename slug."""
    slug = text.lower().strip()
    slug = re.sub(r"[^a-z0-9\s]", "", slug)
    slug = re.sub(r"\s+", "_", slug)
    return slug[:max_len].rstrip("_")


def log_audit(
    question: str,
    audit_entries: List[Dict[str, Any]],
    extra: Dict[str, Any] | None = None,
) -> None:
    """
    Write a full pipeline audit to its own file.

    Args:
        question: the original question text
        audit_entries: list of {"step": str, "detail": dict} from the pipeline
        extra: optional additional metadata (e.g., final answer length, status)
    """
    try:
        os.makedirs(_AUDIT_DIR, exist_ok=True)

        now = datetime.now(timezone.utc)
        timestamp = now.strftime("%Y-%m-%d_%H%M%S")
        slug = _slugify(question)
        filename = f"{timestamp}_{slug}.json"
        filepath = os.path.join(_AUDIT_DIR, filename)

        record = {
            "timestamp": now.isoformat(),
            "question": question,
        }
        if extra:
            record.update(extra)
        record["pipeline"] = audit_entries

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(record, f, indent=2, default=str, ensure_ascii=False)

        logger.info("Audit written: %s", filename)

    except Exception as e:
        # Never let audit logging break the pipeline
        logger.error("Failed to write audit log: %s", e)
