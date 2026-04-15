# qa_v4 Atomization Canary Sweep

Copy these queries into cowork one by one. For each, check:

1. **Atom log line** — server console should show
   `atom_retriever: section <X> selected N/M atoms` and
   `Stage 2 SWITCH: section <X> atom-filtered …` for any atomized
   section the query routes to.
2. **Details panel** — verbatim text matches only the listed atom
   text, not the surrounding table rows.
3. **Summary** — the one-line LLM summary reflects only the
   selected atom(s), not the whole table.

Any query whose Details panel still dumps the full table or whose
summary mentions unrelated rows is a failure. Classify, fix, report.

---

## Table 7 — IVT administration / post-care

| ID | Query | Expected atom(s) |
|---|---|---|
| T7-C1 | Patient on IV alteplase just developed a severe headache. What do I do? | `tbl7.post_complication_trigger` (only) |
| T7-C2 | What is the alteplase dose for AIS? | `tbl7.alteplase_dose` (primary) |
| T7-C3 | How do I dose tenecteplase for a 65 kg patient? | `tbl7.tenecteplase_dose` (primary) |
| T7-C4 | How often do I check BP after IVT? | `tbl7.post_monitoring_schedule` + `tbl7.post_bp_management` |
| T7-C5 | When do I get follow-up imaging after thrombolysis? | `tbl7.post_followup_imaging` (only) |
| T7-C6 | Is alteplase approved for pediatric stroke? | `tbl7.fn_pediatric_dosing` |

## Table 8 — IVT additional conditions

| ID | Query | Expected atom(s) |
|---|---|---|
| T8-C1 | Can I give IVT in pregnancy? | `tbl8.rel.pregnancy_and_post_partum_period` (only) |
| T8-C2 | Patient on DOAC — can I give alteplase? | `tbl8.rel.doac_exposure` (only) |
| T8-C3 | Aortic dissection — is IVT contraindicated? | `tbl8.abs.aortic_arch_dissection` (only) |
| T8-C4 | Patient has prior ICH. Can I thrombolyse? | `tbl8.rel.prior_ich` (primary) |
| T8-C5 | Infective endocarditis + AIS — IVT? | `tbl8.abs.infective_endocarditis` (only) |
| T8-C6 | IVT after recent GI bleed? | `tbl8.ben.history_of_gi_gu_bleeding` + `tbl8.rel.recent_gi_gu_bleeding_within_21_days` |
| T8-C7 | Moya-Moya disease and IVT safety | `tbl8.ben.moya_moya` (primary) |

## Table 5 — sICH management

| ID | Query | Expected atom(s) |
|---|---|---|
| T5-C1 | How do I reverse alteplase if the patient bleeds? | `tbl5.sich.stop_alteplase_infusion…` + `tbl5.sich.cryoprecipitate…` (top picks) |
| T5-C2 | What labs do I order for post-IVT hemorrhage? | `tbl5.sich.emergent_cbc_pt_inr_aptt_fibrinogen…` |
| T5-C3 | Tranexamic acid dose for alteplase-associated ICH? | `tbl5.sich.tranexamic_acid_1000_mg…` |

## Table 6 — angioedema

| ID | Query | Expected atom(s) |
|---|---|---|
| T6-C1 | Patient got angioedema from alteplase — first steps? | `tbl6.angio.maintain_airway` + `tbl6.angio.discontinue_iv_thrombolytic…` |
| T6-C2 | Methylprednisolone dose for thrombolysis angioedema? | `tbl6.angio.administer_iv_methylprednisolone_125_mg` (only) |
| T6-C3 | Is icatibant used for tPA angioedema? | `tbl6.angio.icatibant_a_selective_bradykinin_b2_receptor_antagonist…` |

## Table 9 — DAPT trials

| ID | Query | Expected atom(s) |
|---|---|---|
| T9-C1 | What did CHANCE show? | `tbl9.dapt.chance` (only) |
| T9-C2 | Ticagrelor DAPT trials for stroke | `tbl9.dapt.thales` + `tbl9.dapt.chance_2` |
| T9-C3 | DAPT trial with CYP2C19 genotyping | `tbl9.dapt.chance_2` (only) |

## Table 3 — extended window imaging criteria

| ID | Query | Expected atom(s) |
|---|---|---|
| T3-C1 | DWI/FLAIR mismatch — which trials used it? | `tbl3.wake_up` + `tbl3.thaws` |
| T3-C2 | What imaging criteria did EXTEND use? | `tbl3.extend` (primary) |
| T3-C3 | Core volume cutoff in TIMELESS trial | `tbl3.timeless` (primary) |

## Table 4 — clearly disabling deficits

| ID | Query | Expected atom(s) |
|---|---|---|
| T4-C1 | Is complete hemianopsia clearly disabling for IVT eligibility? | `tbl4.disabling.complete_hemianopsia` (only) |
| T4-C2 | Isolated facial droop — does that rule in IVT? | `tbl4.not_disabling.facial_droop` (only) |
| T4-C3 | Severe aphasia — is it disabling? | `tbl4.disabling.severe_aphasia` (primary) |

## Regression guardrails — NON-atomized sections

These must continue to work exactly as before. No atom log lines
should appear for these queries. Details panel should render the
legacy rss row set for the matched section(s).

| ID | Query | Expected behavior |
|---|---|---|
| REG-1 | What is the time window for IV alteplase? | §4.6 / §4.6.1 — legacy rendering |
| REG-2 | Aspirin for AIS in sinus rhythm? | §4.8(1) + §4.8(5) — legacy rendering |
| REG-3 | BP targets during and after AIS? | §4.3 — legacy rendering |
| REG-4 | 65yo NIHSS 18 M1 occlusion LKW 2h | reperfusion_agent (CMI path, not Q&A) |

---

## Known non-blockers (flagged, not fixing in this sweep)

- **T4 "severe aphasia"** may return up to 7 atoms (NIHSS is a
  universal anchor across Table 4). Top pick still correct.
- **"Show me all absolute contraindications"** still routes via
  the legacy category path; atom retrieval not wired to list mode.
- **T3 TIMELESS vs TRACE-3 comparison** may return all 7 atoms
  via the zero-match PDF-order fallback — the atoms do not yet
  carry `comparison_query` in their intent_affinity.
- **parent_section "4.6" / "4.8"** on all table atoms is a
  best-guess; not a retrieval concern but needs PDF cross-check.
