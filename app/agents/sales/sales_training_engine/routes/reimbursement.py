"""
Reimbursement Intelligence API router.

Provides CPT code lookups, device-to-procedure mappings, and operative note parsing.
"""

import io
import logging
from typing import Dict, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from ..services.reimbursement_service import ReimbursementService, get_reimbursement_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/reimbursement", tags=["reimbursement"])


# --- Request Models ---

class ParseNoteRequest(BaseModel):
    note_text: str
    hospital_name: Optional[str] = None


# --- Endpoints ---

@router.get("/hospitals")
async def list_hospitals(
    svc: ReimbursementService = Depends(get_reimbursement_service),
) -> Dict:
    """List hospitals from physician dossiers for cost context."""
    hospitals = svc.get_hospital_list()
    return {"hospitals": hospitals, "total": len(hospitals)}


@router.get("/codes")
async def list_codes(
    category: Optional[str] = None,
    q: Optional[str] = None,
    svc: ReimbursementService = Depends(get_reimbursement_service),
) -> Dict:
    """List CPT codes, optionally filtered by category or search query."""
    codes = svc.list_codes(category=category, q=q)
    return {"codes": codes, "total": len(codes)}


@router.get("/categories")
async def list_categories(
    svc: ReimbursementService = Depends(get_reimbursement_service),
) -> Dict:
    """List available procedure categories."""
    return {"categories": svc.get_categories()}


@router.get("/codes/{cpt_code}")
async def get_code(
    cpt_code: str,
    svc: ReimbursementService = Depends(get_reimbursement_service),
) -> Dict:
    """Get details for a specific CPT code."""
    code = svc.get_code(cpt_code)
    if not code:
        raise HTTPException(status_code=404, detail=f"CPT code {cpt_code} not found")
    return code


@router.get("/device-map/{device_category}")
async def get_device_map(
    device_category: str,
    svc: ReimbursementService = Depends(get_reimbursement_service),
) -> Dict:
    """Get CPT codes that apply to a given device category."""
    codes = svc.get_codes_for_device_category(device_category)
    return {"device_category": device_category, "codes": codes, "total": len(codes)}


@router.get("/drg-codes")
async def list_drg_codes(
    svc: ReimbursementService = Depends(get_reimbursement_service),
) -> Dict:
    """List all DRG codes with hospital reimbursement data."""
    drgs = svc.list_drg_codes()
    return {"drg_codes": drgs, "total": len(drgs)}


@router.get("/drg/{drg_code}")
async def get_drg(
    drg_code: str,
    svc: ReimbursementService = Depends(get_reimbursement_service),
) -> Dict:
    """Get details for a specific DRG code."""
    drg = svc.get_drg(drg_code)
    if not drg:
        raise HTTPException(status_code=404, detail=f"DRG {drg_code} not found")
    return drg


@router.get("/hospital-costs")
async def get_hospital_costs(
    svc: ReimbursementService = Depends(get_reimbursement_service),
) -> Dict:
    """Get hospital cost data: indirect costs, device costs, and procedure economics."""
    return svc.get_hospital_cost_data()


@router.get("/procedure-economics/{procedure_type}")
async def get_procedure_economics(
    procedure_type: str,
    svc: ReimbursementService = Depends(get_reimbursement_service),
) -> Dict:
    """Get cost vs reimbursement economics for a procedure type."""
    economics = svc.get_procedure_economics(procedure_type)
    if not economics:
        raise HTTPException(status_code=404, detail=f"No economics data for {procedure_type}")
    return economics


@router.get("/icd10-categories")
async def list_icd10_categories(
    svc: ReimbursementService = Depends(get_reimbursement_service),
) -> Dict:
    """List available ICD-10 diagnosis categories."""
    return {"categories": svc.get_icd10_categories()}


@router.get("/icd10-codes")
async def list_icd10_codes(
    category: Optional[str] = None,
    q: Optional[str] = None,
    svc: ReimbursementService = Depends(get_reimbursement_service),
) -> Dict:
    """List ICD-10 codes, optionally filtered by category or search query."""
    codes = svc.list_icd10_codes(category=category, q=q)
    return {"codes": codes, "total": len(codes)}


@router.get("/icd10/{icd10_code}")
async def get_icd10_code(
    icd10_code: str,
    svc: ReimbursementService = Depends(get_reimbursement_service),
) -> Dict:
    """Get details for a specific ICD-10 code."""
    code = svc.get_icd10(icd10_code)
    if not code:
        raise HTTPException(status_code=404, detail=f"ICD-10 code {icd10_code} not found")
    return code


@router.post("/parse-note")
async def parse_operative_note(
    request: ParseNoteRequest,
    svc: ReimbursementService = Depends(get_reimbursement_service),
) -> Dict:
    """Parse an operative note to extract applicable CPT codes using AI."""
    if not request.note_text.strip():
        raise HTTPException(status_code=400, detail="Operative note text is required")

    result = await svc.parse_operative_note(request.note_text, hospital_name=request.hospital_name)
    return result


@router.post("/extract-text")
async def extract_text_from_file(
    file: UploadFile = File(...),
) -> Dict:
    """Extract text from an uploaded operative note file (PDF, DOCX, TXT)."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    filename = file.filename.lower()
    content = await file.read()

    try:
        if filename.endswith('.txt') or filename.endswith('.text'):
            text = content.decode('utf-8', errors='replace')

        elif filename.endswith('.pdf'):
            try:
                import PyPDF2
                reader = PyPDF2.PdfReader(io.BytesIO(content))
                pages = []
                for page in reader.pages:
                    pages.append(page.extract_text() or '')
                text = '\n\n'.join(pages)
            except ImportError:
                # Fallback: try pdfminer
                try:
                    from pdfminer.high_level import extract_text as pdf_extract
                    text = pdf_extract(io.BytesIO(content))
                except ImportError:
                    raise HTTPException(
                        status_code=500,
                        detail="PDF extraction not available. Install PyPDF2: pip install PyPDF2"
                    )

        elif filename.endswith('.docx'):
            try:
                import docx
                doc = docx.Document(io.BytesIO(content))
                text = '\n'.join(p.text for p in doc.paragraphs)
            except ImportError:
                raise HTTPException(
                    status_code=500,
                    detail="DOCX extraction not available. Install python-docx: pip install python-docx"
                )

        elif filename.endswith('.doc'):
            raise HTTPException(
                status_code=400,
                detail="Legacy .doc format not supported. Please save as .docx or .txt"
            )

        else:
            # Try reading as text
            text = content.decode('utf-8', errors='replace')

        return {"text": text.strip(), "filename": file.filename, "char_count": len(text.strip())}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error extracting text from {file.filename}")
        raise HTTPException(status_code=500, detail=f"Error extracting text: {str(e)}")
