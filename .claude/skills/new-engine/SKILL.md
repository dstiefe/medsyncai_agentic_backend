---
name: new-engine
description: Scaffold a new engine following project conventions. Use when creating a new engine, agent, or pipeline component.
---

# New Engine Scaffold

When given an engine name and purpose, create all required files following project conventions.

## Steps

1. Ask what the engine should do if not already explained
2. Confirm the engine name and which intent(s) it will handle
3. Create the engine folder structure:
   ```
   app/agents/<engine_name>/
   ├── SKILL.md                  ← process only
   ├── references/
   │   ├── field_ontology.md
   │   └── output_schema.md
   └── scripts/                  ← deterministic Python only
   ```
4. Create `<engine_name>.py` using the engine template from CLAUDE.md:
   - Extends `BaseEngine`
   - Has `name` and `SKILL_PATH`
   - Implements `async def run()` returning via `_build_return()`
5. Create `routes.py` with `require_auth` dependency, POST-only endpoints, uid/session_id on every model
6. Wire the engine in these 5 locations (check all, never skip):
   - `app/orchestrator/orchestrator.py` — import + `_get_tool_registry()`
   - `app/orchestrator/orchestrator.py` — `INTENT_ENGINE_MAP`
   - `app/orchestrator/intent_classifier.py` — new intent label
   - `app/output_agents/` — create output agent if needed
   - Engine `routes.py` — `require_auth` applied
7. Show summary of all files created/modified and ask for confirmation before writing logic

## Do Not
- Write business logic until structure is confirmed
- Put domain knowledge in SKILL.md (it goes in references/)
- Put LM calls in scripts/ (scripts/ is deterministic Python only)
- Ask an LM to compare a number to a threshold
- Leave any of the 5 wiring locations unupdated
- Skip the output_schema.md in references/
