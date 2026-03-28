"""
Reimbursement Intelligence service.

Manages CPT code data, device-to-procedure mappings, and operative note parsing.
"""

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

from ..config import get_settings
from .llm_service import LLMService

logger = logging.getLogger(__name__)


class ReimbursementService:
    """Service for CPT code lookups and operative note parsing."""

    def __init__(self):
        settings = get_settings()
        data_path = settings.data_dir / "reimbursement_data.json"

        if not data_path.exists():
            raise FileNotFoundError(f"Reimbursement data not found: {data_path}")

        with open(data_path, "r") as f:
            raw = json.load(f)

        self.metadata = raw.get("metadata", {})
        self.categories = raw.get("categories", [])
        self._codes: Dict[str, dict] = {}
        for code in raw.get("codes", []):
            self._codes[code["cpt_code"]] = code

        # Build reverse index: device_category -> list of CPT codes
        self._device_category_map: Dict[str, List[str]] = {}
        for code_data in self._codes.values():
            for cat in code_data.get("device_categories", []):
                self._device_category_map.setdefault(cat, []).append(
                    code_data["cpt_code"]
                )

        # Load DRG data
        self._drg_codes: Dict[str, dict] = {}
        for drg in raw.get("drg_codes", []):
            self._drg_codes[drg["drg_code"]] = drg
        self._drg_procedure_map: Dict[str, dict] = raw.get("drg_procedure_map", {})

        # Load hospital cost data (indirect costs, device costs, economics)
        self._hospital_cost_data: Dict = raw.get("hospital_cost_data", {})

        # Load hospital list from physician dossiers
        self._hospitals: List[dict] = []
        dossier_path = settings.data_dir / "physician_dossiers.json"
        if dossier_path.exists():
            try:
                with open(dossier_path, "r") as f:
                    dossiers = json.load(f)
                seen = set()
                for doc in dossiers:
                    biz = doc.get("business_intelligence", {})
                    for hosp in biz.get("hospital_affiliations", []):
                        name = hosp.get("name", "")
                        if name and name not in seen:
                            seen.add(name)
                            fin = hosp.get("financials", {})
                            qual = hosp.get("quality", {})
                            self._hospitals.append({
                                "name": name,
                                "ccn": hosp.get("npi"),
                                "city": hosp.get("city", ""),
                                "state": hosp.get("state", ""),
                                "beds": fin.get("total_beds"),
                                "star_rating": qual.get("overall_star_rating"),
                                "medicare_discharges": fin.get("medicare_discharges"),
                                "total_discharges": fin.get("total_discharges"),
                                "total_patient_revenue": fin.get("total_patient_revenue"),
                                "case_mix_index": fin.get("case_mix_index"),
                            })
            except Exception as e:
                logger.warning(f"Could not load hospital data from dossiers: {e}")

        # Load ICD-10 data
        self._icd10_categories: List[dict] = raw.get("icd10_categories", [])
        self._icd10_codes: Dict[str, dict] = {}
        for code in raw.get("icd10_codes", []):
            self._icd10_codes[code["icd10_code"]] = code

        # Load endovascular device stack
        self._device_stack: Dict = raw.get("endovascular_device_stack", {})

        # Load payer profiles
        self._payer_data: Dict = raw.get("payer_profiles", {})

        # Load vendor overrides (if any)
        self._vendor_info: Optional[Dict] = None
        self._vendor_override_counts: Dict[str, int] = {}
        self._load_vendor_overrides(settings)

        logger.info(
            f"Loaded {len(self._codes)} CPT codes, "
            f"{len(self._drg_codes)} DRG codes, "
            f"{len(self._icd10_codes)} ICD-10 codes, "
            f"{len(self._device_stack.get('classifications', []))} device classifications, "
            f"{len(self._hospitals)} hospitals for reimbursement intel"
            f"{' [vendor data active]' if self._vendor_info else ''}"
        )

    def _load_vendor_overrides(self, settings) -> None:
        """Load vendor data from disk and merge over defaults."""
        vendor_dir = settings.vendor_data_dir
        if not vendor_dir.exists():
            return

        # Find vendor JSON files (exclude schema.json)
        vendor_files = [
            f for f in vendor_dir.glob("*.json")
            if f.name not in ("schema.json", ".gitkeep")
        ]
        if not vendor_files:
            return

        # Load the most recent vendor file
        vendor_path = sorted(vendor_files, key=lambda f: f.stat().st_mtime)[-1]
        try:
            with open(vendor_path, "r") as f:
                vendor = json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load vendor data from {vendor_path}: {e}")
            return

        self._vendor_info = vendor.get("vendor_info", {})
        self._vendor_info["file"] = vendor_path.name
        counts = {}

        # Merge CPT code overrides
        for item in vendor.get("cpt_codes", []):
            code = item.get("cpt_code")
            if code and code in self._codes:
                if item.get("facility_rate") is not None:
                    self._codes[code]["facility_rate_national"] = item["facility_rate"]
                if item.get("non_facility_rate") is not None:
                    self._codes[code]["non_facility_rate_national"] = item["non_facility_rate"]
                if item.get("work_rvu") is not None:
                    self._codes[code]["work_rvu"] = item["work_rvu"]
                self._codes[code]["_vendor_override"] = True
        counts["cpt_codes"] = len(vendor.get("cpt_codes", []))

        # Merge DRG code overrides
        for item in vendor.get("drg_codes", []):
            code = item.get("drg_code")
            if code and code in self._drg_codes:
                if item.get("base_payment") is not None:
                    self._drg_codes[code]["base_payment"] = item["base_payment"]
                if item.get("relative_weight") is not None:
                    self._drg_codes[code]["relative_weight"] = item["relative_weight"]
                self._drg_codes[code]["_vendor_override"] = True
        counts["drg_codes"] = len(vendor.get("drg_codes", []))

        # Merge device cost overrides
        device_count = 0
        for item in vendor.get("device_costs", []):
            product_name = (item.get("product_name") or "").lower()
            cost = item.get("cost")
            if not product_name or cost is None:
                continue
            for cls in self._device_stack.get("classifications", []):
                for prod in cls.get("products", []):
                    if prod["name"].lower() == product_name:
                        prod["cost_range_low"] = cost
                        prod["cost_range_high"] = cost
                        prod["_vendor_override"] = True
                        if item.get("source"):
                            prod["notes"] = f"[{item['source']}] {prod.get('notes', '')}"
                        device_count += 1
        counts["device_costs"] = device_count

        # Add vendor payer profiles (prepend to defaults)
        vendor_payers = []
        for item in vendor.get("payer_rates", []):
            payer_name = item.get("payer_name")
            if not payer_name:
                continue
            profile = {
                "key": f"vendor_{payer_name.lower().replace(' ', '_')}",
                "label": f"{payer_name} (vendor)",
                "contract_type": item.get("contract_type", "drg_multiplier"),
                "professional_multiplier": item.get("professional_multiplier", 1.0),
                "facility": {},
                "implant_carveout": item.get("implant_carveout", False),
                "implant_markup": item.get("implant_markup", 0),
                "notes": f"Vendor data from {self._vendor_info.get('database_source', 'unknown')}",
                "_vendor_override": True,
            }
            ct = item.get("contract_type", "drg_multiplier")
            if ct == "drg_multiplier":
                profile["facility"] = {"type": "drg_multiplier", "multiplier": item.get("facility_multiplier", 1.0)}
            elif ct == "case_rate":
                profile["facility"] = {"type": "case_rate", "rates": item.get("case_rates", {})}
            elif ct == "pct_of_charges":
                profile["facility"] = {"type": "pct_of_charges", "pct": item.get("facility_pct_of_charges", 0.55)}
            elif ct == "per_diem":
                profile["facility"] = {"type": "per_diem", "rates": item.get("per_diem_rates", {})}
            vendor_payers.append(profile)

        if vendor_payers:
            existing = self._payer_data.get("default_profiles", [])
            self._payer_data["default_profiles"] = vendor_payers + existing
        counts["payer_rates"] = len(vendor_payers)

        # Merge ICD-10 overrides
        for item in vendor.get("icd10_codes", []):
            code = item.get("icd10_code")
            if code:
                if code in self._icd10_codes:
                    self._icd10_codes[code].update(item)
                    self._icd10_codes[code]["_vendor_override"] = True
                else:
                    self._icd10_codes[code] = item
        counts["icd10_codes"] = len(vendor.get("icd10_codes", []))

        self._vendor_override_counts = counts
        logger.info(
            f"Vendor data loaded: {self._vendor_info.get('vendor_name', '?')} "
            f"({self._vendor_info.get('database_source', '?')}). "
            f"Overrides: {counts}"
        )

    # ------------------------------------------------------------------
    # Vendor data management
    # ------------------------------------------------------------------

    def get_vendor_status(self) -> Dict:
        """Return vendor data status — what's loaded, override counts."""
        if not self._vendor_info:
            return {"active": False, "message": "No vendor data loaded. Using published estimates."}
        return {
            "active": True,
            "vendor_name": self._vendor_info.get("vendor_name"),
            "database_source": self._vendor_info.get("database_source"),
            "file": self._vendor_info.get("file"),
            "overrides": self._vendor_override_counts,
        }

    def save_vendor_data(self, data: Dict) -> Dict:
        """Validate and save vendor JSON to disk. Returns status."""
        vendor_info = data.get("vendor_info")
        if not vendor_info or not vendor_info.get("vendor_name"):
            return {"error": "vendor_info.vendor_name is required"}

        settings = get_settings()
        vendor_dir = settings.vendor_data_dir
        vendor_dir.mkdir(parents=True, exist_ok=True)

        # Add upload timestamp
        from datetime import datetime, timezone
        data["vendor_info"]["uploaded_at"] = datetime.now(timezone.utc).isoformat()

        # Save to disk
        filename = f"vendor_data.json"
        filepath = vendor_dir / filename
        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)

        # Reload
        self._load_vendor_overrides(settings)

        return {
            "status": "uploaded",
            "file": filename,
            "overrides": self._vendor_override_counts,
        }

    def clear_vendor_data(self) -> Dict:
        """Remove vendor data and revert to defaults."""
        settings = get_settings()
        vendor_dir = settings.vendor_data_dir
        removed = 0
        if vendor_dir.exists():
            for f in vendor_dir.glob("*.json"):
                if f.name != "schema.json":
                    f.unlink()
                    removed += 1

        # Reset vendor state — requires full reload
        self._vendor_info = None
        self._vendor_override_counts = {}
        return {"status": "cleared", "files_removed": removed}

    def list_codes(self, category: Optional[str] = None, q: Optional[str] = None) -> List[dict]:
        """List CPT codes, optionally filtered by category or search query."""
        results = list(self._codes.values())

        if category:
            results = [c for c in results if c["category"] == category]

        if q:
            q_lower = q.lower()
            results = [
                c
                for c in results
                if q_lower in c["cpt_code"].lower()
                or q_lower in c["procedure_name"].lower()
                or q_lower in c.get("description", "").lower()
            ]

        return results

    def get_code(self, cpt_code: str) -> Optional[dict]:
        """Get details for a single CPT code."""
        return self._codes.get(cpt_code)

    def get_codes_for_device_category(self, device_category: str) -> List[dict]:
        """Get all CPT codes that map to a given device category."""
        code_ids = self._device_category_map.get(device_category, [])
        return [self._codes[c] for c in code_ids if c in self._codes]

    def get_categories(self) -> List[dict]:
        """Return the list of procedure categories."""
        return self.categories

    def list_drg_codes(self) -> List[dict]:
        """List all DRG codes."""
        return list(self._drg_codes.values())

    def get_drg(self, drg_code: str) -> Optional[dict]:
        """Get details for a single DRG code."""
        return self._drg_codes.get(drg_code)

    def get_hospital_cost_data(self) -> Dict:
        """Return full hospital cost data (indirect costs, device costs, economics)."""
        return self._hospital_cost_data

    def get_procedure_economics(self, procedure_type: str) -> Optional[dict]:
        """Get cost vs reimbursement economics for a procedure type."""
        economics = self._hospital_cost_data.get("total_hospital_cost_vs_reimbursement", {})
        return economics.get("procedure_economics", {}).get(procedure_type)

    def get_device_costs(self, device_category: str) -> Optional[dict]:
        """Get device cost data for a category."""
        devices = self._hospital_cost_data.get("device_and_supply_costs", {})
        return devices.get("neurovascular_devices", {}).get(device_category)

    def get_hospital_list(self) -> List[dict]:
        """Return the list of hospitals extracted from physician dossiers."""
        return self._hospitals

    def get_drg_for_procedure(self, procedure_type: str) -> Optional[dict]:
        """Get DRG mapping for a procedure type."""
        mapping = self._drg_procedure_map.get(procedure_type)
        if not mapping:
            return None
        primary_drg = self._drg_codes.get(mapping.get("primary", ""))
        alt_drgs = [self._drg_codes.get(d) for d in mapping.get("alternatives", []) if d in self._drg_codes]
        return {
            "primary_drg": primary_drg,
            "alternative_drgs": alt_drgs,
            "notes": mapping.get("notes", ""),
        }

    # ------------------------------------------------------------------
    # ICD-10 lookups
    # ------------------------------------------------------------------

    def get_icd10_categories(self) -> List[dict]:
        """Return the list of ICD-10 categories."""
        return self._icd10_categories

    def list_icd10_codes(self, category: Optional[str] = None, q: Optional[str] = None) -> List[dict]:
        """List ICD-10 codes, optionally filtered by category or search query."""
        results = list(self._icd10_codes.values())

        if category:
            results = [c for c in results if c["category"] == category]

        if q:
            q_lower = q.lower()
            results = [
                c
                for c in results
                if q_lower in c["icd10_code"].lower()
                or q_lower in c["description"].lower()
                or q_lower in c.get("clinical_notes", "").lower()
            ]

        return results

    def get_icd10(self, icd10_code: str) -> Optional[dict]:
        """Get details for a single ICD-10 code."""
        return self._icd10_codes.get(icd10_code)

    # ------------------------------------------------------------------
    # Endovascular device stack
    # ------------------------------------------------------------------

    def get_device_stack(self, classification: Optional[str] = None) -> Dict:
        """Return endovascular device stack data, optionally filtered by classification."""
        if not classification:
            return self._device_stack

        classifications = [
            c for c in self._device_stack.get("classifications", [])
            if c["key"] == classification
        ]
        return {
            "metadata": self._device_stack.get("metadata", {}),
            "classifications": classifications,
        }

    # ------------------------------------------------------------------
    # Payer economics
    # ------------------------------------------------------------------

    def get_payer_profiles(self) -> Dict:
        """Return payer profile data (profiles, contract types, procedure defaults)."""
        return self._payer_data

    def calculate_payer_economics(
        self,
        procedure_type: str,
        payer_key: Optional[str] = None,
        custom_profile: Optional[Dict] = None,
        device_cost_override: Optional[float] = None,
        indirect_cost_override: Optional[float] = None,
    ) -> Dict:
        """
        Calculate reimbursement and margin for a procedure + payer combination.

        Supports all contract types: medicare, drg_multiplier, case_rate,
        pct_of_charges, per_diem, medicaid.
        """
        # Get procedure defaults
        proc = self._payer_data.get("procedure_defaults", {}).get(procedure_type)
        if not proc:
            return {"error": f"Unknown procedure type: {procedure_type}"}

        # Get payer profile
        profile = custom_profile
        if not profile and payer_key:
            profiles = self._payer_data.get("default_profiles", [])
            profile = next((p for p in profiles if p["key"] == payer_key), None)
        if not profile:
            return {"error": f"Unknown payer: {payer_key}"}

        # Costs (fixed regardless of payer)
        device_cost = device_cost_override if device_cost_override is not None else proc["default_device_cost"]
        indirect_cost = indirect_cost_override if indirect_cost_override is not None else proc["default_indirect_cost"]
        total_cost = device_cost + indirect_cost

        # Professional reimbursement (CPT × multiplier)
        cpt_code = proc.get("primary_cpt", "")
        medicare_cpt_rate = 0
        if cpt_code:
            code_data = self._codes.get(cpt_code)
            if code_data:
                medicare_cpt_rate = code_data.get("facility_rate_national", 0) or 0
        prof_multiplier = profile.get("professional_multiplier", 1.0)
        professional_reimbursement = round(medicare_cpt_rate * prof_multiplier, 2)

        # Facility reimbursement (varies by contract type)
        facility = profile.get("facility", {})
        facility_type = facility.get("type", "drg_multiplier")
        facility_reimbursement = 0
        facility_detail = ""

        if facility_type in ("drg_multiplier", "medicare", "medicaid"):
            # DRG-based: Medicare DRG payment × multiplier
            drg_code = proc.get("primary_drg", "")
            drg_data = self._drg_codes.get(drg_code, {})
            medicare_drg_payment = drg_data.get("base_payment", 0) or 0
            multiplier = facility.get("multiplier", 1.0)
            facility_reimbursement = round(medicare_drg_payment * multiplier, 2)
            facility_detail = f"DRG {drg_code} (${medicare_drg_payment:,.0f}) × {multiplier}"

        elif facility_type == "case_rate":
            # Flat case rate per procedure
            rates = facility.get("rates", {})
            facility_reimbursement = rates.get(procedure_type, 0)
            facility_detail = f"Negotiated case rate for {procedure_type}"

        elif facility_type == "pct_of_charges":
            # Percent of chargemaster billed charges
            pct = facility.get("pct", 0.55)
            chargemaster = proc.get("chargemaster_avg", 0)
            facility_reimbursement = round(chargemaster * pct, 2)
            facility_detail = f"{pct*100:.0f}% of ${chargemaster:,.0f} chargemaster"

        elif facility_type == "per_diem":
            # Per diem by care level + OR fee
            rates = facility.get("rates", {})
            icu_days = proc.get("avg_los_icu", 0)
            floor_days = proc.get("avg_los_floor", 0)
            icu_total = icu_days * rates.get("icu_per_day", 0)
            floor_total = floor_days * rates.get("floor_per_day", 0)
            or_fee = rates.get("or_flat_fee", 0)
            facility_reimbursement = round(icu_total + floor_total + or_fee, 2)
            facility_detail = (
                f"ICU: {icu_days}d × ${rates.get('icu_per_day', 0):,.0f} "
                f"+ Floor: {floor_days}d × ${rates.get('floor_per_day', 0):,.0f} "
                f"+ OR: ${or_fee:,.0f}"
            )

        # Implant carve-out
        implant_reimbursement = 0
        if profile.get("implant_carveout"):
            markup = profile.get("implant_markup", 0)
            implant_reimbursement = round(device_cost * (1 + markup), 2)

        total_reimbursement = professional_reimbursement + facility_reimbursement + implant_reimbursement
        margin = round(total_reimbursement - total_cost, 2)

        return {
            "procedure_type": procedure_type,
            "payer": profile.get("label", payer_key),
            "contract_type": profile.get("contract_type", facility_type),
            "professional": {
                "medicare_rate": medicare_cpt_rate,
                "multiplier": prof_multiplier,
                "reimbursement": professional_reimbursement,
            },
            "facility": {
                "type": facility_type,
                "detail": facility_detail,
                "reimbursement": facility_reimbursement,
            },
            "implant": {
                "carveout": profile.get("implant_carveout", False),
                "device_cost": device_cost,
                "markup": profile.get("implant_markup", 0),
                "reimbursement": implant_reimbursement,
            },
            "total_reimbursement": total_reimbursement,
            "costs": {
                "device": device_cost,
                "indirect": indirect_cost,
                "total": total_cost,
            },
            "margin": margin,
            "margin_pct": round((margin / total_cost * 100), 1) if total_cost else 0,
            "notes": profile.get("notes", ""),
        }

    def calculate_all_payer_economics(
        self, procedure_type: str, device_cost_override: Optional[float] = None
    ) -> List[Dict]:
        """Calculate economics for a procedure across all default payer profiles."""
        results = []
        for profile in self._payer_data.get("default_profiles", []):
            result = self.calculate_payer_economics(
                procedure_type=procedure_type,
                custom_profile=profile,
                device_cost_override=device_cost_override,
            )
            results.append(result)
        return results

    async def parse_operative_note(self, note_text: str, hospital_name: Optional[str] = None) -> dict:
        """
        Use LLM to extract CPT codes from an operative note.

        Returns dict with extracted codes, rationale, and confidence.
        """
        # Build code reference for the prompt
        code_ref_lines = []
        for code_data in self._codes.values():
            code_ref_lines.append(
                f"- {code_data['cpt_code']}: {code_data['procedure_name']} "
                f"(category: {code_data['category']}, setting: {code_data['setting']})"
            )
        code_reference = "\n".join(code_ref_lines)

        # Build DRG reference
        drg_ref_lines = []
        for drg_data in self._drg_codes.values():
            drg_ref_lines.append(
                f"- DRG {drg_data['drg_code']}: {drg_data['description']} "
                f"(weight: {drg_data.get('relative_weight', '?')}, "
                f"payment: ${drg_data.get('base_payment', '?'):,}, "
                f"GMLOS: {drg_data.get('geometric_mean_los', '?')} days)"
            )
        drg_reference = "\n".join(drg_ref_lines) if drg_ref_lines else "No DRG data available"

        # Build DRG procedure map reference
        drg_map_lines = []
        for proc_type, mapping in self._drg_procedure_map.items():
            drg_map_lines.append(
                f"- {proc_type}: Primary DRG {mapping.get('primary', '?')} — {mapping.get('notes', '')}"
            )
        drg_map_reference = "\n".join(drg_map_lines) if drg_map_lines else ""

        # Build ICD-10 reference
        icd10_ref_lines = []
        for icd_data in self._icd10_codes.values():
            icd10_ref_lines.append(
                f"- {icd_data['icd10_code']}: {icd_data['description']} "
                f"(category: {icd_data['category']})"
            )
        icd10_reference = "\n".join(icd10_ref_lines) if icd10_ref_lines else "No ICD-10 data available"

        # Build device stack reference for device matching
        device_stack_lines = []
        for cls in self._device_stack.get("classifications", []):
            for prod in cls.get("products", []):
                device_stack_lines.append(
                    f"- [{cls['key']}] {prod['name']} ({prod['manufacturer']}) "
                    f"— ${prod['cost_range_low']:,}-${prod['cost_range_high']:,}"
                )
        device_stack_reference = "\n".join(device_stack_lines) if device_stack_lines else "No device stack data available"

        # Build optional hospital context
        hospital_context = ""
        if hospital_name:
            hosp = next((h for h in self._hospitals if h["name"] == hospital_name), None)
            if hosp:
                revenue_str = f"${hosp['total_patient_revenue']:,.0f}" if hosp.get("total_patient_revenue") else "N/A"
                hospital_context = (
                    f"\n\nTHIS CASE IS AT: {hosp['name']} ({hosp.get('city', '')}, {hosp.get('state', '')}). "
                    f"{hosp.get('beds', '?')} beds, {hosp.get('star_rating', '?')}-star CMS rating, "
                    f"Medicare discharges: {hosp.get('medicare_discharges', '?'):,}, "
                    f"Total discharges: {hosp.get('total_discharges', '?'):,}, "
                    f"Total patient revenue: {revenue_str}, "
                    f"Case mix index: {hosp.get('case_mix_index', '?')}. "
                    f"Use this hospital's data to refine your cost estimates."
                )

        system_prompt = f"""You are a medical coding specialist focused on neurovascular interventional procedures.

Given an operative note, identify ALL applicable CPT codes from the following reference list. Only use codes from this list.

AVAILABLE CPT CODES:
{code_reference}

CRITICAL CODING RULES:
1. **61710 is OPEN SURGERY** (trephination/craniotomy). NEVER use 61710 for endovascular/transcatheter procedures. For endovascular coil embolization of intracranial aneurysms, use 61624.
2. **Bilateral catheterization**: When both right and left ICA are catheterized with separate angiographic runs, code the first side as 36224 and the contralateral side as 36224-59 or use 36228 for the additional vessel study.
3. **3D rotational angiography**: When 3D rotational angiography and/or 3D reconstructions are performed, add 76376 or 76377.
4. **Closure devices**: When an AngioSeal, Perclose, or other arterial closure device is used, consider G0269.
5. **Add-on codes**: 61626 is an add-on to 61624 for each additional vessel embolized. 36228 is for each additional intracranial vessel study beyond the primary.
6. **Bundling**: Microcatheter placement for the therapeutic procedure is bundled into the embolization code (61624). Diagnostic catheterization performed as a separate identifiable service may be reported with modifier -59.
7. **Supervision & Interpretation**: For 2026, radiological S&I is bundled into 61624. Do not separately code 75894/75898.
8. Be thorough — identify EVERY separately billable procedure documented in the note.

For each code you identify, provide:
1. The CPT code (with modifier if applicable, e.g., 36224-59)
2. A brief rationale explaining why this code applies based on the operative note
3. A confidence level: "high", "medium", or "low"

Also note any coding considerations (e.g., bundled codes, add-on requirements, modifier usage).

ICD-10 DIAGNOSIS CODING:
Identify ALL applicable ICD-10 diagnosis codes based on the operative note. Select the MOST SPECIFIC code possible (laterality, vessel, etiology). Only use codes from this list.

AVAILABLE ICD-10 CODES:
{icd10_reference}

ICD-10 CODING RULES:
1. Code the principal diagnosis (the condition that necessitated the procedure)
2. Code secondary diagnoses that affect clinical care or resource use
3. Always specify laterality when documented (right vs left)
4. Distinguish thrombosis (I63.0x-I63.3x) from embolism (I63.1x-I63.4x) when documented
5. For unruptured aneurysms use I67.1; for ruptured SAH use I60.x with specific artery
6. Code vessel stenosis/occlusion (I65-I66) as secondary when it's the underlying condition
7. Include TIA codes (G45.x) only when documented as the presenting diagnosis

DEVICE IDENTIFICATION:
Match every device, catheter, wire, sheath, particle, coil, stent, balloon, or closure device mentioned in the operative note to a specific product from the device stack below. Use exact product names when you can identify them. If a device is mentioned generically (e.g., "microcatheter"), identify the most likely product based on context.

DEVICE STACK REFERENCE:
{device_stack_reference}

DEVICE MATCHING RULES:
1. Match by brand name when explicitly stated (e.g., "Glidesheath Slender" → Terumo Glidesheath Slender)
2. Match by model name (e.g., "Benchmark" → Penumbra Benchmark Catheter)
3. Match by generic description + context when no brand given (e.g., "6F sheath" → classify as sheath, note brand unknown)
4. Include ALL devices used — sheaths, guide catheters, select catheters, microcatheters, wires, embolic agents, closure devices
5. Note the quantity if multiple of the same device were used (e.g., "15 coils")

HOSPITAL DRG REIMBURSEMENT:
In addition to physician CPT codes, identify the most likely MS-DRG (Medicare Severity Diagnosis Related Group) for the hospital facility payment. Use the procedure-to-DRG mapping below.

AVAILABLE DRG CODES:
{drg_reference}

PROCEDURE-TO-DRG MAPPING:
{drg_map_reference}

For the DRG, consider:
- Whether the patient has MCC (Major Complication/Comorbidity), CC, or neither
- The primary procedure type (open vs endovascular)
- The principal diagnosis (e.g., SAH, ischemic stroke, unruptured aneurysm)

HOSPITAL COST ANALYSIS:
Estimate the total hospital costs (direct + indirect) for this case. Use the device and cost data below.

DEVICE COST REFERENCE:
- Aspiration catheters: $2,500-$5,000 (hospital cost)
- Stent retrievers: $4,000-$9,000 (hospital cost)
- Intracranial coils: $1,200-$3,500 per coil, avg 6-15 per case ($6,000-$25,000 total)
- Flow diverters: $9,000-$18,000 (hospital cost)
- Intracranial stents: $3,500-$7,500 (hospital cost)
- Microcatheters: $500-$1,800 each
- Guide/intermediate catheters: $800-$2,500
- Guidewires: $200-$800
- Embolic agents (Onyx/PHIL): $1,800-$3,500 per vial
- Balloons: $1,500-$3,500
- Closure devices: $150-$300

INDIRECT COST REFERENCE (per neurovascular case):
- Nursing/staffing (neuro-ICU): $8,000-$18,000
- Anesthesia services: $3,000-$7,000
- Pharmacy (contrast, heparin, drugs): $2,500-$8,000
- Lab/diagnostics: $1,500-$4,500
- Admin/overhead: $3,500-$6,500
- Facility/plant: $2,200-$4,200
- Capital equipment depreciation (biplane suite): $1,500-$4,000
{hospital_context}
Respond in JSON format:
{{
  "extracted_codes": [
    {{
      "cpt_code": "XXXXX",
      "rationale": "Brief explanation of why this code applies",
      "confidence": "high|medium|low"
    }}
  ],
  "icd10_codes": [
    {{
      "icd10_code": "XXX.XX",
      "description": "Diagnosis description",
      "rationale": "Why this diagnosis applies based on the operative note",
      "is_principal": true,
      "specificity_note": "Any note about coding specificity"
    }}
  ],
  "devices_used": [
    {{
      "classification": "sheath|guide_catheter|microcatheter|etc",
      "product_name": "Exact product name from device stack",
      "manufacturer": "Manufacturer name",
      "quantity": 1,
      "cost_range_low": 0,
      "cost_range_high": 0,
      "note_excerpt": "Brief quote from operative note identifying this device"
    }}
  ],
  "total_device_cost_estimate": {{
    "low": 0,
    "high": 0
  }},
  "drg_assessment": {{
    "primary_drg": "XXX",
    "drg_description": "Description",
    "rationale": "Why this DRG applies based on the procedure and diagnosis",
    "estimated_hospital_payment": 00000,
    "relative_weight": 0.0,
    "expected_los": 0.0,
    "mcc_cc_status": "with_mcc|with_cc|without_cc_mcc",
    "alternative_drg": "XXX",
    "alternative_rationale": "When the alternative DRG might apply instead"
  }},
  "hospital_cost_breakdown": {{
    "device_costs": {{
      "items": [
        {{"device": "Device name", "estimated_cost": 0000}}
      ],
      "total_device_cost": 00000
    }},
    "indirect_costs": {{
      "nursing_icu": 00000,
      "anesthesia": 00000,
      "pharmacy": 00000,
      "lab_diagnostics": 0000,
      "admin_overhead": 0000,
      "facility": 0000,
      "capital_equipment": 0000,
      "total_indirect_cost": 00000
    }},
    "total_hospital_cost": 00000,
    "drg_payment": 00000,
    "estimated_margin": 00000,
    "margin_notes": "Whether this case is profitable or a loss for the hospital and why"
  }},
  "coding_notes": "Any overall coding considerations or warnings",
  "total_estimated_physician_reimbursement": "Sum of physician CPT facility rates (approximate)",
  "total_estimated_hospital_reimbursement": "DRG-based hospital facility payment (approximate)"
}}"""

        messages = [{"role": "user", "content": f"OPERATIVE NOTE:\n\n{note_text}"}]

        llm = LLMService()
        response_text = await llm.generate(
            system_prompt=system_prompt,
            messages=messages,
            temperature=0.2,
            max_tokens=4000,
        )

        # Parse JSON response
        try:
            response_text = response_text.strip()
            if response_text.startswith("```"):
                response_text = response_text.split("```")[1]
                if response_text.startswith("json"):
                    response_text = response_text[4:]
                response_text = response_text.strip()

            parsed = json.loads(response_text)

            # Enrich extracted codes with full data from our database
            for item in parsed.get("extracted_codes", []):
                # Handle modifier codes like "36224-59"
                base_code = item["cpt_code"].split("-")[0].strip()
                code_data = self._codes.get(base_code)
                if code_data:
                    item["procedure_name"] = code_data["procedure_name"]
                    item["facility_rate"] = code_data.get("facility_rate_national")
                    item["setting"] = code_data.get("setting")
                    item["device_categories"] = code_data.get("device_categories", [])

            # Enrich extracted ICD-10 codes with full data from our database
            for item in parsed.get("icd10_codes", []):
                icd_data = self._icd10_codes.get(item.get("icd10_code", ""))
                if icd_data:
                    item["description"] = icd_data.get("description", item.get("description", ""))
                    item["category"] = icd_data.get("category")
                    item["commonly_paired_cpt"] = icd_data.get("commonly_paired_cpt", [])
                    item["drg_crosswalk"] = icd_data.get("drg_crosswalk", [])

            # Enrich matched devices with data from our device stack
            device_stack_lookup = {}
            for cls in self._device_stack.get("classifications", []):
                for prod in cls.get("products", []):
                    device_stack_lookup[prod["name"].lower()] = {
                        **prod,
                        "classification": cls["key"],
                        "classification_label": cls["label"],
                    }

            for item in parsed.get("devices_used", []):
                prod_name = (item.get("product_name") or "").lower()
                match = device_stack_lookup.get(prod_name)
                if match:
                    item["cost_range_low"] = match["cost_range_low"]
                    item["cost_range_high"] = match["cost_range_high"]
                    item["manufacturer"] = match["manufacturer"]
                    item["classification"] = match["classification"]
                    item["classification_label"] = match["classification_label"]
                    item["matched"] = True
                else:
                    item["matched"] = False

            # Enrich DRG assessment with full data from our database
            drg_assessment = parsed.get("drg_assessment")
            if drg_assessment and drg_assessment.get("primary_drg"):
                drg_data = self._drg_codes.get(drg_assessment["primary_drg"])
                if drg_data:
                    drg_assessment["drg_description"] = drg_data.get("description", drg_assessment.get("drg_description", ""))
                    drg_assessment["estimated_hospital_payment"] = drg_data.get("base_payment", drg_assessment.get("estimated_hospital_payment"))
                    drg_assessment["relative_weight"] = drg_data.get("relative_weight", drg_assessment.get("relative_weight"))
                    drg_assessment["expected_los"] = drg_data.get("geometric_mean_los", drg_assessment.get("expected_los"))
                    drg_assessment["arithmetic_mean_los"] = drg_data.get("arithmetic_mean_los")
                    drg_assessment["neurovascular_context"] = drg_data.get("neurovascular_context", "")

                # Enrich alternative DRG
                alt_code = drg_assessment.get("alternative_drg")
                if alt_code:
                    alt_data = self._drg_codes.get(alt_code)
                    if alt_data:
                        drg_assessment["alternative_description"] = alt_data.get("description", "")
                        drg_assessment["alternative_payment"] = alt_data.get("base_payment")

            return parsed

        except json.JSONDecodeError:
            return {
                "error": "Failed to parse LLM response",
                "raw_response": response_text,
                "extracted_codes": [],
            }


@lru_cache(maxsize=1)
def get_reimbursement_service() -> ReimbursementService:
    """Singleton accessor for ReimbursementService."""
    return ReimbursementService()
