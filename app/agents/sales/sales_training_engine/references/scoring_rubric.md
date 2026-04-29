---
title: Scoring Rubrics
description: >
  LLM-based evaluation prompts for assessing sales representative performance across
  four behavioral dimensions: Competitive Knowledge, Objection Handling, Procedural
  Workflow, and Closing Effectiveness. Each rubric defines scoring criteria (0-100),
  evaluation questions, and expected JSON output format.
---

## 1. Competitive Knowledge Rubric

### Scoring Criteria (0-100)

**90-100 EXPERT:**
- Demonstrates deep knowledge of competitor products, specifications, and capabilities
- Can articulate competitor strengths AND weaknesses accurately
- Provides specific product comparisons with actual data (trial names, outcomes)
- Understands competitive positioning and market dynamics
- Identifies legitimate competitive advantages vs. marketing claims
- Positions own company credibly relative to competitors

**75-89 STRONG:**
- Good knowledge of major competitor products and key differentiators
- Can compare own products to competitors with specific examples
- Understands competitive landscape reasonably well
- Mostly accurate information with minor gaps
- Positions own company competitively with supporting evidence
- Handles competitive questions confidently

**60-74 ADEQUATE:**
- Basic knowledge of competitor products
- Can identify some key differences between products
- Mostly accurate but may lack specific details or trial data
- Competitive positioning exists but could be stronger
- Minor inaccuracies or gaps in knowledge
- Somewhat defensive when asked about competitors

**40-59 NEEDS IMPROVEMENT:**
- Limited knowledge of competitor products
- Struggles to articulate specific competitive differences
- May provide inaccurate or outdated information
- Weak competitive positioning or missing comparisons
- Defensive or dismissive when asked about competitors
- Lacks specific trial data or outcome information

**0-39 INADEQUATE:**
- Minimal knowledge of competitor products
- Cannot articulate competitive differences
- Provides inaccurate information about competitors
- Makes unfounded or exaggerated claims about own product
- Cannot position competitively
- Avoids or deflects competitive questions

### Evaluation Questions
1. What specific competitor products does the rep mention? Are the details accurate?
2. Does the rep cite actual trial data or make vague claims?
3. How does the rep position their own product relative to competitors?
4. Are the competitive claims fair and evidence-based, or overstated?
5. Does the rep demonstrate understanding of the competitive landscape?
6. What competitor strengths or weaknesses does the rep identify?
7. Would a physician find this competitive positioning credible and persuasive?
8. Are there competitor advantages the rep should acknowledge but didn't?

### Expected JSON Output
```json
{
    "score": 0-100,
    "category": "competitive_knowledge",
    "feedback": "2-3 sentence summary",
    "strengths": ["..."],
    "missed_opportunities": ["..."],
    "specific_gaps": ["..."],
    "credibility_assessment": "...",
    "recommendations": "..."
}
```

---

## 2. Objection Handling Rubric

### Scoring Criteria (0-100)

**90-100 EXCELLENT:**
- Directly addresses the core concern without deflection
- Provides specific, evidence-based counterargument (trial data, outcomes, etc.)
- Acknowledges legitimate aspects of the objection
- Honest about limitations or tradeoffs
- Response is persuasive without high-pressure tactics
- Moves conversation constructively forward
- Physician would consider this a strong answer

**75-89 GOOD:**
- Addresses core concern with minor deflection
- Provides evidence to support response (though may lack some specifics)
- Mostly honest and balanced
- Response is persuasive
- Conversational tone, no pressure tactics
- Advances the discussion constructively

**60-74 ADEQUATE:**
- Addresses core concern but with some deflection
- Provides some evidence but may be incomplete or dated
- Acknowledges some limitations
- Response is somewhat persuasive
- Tone is professional but may feel defensive
- Moves conversation forward but with less impact

**40-59 WEAK:**
- Only partially addresses core concern
- Significant deflection or avoidance
- Limited evidence provided
- Acknowledges few limitations
- May use pressure tactics or urgency language
- Response less persuasive, physician still skeptical
- Doesn't advance discussion meaningfully

**0-39 POOR:**
- Fails to address core concern
- Major deflection or complete avoidance
- No supporting evidence
- Dismissive of legitimate concern
- Pressure tactics, urgency language, or hostility
- Response unpersuasive, would strengthen physician's objection
- Damages credibility and relationship

### Detailed Evaluation Dimensions
1. DIRECT ADDRESS: Does rep answer the actual concern?
2. EVIDENCE BASIS: Is the response supported by data?
3. HONESTY & BALANCE: Does rep acknowledge tradeoffs?
4. PERSUASIVENESS: Would this convince a physician?
5. TONE & PROFESSIONALISM: Is the response professional?
6. CONVERSATION ADVANCEMENT: Does this move toward next steps?

### Expected JSON Output
```json
{
    "score": 0-100,
    "category": "objection_handling",
    "feedback": "2-3 sentence summary",
    "addressed_core_concern": true/false,
    "evidence_provided": true/false,
    "deflection_detected": true/false,
    "high_pressure_tactics": true/false,
    "acknowledged_limitations": true/false,
    "strengths": ["..."],
    "weaknesses": ["..."],
    "critical_gaps": ["..."],
    "persuasiveness": "...",
    "recommendations": "..."
}
```

---

## 3. Procedural Workflow Rubric

### Background
Neurointerventional thrombectomy involves a complex procedural workflow where devices must work
together in sequence: access guide catheter -> intermediate catheter -> distal access catheter ->
stent retriever/aspiration catheter. Each device must be compatible with the others (inner diameters,
outer diameters, materials, etc.).

### Scoring Criteria (0-100)

**90-100 EXPERT:**
- Demonstrates comprehensive understanding of full thrombectomy workflow
- Can explain device sequences and compatibility requirements
- Knows specific sizing/nesting parameters (diameters, lengths, material interactions)
- Understands alternative approaches and when to use each
- Can troubleshoot procedural issues
- Explains decision points in the workflow naturally
- Would help a physician optimize their technique

**75-89 STRONG:**
- Good understanding of standard workflow and device compatibility
- Knows most sizing/nesting requirements accurately
- Can explain alternative approaches
- Mostly accurate with minor gaps
- Answers workflow questions confidently
- Would provide useful guidance to physician

**60-74 ADEQUATE:**
- Basic understanding of workflow and compatibility
- Knows some sizing/nesting requirements
- Explains workflow with minor inaccuracies
- Some gaps in technical knowledge
- Can answer straightforward questions
- May struggle with complex scenarios

**40-59 NEEDS IMPROVEMENT:**
- Limited workflow understanding
- Gaps in compatibility knowledge
- Technical inaccuracies in sizing/nesting
- Struggles to explain procedural sequences
- Can answer only basic questions
- Would not provide reliable guidance

**0-39 INADEQUATE:**
- Minimal workflow understanding
- Significant technical inaccuracies
- Cannot explain device sequences
- Cannot discuss compatibility
- Cannot answer procedural questions
- Would mislead a physician

### Detailed Evaluation Dimensions
1. WORKFLOW UNDERSTANDING: Can they explain the sequence of devices used?
2. DEVICE COMPATIBILITY: Can they discuss inner/outer diameter compatibility?
3. TECHNICAL ACCURACY: Are the specific details correct?
4. PROCEDURAL DECISION-MAKING: Can they explain when to use different techniques?
5. SYSTEM INTEGRATION: How their products work together?

### Technical Knowledge Expected
- Guide catheter access (size, positioning)
- Intermediate catheter (typical sizes: 6-8Fr, outer diameter constraints)
- Distal access catheter (typical OD: 0.070-0.088")
- Stent retriever/aspiration catheter sizing and compatibility
- How each device nests inside the previous
- Device material and interaction considerations
- When and why to choose different approaches

### Expected JSON Output
```json
{
    "score": 0-100,
    "category": "procedural_workflow",
    "feedback": "2-3 sentence summary",
    "workflow_understanding": true/false,
    "technical_accuracy": true/false,
    "device_compatibility_knowledge": true/false,
    "alternative_approach_understanding": true/false,
    "strengths": ["..."],
    "technical_gaps": ["..."],
    "workflow_gaps": ["..."],
    "critical_missing_knowledge": ["..."],
    "teaching_value": "...",
    "recommendations": "..."
}
```

---

## 4. Closing Effectiveness Rubric

### Background
In medical device sales, the close is about moving to a next step, not a hard close.
Appropriate next steps include:
- Trial/evaluation of product with small case volume
- Case observation (physician watches skilled operator use device)
- Formal product demonstration
- Information/data review followed by follow-up
- Team discussion with colleagues
- Pilot program with specific parameters
- NOT high-pressure immediate commitment

### Scoring Criteria (0-100)

**90-100 EXCELLENT:**
- Clear, specific next step proposed (not vague "I'll follow up")
- Appropriate to physician's expressed readiness
- Addresses stated concerns before proposing next step
- Specific timeline and commitment requested
- Maintains relationship even if physician hesitant
- Offers multiple pathways forward
- Shows confidence without pressure
- Physician would clearly understand what's being proposed

**75-89 GOOD:**
- Clear next step proposed
- Mostly appropriate to physician's readiness
- Mostly addresses concerns before closing
- Timeline mentioned
- Relationship maintained
- Professional tone throughout

**60-74 ADEQUATE:**
- Next step proposed but could be clearer
- May not fully address all concerns first
- Timeline vague or missing
- Somewhat appropriate to readiness level
- Maintains relationship but less skillfully
- Professional tone

**40-59 WEAK:**
- Vague next step or multiple unclear options
- Doesn't address physician objections adequately
- Poor read on physician's readiness
- Pressure tactics emerging
- No clear timeline
- Relationship somewhat strained

**0-39 POOR:**
- No clear next step or attempt to close
- Aggressive/high-pressure closing tactics
- Ignores physician's stated concerns
- Unclear what physician is being asked to do
- Damages relationship
- Misses signals about readiness

### Detailed Evaluation Dimensions
1. CLARITY OF NEXT STEP: Is it clear what's being asked?
2. APPROPRIATENESS OF CLOSE: Does it match physician's readiness?
3. CONCERN HANDLING: Were objections addressed first?
4. TIMELINE & COMMITMENT: Is follow-up specified?
5. RELATIONSHIP MAINTENANCE: Is relationship preserved?
6. CONFIDENCE WITHOUT PRESSURE: Does rep show confidence without being pushy?

### Appropriate Next Steps for Medical Devices
- Formal product demonstration (specific date/time proposed)
- Limited case trial (specific number of cases, timeline)
- Case observation (rep or skilled operator demonstrates)
- Data review (specific materials offered, follow-up date set)
- Physician discussion with team (gather internal input)
- Pilot program (structured evaluation with success metrics)
- NOT: Generic "I'll call you next week" or "Think about it"

### Expected JSON Output
```json
{
    "score": 0-100,
    "category": "closing_effectiveness",
    "feedback": "2-3 sentence summary",
    "clear_next_step": true/false,
    "momentum_building": true/false,
    "relationship_maintained": true/false,
    "appropriateness_to_readiness": "...",
    "objections_addressed": true/false,
    "pressure_tactics": true/false,
    "strengths": ["..."],
    "weaknesses": ["..."],
    "next_step_proposed": "...",
    "timeline_clarity": "...",
    "likelihood_of_follow_up": "...",
    "recommendations": "..."
}
```

---

## Scoring Thresholds

### Per-Category Pass/Fail
| Category | Passing Score |
|---|---|
| Competitive Knowledge | 70 |
| Objection Handling | 75 |
| Procedural Workflow | 65 |
| Closing Effectiveness | 70 |

### Overall Readiness
| Level | Average Score | Description |
|---|---|---|
| Ready for Independent Calls | 75+ | Can operate independently |
| Needs Mentoring | 60-74 | Can call with supervision/support |
| Requires Training | Below 60 | Needs structured development |
