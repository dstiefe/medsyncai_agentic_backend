"""
Product Knowledge Assessment Simulation Prompt

This module generates knowledge assessment scenarios where the AI plays the role of
an examiner (physician or product specialist) testing a sales representative's product knowledge.

The examiner will:
- Ask progressively harder questions
- Start with basic specifications, advance to clinical evidence
- Require specific citations for factual claims
- Score answers as correct/partially correct/incorrect
- Provide immediate feedback and move to next question
"""

from typing import Dict, Any, List, Optional


def get_prompt(
    physician_profile: Dict[str, Any],
    rep_company: str,
    context: str = ""
) -> str:
    """
    Generate a product knowledge assessment prompt.

    Args:
        physician_profile: Dictionary containing physician profile details
        rep_company: The sales rep's company being tested
        context: Optional additional context

    Returns:
        Complete system prompt for the AI to conduct knowledge assessment
    """

    name = physician_profile.get("name", "Unknown")
    specialty = physician_profile.get("specialty", "")
    hospital_type = physician_profile.get("hospital_type", "")
    experience_years = physician_profile.get("experience_years", 0)
    evidence_driven = physician_profile.get("personality_traits", {}).get("evidence_driven", 0.7)

    company_products = _get_company_products(rep_company)
    key_devices = _get_key_devices(rep_company)

    prompt = f"""You are {name}, a {specialty} physician at a {hospital_type} with {experience_years} years of experience.

You are administering a formal product knowledge assessment for a sales representative from {rep_company.title()}.

ASSESSMENT STRUCTURE:
You will ask 10 progressively difficult questions about {rep_company.title()}'s products.

QUESTION DIFFICULTY PROGRESSION:
1. Basic Specifications (Q1-3): Dimensions, materials, design features, technical specs
   Example: "What's the delivery sheath diameter of your stent retriever?"

2. System Compatibility (Q4-5): How products work together, nesting, sizing
   Example: "What's the maximum outer diameter of your intermediate catheter?"

3. Clinical Evidence (Q6-7): Trial names, study data, indications, outcomes
   Example: "What's the TICI 3 rate from your pivotal trial?"

4. Competitive Comparisons (Q8): How they compare to specific competitors
   Example: "How does your first-pass effect rate compare to the Stryker Trevo?"

5. Edge Cases & Advanced (Q9-10): Off-label use, adverse events, contraindications
   Example: "What's your experience with tortuous vessel access in posterior circulation?"

KEY {rep_company.upper()} PRODUCTS YOU'LL TEST THEM ON:
{_format_product_list(company_products)}

SCORING RULES:
For each answer, score as:
- CORRECT (✓): Factual accuracy, includes specific data/evidence, cites trial names if appropriate
- PARTIALLY CORRECT (~): Mostly accurate but missing details, vague on data, doesn't cite sources
- INCORRECT (✗): Factual error, unsupported claim, refusal to answer, or deflection

CITATION REQUIREMENTS:
For any factual claim about clinical data, require [TRIAL:trial_name] or [DATA:source] format.
Example: "That's interesting - what trial data supports that?" → "The TICI 3 rate was 73% in [TRIAL:ASTER2020]"

If they cannot cite a source, mark as PARTIALLY CORRECT and note the gap.

ASSESSMENT FLOW:
1. Introduce yourself and the assessment purpose
2. Ask Question 1 (basic spec)
3. Wait for their response
4. Score immediately with brief feedback
5. Move to Question 2
6. Continue through all 10 questions
7. After Q10, provide a comprehensive summary

SAMPLE QUESTIONS BY CATEGORY:
{_format_sample_questions(rep_company)}

YOUR DEMEANOR:
- Professional and fair, but thorough
- Don't accept vague answers without follow-up
- Push for specifics: "Can you give me the actual number?"
- Reference your clinical experience: "In our experience with..."
- Be appropriately challenging - a physician should expect any good rep to know these answers
- If they don't know something, note it as a knowledge gap
- Escalate difficulty if they're answering too easily; back off if they're struggling badly

AFTER 10 QUESTIONS, PROVIDE SUMMARY:
```
KNOWLEDGE ASSESSMENT SUMMARY FOR [REP NAME]
==========================================
Overall Knowledge Score: [0-100]
Attempt 1 Date: [today]

PERFORMANCE BY CATEGORY:
- Basic Specifications: [# correct]/3
- System Compatibility: [# correct]/2
- Clinical Evidence: [# correct]/2
- Competitive Comparisons: [# correct]/1
- Edge Cases & Advanced: [# correct]/2

STRENGTHS:
- [Area where they demonstrated strong knowledge]
- [Specific topics they knew well]

KNOWLEDGE GAPS:
- [Area needing improvement]
- [Specific products or data they didn't know]
- [Clinical evidence they couldn't cite]

RECOMMENDATIONS:
- [Specific training recommendations]
- [Products to study]
- [Clinical trials to review]

NOTES:
[Any additional observations about their knowledge, communication, or professional approach]
```

{f'ADDITIONAL CONTEXT: {context}' if context else ''}

Start the assessment now with a professional introduction and your first question.
Keep your questions specific and testable. Be fair but thorough.
"""

    return prompt


def _get_company_products(company: str) -> Dict[str, List[str]]:
    """Get product listings for a company by category."""
    products = {
        "stryker": {
            "stent_retrievers": ["Trevo NXT ProVue", "Trevo6", "Trevo XP"],
            "aspiration_catheters": ["FlowGate2", "FlowGate"],
            "intermediate_catheters": ["AXS Catalyst 7", "SOFIA Plus"],
            "distal_access": ["Excelsior SL-10", "Synchro2 microwire"],
            "pumps_systems": ["Not primary focus"],
        },
        "medtronic": {
            "stent_retrievers": ["Solitaire X", "Solitaire Platinum"],
            "aspiration_catheters": ["React 71", "MindFrame Plus"],
            "intermediate_catheters": ["Rebar 18", "Rebar 27"],
            "distal_access": ["Phenom 21", "Phenom 27"],
            "navigators": ["Rist 071 microwire"],
        },
        "penumbra": {
            "aspiration_catheters": ["JET 7", "ACE 64", "RED 72"],
            "intermediate_catheters": ["Neuron MAX 088", "BENCHMARK"],
            "pumps": ["ENGINE", "ALCiS"],
            "microcatheters": ["Velocity", "PX Slim"],
        },
        "cerenovus": {
            "stent_retrievers": ["Neuronet", "Embotrap II"],
            "intermediate_catheters": ["Sofia Plus"],
            "aspiration": ["Luna aspiration catheter"],
        },
        "microvention": {
            "stent_retrievers": ["AZUR", "ERIC"],
            "intermediate_catheters": ["Fubra", "Fubra Plus"],
        },
    }
    return products.get(company.lower(), {})


def _get_key_devices(company: str) -> List[str]:
    """Get the flagship/key devices for a company."""
    key_devices = {
        "stryker": ["Trevo NXT ProVue", "FlowGate2", "AXS Catalyst 7"],
        "medtronic": ["Solitaire X", "React 71", "Rebar 18"],
        "penumbra": ["JET 7", "ENGINE", "Neuron MAX"],
        "cerenovus": ["Sofia Plus", "Neuronet"],
        "microvention": ["AZUR", "Fubra Plus"],
    }
    return key_devices.get(company.lower(), [])


def _format_product_list(products: Dict[str, List[str]]) -> str:
    """Format product categories for readability."""
    lines = []
    for category, devices in products.items():
        if devices and devices[0] != "Not primary focus":
            formatted_cat = category.replace("_", " ").title()
            device_list = ", ".join(devices)
            lines.append(f"  • {formatted_cat}: {device_list}")
    return "\n".join(lines) if lines else "  (Product list not available)"


def _format_sample_questions(company: str) -> str:
    """Format sample questions by company and category."""
    sample_questions = {
        "stryker": """
BASIC SPECIFICATIONS:
1. "What's the delivery sheath diameter of your Trevo NXT ProVue stent retriever?"
2. "What are the sizes available for your AXS Catalyst 7 intermediate catheter?"
3. "Walk me through the FlowGate2 design - what makes it different from standard aspiration catheters?"

SYSTEM COMPATIBILITY:
4. "If I'm using your AXS Catalyst 7, what's the maximum OD device I can nest inside it?"
5. "How does your distal access strategy work with posterior circulation cases?"

CLINICAL EVIDENCE:
6. "What was your TICI 3 rate in the pivotal trial data you have?"
7. "Do you have any recent comparative data on first-pass effect rates?"

COMPETITIVE COMPARISON:
8. "How does your first-pass effect compare to the Medtronic Solitaire X?"

EDGE CASES:
9. "What's your experience with highly calcified vessels and device navigation?"
10. "Have there been any reported kinking issues with your stent retrievers in tortuous anatomy?"
""",
        "medtronic": """
BASIC SPECIFICATIONS:
1. "What are the diameter options for your Solitaire X stent retriever?"
2. "What's the delivery catheter size requirement for your Rebar 18?"
3. "Tell me about the Navigate compatibility - how does that work exactly?"

SYSTEM COMPATIBILITY:
4. "What devices nest inside your Rebar 18 intermediate catheter?"
5. "How does the full Medtronic stack integrate - from access to retrieval?"

CLINICAL EVIDENCE:
6. "What's your latest TICI 3 or modified TICI 3 outcome data?"
7. "Do you have trial data specifically for aspiration-first strategies with React 71?"

COMPETITIVE COMPARISON:
8. "How does your React 71 compare to the Penumbra JET 7 on thrombectomy completeness?"

EDGE CASES:
9. "What's your experience with posterior circulation thrombectomy using Solitaire?"
10. "Have you seen issues with air embolism management in your system?"
""",
        "penumbra": """
BASIC SPECIFICATIONS:
1. "What sizes does your JET 7 aspiration catheter come in?"
2. "What are the ENGINE pump's suction pressure ranges?"
3. "Explain the RED catheter line - what's the difference between sizes?"

SYSTEM COMPATIBILITY:
4. "How do your Neuron intermediate catheters work with different microcatheter types?"
5. "Walk me through the full system workflow using JET plus ENGINE - what's the setup?"

CLINICAL EVIDENCE:
6. "What was your first-pass effect rate with JET-based aspiration-first in recent trials?"
7. "Do you have comparative data on the ENGINE pump versus manual aspiration?"

COMPETITIVE COMPARISON:
8. "How does aspiration-first with JET compare to stent retriever-first approaches in published data?"

EDGE CASES:
9. "What's your success rate with posterior circulation cases using your JET system?"
10. "Have you encountered any issues with catheter stability during prolonged thrombectomy attempts?"
""",
    }
    return sample_questions.get(company.lower(), "SAMPLE QUESTIONS:\n  (Not available for this company)")


def get_question_progression(
    company: str,
    question_number: int
) -> Dict[str, str]:
    """
    Get a specific question for a given company and progression level.

    Args:
        company: The company name
        question_number: 1-10, the question sequence

    Returns:
        Dictionary with question, expected_answer_level, and scoring_guidance
    """
    questions_by_company = {
        "stryker": {
            1: {
                "question": "What's the delivery sheath diameter of your Trevo NXT ProVue stent retriever?",
                "category": "basic_specification",
                "expected_answer": "The Trevo NXT ProVue uses an 0.087-inch delivery catheter (2.7mm OD equivalent)",
                "scoring_guidance": "Accept 0.087\" or 2.7mm. If they mention 0.088\" accept it as close."
            },
            2: {
                "question": "What size intermediate catheters do you offer in your AXS Catalyst line?",
                "category": "basic_specification",
                "expected_answer": "AXS Catalyst comes in 6Fr and 7Fr sizes with varying lengths",
                "scoring_guidance": "Must mention at least 6Fr and 7Fr. Partial credit if they're not certain on all specs."
            },
            3: {
                "question": "Describe your FlowGate2 aspiration catheter - what's the design innovation?",
                "category": "basic_specification",
                "expected_answer": "FlowGate2 features a larger inner lumen and improved sealing for higher flow rates",
                "scoring_guidance": "Look for mention of larger lumen, flow rate improvement, or better seal."
            },
            4: {
                "question": "What's the maximum outer diameter device you can nest inside your AXS Catalyst 7?",
                "category": "system_compatibility",
                "expected_answer": "Approximately 0.060\" to 0.070\" distal access catheters",
                "scoring_guidance": "They should know typical nesting constraints or be able to reference a compatibility chart."
            },
            5: {
                "question": "Walk me through your recommended setup for a tortuous right ICA case.",
                "category": "system_compatibility",
                "expected_answer": "Typical approach: Guiding catheter > Catalyst intermediate > SL-10 + Synchro2",
                "scoring_guidance": "Should demonstrate understanding of system interaction and access strategy."
            },
            6: {
                "question": "What was your TICI 3 rate in the pivotal thrombectomy trial for Trevo NXT?",
                "category": "clinical_evidence",
                "expected_answer": "Should cite specific trial (e.g., Trevo2Strike, TROP, etc.) with TICI 3 percentage",
                "scoring_guidance": "Require [TRIAL:name] citation. Accept ±5% variance on the rate reported."
            },
            7: {
                "question": "Do you have first-pass effect data comparing stent-first versus aspiration-first with your devices?",
                "category": "clinical_evidence",
                "expected_answer": "Should cite specific trial data on technique comparison",
                "scoring_guidance": "Accept citations from published trials. If they say 'no data', that's incorrect."
            },
            8: {
                "question": "How does your Trevo first-pass effect rate compare to the Medtronic Solitaire X?",
                "category": "competitive_comparison",
                "expected_answer": "Should cite comparative trial data or acknowledge comparable rates with specific numbers",
                "scoring_guidance": "They should have recent comparative data or fair competitive positioning."
            },
            9: {
                "question": "What's your experience managing heavily calcified vessel cases with Trevo?",
                "category": "edge_case",
                "expected_answer": "Discussion of technique modifications, success rate, or specific device features for calcification",
                "scoring_guidance": "Looking for clinical depth and honest acknowledgment of technique modifications."
            },
            10: {
                "question": "Have you documented any stent kinking issues in tortuous anatomy? If so, how is that being addressed?",
                "category": "edge_case",
                "expected_answer": "Honest discussion of any known issues and design improvements to address them",
                "scoring_guidance": "Honesty and problem-solving approach matter more than perfect track record."
            }
        },
        "medtronic": {
            1: {
                "question": "What diameter options are available for your Solitaire X stent retriever?",
                "category": "basic_specification",
                "expected_answer": "Solitaire X comes in 4x20mm and 6x25mm configurations",
                "scoring_guidance": "Accept both sizes. If they mention legacy sizes, note but accept."
            },
            2: {
                "question": "What's the typical delivery catheter compatibility for your Rebar 18 intermediate catheter?",
                "category": "basic_specification",
                "expected_answer": "Rebar 18 typically uses 0.070\" or 0.088\" delivery catheters",
                "scoring_guidance": "Should know typical sizes that work with their system."
            },
            3: {
                "question": "What's the core innovation in your React 71 aspiration catheter?",
                "category": "basic_specification",
                "expected_answer": "Increased lumen size for improved flow, better sealing, faster debulking",
                "scoring_guidance": "Should mention improved aspiration efficiency or flow rate."
            },
            4: {
                "question": "Can you walk me through the nesting options with Rebar 18 and your distal access catheter?",
                "category": "system_compatibility",
                "expected_answer": "Specific nesting compatibility with Phenom and other distal access options",
                "scoring_guidance": "Should demonstrate knowledge of compatible combinations."
            },
            5: {
                "question": "How does your Navigate system integrate with the Solitaire for improved outcomes?",
                "category": "system_compatibility",
                "expected_answer": "Navigate provides enhanced support, stability, and improved device delivery",
                "scoring_guidance": "Should articulate the added value of the complete system."
            },
            6: {
                "question": "What's your TICI 3 rate from recent Solitaire clinical data? Cite the specific trial.",
                "category": "clinical_evidence",
                "expected_answer": "[TRIAL:trial_name] reported X% TICI 3 rate",
                "scoring_guidance": "Require trial citation. Numbers should be recent (2020+)."
            },
            7: {
                "question": "Do you have trial data on React 71 aspiration-first outcomes?",
                "category": "clinical_evidence",
                "expected_answer": "Should cite specific trial data with first-pass effect or TICI rates",
                "scoring_guidance": "Accept published trial citations with specific outcome metrics."
            },
            8: {
                "question": "How does React 71 compare to the Penumbra JET 7 in head-to-head studies?",
                "category": "competitive_comparison",
                "expected_answer": "Should reference comparative effectiveness data if available, or acknowledge competitive positioning",
                "scoring_guidance": "Honest competitive assessment with data backing preferred."
            },
            9: {
                "question": "What's your success rate in posterior circulation cases with the full Solitaire system?",
                "category": "edge_case",
                "expected_answer": "Discussion of technique modifications or access challenges in posterior circulation",
                "scoring_guidance": "Looking for clinical experience discussion."
            },
            10: {
                "question": "Any documented thromboembolism or air embolism issues specific to your system design? How are you addressing them?",
                "category": "edge_case",
                "expected_answer": "Honest discussion of safety profile and any design improvements",
                "scoring_guidance": "Transparency and problem-solving approach valued."
            }
        },
        "penumbra": {
            1: {
                "question": "What diameter sizes does your JET 7 aspiration catheter come in?",
                "category": "basic_specification",
                "expected_answer": "JET 7 comes in 7F size (and potentially other configurations)",
                "scoring_guidance": "Should know primary sizes and maybe mention RED alternatives."
            },
            2: {
                "question": "What are the pressure ranges for your ENGINE pump system?",
                "category": "basic_specification",
                "expected_answer": "ENGINE provides adjustable vacuum pressure (typically 0.3-1.0 atm equivalent)",
                "scoring_guidance": "Should know pressure ranges are adjustable and approximate values."
            },
            3: {
                "question": "Explain the difference between your JET, ACE, and RED aspiration catheter lines.",
                "category": "basic_specification",
                "expected_answer": "Different sizes, lengths, and optimal use cases (JET for large vessel, RED for distal, ACE for specific scenarios)",
                "scoring_guidance": "Should distinguish between the product lines and their intended uses."
            },
            4: {
                "question": "How do your Neuron intermediate catheters integrate with various microcatheter types?",
                "category": "system_compatibility",
                "expected_answer": "Neuron MAX and other sizes accommodate different microcatheter ODs for flexibility",
                "scoring_guidance": "Should know compatibility parameters."
            },
            5: {
                "question": "Walk me through the complete JET + ENGINE workflow from setup to thrombectomy.",
                "category": "system_compatibility",
                "expected_answer": "Detailed workflow explaining pump connection, aspiration setup, pressure management",
                "scoring_guidance": "Should demonstrate operational understanding of the full system."
            },
            6: {
                "question": "What's your first-pass effect rate with JET-based aspiration-first? Cite the trial.",
                "category": "clinical_evidence",
                "expected_answer": "[TRIAL:trial_name] reported X% first-pass effect with aspiration-first technique",
                "scoring_guidance": "Require specific trial citation with percentage data."
            },
            7: {
                "question": "Do you have comparative data on ENGINE pump versus manual aspiration outcomes?",
                "category": "clinical_evidence",
                "expected_answer": "Should cite trial data showing outcomes with ENGINE pump support",
                "scoring_guidance": "Accept published comparative data or acknowledge comparative positioning."
            },
            8: {
                "question": "How does aspiration-first with your JET compare to stent retriever-first in published head-to-head studies?",
                "category": "competitive_comparison",
                "expected_answer": "Should reference ASTER or similar comparative trials with data",
                "scoring_guidance": "Critical knowledge for competitive positioning."
            },
            9: {
                "question": "What's your success rate with posterior circulation thrombectomy using JET-based approach?",
                "category": "edge_case",
                "expected_answer": "Discussion of technique modifications and outcomes in posterior circulation",
                "scoring_guidance": "Clinical experience and data preferred."
            },
            10: {
                "question": "Any safety concerns with high-pressure aspiration in fragile vessels? How do you mitigate distal embolization?",
                "category": "edge_case",
                "expected_answer": "Discussion of pressure management, technique modifications, and safety data",
                "scoring_guidance": "Looking for understanding of risk profile and mitigation strategies."
            }
        }
    }

    company_lower = company.lower()
    if company_lower in questions_by_company and question_number in questions_by_company[company_lower]:
        return questions_by_company[company_lower][question_number]

    return {
        "question": f"Question {question_number} for {company}",
        "category": "general",
        "expected_answer": "Expected answer not defined",
        "scoring_guidance": "Assess accuracy, completeness, and citation of sources"
    }


def get_scoring_guidance(correct_answers: int, total_questions: int = 10) -> str:
    """
    Generate scoring guidance based on number of correct answers.

    Args:
        correct_answers: Number of correct answers out of total_questions
        total_questions: Total questions asked (default 10)

    Returns:
        Interpretation and recommendations based on score
    """
    percentage = (correct_answers / total_questions) * 100

    if percentage >= 90:
        return """
ASSESSMENT RESULT: EXCELLENT (90-100%)
This rep demonstrates comprehensive product knowledge. They knew:
- Technical specifications precisely
- System compatibility requirements
- Clinical trial data with citations
- Competitive positioning with evidence
Recommendation: This rep is well-prepared for advanced clinical discussions.
Minimal additional training needed - focus on edge cases and new trial data updates.
"""
    elif percentage >= 75:
        return """
ASSESSMENT RESULT: STRONG (75-89%)
This rep shows good foundational knowledge. They need:
- More detailed system integration knowledge
- Better trial data citation accuracy
- Competitive comparison preparation
Recommendation: Schedule refresher training on specific knowledge gaps identified above.
Good candidate for advanced clinical presentations.
"""
    elif percentage >= 60:
        return """
ASSESSMENT RESULT: ADEQUATE (60-74%)
This rep has basic knowledge but needs significant improvement:
- Trial data memorization and citation practice
- System compatibility training
- Product specification drill
Recommendation: Require training module completion before independent clinical presentations.
Schedule follow-up assessment in 2-4 weeks.
"""
    elif percentage >= 40:
        return """
ASSESSMENT RESULT: NEEDS IMPROVEMENT (40-59%)
This rep lacks sufficient product knowledge:
- Multiple gaps in technical specifications
- Unable to cite clinical evidence
- Weak understanding of system integration
Recommendation: Intensive product training required before unsupervised rep activities.
Pair with experienced mentor. Schedule formal retest before resuming full duties.
"""
    else:
        return """
ASSESSMENT RESULT: INADEQUATE (Below 40%)
This rep is not adequately trained on product knowledge:
- Significant knowledge gaps across all categories
- Cannot support clinical claims with evidence
- Requires fundamental product training
Recommendation: Remove from independent rep activities. Require comprehensive training program
completion before any clinical customer interactions. Retest mandatory after training.
"""
