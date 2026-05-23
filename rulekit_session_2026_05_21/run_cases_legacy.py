"""
Test fact bundles for both PA and FCBA trees, with realistic case profiles.

For each bundle:
- All atom values are explicit (TRUE, FALSE, or UNDETERMINED).
- Evidence strings are short descriptions for the audit trail.
- The bundle is constructed to exercise specific tree pathways.
"""

import sys
import os
# Make this script runnable from any directory by adding its own folder to the path
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from rulekit import Kleene, FactBundle, format_trace
from policies.pa_section2 import (
    PA_DETERMINATIONS, PA_SCHEMA, ATOMS as PA_ATOMS,
)
from policies.fcba_1026_13a import (
    FCBA_DETERMINATIONS, FCBA_SCHEMA, ATOMS as FCBA_ATOMS,
)


T, F, U = Kleene.TRUE, Kleene.FALSE, Kleene.UNDETERMINED


# ---------------------------------------------------------------------------
# PA fact bundles
# ---------------------------------------------------------------------------

def make_pa_bundle(values: dict[str, Kleene], evidence: dict[str, str]) -> FactBundle:
    """Build a PA fact bundle, defaulting unmentioned atoms to UNDETERMINED."""
    full = {atom_id: U for atom_id in PA_ATOMS}
    full.update(values)
    return FactBundle(values=full, evidence=evidence)


# Case PA-1: standard pathway approval — patient meets all standard criteria
PA_CASE_STANDARD_APPROVAL = make_pa_bundle(
    values={
        # Radiculopathy diagnosis (one of the three options)
        "pa.a01a": T, "pa.a01b": T, "pa.a01c": T,
        # Other diagnoses absent
        "pa.a02a": F, "pa.a03a": F,
        # Imaging
        "pa.a04a": T, "pa.a04b": F, "pa.a04c": T,
        # Standard PT (6 weeks + qualifiers)
        "pa.a05": T, "pa.a06a": T, "pa.a06b": T, "pa.a07": T,
        # Exception path not relevant
        "pa.a10a": F, "pa.a10b": F, "pa.a11": F,
        # Pharma: NSAIDs + neuropathic agents
        "pa.a08_nsaid": T, "pa.a08_muscle": F, "pa.a08_neuro": T, "pa.a08_steroid": F,
        # Interventional: one ESI
        "pa.a09_esi": T, "pa.a09_mbb": F, "pa.a09_trigger": F,
        # Surgical-level imaging
        "pa.a13_level": T, "pa.a13_interp": T,
        # Documentation complete
        "pa.a14": T, "pa.a15": T, "pa.a16": T, "pa.a17": T,
    },
    evidence={
        "pa.a01a": "Clinical note: C6 radiculopathy confirmed",
        "pa.a05": "PT records show 8 weeks of supervised therapy",
        "pa.a08_nsaid": "Ibuprofen 800mg trialed for 6 weeks",
        "pa.a09_esi": "C5-C6 ESI performed 2024-09-15",
    },
)


# Case PA-2: myelopathy exception approval — primary myelopathy with shortened PT
PA_CASE_MYELOPATHY_APPROVAL = make_pa_bundle(
    values={
        # Diagnosis: myelopathy with cord compression and multiple signs
        "pa.a01a": F, "pa.a03a": F,
        "pa.a02a": T, "pa.a02b": T,
        "pa.a02c": T,  # gait disturbance
        "pa.a02d": T,  # bilateral weakness
        "pa.a02e": T,  # hyperreflexia
        "pa.a02f": T,  # Hoffman sign
        "pa.a02g": F,
        # Imaging
        "pa.a04a": T, "pa.a04b": F, "pa.a04c": T,
        # Exception antecedent satisfied
        "pa.a10a": T, "pa.a10b": T,
        # Standard PT (6 weeks) not met
        "pa.a05": F,
        # Exception PT (4 weeks) met, with qualifiers
        "pa.a11": T, "pa.a06a": T, "pa.a06b": T, "pa.a07": T,
        # Pharma
        "pa.a08_nsaid": T, "pa.a08_muscle": F, "pa.a08_neuro": T, "pa.a08_steroid": F,
        # Interventional waived via physician documentation
        "pa.a09_esi": F, "pa.a09_mbb": F, "pa.a09_trigger": F,
        "pa.a12": T,  # physician documents risk
        # Surgical-level imaging
        "pa.a13_level": T, "pa.a13_interp": T,
        # Documentation complete
        "pa.a14": T, "pa.a15": T, "pa.a16": T, "pa.a17": T,
    },
    evidence={
        "pa.a02a": "Myelopathy primary; mJOA 11",
        "pa.a02b": "MRI shows cord compression at C4-C5",
        "pa.a11": "PT completed 5 weeks before surgical consult",
        "pa.a12": "Surgeon documented ESI risk given cord compression",
    },
)


# Case PA-3: insufficient evidence — undetermined determination
PA_CASE_INSUFFICIENT_EVIDENCE = make_pa_bundle(
    values={
        # Radiculopathy partial — diagnosis confirmed but symptoms unclear
        "pa.a01a": T, "pa.a01b": T, "pa.a01c": U,
        "pa.a02a": F, "pa.a03a": F,
        # Imaging present
        "pa.a04a": T, "pa.a04b": F, "pa.a04c": T,
        # Exception path absent
        "pa.a10a": F, "pa.a10b": F, "pa.a11": F,
        # PT: partial documentation
        "pa.a05": T, "pa.a06a": T, "pa.a06b": U, "pa.a07": T,
        # Pharma: one trial confirmed, others unclear
        "pa.a08_nsaid": T, "pa.a08_muscle": U, "pa.a08_neuro": U, "pa.a08_steroid": F,
        # Interventional confirmed
        "pa.a09_esi": T, "pa.a09_mbb": F, "pa.a09_trigger": F,
        # Surgical-level imaging
        "pa.a13_level": T, "pa.a13_interp": T,
        # Some documentation missing
        "pa.a14": T, "pa.a15": T, "pa.a16": U, "pa.a17": T,
    },
    evidence={
        "pa.a01c": "Symptom distribution not specified in records",
        "pa.a06b": "Functional outcomes notation incomplete",
        "pa.a08_neuro": "Possible gabapentin trial; dates unclear",
        "pa.a16": "Functional limitations described informally",
    },
)


# Case PA-4: clear denial — axial pain only, no diagnosis criteria met
PA_CASE_DENIAL_NO_DIAGNOSIS = make_pa_bundle(
    values={
        "pa.a01a": F, "pa.a02a": F, "pa.a03a": F,
        "pa.a01b": F, "pa.a01c": F,
        "pa.a02b": F, "pa.a02c": F, "pa.a02d": F, "pa.a02e": F, "pa.a02f": F, "pa.a02g": F,
        "pa.a03b": F,
        "pa.a04a": T, "pa.a04b": F, "pa.a04c": F,
        "pa.a05": T, "pa.a06a": T, "pa.a06b": T, "pa.a07": T,
        "pa.a10a": F, "pa.a10b": F, "pa.a11": F,
        "pa.a08_nsaid": T, "pa.a08_muscle": T, "pa.a08_neuro": F, "pa.a08_steroid": F,
        "pa.a09_esi": F, "pa.a09_mbb": F, "pa.a09_trigger": F,
        "pa.a13_level": F, "pa.a13_interp": T,
        "pa.a14": T, "pa.a15": T, "pa.a16": T, "pa.a17": T,
    },
    evidence={
        "pa.a04c": "Imaging shows no structural pathology consistent with symptoms",
        "pa.a01a": "No radicular signs; presentation is axial neck pain only",
    },
)


# ---------------------------------------------------------------------------
# FCBA fact bundles
# ---------------------------------------------------------------------------

def make_fcba_bundle(values: dict[str, Kleene], evidence: dict[str, str]) -> FactBundle:
    full = {atom_id: U for atom_id in FCBA_ATOMS}
    full.update(values)
    return FactBundle(values=full, evidence=evidence)


# Case FCBA-1: clear unauthorized charge (a)(1)
FCBA_CASE_UNAUTHORIZED = make_fcba_bundle(
    values={
        "fcba.a1a": T, "fcba.a1b": T, "fcba.a1c": T,
        # Other categories not triggered
        "fcba.a2a": T, "fcba.a2b": F, "fcba.a2c": F,
        "fcba.a3a": F, "fcba.a3b": F, "fcba.a3c": F,
        "fcba.a4": F, "fcba.a5": F,
        "fcba.a6a": F, "fcba.a6b": F,
        "fcba.a7": F,
    },
    evidence={
        "fcba.a1a": "Charge of $487 on 2026-04-12 to Acme Electronics",
        "fcba.a1b": "Consumer reports no such transaction",
        "fcba.a1c": "No authorized user reports this charge; card was in consumer's possession",
    },
)


# Case FCBA-2: undelivered services (a)(3)
FCBA_CASE_UNDELIVERED = make_fcba_bundle(
    values={
        "fcba.a1a": T, "fcba.a1b": F, "fcba.a1c": F,
        "fcba.a2a": T, "fcba.a2b": F, "fcba.a2c": F,
        # Property/services issue: charged for services, not delivered as agreed
        "fcba.a3a": T, "fcba.a3b": F, "fcba.a3c": T,
        "fcba.a4": F, "fcba.a5": F,
        "fcba.a6a": F, "fcba.a6b": F,
        "fcba.a7": F,
    },
    evidence={
        "fcba.a3a": "Subscription service $89.99/month",
        "fcba.a3c": "Service was paid but not delivered; provider went out of business",
    },
)


# Case FCBA-3: not a billing error (none of the categories triggered)
FCBA_CASE_VALID_CHARGE = make_fcba_bundle(
    values={
        "fcba.a1a": T, "fcba.a1b": F, "fcba.a1c": F,
        "fcba.a2a": T, "fcba.a2b": F, "fcba.a2c": F,
        "fcba.a3a": F, "fcba.a3b": F, "fcba.a3c": F,
        "fcba.a4": F, "fcba.a5": F,
        "fcba.a6a": T, "fcba.a6b": F,
        "fcba.a7": F,
    },
    evidence={
        "fcba.a1a": "Valid authorized charge",
    },
)


# Case FCBA-4: undetermined — unauthorized charge alleged but evidence partial
FCBA_CASE_UNDETERMINED = make_fcba_bundle(
    values={
        "fcba.a1a": T, "fcba.a1b": T, "fcba.a1c": U,
        "fcba.a2a": T, "fcba.a2b": F, "fcba.a2c": F,
        "fcba.a3a": F, "fcba.a3b": F, "fcba.a3c": F,
        "fcba.a4": F, "fcba.a5": F,
        "fcba.a6a": F, "fcba.a6b": F,
        "fcba.a7": F,
    },
    evidence={
        "fcba.a1c": "Authorized users not fully canvassed; spouse not yet contacted",
    },
)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_case(determination, bundle, label):
    print(f"\n{'=' * 72}")
    print(f"CASE: {label}")
    print(f"DETERMINATION: {determination.id} — {determination.description}")
    print("=" * 72)
    result, trace = determination.evaluate(bundle)
    print(f"\nRESULT: {result}\n")
    print("REASONING TRACE:")
    print(format_trace(trace))


def run_all():
    print("\n" + "#" * 72)
    print("# POLICY 1 — PA SECTION 2 (HealthFirst CC-SPINE-2024)")
    print("#" * 72)

    run_case(PA_DETERMINATIONS["PA.D1"], PA_CASE_STANDARD_APPROVAL,
             "PA-1: Standard pathway — radiculopathy patient with full conservative tx")
    run_case(PA_DETERMINATIONS["PA.D1"], PA_CASE_MYELOPATHY_APPROVAL,
             "PA-2: Exception pathway — primary myelopathy with 4-week PT and waived interventional")
    run_case(PA_DETERMINATIONS["PA.D1"], PA_CASE_INSUFFICIENT_EVIDENCE,
             "PA-3: Insufficient evidence — some atoms undetermined")
    run_case(PA_DETERMINATIONS["PA.D1"], PA_CASE_DENIAL_NO_DIAGNOSIS,
             "PA-4: Clear denial — no qualifying diagnosis")

    # Also evaluate D2 (the complement) for case 4 to show linked-determination behavior
    run_case(PA_DETERMINATIONS["PA.D2"], PA_CASE_DENIAL_NO_DIAGNOSIS,
             "PA-4 (D2 view): Same case, denial determination")

    print("\n\n" + "#" * 72)
    print("# POLICY 2 — FCBA § 1026.13(a) billing error definition")
    print("#" * 72)

    run_case(FCBA_DETERMINATIONS["FCBA.D1"], FCBA_CASE_UNAUTHORIZED,
             "FCBA-1: Unauthorized charge — (a)(1)")
    run_case(FCBA_DETERMINATIONS["FCBA.D1"], FCBA_CASE_UNDELIVERED,
             "FCBA-2: Undelivered services — (a)(3)")
    run_case(FCBA_DETERMINATIONS["FCBA.D1"], FCBA_CASE_VALID_CHARGE,
             "FCBA-3: Valid authorized charge — no category triggered")
    run_case(FCBA_DETERMINATIONS["FCBA.D1"], FCBA_CASE_UNDETERMINED,
             "FCBA-4: Undetermined — alleged unauthorized, evidence partial")


if __name__ == "__main__":
    run_all()
