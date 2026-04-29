"""
Assessment service for MedSync AI Sales Intelligence Platform.

Generates structured assessments from document chunks using LLM,
scores answers (MC direct comparison, write-in via LLM evaluation),
and persists results via JSON file storage.
"""

import json
import logging
import uuid
from datetime import datetime
from functools import lru_cache
from typing import Any, Dict, List, Optional

from ..services.data_loader import DataManager, get_data_manager
from ..services.llm_service import LLMService
from ..services.persistence_service import PersistenceService, get_persistence_service

logger = logging.getLogger(__name__)

# Categories for assessment questions
ASSESSMENT_CATEGORIES = [
    "specifications",
    "clinical_evidence",
    "ifu_regulatory",
    "competitive_knowledge",
    "procedure_workflow",
]

CATEGORY_LABELS = {
    "specifications": "Device Specifications",
    "clinical_evidence": "Clinical Evidence",
    "ifu_regulatory": "IFU & Regulatory",
    "competitive_knowledge": "Competitive Knowledge",
    "procedure_workflow": "Procedure Workflow",
}

# Difficulty-specific chunk selection and question complexity guidance
DIFFICULTY_GUIDANCE = {
    "beginner": {
        "description": "Basic device facts, simple indications, straightforward specs",
        "question_guidance": """Generate BEGINNER-level questions:
- Basic device names, categories, manufacturers
- Simple specifications (sizes, lengths, French gauges)
- Standard indications for each device
- Straightforward IFU boundaries (explicit contraindications)
- One clearly correct answer per multiple-choice question
- Write-in answers should be short (1-2 sentences)""",
        "source_types": ["ifu_document", "device_spec", "product_page"],
    },
    "intermediate": {
        "description": "Compatibility chains, clinical trial data, head-to-head comparisons",
        "question_guidance": """Generate INTERMEDIATE-level questions:
- Device compatibility chains (what fits inside what, clearances)
- Clinical trial data (DAWN, DEFUSE-3, ASTER, COMPASS, DIRECT)
- Head-to-head comparisons between competing devices
- Procedural workflow sequences
- Some questions may have nuanced answers
- Write-in answers should demonstrate understanding (2-4 sentences)""",
        "source_types": ["clinical_trial", "ifu_document", "device_spec", "competitive_analysis"],
    },
    "experienced": {
        "description": "Edge cases, adverse events, regulatory gray areas, complex workflows",
        "question_guidance": """Generate EXPERIENCED REP-level questions:
- Edge cases and off-label considerations
- Adverse event data from MAUDE reports
- Complex multi-device workflow optimization
- Regulatory gray areas and IFU boundary interpretation
- Literature interpretation (study design limitations, conflicting data)
- Questions should be challenging and require deep domain knowledge
- Include scenario-based questions""",
        "source_types": ["clinical_trial", "ifu_document", "adverse_event", "competitive_analysis", "device_spec"],
    },
}


ASSESSMENT_GENERATION_PROMPT = """You are MedSync AI Assessment Generator for neurovascular device sales representatives.

Generate a structured assessment exam with {question_count} questions across these categories:
{category_distribution}

{difficulty_guidance}

RULES:
- Each question MUST be answerable from the provided document chunks
- For multiple_choice: provide exactly 4 options with one correct answer
- For write_in: provide the ideal answer that would be considered correct
- For matching: provide 4-5 items on each side
- Mix question types: ~60% multiple_choice, ~25% write_in, ~15% matching
- Cite the source chunk for each question
- Questions should be practical and relevant to a sales rep's daily work

OUTPUT FORMAT: Return a JSON array of question objects:
[
  {{
    "question_id": "q1",
    "question_text": "What is the maximum vessel diameter indicated for the Solitaire X?",
    "question_type": "multiple_choice",
    "category": "specifications",
    "difficulty": "{difficulty}",
    "options": ["4mm", "5mm", "5.5mm", "6mm"],
    "correct_answer": "5.5mm",
    "explanation": "According to the Solitaire X IFU, the device is indicated for use in vessels up to 5.5mm diameter.",
    "source_chunk_id": "chunk_123"
  }},
  {{
    "question_id": "q2",
    "question_text": "Explain how the DAWN trial changed the treatment window for mechanical thrombectomy.",
    "question_type": "write_in",
    "category": "clinical_evidence",
    "difficulty": "{difficulty}",
    "correct_answer": "The DAWN trial demonstrated that patients with favorable imaging profiles (clinical-imaging mismatch) could benefit from mechanical thrombectomy up to 24 hours after symptom onset, extending the previously accepted 6-hour window.",
    "explanation": "DAWN was a landmark RCT showing benefit of thrombectomy in the 6-24 hour window using perfusion imaging selection.",
    "source_chunk_id": "chunk_456"
  }},
  {{
    "question_id": "q3",
    "question_text": "Match each device to its manufacturer.",
    "question_type": "matching",
    "category": "competitive_knowledge",
    "difficulty": "{difficulty}",
    "left_items": ["Solitaire X", "ACE 68", "SOFIA Plus", "Trevo XP"],
    "right_items": ["Medtronic", "Penumbra", "MicroVention", "Stryker"],
    "correct_matches": {{"Solitaire X": "Medtronic", "ACE 68": "Penumbra", "SOFIA Plus": "MicroVention", "Trevo XP": "Stryker"}},
    "explanation": "Knowing which manufacturer makes each device is fundamental competitive knowledge.",
    "source_chunk_id": "chunk_789"
  }}
]

Return ONLY the JSON array, no other text.

DOCUMENT CHUNKS:
{chunks_text}
"""

WRITE_IN_SCORING_PROMPT = """You are scoring a sales rep's written answer on a neurovascular device assessment.

Question: {question_text}
Category: {category}
Ideal Answer: {correct_answer}
Rep's Answer: {rep_answer}

Score this answer on a scale:
- "correct" — Answer is substantially correct, covers key points
- "partially_correct" — Answer has some correct elements but misses important points
- "incorrect" — Answer is wrong or completely misses the point

Respond with ONLY a JSON object:
{{"score": "correct|partially_correct|incorrect", "feedback": "Brief explanation of what was right/wrong"}}
"""


class AssessmentService:
    """Service for generating, storing, and scoring structured assessments."""

    def __init__(self):
        self.persistence = get_persistence_service()
        self.data_manager = get_data_manager()

    async def generate_assessment(
        self,
        rep_company: str,
        difficulty_level: str = "intermediate",
        rep_name: str = "",
        rep_id: str = "",
        question_count: int = 15,
    ) -> Dict[str, Any]:
        """
        Generate a structured assessment using LLM + document chunks.

        Returns assessment with questions (correct answers stored server-side only).
        """
        assessment_id = f"assess_{uuid.uuid4().hex[:12]}"
        difficulty = DIFFICULTY_GUIDANCE.get(difficulty_level, DIFFICULTY_GUIDANCE["intermediate"])

        # Select relevant chunks by category and difficulty
        chunks_by_category = self._select_chunks_for_assessment(
            difficulty_level, rep_company, question_count
        )

        # Format chunks for the LLM prompt
        chunks_text = self._format_chunks_for_prompt(chunks_by_category)

        # Build category distribution string
        questions_per_cat = max(2, question_count // len(ASSESSMENT_CATEGORIES))
        remainder = question_count - (questions_per_cat * len(ASSESSMENT_CATEGORIES))
        cat_dist_parts = []
        for i, cat in enumerate(ASSESSMENT_CATEGORIES):
            count = questions_per_cat + (1 if i < remainder else 0)
            cat_dist_parts.append(f"- {CATEGORY_LABELS[cat]}: {count} questions")
        category_distribution = "\n".join(cat_dist_parts)

        # Generate questions via LLM
        prompt = ASSESSMENT_GENERATION_PROMPT.format(
            question_count=question_count,
            category_distribution=category_distribution,
            difficulty_guidance=difficulty["question_guidance"],
            difficulty=difficulty_level,
            chunks_text=chunks_text,
        )

        llm = LLMService()
        response = await llm.generate(
            system_prompt=prompt,
            messages=[{"role": "user", "content": "Generate the assessment questions now."}],
            temperature=0.3,
            max_tokens=4000,
        )

        # Parse questions from LLM response
        questions = self._parse_questions(response, assessment_id)

        if not questions:
            raise ValueError("Failed to generate assessment questions from LLM")

        # Store full assessment with correct answers (server-side)
        assessment_record = {
            "assessment_id": assessment_id,
            "rep_id": rep_id,
            "rep_name": rep_name,
            "rep_company": rep_company,
            "difficulty_level": difficulty_level,
            "question_count": len(questions),
            "questions": questions,  # includes correct_answer
            "status": "in_progress",
            "created_at": datetime.utcnow().isoformat(),
            "submitted_at": None,
            "results": None,
        }
        self._save_assessment(assessment_record)

        # Return questions WITHOUT correct answers to the client
        client_questions = []
        for q in questions:
            cq = {
                "question_id": q["question_id"],
                "question_text": q["question_text"],
                "question_type": q["question_type"],
                "category": q["category"],
                "difficulty": q.get("difficulty", difficulty_level),
                "options": q.get("options"),
                "left_items": q.get("left_items"),
                "right_items": q.get("right_items"),
                "hint": q.get("hint"),
            }
            # Remove None values
            client_questions.append({k: v for k, v in cq.items() if v is not None})

        return {
            "assessment_id": assessment_id,
            "difficulty_level": difficulty_level,
            "question_count": len(client_questions),
            "questions": client_questions,
        }

    async def score_assessment(
        self,
        assessment_id: str,
        submissions: List[Dict[str, str]],
    ) -> Dict[str, Any]:
        """
        Score all submitted answers for an assessment.

        MC = direct comparison. Write-in = LLM evaluation.
        Matching = check each pair.
        """
        record = self._load_assessment(assessment_id)
        if not record:
            raise ValueError(f"Assessment {assessment_id} not found")

        questions_map = {q["question_id"]: q for q in record["questions"]}
        llm = LLMService()

        question_results = []
        total_score = 0
        max_score = 0
        category_scores: Dict[str, Dict[str, int]] = {}

        for sub in submissions:
            qid = sub.get("question_id", "")
            rep_answer = sub.get("rep_answer", "")
            question = questions_map.get(qid)

            if not question:
                continue

            cat = question.get("category", "unknown")
            if cat not in category_scores:
                category_scores[cat] = {"earned": 0, "possible": 0, "correct": 0, "total": 0}

            max_score += 1
            category_scores[cat]["possible"] += 1
            category_scores[cat]["total"] += 1

            qtype = question["question_type"]
            result = {
                "question_id": qid,
                "question_text": question["question_text"],
                "question_type": qtype,
                "category": cat,
                "rep_answer": rep_answer,
                "correct_answer": question.get("correct_answer", ""),
                "explanation": question.get("explanation", ""),
            }

            if qtype == "multiple_choice":
                is_correct = rep_answer.strip().lower() == question.get("correct_answer", "").strip().lower()
                result["score"] = "correct" if is_correct else "incorrect"
                if is_correct:
                    total_score += 1
                    category_scores[cat]["earned"] += 1
                    category_scores[cat]["correct"] += 1

            elif qtype == "write_in":
                # Use LLM to evaluate write-in answer
                score_result = await self._score_write_in(llm, question, rep_answer)
                result["score"] = score_result["score"]
                result["feedback"] = score_result.get("feedback", "")
                if score_result["score"] == "correct":
                    total_score += 1
                    category_scores[cat]["earned"] += 1
                    category_scores[cat]["correct"] += 1
                elif score_result["score"] == "partially_correct":
                    total_score += 0.5
                    category_scores[cat]["earned"] += 0.5

            elif qtype == "matching":
                correct_matches = question.get("correct_matches", {})
                rep_matches = {}
                try:
                    rep_matches = json.loads(rep_answer) if isinstance(rep_answer, str) else rep_answer
                except (json.JSONDecodeError, TypeError):
                    rep_matches = {}

                correct_count = sum(
                    1 for k, v in rep_matches.items()
                    if correct_matches.get(k, "").strip().lower() == v.strip().lower()
                )
                total_items = len(correct_matches)
                if total_items > 0 and correct_count == total_items:
                    result["score"] = "correct"
                    total_score += 1
                    category_scores[cat]["earned"] += 1
                    category_scores[cat]["correct"] += 1
                elif correct_count > 0:
                    result["score"] = "partially_correct"
                    partial = correct_count / total_items
                    total_score += partial
                    category_scores[cat]["earned"] += partial
                else:
                    result["score"] = "incorrect"

                result["correct_matches"] = correct_matches
                result["rep_matches"] = rep_matches

            question_results.append(result)

        percentage = round((total_score / max_score * 100) if max_score > 0 else 0, 1)
        pass_fail = "pass" if percentage >= 70 else "fail"

        # Format category scores
        formatted_categories = {}
        for cat, data in category_scores.items():
            formatted_categories[cat] = {
                "label": CATEGORY_LABELS.get(cat, cat.replace("_", " ").title()),
                "earned": data["earned"],
                "possible": data["possible"],
                "percentage": round((data["earned"] / data["possible"] * 100) if data["possible"] > 0 else 0, 1),
                "correct_count": data["correct"],
                "total_count": data["total"],
            }

        results = {
            "assessment_id": assessment_id,
            "total_score": total_score,
            "max_score": max_score,
            "percentage": percentage,
            "pass_fail": pass_fail,
            "category_scores": formatted_categories,
            "question_results": question_results,
            "submitted_at": datetime.utcnow().isoformat(),
        }

        # Update stored record
        record["status"] = "completed"
        record["submitted_at"] = results["submitted_at"]
        record["results"] = results
        self._save_assessment(record)

        return results

    def get_results(self, assessment_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve stored assessment results."""
        record = self._load_assessment(assessment_id)
        if not record or not record.get("results"):
            return None
        return record["results"]

    # --- Private helpers ---

    def _select_chunks_for_assessment(
        self, difficulty: str, rep_company: str, question_count: int
    ) -> Dict[str, List[dict]]:
        """Select document chunks organized by category for question generation."""
        diff_config = DIFFICULTY_GUIDANCE.get(difficulty, DIFFICULTY_GUIDANCE["intermediate"])
        preferred_source_types = diff_config["source_types"]
        chunks = self.data_manager.document_chunks

        # Map source_type to assessment category
        source_to_category = {
            "ifu_document": "ifu_regulatory",
            "device_spec": "specifications",
            "product_page": "specifications",
            "clinical_trial": "clinical_evidence",
            "adverse_event": "clinical_evidence",
            "competitive_analysis": "competitive_knowledge",
        }

        categorized: Dict[str, List[dict]] = {cat: [] for cat in ASSESSMENT_CATEGORIES}

        for chunk in chunks:
            st = chunk.get("source_type", "")
            cat = source_to_category.get(st, "")

            # If not mapped, try section_hint
            if not cat:
                sh = chunk.get("section_hint", "").lower()
                if "procedure" in sh or "workflow" in sh or "technique" in sh:
                    cat = "procedure_workflow"
                elif "indication" in sh or "contraindication" in sh or "warning" in sh:
                    cat = "ifu_regulatory"
                elif "spec" in sh or "dimension" in sh or "size" in sh:
                    cat = "specifications"
                elif "trial" in sh or "study" in sh or "evidence" in sh:
                    cat = "clinical_evidence"
                else:
                    cat = "specifications"  # default

            # Prioritize chunks matching preferred source types
            if st in preferred_source_types:
                categorized[cat].append(chunk)
            elif len(categorized[cat]) < 20:
                categorized[cat].append(chunk)

        # Limit chunks per category to keep prompt manageable
        chunks_per_cat = max(8, 50 // len(ASSESSMENT_CATEGORIES))
        for cat in categorized:
            if len(categorized[cat]) > chunks_per_cat:
                # Take a diverse sample
                step = len(categorized[cat]) // chunks_per_cat
                categorized[cat] = categorized[cat][::step][:chunks_per_cat]

        # Ensure procedure_workflow has chunks (it may be sparse)
        if len(categorized["procedure_workflow"]) < 3:
            for chunk in chunks:
                text = chunk.get("text", "").lower()
                if any(kw in text for kw in ["workflow", "procedure", "technique", "access", "deploy"]):
                    categorized["procedure_workflow"].append(chunk)
                    if len(categorized["procedure_workflow"]) >= 8:
                        break

        return categorized

    def _format_chunks_for_prompt(self, chunks_by_category: Dict[str, List[dict]]) -> str:
        """Format categorized chunks as text for the LLM prompt."""
        parts = []
        for cat, chunks in chunks_by_category.items():
            if not chunks:
                continue
            label = CATEGORY_LABELS.get(cat, cat)
            parts.append(f"\n=== {label} ===")
            for chunk in chunks:
                cid = chunk.get("chunk_id", "unknown")
                src = chunk.get("source_type", "")
                mfr = chunk.get("manufacturer", "")
                devices = ", ".join(chunk.get("device_names", []))
                text = chunk.get("text", "")[:800]
                parts.append(
                    f"[{cid}] (source: {src}, manufacturer: {mfr}, devices: {devices})\n{text}\n"
                )
        return "\n".join(parts)

    def _parse_questions(self, llm_response: str, assessment_id: str) -> List[dict]:
        """Parse LLM response into structured question objects."""
        # Try to extract JSON array from response
        text = llm_response.strip()

        # Remove markdown code fences if present
        if text.startswith("```"):
            lines = text.split("\n")
            start = 1
            end = len(lines)
            for i in range(len(lines) - 1, 0, -1):
                if lines[i].strip().startswith("```"):
                    end = i
                    break
            text = "\n".join(lines[start:end])

        try:
            questions = json.loads(text)
        except json.JSONDecodeError:
            # Try to find JSON array in the text
            import re
            match = re.search(r'\[.*\]', text, re.DOTALL)
            if match:
                try:
                    questions = json.loads(match.group())
                except json.JSONDecodeError:
                    logger.error("Failed to parse assessment questions from LLM response")
                    return []
            else:
                logger.error("No JSON array found in LLM response")
                return []

        if not isinstance(questions, list):
            return []

        # Normalize and validate
        valid = []
        for i, q in enumerate(questions):
            if not isinstance(q, dict):
                continue
            q["question_id"] = q.get("question_id", f"q{i+1}")
            if not q.get("question_text") or not q.get("question_type"):
                continue
            if q["question_type"] not in ("multiple_choice", "write_in", "matching"):
                q["question_type"] = "multiple_choice"
            if q["question_type"] == "multiple_choice" and not q.get("options"):
                continue
            if q["question_type"] == "matching" and (not q.get("left_items") or not q.get("right_items")):
                continue
            if not q.get("category"):
                q["category"] = ASSESSMENT_CATEGORIES[i % len(ASSESSMENT_CATEGORIES)]
            valid.append(q)

        return valid

    async def _score_write_in(
        self, llm: LLMService, question: dict, rep_answer: str
    ) -> dict:
        """Use LLM to score a write-in answer."""
        if not rep_answer.strip():
            return {"score": "incorrect", "feedback": "No answer provided."}

        prompt = WRITE_IN_SCORING_PROMPT.format(
            question_text=question["question_text"],
            category=question.get("category", ""),
            correct_answer=question.get("correct_answer", ""),
            rep_answer=rep_answer,
        )

        try:
            response = await llm.generate(
                system_prompt=prompt,
                messages=[{"role": "user", "content": "Score this answer now."}],
                temperature=0,
                max_tokens=300,
            )

            text = response.strip()
            if text.startswith("```"):
                lines = text.split("\n")
                text = "\n".join(lines[1:-1])

            result = json.loads(text)
            if result.get("score") not in ("correct", "partially_correct", "incorrect"):
                result["score"] = "incorrect"
            return result
        except Exception as e:
            logger.error(f"Error scoring write-in: {e}")
            return {"score": "incorrect", "feedback": "Could not evaluate answer."}

    def _save_assessment(self, record: dict) -> None:
        """Save assessment to JSON file."""
        data = self.persistence._load_json("assessments.json")
        if "assessments" not in data:
            data["assessments"] = {}
        data["assessments"][record["assessment_id"]] = record
        self.persistence._save_json("assessments.json", data)

    def _load_assessment(self, assessment_id: str) -> Optional[dict]:
        """Load an assessment by ID."""
        data = self.persistence._load_json("assessments.json")
        return data.get("assessments", {}).get(assessment_id)


@lru_cache(maxsize=1)
def get_assessment_service() -> AssessmentService:
    """Get singleton AssessmentService instance."""
    return AssessmentService()
