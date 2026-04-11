"""
Q&A v3 reversibility flags.

Every deterministic v3 stage that was added during the 2026-04-10/11
architecture work checks one of these env-var flags before running.
Defaults are ON. Set the corresponding env var to "0", "false", "no",
or "off" (case-insensitive) to disable a single stage so its before/
after behavior can be A/B compared without ripping the code out.

The flags are read at module import via ``_read``. Tests that need to
toggle a flag mid-process should monkey-patch the constant directly.

Flags
-----
QA_V3_REC_ANCHOR_PREFILTER       — anchor pre-filter inside RecSelectionAgent
QA_V3_RSS_ANCHOR_FILTER          — paragraph anchor filter inside RSSSummaryAgent
QA_V3_KG_ANCHOR_FILTER           — paragraph anchor filter inside KGSummaryAgent
QA_V3_SECTION_ANCHOR_RANKER      — anchor-vocab section ranker cross-check
QA_V3_CONTENT_DISPATCH           — intent->content-source dispatch gating
QA_V3_FAMILY_DEDUP               — collapse SBP/BP into one family on counting
QA_V3_CLARIFICATION_TRIGGERS     — anchor/intent-driven clarification triggers

(There is no PARSER_SECTION_MAP flag: the parser deliberately does
not consume ais_guideline_section_map.json — that file is reserved
for the deterministic SectionRouter. See .notes/v3_scaffolding_audit.md
for the rationale.)

All flags default to ENABLED (True) when the env var is unset, missing,
empty, or any value other than the explicit "off" set.
"""

from __future__ import annotations

import os
from typing import Dict


_OFF_VALUES = {"0", "false", "no", "off", "disable", "disabled"}


def _read(env_var: str, default: bool = True) -> bool:
    """Return True iff the env var is unset OR set to anything not in
    the off-set. Defaults to True so the new pipeline is ON by default."""
    raw = os.environ.get(env_var)
    if raw is None:
        return default
    return raw.strip().lower() not in _OFF_VALUES


# ---------------------------------------------------------------------------
# Public flag constants — read once at import. Tests may monkey-patch.
# ---------------------------------------------------------------------------

REC_ANCHOR_PREFILTER: bool = _read("QA_V3_REC_ANCHOR_PREFILTER")
RSS_ANCHOR_FILTER: bool = _read("QA_V3_RSS_ANCHOR_FILTER")
KG_ANCHOR_FILTER: bool = _read("QA_V3_KG_ANCHOR_FILTER")
SECTION_ANCHOR_RANKER: bool = _read("QA_V3_SECTION_ANCHOR_RANKER")
CONTENT_DISPATCH: bool = _read("QA_V3_CONTENT_DISPATCH")
FAMILY_DEDUP: bool = _read("QA_V3_FAMILY_DEDUP")
CLARIFICATION_TRIGGERS: bool = _read("QA_V3_CLARIFICATION_TRIGGERS")
# scispaCy lemma fallback inside AnchorVocab.extract. When off, the
# anchor filter runs with literal token-boundary containment only,
# exactly matching pre-scispaCy behavior.
SCISPACY: bool = _read("QA_V3_SCISPACY")


def snapshot() -> Dict[str, bool]:
    """Return the current flag values as a dict for audit logging."""
    return {
        "REC_ANCHOR_PREFILTER": REC_ANCHOR_PREFILTER,
        "RSS_ANCHOR_FILTER": RSS_ANCHOR_FILTER,
        "KG_ANCHOR_FILTER": KG_ANCHOR_FILTER,
        "SECTION_ANCHOR_RANKER": SECTION_ANCHOR_RANKER,
        "CONTENT_DISPATCH": CONTENT_DISPATCH,
        "FAMILY_DEDUP": FAMILY_DEDUP,
        "CLARIFICATION_TRIGGERS": CLARIFICATION_TRIGGERS,
        "SCISPACY": SCISPACY,
    }


if __name__ == "__main__":  # pragma: no cover
    import json
    print(json.dumps(snapshot(), indent=2))
