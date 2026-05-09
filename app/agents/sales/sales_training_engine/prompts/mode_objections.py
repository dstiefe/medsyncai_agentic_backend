"""
Objection Handling Drills Simulation Prompt

This module generates objection handling scenarios where the AI plays the role of
a physician raising realistic concerns that sales representatives must address.

The physician will:
- Present one objection at a time
- Be realistic and persistent
- Challenge deflection or vague answers
- Evaluate whether the rep adequately addressed the concern
- Progress through a series of increasingly complex objections
"""

from typing import Dict, Any, List, Optional
from enum import Enum


class ObjectionCategory(Enum):
    """Types of objections physicians raise."""
    STATUS_QUO = "status_quo"
    EVIDENCE_CURRENCY = "evidence_currency"
    FORMULARY_CONSTRAINT = "formulary_constraint"
    ADVERSE_EXPERIENCE = "adverse_experience"
    CLINICAL_CHALLENGE = "clinical_challenge"
    COMPETITIVE_PRESSURE = "competitive_pressure"
    COST_BENEFIT = "cost_benefit"
    WORKFLOW_INTEGRATION = "workflow_integration"
    TRAINING_SUPPORT = "training_support"
    VENDOR_RELATIONSHIP = "vendor_relationship"


def get_prompt(
    physician_profile: Dict[str, Any],
    rep_company: str,
    context: str = ""
) -> str:
    """
    Generate an objection handling drills prompt.

    Args:
        physician_profile: Dictionary containing physician profile details
        rep_company: The sales rep's company being tested
        context: Optional additional context

    Returns:
        Complete system prompt for the AI to roleplay objecting physician
    """

    name = physician_profile.get("name", "Unknown")
    specialty = physician_profile.get("specialty", "")
    annual_cases = physician_profile.get("annual_cases", 0)
    experience_years = physician_profile.get("experience_years", 0)
    current_stack = physician_profile.get("current_stack", {})
    personality = physician_profile.get("personality_traits", {})
    communication_style = physician_profile.get("communication_style", "")

    # Format current stack for reference
    current_devices = ", ".join([v for v in current_stack.values() if v][:3])

    # Determine objection intensity based on personality
    objection_intensity = _get_objection_intensity(personality)

    prompt = f"""You are {name}, a {specialty} physician with {experience_years} years of experience.

ROLE IN THIS DRILL:
You are raising realistic objections to a sales representative from {rep_company.title()}.
This is an objection handling training exercise. Your job is to push back on their pitch
with the concerns and skepticism a real physician would have.

YOUR CURRENT SITUATION:
- You're using: {current_devices}
- Clinical volume: {annual_cases} cases per year
- You're experienced and skeptical of new products
- Communication style: {communication_style}

YOUR APPROACH:
You will raise 8-10 realistic objections, one at a time. For each:

1. Present the objection clearly and specifically
2. Wait for the rep's response
3. Evaluate whether they adequately addressed your concern
4. Push back if they deflected, were vague, or didn't directly answer
5. Ask follow-up questions if needed
6. Move to next objection only when satisfied (or after they've made their best attempt)

OBJECTION PROGRESSION:
You will naturally progress through these objections in realistic order:

1. STATUS QUO BIAS (Opening Objection)
2. EVIDENCE CURRENCY
3. FORMULARY/CONTRACT CONSTRAINT
4. ADVERSE EXPERIENCE
5. CLINICAL SKEPTICISM
6. COMPETITIVE PRESSURE
7. COST-BENEFIT ANALYSIS
8. WORKFLOW INTEGRATION
9. TRAINING & SUPPORT
10. VENDOR RELATIONSHIP

DO NOT ACCEPT THESE RESPONSES:
- "I understand your concern" without actually addressing it
- Deflecting to a feature that doesn't answer your core concern
- Vague claims like "Our data is excellent" (demand specifics)
- Comparisons without evidence
- Dismissing your legitimate clinical concerns
- High-pressure tactics or urgency language

IF THE REP DODGES:
Push back directly: "That doesn't really answer my question about..."
or "I appreciate that, but what about the specific concern I raised?"

EVALUATION FRAMEWORK:
After each rep response, assess:
✓ Did they address the core concern directly?
✓ Was their response evidence-based?
✓ Did they acknowledge tradeoffs or limitations honestly?
✓ Would you consider switching based on this answer?

Move to next objection when:
- They provided a satisfactory answer, OR
- They made a genuine attempt and you're not convinced, but ready to move on

OBJECTION INTENSITY: {objection_intensity}
Your objections should be {objection_intensity} in tone and persistence.

{f'ADDITIONAL CONTEXT: {context}' if context else ''}

You are now beginning the objection drill. Introduce yourself briefly, then present your
first objection (Status Quo Bias). Be realistic—you're not trying to be difficult, just
expressing real concerns a busy physician would raise.

Remember: Your job is to challenge the rep appropriately. If they make good counterpoints,
you can acknowledge them. But push back on weak or evasive responses.
"""

    return prompt


def _get_objection_intensity(personality: Dict[str, float]) -> str:
    """Determine objection intensity based on personality traits."""
    evidence_driven = personality.get("evidence_driven", 0.5)
    cautious = personality.get("cautious", 0.5)
    cost_conscious = personality.get("cost_conscious", 0.5)

    intensity_score = evidence_driven + cautious + cost_conscious

    if intensity_score >= 2.2:
        return "high (you're very skeptical and demanding of evidence)"
    elif intensity_score >= 1.5:
        return "moderate (you're cautious but open to evidence)"
    else:
        return "light (you're open-minded but still professional)"


def get_objection(
    objection_type: ObjectionCategory,
    physician_profile: Dict[str, Any],
    rep_company: str,
    previous_answers: Optional[List[str]] = None
) -> str:
    """
    Get a specific objection based on type and context.

    Args:
        objection_type: The category of objection to present
        physician_profile: The physician's profile
        rep_company: The sales rep's company
        previous_answers: List of previous rep responses (for context)

    Returns:
        The objection statement
    """

    name = physician_profile.get("name", "Dr. Unknown")
    current_stack = physician_profile.get("current_stack", {})
    annual_cases = physician_profile.get("annual_cases", 0)
    experience_years = physician_profile.get("experience_years", 0)

    current_devices = list(current_stack.values())
    primary_device = current_devices[0] if current_devices else "my current devices"

    objections = {
        ObjectionCategory.STATUS_QUO: f"""Here's my first concern: I'm quite satisfied with what I'm using right now.
I'm currently using {primary_device} and my complication rates are good, first-pass effect is solid,
and my team is trained on these devices. You're going to have to show me something significantly
better to justify switching. What specific advantage does your product offer that would make me
change what's working?""",

        ObjectionCategory.EVIDENCE_CURRENCY: f"""Okay, but your clinical data—how recent is it? I was looking at your website and
much of the data is from 2015, 2016, even older. That's over a decade ago. The field has evolved
significantly. What's your current clinical evidence? Do you have outcome data from the last 2-3 years?
And what's your TICI 3 rate from recent cases?""",

        ObjectionCategory.FORMULARY_CONSTRAINT: f"""Here's a practical issue: My hospital just signed a three-year GPO contract with my current
vendor. We can't easily add new products even if they're superior. The logistics, approval process,
contract negotiation—it's complicated. What would you suggest as a path forward given that constraint?""",

        ObjectionCategory.ADVERSE_EXPERIENCE: f"""Actually, I do have a concern based on personal experience. I had a case about six months ago
where your device—or a similar one—kinked in the internal carotid artery. It was difficult to
retrieve and we had significant downtime troubleshooting it. How common is that problem? What's
your mitigation strategy?""",

        ObjectionCategory.CLINICAL_CHALLENGE: f"""Let me ask you this: Show me your first-pass effect data in challenging cases.
My most difficult cases involve calcified vessels, tandem occlusions, or patients with difficult anatomy.
That's where I need strong performance. What's your success rate in those scenarios? Can you break down
your data by case complexity?""",

        ObjectionCategory.COMPETITIVE_PRESSURE: f"""Here's what I'm wrestling with: A competitor rep was in here last month and showed me data
I hadn't seen before. They demonstrated superior outcomes on [specific metric]. How does your product
compare? And be honest—do you have equivalent or better data to show me?""",

        ObjectionCategory.COST_BENEFIT: f"""Let's talk about economics. The price difference between your device and what I'm using is
meaningful. You'd need to convince me that the clinical benefit justifies the cost difference. Walk me
through the cost-benefit analysis. Does faster procedure time offset higher device cost? Show me the math.""",

        ObjectionCategory.WORKFLOW_INTEGRATION: f"""I need to understand workflow integration. We use [current setup]. We have established
protocols, training, and procedures built around our current system. Will your device integrate smoothly?
Are there compatibility issues? What's the learning curve for my team? Could it slow us down initially?""",

        ObjectionCategory.TRAINING_SUPPORT: f"""Assuming I wanted to move forward, what would training look like? My team is busy running
cases. How much time would we need to invest in learning your device? Who provides the training? How much
support can you provide if we run into issues during implementation?""",

        ObjectionCategory.VENDOR_RELATIONSHIP: f"""I need to be honest—I have a good relationship with my current vendor. They know me,
support our program, give us favorable pricing, and respond when we have issues. Switching means starting
that relationship over from scratch. What assurance can you give me that you'll provide equivalent support?""",
    }

    return objections.get(objection_type, "Default objection not found.")


def get_evaluation_framework(objection_type: ObjectionCategory) -> Dict[str, List[str]]:
    """
    Get evaluation criteria for a specific objection type.

    Args:
        objection_type: The type of objection being addressed

    Returns:
        Dictionary with evaluation criteria and red flags
    """

    frameworks = {
        ObjectionCategory.STATUS_QUO: {
            "good_responses": [
                "Acknowledges current satisfaction while highlighting specific clinical gap",
                "Provides evidence of clinical improvement (trial data, outcomes)",
                "Addresses the specific barrier to switching (cost, complexity, training)",
                "Offers path to evaluation (trial, case observation, limited rollout)",
            ],
            "red_flags": [
                "Dismisses current device without evidence",
                "Vague claims like 'our product is better'",
                "High-pressure sales tactics",
                "Doesn't acknowledge legitimacy of current satisfaction",
            ],
            "key_question": "Is there a compelling, evidence-based reason to switch?",
        },

        ObjectionCategory.EVIDENCE_CURRENCY: {
            "good_responses": [
                "Provides recent data (2022-2025) from peer-reviewed sources",
                "Cites specific trial names and outcome percentages",
                "Acknowledges older data but explains why it's still relevant",
                "Offers to send comprehensive, current clinical evidence",
            ],
            "red_flags": [
                "Only provides old data with no recent evidence",
                "Vague references like 'our latest studies'",
                "Defensive about age of data",
                "Can't cite specific trial names or numbers",
            ],
            "key_question": "Do they have recent, credible clinical evidence?",
        },

        ObjectionCategory.FORMULARY_CONSTRAINT: {
            "good_responses": [
                "Acknowledges reality of GPO contracts",
                "Suggests creative solutions (pilot program, specific indications)",
                "Offers to work with hospital administration",
                "Provides information about contract flexibility options",
            ],
            "red_flags": [
                "Downplays the seriousness of contract constraints",
                "Pushes for immediate switch despite contract",
                "No viable solution offered",
                "Dismisses the concern as 'not their problem'",
            ],
            "key_question": "Do they understand and help navigate contract realities?",
        },

        ObjectionCategory.ADVERSE_EXPERIENCE: {
            "good_responses": [
                "Takes the concern seriously, doesn't dismiss it",
                "Asks for details to understand the specific issue",
                "Provides honest discussion of risk profile",
                "Explains design features that mitigate that risk",
                "Offers to review the case or discuss mitigation",
            ],
            "red_flags": [
                "Dismisses the concern or blames operator",
                "Doesn't acknowledge the problem exists",
                "Defensive response",
                "Can't explain mitigation strategies",
            ],
            "key_question": "Do they respond professionally to safety concerns?",
        },

        ObjectionCategory.CLINICAL_CHALLENGE: {
            "good_responses": [
                "Provides specific outcome data for challenging cases",
                "Breaks down data by case type (calcified, tandem, etc.)",
                "Honest about limitations in specific scenarios",
                "Explains technique modifications for difficult cases",
                "Cites trial data for subgroup analysis",
            ],
            "red_flags": [
                "Only provides overall statistics, not subgroup data",
                "Vague claims about difficult cases",
                "Can't cite specific evidence for challenging scenarios",
                "Oversells capability in complex anatomy",
            ],
            "key_question": "Do they have credible data for your specific clinical challenges?",
        },

        ObjectionCategory.COMPETITIVE_PRESSURE: {
            "good_responses": [
                "Acknowledges competitor's strengths honestly",
                "Provides direct comparison with specific data",
                "Explains where they have advantage, where they don't",
                "Offers to review competitor data together",
                "Evidence-based competitive positioning",
            ],
            "red_flags": [
                "Dismisses competitor without engagement",
                "Makes unsupported claims about competitor",
                "Can't answer direct comparison questions",
                "Defensive or dismissive tone",
            ],
            "key_question": "Can they engage honestly in competitive discussion?",
        },

        ObjectionCategory.COST_BENEFIT: {
            "good_responses": [
                "Acknowledges cost difference directly",
                "Provides quantified benefits (faster cases, higher FPE, lower complications)",
                "Walks through financial calculation",
                "Discusses total cost of ownership, not just device price",
                "Offers pricing flexibility or ROI analysis",
            ],
            "red_flags": [
                "Avoids discussing higher cost",
                "Vague benefit claims without numbers",
                "No financial analysis provided",
                "Assumes benefits outweigh costs without proof",
            ],
            "key_question": "Is there genuine financial benefit despite higher cost?",
        },

        ObjectionCategory.WORKFLOW_INTEGRATION: {
            "good_responses": [
                "Understands your current workflow in detail",
                "Explains integration requirements honestly",
                "Acknowledges any compatibility issues",
                "Provides timeline for team learning curve",
                "Offers implementation support",
            ],
            "red_flags": [
                "Doesn't ask about your current workflow",
                "Overstates ease of integration",
                "Can't explain technical compatibility",
                "Dismisses workflow concerns",
            ],
            "key_question": "Will this integrate smoothly into our operation?",
        },

        ObjectionCategory.TRAINING_SUPPORT: {
            "good_responses": [
                "Clear, realistic training timeline",
                "Identifies on-site vs. off-site training needs",
                "Explains ongoing support structure",
                "Provides dedicated support contact",
                "Discusses training for different roles (nurses, physicians, techs)",
            ],
            "red_flags": [
                "Vague about training requirements",
                "Implies no training needed for 'simple' product",
                "No ongoing support plan",
                "Can't explain support contact structure",
            ],
            "key_question": "Do they provide adequate training and ongoing support?",
        },

        ObjectionCategory.VENDOR_RELATIONSHIP: {
            "good_responses": [
                "Acknowledges importance of relationship",
                "Explains their relationship/support philosophy",
                "Offers designated account rep or support team",
                "Discusses how they handle issues and escalations",
                "Provides references from similar customers",
            ],
            "red_flags": [
                "Dismisses importance of vendor relationship",
                "Can't articulate their support approach",
                "No clear point of contact or escalation path",
                "Generic response about company support",
            ],
            "key_question": "Will they support us like my current vendor does?",
        },
    }

    return frameworks.get(objection_type, {})


def get_follow_up_challenge(
    objection_type: ObjectionCategory,
    rep_response: str,
    physician_profile: Dict[str, Any]
) -> Optional[str]:
    """
    Generate a follow-up challenge if the rep's response was inadequate.

    Args:
        objection_type: The type of objection
        rep_response: The rep's response to evaluate
        physician_profile: The physician's profile

    Returns:
        A follow-up challenge, or None if response was acceptable
    """

    # This would be driven by LLM evaluation in actual implementation
    # Here we provide templates for different inadequate response patterns

    if "understand" in rep_response.lower() and len(rep_response.split()) < 20:
        return "I appreciate that you understand, but you haven't actually addressed my concern. Can you give me specifics?"

    if "data" in objection_type.name.lower() and "[" not in rep_response:
        return "That's helpful, but I need to see actual numbers and trial citations. Can you provide specific data?"

    if "cost" in objection_type.name.lower() and "$" not in rep_response:
        return "I hear you, but you haven't addressed the actual cost difference. Can you walk me through the numbers?"

    return None


def get_drill_summary_prompt(
    rep_company: str,
    objections_presented: int,
    objections_handled_well: int
) -> str:
    """
    Generate a summary prompt at the end of the objection drill.

    Args:
        rep_company: The sales rep's company
        objections_presented: Number of objections presented
        objections_handled_well: Number of objections handled adequately

    Returns:
        Summary prompt and evaluation
    """

    handling_percentage = (objections_handled_well / objections_presented * 100) if objections_presented > 0 else 0

    if handling_percentage >= 80:
        evaluation = """
EXCELLENT OBJECTION HANDLING
This rep demonstrates strong skills in addressing physician concerns:
✓ Engaged directly with each concern
✓ Provided evidence-based responses
✓ Acknowledged limitations and tradeoffs
✓ Didn't deflect or use high-pressure tactics
✓ Moved conversations toward next steps appropriately

Recommendation: Ready for independent physician calls. Focus on continuing to deepen
competitive knowledge and clinical evidence retention.
"""
    elif handling_percentage >= 60:
        evaluation = """
GOOD OBJECTION HANDLING WITH GAPS
This rep handles most objections well but struggles in some areas:
✓ Good engagement on most concerns
~ Mixed on providing specific evidence
~ Sometimes deflected rather than addressed directly
~ Needs stronger competitive knowledge
~ Better on clinical objections than business objections

Recommendation: Focused training on: (1) Citation practice for specific trials,
(2) Competitive positioning, (3) Directness in addressing concerns. Re-test in 2-3 weeks.
"""
    elif handling_percentage >= 40:
        evaluation = """
ADEQUATE OBJECTION HANDLING WITH SIGNIFICANT GAPS
This rep needs improvement in objection handling:
~ Addressed some concerns effectively
✗ Frequently deflected or avoided direct answers
✗ Weak on evidence citations and specific data
✗ High-pressure tactics in some responses
✗ Limited knowledge of competitive landscape

Recommendation: Structured training program on: (1) Objection handling technique,
(2) Product knowledge and trial data, (3) Evidence-based selling. Pair with mentor.
Supervised calls only until improvement demonstrated.
"""
    else:
        evaluation = """
INADEQUATE OBJECTION HANDLING
This rep requires significant training before unsupervised physician interactions:
✗ Failed to address core concerns in most objections
✗ Frequent deflection and avoidance
✗ Weak or missing evidence support
✗ Defensive or dismissive responses
✗ Limited product and competitive knowledge

Recommendation: Comprehensive retraining required. Remove from independent sales activities.
Intensive mentoring and role-playing practice needed. Full retest mandatory after 4-6 weeks
of structured development.
"""

    summary = f"""
================================================================================
OBJECTION HANDLING DRILL SUMMARY
================================================================================
Company: {rep_company.title()}
Objections Presented: {objections_presented}
Well-Handled: {objections_handled_well}
Success Rate: {handling_percentage:.1f}%

{evaluation}

DETAILED FEEDBACK BY CATEGORY:
[Summarize performance on each objection type - Status Quo, Evidence, Cost, Clinical, etc.]

SPECIFIC STRENGTHS:
- [Area where rep showed strongest skills]
- [Another area of strength]

DEVELOPMENT AREAS:
- [Most critical area for improvement]
- [Secondary area needing work]
- [Specific product knowledge gaps]

NEXT STEPS:
[Specific recommendations for development based on performance]

================================================================================
"""

    return summary


def get_objection_sequence(physician_profile: Dict[str, Any]) -> List[ObjectionCategory]:
    """
    Get the recommended sequence of objections based on physician profile.

    Args:
        physician_profile: The physician's profile

    Returns:
        Ordered list of objection categories
    """

    # Most realistic objections come in this order naturally
    standard_sequence = [
        ObjectionCategory.STATUS_QUO,  # Opening - what I'm using works
        ObjectionCategory.EVIDENCE_CURRENCY,  # Data freshness question
        ObjectionCategory.FORMULARY_CONSTRAINT,  # Practical business barrier
        ObjectionCategory.ADVERSE_EXPERIENCE,  # Personal clinical concern
        ObjectionCategory.CLINICAL_CHALLENGE,  # Clinical depth challenge
        ObjectionCategory.COMPETITIVE_PRESSURE,  # What about competitors?
        ObjectionCategory.COST_BENEFIT,  # Financial justification
        ObjectionCategory.WORKFLOW_INTEGRATION,  # Operational fit
    ]

    # Customize based on profile characteristics
    evidence_driven = physician_profile.get("personality_traits", {}).get("evidence_driven", 0.5)
    cost_conscious = physician_profile.get("personality_traits", {}).get("cost_conscious", 0.5)
    learning_oriented = physician_profile.get("personality_traits", {}).get("learning_oriented", 0.5)

    # Reorder based on what this physician cares about most
    customized_sequence = standard_sequence.copy()

    if evidence_driven > 0.7:
        # Move evidence and clinical challenge earlier
        if ObjectionCategory.EVIDENCE_CURRENCY in customized_sequence:
            customized_sequence.remove(ObjectionCategory.EVIDENCE_CURRENCY)
            customized_sequence.insert(0, ObjectionCategory.EVIDENCE_CURRENCY)
        if ObjectionCategory.CLINICAL_CHALLENGE in customized_sequence:
            customized_sequence.remove(ObjectionCategory.CLINICAL_CHALLENGE)
            customized_sequence.insert(2, ObjectionCategory.CLINICAL_CHALLENGE)

    if cost_conscious > 0.7:
        # Move cost-benefit earlier
        if ObjectionCategory.COST_BENEFIT in customized_sequence:
            customized_sequence.remove(ObjectionCategory.COST_BENEFIT)
            idx = min(4, len(customized_sequence))
            customized_sequence.insert(idx, ObjectionCategory.COST_BENEFIT)

    if learning_oriented > 0.7:
        # Add training support objection
        customized_sequence.append(ObjectionCategory.TRAINING_SUPPORT)

    # Add vendor relationship near end for experienced physicians
    if physician_profile.get("experience_years", 0) > 10:
        customized_sequence.append(ObjectionCategory.VENDOR_RELATIONSHIP)

    return customized_sequence
