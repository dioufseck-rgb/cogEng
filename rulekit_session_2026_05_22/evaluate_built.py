"""
evaluate_built.py — evaluate built trees against test cases.

Loads built_pa.pkl and built_fcba.pkl and runs realistic case bundles
against them. End-to-end proof: policies in (text files), trees out
(pickle), cases evaluate correctly.
"""

import sys
import os
import pickle

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from rulekit import Kleene, FactBundle, format_trace


T, F, U = Kleene.TRUE, Kleene.FALSE, Kleene.UNDETERMINED


# PA cases
PA_CASE_1 = {
    "pa.radic.diagnosis": T, "pa.radic.nerve_root_compression": T,
    "pa.radic.symptoms_pain": T, "pa.radic.symptoms_numbness": T,
    "pa.radic.symptoms_weakness": T,
    "pa.myel.diagnosis": F, "pa.hern.diagnosis": F,
    "pa.imaging.mri": T, "pa.imaging.ct_myelogram": F,
    "pa.imaging.demonstrates_pathology": T,
    "pa.pt.completed_six_weeks": T, "pa.pt.supervised": T,
    "pa.pt.functional_outcomes_documented": T, "pa.pt.directed_at_cervical": T,
    "pa.exc.myelopathy_confirmed": F, "pa.exc.myelopathy_is_primary": F,
    "pa.exc.pt_completed_four_weeks": F,
    "pa.exc.physician_documents_interv_risk": F,
    "pa.pharma.nsaid_trial_a": T, "pa.pharma.nsaid_trial_b": F,
    "pa.pharma.muscle_relaxant_trial": F, "pa.pharma.neuropathic_trial": T,
    "pa.pharma.corticosteroid_trial": F,
    "pa.interv.esi": T, "pa.interv.medial_branch_block": F,
    "pa.interv.trigger_point": F,
    "pa.surg_imaging.demonstrates_pathology_a": T,
    "pa.surg_imaging.demonstrates_pathology_b": T,
    "pa.surg_imaging.interpreted_by_radiologist": T,
    "pa.surg_imaging.interpreted_by_specialist": F,
    "pa.doc.attestation_conservative": T, "pa.doc.clinical_rationale": T,
    "pa.doc.functional_limitations": T,
    "pa.doc.surgical_risks_alternatives_a": T,
    "pa.doc.surgical_risks_alternatives_b": T,
}

PA_CASE_2 = {
    "pa.radic.diagnosis": F, "pa.hern.diagnosis": F,
    "pa.myel.diagnosis": T, "pa.myel.cord_compression": T,
    "pa.myel.symptom_gait": T, "pa.myel.symptom_bilateral_weakness": T,
    "pa.myel.symptom_hyperreflexia": T, "pa.myel.symptom_hoffman": T,
    "pa.myel.symptom_bowel_bladder_a": F,
    "pa.myel.symptom_bowel_bladder_b": F,
    "pa.imaging.mri": T, "pa.imaging.ct_myelogram": F,
    "pa.imaging.demonstrates_pathology": T,
    "pa.exc.myelopathy_confirmed": T, "pa.exc.myelopathy_is_primary": T,
    "pa.pt.completed_six_weeks": F,
    "pa.exc.pt_completed_four_weeks": T,
    "pa.pt.supervised": T, "pa.pt.functional_outcomes_documented": T,
    "pa.pt.directed_at_cervical": T,
    "pa.pharma.nsaid_trial_a": T, "pa.pharma.nsaid_trial_b": F,
    "pa.pharma.muscle_relaxant_trial": F, "pa.pharma.neuropathic_trial": T,
    "pa.pharma.corticosteroid_trial": F,
    "pa.interv.esi": F, "pa.interv.medial_branch_block": F,
    "pa.interv.trigger_point": F,
    "pa.exc.physician_documents_interv_risk": T,
    "pa.surg_imaging.demonstrates_pathology_a": T,
    "pa.surg_imaging.demonstrates_pathology_b": T,
    "pa.surg_imaging.interpreted_by_radiologist": T,
    "pa.surg_imaging.interpreted_by_specialist": F,
    "pa.doc.attestation_conservative": T, "pa.doc.clinical_rationale": T,
    "pa.doc.functional_limitations": T,
    "pa.doc.surgical_risks_alternatives_a": T,
    "pa.doc.surgical_risks_alternatives_b": T,
}

PA_CASE_3 = {
    "pa.radic.diagnosis": T, "pa.radic.nerve_root_compression": T,
    "pa.radic.symptoms_pain": U, "pa.radic.symptoms_numbness": U,
    "pa.radic.symptoms_weakness": U,
    "pa.myel.diagnosis": F, "pa.hern.diagnosis": F,
    "pa.imaging.mri": T, "pa.imaging.ct_myelogram": F,
    "pa.imaging.demonstrates_pathology": T,
    "pa.exc.myelopathy_confirmed": F, "pa.exc.myelopathy_is_primary": F,
    "pa.pt.completed_six_weeks": T, "pa.pt.supervised": T,
    "pa.pt.functional_outcomes_documented": U, "pa.pt.directed_at_cervical": T,
    "pa.exc.pt_completed_four_weeks": F,
    "pa.pharma.nsaid_trial_a": T, "pa.pharma.nsaid_trial_b": F,
    "pa.pharma.muscle_relaxant_trial": U, "pa.pharma.neuropathic_trial": U,
    "pa.pharma.corticosteroid_trial": F,
    "pa.interv.esi": T, "pa.interv.medial_branch_block": F,
    "pa.interv.trigger_point": F,
    "pa.exc.physician_documents_interv_risk": F,
    "pa.surg_imaging.demonstrates_pathology_a": T,
    "pa.surg_imaging.demonstrates_pathology_b": T,
    "pa.surg_imaging.interpreted_by_radiologist": T,
    "pa.surg_imaging.interpreted_by_specialist": F,
    "pa.doc.attestation_conservative": T, "pa.doc.clinical_rationale": T,
    "pa.doc.functional_limitations": U,
    "pa.doc.surgical_risks_alternatives_a": T,
    "pa.doc.surgical_risks_alternatives_b": T,
}

PA_CASE_4 = {atom_id: F for atom_id in PA_CASE_1}
PA_CASE_4["pa.imaging.mri"] = T
PA_CASE_4["pa.pt.completed_six_weeks"] = T
PA_CASE_4["pa.pt.supervised"] = T
PA_CASE_4["pa.pt.functional_outcomes_documented"] = T
PA_CASE_4["pa.pt.directed_at_cervical"] = T
PA_CASE_4["pa.surg_imaging.interpreted_by_radiologist"] = T
PA_CASE_4["pa.doc.attestation_conservative"] = T
PA_CASE_4["pa.doc.clinical_rationale"] = T
PA_CASE_4["pa.doc.functional_limitations"] = T
PA_CASE_4["pa.doc.surgical_risks_alternatives_a"] = T
PA_CASE_4["pa.doc.surgical_risks_alternatives_b"] = T
PA_CASE_4["pa.imaging.demonstrates_pathology"] = F
PA_CASE_4["pa.surg_imaging.demonstrates_pathology_a"] = F


# FCBA cases
FCBA_CASE_UNAUTHORIZED = {
    "fcba.a1_extension": T, "fcba.a1_not_consumer": T, "fcba.a1_not_authorized": T,
    "fcba.a2_extension": T, "fcba.a2_not_per_1026_7": F, "fcba.a2_not_per_1026_8": F,
    "fcba.a3_extension_property": F, "fcba.a3_extension_services": F,
    "fcba.a3_not_accepted": F, "fcba.a3_not_delivered": F,
    "fcba.a4_failure_to_credit": F, "fcba.a5_computational_error": F,
    "fcba.a6_extension": F, "fcba.a6_clarification_requested": F,
    "fcba.a7_failure_to_deliver_statement": F,
}

FCBA_CASE_UNDELIVERED = {
    "fcba.a1_extension": T, "fcba.a1_not_consumer": F, "fcba.a1_not_authorized": F,
    "fcba.a2_extension": T, "fcba.a2_not_per_1026_7": F, "fcba.a2_not_per_1026_8": F,
    "fcba.a3_extension_property": F, "fcba.a3_extension_services": T,
    "fcba.a3_not_accepted": F, "fcba.a3_not_delivered": T,
    "fcba.a4_failure_to_credit": F, "fcba.a5_computational_error": F,
    "fcba.a6_extension": F, "fcba.a6_clarification_requested": F,
    "fcba.a7_failure_to_deliver_statement": F,
}

FCBA_CASE_VALID = {
    "fcba.a1_extension": T, "fcba.a1_not_consumer": F, "fcba.a1_not_authorized": F,
    "fcba.a2_extension": T, "fcba.a2_not_per_1026_7": F, "fcba.a2_not_per_1026_8": F,
    "fcba.a3_extension_property": F, "fcba.a3_extension_services": F,
    "fcba.a3_not_accepted": F, "fcba.a3_not_delivered": F,
    "fcba.a4_failure_to_credit": F, "fcba.a5_computational_error": F,
    "fcba.a6_extension": T, "fcba.a6_clarification_requested": F,
    "fcba.a7_failure_to_deliver_statement": F,
}

FCBA_CASE_UNDETERMINED = {
    "fcba.a1_extension": T, "fcba.a1_not_consumer": T, "fcba.a1_not_authorized": U,
    "fcba.a2_extension": T, "fcba.a2_not_per_1026_7": F, "fcba.a2_not_per_1026_8": F,
    "fcba.a3_extension_property": F, "fcba.a3_extension_services": F,
    "fcba.a3_not_accepted": F, "fcba.a3_not_delivered": F,
    "fcba.a4_failure_to_credit": F, "fcba.a5_computational_error": F,
    "fcba.a6_extension": F, "fcba.a6_clarification_requested": F,
    "fcba.a7_failure_to_deliver_statement": F,
}


def make_bundle(case_dict, all_atom_ids):
    values = {aid: U for aid in all_atom_ids}
    values.update(case_dict)
    return FactBundle(values=values)


def evaluate_case(name, expected, det, bundle, show_trace=False):
    result, trace = det.evaluate(bundle)
    matches = str(result) == expected.lower()
    marker = "PASS" if matches else "FAIL"
    print(f"  [{marker}] {name}: expected={expected}, got={result}")
    if show_trace and not matches:
        print(format_trace(trace))
    return matches


def main():
    results = []

    print("\n" + "=" * 72)
    print("PA (built from policy_inputs/pa_section2.txt)")
    print("=" * 72)
    with open("built_pa.pkl", "rb") as f:
        pa = pickle.load(f)
    pa_atoms = list(pa.atoms.keys())
    print(f"  {len(pa.atoms)} atoms, {len(pa.determinations)} determinations\n")

    d1 = pa.determinations["pa.D1"]
    d2 = pa.determinations["pa.D2"]

    results.append(evaluate_case("PA-1 standard approval (D1)", "TRUE",
                                  d1, make_bundle(PA_CASE_1, pa_atoms)))
    results.append(evaluate_case("PA-2 myelopathy exception (D1)", "TRUE",
                                  d1, make_bundle(PA_CASE_2, pa_atoms)))
    results.append(evaluate_case("PA-3 insufficient evidence (D1)", "UNDETERMINED",
                                  d1, make_bundle(PA_CASE_3, pa_atoms)))
    results.append(evaluate_case("PA-4 denial (D1)", "FALSE",
                                  d1, make_bundle(PA_CASE_4, pa_atoms)))
    results.append(evaluate_case("PA-4 denial (D2)", "TRUE",
                                  d2, make_bundle(PA_CASE_4, pa_atoms)))

    print("\n" + "=" * 72)
    print("FCBA (built from policy_inputs/fcba_1026_13a.txt)")
    print("=" * 72)
    with open("built_fcba.pkl", "rb") as f:
        fcba = pickle.load(f)
    fcba_atoms = list(fcba.atoms.keys())
    print(f"  {len(fcba.atoms)} atoms, {len(fcba.determinations)} determinations\n")

    fd1 = fcba.determinations["fcba.D1"]
    fd2 = fcba.determinations["fcba.D2"]

    results.append(evaluate_case("FCBA-1 unauthorized (D1)", "TRUE",
                                  fd1, make_bundle(FCBA_CASE_UNAUTHORIZED, fcba_atoms)))
    results.append(evaluate_case("FCBA-2 undelivered (D1)", "TRUE",
                                  fd1, make_bundle(FCBA_CASE_UNDELIVERED, fcba_atoms)))
    results.append(evaluate_case("FCBA-3 valid charge (D1)", "FALSE",
                                  fd1, make_bundle(FCBA_CASE_VALID, fcba_atoms)))
    results.append(evaluate_case("FCBA-3 valid charge (D2)", "TRUE",
                                  fd2, make_bundle(FCBA_CASE_VALID, fcba_atoms)))
    results.append(evaluate_case("FCBA-4 undetermined (D1)", "UNDETERMINED",
                                  fd1, make_bundle(FCBA_CASE_UNDETERMINED, fcba_atoms)))

    print("\n" + "=" * 72)
    print("SUMMARY")
    print("=" * 72)
    print(f"\n  {sum(results)}/{len(results)} cases produced expected outcomes\n")
    if all(results):
        print("  ALL BUILT TREES EVALUATE CORRECTLY\n")
    else:
        print("  Some built trees have evaluation errors\n")


if __name__ == "__main__":
    main()
