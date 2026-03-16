"""
Consolidated Training routes for MedSync AI Sales Training Engine.

Migrated from:
  - api/assessment.py     -> /sales/assessment
  - api/certifications.py -> /sales/certifications
  - api/knowledge_qa.py   -> /sales/qa
"""

import json
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..services.assessment_service import AssessmentService, get_assessment_service
from ..services.data_loader import DataManager, get_data_manager
from ..services.persistence_service import PersistenceService, get_persistence_service
from ..services.llm_adapter import SalesLLMAdapter
from ..rag.retrieval import VectorRetriever

logger = logging.getLogger(__name__)

# Data directory — resolve relative to this package
_DATA_DIR = Path(__file__).resolve().parent.parent / "data"


# ── Assessment Router ─────────────────────────────────────────────────────

assessment_router = APIRouter(prefix="/sales/assessment", tags=["Sales Assessment"])


# --- Request / Response Models ---

class GenerateAssessmentRequest(BaseModel):
    """Request to generate a new structured assessment."""
    rep_company: str = Field(..., description="Rep's company for relevant questions")
    difficulty_level: str = Field(default="intermediate", description="beginner, intermediate, experienced")
    rep_name: str = Field(default="", description="Rep name for personalization")
    rep_id: str = Field(default="", description="Rep ID for tracking")
    question_count: int = Field(default=15, ge=5, le=25, description="Number of questions to generate")


class SubmissionEntry(BaseModel):
    """A single question answer submission."""
    question_id: str
    rep_answer: str  # For matching, this is a JSON string of {"left": "right"} pairs


class SubmitAssessmentRequest(BaseModel):
    """Request to submit answers for scoring."""
    submissions: List[SubmissionEntry]


# --- Endpoints ---

@assessment_router.post("/generate")
async def generate_assessment(request: GenerateAssessmentRequest):
    """
    Generate a new structured assessment.

    The LLM creates questions from document chunks organized by category.
    Questions are returned WITHOUT correct answers (stored server-side).
    """
    try:
        service = get_assessment_service()
        result = await service.generate_assessment(
            rep_company=request.rep_company,
            difficulty_level=request.difficulty_level,
            rep_name=request.rep_name,
            rep_id=request.rep_id,
            question_count=request.question_count,
        )
        return result

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Error generating assessment")
        raise HTTPException(status_code=500, detail=f"Failed to generate assessment: {str(e)}")


@assessment_router.post("/{assessment_id}/submit")
async def submit_assessment(assessment_id: str, request: SubmitAssessmentRequest):
    """
    Submit answers for a generated assessment and receive scores.

    MC answers are scored directly. Write-in answers are evaluated by LLM.
    Matching answers are compared pair by pair.
    """
    try:
        service = get_assessment_service()
        submissions = [s.model_dump() for s in request.submissions]
        results = await service.score_assessment(assessment_id, submissions)
        return results

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("Error scoring assessment")
        raise HTTPException(status_code=500, detail=f"Failed to score assessment: {str(e)}")


@assessment_router.get("/{assessment_id}/results")
async def get_assessment_results(assessment_id: str):
    """
    Retrieve stored results for a completed assessment.
    """
    service = get_assessment_service()
    results = service.get_results(assessment_id)
    if not results:
        raise HTTPException(status_code=404, detail=f"Results not found for assessment {assessment_id}")
    return results


# ── Certification Router ──────────────────────────────────────────────────

certification_router = APIRouter(prefix="/sales/certifications", tags=["Sales Certifications"])

# Default certification paths
DEFAULT_CERT_PATHS = [
    {
        "cert_id": "evt_specialist",
        "name": "EVT Specialist",
        "description": "Demonstrate mastery of endovascular thrombectomy device knowledge through structured assessments.",
        "company": "all",
        "requirements": [
            {"requirement_type": "assessment_score", "min_score": 0.80, "count": 2},
        ],
        "badge_icon": "trophy",
        "validity_months": 6,
    },
    {
        "cert_id": "aspiration_expert",
        "name": "Aspiration Technique Expert",
        "description": "Prove your expertise in aspiration-first thrombectomy approaches across multiple simulations.",
        "company": "all",
        "requirements": [
            {"requirement_type": "simulation_count", "mode": "competitive_sales_call", "count": 3, "min_score": 0.80},
        ],
        "badge_icon": "star",
        "validity_months": 6,
    },
    {
        "cert_id": "competitive_pro",
        "name": "Competitive Positioning Pro",
        "description": "Show strong competitive knowledge across multiple scored sessions.",
        "company": "all",
        "requirements": [
            {"requirement_type": "dimension_min", "dimension": "competitive_knowledge", "min_score": 0.80, "count": 5},
        ],
        "badge_icon": "shield",
        "validity_months": 6,
    },
    {
        "cert_id": "objection_master",
        "name": "Objection Handling Master",
        "description": "Master evidence-based responses to physician objections.",
        "company": "all",
        "requirements": [
            {"requirement_type": "dimension_min", "dimension": "objection_handling", "min_score": 0.80, "count": 3},
        ],
        "badge_icon": "lightning",
        "validity_months": 6,
    },
    {
        "cert_id": "regulatory_expert",
        "name": "Regulatory Compliance Expert",
        "description": "Demonstrate strong knowledge of IFU boundaries, contraindications, and on-label usage.",
        "company": "all",
        "requirements": [
            {"requirement_type": "dimension_min", "dimension": "regulatory_compliance", "min_score": 0.85, "count": 3},
        ],
        "badge_icon": "check_circle",
        "validity_months": 6,
    },
]


def _get_cert_paths() -> List[dict]:
    """Load certification paths from config or use defaults."""
    cert_file = _DATA_DIR / "certification_paths.json"
    if cert_file.exists():
        try:
            with open(cert_file, "r") as f:
                data = json.load(f)
                return data.get("paths", DEFAULT_CERT_PATHS)
        except (json.JSONDecodeError, IOError):
            pass
    return DEFAULT_CERT_PATHS


@certification_router.get("/paths")
async def list_cert_paths() -> Dict:
    """List all certification paths."""
    paths = _get_cert_paths()
    return {"paths": paths, "total": len(paths)}


@certification_router.get("/{rep_id}")
async def get_rep_certifications(
    rep_id: str,
    persistence: PersistenceService = Depends(get_persistence_service),
) -> Dict:
    """Get certifications earned by a rep."""
    certs = persistence.get_rep_certifications(rep_id)
    return {"certifications": certs, "total": len(certs)}


@certification_router.post("/{rep_id}/check")
async def check_certifications(
    rep_id: str,
    persistence: PersistenceService = Depends(get_persistence_service),
) -> Dict:
    """Check if a rep qualifies for new certifications."""
    paths = _get_cert_paths()
    existing = persistence.get_rep_certifications(rep_id)
    existing_ids = {c.get("cert_id") for c in existing if c.get("status") == "active"}

    activities = persistence.get_rep_activities(rep_id, limit=500)
    scored_activities = [a for a in activities if a.get("scores")]

    newly_earned = []

    for path in paths:
        if path["cert_id"] in existing_ids:
            continue

        qualified = _check_requirements(path["requirements"], scored_activities)
        if qualified:
            now = datetime.utcnow()
            cert = {
                "rep_id": rep_id,
                "cert_id": path["cert_id"],
                "cert_name": path["name"],
                "earned_at": now.isoformat() + "Z",
                "expires_at": (now + timedelta(days=path.get("validity_months", 6) * 30)).isoformat() + "Z",
                "status": "active",
            }
            persistence.save_certification(cert)
            newly_earned.append(cert)

    return {"newly_earned": newly_earned, "total_earned": len(existing) + len(newly_earned)}


@certification_router.get("/{rep_id}/progress")
async def get_cert_progress(
    rep_id: str,
    persistence: PersistenceService = Depends(get_persistence_service),
) -> Dict:
    """Get progress toward each certification for a rep."""
    paths = _get_cert_paths()
    existing = persistence.get_rep_certifications(rep_id)
    existing_map = {c.get("cert_id"): c for c in existing}

    activities = persistence.get_rep_activities(rep_id, limit=500)
    scored_activities = [a for a in activities if a.get("scores")]

    progress = []
    for path in paths:
        cert_id = path["cert_id"]
        earned = existing_map.get(cert_id)

        req_progress = []
        for req in path["requirements"]:
            current, needed = _compute_progress(req, scored_activities)
            req_progress.append({
                "requirement_type": req["requirement_type"],
                "current": current,
                "needed": needed,
                "met": current >= needed,
            })

        progress.append({
            "cert_id": cert_id,
            "name": path["name"],
            "description": path["description"],
            "badge_icon": path.get("badge_icon", ""),
            "earned": earned is not None and earned.get("status") == "active",
            "earned_at": earned.get("earned_at") if earned else None,
            "expires_at": earned.get("expires_at") if earned else None,
            "requirements": req_progress,
            "overall_progress": sum(1 for r in req_progress if r["met"]) / max(len(req_progress), 1),
        })

    return {"progress": progress}


def _check_requirements(requirements: List[dict], scored_activities: List[dict]) -> bool:
    """Check if all requirements for a certification are met."""
    for req in requirements:
        current, needed = _compute_progress(req, scored_activities)
        if current < needed:
            return False
    return True


def _compute_progress(req: dict, scored_activities: List[dict]) -> tuple:
    """Compute (current, needed) for a single requirement."""
    req_type = req.get("requirement_type", "")
    needed = req.get("count", 1)
    min_score = req.get("min_score", 0.80)

    if req_type == "assessment_score":
        qualifying = [
            a for a in scored_activities
            if a.get("activity_type") in ("assessment", "simulation")
            and (a.get("overall_score") or 0) >= min_score
        ]
        return len(qualifying), needed

    elif req_type == "simulation_count":
        mode = req.get("mode")
        qualifying = [
            a for a in scored_activities
            if a.get("activity_type") == "simulation"
            and (not mode or a.get("mode") == mode)
            and (a.get("overall_score") or 0) >= min_score
        ]
        return len(qualifying), needed

    elif req_type == "dimension_min":
        dimension = req.get("dimension", "")
        qualifying = [
            a for a in scored_activities
            if (a.get("scores") or {}).get(dimension, 0) >= min_score
        ]
        return len(qualifying), needed

    return 0, needed


# ── Knowledge Q&A Router ─────────────────────────────────────────────────

qa_router = APIRouter(prefix="/sales/qa", tags=["Sales Knowledge QA"])


# --- Request / Response Models ---

class QARequest(BaseModel):
    """Request model for a knowledge base question."""
    question: str = Field(..., description="The user's question")
    conversation_history: List[Dict] = Field(
        default_factory=list,
        description="Previous Q&A turns for multi-turn context",
    )
    filters: Optional[Dict] = Field(
        None,
        description="Optional filters: manufacturer, source_type, device_names",
    )
    rep_name: Optional[str] = Field(
        None,
        description="Rep name for personalized responses",
    )

    class Config:
        json_schema_extra = {
            "example": {
                "question": "What is the evidence for aspiration thrombectomy in large vessel occlusion?",
                "conversation_history": [],
                "filters": None,
            }
        }


class QASourceChunk(BaseModel):
    """A source chunk used to answer the question."""
    chunk_id: str
    source_type: str
    file_name: str
    manufacturer: str
    section_hint: str
    excerpt: str = Field(..., description="Short excerpt from the chunk")
    score: float


class QAResponse(BaseModel):
    """Response model for a knowledge base answer."""
    answer: str = Field(..., description="The grounded answer")
    sources: List[QASourceChunk] = Field(
        default_factory=list,
        description="Source chunks that informed the answer",
    )
    source_count: int = Field(0, description="Number of sources used")


# --- System prompt for grounded Q&A ---

QA_SYSTEM_PROMPT = """You are MedSync AI Knowledge Assistant — a medical device knowledge base for neurovascular sales representatives.

CRITICAL RULES:
1. Answer ONLY using the provided document context below. Never use outside knowledge.
2. If the context does not contain enough information to answer, say: "I don't have sufficient information in the knowledge base to answer that question. Try rephrasing or ask about a specific device or topic."
3. For clinical study questions: Only cite findings from METHODS and RESULTS sections. Do NOT reference abstracts, discussion sections, or conclusions. Present data as reported (sample sizes, percentages, p-values, outcomes).
4. Always cite your sources by file name so the rep can look them up.
5. Be specific — include device names, specifications, numbers, and data points from the sources.
6. Keep answers concise and practical for a sales rep audience.
7. If multiple sources provide conflicting data, present both and note the discrepancy.
8. Format answers as clean readable plain text. Use short paragraphs separated by blank lines. Use simple dash bullets (- item) for lists. Do NOT use markdown formatting symbols like ##, **, *, or any other markup. Write in natural prose with paragraphs and simple lists only.

VERBATIM SOURCE DATA RULES (MANDATORY):
9. IFU data and device specifications must be quoted VERBATIM — word for word, exactly as written in the source. IFUs are legal documents. NEVER paraphrase, reword, or summarize IFU text. Present the exact text from the source.
10. NEVER round numbers. All values must appear exactly as stated in the source document. For example, "0.017 inches" must remain "0.017 inches" — never "~0.02 inches" or "approximately 0.02 inches." This applies to all specifications, dimensions, pressures, flow rates, and any numerical data.
11. 510(k) data, Recall notices, MAUDE adverse event reports, and clinical article methods/results must also be presented VERBATIM — quote the exact text from the source. You may add a brief summary ONLY in a clearly labeled "Summary:" section AFTER the verbatim text, never as a replacement for it.
12. Marketing materials and webpage content are the ONLY source types that may be freely summarized or paraphrased in your response.
13. When presenting verbatim content, label it clearly with the source file name so the rep knows it is an exact quote from the original document.

You are grounded in a knowledge base of:
- Device IFU documents (indications, contraindications, warnings, specifications) — VERBATIM ONLY
- 510(k) submissions — VERBATIM ONLY
- Recall notices — VERBATIM ONLY
- MAUDE adverse event reports — VERBATIM ONLY
- Clinical trial data (methods and results sections) — VERBATIM ONLY
- Competitive intelligence and marketing claims — may be summarized
- Press releases and product announcements — may be summarized
"""


# --- Intent extraction prompt ---

INTENT_EXTRACTION_PROMPT = """You are a search query analyzer for a medical device knowledge base containing document chunks about neurovascular thrombectomy devices.

Given the user's question, extract structured search parameters to find relevant chunks. Output ONLY a JSON object — no explanation, no markdown fences.

The knowledge base contains chunks with these fields:
- text: the chunk content
- file_name: source file name (e.g., "DAWN_Trial_6_to_24_hour_Methods_Results.txt", "ACE_68_IFU_Contraindications.txt")
- source_type: one of "clinical_trial", "ifu", "competitive_intel", "adverse_event", "press_release"
- manufacturer: e.g., "Penumbra", "Medtronic", "Stryker", "MicroVention"
- section_hint: e.g., "methods_results", "contraindications", "indications", "warnings", "specifications"
- device_names: list of device names in the chunk

Output this JSON:
{
  "search_terms": ["keyword1", "keyword2"],
  "trial_names": ["DAWN", "DEFUSE-3"],
  "device_names": ["ACE 68", "Solitaire X"],
  "manufacturers": ["Penumbra"],
  "source_types": ["clinical_trial", "ifu"],
  "section_hints": ["methods_results"],
  "file_name_keywords": ["DAWN", "6_to_24"]
}

Rules:
- search_terms: important medical/technical terms from the question
- trial_names: any specific trial or study names mentioned or implied (e.g., "EVT 6-24 hours" implies DAWN and DEFUSE-3)
- device_names: specific devices mentioned or implied
- manufacturers: companies mentioned or implied
- source_types: which document types are most relevant
- section_hints: which sections to prioritize
- file_name_keywords: terms likely to appear in file names
- Include empty arrays [] for fields with no matches
- Be generous with trial_names — if the question implies a well-known trial, include it"""


async def _extract_search_intent(question: str, llm_service: SalesLLMAdapter) -> dict:
    """Use LLM to extract structured search parameters from a question."""
    try:
        response = await llm_service.generate(
            system_prompt=INTENT_EXTRACTION_PROMPT,
            messages=[{"role": "user", "content": question}],
            temperature=0,
            max_tokens=500,
        )

        # Strip markdown fences if present
        text = response.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
            text = text.strip()

        intent = json.loads(text)
        logger.info(f"Extracted search intent: {json.dumps(intent, indent=2)}")
        return intent

    except (json.JSONDecodeError, Exception) as e:
        logger.warning(f"Intent extraction failed: {e}. Falling back to basic keywords.")
        # Fallback: extract simple keywords from question
        words = question.lower().split()
        stop_words = {"what", "is", "the", "a", "an", "to", "for", "of", "in", "and", "or", "how", "does", "do", "can", "with", "about", "are", "from", "this", "that", "it", "be", "was", "were"}
        keywords = [w for w in words if w not in stop_words and len(w) > 2]
        return {
            "search_terms": keywords,
            "trial_names": [],
            "device_names": [],
            "manufacturers": [],
            "source_types": [],
            "section_hints": [],
            "file_name_keywords": keywords[:3],
        }


def _hybrid_search(intent: dict, chunks: list, max_results: int = 15) -> list:
    """
    Search chunks using keyword matching, file name matching, and metadata filters.

    Scoring:
      +3 for file_name_keywords match in chunk's file_name
      +2 for trial_name found in chunk text
      +1 for search_term found in chunk text
      +1 for source_type match
      +1 for manufacturer match
      +1 for section_hint match
      +1 for device_name match

    Returns list of (chunk, score) tuples sorted by score descending.
    """
    search_terms = [t.lower() for t in intent.get("search_terms", [])]
    trial_names = [t.lower() for t in intent.get("trial_names", [])]
    device_names = [d.lower() for d in intent.get("device_names", [])]
    manufacturers = [m.lower() for m in intent.get("manufacturers", [])]
    source_types = [s.lower() for s in intent.get("source_types", [])]
    section_hints = [s.lower() for s in intent.get("section_hints", [])]
    file_name_keywords = [k.lower() for k in intent.get("file_name_keywords", [])]

    scored_chunks = []

    for chunk in chunks:
        score = 0
        chunk_text = (chunk.get("text", "") or "").lower()
        chunk_file = (chunk.get("file_name", "") or "").lower()
        chunk_source = (chunk.get("source_type", "") or "").lower()
        chunk_mfr = (chunk.get("manufacturer", "") or "").lower()
        chunk_section = (chunk.get("section_hint", "") or "").lower()
        chunk_devices = [d.lower() for d in (chunk.get("device_names", []) or [])]

        # File name keyword match (+3 each)
        for kw in file_name_keywords:
            if kw in chunk_file:
                score += 3

        # Trial name in text (+2 each)
        for trial in trial_names:
            if trial in chunk_text:
                score += 2

        # Search term in text (+1 each)
        for term in search_terms:
            if term in chunk_text:
                score += 1

        # Source type match (+1)
        if source_types and chunk_source in source_types:
            score += 1

        # Manufacturer match (+1)
        if manufacturers and chunk_mfr in manufacturers:
            score += 1

        # Section hint match (+1)
        if section_hints and chunk_section in section_hints:
            score += 1

        # Device name match (+1 each)
        for dev in device_names:
            if dev in chunk_devices or any(dev in cd for cd in chunk_devices):
                score += 1
            # Also check in text
            elif dev in chunk_text:
                score += 1

        if score > 0:
            scored_chunks.append((chunk, score))

    # Sort by score descending
    scored_chunks.sort(key=lambda x: x[1], reverse=True)

    return scored_chunks[:max_results]


@qa_router.post("/ask")
async def ask_question(
    request: QARequest,
    data_mgr: DataManager = Depends(get_data_manager),
) -> QAResponse:
    """
    Answer a question using only the document knowledge base.

    Two-stage hybrid retrieval:
      1. LLM extracts search intent (keywords, trial names, metadata)
      2. Python keyword/metadata search over all chunks
      3. Fallback: vector search supplements if results are sparse
    Then generates a grounded answer using the LLM.
    """
    try:
        llm_service = SalesLLMAdapter()

        question = request.question.strip()
        if not question:
            raise HTTPException(status_code=400, detail="Question cannot be empty")

        # --- Stage 1: LLM Intent Extraction ---
        intent = await _extract_search_intent(question, llm_service)

        # --- Stage 2: Hybrid Keyword/Metadata Search ---
        all_chunks = data_mgr.document_chunks
        hybrid_results = _hybrid_search(intent, all_chunks, max_results=15)

        logger.info(
            f"Hybrid search returned {len(hybrid_results)} results for: {question[:80]}"
        )

        # --- Fallback: Vector search if hybrid results are sparse ---
        if len(hybrid_results) < 5:
            logger.info("Hybrid results sparse, supplementing with vector search")
            retriever = VectorRetriever(data_mgr)
            vector_results = retriever.retrieve(
                question,
                k=10,
                filters=request.filters or None,
            )

            # Merge: add vector results not already in hybrid results
            hybrid_chunk_texts = {
                (c.get("file_name", ""), c.get("text", "")[:100])
                for c, _ in hybrid_results
            }
            for vr in vector_results:
                key = (vr.file_name, vr.text[:100])
                if key not in hybrid_chunk_texts:
                    # Convert VectorRetriever result to chunk dict format
                    hybrid_results.append((
                        {
                            "chunk_id": vr.chunk_id,
                            "text": vr.text,
                            "file_name": vr.file_name,
                            "source_type": vr.source_type,
                            "manufacturer": vr.manufacturer,
                            "section_hint": vr.section_hint,
                            "device_names": [],
                        },
                        0.5,  # Lower score for vector-only results
                    ))
                    hybrid_chunk_texts.add(key)

            # Re-sort and limit
            hybrid_results.sort(key=lambda x: x[1], reverse=True)
            hybrid_results = hybrid_results[:15]

        if not hybrid_results:
            return QAResponse(
                answer="I couldn't find any relevant information in the knowledge base for your question. Try asking about a specific device, manufacturer, clinical trial, or IFU topic.",
                sources=[],
                source_count=0,
            )

        # --- Build context for LLM ---
        # Source types that MUST be quoted verbatim (regulatory/clinical)
        VERBATIM_SOURCE_TYPES = {"ifu", "510k", "recall", "adverse_event", "clinical_trial"}

        context_parts = []
        for i, (chunk, score) in enumerate(hybrid_results):
            source_type_raw = (chunk.get("source_type", "") or "unknown").lower()
            source_type = source_type_raw.upper()
            section = chunk.get("section_hint", "")
            section_str = f" | Section: {section}" if section else ""
            mfr = chunk.get("manufacturer", "")
            mfr_str = f" | Manufacturer: {mfr}" if mfr else ""
            file_name = chunk.get("file_name", "unknown")
            text = chunk.get("text", "")

            # Tag verbatim-required sources so the LLM knows the rule applies
            if source_type_raw in VERBATIM_SOURCE_TYPES:
                handling = "VERBATIM REQUIRED — quote this text exactly, do not paraphrase or round any numbers"
            else:
                handling = "May be summarized or paraphrased"

            context_parts.append(
                f"[SOURCE {i+1}: {source_type}{section_str}{mfr_str} | Relevance: {score}]\n"
                f"File: {file_name}\n"
                f"Handling: {handling}\n"
                f"{text[:1200]}"
            )

        context_block = "\n\n---\n\n".join(context_parts)

        # --- Build messages ---
        messages = []

        # Add conversation history
        for turn in request.conversation_history[-6:]:
            messages.append({"role": turn.get("role", "user"), "content": turn.get("content", "")})

        # Add current question
        messages.append({"role": "user", "content": question})

        # --- Build system prompt with optional personalization ---
        system_prompt = QA_SYSTEM_PROMPT
        if request.rep_name:
            system_prompt = f"You are helping {request.rep_name}, a neurovascular sales representative. Address them by name occasionally.\n\n{system_prompt}"

        # --- Generate answer ---
        full_system = f"{system_prompt}\n\n=== DOCUMENT CONTEXT ===\n\n{context_block}"

        answer = await llm_service.generate(
            system_prompt=full_system,
            messages=messages,
            temperature=0.3,
            max_tokens=1500,
        )

        # --- Build source list ---
        sources = []
        for chunk, score in hybrid_results:
            chunk_id = chunk.get("chunk_id", chunk.get("file_name", "unknown"))
            sources.append(QASourceChunk(
                chunk_id=chunk_id,
                source_type=chunk.get("source_type", ""),
                file_name=chunk.get("file_name", ""),
                manufacturer=chunk.get("manufacturer", ""),
                section_hint=chunk.get("section_hint", ""),
                excerpt=(chunk.get("text", "")[:150].strip() + "..."),
                score=round(float(score), 4),
            ))

        return QAResponse(
            answer=answer,
            sources=sources,
            source_count=len(sources),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error processing Q&A question")
        raise HTTPException(
            status_code=500,
            detail=f"Error processing question: {str(e)}",
        )


@qa_router.get("/stats")
async def get_knowledge_base_stats(
    data_mgr: DataManager = Depends(get_data_manager),
) -> Dict:
    """
    Get knowledge base statistics for the Q&A interface.

    Returns chunk counts by source type, manufacturers covered, etc.
    """
    try:
        chunks = data_mgr.document_chunks

        # Count by source_type
        source_counts = {}
        manufacturer_set = set()
        section_counts = {}

        for chunk in chunks:
            st = chunk.get("source_type", "unknown")
            source_counts[st] = source_counts.get(st, 0) + 1

            mfr = chunk.get("manufacturer", "")
            if mfr:
                manufacturer_set.add(mfr)

            sh = chunk.get("section_hint", "")
            if sh:
                section_counts[sh] = section_counts.get(sh, 0) + 1

        return {
            "total_chunks": len(chunks),
            "source_types": source_counts,
            "manufacturers": sorted(manufacturer_set),
            "section_types": section_counts,
            "total_devices": len(data_mgr.devices),
        }

    except Exception as e:
        logger.exception("Error getting KB stats")
        raise HTTPException(
            status_code=500,
            detail=f"Error getting stats: {str(e)}",
        )
