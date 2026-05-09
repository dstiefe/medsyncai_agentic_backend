"""
Scoring Rubrics for MedSync AI Sales Simulation Engine

This module provides LLM-based evaluation prompts for assessing sales representative
performance across four behavioral dimensions:

1. Competitive Knowledge - Understanding competitor products, claims, and positioning
2. Objection Handling - Addressing physician concerns with evidence and persuasion
3. Procedural Workflow - Understanding device-system interactions and clinical workflow
4. Closing Effectiveness - Moving conversations toward meaningful next steps

Each rubric generates a prompt that asks the LLM to evaluate a response and return
structured scoring in JSON format.
"""

from typing import Dict, Any, Optional
import json


def get_competitive_knowledge_rubric(
    user_response: str,
    context: str = ""
) -> str:
    """
    Generate evaluation prompt for competitive knowledge assessment.

    Evaluates whether the rep demonstrates understanding of:
    - Competitor product specifications and capabilities
    - Competitor marketing claims and positioning
    - Competitor weaknesses and vulnerabilities
    - How their own products compare
    - Market dynamics and positioning

    Args:
        user_response: The rep's response about competitor products
        context: Additional context (what competitor was discussed, etc.)

    Returns:
        LLM prompt for scoring competitive knowledge

    Expected JSON output:
    {
        "score": 0-100,
        "category": "competitive_knowledge",
        "feedback": "...",
        "missed_opportunities": ["...", "..."],
        "strengths": ["...", "..."],
        "recommendations": "..."
    }
    """

    prompt = f"""You are an expert evaluator of medical device sales representative performance.

EVALUATION TASK: Competitive Knowledge Assessment

The sales representative made the following response when asked about competitors:

---
{user_response}
---

{f'CONTEXT: {context}' if context else ''}

SCORING CRITERIA (0-100 scale):

90-100 (EXPERT):
- Demonstrates deep knowledge of competitor products, specifications, and capabilities
- Can articulate competitor strengths AND weaknesses accurately
- Provides specific product comparisons with actual data (trial names, outcomes)
- Understands competitive positioning and market dynamics
- Identifies legitimate competitive advantages vs. marketing claims
- Positions own company credibly relative to competitors

75-89 (STRONG):
- Good knowledge of major competitor products and key differentiators
- Can compare own products to competitors with specific examples
- Understands competitive landscape reasonably well
- Mostly accurate information with minor gaps
- Positions own company competitively with supporting evidence
- Handles competitive questions confidently

60-74 (ADEQUATE):
- Basic knowledge of competitor products
- Can identify some key differences between products
- Mostly accurate but may lack specific details or trial data
- Competitive positioning exists but could be stronger
- Minor inaccuracies or gaps in knowledge
- Somewhat defensive when asked about competitors

40-59 (NEEDS IMPROVEMENT):
- Limited knowledge of competitor products
- Struggles to articulate specific competitive differences
- May provide inaccurate or outdated information
- Weak competitive positioning or missing comparisons
- Defensive or dismissive when asked about competitors
- Lacks specific trial data or outcome information

0-39 (INADEQUATE):
- Minimal knowledge of competitor products
- Cannot articulate competitive differences
- Provides inaccurate information about competitors
- Makes unfounded or exaggerated claims about own product
- Cannot position competitively
- Avoids or deflects competitive questions

EVALUATION QUESTIONS:
1. What specific competitor products does the rep mention? Are the details accurate?
2. Does the rep cite actual trial data or make vague claims?
3. How does the rep position their own product relative to competitors?
4. Are the competitive claims fair and evidence-based, or overstated?
5. Does the rep demonstrate understanding of the competitive landscape?
6. What competitor strengths or weaknesses does the rep identify?
7. Would a physician find this competitive positioning credible and persuasive?
8. Are there competitor advantages the rep should acknowledge but didn't?

Now provide your evaluation in this JSON format:

{{
    "score": <0-100>,
    "category": "competitive_knowledge",
    "feedback": "<2-3 sentence summary of overall competitive knowledge demonstrated>",
    "strengths": [
        "<Specific area of strong competitive knowledge>",
        "<Another strength>"
    ],
    "missed_opportunities": [
        "<Competitor advantage the rep didn't acknowledge>",
        "<Another missed opportunity to differentiate>"
    ],
    "specific_gaps": [
        "<Inaccuracy or lack of knowledge about competitor X>",
        "<Another knowledge gap>"
    ],
    "credibility_assessment": "<Does the competitive positioning sound credible to a physician? Why or why not?>",
    "recommendations": "<Specific guidance for improving competitive knowledge>"
}}

Provide ONLY the JSON output, no other text."""

    return prompt


def get_objection_handling_rubric(
    user_response: str,
    objection: str,
    context: str = ""
) -> str:
    """
    Generate evaluation prompt for objection handling assessment.

    Evaluates whether the rep:
    - Addressed the core concern directly
    - Used evidence and data to support their response
    - Acknowledged limitations or tradeoffs honestly
    - Avoided deflection or high-pressure tactics
    - Made the response persuasive

    Args:
        user_response: The rep's response to the objection
        objection: The objection statement the rep was addressing
        context: Additional context (physician type, current situation, etc.)

    Returns:
        LLM prompt for scoring objection handling

    Expected JSON output:
    {
        "score": 0-100,
        "category": "objection_handling",
        "feedback": "...",
        "addressed_core_concern": boolean,
        "evidence_based": boolean,
        "deflection_detected": boolean,
        "recommendations": "..."
    }
    """

    prompt = f"""You are an expert evaluator of medical device sales representative performance.

EVALUATION TASK: Objection Handling Assessment

The physician raised this objection:
---
{objection}
---

The sales representative provided this response:
---
{user_response}
---

{f'CONTEXT: {context}' if context else ''}

SCORING CRITERIA (0-100 scale):

90-100 (EXCELLENT):
- Directly addresses the core concern without deflection
- Provides specific, evidence-based counterargument (trial data, outcomes, etc.)
- Acknowledges legitimate aspects of the objection
- Honest about limitations or tradeoffs
- Response is persuasive without high-pressure tactics
- Moves conversation constructively forward
- Physician would consider this a strong answer

75-89 (GOOD):
- Addresses core concern with minor deflection
- Provides evidence to support response (though may lack some specifics)
- Mostly honest and balanced
- Response is persuasive
- Conversational tone, no pressure tactics
- Advances the discussion constructively

60-74 (ADEQUATE):
- Addresses core concern but with some deflection
- Provides some evidence but may be incomplete or dated
- Acknowledges some limitations
- Response is somewhat persuasive
- Tone is professional but may feel defensive
- Moves conversation forward but with less impact

40-59 (WEAK):
- Only partially addresses core concern
- Significant deflection or avoidance
- Limited evidence provided
- Acknowledges few limitations
- May use pressure tactics or urgency language
- Response less persuasive, physician still skeptical
- Doesn't advance discussion meaningfully

0-39 (POOR):
- Fails to address core concern
- Major deflection or complete avoidance
- No supporting evidence
- Dismissive of legitimate concern
- Pressure tactics, urgency language, or hostility
- Response unpersuasive, would strengthen physician's objection
- Damages credibility and relationship

DETAILED EVALUATION:

1. DIRECT ADDRESS (Does rep answer the actual concern?):
   - Does rep engage with the specific objection raised?
   - Or do they answer a different question?
   - Is there deflection to a feature that doesn't address the core issue?

2. EVIDENCE BASIS (Is the response supported?):
   - Does rep cite specific trial data, outcomes, or evidence?
   - Are claims factual and verifiable?
   - Are claims vague or unsupported?
   - Could the rep back up these claims if pressed?

3. HONESTY & BALANCE (Does rep acknowledge tradeoffs?):
   - Does rep admit limitations or areas where they're not superior?
   - Do they oversell their product?
   - Do they take the objection seriously or dismiss it?

4. PERSUASIVENESS (Would this convince a physician?):
   - Is the response compelling and credible?
   - Does it lower the physician's concern or just deflect it?
   - Would a skeptical physician find this convincing?

5. TONE & PROFESSIONALISM:
   - Is the response professional and respectful?
   - Are there high-pressure tactics or urgency language?
   - Does rep acknowledge physician's legitimate concerns?

6. CONVERSATION ADVANCEMENT:
   - Does this move toward a next step or deeper engagement?
   - Or does it stall or damage the relationship?

Now provide your evaluation in this JSON format:

{{
    "score": <0-100>,
    "category": "objection_handling",
    "feedback": "<2-3 sentence summary of how well the objection was handled>",
    "addressed_core_concern": <true/false>,
    "evidence_provided": <true/false>,
    "deflection_detected": <true/false>,
    "high_pressure_tactics": <true/false>,
    "acknowledged_limitations": <true/false>,
    "strengths": [
        "<What the rep did well in this response>"
    ],
    "weaknesses": [
        "<Area needing improvement>"
    ],
    "critical_gaps": [
        "<Information the rep should have provided but didn't>"
    ],
    "persuasiveness": "<Would this response be persuasive to a skeptical physician? Why/why not?>",
    "recommendations": "<Specific guidance for handling this objection better next time>"
}}

Provide ONLY the JSON output, no other text."""

    return prompt


def get_procedural_workflow_rubric(
    user_response: str,
    context: str = ""
) -> str:
    """
    Generate evaluation prompt for procedural workflow knowledge assessment.

    Evaluates whether the rep understands:
    - How devices work together in sequence
    - Compatibility and nesting requirements
    - System integration and interdependencies
    - Procedural steps and decision points
    - Device sizing and selection criteria
    - How their products fit into standard thrombectomy workflow

    Args:
        user_response: The rep's response about procedural workflow
        context: Additional context (what question was asked, etc.)

    Returns:
        LLM prompt for scoring procedural workflow knowledge

    Expected JSON output:
    {
        "score": 0-100,
        "category": "procedural_workflow",
        "feedback": "...",
        "workflow_understanding": boolean,
        "technical_accuracy": boolean,
        "recommendations": "..."
    }
    """

    prompt = f"""You are an expert evaluator of medical device sales representative performance.

EVALUATION TASK: Procedural Workflow Knowledge Assessment

The sales representative provided this response about procedural workflow:

---
{user_response}
---

{f'CONTEXT: {context}' if context else ''}

BACKGROUND:
Neurointerventional thrombectomy involves a complex procedural workflow where devices must work
together in sequence: access guide catheter → intermediate catheter → distal access catheter →
stent retriever/aspiration catheter. Each device must be compatible with the others (inner diameters,
outer diameters, materials, etc.).

SCORING CRITERIA (0-100 scale):

90-100 (EXPERT):
- Demonstrates comprehensive understanding of full thrombectomy workflow
- Can explain device sequences and compatibility requirements
- Knows specific sizing/nesting parameters (diameters, lengths, material interactions)
- Understands alternative approaches and when to use each
- Can troubleshoot procedural issues
- Explains decision points in the workflow naturally
- Would help a physician optimize their technique

75-89 (STRONG):
- Good understanding of standard workflow and device compatibility
- Knows most sizing/nesting requirements accurately
- Can explain alternative approaches
- Mostly accurate with minor gaps
- Answers workflow questions confidently
- Would provide useful guidance to physician

60-74 (ADEQUATE):
- Basic understanding of workflow and compatibility
- Knows some sizing/nesting requirements
- Explains workflow with minor inaccuracies
- Some gaps in technical knowledge
- Can answer straightforward questions
- May struggle with complex scenarios

40-59 (NEEDS IMPROVEMENT):
- Limited workflow understanding
- Gaps in compatibility knowledge
- Technical inaccuracies in sizing/nesting
- Struggles to explain procedural sequences
- Can answer only basic questions
- Would not provide reliable guidance

0-39 (INADEQUATE):
- Minimal workflow understanding
- Significant technical inaccuracies
- Cannot explain device sequences
- Cannot discuss compatibility
- Cannot answer procedural questions
- Would mislead a physician

DETAILED EVALUATION:

1. WORKFLOW UNDERSTANDING (Does rep understand the procedure?):
   - Can they explain the sequence of devices used?
   - Do they understand standard thrombectomy approach?
   - Can they explain alternatives (stent-first vs. aspiration-first)?

2. DEVICE COMPATIBILITY (Does rep know what works with what?):
   - Can they discuss inner/outer diameter compatibility?
   - Do they know nesting requirements?
   - Understand material interactions?
   - Know which combinations work and which don't?

3. TECHNICAL ACCURACY (Are the details correct?):
   - Specific device diameters and lengths accurate?
   - Compatibility information correct?
   - Procedural steps described accurately?
   - Any errors or misconceptions?

4. PROCEDURAL DECISION-MAKING (Does rep understand case strategy?):
   - Can they explain when to use different techniques?
   - How decisions made during procedure based on anatomy?
   - How their devices support these decisions?

5. SYSTEM INTEGRATION (Does rep understand their full system?):
   - How their products work together?
   - How they integrate with standard workflow?
   - Advantages/disadvantages vs. other systems?

TECHNICAL KNOWLEDGE EXPECTED:
- Guide catheter access (size, positioning)
- Intermediate catheter (typical sizes: 6-8Fr, outer diameter constraints)
- Distal access catheter (typical OD: 0.070-0.088")
- Stent retriever/aspiration catheter sizing and compatibility
- How each device nests inside the previous
- Device material and interaction considerations
- When and why to choose different approaches

Now provide your evaluation in this JSON format:

{{
    "score": <0-100>,
    "category": "procedural_workflow",
    "feedback": "<2-3 sentence summary of workflow knowledge demonstrated>",
    "workflow_understanding": <true/false - understands overall procedure?>,
    "technical_accuracy": <true/false - details correct?>,
    "device_compatibility_knowledge": <true/false - knows what works together?>,
    "alternative_approach_understanding": <true/false - knows different techniques?>,
    "strengths": [
        "<Area of strong procedural knowledge>"
    ],
    "technical_gaps": [
        "<Specific inaccuracy or knowledge gap in technical details>"
    ],
    "workflow_gaps": [
        "<Gap in understanding procedural workflow or sequences>"
    ],
    "critical_missing_knowledge": [
        "<Important technical information the rep didn't mention but should know>"
    ],
    "teaching_value": "<Would a physician learn from this explanation, or would they need to correct errors?>",
    "recommendations": "<Specific areas for technical knowledge development>"
}}

Provide ONLY the JSON output, no other text."""

    return prompt


def get_closing_effectiveness_rubric(
    user_response: str,
    conversation_history: str = ""
) -> str:
    """
    Generate evaluation prompt for closing effectiveness assessment.

    Evaluates whether the rep:
    - Is moving toward a commitment or next step
    - Uses appropriate closing techniques (trial, case observation, formal evaluation, etc.)
    - Reads the physician's readiness
    - Handles objections to next steps
    - Maintains relationship even if not closing today
    - Sets clear expectations for follow-up

    Args:
        user_response: The rep's closing or attempted next step
        conversation_history: Summary of the conversation so far

    Returns:
        LLM prompt for scoring closing effectiveness

    Expected JSON output:
    {
        "score": 0-100,
        "category": "closing_effectiveness",
        "feedback": "...",
        "clear_next_step": boolean,
        "momentum_building": boolean,
        "relationship_maintained": boolean,
        "recommendations": "..."
    }
    """

    prompt = f"""You are an expert evaluator of medical device sales representative performance.

EVALUATION TASK: Closing Effectiveness Assessment

The sales representative's closing/next-step statement:
---
{user_response}
---

{f'CONVERSATION CONTEXT: {conversation_history}' if conversation_history else ''}

BACKGROUND:
In medical device sales, especially with physicians, the close is about moving to a next step,
not a hard close. Appropriate next steps include:
- Trial/evaluation of product with small case volume
- Case observation (physician watches skilled operator use device)
- Formal product demonstration
- Information/data review followed by follow-up
- Team discussion with colleagues
- Pilot program with specific parameters
- NOT high-pressure immediate commitment

Successful closers read physician readiness, offer appropriate next steps, handle objections to
those steps, and maintain relationship regardless of immediate outcome.

SCORING CRITERIA (0-100 scale):

90-100 (EXCELLENT):
- Clear, specific next step proposed (not vague "I'll follow up")
- Appropriate to physician's expressed readiness
- Addresses stated concerns before proposing next step
- Specific timeline and commitment requested
- Maintains relationship even if physician hesitant
- Offers multiple pathways forward
- Shows confidence without pressure
- Physician would clearly understand what's being proposed

75-89 (GOOD):
- Clear next step proposed
- Mostly appropriate to physician's readiness
- Mostly addresses concerns before closing
- Timeline mentioned
- Relationship maintained
- Professional tone throughout

60-74 (ADEQUATE):
- Next step proposed but could be clearer
- May not fully address all concerns first
- Timeline vague or missing
- Somewhat appropriate to readiness level
- Maintains relationship but less skillfully
- Professional tone

40-59 (WEAK):
- Vague next step or multiple unclear options
- Doesn't address physician objections adequately
- Poor read on physician's readiness
- Pressure tactics emerging
- No clear timeline
- Relationship somewhat strained

0-39 (POOR):
- No clear next step or attempt to close
- Aggressive/high-pressure closing tactics
- Ignores physician's stated concerns
- Unclear what physician is being asked to do
- Damages relationship
- Misses signals about readiness

DETAILED EVALUATION:

1. CLARITY OF NEXT STEP (Is it clear what's being asked?):
   - What specific action is the rep asking for?
   - Is it clear enough that physician knows exactly what's being proposed?
   - Or is it vague ("I'll follow up" / "Stay in touch")?

2. APPROPRIATENESS OF CLOSE (Does it match physician's readiness?):
   - Is the physician ready for commitment, trial, or observation?
   - Is the proposed next step appropriate to their expressed interest level?
   - Or is the rep pushing too hard or not pushing hard enough?

3. CONCERN HANDLING (Were objections addressed first?):
   - Did rep address physician's stated objections before closing?
   - Or is rep trying to close despite unresolved concerns?
   - Does physician feel heard before being asked for next step?

4. TIMELINE & COMMITMENT (Is follow-up specified?):
   - When will this evaluation happen?
   - Who will contact whom?
   - What's the timeline for decision?
   - Or is it vague and open-ended?

5. RELATIONSHIP MAINTENANCE (Is relationship preserved?):
   - Does rep show respect for physician's perspective even if not committing?
   - Would physician want to talk to rep again?
   - Or would this interaction sour the relationship?

6. CONFIDENCE WITHOUT PRESSURE:
   - Does rep show confidence in product?
   - Or does rep come across as desperate/pushy?

APPROPRIATE NEXT STEPS FOR MEDICAL DEVICES:
- Formal product demonstration (specific date/time proposed)
- Limited case trial (specific number of cases, timeline)
- Case observation (rep or skilled operator demonstrates)
- Data review (specific materials offered, follow-up date set)
- Physician discussion with team (gather internal input)
- Pilot program (structured evaluation with success metrics)
- NOT: Generic "I'll call you next week" or "Think about it"

Now provide your evaluation in this JSON format:

{{
    "score": <0-100>,
    "category": "closing_effectiveness",
    "feedback": "<2-3 sentence summary of closing effectiveness>",
    "clear_next_step": <true/false - is next step specific and clear?>,
    "momentum_building": <true/false - is rep building toward commitment?>,
    "relationship_maintained": <true/false - would physician want future contact?>,
    "appropriateness_to_readiness": "<Is the proposed next step appropriate to the physician's expressed interest level?>",
    "objections_addressed": <true/false - were physician's concerns addressed before closing?>,
    "pressure_tactics": <true/false - any aggressive or high-pressure language?>,
    "strengths": [
        "<What the rep did well in closing>"
    ],
    "weaknesses": [
        "<Area where closing could be stronger>"
    ],
    "next_step_proposed": "<Summarize the specific next step being proposed>",
    "timeline_clarity": "<Is the timeline specific (date/timeframe) or vague?>",
    "likelihood_of_follow_up": "<Based on this interaction, would the physician actually follow up on the proposed next step?>",
    "recommendations": "<Specific guidance for more effective closes in future>"
}}

Provide ONLY the JSON output, no other text."""

    return prompt


def parse_rubric_response(rubric_response: str) -> Dict[str, Any]:
    """
    Parse a rubric response (assumed to be JSON) into a structured dict.

    Args:
        rubric_response: The raw response from the LLM (should be JSON)

    Returns:
        Parsed dictionary of rubric results

    Handles JSON parsing errors gracefully.
    """
    try:
        return json.loads(rubric_response)
    except json.JSONDecodeError:
        # If response isn't valid JSON, return error structure
        return {
            "error": "Failed to parse rubric response as JSON",
            "raw_response": rubric_response,
            "score": 0,
            "feedback": "Unable to parse evaluation response"
        }


def get_rubric_summary(
    category: str,
    score: int,
    feedback: str
) -> str:
    """
    Generate a human-readable summary of a rubric score.

    Args:
        category: The rubric category (competitive_knowledge, objection_handling, etc.)
        score: The numerical score (0-100)
        feedback: The feedback text

    Returns:
        Formatted summary string
    """

    if score >= 90:
        level = "EXPERT"
    elif score >= 75:
        level = "STRONG"
    elif score >= 60:
        level = "ADEQUATE"
    elif score >= 40:
        level = "NEEDS IMPROVEMENT"
    else:
        level = "INADEQUATE"

    category_display = category.replace("_", " ").title()

    summary = f"""
{category_display.upper()} EVALUATION
{'=' * 60}
Level: {level} ({score}/100)

Feedback:
{feedback}
"""

    return summary


# Scoring thresholds for pass/fail decisions
PASSING_SCORES = {
    "competitive_knowledge": 70,  # Must know competitors reasonably well
    "objection_handling": 75,  # Must handle objections effectively
    "procedural_workflow": 65,  # Must understand technical workflow
    "closing_effectiveness": 70,  # Must be able to advance toward next steps
}

# Overall readiness thresholds
OVERALL_READINESS_THRESHOLDS = {
    "ready_for_independent_calls": 75,  # Average across all categories
    "needs_mentoring": 60,  # Can call with supervision/support
    "requires_training": 50,  # Needs structured development
}


def assess_overall_readiness(
    scores: Dict[str, int]
) -> Dict[str, Any]:
    """
    Assess overall readiness based on rubric scores across all categories.

    Args:
        scores: Dictionary mapping rubric categories to scores (0-100)

    Returns:
        Dictionary with readiness assessment and recommendations
    """

    if not scores:
        return {"error": "No scores provided"}

    average_score = sum(scores.values()) / len(scores)
    category_results = {
        category: {
            "score": score,
            "passing": score >= PASSING_SCORES.get(category, 70),
            "level": _get_score_level(score)
        }
        for category, score in scores.items()
    }

    if average_score >= OVERALL_READINESS_THRESHOLDS["ready_for_independent_calls"]:
        readiness = "ready_for_independent_calls"
        recommendation = "This rep is ready for independent physician calls."
    elif average_score >= OVERALL_READINESS_THRESHOLDS["needs_mentoring"]:
        readiness = "needs_mentoring"
        recommendation = "This rep can make calls with coaching/mentoring support."
    else:
        readiness = "requires_training"
        recommendation = "This rep requires structured training before independent calls."

    return {
        "overall_score": round(average_score, 1),
        "readiness_level": readiness,
        "recommendation": recommendation,
        "category_results": category_results,
        "passing_categories": sum(1 for r in category_results.values() if r["passing"]),
        "total_categories": len(category_results),
        "strengths": [cat for cat, res in category_results.items() if res["score"] >= 80],
        "development_areas": [cat for cat, res in category_results.items() if res["score"] < 70],
    }


def _get_score_level(score: int) -> str:
    """Convert numeric score to descriptive level."""
    if score >= 90:
        return "Expert"
    elif score >= 75:
        return "Strong"
    elif score >= 60:
        return "Adequate"
    elif score >= 40:
        return "Needs Improvement"
    else:
        return "Inadequate"
