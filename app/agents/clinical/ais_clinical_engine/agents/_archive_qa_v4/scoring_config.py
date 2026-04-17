"""
Shared scoring constants for the qa_v4 retrieval pipeline.

All three retrieval levels (dispatcher, atom, rec) draw their weights
and thresholds from this one module. When the philosophy changes, it
changes here — not scattered across 4 files with subtle inconsistencies.

Design principles:
  1. Semantic similarity is the primary signal at every level.
  2. Intent alignment is a secondary boost.
  3. Lexical anchor matching and value ranges are precision tiebreakers
     within semantically-close content.
  4. All thresholds must be justified with a comment.
"""

# ── Normalized-scale weights (used where score is in [0, 1]) ──────
#
# Dispatcher and atom scoring live in the [0, 1] range because their
# semantic component (cosine similarity) is already in [0, 1]. Other
# components are multiplied by small weights so the total stays in
# a predictable range.

# Dispatcher (picks concept sections from 75 candidates):
#   Composite = SEMANTIC*cos + INTENT*intent_match + THRESHOLD*value_hits
#   Semantic dominates so LLM intent misclassification doesn't override
#   a clear semantic win. Threshold represents explicit clinical
#   scenarios (e.g., INR > 1.7) and gets a strong one-shot bonus.
DISPATCHER_SEMANTIC_WEIGHT = 0.9
DISPATCHER_INTENT_WEIGHT = 0.1
DISPATCHER_THRESHOLD_BONUS = 0.5  # per threshold crossed

# A concept section must clear this combined score to be considered.
# semantic 0.4 + intent 0 = 0.36 passes. Lower blocks pure-vocabulary
# matches that don't actually mean what the clinician is asking.
DISPATCHER_MIN_COMBINED_SCORE = 0.35

# Among sections above the floor, only those within this fraction
# of the top score are returned. 93% keeps tightly competitive
# sections, drops marginal ones.
DISPATCHER_RELATIVE_TOP_BAND = 0.93

# Hard cap to prevent noise cascade from multiple matches.
DISPATCHER_MAX_SECTIONS = 3


# Atom scoring (within a dispatched concept section, picks best atoms):
#   Composite = SEMANTIC*cos + INTENT*intent_match + ANCHOR*jaccard + VALUE*range_hit
#   Semantic is still primary (0.5) but lexical signals help
#   differentiate atoms that all semantically match the concept.
ATOM_SEMANTIC_WEIGHT = 0.5
ATOM_INTENT_WEIGHT = 0.2
ATOM_ANCHOR_WEIGHT = 0.2
ATOM_VALUE_WEIGHT = 0.1

# Atom score threshold — below this, atom is dropped.
# 0.2 = a 0.4 cos_sim semantic match is enough (0.4 * 0.5 = 0.2),
# OR an intent match plus any other signal, OR strong anchor overlap.
ATOM_SCORE_THRESHOLD = 0.2


# ── Lexical-scale thresholds (used where score is 10-500 range) ──
#
# Rec and RSS row scoring produces scores on a lexical scale where
# each matched concept contributes ~10 points, with multipliers for
# coverage ratio, co-occurrence, and intent alignment. Semantic is
# added on top via a large multiplier so it's comparable.

# Semantic-to-lexical conversion: semantic is in [0, 1]; multiply
# to bring it into the same range as lexical scoring's 10-500.
SEMANTIC_TO_LEXICAL_MULTIPLIER = 100.0

# Row/rec score thresholds. A row or rec must clear BOTH the
# absolute floor AND the relative floor (fraction of section top).
ROW_SCORE_ABSOLUTE_FLOOR = 20.0
ROW_SCORE_RELATIVE_FLOOR = 0.3   # 30% of top row's score

REC_SCORE_ABSOLUTE_FLOOR = 20.0
REC_SCORE_RELATIVE_FLOOR = 0.3   # 30% of top rec's score

# Temporal/relational bonus in Path A row scoring. Query words like
# "after", "before", "within" that appear in row text boost score.
RELATIONAL_BONUS_PER_WORD = 15.0


# ── Shared semantic signal gates ──────────────────────────────────
#
# A content item must have SOME signal — either lexical match OR
# non-trivial semantic similarity — to enter the candidate pool.
# This prevents force-including items that happen to share a tag
# but have zero actual query relevance.

# Minimum semantic cosine for a rec/atom to qualify on semantic alone
# (no lexical match required). 0.3 is well above random noise (~0.1)
# and below clear topical matches (~0.5+).
SEMANTIC_SIGNAL_FLOOR = 0.3
