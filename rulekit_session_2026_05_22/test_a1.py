"""
Test harness for substage A1 (atom extraction).

Runs A1 against PA Section 2 source text and compares the extracted atoms
against the hand-built ones in policies/pa_section2.py.

This is a meaningful test of whether the builder discipline, applied via
LLM prompt, produces output that matches what a careful human produces.
"""

import sys
import os
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import json
from rulekit.builder import ReaderVoice, run_a1, check_atomicity
from policies.pa_section2 import ATOMS as HAND_BUILT_PA_ATOMS


# PA Section 2 source text — Section 2 only, the scope of our hand-built tree.
PA_SECTION_2_SOURCE = """
SECTION 2 — MEDICAL NECESSITY CRITERIA

Authorization for cervical spinal surgery (CPT 22551 and related codes) will
be approved when ALL of the following criteria are satisfied:

2.1 DIAGNOSIS REQUIREMENT
    Member must have a confirmed diagnosis of one of the following:
    (a) Cervical radiculopathy — nerve root compression with radicular symptoms
        (pain, numbness, weakness in dermatomal distribution)
    (b) Cervical myelopathy — spinal cord compression with myelopathic symptoms
        (gait disturbance, bilateral upper extremity weakness, hyperreflexia,
        positive Hoffman sign, bowel/bladder dysfunction)
    (c) Cervical disc herniation with objective neurological deficit

    Supporting documentation required: MRI or CT myelogram within 6 months of
    request demonstrating structural pathology consistent with symptoms.

2.2 CONSERVATIVE TREATMENT REQUIREMENT
    Member must have completed a documented course of conservative treatment
    prior to surgical authorization, consisting of ALL of the following:

    (a) Physical therapy: minimum 6 weeks of supervised physical therapy
        with documented functional outcomes. Therapy must be directed toward
        the cervical condition for which surgery is requested.

    (b) Pharmacotherapy: trial of at least two of the following for minimum
        4 weeks each:
        - NSAIDs or COX-2 inhibitors
        - Muscle relaxants
        - Neuropathic agents (gabapentin, pregabalin, duloxetine)
        - Oral corticosteroids

    (c) One of the following interventional treatments:
        - Cervical epidural steroid injection (minimum 1)
        - Cervical medial branch block
        - Trigger point injection series

    EXCEPTION 2.2(A) — MYELOPATHY PATHWAY:
    For members with confirmed cervical myelopathy (criterion 2.1(b)),
    the conservative treatment requirement is MODIFIED as follows:
    Physical therapy requirement is reduced to 4 weeks minimum.
    Interventional treatment requirement (2.2(c)) is WAIVED if treating
    physician documents that interventional treatment poses risk of
    neurological deterioration.
    Pharmacotherapy requirement (2.2(b)) remains in full.

    NOTE: The myelopathy exception applies only when myelopathy is the
    PRIMARY diagnosis. Cases where myelopathy is documented as a finding
    but radiculopathy is the primary complaint are subject to standard
    conservative treatment requirements.

2.3 IMAGING REQUIREMENT
    Current imaging (within 6 months) must demonstrate structural pathology
    consistent with the member's symptoms and proposed surgical level.
    Imaging must be interpreted by a radiologist or treating specialist.

2.4 PHYSICIAN DOCUMENTATION
    Treating physician must provide:
    (a) Attestation that conservative treatment has been completed
    (b) Clinical rationale for surgical intervention
    (c) Description of functional limitations
    (d) Statement of surgical risks and alternatives considered
"""


def run_test():
    print("=" * 72)
    print("Substage A1 test — atom extraction on PA Section 2")
    print("=" * 72)

    voice = ReaderVoice.pa_reviewer()
    print(f"\nReader voice: {voice.role}")
    print(f"Domain: {voice.domain}\n")

    print("Calling A1 (offline mode using pre-generated response)...")
    with open(os.path.join(_HERE, "test_data", "a1_response_pa_section2.json")) as f:
        offline_response = f.read()
    result = run_a1(PA_SECTION_2_SOURCE, voice, offline_response=offline_response)

    print(f"\nA1 extracted {len(result.atoms)} atoms.\n")
    print(f"Hand-built tree has {len(HAND_BUILT_PA_ATOMS)} atoms.\n")

    print("=" * 72)
    print("EXTRACTED ATOMS")
    print("=" * 72)
    for atom_id, atom in result.atoms.items():
        flags = result.atomicity_flags.get(atom_id, [])
        flag_str = f"  [ATOMICITY FLAGS: {', '.join(flags)}]" if flags else ""
        print(f"\n  {atom_id}  [src: {atom.source_span}]{flag_str}")
        print(f"    {atom.statement}")

    print("\n" + "=" * 72)
    print("ATOMICITY CHECK SUMMARY")
    print("=" * 72)
    if result.atomicity_flags:
        print(f"\n{len(result.atomicity_flags)} of {len(result.atoms)} atoms flagged "
              f"for potential atomicity issues:")
        for atom_id, flags in result.atomicity_flags.items():
            print(f"  {atom_id}: {flags}")
    else:
        print("\nAll atoms passed mechanical atomicity check.")

    print("\n" + "=" * 72)
    print("COMPARISON WITH HAND-BUILT")
    print("=" * 72)
    print(f"\nHand-built atom count: {len(HAND_BUILT_PA_ATOMS)}")
    print(f"LLM-extracted count:   {len(result.atoms)}")
    print(f"Difference: {len(result.atoms) - len(HAND_BUILT_PA_ATOMS):+d}\n")

    print("Hand-built atoms (for reference):")
    for atom_id, atom in HAND_BUILT_PA_ATOMS.items():
        print(f"  {atom_id} [{atom.source_span}]: {atom.statement[:60]}...")

    # Save the raw response and prompt for inspection
    with open("a1_audit.json", "w") as f:
        json.dump({
            "prompt": result.prompt,
            "raw_response": result.raw_response,
            "extracted_atoms": {
                aid: {"statement": a.statement, "source_span": a.source_span}
                for aid, a in result.atoms.items()
            },
            "atomicity_flags": result.atomicity_flags,
        }, f, indent=2)
    print("\nFull audit (prompt + raw response + parsed atoms) saved to a1_audit.json")


if __name__ == "__main__":
    run_test()
