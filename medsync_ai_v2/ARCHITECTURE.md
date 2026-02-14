# MedSync AI v2 — System Architecture

## High-Level Pipeline

```mermaid
flowchart TD
    USER([User Query]) --> MAIN[main.py / FastAPI + SSE]
    MAIN --> ORCH[Orchestrator Pipeline]

    subgraph ORCH_PIPELINE["Orchestrator Pipeline"]
        direction TB
        S1["Step 1: InputRewriter<br/><i>LLM &bull; Sonnet</i>"]
        S1b{"Clinical<br/>follow-up?"}
        S1d{"Guideline<br/>follow-up?"}
        S2["Steps 2+3 &lpar;PARALLEL&rpar;"]
        IC["IntentClassifier<br/><i>LLM &bull; Sonnet</i>"]
        EE["EquipmentExtraction<br/><i>LLM &bull; Haiku + Whoosh</i>"]
        GENERAL_CHECK{"intent =<br/>general?"}
        VALIDATE{"Unresolved<br/>devices?"}
        GENERIC_CHECK{"generic_specs +<br/>COMPAT_INTENT?"}
        HYBRID_CHECK{"clinical_hybrid<br/>detected?"}
        ROUTE{"Route by<br/>Intent"}

        S1 --> S1b
        S1b -->|yes| MERGE_CLINICAL["Merge Turn 1 + Turn 2"]
        S1b -->|no| S1d
        MERGE_CLINICAL --> S2
        S1d -->|yes| ENRICH["Enrich with clinical context"]
        S1d -->|no| S2
        ENRICH --> S2
        S2 --> IC & EE
        IC & EE --> GENERAL_CHECK
        GENERAL_CHECK -->|yes| GENERAL_PATH
        GENERAL_CHECK -->|no| VALIDATE
        VALIDATE -->|"relational intent<br/>+ not_found"| CLARIFY_PATH
        VALIDATE -->|ok| GENERIC_CHECK
        GENERIC_CHECK -->|yes| GENERIC_PIPELINE
        GENERIC_CHECK -->|no| HYBRID_CHECK
        GENERIC_PIPELINE --> HYBRID_CHECK
        HYBRID_CHECK -->|no| ROUTE
        HYBRID_CHECK -->|yes| PLANNED_HYBRID
    end

    ROUTE -->|chain| CHAIN_PATH
    ROUTE -->|database| DB_PATH
    ROUTE -->|vector| VEC_PATH
    ROUTE -->|clinical| CLINICAL_PATH
    ROUTE -->|planned| PLANNED_PATH
    ROUTE -->|research| RESEARCH_STUB
    ROUTE -->|general| GENERAL_PATH

    CHAIN_PATH --> SSE_OUT
    DB_PATH --> SSE_OUT
    VEC_PATH --> SSE_OUT
    CLINICAL_PATH --> SSE_OUT
    PLANNED_PATH --> SSE_OUT
    PLANNED_HYBRID --> SSE_OUT
    GENERAL_PATH --> SSE_OUT
    CLARIFY_PATH --> SSE_OUT
    RESEARCH_STUB --> SSE_OUT

    SSE_OUT([SSE Stream to Client])
```

## Intent Classification & Routing

```mermaid
flowchart LR
    subgraph INTENTS["13 Intent Types"]
        direction TB
        I1[equipment_compatibility]
        I2[device_discovery]
        I3[filtered_discovery]
        I4[specification_lookup]
        I5[spec_reasoning]
        I6[device_search]
        I7[device_comparison]
        I8[documentation]
        I9[knowledge_base]
        I10[device_definition]
        I11[manufacturer_lookup]
        I12[clinical_support]
        I13[deep_research]
        I14[general]
    end

    subgraph ENGINES["Engine Paths"]
        direction TB
        CHAIN["Chain Engine"]
        DATABASE["Database Engine"]
        VECTOR["Vector Engine"]
        CLINICAL["Clinical Engine"]
        PLANNED["Planned Path<br/><i>multi-engine</i>"]
        RESEARCH["Research Stub"]
        GENERAL["General Output"]
    end

    I1 & I2 --> CHAIN
    I4 & I5 & I6 & I7 & I11 --> DATABASE
    I8 & I9 & I10 --> VECTOR
    I12 --> CLINICAL
    I3 --> PLANNED
    I13 --> RESEARCH
    I14 --> GENERAL

    style PLANNED fill:#f9f,stroke:#333
    style CHAIN fill:#bbf,stroke:#333
    style DATABASE fill:#bfb,stroke:#333
    style VECTOR fill:#fbf,stroke:#333
    style CLINICAL fill:#fbb,stroke:#333
```

## Chain Engine (Compatibility)

```mermaid
flowchart TD
    subgraph CHAIN_ENGINE["Chain Engine"]
        direction TB
        RESOLVE["_resolve_input&lpar;&rpar;<br/><i>Python &bull; transforms prior_results</i>"]
        MAP["map_device_categories&lpar;&rpar;<br/><i>Python</i>"]
        PAR_LLM["PARALLEL LLM Calls"]
        QC["QueryClassifier<br/><i>LLM &bull; Haiku</i>"]
        CB["ChainBuilder<br/><i>LLM &bull; Haiku</i>"]
        PAIRS["ChainPairGenerator<br/><i>Python &bull; OD/ID math</i>"]
        ANALYZE["ChainAnalyzerMulti<br/><i>Python &bull; rollup</i>"]
        DECIDE["decide_next_action&lpar;&rpar;<br/><i>Python</i>"]
        SUBSET["run_n1_subsets&lpar;&rpar;<br/><i>Python &bull; if needed</i>"]
        TEXT["ChainTextBuilder<br/><i>Python &bull; narrative</i>"]
        FLAT["ChainFlattenerMulti<br/><i>Python &bull; flat records</i>"]
        QUALITY["check_quality&lpar;&rpar;<br/><i>Python</i>"]

        RESOLVE --> MAP --> PAR_LLM
        PAR_LLM --> QC & CB
        QC & CB --> PAIRS
        PAIRS --> ANALYZE --> DECIDE
        DECIDE -->|needs subsets| SUBSET --> TEXT
        DECIDE -->|done| TEXT
        TEXT --> FLAT --> QUALITY
    end

    QUALITY --> CHAIN_OUT["ChainOutputAgent<br/><i>LLM &bull; Sonnet &bull; stream</i>"]

    style QC fill:#ffe0b2
    style CB fill:#ffe0b2
    style CHAIN_OUT fill:#bbdefb
```

## Database Engine (Specs, Search, Comparison)

```mermaid
flowchart TD
    subgraph DB_ENGINE["Database Engine"]
        direction TB
        DB_SWITCH{"input_type?"}

        subgraph DEFAULT_PATH["Default Path"]
            QSA["QuerySpecAgent<br/><i>LLM &bull; Haiku</i>"]
        end

        subgraph FILTER_PATH["Filter Path<br/><i>from planner</i>"]
            PRE_BUILT["Pre-built query_spec<br/><i>no LLM</i>"]
        end

        QE["QueryExecutor<br/><i>Python &bull; executes against DATABASE</i>"]

        DB_SWITCH -->|"query_spec"| QSA
        DB_SWITCH -->|"filter"| PRE_BUILT
        QSA --> QE
        PRE_BUILT --> QE
    end

    QE --> DB_OUT["DatabaseOutputAgent<br/><i>LLM &bull; Sonnet &bull; stream</i>"]

    style QSA fill:#ffe0b2
    style DB_OUT fill:#bbdefb
```

## Vector Engine (IFU / 510k Documents)

```mermaid
flowchart TD
    subgraph VEC_ENGINE["Vector Engine"]
        direction TB
        META["Build metadata filter<br/><i>Python &bull; device_variant_ids</i>"]
        SEARCH["VectorStoreClient<br/><i>Python REST &bull; OpenAI API</i>"]
        SCORE["Score filtering<br/><i>Python &bull; MIN_SCORE=0.4, top 10</i>"]

        META --> SEARCH --> SCORE
    end

    SCORE --> VEC_OUT["VectorOutputAgent<br/><i>LLM &bull; Sonnet &bull; stream</i><br/>anti-hallucination prompt"]

    style VEC_OUT fill:#bbdefb
```

## Clinical Support Engine (AIS Eligibility)

```mermaid
flowchart TD
    subgraph CLIN_ENGINE["Clinical Support Engine"]
        direction TB
        PARSE["PatientParser.parse&lpar;&rpar;<br/><i>Python regex</i>"]
        COMPLETE["assess_completeness&lpar;&rpar;<br/><i>Python</i>"]
        COMPLETE_CHECK{"assessable?"}
        ELIG["EligibilityRules.evaluate_all&lpar;&rpar;<br/><i>Python &bull; IVT/EVT/BP rules</i>"]
        TRIALS["TrialMetricsLookup<br/><i>Python &bull; JSON file</i>"]
        SUFFICIENCY["_evaluate_sufficiency&lpar;&rpar;<br/><i>Python &bull; edge case check</i>"]
        VSEARCH["_search_guidelines&lpar;&rpar;<br/><i>Python REST &bull; Vector Store</i>"]
        CONTEXT_REVIEW["ContextReview<br/><i>LLM &bull; Haiku &bull; only if UNCERTAIN</i>"]
        GAP_FILL["Gap-fill vector search<br/><i>Python REST</i>"]

        PARSE --> COMPLETE --> COMPLETE_CHECK
        COMPLETE_CHECK -->|no| CLARIFY["Return needs_clarification<br/><i>deterministic questions</i>"]
        COMPLETE_CHECK -->|yes| ELIG --> TRIALS --> SUFFICIENCY
        SUFFICIENCY -->|needs vector| VSEARCH --> CONTEXT_REVIEW
        SUFFICIENCY -->|sufficient| CONTEXT_REVIEW
        CONTEXT_REVIEW -->|gaps found| GAP_FILL --> DONE["Return eligibility data"]
        CONTEXT_REVIEW -->|complete| DONE
    end

    CLARIFY --> CLARIFY_OUT["Deterministic text<br/><i>no LLM &bull; direct SSE</i>"]
    DONE --> CLIN_OUT["ClinicalOutputAgent<br/><i>LLM &bull; Sonnet &bull; stream</i>"]

    style CONTEXT_REVIEW fill:#ffe0b2
    style CLIN_OUT fill:#bbdefb
    style CLARIFY_OUT fill:#c8e6c9
```

## Planned Path (Multi-Engine Orchestration)

```mermaid
flowchart TD
    subgraph PLANNED["Planned Path"]
        direction TB
        PLANNER["QueryPlanner<br/><i>LLM &bull; Haiku</i>"]
        PLAN_OUT["Execution Plan<br/><i>strategy + steps + depends_on</i>"]

        PLANNER --> PLAN_OUT

        subgraph WAVES["Wave-Based Parallel Execution"]
            direction LR
            WAVE1["Wave 1<br/><i>independent steps</i>"]
            WAVE2["Wave 2<br/><i>depends on Wave 1</i>"]
            WAVE1 -->|"asyncio.gather"| WAVE2
        end

        PLAN_OUT --> WAVES

        subgraph STEP_TYPES["Step Types"]
            S_DB["database step<br/><i>filter path, no LLM</i>"]
            S_CHAIN["chain step<br/><i>2 LLM + Python math</i>"]
            S_VEC["vector step<br/><i>REST search, no LLM</i>"]
        end
    end

    WAVES --> OUTPUT_DISPATCH{"output_agent<br/>from plan?"}
    OUTPUT_DISPATCH -->|chain_output_agent| CO["ChainOutputAgent<br/><i>LLM stream</i>"]
    OUTPUT_DISPATCH -->|vector_output_agent| VO["VectorOutputAgent<br/><i>LLM stream</i>"]
    OUTPUT_DISPATCH -->|synthesis_output_agent| SO["SynthesisOutputAgent<br/><i>LLM stream</i>"]
    OUTPUT_DISPATCH -->|database_output_agent| DO["DatabaseOutputAgent<br/><i>LLM stream</i>"]

    style PLANNER fill:#ffe0b2
    style SO fill:#e1bee7
```

## Hybrid Device + Clinical Path

```mermaid
flowchart TD
    subgraph HYBRID["Hybrid Path &lpar;device + clinical in one query&rpar;"]
        direction TB

        DETECT["Detect: has_clinical + has_device"]

        subgraph PARALLEL_EXEC["PARALLEL Execution"]
            direction LR
            CLIN_ENG["ClinicalSupportEngine<br/><i>eligibility assessment</i>"]
            PLAN_ENG["QueryPlanner<br/><i>device plan</i>"]
        end

        DETECT --> PARALLEL_EXEC

        PLAN_STEPS["Execute device plan steps<br/><i>wave-based parallel</i>"]
        INJECT["Inject clinical_result<br/>into step_results"]

        CLIN_CHECK{"clinical status?"}
        COMPLETE_RESULT["Full eligibility data"]
        NEEDS_CLAR["Pre-format clarification<br/><i>_format_clinical_clarification&lpar;&rpar;</i><br/>Store pending context"]

        PARALLEL_EXEC --> PLAN_STEPS
        PARALLEL_EXEC --> CLIN_CHECK
        PLAN_STEPS --> INJECT
        CLIN_CHECK -->|complete| COMPLETE_RESULT --> INJECT
        CLIN_CHECK -->|needs_clarification| NEEDS_CLAR --> INJECT

        INJECT --> SYNTH["SynthesisOutputAgent<br/><i>LLM stream &bull; combines both</i>"]
    end

    style DETECT fill:#fff9c4
    style SYNTH fill:#e1bee7
```

## Generic Device Pipeline

```mermaid
flowchart TD
    subgraph GENERIC["Generic Pipeline &lpar;COMPAT_INTENTS only&rpar;"]
        direction TB
        GDS["GenericDeviceStructuring<br/><i>LLM &bull; Haiku &bull; merge fragments</i>"]
        GP["GenericPrep<br/><i>LLM &bull; Haiku &bull; map to DB fields</i>"]
        GPP["GenericPrepPython<br/><i>Python &bull; create synthetic records</i>"]
        REQ_DB["Request-scoped DB copy<br/><i>prevents cross-request contamination</i>"]

        GDS -->|structured devices| GP
        GP -->|sufficient devices| GPP
        GPP --> REQ_DB
    end

    REQ_DB -->|"synthetic devices +<br/>request_db"| ROUTING["Continue to intent routing"]

    style GDS fill:#ffe0b2
    style GP fill:#ffe0b2
    style GPP fill:#c8e6c9
```

## Output Agents

```mermaid
flowchart LR
    subgraph OUTPUT_AGENTS["Output Agents &lpar;all LLM streaming via broker&rpar;"]
        direction TB
        OA1["GeneralOutputAgent<br/><i>greetings, scope, off-topic</i>"]
        OA2["ChainOutputAgent<br/><i>compatibility results<br/>dynamic system msg per sub-type</i>"]
        OA3["DatabaseOutputAgent<br/><i>spec lookup, search, comparison<br/>dynamic system msg per count</i>"]
        OA4["VectorOutputAgent<br/><i>IFU/510k chunks<br/>anti-hallucination prompt</i>"]
        OA5["ClinicalOutputAgent<br/><i>eligibility assessment<br/>Class/Level notation</i>"]
        OA6["SynthesisOutputAgent<br/><i>multi-engine combination<br/>chain+vector, db+vector, device+clinical</i>"]
        OA7["ClarificationOutputAgent<br/><i>unresolved device names<br/>fuzzy suggestions</i>"]
    end

    OUTPUT_AGENTS -->|"call_stream&lpar;&rpar;"| BROKER["StreamingBroker"]
    BROKER -->|SSE| CLIENT([Client])
```

## Model Assignment

```mermaid
flowchart TD
    subgraph MODELS["LLM Model Tiers"]
        direction LR
        subgraph SONNET["Claude Sonnet 4.5 &lpar;default&rpar;"]
            direction TB
            M1[InputRewriter]
            M2[IntentClassifier]
            M3[All Output Agents]
        end
        subgraph HAIKU["Claude Haiku 4.5 &lpar;fast&rpar;"]
            direction TB
            M4[EquipmentExtraction]
            M5[QueryClassifier]
            M6[ChainBuilder]
            M7[QuerySpecAgent]
            M8[QueryPlanner]
            M9[GenericDeviceStructuring]
            M10[GenericPrep]
            M11[ClarificationOutputAgent]
            M12[ContextReview]
        end
    end

    style SONNET fill:#bbdefb
    style HAIKU fill:#ffe0b2
```

## Latency: LLM Round Trips

```mermaid
sequenceDiagram
    participant U as User
    participant R as InputRewriter
    participant IC as IntentClassifier
    participant EE as EquipmentExtraction
    participant E as Engine
    participant O as OutputAgent

    U->>R: raw query
    Note over R: Round 1 (Sonnet)
    R->>IC: normalized query
    R->>EE: normalized query
    Note over IC,EE: Round 2 (parallel: Sonnet + Haiku)
    IC-->>E: intent
    EE-->>E: devices
    Note over E: Round 3 (engine-specific, Haiku)
    E->>O: structured data
    Note over O: Round 4 (Sonnet, streaming)
    O-->>U: SSE tokens

    Note right of U: Best case: 3 rounds<br/>(general skips engine)
    Note right of U: Typical: 4 rounds<br/>(rewriter → [IC+EE] → engine → output)
    Note right of U: Planned: 5-6 rounds<br/>(+ planner + multi-engine steps)
```

## Data Flow Contracts

```mermaid
flowchart LR
    subgraph CONTRACTS["Standard Return Contract"]
        direction TB
        C1["status: ok | error | needs_clarification"]
        C2["engine: chain | database | vector | clinical"]
        C3["result_type: compatibility_check | spec_lookup | ..."]
        C4["data: engine-specific payload"]
        C5["classification: query metadata"]
        C6["confidence: 0.0 - 1.0"]
    end

    subgraph SSE_EVENTS["SSE Event Types"]
        direction TB
        E1["status &mdash; agent progress updates"]
        E2["final_chunk &mdash; streaming response tokens"]
        E3["chain_category_chunk &mdash; flat device records"]
        E4["query_result_device_chunk &mdash; DB device records"]
        E5["done &mdash; stream complete"]
    end
```

## External Dependencies

```mermaid
flowchart TD
    subgraph EXTERNAL["External Services"]
        direction LR
        ANTHROPIC["Anthropic API<br/><i>Claude Sonnet + Haiku</i>"]
        OPENAI["OpenAI API<br/><i>Vector Stores &lpar;embeddings&rpar;</i>"]
        FIREBASE["Firebase Firestore<br/><i>device database + users</i>"]
        WHOOSH["Whoosh Index<br/><i>local fuzzy device search</i>"]
    end

    subgraph APP["MedSync AI v2"]
        LLM_CLIENT["shared/llm_client.py<br/><i>dual-provider: call&lpar;&rpar; + call_json&lpar;&rpar; + call_stream&lpar;&rpar;</i>"]
        VEC_CLIENT["shared/vector_client.py<br/><i>sync REST, asyncio.to_thread&lpar;&rpar;</i>"]
        DEV_SEARCH["shared/device_search.py<br/><i>Firebase + Whoosh + extract_device_specs&lpar;&rpar;</i>"]
    end

    LLM_CLIENT --> ANTHROPIC
    VEC_CLIENT --> OPENAI
    DEV_SEARCH --> FIREBASE
    DEV_SEARCH --> WHOOSH
```
