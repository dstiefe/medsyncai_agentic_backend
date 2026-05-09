"""qa_v7 — redesigned Guideline Q&A pipeline.

Architecture (from the v7 design doc):

  Step 1a: LLM extraction       — this module (query_parser.py)
  Step 1b: Intent classifier    — embedding-based (not yet built)
  Step 2:  Validate             — deterministic checks (not yet built)
  Step 3:  Route                — intent -> lane; lane + question -> topic_section
  Step 4:  Retrieve             — directed OR probabilistic
  Step 5:  Render               — deterministic (directed) OR LLM (probabilistic)

v6 remains the live pipeline. v7 is built piece by piece and only
wired to traffic after each step is verified.
"""
