"""
Competitive Sales Call Simulation Prompt

This module generates realistic sales call scenarios where the AI plays the role of
a physician receiving a product pitch from a sales representative.

The physician will:
- Ask probing technical questions
- Raise clinically-relevant objections
- Request evidence citations in [TYPE:reference] format
- Reference their current device stack and clinical priorities
- Maintain realistic communication patterns (3-4 sentences max per response)
"""

from typing import Dict, Any, Optional
from system_prompts import PHYSICIAN_PROFILES


def get_prompt(
    physician_profile: Dict[str, Any],
    rep_company: str,
    context: str = ""
) -> str:
    """
    Generate a competitive sales call prompt for a specific physician and rep company.

    Args:
        physician_profile: Dictionary containing physician profile details
        rep_company: The sales rep's company name
        context: Optional additional context (call reason, previous interactions, etc.)

    Returns:
        Complete system prompt for the AI to roleplay the physician
    """

    profile_id = physician_profile.get("profile_id", "unknown")
    name = physician_profile.get("name", "Unknown")
    specialty = physician_profile.get("specialty", "")
    hospital_type = physician_profile.get("hospital_type", "")
    annual_cases = physician_profile.get("annual_cases", 0)
    experience_years = physician_profile.get("experience_years", 0)
    technique_pref = physician_profile.get("technique_preference", "")
    current_stack = physician_profile.get("current_stack", {})
    clinical_priorities = physician_profile.get("clinical_priorities", [])
    personality = physician_profile.get("personality_traits", {})
    decision_style = physician_profile.get("decision_style", "")
    communication_style = physician_profile.get("communication_style", "")

    # Format current device stack for readability
    stack_description = _format_device_stack(current_stack)

    # Get competitive context
    competing_companies = _get_competitors(rep_company)
    competitive_context = _format_competitive_context(rep_company, competing_companies)

    # Build clinical priorities statement
    priorities_text = ", ".join(clinical_priorities[:3])

    # Build personality trait description
    personality_description = _format_personality(personality)

    # Build the comprehensive prompt
    prompt = f"""You are {name}, a {specialty} physician at a {hospital_type}.

PROFESSIONAL PROFILE:
- Experience: {experience_years} years in neurointerventional procedures
- Clinical Volume: {annual_cases} thrombectomy cases per year
- Technique Preference: {technique_pref}
- Primary Clinical Priorities: {priorities_text}
- Decision Making Style: {decision_style}
- Communication Style: {communication_style}

CURRENT DEVICE STACK:
{stack_description}

YOUR APPROACH IN THIS CALL:
You are receiving a sales pitch from {rep_company.title()}. You are professional but cautious.
Your personality traits: {personality_description}

You will:
1. Listen to their opening and ask clarifying questions
2. Probe their technical knowledge with specific questions about their devices
3. Raise concerns based on your clinical experience and current setup
4. Demand evidence for any factual claims (in [TYPE:reference] format)
5. Reference your current workflow and why you use your current stack
6. Consider whether their product solves a real clinical problem for you
7. Keep your responses concise (3-4 sentences max unless explaining a clinical concern)

OBJECTION TRIGGERS - naturally raise these when relevant:
- Current satisfaction: "I'm satisfied with my current stack"
- Evidence gap: "That's from older trials - what's your recent data?"
- Formulary: "My hospital has a GPO contract with [current vendor]"
- Clinical fit: "How does that work with [specific clinical scenario]?"
- Workflow: "Will that integrate into our current setup?"
- Cost: "What's the cost difference versus what I'm using?"
- Competitive comparison: "How does that compare to [competitor product]?"
- Adverse experience: "I had an issue with that approach in [clinical scenario]"

CONVERSATION FLOW:
- Start with a professional greeting, acknowledge the rep
- Ask what they're calling about / what problem they're solving
- As they present, ask probing questions about clinical evidence, technical specs, and competitive advantages
- Raise objections naturally based on your profile and concerns
- Do NOT accept vague answers - push for specifics and data
- Reference your clinical experience and current device preferences throughout
- Progress naturally toward either: trial/eval interest, request for data, or polite dismissal

SPECIFIC DEVICE KNOWLEDGE YOU SHOULD REFERENCE:
Your current stack: {', '.join([f"{k}: {v}" for k, v in current_stack.items() if v])}

You know these devices well. If someone claims equivalence or superiority to your current devices,
you should ask for specific clinical evidence, not just marketing claims.

IMPORTANT RULES:
- Demand [TYPE:reference] format citations for ANY factual claims (trial names, data, specifications)
  Example: "What's your TICI 3 rate?" → Rep should respond with "[TRIAL:ThromVe2023] showed 73% TICI 3"
- Stay in character as a busy, experienced physician
- Be realistic - you're open to new products IF properly justified
- Don't make up specific trial data you don't know - ask the rep for it
- Reference your hospital's protocols, GPO contracts, and clinical team preferences
- Acknowledge tradeoffs: new product might be better in one way but worse in another

CLOSING STYLES YOU MIGHT USE (depending on how the call goes):
- If impressed: "Send me your latest trial data and we'll arrange a product demonstration"
- If skeptical: "I appreciate the call, but I need to see your recent comparative data"
- If formulary-blocked: "Our GPO contract prevents easy switching, but I'll keep your info"
- If genuinely interested: "Let's set up a formal evaluation - I'd like to see it in action"
- If not interested: "We're satisfied with our current approach, but thanks for reaching out"

{f'ADDITIONAL CONTEXT: {context}' if context else ''}

Remember: You are the PHYSICIAN, not the sales rep. You are skeptical, experienced, and focused on
what's best for your patients and your clinical workflow. You ask tough questions and demand evidence.
"""

    return prompt


def _format_device_stack(current_stack: Dict[str, str]) -> str:
    """Format the current device stack for readability."""
    if not current_stack:
        return "  (No specific devices listed)"

    lines = []
    for device_type, device_name in current_stack.items():
        if device_name:
            # Format the device type nicely (stent_retriever -> Stent Retriever)
            formatted_type = device_type.replace("_", " ").title()
            lines.append(f"  - {formatted_type}: {device_name}")

    return "\n".join(lines) if lines else "  (No specific devices listed)"


def _get_competitors(rep_company: str) -> list:
    """Get list of competitor companies."""
    competitors_map = {
        "stryker": ["Medtronic", "Penumbra", "Cerenovus", "Microvention"],
        "medtronic": ["Stryker", "Penumbra", "Cerenovus", "Microvention"],
        "penumbra": ["Stryker", "Medtronic", "Cerenovus"],
        "cerenovus": ["Stryker", "Medtronic", "Penumbra", "Microvention"],
        "microvention": ["Stryker", "Medtronic", "Cerenovus"],
    }
    return competitors_map.get(rep_company.lower(), [])


def _format_competitive_context(rep_company: str, competitors: list) -> str:
    """Format competitive context into readable statement."""
    if not competitors:
        return ""

    competitors_text = ", ".join(competitors)
    return f"Main competitors in your market: {competitors_text}"


def _format_personality(traits: Dict[str, float]) -> str:
    """Format personality traits into readable description."""
    descriptions = []

    if traits.get("evidence_driven", 0) > 0.7:
        descriptions.append("evidence-driven")
    if traits.get("innovative", 0) > 0.7:
        descriptions.append("open to innovation")
    if traits.get("cautious", 0) > 0.7:
        descriptions.append("cautious")
    if traits.get("cost_conscious", 0) > 0.7:
        descriptions.append("cost-conscious")
    if traits.get("loyal", 0) > 0.7:
        descriptions.append("loyal to current vendors")
    if traits.get("learning_oriented", 0) > 0.7:
        descriptions.append("eager to learn")

    if descriptions:
        return ", ".join(descriptions)
    return "professional and experienced"


def get_conversation_starter(physician_profile: Dict[str, Any], rep_company: str) -> str:
    """
    Generate a realistic opening for a competitive sales call.

    Args:
        physician_profile: The physician's profile
        rep_company: The sales rep's company

    Returns:
        A realistic opening line the physician might use
    """
    name = physician_profile.get("name", "Dr. Unknown")
    openings = [
        f"Hi, this is {name} speaking. What can I help you with?",
        f"Good afternoon, it's {name}. I have a few minutes - what's this about?",
        f"{name} here. I'm in the middle of cases, so make it quick.",
        f"This is {name}. How did you get my number? What are you selling?",
        f"{name} on the line. I'm listening, but I'm busy.",
    ]
    return openings[hash(rep_company) % len(openings)]


def get_challenge_prompt(
    physician_profile: Dict[str, Any],
    rep_company: str,
    rep_claim: str
) -> str:
    """
    Generate a challenge prompt when the physician wants to question a rep's claim.

    Args:
        physician_profile: The physician's profile
        rep_company: The sales rep's company
        rep_claim: The claim being made by the rep

    Returns:
        A prompt directing the AI to challenge the claim appropriately
    """
    name = physician_profile.get("name", "Dr. Unknown")
    evidence_driven = physician_profile.get("personality_traits", {}).get("evidence_driven", 0.5)

    if evidence_driven > 0.7:
        return f"""As {name}, you've just heard this claim from the {rep_company} rep:
"{rep_claim}"

This is a factual claim that requires evidence. Ask them specifically:
- What trial data supports this?
- What's the sample size and patient population?
- How does this compare to your current devices?
- Do you have a [TRIAL:name] citation for this?

Don't accept vague answers. Push for specific, verifiable data."""
    else:
        return f"""As {name}, you've heard this claim from the {rep_company} rep:
"{rep_claim}"

You're skeptical but not rigid. Ask clarifying questions:
- How have you seen that work in practice?
- Does that apply to [specific clinical scenario]?
- Is there data supporting that?

You want practical answers, not just marketing talk."""


def get_closing_scenario(
    physician_profile: Dict[str, Any],
    rep_company: str,
    conversation_quality: str = "mixed"
) -> str:
    """
    Generate a closing scenario based on conversation quality.

    Args:
        physician_profile: The physician's profile
        rep_company: The sales rep's company
        conversation_quality: 'strong', 'weak', or 'mixed'

    Returns:
        A closing prompt reflecting the conversation outcome
    """
    name = physician_profile.get("name", "Dr. Unknown")
    loyalty = physician_profile.get("personality_traits", {}).get("loyal", 0.5)

    closings = {
        "strong": f"""The rep from {rep_company} has made a compelling case. You're interested.

As {name}, you might say:
"You've given me some good information. Send me your latest clinical data and let's
talk about a formal evaluation. I'd like to see the device in action in a case."

OR if you're just being polite:
"I appreciate the pitch. We'll review your materials and I'll discuss with the team."

Stay realistic - don't commit to more than a next step.""",

        "weak": f"""The rep from {rep_company} didn't address your key concerns well. You're not impressed.

As {name}, you might say:
"I appreciate you calling, but you haven't really addressed my concerns about [specific issue].
Our current approach works well. Send your data and maybe we'll revisit this in the future."

Or: "I'm committed to my current vendor. Unless you can show me significant clinical advantage,
there's no compelling reason to switch."

Be firm but professional.""",

        "mixed": f"""The conversation was productive but not conclusive. You're interested but cautious.

As {name}, you might say:
"You've got some interesting data. I'd like to see your recent trials and get more specifics
on [device X]. If you can send that, we can set up a demo with my team."

Or: "I have to be honest - I'm not sure this is better than what I have, but it's worth evaluating.
Let's schedule a proper product demonstration."

Keep it open but honest.""",
    }

    return closings.get(conversation_quality, closings["mixed"])
