"""
Audit Logger — writes every QA pipeline run to a persistent log file.

Each question produces one JSON object written as a single line to
`qa_audit_log.jsonl` in the project's `logs/` directory. The file
is append-only — one line per question, newest at the bottom.

Usage:
    from .audit_logger import log_audit

    log_audit(
        question="What are the BP thresholds before IVT?",
        audit_entries=[AuditEntry(step="step1_llm_classifier", detail={...}), ...],
    )

To review:
    - Open logs/qa_audit_log.jsonl
    - Each line is a complete JSON object with timestamp, question, and all steps
    - Use `jq` for filtering: cat logs/qa_audit_log.jsonl | jq 'select(.question | test("blood pressure"))'
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# Log file lives at project root: logs/qa_audit_log.jsonl
_PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "..", "..")
)
_LOG_DIR = os.path.join(_PROJECT_ROOT, "logs")
_LOG_FILE = os.path.join(_LOG_DIR, "qa_audit_log.jsonl")


def log_audit(
    question: str,
    audit_entries: List[Dict[str, Any]],
    extra: Dict[str, Any] | None = None,
) -> None:
    """
    Append a full pipeline audit to the log file.

    Args:
        question: the original question text
        audit_entries: list of {"step": str, "detail": dict} from the pipeline
        extra: optional additional metadata (e.g., final answer length, status)
    """
    try:
        os.makedirs(_LOG_DIR, exist_ok=True)

        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "question": question,
            "steps": audit_entries,
        }
        if extra:
            record.update(extra)

        line = json.dumps(record, default=str, ensure_ascii=False)

        with open(_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")

        logger.info("Audit logged: %s (%d steps)", question[:60], len(audit_entries))

    except Exception as e:
        # Never let audit logging break the pipeline
        logger.error("Failed to write audit log: %s", e)
