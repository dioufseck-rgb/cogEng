"""
PA Section 2 — cervical spinal surgery authorization.

Source: HealthFirst Health Plan, CC-SPINE-2024, Section 2.
Scope of this build: Section 2 only (approval determination with the myelopathy
exception 2.2A). Section 3 (exclusions) is not included in this run.

Discipline: atoms are atomic (no hidden connectives); operator vocabulary is
AT-LEAST-N + NOT; internal nodes are anonymous; edges carry policy reference
language; provenance is marked per operator.
"""

from rulekit import (
    Atom, Schema, SchemaField, EvalMode,
    Leaf, CardinalityNode, NotNode, EdgeMeta,
    Determination, Provenance,
)


# ---------------------------------------------------------------------------
# Atoms — refined per atomicity discipline
# ---------------------------------------------------------------------------

ATOMS = {
    # Diagnosis pathway — Section 2.1
    "pa.a01a": Atom("pa.a01a", "Member has confirmed cervical radiculopathy diagnosis.", "2.1(a)"),
    "pa.a01b": Atom("pa.a01b", "Nerve root compression is documented.", "2.1(a)"),
    "pa.a01c": Atom("pa.a01c", "Radicular symptoms in dermatomal distribution are documented.", "2.1(a)"),

    "pa.a02a": Atom("pa.a02a", "Member has confirmed cervical myelopathy diagnosis.", "2.1(b)"),
    "pa.a02b": Atom("pa.a02b", "Spinal cord compression is documented.", "2.1(b)"),
    "pa.a02c": Atom("pa.a02c", "Gait disturbance is documented.", "2.1(b)"),
    "pa.a02d": Atom("pa.a02d", "Bilateral upper extremity weakness is documented.", "2.1(b)"),
    "pa.a02e": Atom("pa.a02e", "Hyperreflexia is documented.", "2.1(b)"),
    "pa.a02f": Atom("pa.a02f", "Positive Hoffman sign is documented.", "2.1(b)"),
    "pa.a02g": Atom("pa.a02g", "Bowel/bladder dysfunction is documented.", "2.1(b)"),

    "pa.a03a": Atom("pa.a03a", "Member has confirmed cervical disc herniation diagnosis.", "2.1(c)"),
    "pa.a03b": Atom("pa.a03b", "Objective neurological deficit is documented.", "2.1(c)"),

    # Imaging — Section 2.1 supporting documentation, also referenced by 2.3
    "pa.a04a": Atom("pa.a04a", "Member has MRI within 6 months of request.", "2.1 supporting doc"),
    "pa.a04b": Atom("pa.a04b", "Member has CT myelogram within 6 months of request.", "2.1 supporting doc"),
    "pa.a04c": Atom("pa.a04c", "The imaging demonstrates structural pathology consistent with symptoms.", "2.1 supporting doc"),

    # Physical therapy — Section 2.2(a) and 2.2A modified
    "pa.a05": Atom("pa.a05", "Member has completed at least 6 weeks of physical therapy.", "2.2(a)"),
    "pa.a06a": Atom("pa.a06a", "Physical therapy was supervised.", "2.2(a)"),
    "pa.a06b": Atom("pa.a06b", "Physical therapy was documented with functional outcomes.", "2.2(a)"),
    "pa.a07": Atom("pa.a07", "Physical therapy was directed at the cervical condition for which surgery is requested.", "2.2(a)"),
    "pa.a11": Atom("pa.a11", "Member has completed at least 4 weeks of physical therapy.", "2.2A modified PT"),

    # Pharmacotherapy — Section 2.2(b)
    "pa.a08_nsaid": Atom("pa.a08_nsaid", "Member trialed NSAIDs or COX-2 inhibitors for at least 4 weeks.", "2.2(b)"),
    "pa.a08_muscle": Atom("pa.a08_muscle", "Member trialed muscle relaxants for at least 4 weeks.", "2.2(b)"),
    "pa.a08_neuro": Atom("pa.a08_neuro", "Member trialed neuropathic agents (gabapentin, pregabalin, or duloxetine) for at least 4 weeks.", "2.2(b)"),
    "pa.a08_steroid": Atom("pa.a08_steroid", "Member trialed oral corticosteroids for at least 4 weeks.", "2.2(b)"),

    # Interventional treatments — Section 2.2(c)
    "pa.a09_esi": Atom("pa.a09_esi", "Member received at least one cervical epidural steroid injection.", "2.2(c)"),
    "pa.a09_mbb": Atom("pa.a09_mbb", "Member received a cervical medial branch block.", "2.2(c)"),
    "pa.a09_trigger": Atom("pa.a09_trigger", "Member received a trigger point injection series.", "2.2(c)"),

    # Myelopathy exception gating — Section 2.2A
    "pa.a10a": Atom("pa.a10a", "Member has confirmed cervical myelopathy under criterion 2.1(b).", "2.2A antecedent"),
    "pa.a10b": Atom("pa.a10b", "Myelopathy is the primary diagnosis (not a finding accompanying a primary complaint of radiculopathy).", "2.2A NOTE"),
    "pa.a12": Atom("pa.a12", "Treating physician has documented that interventional treatment poses risk of neurological deterioration.", "2.2A waiver condition"),

    # Surgical-level imaging — Section 2.3 (under redundancy principle, may share map binding with a04)
    "pa.a13_level": Atom("pa.a13_level", "Imaging demonstrates pathology at the proposed surgical level.", "2.3"),
    "pa.a13_interp": Atom("pa.a13_interp", "Imaging is interpreted by a radiologist or treating specialist.", "2.3"),

    # Physician documentation — Section 2.4
    "pa.a14": Atom("pa.a14", "Treating physician has attested that conservative treatment has been completed.", "2.4(a)"),
    "pa.a15": Atom("pa.a15", "Treating physician has provided clinical rationale for surgical intervention.", "2.4(b)"),
    "pa.a16": Atom("pa.a16", "Treating physician has provided description of functional limitations.", "2.4(c)"),
    "pa.a17": Atom("pa.a17", "Treating physician has provided statement of surgical risks and alternatives considered.", "2.4(d)"),
}


# ---------------------------------------------------------------------------
# Schema — typed field declarations
# ---------------------------------------------------------------------------

# All PA atoms are characterized fields by default — they require LLM substrate
# to characterize the claim against clinical records. A few are computed
# (PT duration, imaging age) but for this build we keep them characterized
# with the understanding that production map would compute durations.

def _char_field(atom_id: str, spec: str, undet: str = "Evidence is missing or contradictory.") -> SchemaField:
    return SchemaField(
        atom_id=atom_id,
        evaluation_mode=EvalMode.CHARACTERIZED,
        specification=spec,
        undetermined_rule=undet,
    )


PA_SCHEMA = Schema(
    name="PA Section 2 (CC-SPINE-2024)",
    atoms=ATOMS,
    fields={
        atom_id: _char_field(
            atom_id,
            f"Characterize whether the clinical record supports: '{atom.statement}'",
        )
        for atom_id, atom in ATOMS.items()
    },
)


# ---------------------------------------------------------------------------
# Helpers for building tree fragments
# ---------------------------------------------------------------------------

def leaf(atom_id: str) -> Leaf:
    return Leaf(atom_id=atom_id)


def all_of(children, label="ALL", provenance=Provenance.TRANSCRIBED, source="", n=None):
    """AT-LEAST-N where N == len(children). Default surface label 'ALL'."""
    n = n or len(children)
    return CardinalityNode(
        n=n, children=children, surface_label=label,
        provenance=provenance, source_span=source,
    )


def any_of(children, label="ANY", provenance=Provenance.STRUCTURAL, source=""):
    """AT-LEAST-1."""
    return CardinalityNode(
        n=1, children=children, surface_label=label,
        provenance=provenance, source_span=source,
    )


def at_least(n: int, children, label=None, provenance=Provenance.TRANSCRIBED, source=""):
    label = label or f"AT LEAST {n}"
    return CardinalityNode(
        n=n, children=children, surface_label=label,
        provenance=provenance, source_span=source,
    )


def not_(child, provenance=Provenance.INFERRED, source="", confidence=None, latent_type=None):
    return NotNode(child=child, provenance=provenance, source_span=source,
                   confidence=confidence, latent_type=latent_type)


# ---------------------------------------------------------------------------
# Sub-trees — each is an anonymous internal structure with edge metadata
# at its parent's children_meta.
# ---------------------------------------------------------------------------

# Diagnosis disjunction (2.1) — three diagnosis options, OR-with-cardinality-1
radiculopathy = all_of(
    [leaf("pa.a01a"), leaf("pa.a01b"), leaf("pa.a01c")],
    label="ALL (radiculopathy criteria)",
    provenance=Provenance.STRUCTURAL,
    source="2.1(a) — radiculopathy criteria joined as conjunction",
)

myelopathy_diagnosis = all_of(
    [
        leaf("pa.a02a"),
        leaf("pa.a02b"),
        any_of(
            [leaf("pa.a02c"), leaf("pa.a02d"), leaf("pa.a02e"),
             leaf("pa.a02f"), leaf("pa.a02g")],
            label="ANY (myelopathic symptom)",
            provenance=Provenance.STRUCTURAL,
            source="2.1(b) — symptom list as disjunction",
        ),
    ],
    label="ALL (myelopathy criteria)",
    provenance=Provenance.STRUCTURAL,
    source="2.1(b) — myelopathy joined as conjunction with disjunctive symptoms",
)

disc_herniation = all_of(
    [leaf("pa.a03a"), leaf("pa.a03b")],
    label="ALL (disc herniation criteria)",
    provenance=Provenance.STRUCTURAL,
    source="2.1(c) — disc herniation requires diagnosis + objective deficit",
)

diagnosis_disjunction = any_of(
    [radiculopathy, myelopathy_diagnosis, disc_herniation],
    label="ONE OF (diagnosis)",
    provenance=Provenance.TRANSCRIBED,
    source="2.1 — 'one of the following'",
)

# Imaging for diagnosis (2.1 supporting documentation)
imaging_modality = any_of(
    [leaf("pa.a04a"), leaf("pa.a04b")],
    label="MRI OR CT myelogram",
    provenance=Provenance.TRANSCRIBED,
    source="2.1 — 'MRI or CT myelogram'",
)

imaging_for_diagnosis = all_of(
    [imaging_modality, leaf("pa.a04c")],
    label="ALL (imaging requirement)",
    provenance=Provenance.STRUCTURAL,
    source="2.1 — modality + structural pathology finding",
)

# 2.1 sub-tree = diagnosis AND imaging
section_2_1 = all_of(
    [diagnosis_disjunction, imaging_for_diagnosis],
    label="ALL (2.1)",
    provenance=Provenance.STRUCTURAL,
    source="2.1 — diagnosis and imaging are joint requirements",
)

# PT qualifiers — used in both standard and exception pathways under redundancy principle
pt_qualifiers = all_of(
    [leaf("pa.a06a"), leaf("pa.a06b"), leaf("pa.a07")],
    label="ALL (PT qualifiers)",
    provenance=Provenance.STRUCTURAL,
    source="2.2(a) — supervised + documented + directed",
)

# Standard PT (6 weeks + qualifiers)
standard_pt = all_of(
    [leaf("pa.a05"), pt_qualifiers],
    label="ALL (standard PT requirement)",
    provenance=Provenance.TRANSCRIBED,
    source="2.2(a)",
)

# Exception PT (4 weeks + qualifiers; qualifier carry-over is FLAGGED as latent L1)
exception_pt_node = all_of(
    [leaf("pa.a11"), pt_qualifiers],
    label="ALL (exception PT requirement)",
    provenance=Provenance.INFERRED,
    source="2.2A — modified PT duration; qualifier carry-over inferred",
)
exception_pt_node.confidence = 0.7
exception_pt_node.latent_type = "scope (L1: qualifier carry-over)"

# Pharmacotherapy: AT-LEAST-2 of four classes, transcribed
pharma = at_least(
    2,
    [leaf("pa.a08_nsaid"), leaf("pa.a08_muscle"),
     leaf("pa.a08_neuro"), leaf("pa.a08_steroid")],
    label="AT LEAST 2 (pharma classes)",
    provenance=Provenance.TRANSCRIBED,
    source="2.2(b) — 'at least two of the following'",
)

# Interventional: AT-LEAST-1 of three options, transcribed
interventional = at_least(
    1,
    [leaf("pa.a09_esi"), leaf("pa.a09_mbb"), leaf("pa.a09_trigger")],
    label="ONE OF (interventional)",
    provenance=Provenance.TRANSCRIBED,
    source="2.2(c) — 'one of the following'",
)

# Exception antecedent: AND of confirmed myelopathy + primary diagnosis status
exception_antecedent = all_of(
    [leaf("pa.a10a"), leaf("pa.a10b")],
    label="ALL (exception antecedent)",
    provenance=Provenance.STRUCTURAL,
    source="2.2A header + NOTE",
)

# Waivable interventional under exception
waivable_interventional = any_of(
    [interventional, leaf("pa.a12")],
    label="interventional OR physician-documented waiver",
    provenance=Provenance.TRANSCRIBED,
    source="2.2A — interventional 'WAIVED if treating physician documents...'",
)

# Standard pathway: NOT exception antecedent AND standard PT AND pharma AND interventional
standard_pathway = all_of(
    [
        not_(exception_antecedent,
             provenance=Provenance.INFERRED,
             source="2.2A — exception gating; standard pathway applies when antecedent false",
             confidence=0.85,
             latent_type="scope (mutual exclusion between pathways)"),
        standard_pt,
        pharma,
        interventional,
    ],
    label="ALL (standard pathway)",
    provenance=Provenance.STRUCTURAL,
    source="2.2 standard conservative treatment requirement",
)

# Exception pathway: exception antecedent AND modified PT AND pharma AND waivable interventional
exception_pathway = all_of(
    [
        exception_antecedent,
        exception_pt_node,
        pharma,  # "remains in full"
        waivable_interventional,
    ],
    label="ALL (exception pathway)",
    provenance=Provenance.STRUCTURAL,
    source="2.2A modified conservative treatment requirement",
)

# 2.2 sub-tree = standard OR exception
section_2_2 = any_of(
    [standard_pathway, exception_pathway],
    label="standard OR exception",
    provenance=Provenance.INFERRED,
    source="2.2 + 2.2A — 'MODIFIED' interpreted as alternative pathway",
)
section_2_2.confidence = 0.8
section_2_2.latent_type = "scope (L4: MODIFIED as alternative-pathway)"

# 2.3 — surgical-level imaging (kept distinct from 2.1 imaging per redundancy-as-binding principle)
section_2_3 = all_of(
    [leaf("pa.a13_level"), leaf("pa.a13_interp")],
    label="ALL (2.3 surgical-level imaging)",
    provenance=Provenance.STRUCTURAL,
    source="2.3",
)

# 2.4 — physician documentation
section_2_4 = all_of(
    [leaf("pa.a14"), leaf("pa.a15"), leaf("pa.a16"), leaf("pa.a17")],
    label="ALL (2.4 documentation)",
    provenance=Provenance.TRANSCRIBED,
    source="2.4 — physician documentation requirements",
)


# ---------------------------------------------------------------------------
# D1 — AUTHORIZATION_APPROVED
# ---------------------------------------------------------------------------

PA_D1_TREE = all_of(
    [section_2_1, section_2_2, section_2_3, section_2_4],
    label="ALL (Section 2 approval criteria)",
    provenance=Provenance.TRANSCRIBED,
    source="Section 2 header — 'will be approved when ALL of the following criteria are satisfied'",
)

PA_D1 = Determination(
    id="PA.D1",
    description="Authorization approved for cervical spinal surgery (CPT 22551 and related codes).",
    tree=PA_D1_TREE,
    provenance=Provenance.TRANSCRIBED,
    polarity="positive",
    linked_to="PA.D2",
    source_span="Section 2 header",
)


# ---------------------------------------------------------------------------
# D2 — AUTHORIZATION_DENIED (inferred from complement; Section 3 not included)
# ---------------------------------------------------------------------------

PA_D2 = Determination(
    id="PA.D2",
    description="Authorization denied (structural complement of D1; Section 3 grounds not modeled in this build).",
    tree=not_(PA_D1_TREE,
              provenance=Provenance.INFERRED,
              source="Inferred from complement of D1; Section 3 not modeled",
              confidence=0.7,
              latent_type="meta-interpretation (D2 partial: complement-only)"),
    provenance=Provenance.INFERRED,
    polarity="negative",
    linked_to="PA.D1",
    source_span="Implicit structural complement of Section 2",
)


PA_DETERMINATIONS = {"PA.D1": PA_D1, "PA.D2": PA_D2}
