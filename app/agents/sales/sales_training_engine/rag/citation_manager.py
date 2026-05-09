"""
Citation management module for MedSync AI Sales Simulation Engine.

Handles extraction, validation, and formatting of citations from LLM responses.
"""

from __future__ import annotations

import re
from typing import List, Optional

from ..models.simulation_state import Citation, CitationType
from ..services.data_loader import DataManager


class CitationManager:
    """Manages citations for LLM responses."""

    # Pattern to match citations: [TYPE:reference]
    CITATION_PATTERN = r"\[([A-Z_]+):([^\]]+)\]"

    def __init__(self, data_manager: DataManager):
        """
        Initialize CitationManager.

        Args:
            data_manager: The DataManager instance
        """
        self.data_manager = data_manager

    def extract_citations(self, response: str) -> List[Citation]:
        """
        Extract and validate all citations from an LLM response.

        Parses citation tags in format [TYPE:reference] where TYPE is one of:
        - SPECS: Device specification reference (device_id=123)
        - IFU: Instructions for use file reference
        - WEBPAGE: Webpage text file reference
        - LITERATURE: Clinical literature or trial reference
        - MAUDE: FDA adverse event reference

        Args:
            response: The LLM response text

        Returns:
            List of validated Citation objects
        """
        citations = []
        matches = re.finditer(self.CITATION_PATTERN, response)

        for match in matches:
            citation_type_str = match.group(1)
            reference = match.group(2)

            # Determine citation type
            try:
                citation_type = CitationType[citation_type_str]
            except KeyError:
                # Skip unknown citation types
                continue

            # Validate citation based on type
            verified = self._validate_citation(citation_type, reference)

            # Extract excerpt (simple: get surrounding text)
            start = max(0, match.start() - 50)
            end = min(len(response), match.end() + 50)
            excerpt = response[start:end].strip()

            citation = Citation(
                citation_type=citation_type,
                reference=reference,
                excerpt=excerpt,
                verified=verified,
            )
            citations.append(citation)

        return citations

    def _validate_citation(self, citation_type: CitationType, reference: str) -> bool:
        """
        Validate that a citation reference is legitimate.

        Args:
            citation_type: The type of citation
            reference: The reference string

        Returns:
            True if citation can be verified, False otherwise
        """
        if citation_type == CitationType.SPECS:
            # Check if device exists: format "device_id=123"
            try:
                if reference.startswith("device_id="):
                    device_id = int(reference.split("=")[1])
                    return self.data_manager.get_device(device_id) is not None
            except (ValueError, IndexError):
                return False

        elif citation_type == CitationType.IFU:
            # Check if file exists in chunks: format "filename.pdf"
            for chunk in self.data_manager.document_chunks:
                if chunk.get("file_name", "").lower() == reference.lower():
                    if chunk.get("source_type") == "ifu":
                        return True

        elif citation_type == CitationType.WEBPAGE:
            # Check if webpage file exists: format "filename.txt"
            for chunk in self.data_manager.document_chunks:
                if chunk.get("file_name", "").lower() == reference.lower():
                    if chunk.get("source_type") == "webpage_text":
                        return True

        elif citation_type == CitationType.LITERATURE:
            # Literature citations are harder to verify, accept if reference is non-empty
            return len(reference.strip()) > 0

        elif citation_type == CitationType.MAUDE:
            # MAUDE citations are event descriptions, accept if non-empty
            return len(reference.strip()) > 0

        return False

    def inject_citation_instructions(self, prompt: str) -> str:
        """
        Append citation format instructions to a prompt.

        Args:
            prompt: The base prompt text

        Returns:
            Prompt with appended citation instructions
        """
        instructions = """

When making claims about device specifications, clinical evidence, or regulatory matters,
support them with citations in the following format:

- For device specifications: [SPECS:device_id=XXX]
- For IFU (Instructions for Use): [IFU:filename.pdf]
- For product pages: [WEBPAGE:filename.txt]
- For clinical literature: [LITERATURE:study_or_trial_name]
- For adverse events: [MAUDE:brief_event_description]

Example: "The Trevo XP has a 0.021-inch compatible lumen [SPECS:device_id=123] and is used
for thrombectomy [IFU:Trevo_XP_IFU.pdf]."

Always verify that your citations are accurate before including them."""

        return prompt + instructions

    def strip_citations(self, response: str) -> str:
        """
        Remove all citation tags from a response for clean display.

        Args:
            response: The response text with citations

        Returns:
            The response with all [TYPE:reference] tags removed
        """
        return re.sub(self.CITATION_PATTERN, "", response)

    def format_citations_for_display(
        self, citations: List[Citation]
    ) -> List[dict]:
        """
        Format citations as footnote-style references for display.

        Args:
            citations: List of Citation objects

        Returns:
            List of formatted citation dictionaries with keys:
            - number: Citation footnote number
            - type: Citation type
            - reference: Reference text
            - verified: Whether citation was verified
            - excerpt: Context excerpt
        """
        formatted = []

        for i, citation in enumerate(citations, 1):
            formatted.append(
                {
                    "number": i,
                    "type": citation.citation_type.value,
                    "reference": citation.reference,
                    "verified": citation.verified,
                    "excerpt": citation.excerpt,
                }
            )

        return formatted
