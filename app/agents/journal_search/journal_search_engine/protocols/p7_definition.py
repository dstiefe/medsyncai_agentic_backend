"""P7: Definition extraction — clinical term/scale definitions."""

from __future__ import annotations
from ..models.query import ClassifiedIntent, ProtocolResult
from .db_access import _get_connection, NOT_REPORTED

# Standard clinical definitions used in stroke trials
STANDARD_DEFINITIONS = {
    "tici": {
        "scale": "Thrombolysis in Cerebral Infarction (TICI)",
        "grades": {
            "0": "No perfusion — no antegrade flow beyond the point of occlusion",
            "1": "Penetration with minimal perfusion — contrast passes beyond the obstruction but fails to opacify the entire cerebral bed distal to the obstruction",
            "2a": "Partial perfusion — contrast passes beyond the obstruction and opacifies the arterial bed distal to the obstruction, but filling is incomplete (<50% of the expected territory)",
            "2b": "Partial perfusion — complete filling of the expected vascular territory, but filling is slower than normal (≥50% but <100%)",
            "2b50": "Near-complete perfusion — filling of ≥50% but <90% of the expected territory (used in some trials)",
            "2c": "Near-complete perfusion — filling of ≥90% but not 100% of the expected territory",
            "3": "Complete perfusion — full flow in all distal branches with normal hemodynamics",
        },
        "notes": "TICI 2b-3 is the most common reperfusion success endpoint. Some newer trials use TICI 2c-3.",
    },
    "mrs": {
        "scale": "Modified Rankin Scale (mRS)",
        "grades": {
            "0": "No symptoms at all",
            "1": "No significant disability despite symptoms — able to carry out all usual duties and activities",
            "2": "Slight disability — unable to carry out all previous activities but able to look after own affairs without assistance",
            "3": "Moderate disability — requiring some help but able to walk without assistance",
            "4": "Moderately severe disability — unable to walk without assistance and unable to attend to own bodily needs without assistance",
            "5": "Severe disability — bedridden, incontinent, and requiring constant nursing care and attention",
            "6": "Dead",
        },
        "notes": "mRS 0-2 (functional independence) is the most common primary endpoint in EVT trials. Some large-core trials use mRS 0-3.",
    },
    "nihss": {
        "scale": "National Institutes of Health Stroke Scale (NIHSS)",
        "description": "Quantitative measure of stroke-related neurological deficit. Scores range from 0 (no deficit) to 42 (maximum deficit). Assessed across 11 domains: consciousness, gaze, visual fields, facial palsy, motor arm, motor leg, ataxia, sensory, language, dysarthria, extinction/inattention.",
        "ranges": {
            "0": "No stroke symptoms",
            "1-4": "Minor stroke",
            "5-15": "Moderate stroke",
            "16-20": "Moderate-severe stroke",
            "21-42": "Severe stroke",
        },
    },
    "aspects": {
        "scale": "Alberta Stroke Program Early CT Score (ASPECTS)",
        "description": "10-point quantitative score for early ischemic change on non-contrast CT. Scores range from 0 (complete MCA territory infarct) to 10 (no early ischemic changes). Each of 10 defined regions in the MCA territory receives 1 point if normal. Points subtracted for early ischemic changes in each region.",
        "regions": "Caudate (C), Lentiform (L), Internal Capsule (IC), Insular Ribbon (I), M1-M6 (anterior/posterior MCA cortex at two levels)",
        "ranges": {
            "8-10": "Small core — favorable for EVT",
            "6-7": "Moderate core",
            "3-5": "Large core — studied in ANGEL-ASPECT, SELECT2, RESCUE-Japan LIMIT, TENSION, LASTE",
            "0-2": "Very large core — limited evidence",
        },
    },
    "pc-aspects": {
        "scale": "Posterior Circulation ASPECTS (pc-ASPECTS)",
        "description": "10-point score for early ischemic changes in the posterior circulation territory on CT or DWI. Regions: left/right thalamus, left/right cerebellum, left/right PCA territory, pons, midbrain.",
    },
}


async def execute_p7(intent: ClassifiedIntent) -> ProtocolResult:
    """Look up or construct a clinical definition."""
    term = (intent.definition_term or intent.field_requested or intent.original_query or "").lower().strip()

    # Check standard definitions
    for key, defn in STANDARD_DEFINITIONS.items():
        if key in term:
            return ProtocolResult(
                protocol="P7",
                query=intent.original_query,
                data={"term": key, "definition": defn},
                data_found=True,
                source_tables=["standard_definitions"],
            )

    # sICH: return per-trial definitions
    if "sich" in term or "symptomatic" in term and ("hemorrhage" in term or "ich" in term):
        conn = _get_connection()
        rows = conn.execute("""
            SELECT s.trial_acronym, so.sich_definition,
                   so.sich_intervention_pct, so.sich_control_pct, so.sich_p_value
            FROM safety_outcomes so
            JOIN studies s ON s.study_id = so.study_id
            WHERE so.sich_definition IS NOT NULL
            ORDER BY s.pub_year DESC
        """).fetchall()
        conn.close()

        definitions = [dict(r) for r in rows]
        return ProtocolResult(
            protocol="P7",
            query=intent.original_query,
            data={
                "term": "sICH",
                "description": "Symptomatic intracranial hemorrhage — definitions vary by trial",
                "definitions_by_trial": definitions,
            },
            data_found=bool(definitions),
            source_tables=["safety_outcomes"],
        )

    # Fallback to P8
    from .p8_extracted_table import execute_p8
    return await execute_p8(intent)
