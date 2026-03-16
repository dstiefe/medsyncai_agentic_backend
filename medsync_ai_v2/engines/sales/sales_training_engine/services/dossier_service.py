"""
Physician Dossier Service for MedSync AI Sales Intelligence Platform.

Manages CRUD operations for physician dossiers with JSON file persistence.
All CMS data stored verbatim — never rounded or paraphrased.
"""

import json
import shutil
import threading
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

from ..models.physician_dossier import (
    Interaction,
    PhysicianDossier,
    PhysicianDossierSummary,
)

# Data directory: the engine's data/ folder (sibling of services/)
_DATA_DIR = Path(__file__).resolve().parent.parent / "data"


class DossierService:
    """JSON file-based persistence for physician dossiers."""

    FILENAME = "physician_dossiers.json"
    SEED_DIR = "data_pipeline"

    def __init__(self, data_dir: Optional[Path] = None):
        if data_dir is None:
            data_dir = _DATA_DIR
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._dossiers: Dict[str, PhysicianDossier] = {}
        self._load_initial()

    def _load_initial(self) -> None:
        """Load dossiers from data dir, falling back to seed data."""
        filepath = self.data_dir / self.FILENAME
        if not filepath.exists():
            # Try to copy seed data from data_pipeline/
            # Check multiple possible locations
            candidates = [
                self.data_dir.parent / self.SEED_DIR / self.FILENAME,
                self.data_dir.parent / "backend" / self.SEED_DIR / self.FILENAME,
                Path(__file__).parent.parent.parent / self.SEED_DIR / self.FILENAME,
            ]
            for seed_path in candidates:
                if seed_path.exists():
                    shutil.copy2(seed_path, filepath)
                    break

        if filepath.exists():
            try:
                with open(filepath, "r") as f:
                    raw = json.load(f)
                if isinstance(raw, list):
                    for item in raw:
                        dossier = PhysicianDossier(**item)
                        self._dossiers[dossier.id] = dossier
                elif isinstance(raw, dict) and "dossiers" in raw:
                    for item in raw["dossiers"]:
                        dossier = PhysicianDossier(**item)
                        self._dossiers[dossier.id] = dossier
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(f"Failed to load dossiers: {e}")

    def _save(self) -> None:
        """Thread-safe write to JSON file."""
        filepath = self.data_dir / self.FILENAME
        data = [d.model_dump() for d in self._dossiers.values()]
        with self._lock:
            with open(filepath, "w") as f:
                json.dump(data, f, indent=2, default=str)

    def _compute_completion(self, dossier: PhysicianDossier) -> int:
        """Compute % of dossier sections that have data."""
        sections = [
            dossier.clinical_profile,
            dossier.business_intelligence,
            dossier.competitive_landscape,
            dossier.decision_making,
            dossier.relationship,
            dossier.compliance,
        ]
        filled = 0
        total = 0
        for section in sections:
            d = section.model_dump()
            for key, val in d.items():
                total += 1
                if val and val != [] and val != {} and val != "":
                    filled += 1
        return round((filled / total) * 100) if total > 0 else 0

    def _compute_total_procedures(self, dossier: PhysicianDossier) -> int:
        """Sum procedural CPT case volumes (36xxx, 37xxx, 61xxx, 75xxx)."""
        total = 0
        for cv in dossier.business_intelligence.case_volumes:
            code = cv.cpt_code
            if code.startswith(("36", "37", "61", "75")):
                total += cv.annual_services
        return total

    def list_dossiers(self) -> List[PhysicianDossierSummary]:
        """Return lightweight summaries for all dossiers."""
        summaries = []
        for d in self._dossiers.values():
            last_interaction = None
            if d.relationship.interactions:
                dates = [i.date for i in d.relationship.interactions if i.date]
                if dates:
                    last_interaction = max(dates)

            summaries.append(
                PhysicianDossierSummary(
                    id=d.id,
                    name=d.name,
                    specialty=d.specialty,
                    institution=d.institution,
                    city=d.city,
                    state=d.state,
                    npi=d.npi,
                    stroke_center_level=d.stroke_center_level,
                    total_procedures=self._compute_total_procedures(d),
                    years_experience=d.years_experience,
                    last_interaction=last_interaction,
                    completion_pct=self._compute_completion(d),
                )
            )
        return summaries

    def get_dossier(self, physician_id: str) -> Optional[PhysicianDossier]:
        """Get a full dossier by ID."""
        return self._dossiers.get(physician_id)

    def create_dossier(self, dossier: PhysicianDossier) -> PhysicianDossier:
        """Create a new dossier."""
        now = datetime.utcnow().isoformat()
        dossier.created_at = now
        dossier.updated_at = now
        self._dossiers[dossier.id] = dossier
        self._save()
        return dossier

    def update_dossier(
        self, physician_id: str, updates: dict
    ) -> Optional[PhysicianDossier]:
        """Full update of a dossier using dict merge."""
        existing = self._dossiers.get(physician_id)
        if not existing:
            return None

        current = existing.model_dump()
        current.update(updates)
        current["updated_at"] = datetime.utcnow().isoformat()
        updated = PhysicianDossier(**current)
        self._dossiers[physician_id] = updated
        self._save()
        return updated

    def update_section(
        self, physician_id: str, section: str, data: dict
    ) -> Optional[PhysicianDossier]:
        """Update a specific section of a dossier."""
        valid_sections = [
            "clinical_profile",
            "business_intelligence",
            "competitive_landscape",
            "decision_making",
            "relationship",
            "compliance",
        ]
        if section not in valid_sections:
            return None

        existing = self._dossiers.get(physician_id)
        if not existing:
            return None

        current = existing.model_dump()
        if section in current:
            if isinstance(current[section], dict):
                current[section].update(data)
            else:
                current[section] = data
        current["updated_at"] = datetime.utcnow().isoformat()
        updated = PhysicianDossier(**current)
        self._dossiers[physician_id] = updated
        self._save()
        return updated

    def delete_dossier(self, physician_id: str) -> bool:
        """Delete a dossier by ID."""
        if physician_id in self._dossiers:
            del self._dossiers[physician_id]
            self._save()
            return True
        return False

    def add_interaction(
        self, physician_id: str, interaction: Interaction
    ) -> Optional[PhysicianDossier]:
        """Append an interaction to a dossier's relationship section."""
        existing = self._dossiers.get(physician_id)
        if not existing:
            return None

        existing.relationship.interactions.insert(0, interaction)
        existing.updated_at = datetime.utcnow().isoformat()
        self._save()
        return existing

    def get_prompt_summary(self, physician_id: str) -> Optional[str]:
        """Get LLM-ready text summary for a dossier."""
        dossier = self._dossiers.get(physician_id)
        if not dossier:
            return None
        return dossier.summary_for_prompt()


@lru_cache(maxsize=1)
def get_dossier_service() -> DossierService:
    """Get the singleton DossierService instance."""
    return DossierService()
