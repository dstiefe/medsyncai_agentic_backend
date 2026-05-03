"""
Per-gate satisfaction helpers — deterministic functions that decide whether
each interactive gate has enough explicitly stated information to close.

Design principle (from product):
    "If it's not clear from what the user wrote, leave the gate unanswered."

A gate closes only when every strict criterion of at least one applicable
recommendation is explicitly populated (non-null). Anything less leaves the
gate as "needed" with a list of the specific missing criteria.

These helpers are pure: ParsedVariables in, status out. No I/O, no LLM calls,
no inference beyond reading the populated fields.

Phase 2 — covers Advanced Imaging gate (Rec 4.6.3-001/002/003).
Other gates (Symptom Recognition, Wake-Up Time, EVT Availability,
Contraindication Review, Disabling Deficit) follow the same pattern in
later phases.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Literal, Optional

from ..models.clinical import ParsedVariables


GateStatus = Literal["satisfied", "unsatisfied", "needed"]


@dataclass
class RecImagingStatus:
    """Per-rec evaluation of imaging criteria."""

    rec_id: str
    evaluable: bool
    meets: bool
    missing_criteria: List[str] = field(default_factory=list)


@dataclass
class ImagingGateStatus:
    """Aggregate Advanced Imaging gate status across all extended-window recs."""

    status: GateStatus
    matched_rec_id: Optional[str] = None
    rec_statuses: List[RecImagingStatus] = field(default_factory=list)
    missing_criteria: List[str] = field(default_factory=list)


# ── Rec 4.6.3-001: DWI-FLAIR mismatch pathway ────────────────────────────────
# Criteria (all four must be explicitly stated):
#   - MRI was performed (imagingModality == "mri" or "both")
#   - DWI lesion present (dwiLesionPresent == True/False)
#   - DWI lesion < 1/3 MCA territory (dwiLesionSmallerThanThirdMca == True/False)
#   - FLAIR shows no marked signal change (flairMarkedSignalChange == False) —
#     the criterion that defines the mismatch
_REC_4_6_3_001_CRITERIA = [
    ("imagingModality", "MRI modality"),
    ("dwiLesionPresent", "DWI lesion presence"),
    ("dwiLesionSmallerThanThirdMca", "DWI lesion size relative to MCA territory"),
    ("flairMarkedSignalChange", "FLAIR signal change"),
]


def _rec_4_6_3_001_imaging_status(parsed: ParsedVariables) -> RecImagingStatus:
    missing = [
        label for attr, label in _REC_4_6_3_001_CRITERIA
        if getattr(parsed, attr) is None
    ]
    # Composite shortcut: user stated "DWI-FLAIR mismatch" directly. Counts as
    # satisfying the DWI-present / FLAIR-negative pair, but lesion size and
    # modality still need to be stated independently.
    if parsed.dwiFlair is True:
        missing = [m for m in missing if m not in (
            "DWI lesion presence", "FLAIR signal change",
        )]
    evaluable = not missing
    if not evaluable:
        return RecImagingStatus(
            rec_id="rec-4.6.3-001",
            evaluable=False,
            meets=False,
            missing_criteria=missing,
        )
    meets = (
        parsed.imagingModality in ("mri", "both")
        and (parsed.dwiFlair is True or (
            parsed.dwiLesionPresent is True
            and parsed.flairMarkedSignalChange is False
        ))
        and parsed.dwiLesionSmallerThanThirdMca is True
    )
    return RecImagingStatus(
        rec_id="rec-4.6.3-001",
        evaluable=True,
        meets=meets,
    )


# ── Rec 4.6.3-002: Perfusion mismatch pathway ────────────────────────────────
# Criteria (both must be explicitly stated):
#   - Automated perfusion modality performed (imagingModality == "ctp" or "both")
#   - Salvageable penumbra detected (penumbra == True/False)
# Time criteria (4.5–9h or wake-up <9h) are checked in separate gates.
_REC_4_6_3_002_CRITERIA = [
    ("imagingModality", "perfusion modality (CTP or MR perfusion)"),
    ("penumbra", "salvageable penumbra"),
]


def _rec_4_6_3_002_imaging_status(parsed: ParsedVariables) -> RecImagingStatus:
    missing = [
        label for attr, label in _REC_4_6_3_002_CRITERIA
        if getattr(parsed, attr) is None
    ]
    evaluable = not missing
    if not evaluable:
        return RecImagingStatus(
            rec_id="rec-4.6.3-002",
            evaluable=False,
            meets=False,
            missing_criteria=missing,
        )
    meets = (
        parsed.imagingModality in ("ctp", "both")
        and parsed.penumbra is True
    )
    return RecImagingStatus(
        rec_id="rec-4.6.3-002",
        evaluable=True,
        meets=meets,
    )


# ── Rec 4.6.3-003: LVO + penumbra + no EVT pathway ───────────────────────────
# Imaging criteria match Rec 4.6.3-002 (same "automated perfusion + penumbra").
# LVO confirmation, time, and EVT-availability are gated separately.
def _rec_4_6_3_003_imaging_status(parsed: ParsedVariables) -> RecImagingStatus:
    base = _rec_4_6_3_002_imaging_status(parsed)
    return RecImagingStatus(
        rec_id="rec-4.6.3-003",
        evaluable=base.evaluable,
        meets=base.meets,
        missing_criteria=base.missing_criteria,
    )


# ── Aggregate: Advanced Imaging gate ─────────────────────────────────────────


def advanced_imaging_gate_status(parsed: ParsedVariables) -> ImagingGateStatus:
    """Decide the Advanced Imaging gate status from extracted variables.

    Returns:
        - status="satisfied" + matched_rec_id when at least one rec's imaging
          criteria are all stated AND meet the rec requirements.
        - status="unsatisfied" when imaging is fully stated but no rec applies
          (e.g. user explicitly said no DWI lesion AND no penumbra), OR both
          modalities are unavailable.
        - status="needed" when no rec has all imaging criteria stated.
    """
    rec_statuses = [
        _rec_4_6_3_001_imaging_status(parsed),
        _rec_4_6_3_002_imaging_status(parsed),
        _rec_4_6_3_003_imaging_status(parsed),
    ]

    # 1. Any rec satisfied → gate closed satisfied. Prefer the first matching
    # rec in declaration order (4.6.3-001 → -002 → -003); Phase 5 picker can
    # apply more nuanced selection if needed.
    for rs in rec_statuses:
        if rs.evaluable and rs.meets:
            return ImagingGateStatus(
                status="satisfied",
                matched_rec_id=rs.rec_id,
                rec_statuses=rec_statuses,
            )

    # 2. Both modalities unavailable → no extended-window pathway possible.
    if parsed.mriUnavailable is True and parsed.ctpUnavailable is True:
        return ImagingGateStatus(
            status="unsatisfied",
            rec_statuses=rec_statuses,
        )

    # 3. At least one rec is fully evaluable but none meet — imaging done but
    # no rec applies (e.g. DWI lesion stated as larger than 1/3 MCA → Rec 1
    # fails; no penumbra stated → Rec 2/3 fails). Gate closes negatively.
    if any(rs.evaluable for rs in rec_statuses):
        return ImagingGateStatus(
            status="unsatisfied",
            rec_statuses=rec_statuses,
        )

    # 4. Otherwise, gate is needed. Surface the union of missing criteria
    # across all recs so the UI can show what's still required.
    missing_union: List[str] = []
    seen = set()
    for rs in rec_statuses:
        for m in rs.missing_criteria:
            if m not in seen:
                seen.add(m)
                missing_union.append(m)
    return ImagingGateStatus(
        status="needed",
        rec_statuses=rec_statuses,
        missing_criteria=missing_union,
    )
