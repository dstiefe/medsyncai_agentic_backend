# Clinical Engine Audit: Harness Resilience Findings

Audit of `app/agents/clinical/` against the orchestration design patterns
specified in `.notes/clinical-module-architecture-v2.md`.

Date: 2026-04-04

---

## 1. Multi-Agent Context Isolation

**Spec requirement:** Never use a single omnipotent agent. Implement role
separation with a Coordinator + narrowly-scoped sub-agents. Strip context
when spawning sub-agents — only pass exact system prompt, target data,
and required tools.

### Findings: PASS

The clinical module uses **two fully separate pipelines**, each with
dedicated sub-agents that receive only typed dataclass inputs:

**Scenario pipeline** (5 agents):
- `NLPService` — Claude tool_use call with constrained schema (parsing only)
- `Table8Agent` — 37 contraindication rules, pure Python
- `Table4Agent` — disabling deficit thresholds, pure Python
- `IVTRecsAgent` — recommendation firing, pure Python
- `ChecklistAgent` — 5-domain completeness check, pure Python
- `RuleEngine` — EVT eligibility (24 rules), pure Python
- `DecisionEngine` — final state synthesis, pure Python

**Q&A pipeline** (5 agents):
- `IntentAgent` — deterministic classification, no LLM
- `RecommendationAgent` — keyword + semantic search, no LLM
- `SupportiveTextAgent` — keyword search, no LLM
- `KnowledgeGapAgent` — section lookup, no LLM
- `AssemblyAgent` — 9-layer verification + assembly, no LLM

**Context stripping is enforced structurally.** Each agent receives a typed
contract (`ParsedVariables`, `IntentResult`, `RecommendationResult`, etc.)
— not raw conversation history. The Q&A pipeline uses `asyncio.gather()`
to run 3 retrieval agents in parallel, each receiving only `IntentResult`.

**One concern:** `NLPService.parse_scenario()` is the only LLM call in the
scenario pipeline. If it fails, the pipeline returns empty `ParsedVariables`
with no fallback. This is correct (fail-safe > hallucinate), but there is
no retry or degraded-mode path.

### Checklist

- [x] Are we currently feeding the entire user conversation into every LLM call?
  **No.** LLM calls receive only the specific text to parse or format, not
  session history. The Clinical Output Agent gets structured decision state,
  not raw conversation.

- [x] Do we have a physically separate system prompt/LLM call for verifying
  an action versus generating the action?
  **Yes.** Generation (NLPService parsing) and verification (Table8/4, RuleEngine,
  AssemblyAgent scope gates) are in completely separate code paths. The
  AssemblyAgent runs 6 verification layers before assembling any response.

---

## 2. Hardcoded Sandboxing & Write Discipline

**Spec requirement:** Restrict agents from modifying critical systems.
Verification must happen in read-only state. AI internal state updated
only after tool confirms successful execution.

### Findings: PASS

**All agents are pure functions with no side effects:**
- `Table8Agent`, `Table4Agent`, `IVTRecsAgent`, `ChecklistAgent` — return
  dataclass results, never write to any store
- `RuleEngine`, `DecisionEngine` — deterministic computation, no I/O
- `IntentAgent`, `RecommendationAgent`, `SupportiveTextAgent`,
  `KnowledgeGapAgent`, `AssemblyAgent` — read-only queries against
  in-memory data structures

**Only the REST layer (`routes.py`) performs writes:**
- `_save_clinical_context()` persists to Firebase after full pipeline completes
- Session state is saved AFTER all agents return, not during processing
- Re-evaluate endpoint applies overrides WITHOUT re-running the full pipeline

**Ephemeral scratchpads exist implicitly:**
- `AssemblyAgent.audit_trail` — in-memory list, cleared per request
- Scored recommendation lists — in-memory, discarded after response
- No persistent agent-level state between requests

### Checklist

- [x] Can our reasoning/verification agents physically access write-enabled tools?
  **No.** All agents are Python classes with no database clients, no API
  write methods, no file handles. Only `routes.py` has Firebase access.

- [x] Do we have an isolated scratchpad for the AI to process data before
  committing it?
  **Yes (implicit).** All intermediate results exist only as in-memory
  dataclass instances during request processing. Nothing is committed
  until the full pipeline returns successfully.

- [x] Are tool executions validated by the backend before the AI context
  is updated with a "success" message?
  **Yes.** Firebase persistence happens in `routes.py` after the entire
  pipeline returns. The LLM never receives a "saved" confirmation —
  it is not involved in the write path at all.

---

## 3. Procedural Playbooks (Domain-Specific Workflows)

**Spec requirement:** Do not rely on the LLM to invent a verification or
execution strategy. The harness must dictate the exact sequence based on
data type, using hardcoded workflows injected into prompts.

### Findings: STRONG PASS

This is the clinical module's strongest area. The entire evaluation logic
is encoded in deterministic Python, not LLM prompts.

**Scenario pipeline playbook (hardcoded in Python):**
```
1. Parse text → ParsedVariables     (LLM, constrained by tool schema)
2. Table 8 → contraindication tier  (Python: 37 rules, 3 tiers)
3. Table 4 → disabling assessment   (Python: NIHSS thresholds)
4. IVT Recs → fired recommendations (Python: 5 pathways A-E)
5. Checklist → completeness check   (Python: 5 domains, 25 items)
6. EVT Rules → eligibility          (Python: 24 condition-action rules)
7. Decision → final state           (Python: 40+ headline permutations)
```

**Q&A pipeline playbook (hardcoded in Python):**
```
1. Intent → classify question        (Python: regex + keyword + concept index)
2. [parallel] Search 3 sources       (Python: scoring + embeddings + keyword)
3. Assembly → 9-layer verification   (Python: scope gates, clarification, thresholds)
4. Format → verbatim response        (Python: template assembly)
```

**Clinical Output Agent playbook (injected into LLM prompt):**
- `SKILL.md` defines exact reasoning steps
- `references/clinical_rules.md` provides citation rules
- `references/routine_format.md` and `edge_case_format.md` define
  output templates based on case complexity
- Safety rules are hardcoded in SKILL.md lines 229-237

**The LLM is never asked to decide WHAT to verify or HOW to evaluate.**
It receives pre-computed structured data and formats it into prose.

### Checklist

- [x] Are we relying on the LLM's internal knowledge to know how to test
  or verify a specific type of data?
  **No.** All verification is deterministic Python. The LLM's only roles
  are (1) parsing unstructured text into structured fields, and (2)
  formatting structured results into clinical prose.

- [x] Do we have hardcoded string templates/playbooks that get injected
  into the prompt based on the task classification?
  **Yes.** The Clinical Output Agent receives different reference files
  (`routine_format.md` vs `edge_case_format.md`) based on case complexity.
  The Q&A Assembly Agent uses hardcoded templates for recommendation
  formatting (never LLM-generated).

---

## 4. Self-Healing Memory Architecture

**Spec requirement:** Prevent context entropy by structuring memory
hierarchically. Use a lightweight index in context (Layer 1) with
on-demand retrieval for payloads (Layer 2). Automated truncation of
old context.

### Findings: PARTIAL PASS

**What exists:**

- **On-demand retrieval:** The `EmbeddingStore` loads pre-computed
  embeddings lazily on first use (`embedding_store.py:57-88`). The
  `SectionConceptIndex` is built at startup and queried on demand.
  Data files (`recommendations.json`, `guideline_knowledge.json`)
  are loaded via `@lru_cache` — read once, cached in memory.

- **Session context:** Firebase stores full clinical context between
  requests. The re-evaluate endpoint loads only what it needs from
  the stored state (overrides + prior results), not the full session.

- **Typed contracts as implicit indexing:** Each agent receives only
  the typed result it needs (`IntentResult`, `RecommendationResult`),
  which functions like an index — pointers to relevant data rather
  than raw content dumps.

**What is missing:**

- **No explicit Layer 1/Layer 2 separation for session memory.**
  The session state in Firebase stores the full `ClinicalDecisionState`
  (123 fields) as a flat JSON blob. There is no lightweight index
  that points to heavier payloads — it's all loaded at once during
  re-evaluation.

- **No automated context summarization or truncation.** If a user
  runs many scenarios in one session, all prior states accumulate.
  There is no background job to compress old session context.

- **No explicit TTL or cleanup for Firebase sessions.** Stale
  sessions are never pruned.

### Checklist

- [ ] Does our app crash or hallucinate when a user session gets too long?
  **Unlikely** — each request is independent (no accumulated context passed
  to LLM). But Firebase session size could grow unbounded.

- [x] Are we forcing the LLM to re-read the entire session history on
  every single turn?
  **No.** Each request gets only structured data, not conversation history.

- [ ] Do we have an automated background job that summarizes and truncates
  old context?
  **No.** This is a gap. Firebase sessions have no TTL or compression.

---

## 5. Anti-Laziness Guardrails

**Spec requirement:** Counteract LLM verification avoidance. System
prompt must aggressively enforce checking. Orchestration layer should
reject responses that skip required analytical tools.

### Findings: STRONG PASS (with one gap)

**Hard constraints that prevent skipping:**

1. **6-step verification in AssemblyAgent is mandatory and sequential.**
   The code structure forces every response through all 6 gates:
   - Topic coverage scope gate (line ~432)
   - Hardcoded clarification rules (line ~454)
   - Content breadth analysis (line ~474)
   - Generic ambiguity detection (line ~515)
   - Section ambiguity detection (line ~540)
   - Score threshold scope gate (line ~560)
   There are **no early exits** except explicit failure conditions.

2. **Immutable threshold constants** prevent drift:
   ```python
   SCOPE_GATE_MIN_SCORE = 3
   REC_INCLUSION_MIN_SCORE = 1
   MAX_RECS_IN_RESPONSE = 5
   ```

3. **Forced clarification rules** are hardcoded for known clinical
   ambiguities (M2 dominance, IVT disabling status). These cannot
   be bypassed — they fire deterministically based on keyword presence.

4. **Verbatim recommendation assembly** — the Assembly Agent copies
   guideline text character-for-character. The LLM never paraphrases
   or summarizes recommendations.

5. **`validate_summary()`** post-checks for invented numbers,
   percentages, clinical thresholds, and time durations in any
   LLM-generated summary text.

6. **Clinical Output Agent safety rules** (SKILL.md lines 229-237)
   explicitly list dangerous patterns:
   - "NEVER recommend delaying IVT for CTA, CTP, or advanced imaging"
   - "CTP is NOT required in the standard window"
   - Trial name stripping for routine cases (prevents citation confusion)

**The gap:**

- **NLPService (parsing) has no adversarial verification.** When
  Claude parses patient text into `ParsedVariables`, there is no
  second-pass check that the extracted values match the input text.
  For example, if Claude extracts `nihss=18` from "NIHSS 8", nothing
  catches this. The downstream pipeline trusts the parsed values
  completely.

  **Mitigation:** The tool_use schema constrains output shape and
  field types, but does not validate semantic accuracy. A deterministic
  regex cross-check on critical fields (NIHSS, ASPECTS, age, LKW)
  would close this gap.

### Checklist

- [x] Have we noticed the AI saying "Looks good to me" without actually
  calling the verification tools?
  **Not applicable.** Verification is deterministic Python — the LLM is
  never asked to verify. All scope gates, clarification detection, and
  threshold checks run as mandatory Python code.

- [x] Is our verification prompt designed to encourage the AI to act as
  an adversarial "red team" against the proposed action?
  **Partially.** The Clinical Output Agent's SKILL.md includes explicit
  safety rules. But the NLPService parser has no adversarial self-check.

---

## Summary

| Category | Verdict | Key Evidence |
|----------|---------|-------------|
| **1. Multi-Agent Context Isolation** | PASS | 10+ agents, typed contracts, no shared state |
| **2. Hardcoded Sandboxing** | PASS | All agents are pure functions; only REST layer writes |
| **3. Procedural Playbooks** | STRONG PASS | 37 contraindication rules, 24 EVT rules, 9-layer assembly — all deterministic Python |
| **4. Self-Healing Memory** | PARTIAL PASS | On-demand loading and typed contracts, but no session TTL or context compression |
| **5. Anti-Laziness Guardrails** | STRONG PASS | 6 mandatory verification gates, immutable thresholds, verbatim assembly, validate_summary() |

### Recommended Actions

1. **NLP parsing verification (Priority: HIGH)** — Add a deterministic
   regex cross-check on `ParsedVariables` critical fields (NIHSS, ASPECTS,
   age, LKW, vessel) against the raw input text. This closes the only
   gap where LLM output is trusted without validation.

2. **Firebase session TTL (Priority: MEDIUM)** — Add a TTL or cleanup
   policy for clinical session data. Current implementation allows
   unbounded growth.

3. **Session index layer (Priority: LOW)** — For multi-scenario sessions,
   consider a lightweight index of prior evaluations rather than storing
   full `ClinicalDecisionState` blobs. Current single-scenario usage
   makes this low priority.
