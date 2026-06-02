# Proposition Layer

RuleKit distinguishes between a proposition being asserted and a proposition
being established. This matters when a customer, member, applicant, patient, or
other claimant narrative is part of the evidence packet.

## Purpose

The proposition layer sits between raw case text and atom binding:

```text
raw case packet
  -> canonical propositions with source posture
  -> Map atom bindings
  -> deterministic DAG
  -> disposition and trace
```

The normalizer may say "the member asserted X." It must not silently turn that
into "X was true."

## Case Packet Shape

Cases may include `structured_fields.propositions` or
`structured_fields.canonical_propositions`:

```json
{
  "propositions": [
    {
      "proposition_id": "p1",
      "canonical_concept": "payment_posted_before_due_date",
      "atom_id": "credit.payment_timely",
      "value": true,
      "assertion_status": "asserted",
      "source_posture": "claimant_assertion",
      "speaker": "member",
      "source_ids": ["member_statement"],
      "evidence_text": "I paid before the due date."
    }
  ]
}
```

Supported assertion statuses include:

- `asserted`
- `established`
- `supported`
- `confirmed`
- `documented`
- `contradicted`
- `conflicting`
- `not_addressed`

Supported source postures include:

- `claimant_assertion`
- `respondent_assertion`
- `institutional_record`
- `official_record`
- `third_party_record`
- `expert_record`
- `system_log`
- `unknown`

## Default Binding Rule

By default, only these assertion statuses can bind atoms:

- `established`
- `supported`
- `confirmed`
- `documented`

An `asserted` claimant proposition is preserved in the Map record as an
undetermined binding with provenance metadata. It does not become true merely
because the claimant said it.

## Source Posture Validation

Atom binding policies can require source postures:

```json
{
  "required_source_postures_for_true": ["institutional_record"]
}
```

This lets a policy accept a bank ledger, system log, official record, or
clinical record while rejecting claimant assertion for the same atom.

## Profile Vocabulary

Programs can define sanctioned vocabulary in
`program.metadata.extras.map_profile.concepts`:

```json
{
  "map_profile": {
    "concepts": {
      "payment_posted_before_due_date": {
        "lexical_cues": [
          "paid before the due date",
          "posted before the due date"
        ],
        "atom_bindings": [
          {
            "id": "payment_timely_from_record",
            "atom_id": "credit.payment_timely",
            "value": true,
            "accepted_assertion_statuses": ["established"],
            "accepted_source_postures": ["institutional_record"]
          }
        ]
      }
    }
  }
}
```

The vocabulary can be co-authored by the builder agent from policy text,
labeled cases, mismatch analysis, and general linguistic knowledge. The final
artifact remains reviewable policy-pack data.

## Design Principle

The normalizer classifies propositions and source posture. The Map layer binds
atoms only when the proposition and source posture satisfy the policy profile
and atom binding policy. The deterministic engine never has to guess whether
"the member said X" means "X was established."

