"""
Per-gate / per-rec satisfaction helpers — deterministic functions that
decide whether each interactive gate or recommendation has enough explicitly
stated information to close / apply.

Design principle (from product):
    "If it's not clear from what the user wrote, leave the gate unanswered."

A gate closes only when every strict criterion of at least one applicable
recommendation is explicitly populated (non-null). Anything less leaves the
gate as "needed" with a list of the specific missing criteria.

These helpers are pure: ParsedVariables in, status out. No I/O, no LLM calls,
no inference beyond reading the populated fields.

Coverage:
- Advanced Imaging gate — full Rec 4.6.3-001/002/003 imaging criteria
- Symptom Recognition / Wake-Up Time / EVT Availability / Disabling
  Deficit / LKW <24h / M2 Dominance / Contraindication Review gates
- Per-rec satisfaction for §4.6.1, §4.6.2, §4.6.3, §4.7.1, §4.7.2,
  §4.7.3, §4.3 (BP) — covers the IVT and EVT decision pathways used
  by the navigator
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


# ════════════════════════════════════════════════════════════════════════════
# Per-rec satisfaction helpers
#
# Each function returns True only if every strict criterion for that rec is
# explicitly populated AND meets the rec requirements. Returns False if any
# criterion is contradicted; returns None if any criterion is null (meaning
# "not stated by user — gate stays open").
#
# Helpers are intentionally narrow: they answer "does this rec apply?", not
# "what should the navigator say?". Pathway picking and display text are
# downstream concerns.
# ════════════════════════════════════════════════════════════════════════════


def _all_stated(*values) -> bool:
    """True only if every value is explicitly populated (not None)."""
    return all(v is not None for v in values)


# ── §4.6.1 Thrombolysis Decision-Making ──────────────────────────────────────


def rec_4_6_1_001_satisfied(parsed: ParsedVariables) -> Optional[bool]:
    """COR 1, A — Adult AIS with disabling deficits, eligible for IVT, faster
    treatment improves outcomes. Standard window, disabling deficit."""
    age = parsed.age
    nondis = parsed.nonDisabling
    lkw = parsed.lastKnownWellHours
    if not _all_stated(age, nondis, lkw):
        return None
    return age >= 18 and nondis is False and lkw <= 4.5


def rec_4_6_1_008_satisfied(parsed: ParsedVariables) -> Optional[bool]:
    """COR 3:NB, B-R — Mild non-disabling deficits within 4.5h: IVT NOT
    recommended; double antiplatelet preferred."""
    nondis = parsed.nonDisabling
    nihss = parsed.nihss
    lkw = parsed.lastKnownWellHours
    if not _all_stated(nondis, nihss, lkw):
        return None
    return nondis is True and nihss <= 5 and lkw <= 4.5


def rec_4_6_1_014_satisfied(parsed: ParsedVariables) -> Optional[bool]:
    """COR 2b, C-LD — Pediatric AIS (28d–18y), within 4.5h, disabling deficits.
    Alteplase 0.9 mg/kg may be considered."""
    age = parsed.age
    nondis = parsed.nonDisabling
    lkw = parsed.lastKnownWellHours
    if not _all_stated(age, nondis, lkw):
        return None
    return age < 18 and nondis is False and lkw <= 4.5


# ── §4.6.2 Choice of Thrombolytic Agent ──────────────────────────────────────


def rec_4_6_2_001_satisfied(parsed: ParsedVariables) -> Optional[bool]:
    """COR 1, A — TNK 0.25 mg/kg or alteplase 0.9 mg/kg recommended for adult
    AIS within 4.5h, eligible for IVT."""
    age = parsed.age
    lkw = parsed.lastKnownWellHours
    if not _all_stated(age, lkw):
        return None
    return age >= 18 and lkw <= 4.5


def rec_4_6_2_002_satisfied(parsed: ParsedVariables) -> Optional[bool]:
    """COR 3:NB, A — TNK 0.4 mg/kg NOT recommended within 4.5h. Same trigger
    population as 4.6.2-001 — applies whenever eligibility for IVT is met."""
    return rec_4_6_2_001_satisfied(parsed)


# ── §4.6.3 Extended Time Windows ─────────────────────────────────────────────
# Imaging criteria already covered by _rec_4_6_3_*_imaging_status helpers
# above; the per-rec satisfaction helpers here add the time / vessel /
# EVT-availability legs for the full rec eligibility check.


def rec_4_6_3_001_satisfied(parsed: ParsedVariables) -> Optional[bool]:
    """COR 2a, B-R — Unknown onset + Sx Recognition <4.5h + DWI-FLAIR mismatch
    + DWI <1/3 MCA + FLAIR no marked change."""
    img = _rec_4_6_3_001_imaging_status(parsed)
    if not img.evaluable:
        return None
    if not img.meets:
        return False
    sx = parsed.symptomRecognizedWithin4_5h
    if sx is None:
        return None
    return sx is True


def rec_4_6_3_002_satisfied(parsed: ParsedVariables) -> Optional[bool]:
    """COR 2a, B-R — Salvageable penumbra on automated perfusion + (wake-up
    <9h from sleep midpoint OR 4.5–9h from LKW)."""
    img = _rec_4_6_3_002_imaging_status(parsed)
    if not img.evaluable:
        return None
    if not img.meets:
        return False
    lkw = parsed.lastKnownWellHours
    mid = parsed.wakeUpMidpointToPresentationHours
    wakeup = parsed.wakeUp
    # Time leg satisfied if EITHER: 4.5–9h from LKW OR wake-up + mid≤9h.
    lkw_leg = lkw is not None and 4.5 < lkw <= 9
    midsleep_leg = wakeup is True and mid is not None and mid <= 9
    if lkw_leg or midsleep_leg:
        return True
    # Both legs evaluable but neither meets → False.
    if (lkw is not None) and (wakeup is False or mid is not None):
        return False
    return None


def rec_4_6_3_003_satisfied(
    parsed: ParsedVariables,
    evt_excluded_by_engine: bool = False,
) -> Optional[bool]:
    """COR 2b, B-R — LVO + salvageable penumbra + 4.5–24h + cannot receive EVT.
    'cannot receive EVT' = clinician gate OR engine-determined ineligibility."""
    img = _rec_4_6_3_003_imaging_status(parsed)
    if not img.evaluable:
        return None
    if not img.meets:
        return False
    lvo = parsed.isLVO
    lkw = parsed.lastKnownWellHours
    cannot_receive_evt = parsed.evtUnavailable is True or evt_excluded_by_engine
    if lvo is None or lkw is None:
        return None
    return lvo is True and 4.5 < lkw <= 24 and cannot_receive_evt


# ── §4.7.1 Concomitant IVT + EVT ─────────────────────────────────────────────


def rec_4_7_1_001_satisfied(parsed: ParsedVariables) -> Optional[bool]:
    """COR 1, A — IVT is safe and recommended for patients eligible for both
    IVT and EVT. Trigger = LVO + standard IVT window (eligibility for both)."""
    lvo = parsed.isLVO
    lkw = parsed.lastKnownWellHours
    nondis = parsed.nonDisabling
    if not _all_stated(lvo, lkw, nondis):
        return None
    return lvo is True and lkw <= 4.5 and nondis is False


def rec_4_7_1_002_satisfied(parsed: ParsedVariables) -> Optional[bool]:
    """COR 1, A — IVT should be administered as rapidly as possible without
    waiting to assess response before EVT. Same trigger as 4.7.1-001."""
    return rec_4_7_1_001_satisfied(parsed)


# ── §4.7.2 Endovascular Thrombectomy for Adults ──────────────────────────────


def _evt_anterior_lvo(parsed: ParsedVariables) -> Optional[bool]:
    v = (parsed.vessel or "").upper()
    if not v:
        return None
    return v in ("ICA", "M1")


def rec_4_7_2_001_satisfied(parsed: ParsedVariables) -> Optional[bool]:
    """COR 1, A — Anterior LVO (ICA/M1), 0–6h, NIHSS≥6, mRS 0–1, ASPECTS 3–10."""
    if not _all_stated(parsed.lastKnownWellHours, parsed.nihss, parsed.prestrokeMRS, parsed.aspects):
        return None
    anterior = _evt_anterior_lvo(parsed)
    if anterior is None:
        return None
    return (
        anterior is True
        and parsed.lastKnownWellHours <= 6
        and parsed.nihss >= 6
        and parsed.prestrokeMRS <= 1
        and 3 <= parsed.aspects <= 10
    )


def rec_4_7_2_002_satisfied(parsed: ParsedVariables) -> Optional[bool]:
    """COR 1, A — Anterior LVO, 6–24h, NIHSS≥6, mRS 0–1, ASPECTS≥6."""
    if not _all_stated(parsed.lastKnownWellHours, parsed.nihss, parsed.prestrokeMRS, parsed.aspects):
        return None
    anterior = _evt_anterior_lvo(parsed)
    if anterior is None:
        return None
    return (
        anterior is True
        and 6 < parsed.lastKnownWellHours <= 24
        and parsed.nihss >= 6
        and parsed.prestrokeMRS <= 1
        and parsed.aspects >= 6
    )


def rec_4_7_2_003_satisfied(parsed: ParsedVariables) -> Optional[bool]:
    """COR 1, A — Selected anterior LVO, 6–24h, age<80, NIHSS≥6, mRS 0–1,
    ASPECTS 3–5, no significant mass effect."""
    if not _all_stated(parsed.age, parsed.lastKnownWellHours, parsed.nihss,
                        parsed.prestrokeMRS, parsed.aspects, parsed.massEffectSignificant):
        return None
    anterior = _evt_anterior_lvo(parsed)
    if anterior is None:
        return None
    return (
        anterior is True
        and parsed.age < 80
        and 6 < parsed.lastKnownWellHours <= 24
        and parsed.nihss >= 6
        and parsed.prestrokeMRS <= 1
        and 3 <= parsed.aspects <= 5
        and parsed.massEffectSignificant is False
    )


def rec_4_7_2_004_satisfied(parsed: ParsedVariables) -> Optional[bool]:
    """COR 2a, B-R — Selected anterior LVO, 0–6h, age<80, NIHSS≥6, mRS 0–1,
    ASPECTS 0–2, no significant mass effect."""
    if not _all_stated(parsed.age, parsed.lastKnownWellHours, parsed.nihss,
                        parsed.prestrokeMRS, parsed.aspects, parsed.massEffectSignificant):
        return None
    anterior = _evt_anterior_lvo(parsed)
    if anterior is None:
        return None
    return (
        anterior is True
        and parsed.age < 80
        and parsed.lastKnownWellHours <= 6
        and parsed.nihss >= 6
        and parsed.prestrokeMRS <= 1
        and 0 <= parsed.aspects <= 2
        and parsed.massEffectSignificant is False
    )


def rec_4_7_2_005_satisfied(parsed: ParsedVariables) -> Optional[bool]:
    """COR 2a, B-NR — Anterior LVO, 0–6h, NIHSS≥6, ASPECTS≥6, prestroke mRS 2."""
    if not _all_stated(parsed.lastKnownWellHours, parsed.nihss, parsed.prestrokeMRS, parsed.aspects):
        return None
    anterior = _evt_anterior_lvo(parsed)
    if anterior is None:
        return None
    return (
        anterior is True
        and parsed.lastKnownWellHours <= 6
        and parsed.nihss >= 6
        and parsed.aspects >= 6
        and parsed.prestrokeMRS == 2
    )


def rec_4_7_2_006_satisfied(parsed: ParsedVariables) -> Optional[bool]:
    """COR 2b, B-NR — Anterior LVO, 0–6h, NIHSS≥6, ASPECTS≥6, prestroke mRS 3–4."""
    if not _all_stated(parsed.lastKnownWellHours, parsed.nihss, parsed.prestrokeMRS, parsed.aspects):
        return None
    anterior = _evt_anterior_lvo(parsed)
    if anterior is None:
        return None
    return (
        anterior is True
        and parsed.lastKnownWellHours <= 6
        and parsed.nihss >= 6
        and parsed.aspects >= 6
        and 3 <= parsed.prestrokeMRS <= 4
    )


def rec_4_7_2_007_satisfied(parsed: ParsedVariables) -> Optional[bool]:
    """COR 2a, B-NR — Dominant proximal M2, 0–6h, mRS 0–1, NIHSS≥6, ASPECTS≥6."""
    if not _all_stated(parsed.lastKnownWellHours, parsed.nihss, parsed.prestrokeMRS,
                        parsed.aspects, parsed.m2Dominant):
        return None
    v = (parsed.vessel or "").upper()
    if not v:
        return None
    return (
        v == "M2"
        and parsed.m2Dominant is True
        and parsed.lastKnownWellHours <= 6
        and parsed.nihss >= 6
        and parsed.prestrokeMRS <= 1
        and parsed.aspects >= 6
    )


def rec_4_7_2_008_satisfied(parsed: ParsedVariables) -> Optional[bool]:
    """COR 3:NB, A — Nondominant/codominant M2, distal MCA, ACA, PCA → EVT NOT
    recommended."""
    v = (parsed.vessel or "").upper()
    if not v:
        return None
    if v == "M2":
        if parsed.m2Dominant is None:
            return None
        return parsed.m2Dominant is False
    return v in ("DISTAL_MCA", "M3", "ACA", "PCA")


# ── §4.7.3 Posterior Circulation EVT ─────────────────────────────────────────


def rec_4_7_3_001_satisfied(parsed: ParsedVariables) -> Optional[bool]:
    """COR 1, A — Basilar artery occlusion ≤24h, NIHSS≥10, mRS 0–1, PC-ASPECTS≥6,
    pons-midbrain index <3."""
    if not _all_stated(parsed.lastKnownWellHours, parsed.nihss, parsed.prestrokeMRS,
                        parsed.pcAspects, parsed.ponsMidbrainIndex):
        return None
    v = (parsed.vessel or "").lower()
    if not v:
        return None
    return (
        v in ("basilar", "ba")
        and parsed.lastKnownWellHours <= 24
        and parsed.nihss >= 10
        and parsed.prestrokeMRS <= 1
        and parsed.pcAspects >= 6
        and parsed.ponsMidbrainIndex < 3
    )


def rec_4_7_3_002_satisfied(parsed: ParsedVariables) -> Optional[bool]:
    """COR 2b, B-R — Basilar artery occlusion, NIHSS 6–9. Effectiveness not
    well established. Same baseline criteria as 4.7.3-001 except NIHSS band."""
    if not _all_stated(parsed.lastKnownWellHours, parsed.nihss, parsed.prestrokeMRS,
                        parsed.pcAspects, parsed.ponsMidbrainIndex):
        return None
    v = (parsed.vessel or "").lower()
    if not v:
        return None
    return (
        v in ("basilar", "ba")
        and parsed.lastKnownWellHours <= 24
        and 6 <= parsed.nihss <= 9
        and parsed.prestrokeMRS <= 1
        and parsed.pcAspects >= 6
        and parsed.ponsMidbrainIndex < 3
    )


# ── §4.3 Blood Pressure Management ───────────────────────────────────────────


def rec_4_3_005_satisfied(parsed: ParsedVariables) -> Optional[bool]:
    """COR 1, B-NR — Lower SBP <185 and DBP <110 before IVT. Trigger = elevated
    BP in IVT-eligible patient."""
    if not _all_stated(parsed.sbp, parsed.dbp, parsed.lastKnownWellHours):
        return None
    elevated = parsed.sbp >= 185 or parsed.dbp >= 110
    return elevated and parsed.lastKnownWellHours <= 4.5


def rec_4_3_006_satisfied(parsed: ParsedVariables) -> Optional[bool]:
    """COR 2a, B-NR — Maintain BP ≤185/110 before EVT for patients not getting
    IVT. Trigger = LVO + EVT-window + no IVT given."""
    if not _all_stated(parsed.sbp, parsed.dbp, parsed.isLVO, parsed.ivtNotGiven):
        return None
    return (
        parsed.isLVO is True
        and parsed.ivtNotGiven is True
        and (parsed.sbp >= 185 or parsed.dbp >= 110)
    )


def rec_4_3_007_satisfied(parsed: ParsedVariables) -> Optional[bool]:
    """COR 1, B-R — Maintain BP <180/105 for ≥24h after IVT."""
    if parsed.ivtGiven is None:
        return None
    return parsed.ivtGiven is True


def rec_4_3_009_satisfied(parsed: ParsedVariables) -> Optional[bool]:
    """COR 2a, B-NR — Maintain BP ≤180/105 during and 24h after EVT."""
    # Requires confirmation EVT was performed; we don't have an explicit
    # 'evtPerformed' field, so leave None unless gateable.
    return None


def rec_4_3_010_satisfied(parsed: ParsedVariables) -> Optional[bool]:
    """COR 3:Harm, A — Intensive SBP <140 for 72h after successful anterior LVO
    EVT is HARMFUL. Trigger = anterior LVO + successful recanalization."""
    # Requires post-EVT recanalization status (mTICI 2b/2c/3) which is
    # not yet a parsed field; leave None until added.
    return None

