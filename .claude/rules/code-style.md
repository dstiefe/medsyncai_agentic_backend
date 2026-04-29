# Code Style

## General
- Prefer clarity over cleverness — readable code is more important than compact code
- Functions should do one thing
- No commented-out code in commits
- No TODO comments in commits — open a ticket instead
- Don't add features, refactor, or make improvements beyond what was asked

## The Three-Layer Rule

### SKILL.md — Process Only
Contains: agent role, step-by-step reasoning, pointers to reference files, output format, worked examples.
Does NOT contain: thresholds, criteria, field definitions, valid values, schemas, or domain knowledge.

### references/ — Domain Knowledge Only
Contains: criteria and rules, field ontologies, output schemas, taxonomies, glossaries, JSON lookup tables.
Does NOT contain: reasoning instructions, process steps, or code.

### scripts/ — Deterministic Code Only
Contains: threshold matching, schema validation, score calculation, data parsing.
Does NOT contain: LM calls or probabilistic logic.

**Test for references/ vs SKILL.md:** If a clinical guideline or policy changes, does this content change? Yes → references/. It's about how to reason → SKILL.md.

**Test for scripts/ vs LM:** Can this be unit tested with a guaranteed correct output? Yes → Python script. Requires language understanding → LM.

## Probabilistic vs Deterministic

**Use Python (scripts/) for:**
- Threshold comparisons (value vs number)
- Boolean logic
- Schema validation
- Score calculation
- Anything that must be auditable and provably correct

**Use the LM for:**
- Extracting structured data from unstructured text
- Parsing ambiguous language
- Judgment calls that cannot be reduced to logic
- Synthesizing findings into narrative

**Never ask an LM to compare a number to a threshold.**

## Naming
- Variables and functions: descriptive names that explain intent
- Booleans: prefix with `is_`, `has_`, `should_`, `can_`
- Constants: `UPPER_SNAKE_CASE`
- Engine classes: `PascalCase` ending in `Engine` (e.g. `ClinicalSupportEngine`)
- Agent classes: `PascalCase` ending in `Agent`

## Imports
- Group imports: stdlib → external libraries → internal app modules → local files
- No unused imports

## Comments
- Comment the *why*, not the *what*
- Complex clinical logic needs an explanation comment above it

## Engine Inheritance
Every engine must follow:
```
BaseAgent → BaseEngine → YourNewEngine
```
