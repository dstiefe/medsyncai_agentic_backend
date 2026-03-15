"""
AIS Clinical Engine — BaseEngine wrapper for the orchestrator chat pipeline.

Wraps the clinical decision pipeline (NLPService → IVTOrchestrator →
RuleEngine → DecisionEngine) and returns formatted text via _build_return().

The REST API (routes.py) remains the primary interface for the frontend;
this engine serves the chat/stream SSE pipeline.
"""

import re
from typing import List

from medsync_ai_v2.base_engine import BaseEngine

from .agents.ivt_orchestrator import IVTOrchestrator
from .data.loader import load_recommendations
from .models.clinical import ClinicalDecisionState, ParsedVariables
from .services.decision_engine import DecisionEngine
from .services.nlp_service import NLPService
from .services.rule_engine import RuleEngine


# Patterns for classifying incoming queries
_CLINICAL_PARAMS = re.compile(
    r"""
    nihss | aspects | last\s*known\s*well | lkw |
    \bocclusion\b | \bm1\b | \bm2\b | \bica\b | \bbasilar\b | \bt-ica\b |
    \bmrs\b | pre.?stroke |
    \d{1,3}\s*[-\s]*(?:y/?o|year|yr) |       # age patterns
    \b(?:sbp|dbp)\b | \d{2,3}\s*/\s*\d{2,3}  # BP patterns
    """,
    re.IGNORECASE | re.VERBOSE,
)

_AIS_KEYWORDS = re.compile(
    r"""
    guideline | recommendation | \bivt\b | \bevt\b |
    thrombolysis | thrombectomy | reperfusion |
    contraindication | eligib | \bais\b |
    acute\s+ischemic\s+stroke |
    table\s*[48] | disabling | blood\s*pressure\s*target |
    alteplase | tenecteplase
    """,
    re.IGNORECASE | re.VERBOSE,
)


class AisClinicalEngine(BaseEngine):
    """BaseEngine wrapper for the AIS clinical decision pipeline."""

    def __init__(self):
        super().__init__(name="ais_clinical_engine", skill_path=None)
        self._nlp_service = NLPService()
        self._ivt_orchestrator = IVTOrchestrator()
        self._rule_engine = RuleEngine()
        self._decision_engine = DecisionEngine()

    async def run(self, input_data: dict, session_state: dict) -> dict:
        raw_query = input_data.get("raw_query", "")
        query = input_data.get("normalized_query", raw_query)

        query_type = self._classify_query(query)

        if query_type == "scenario":
            return await self._run_scenario(query, session_state)
        elif query_type == "guideline_qa":
            return self._run_guideline_qa(query)
        else:
            return self._build_return(
                status="complete",
                result_type="out_of_scope",
                data={
                    "formatted_text": (
                        "This question falls outside the scope of the "
                        "2026 AHA/ASA Acute Ischemic Stroke Guidelines."
                    )
                },
                classification={"query_type": "out_of_scope"},
                confidence=0.95,
            )

    # ------------------------------------------------------------------
    # Query classification
    # ------------------------------------------------------------------

    @staticmethod
    def _classify_query(query: str) -> str:
        has_clinical = bool(_CLINICAL_PARAMS.search(query))
        has_ais = bool(_AIS_KEYWORDS.search(query))

        if has_clinical:
            return "scenario"
        if has_ais:
            return "guideline_qa"
        return "out_of_scope"

    # ------------------------------------------------------------------
    # Scenario pipeline
    # ------------------------------------------------------------------

    async def _run_scenario(self, query: str, session_state: dict) -> dict:
        # 1. Parse (LLM call)
        parsed = await self._nlp_service.parse_scenario(query)

        # 2. Evaluate (deterministic)
        ivt_result = self._ivt_orchestrator.evaluate(parsed)
        evt_result = self._rule_engine.evaluate(parsed)
        decision_state = self._decision_engine.compute_effective_state(
            parsed, ivt_result, evt_result
        )

        # 3. Store in session for potential multi-turn
        session_state["last_clinical_assessment"] = {
            "patient": parsed.model_dump(),
            "decision_state": decision_state.model_dump(),
        }

        # 4. Format
        formatted = self._format_decision(
            parsed, ivt_result, evt_result, decision_state
        )

        return self._build_return(
            status="complete",
            result_type="clinical_guidance",
            data={
                "formatted_text": formatted,
                "decision_state": decision_state.model_dump(),
            },
            classification={"query_type": "scenario"},
            confidence=0.9,
        )

    # ------------------------------------------------------------------
    # Guideline Q&A
    # ------------------------------------------------------------------

    def _run_guideline_qa(self, query: str) -> dict:
        all_recs = load_recommendations()
        query_lower = query.lower()
        keywords = [w for w in query_lower.split() if len(w) > 3]

        scored = []
        for rec in all_recs:
            text = rec.get("text", "").lower()
            title = rec.get("sectionTitle", "").lower()
            score = sum(
                (2 if kw in title else 0) + (1 if kw in text else 0)
                for kw in keywords
            )
            if score > 0:
                scored.append((score, rec))

        scored.sort(key=lambda x: x[0], reverse=True)
        top = [r for _, r in scored[:5]]

        if not top:
            formatted = "No relevant recommendations found for this question in the 2026 AHA/ASA AIS Guidelines."
        else:
            lines = [f"Based on {len(top)} relevant guideline recommendation(s):\n"]
            for rec in top:
                cor = rec.get("cor", "")
                loe = rec.get("loe", "")
                lines.append(
                    f"- **[COR {cor} / LOE {loe}]** Section {rec['section']}, "
                    f"Rec {rec['recNumber']}: {rec['text']}"
                )
            formatted = "\n".join(lines)

        return self._build_return(
            status="complete",
            result_type="clinical_guidance",
            data={"formatted_text": formatted},
            classification={"query_type": "guideline_qa"},
            confidence=0.7,
        )

    # ------------------------------------------------------------------
    # Text formatter
    # ------------------------------------------------------------------

    def _format_decision(
        self,
        parsed: ParsedVariables,
        ivt_result: dict,
        evt_result: dict,
        ds: ClinicalDecisionState,
    ) -> str:
        sections: List[str] = []

        # Headline
        sections.append(f"**{ds.headline}**\n")

        # Patient summary
        patient_parts = []
        if parsed.age is not None:
            patient_parts.append(f"{parsed.age}-year-old")
        if parsed.sex:
            patient_parts.append(parsed.sex)
        if parsed.nihss is not None:
            patient_parts.append(f"NIHSS {parsed.nihss}")
        if parsed.aspects is not None:
            patient_parts.append(f"ASPECTS {parsed.aspects}")
        if parsed.vessel:
            patient_parts.append(f"{parsed.vessel} occlusion")
        if parsed.timeHours is not None:
            patient_parts.append(f"{parsed.timeHours}h from LKW")
        if parsed.prestrokeMRS is not None:
            patient_parts.append(f"prestroke mRS {parsed.prestrokeMRS}")
        if parsed.sbp is not None or parsed.dbp is not None:
            bp = f"{parsed.sbp or '?'}/{parsed.dbp or '?'} mmHg"
            patient_parts.append(f"BP {bp}")

        if patient_parts:
            sections.append(f"**Patient:** {', '.join(patient_parts)}\n")

        # IVT assessment
        ivt_elig = ds.effective_ivt_eligibility
        risk_tier = ivt_result.get("riskTier", "")
        ivt_label = {
            "eligible": "Eligible",
            "contraindicated": "Contraindicated",
            "caution": "Eligible with Caution",
            "pending": "Pending Assessment",
        }.get(ivt_elig, ivt_elig)

        ivt_lines = [f"**IV Thrombolysis (IVT):** {ivt_label}"]

        contras = ivt_result.get("contraindications", [])
        if contras:
            ivt_lines.append("  Absolute contraindications: " + ", ".join(contras))

        warnings = ivt_result.get("warnings", [])
        if warnings:
            ivt_lines.append("  Relative contraindications: " + ", ".join(warnings))

        # Disabling assessment
        disabling = ivt_result.get("disablingAssessment", {})
        if isinstance(disabling, dict) and disabling.get("isDisabling") is not None:
            is_dis = disabling["isDisabling"]
            ivt_lines.append(
                f"  Deficit assessment: {'Disabling' if is_dis else 'Non-disabling'}"
            )

        sections.append("\n".join(ivt_lines) + "\n")

        # IVT recommendations
        ivt_recs = ivt_result.get("recommendations", [])
        if ivt_recs:
            rec_lines = ["**IVT Recommendations:**"]
            for rec in ivt_recs:
                if hasattr(rec, "model_dump"):
                    rec = rec.model_dump()
                cor = rec.get("cor", "")
                loe = rec.get("loe", "")
                text = rec.get("text", "")
                rec_lines.append(f"- [COR {cor} / LOE {loe}] {text}")
            sections.append("\n".join(rec_lines) + "\n")

        # EVT assessment
        evt_recs_data = evt_result.get("recommendations", {})
        has_evt = False
        if isinstance(evt_recs_data, dict):
            all_evt_recs = []
            for cat_recs in evt_recs_data.values():
                if isinstance(cat_recs, list):
                    all_evt_recs.extend(cat_recs)
            if all_evt_recs:
                has_evt = True
                evt_lines = ["**Endovascular Thrombectomy (EVT):**"]
                for rec in all_evt_recs:
                    if hasattr(rec, "model_dump"):
                        rec = rec.model_dump()
                    cor = rec.get("cor", "")
                    loe = rec.get("loe", "")
                    text = rec.get("text", "")
                    evt_lines.append(f"- [COR {cor} / LOE {loe}] {text}")
                sections.append("\n".join(evt_lines) + "\n")

        if not has_evt:
            if parsed.isLVO:
                sections.append("**EVT:** LVO detected, EVT may be indicated.\n")
            else:
                sections.append("**EVT:** No EVT recommendations fired for this scenario.\n")

        # BP warning
        if ds.bp_warning:
            sections.append(f"**Blood Pressure:** {ds.bp_warning}\n")

        # Notes
        notes = ivt_result.get("notes", [])
        evt_notes = evt_result.get("notes", [])
        all_notes = list(notes) + list(evt_notes)
        if all_notes:
            note_lines = ["**Notes:**"]
            for note in all_notes:
                if hasattr(note, "model_dump"):
                    note = note.model_dump()
                if isinstance(note, dict):
                    severity = note.get("severity", "info")
                    text = note.get("text", str(note))
                else:
                    severity = "info"
                    text = str(note)
                prefix = {"danger": "!!!", "warning": "!!", "info": ""}.get(severity, "")
                note_lines.append(f"- {prefix} {text}".strip())
            sections.append("\n".join(note_lines) + "\n")

        # Disclaimer
        sections.append(
            "*This assessment reflects the 2026 AHA/ASA Acute Ischemic Stroke "
            "Guidelines and does not replace clinical judgment.*"
        )

        return "\n".join(sections)
