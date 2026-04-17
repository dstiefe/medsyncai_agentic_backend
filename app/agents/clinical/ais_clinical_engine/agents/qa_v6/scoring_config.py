"""
qa_v6 scoring configuration.

ONE set of weights and thresholds. ONE threshold. ONE retrieval path.

All signals contribute to a single score per atom:
  score = W_SEMANTIC   * cosine_similarity
        + W_INTENT     * intent_affinity_match
        + W_PINPOINT   * pinpoint_anchor_coverage
        + W_GLOBAL     * global_anchor_match (tiebreaker only — see doctrine)
        + W_VALUE      * value_range_satisfaction
        + W_VALUE_GUIDED * value_guided_hit

Semantic is the primary signal. Pinpoint anchors are the primary lexical
discriminator and act as a CONJUNCTIVE AND-GATE upstream of scoring.
Global anchors (IVT, stroke, AIS) contribute minimally and only when
paired with a pinpoint anchor or a value signal — a purely global query
cannot discriminate and should not be steered by its global terms.

See `references/anchor_semantics.md` for the full anchor doctrine. The
weights below are calibrated under that doctrine; changing the doctrine
without recalibrating these weights will produce inconsistent behaviour.
"""

# ── Signal weights ────────────────────────────────────────────────
# All signals produce values in [0, 1] so weights are directly
# comparable. Weights sum to ~1.0 so total score lands in [0, 1.2].
#
# 2026-04-17 retune: clinician policy is "rather trigger clarifying
# questions than leak weak relations." Semantic weight reduced so
# exact anchor/intent signals dominate; topic alignment bumped so
# section-correct matches stand out; thresholds raised elsewhere.

W_SEMANTIC = 0.25      # Cosine similarity — still primary but no
                       # longer carries an atom alone. Was 0.40.
W_INTENT = 0.25        # Intent affinity match — now co-equal with
                       # pinpoint and semantic. Was 0.20.
W_PINPOINT = 0.25      # Pinpoint anchor coverage — now co-equal with
                       # intent and semantic. Was 0.20.
W_TOPIC = 0.10         # Step 2b-confirmed topic → section alignment.
                       # Bumped from 0.05 so correct-section atoms
                       # pull ahead of lexically-similar off-topic.
W_GLOBAL = 0.05        # Global anchor match — tie-breaker only
W_VALUE = 0.05         # Value range satisfaction — when applicable
W_VALUE_GUIDED = 0.05  # Any numeric context near an anchor with a value

# ── Signal thresholds ─────────────────────────────────────────────

# Clinician policy: "rather trigger clarifying questions than leak weak
# relations." The thresholds below are tuned toward asking for
# clarification instead of surfacing near-miss content.

# Minimum total score for an atom to survive retrieval.
# Raised 0.22 → 0.30 to drop tail noise. An atom must have:
#   - strong semantic (cos ≥ 0.55), OR
#   - intent match + decent pinpoint, OR
#   - intent + topic bonus + some semantic signal
# in order to score above 0.30.
SCORE_THRESHOLD = 0.30

# Minimum semantic cosine for an atom to qualify at all on semantic
# signal. Raised 0.30 → 0.45 so "vaguely similar" atoms don't
# accumulate weak-semantic points that push them over threshold.
SEMANTIC_SIGNAL_FLOOR = 0.45

# Top-match confidence floor. If the highest-scoring retrieved rec
# is below this total score, the system prefers to TRIGGER A
# CLARIFICATION (asking the clinician to refine) rather than surface
# a best-guess answer from weakly-matched recs. 0.50 corresponds to
# roughly: strong semantic (0.55 cos) + intent match + pinpoint
# coverage — i.e. a "confidently answerable" match.
MIN_CONFIDENT_SCORE = 0.50

# Semantic fallback for the pinpoint AND-gate. If the lexical /
# stem-match gate fails but the query-anchor's embedding cosine
# against the atom's embedding is ≥ PINPOINT_SEMANTIC_FLOOR, treat
# the pinpoint anchor as satisfied. This lets clinically-equivalent
# phrasings match even when they share no tokens — e.g. query
# anchor "non-disabling stroke" matches a T4.3 atom about
# "isolated mild aphasia" via semantic similarity, not string match.
# The lexical fast path still runs first, so discrimination is
# preserved when tokens align.
PINPOINT_SEMANTIC_FLOOR = 0.55

# Global anchor terms. These appear across many sections and don't
# discriminate — weighted low. Maintained here so retrieval can
# identify tier when the guideline_anchor_words.json lookup misses.
GLOBAL_ANCHOR_TERMS = frozenset({
    "ivt", "iv thrombolysis", "intravenous thrombolysis",
    "stroke", "ais", "acute ischemic stroke", "cerebral ischemia",
    "thrombolysis", "alteplase", "tenecteplase", "tpa",
    "evt", "thrombectomy", "endovascular thrombectomy",
    "patient", "patients",
})

# ── Result caps ───────────────────────────────────────────────────

MAX_RECS = 3               # Cap at 3 recs. >3 clustered → clarification.
MAX_RSS = 10               # Supporting evidence rows
MAX_TABLES = 5             # Tables included
MAX_FIGURES = 3            # Figures included

# Relative clustering band: if multiple recs are within this fraction
# of the top rec's score, they're "close" — may indicate ambiguity.
REC_TIGHT_BAND = 0.85  # within 85% of top → counted as clustered

# ── Intent families that want knowledge gaps in output ────────────
# KG is research-oriented; only include when the intent is about
# uncertainty/gaps. For prescriptive intents, KG is noise.
KG_INTENTS = frozenset({
    "knowledge_gap",
    "current_understanding_and_gaps",
    "evidence_vs_gaps",
    "rationale_with_uncertainty",
    "recommendation_with_confidence",
    "pediatric_specific",
})
