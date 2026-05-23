"""
FCBA § 1026.13(a) — Definition of billing error.

Source: 12 CFR § 1026.13(a). Public source via eCFR.

Scope: just the definition. The determination is "this transaction/event
qualifies as a billing error." Seven enumerated categories compose
disjunctively — any one of the seven triggers the definition.

Discipline: same as PA — atomic atoms, AT-LEAST-N + NOT vocabulary,
anonymous internal nodes, provenance metadata throughout.

Note on (a)(8): the 'other' subsection in the full regulation cross-references
a separate enumeration. For this build we treat (a)(1) through (a)(7) which
are the substantive categories.
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
    # (a)(1) — unauthorized extension of credit
    "fcba.a1a": Atom(
        "fcba.a1a",
        "The reflection on the periodic statement is of an extension of credit.",
        "1026.13(a)(1)",
    ),
    "fcba.a1b": Atom(
        "fcba.a1b",
        "The extension of credit was not made to the consumer.",
        "1026.13(a)(1)",
    ),
    "fcba.a1c": Atom(
        "fcba.a1c",
        "The extension of credit was not made to a person with actual, implied, or apparent authority to use the consumer's credit card or open-end credit plan.",
        "1026.13(a)(1)",
    ),

    # (a)(2) — extension of credit not identified per requirements
    "fcba.a2a": Atom(
        "fcba.a2a",
        "The reflection on the periodic statement is of an extension of credit.",
        "1026.13(a)(2)",
    ),
    "fcba.a2b": Atom(
        "fcba.a2b",
        "The extension of credit is not identified in accordance with the requirements of § 1026.7(a)(2) or (b)(2), as applicable.",
        "1026.13(a)(2)",
    ),
    "fcba.a2c": Atom(
        "fcba.a2c",
        "The extension of credit is not identified in accordance with the requirements of § 1026.8.",
        "1026.13(a)(2)",
    ),

    # (a)(3) — property or services not accepted or not delivered as agreed
    "fcba.a3a": Atom(
        "fcba.a3a",
        "The reflection on the periodic statement is of an extension of credit for property or services.",
        "1026.13(a)(3)",
    ),
    "fcba.a3b": Atom(
        "fcba.a3b",
        "The property or services were not accepted by the consumer or the consumer's designee.",
        "1026.13(a)(3)",
    ),
    "fcba.a3c": Atom(
        "fcba.a3c",
        "The property or services were not delivered to the consumer or the consumer's designee as agreed.",
        "1026.13(a)(3)",
    ),

    # (a)(4) — failure to credit a payment
    "fcba.a4": Atom(
        "fcba.a4",
        "The periodic statement reflects the creditor's failure to credit properly a payment or other credit issued to the consumer's account.",
        "1026.13(a)(4)",
    ),

    # (a)(5) — computational error
    "fcba.a5": Atom(
        "fcba.a5",
        "The periodic statement reflects a computational or similar error of an accounting nature made by the creditor.",
        "1026.13(a)(5)",
    ),

    # (a)(6) — request for clarification
    "fcba.a6a": Atom(
        "fcba.a6a",
        "The reflection on the periodic statement is of an extension of credit.",
        "1026.13(a)(6)",
    ),
    "fcba.a6b": Atom(
        "fcba.a6b",
        "The consumer requests additional clarification, including documentary evidence, regarding the extension of credit.",
        "1026.13(a)(6)",
    ),

    # (a)(7) — failure to mail or deliver statement
    "fcba.a7": Atom(
        "fcba.a7",
        "The creditor failed to mail or deliver a periodic statement to the consumer.",
        "1026.13(a)(7)",
    ),
}


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def _char_field(atom_id: str, atom: Atom) -> SchemaField:
    return SchemaField(
        atom_id=atom_id,
        evaluation_mode=EvalMode.CHARACTERIZED,
        specification=(
            f"Characterize whether the dispute record, account history, and "
            f"transaction details support: '{atom.statement}'"
        ),
        undetermined_rule="Evidence is missing or contradictory in the available records.",
    )


FCBA_SCHEMA = Schema(
    name="FCBA § 1026.13(a) billing error definition",
    atoms=ATOMS,
    fields={atom_id: _char_field(atom_id, atom) for atom_id, atom in ATOMS.items()},
)


# ---------------------------------------------------------------------------
# Tree construction helpers (same shape as PA)
# ---------------------------------------------------------------------------

def leaf(atom_id: str) -> Leaf:
    return Leaf(atom_id=atom_id)


def all_of(children, label="ALL", provenance=Provenance.STRUCTURAL, source=""):
    return CardinalityNode(
        n=len(children), children=children, surface_label=label,
        provenance=provenance, source_span=source,
    )


def any_of(children, label="ANY", provenance=Provenance.STRUCTURAL, source=""):
    return CardinalityNode(
        n=1, children=children, surface_label=label,
        provenance=provenance, source_span=source,
    )


# ---------------------------------------------------------------------------
# Sub-trees per enumerated category
# ---------------------------------------------------------------------------

# (a)(1) — unauthorized: extension AND not-to-consumer AND not-to-authorized-person
# The "not made to the consumer OR to a person with authority" is structurally an
# AND between (not to consumer) and (not to authorized person). The disjunction
# in the policy text is inside a negation: "not made to X or Y" means
# "not made to X AND not made to Y" by De Morgan.
unauthorized = all_of(
    [leaf("fcba.a1a"), leaf("fcba.a1b"), leaf("fcba.a1c")],
    label="ALL (unauthorized extension)",
    provenance=Provenance.STRUCTURAL,
    source="(a)(1) — De Morgan on 'not made to consumer or authorized person'",
)
unauthorized.confidence = 0.9
unauthorized.latent_type = "scope (De Morgan transformation)"

# (a)(2) — not identified per requirements: extension AND (not per 1026.7) AND (not per 1026.8)
# The "and" between 1026.7 and 1026.8 is transcribed.
not_identified = all_of(
    [leaf("fcba.a2a"), leaf("fcba.a2b"), leaf("fcba.a2c")],
    label="ALL (not identified per requirements)",
    provenance=Provenance.TRANSCRIBED,
    source="(a)(2) — '1026.7(a)(2) or (b)(2), as applicable, and 1026.8'",
)

# (a)(3) — property/services issue: extension for property OR services, AND
# (not accepted OR not delivered as agreed)
not_accepted_or_undelivered = any_of(
    [leaf("fcba.a3b"), leaf("fcba.a3c")],
    label="not accepted OR not delivered",
    provenance=Provenance.TRANSCRIBED,
    source="(a)(3) — 'not accepted ... or not delivered'",
)

property_services_issue = all_of(
    [leaf("fcba.a3a"), not_accepted_or_undelivered],
    label="ALL (property/services issue)",
    provenance=Provenance.STRUCTURAL,
    source="(a)(3) — extension AND (not accepted OR not delivered)",
)

# (a)(4) — atomic: single failure-to-credit proposition
failure_to_credit = leaf("fcba.a4")

# (a)(5) — atomic: single computational-error proposition
computational_error = leaf("fcba.a5")

# (a)(6) — request for clarification: extension AND consumer-requests-clarification
clarification_request = all_of(
    [leaf("fcba.a6a"), leaf("fcba.a6b")],
    label="ALL (clarification request)",
    provenance=Provenance.STRUCTURAL,
    source="(a)(6) — extension AND consumer requests clarification",
)

# (a)(7) — atomic: failure to mail/deliver statement
failure_to_deliver = leaf("fcba.a7")


# ---------------------------------------------------------------------------
# D1 — IS_BILLING_ERROR — any one of the seven categories triggers
# ---------------------------------------------------------------------------

FCBA_D1_TREE = any_of(
    [
        unauthorized,
        not_identified,
        property_services_issue,
        failure_to_credit,
        computational_error,
        clarification_request,
        failure_to_deliver,
    ],
    label="ANY of seven billing error categories",
    provenance=Provenance.STRUCTURAL,
    source="(a)(1)–(a)(7) — enumerated definition; meeting any constitutes a billing error",
)

FCBA_D1 = Determination(
    id="FCBA.D1",
    description="The transaction or event qualifies as a 'billing error' under 12 CFR § 1026.13(a).",
    tree=FCBA_D1_TREE,
    provenance=Provenance.TRANSCRIBED,
    polarity="positive",
    linked_to="FCBA.D2",
    source_span="1026.13(a) — 'the term billing error means'",
)


# ---------------------------------------------------------------------------
# D2 — NOT_BILLING_ERROR (inferred from complement)
# ---------------------------------------------------------------------------

from rulekit import NotNode

FCBA_D2 = Determination(
    id="FCBA.D2",
    description="The transaction or event does not qualify as a billing error (structural complement of D1).",
    tree=NotNode(
        child=FCBA_D1_TREE,
        provenance=Provenance.INFERRED,
        source_span="Inferred from complement of (a) definition",
        confidence=0.95,
        latent_type="meta-interpretation (D2 complement of definitional disjunction)",
    ),
    provenance=Provenance.INFERRED,
    polarity="negative",
    linked_to="FCBA.D1",
    source_span="Implicit structural complement",
)


FCBA_DETERMINATIONS = {"FCBA.D1": FCBA_D1, "FCBA.D2": FCBA_D2}
