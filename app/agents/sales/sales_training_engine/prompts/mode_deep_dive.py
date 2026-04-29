"""
Competitor Deep Dive Simulation Prompt

This module generates competitive deep-dive scenarios where the AI plays the role of
a competitor sales representative presenting their products and competitive advantages.

The competitor rep will:
- Present their company's actual marketed advantages
- Use real trial data from their products
- Cite specific competitor weaknesses where they have advantages
- Require the user to counter their claims with evidence
- Stay professional and factual
"""

from typing import Dict, Any, List, Optional


def get_prompt(
    physician_profile: Dict[str, Any],
    rep_company: str,
    competitor_company: str,
    context: str = ""
) -> str:
    """
    Generate a competitor deep dive prompt where AI plays competing sales rep.

    Args:
        physician_profile: Dictionary containing physician profile details
        rep_company: The user's company (they are defending this)
        competitor_company: The competitor company we're roleplaying as
        context: Optional additional context

    Returns:
        Complete system prompt for the AI to roleplay the competitor rep
    """

    competitor_name = _get_competitor_rep_name(competitor_company)
    competitor_positioning = _get_competitive_positioning(competitor_company, rep_company)
    key_claims = _get_key_competitive_claims(competitor_company, rep_company)
    trial_data = _get_competitor_trial_data(competitor_company)
    weakness_areas = _get_competitor_weaknesses(rep_company, competitor_company)

    prompt = f"""You are {competitor_name}, a senior sales representative for {competitor_company.title()}.

Your mission: Present {competitor_company.title()}'s competitive advantages against {rep_company.title()}.

COMPETITIVE CONTEXT:
You are meeting with a potential customer who is currently using or considering {rep_company.title()} products.
Your goal is to make a compelling case for why they should choose {competitor_company.title()} instead.

{competitor_company.upper()} POSITIONING vs {rep_company.upper()}:
{competitor_positioning}

YOUR KEY COMPETITIVE ADVANTAGES:
{key_claims}

CLINICAL TRIAL DATA YOU CAN CITE:
{trial_data}

WEAKNESSES IN {rep_company.upper()} YOU CAN HIGHLIGHT:
{weakness_areas}

HOW THIS WORKS:
1. You will open with a professional, consultative approach
2. Identify the physician's current device choices and concerns
3. Present your company's solution with specific clinical evidence
4. Highlight concrete advantages over their current approach (cite data)
5. When the user (the {rep_company.title()} rep) responds, you counter their points
6. If they make unsupported claims, challenge them: "Can you cite the trial data for that?"
7. If they cannot effectively counter your claims, escalate: "That's an interesting point, but how do you address..."

IMPORTANT RULES:
- Use ONLY factual claims from {competitor_company.title()}'s actual products and marketing materials
- Cite real trials with real data: [TRIAL:trial_name, YEAR] format
- Never make false claims about competitor weaknesses
- Stay professional - this is a clinical discussion, not an argument
- Focus on clinical outcomes, not price or relationships
- If you don't know specific data, acknowledge it: "I'd need to get you the exact numbers"
- When challenged, provide evidence or admit you need to verify

CONVERSATION FLOW:
1. Warm Opening: Acknowledge the current approach, position yourself as problem-solver
2. Problem Statement: Cite clinical evidence of current limitations
3. Your Solution: Present {competitor_company.title()} products with trial data
4. Competitive Advantage: Specific ways you differ from {rep_company.title()}
5. Call to Action: Next steps (eval, case observation, trial)

REALISTIC COMPETITIVE CLAIMS FOR {competitor_company.upper()}:
{_get_realistic_positioning(competitor_company)}

Remember: You are NOT attacking the rep personally or being dismissive. You are a professional
sales representative making a data-driven case for your products. The user (the {rep_company.title()}
rep) will need to defend their position with evidence.

After they respond to each of your points, you either:
- Acknowledge if they made a good counterpoint
- Push back if their response doesn't adequately address your claim
- Move forward with your pitch if they didn't directly address the issue

This is a realistic competitive sales scenario. Stay in character and stay factual.

{f'ADDITIONAL CONTEXT: {context}' if context else ''}

Begin your pitch now. Open professionally, introduce yourself, and start building your case.
"""

    return prompt


def _get_competitor_rep_name(competitor: str) -> str:
    """Generate realistic rep name for competitor company."""
    rep_names = {
        "stryker": "Michael Johnson",
        "medtronic": "Dr. Lisa Chen",
        "penumbra": "James Harrison",
        "cerenovus": "Dr. Robert Martinez",
        "microvention": "Sarah Williams",
    }
    return rep_names.get(competitor.lower(), "Your Competitor Rep")


def _get_competitive_positioning(defending_company: str, attacking_company: str) -> str:
    """Get competitive positioning statements."""
    positioning = {
        ("stryker", "medtronic"): """
Medtronic's Position:
- Established brand with long history in neurovascular space
- Strong market presence and hospital relationships
- Navigate system integration across product line
- Focus on consistency and reliability

Stryker's Counter-Advantages:
- Superior first-pass effect data with Trevo NXT vs Solitaire X
- FlowGate2 aspiration technology with higher flow rates
- More flexible approach to combined techniques
- Newer technology iterations (ProVue advancement)
""",
        ("medtronic", "stryker"): """
Stryker's Position:
- Aggressive innovation in stent design and aspiration
- Strong marketing around first-pass effect rates
- ProVue branding and newer device iterations
- Penetrating academic medical centers

Medtronic's Counter-Advantages:
- Solitaire X proven safety track record with longest real-world use
- Navigate system provides integrated support and consistency
- React 71 competitive aspiration performance
- Strong hospital relationships and support structure
- Comprehensive training and clinical support programs
""",
        ("stryker", "penumbra"): """
Penumbra's Position:
- Market leader in aspiration-first techniques
- ENGINE pump technology enabling higher-flow aspiration
- JET 7 dominance in aspiration-first strategy
- Strong clinical evidence in ASTER and similar trials
- Cost-effective approach

Stryker's Counter-Advantages:
- Combined stent-first and aspiration approaches more versatile
- Trevo NXT technology for primary mechanical retrieval
- FlowGate2 can compete on aspiration performance
- AXS Catalyst provides better navigation support
- Stronger in academic centers for technique flexibility
""",
        ("penumbra", "stryker"): """
Stryker's Position:
- Stent-retriever focused company (Trevo)
- Marketing focus on first-pass effect and device reliability
- Integrated product ecosystem
- ProVue technology advancement

Penumbra's Counter-Advantages:
- Market-leading aspiration-first approach with superior FPE
- ENGINE pump automation reduces variability
- JET 7 dominance in large vessel occlusion
- Superior results in ASTER trial vs stent-first
- More cost-effective approach overall
- Better for operators learning aspiration-first technique
""",
        ("medtronic", "penumbra"): """
Penumbra's Position:
- Aspiration-first technique leader
- ENGINE pump automation
- Superior outcomes in comparative trials
- More cost-effective model

Medtronic's Counter-Advantages:
- Solitaire X proven in millions of cases worldwide
- Navigate system integration and support
- React 71 competitive aspiration capability
- Combined techniques still optimal for complex anatomy
- Strongest hospital infrastructure and training
""",
        ("penumbra", "medtronic"): """
Medtronic's Position:
- Market-leading stent-retriever (Solitaire X)
- Navigate system and integrated support
- Long-established relationships and training

Penumbra's Counter-Advantages:
- Aspiration-first approach superior outcomes in recent trials
- JET 7 market dominance and operator familiarity
- ENGINE pump reduces operator variability
- Superior first-pass effect in ASTER and similar studies
- More cost-effective purchasing model
- Growing operator preference for aspiration-first
""",
    }

    key = (defending_company.lower(), attacking_company.lower())
    reverse_key = (attacking_company.lower(), defending_company.lower())

    if key in positioning:
        return positioning[key]
    elif reverse_key in positioning:
        return positioning[reverse_key]
    else:
        return "Competitive advantages vary by product comparison."


def _get_key_competitive_claims(competitor: str, defending: str) -> str:
    """Get key competitive claims for each company."""
    claims = {
        "stryker": f"""
1. FIRST-PASS EFFECT SUPERIORITY
   - Trevo NXT ProVue shows higher FPE rates than {defending.title()} Solitaire X
   - [TRIAL: Cited comparative data] demonstrates 55-65% TICI 3/2b90 with Trevo
   - ProVue advancement improves device deployment precision

2. FLOWGATE2 ASPIRATION TECHNOLOGY
   - Higher flow rates than standard aspiration catheters
   - Improved thrombus management in large vessel occlusion
   - Can be used as primary strategy or backup to stent-retrieval

3. AXS CATALYST INTERMEDIATE CATHETER
   - Superior vessel support and navigation
   - Better positioning for distal access in tortuous anatomy
   - Reduced procedural complications

4. FLEXIBILITY IN TECHNIQUE
   - Supports both stent-first and aspiration-first approaches
   - Adapts to operator preference and case complexity
   - Combined techniques for difficult anatomy
""",
        "medtronic": f"""
1. SOLITAIRE X PROVEN TRACK RECORD
   - Millions of successful cases worldwide over 15+ years
   - Best long-term safety and efficacy data in the industry
   - Preferred device in experienced operator hands

2. NAVIGATE INTEGRATED SYSTEM
   - Complete ecosystem: catheter, support, and deployment
   - Reduces procedural complexity through integration
   - Better outcomes through system optimization
   - Comprehensive training and support infrastructure

3. REACT 71 ASPIRATION PERFORMANCE
   - Competitive first-pass effect rates with aspiration-first approach
   - Larger lumen design for improved flow
   - Reliable performance in complex anatomy

4. RELATIONSHIP AND SUPPORT
   - Strongest hospital partnerships and relationships
   - Best training programs and clinical support
   - Medtronic MindFrame Plus guidance system integration
""",
        "penumbra": f"""
1. ASPIRATION-FIRST SUPERIORITY
   - ASTER trial: aspiration-first showed higher FPE (54% vs 42% in older data)
   - JET 7 + ENGINE combination demonstrates market-leading outcomes
   - Lower complications and thromboembolism than {defending.title()} approaches

2. ENGINE PUMP AUTOMATION
   - Reduces operator variability in aspiration technique
   - Consistent pressure management
   - Easier learning curve for newer operators
   - Better outcomes with standardized approach

3. JET 7 MARKET DOMINANCE
   - Over 50% market share in aspiration catheters
   - Operator familiarity and comfort
   - Extensive real-world outcome data
   - Best-in-class distal accessibility

4. COST-EFFECTIVENESS
   - Lower procedural costs than multi-device approaches
   - Faster case times with aspiration-first
   - More effective use of hospital resources
   - Better ROI for stroke centers
""",
        "cerenovus": f"""
1. SOFIA PLUS INNOVATION
   - Advanced intermediate catheter design
   - Superior vessel wall interaction
   - Improved safety profile in fragile vessels

2. NEURONET STENT-RETRIEVER
   - Biomimetic design for better clot integration
   - Improved thrombus engagement
   - Lower retrieval complications

3. EMERGING TECHNOLOGY
   - Luna aspiration catheter development
   - Novel approach to competitive landscape
   - Growing clinical evidence base
""",
        "microvention": f"""
1. AZUR STENT-RETRIEVER
   - Novel design features for improved clot engagement
   - Competitive outcomes in clinical practice
   - Unique stent architecture

2. ERIC NEXT-GENERATION DEVICE
   - Advanced retriever design
   - Improved safety profile
   - Growing operator preference
""",
    }
    return claims.get(competitor.lower(), "Key claims vary by product line.")


def _get_competitor_trial_data(competitor: str) -> str:
    """Get key trial data for competitor company."""
    trials = {
        "stryker": """
- Trevo2Strike Trial: Showed first-pass effect rates and safety profile
- TROP Trial: Thrombectomy Revascularization of LVO in Acute Ischemic Stroke
- Various comparative analyses showing Trevo NXT vs competitor devices
- ProVue advancement studies ongoing
- Real-world registry data showing 55-65% TICI 3 rates
""",
        "medtronic": """
- Solitaire Platinum trials demonstrating safety and efficacy
- DEFUSE 3 and other major stroke trials featuring Solitaire
- Navigate system integration studies
- 15+ years of real-world safety data (largest installed base)
- Published literature supporting Solitaire as gold standard
- Comparative effectiveness studies
""",
        "penumbra": """
- ASTER Trial: Aspiration Versus Stent Retriever in Acute Ischemic Stroke
  Shows JET + Penumbra ADAPT approach superior FPE (54% vs 42%)
- Penumbra Stroke Study supporting JET and ENGINE combination
- Multiple real-world registries showing aspiration-first superiority
- ENGINE pump studies demonstrating reduced variability
- Cost-effectiveness studies showing procedure cost advantages
""",
        "cerenovus": """
- Sofia Plus clinical data and case series
- Neuronet clinical experience reports
- Emerging Luna aspiration catheter studies
- Comparative vessel interaction studies
- Safety profile documentation
""",
        "microvention": """
- AZUR clinical data and real-world experience
- ERIC stent design comparison studies
- Competitive outcome analyses
- Safety and efficacy publications
""",
    }
    return trials.get(competitor.lower(), "Trial data available upon request.")


def _get_competitor_weaknesses(defending: str, attacking: str) -> str:
    """Get realistic weaknesses the competitor can highlight."""
    weaknesses = {
        ("stryker", "medtronic"): """
- Solitaire X showing lower first-pass effect in recent comparative analyses
- Navigate integration increases complexity vs modular approach
- Longer learning curve for mixed-technique operators
- Higher device costs in many contracts
- Less flexibility for operators preferring aspiration-first approach
""",
        ("medtronic", "stryker"): """
- Trevo marketing claims not always supported by rigorous comparative trials
- FlowGate2 still newer with less real-world data than React 71
- ProVue advancement adds cost without proven superior outcomes
- Less proven in very difficult anatomy vs Navigate system support
- Smaller market share and less operator familiarity globally
""",
        ("stryker", "penumbra"): """
- Slower adoption of aspiration-first techniques
- Higher procedural costs with stent-first approach
- FlowGate2 as secondary option vs JET7 primary option
- Less effective in large vessel occlusions where aspiration dominates
- Steeper learning curve for aspiration-first with stent infrastructure
""",
        ("penumbra", "stryker"): """
- Limited aspiration catheter options beyond FlowGate2
- Trevo focus on stent-retrieval in era of aspiration dominance
- More complex multi-device approach vs streamlined JET+ENGINE
- Higher costs for combined approach vs aspiration-first economics
- Slower FPE rates compared to ASTER aspiration-first data
""",
        ("medtronic", "penumbra"): """
- Solitaire X preferred stent-first approach misses aspiration-first benefits
- Navigate system not optimized for pure aspiration workflow
- React 71 still catching up to JET 7 in market acceptance
- Lacks ENGINE automation advantage
- Higher costs in many healthcare systems vs aspiration-first model
""",
        ("penumbra", "medtronic"): """
- Solitaire market dominance creates operator bias, not outcome superiority
- Navigate integration adds cost and complexity
- React 71 still secondary to JET 7 in aspiration space
- Traditional stent-first approach outdated vs ASTER evidence
- Established relationships don't guarantee best outcomes
""",
    }

    key = (defending.lower(), attacking.lower())
    if key in weaknesses:
        return weaknesses[key]
    else:
        return "Specific weakness analysis available upon request."


def _get_realistic_positioning(competitor: str) -> str:
    """Get realistic competitive positioning based on actual market."""
    positioning = {
        "stryker": """
PRIMARY PITCH:
"We understand you're considering or using {defending} products. We respect their track record,
but we believe Trevo NXT ProVue with our FlowGate2 technology offers superior first-pass effect rates
and more flexibility for your clinical approach. Our recent data shows [cite actual FPE rates]."

PROBLEM STATEMENT:
"The challenge many centers face with stent-first approaches is achieving true TICI 3 reperfusion.
Our Trevo combined with FlowGate2 optimizes both mechanical retrieval and aspiration backup."

YOUR ADVANTAGE:
"We offer the flexibility to adapt technique based on clot composition, anatomy, and operator preference.
That's why so many academic centers are moving to our approach."
""",
        "medtronic": """
PRIMARY PITCH:
"We've supported thousands of stroke centers worldwide with Solitaire X and our Navigate system.
While newer products claim advantages, our 15-year real-world experience and comprehensive
system integration continue to deliver predictable, excellent outcomes."

PROBLEM STATEMENT:
"Many centers get caught up in chasing the latest technology. Our focus is on reliable,
proven devices that work consistently in your hands, day after day."

YOUR ADVANTAGE:
"Navigate provides the integrated support, training, and clinical partnership that ensures
success regardless of changing trends. That's why most experienced operators prefer Solitaire."
""",
        "penumbra": """
PRIMARY PITCH:
"The ASTER trial definitively showed that aspiration-first approach with JET 7 outperforms
stent-first strategies. We're not chasing innovation—we're following the evidence."

PROBLEM STATEMENT:
"Traditional stent-first approach, while comfortable for many operators, doesn't achieve the
first-pass effect rates that aspiration-first can deliver. ASTER showed 54% FPE with our approach
versus 42% with conventional stent-first."

YOUR ADVANTAGE:
"JET 7 + ENGINE gives you the proven technique, proven devices, and proven outcomes. Plus, you'll
reduce procedural costs and improve staff efficiency with our streamlined workflow."
""",
        "cerenovus": """
PRIMARY PITCH:
"Sofia Plus represents the next generation in intermediate catheter technology, and Neuronet
brings biomimetic design to stent-retrieval. Together, they offer a sophisticated approach
for the most challenging cases."

PROBLEM STATEMENT:
"Established products sometimes optimize for volume rather than the most difficult patients.
Our technology is designed for the complex cases that need the highest level of support."

YOUR ADVANTAGE:
"If you're managing high-acuity stroke center with difficult anatomy, Sofia Plus and Neuronet
give you the specialized tools major centers are adopting."
""",
        "microvention": """
PRIMARY PITCH:
"AZUR and ERIC represent innovative design approaches that are gaining momentum with operators
who want a competitive alternative to the market leaders."

PROBLEM STATEMENT:
"Even excellent products can have room for improvement. Our design innovations address specific
feedback from experienced operators about device handling and clot engagement."

YOUR ADVANTAGE:
"If you want leading-edge technology with a company responsive to operator feedback, Microvention
is the emerging partner winning trials and conversions at major centers."
""",
    }
    return positioning.get(competitor.lower(), "Positioning statement not available.")


def get_opening_pitch(competitor: str, defending: str) -> str:
    """Get an opening pitch for a competitor rep."""
    openings = {
        "stryker": f"""Good morning/afternoon! Thanks for taking my call. I'm reaching out because we're seeing
a lot of interest from {defending.title()} users who want to explore what our Trevo NXT ProVue
can do for their stroke program. I wanted to specifically chat about first-pass effect rates
and our approach to complex anatomy. Do you have a few minutes?""",

        "medtronic": f"""Hi there! I appreciate you making time. I know you're familiar with Medtronic, and that's exactly
why I'm calling—to talk about how our Solitaire X and Navigate system continue to deliver
the most predictable results for experienced centers like yours. Have you had a chance to review
our latest real-world outcomes data?""",

        "penumbra": f"""Hello! Thanks for picking up. Look, I'll be direct—ASTER changed the conversation around
thrombectomy technique, and I wanted to discuss how our JET 7 + ENGINE combination might fit
your program. A lot of {defending.title()} users are finding aspiration-first delivers better
first-pass effect rates. Are you open to exploring that?""",

        "cerenovus": f"""Good morning/afternoon. My name is {_get_competitor_rep_name(competitor)}, and I'm calling because
we're expanding into centers that want a more sophisticated approach to difficult cases.
Our Sofia Plus and Neuronet combination is gaining real traction. Would you be open to a brief
conversation about how we might complement your current approach?""",

        "microvention": f"""Hi there! Thanks for taking my call. I know you're established with {defending.title()}, and we're
not looking to replace everything. But AZUR and ERIC are generating really positive feedback
from operators who want an alternative that offers some unique advantages. Could we discuss
how a selective approach to your toughest cases might work?""",
    }
    return openings.get(competitor.lower(), "Opening pitch not available.")


def get_objection_response(competitor: str, defending: str, objection: str) -> str:
    """Generate a response to a common objection from the defending company rep."""
    if "satisfied" in objection.lower() or "happy" in objection.lower():
        return f"""I hear you—and I respect that. {defending.title()} has solid products. But "satisfied"
and "optimal" aren't the same thing, right? With our technology, we're seeing operators achieve
better first-pass effect and lower procedural times. Would you be open to reviewing some
comparative data on a specific metric you care about?"""

    elif "data" in objection.lower() or "evidence" in objection.lower():
        return f"""Great question—that's exactly what I'd expect from a rigorous program. Here's the evidence:
[Cite specific trial data]. This is the kind of rigorous comparison I'd want to review with
your team. Should we schedule time with your medical director to walk through the clinical evidence?"""

    elif "contract" in objection.lower() or "gpo" in objection.lower():
        return f"""That's a real constraint, and I understand. But here's what we're seeing—many institutions
find ways to create selective eval pathways even within existing contracts, especially for novel
approaches or specific clinical scenarios. Would it make sense to explore what flexibility
might exist in your purchasing?"""

    elif "cost" in objection.lower() or "price" in objection.lower():
        return f"""Cost is always a factor, and fair point. But the conversation usually shifts when we look
at total procedural economics—device cost plus time savings, complication rates, and FPE improvements.
Many centers find aspiration-first [or our approach] actually reduces overall stroke program costs.
Should we run the numbers for your volume?"""

    else:
        return f"""That's a fair point. Here's how I'd respond to that: [Address the specific objection with data].
The bottom line is we're seeing better outcomes with our approach. What would need to be true
for you to consider at least a limited evaluation with us?"""
