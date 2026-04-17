"""
qa_v6 scoring configuration.

ONE set of weights and thresholds. ONE threshold. ONE retrieval path.

All signals contribute to a single score per atom:
  score = W_SEMANTIC   * cosine_similarity
        + W_INTENT     * intent_affinity_match
        + W_PINPOINT   * pinpoint_anchor_coverage
        + W_GLOBAL     * global_anchor_match (tiebreaker only)
        + W_VALUE      * value_range_satisfaction
        + W_VALUE_GUIDED * value_guided_hit

Semantic is the primary signal. Pinpoint anchors are the primary
lexical discriminator. Global anchors (IVT, stroke, AIS) contribute
minimally so they don't dominate rankings by appearing in every
related section. Values guide toward quantitatively specific content.
"""

# ── Signal weights ────────────────────────────────────────────────
# All signals produce values in [0, 1] so weights are directly
# comparable. Weights sum to ~1.0 so total score lands in [0, 1.2].

W_SEMANTIC = 0.40      # Cosine similarity — primary signal
W_INTENT = 0.20        # Intent affinity match — strong secondary
W_PINPOINT = 0.20      # Pinpoint anchor coverage — discriminating
W_TOPIC = 0.05         # Step 2b-confirmed topic → section alignment
W_GLOBAL = 0.05        # Global anchor match — kept as tie-breaker;
                       # removing it narrowed score distribution and
                       # caused ambiguity detector to over-trigger
W_VALUE = 0.05         # Value range satisfaction — when applicable
W_VALUE_GUIDED = 0.05  # Any numeric context near an anchor with a value

# ── Signal thresholds ─────────────────────────────────────────────

# Minimum total score for an atom to survive. Calibrated so:
#   - Strong semantic alone (cos ≥ 0.55): 0.45 × 0.55 = 0.25 → passes
#   - Strong pinpoint alone (2/2 anchors): 0.20 × 1.0 = 0.20 → passes
#   - Intent-only match: 0.20 → barely passes (OK — pinpoint corroborates)
#   - Weak semantic (cos ≈ 0.3) alone: 0.135 → dropped (as intended)
SCORE_THRESHOLD = 0.22

# Minimum semantic cosine for an atom to qualify on semantic alone
# (no lexical match required). Below this, cosine noise dominates.
SEMANTIC_SIGNAL_FLOOR = 0.3

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
