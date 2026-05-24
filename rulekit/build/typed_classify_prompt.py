"""
typed_classify_prompt.py — extended Stage-1 classification for the typed
decomposer.

This module is the evaluation playground for the typed extension to the
build pipeline's Stage-1 classifier. It is intentionally NOT wired into
production ``rulekit/build/decomposer.py`` yet. We iterate on the prompt
against eval cases here, then commit it once it's stable.

WHAT'S NEW vs the production prompt
====================================

Production prompt classifies into: leaf | and | or | not | at_least.
This prompt adds: comparison.

A claim is classified as ``comparison`` when:
  - It expresses a numeric inequality or equality between two terms
  - Both terms (LHS, RHS) are extractable as numeric values (case data
    or policy constants) or as arithmetic expressions over them

Crucially, this prompt only IDENTIFIES the comparison. The sub-
decomposition of LHS/RHS into numeric leaves, constants, and arithmetic
nodes is a SEPARATE prompt (next session's work). At this stage we just
need the LLM to say "this is a comparison, operator=LEQ, LHS describes
contract_first_year_salary, RHS describes 9.12% of salary_cap".

DESIGN NOTES
============

1. The prompt extends the EXISTING examples rather than replacing them,
   so Boolean regression is preserved.

2. Adversarial guidance is explicit: numbers in a claim do NOT
   automatically make it a comparison. Counting nouns ("6 weeks of
   physical therapy"), temporal validity ("within 6 months"), and
   identifying numbers ("Section 1026.13(a)(3)") are NOT comparisons.

3. "Not above X" should be classified DIRECTLY as LEQ, not as
   NOT(GT(...)). Semantic-equivalence collapse at the prompt layer
   keeps the engine tree smaller.

4. AND-of-comparisons (the bracket pattern) is handled by the existing
   AND classifier: the top-level claim "team salary at-or-above cap and
   below first apron" gets classified as AND(2), and each child is
   re-decomposed on the next call. So this prompt doesn't need a
   special bracket case — composition handles it.
"""

from __future__ import annotations


TYPED_DECOMPOSE_PROMPT = """You are a {role} reading a {domain} policy.

{background}

You are building a logical decomposition tree for a determination. At each
step you are given a single claim. You must classify the claim into one of:

  - LEAF (atomic, not decomposable)
  - AND / OR / NOT / AT_LEAST (Boolean composition)
  - COMPARISON (numeric inequality or equality)

Determination being decomposed: {determination_id}
Determination description: {determination_description}
{scope_section}

Current claim to classify: "{claim}"

Path from determination root to this claim (breadcrumb):
{path}

POLICY TEXT (excerpt):
{policy_text}

DECIDING WHETHER A CLAIM IS ATOMIC (LEAF)
==========================================

A claim is ATOMIC when:
- It is a single proposition evaluable from typical evidence as true,
  false, or undetermined.
- It contains no logical connectives (and, or, not, either, neither,
  unless, except) that would require decomposition.
- It is NOT a numeric inequality or equality between two extractable
  terms (those are COMPARISONS — see below).
- Further splitting would produce sub-claims that always co-evaluate
  from the same evidence source.

Numbers appearing in a claim do NOT automatically make it composed.
The following remain ATOMIC:
- "Member has completed a 6-week course of physical therapy."
  (Atomic: 6 weeks is a fixed-duration completion attribute, not a
  threshold for engine arithmetic.)
- "Member has an MRI within 6 months of the request."
  (Atomic: temporal validity attribute, not a numeric comparison.)
- "The submission occurred within 30 days of the qualifying event."
  (Atomic temporal-validity attribute.)
- "The applicant holds a valid license issued by the state board."
  (Atomic, no numerics involved.)

DECIDING WHETHER A CLAIM IS BOOLEAN-COMPOSED
=============================================

A claim is BOOLEAN-COMPOSED when:
- It contains explicit conjunction ("all of the following", "and"),
  disjunction ("any of the following", "or"), negation ("not", "without"),
  or cardinality ("at least N of").
- The policy's drafting explicitly enumerates sub-clauses for this claim.
- The claim can be separated into independently evaluable sub-claims.

Examples of Boolean-composed claims:
- "Member has confirmed cervical radiculopathy or cervical myelopathy."
  → OR of two atomic diagnosis claims.
- "Member must have completed 6 weeks of physical therapy and the
  therapy was supervised." → AND of two atomic claims.
- "Member trialed at least two of: NSAIDs, muscle relaxants, neuropathic
  agents, oral corticosteroids." → AT_LEAST with N=2 and 4 children.
- "The transaction was not authorized by the cardholder." → NOT of one
  atomic claim.

DECIDING WHETHER A CLAIM IS A COMPARISON
=========================================

A claim is a COMPARISON when:
- It expresses an inequality (≤, <, ≥, >) or equality (=) between two
  numeric terms.
- BOTH terms are concrete enough that the engine can compare them
  numerically. Each term is either:
    (i) a numeric attribute extractable from case data
       (e.g., team_salary, contract_length_years, player_years_of_service)
    (ii) a named policy constant
       (e.g., salary_cap, first_apron_level, taxpayer_threshold)
    (iii) a simple arithmetic expression over (i) or (ii)
       (e.g., "9.12% of the salary cap", "105% of prior salary",
        "outgoing salary plus $250,000")

The comparison operators are:
  - "leq"  for "at most", "no greater than", "does not exceed", "≤", "<="
  - "lt"   for "below", "less than", "under", "<", strictly less than
  - "geq"  for "at least", "no less than", "is at or above", "≥", ">="
  - "gt"   for "above", "greater than", "exceeds", ">", strictly greater
  - "eq"   for "equals", "is", "=", numeric identity

PHRASING NORMALIZATION
=======================

Prefer the direct comparison operator over a negated opposite:
- "Team salary is not above the salary cap" → use leq (NOT gt).
- "Contract length is not less than 2 years" → use geq (NOT lt).
This keeps the engine tree smaller. Use NOT(comparison) only when the
policy specifically negates a comparison the case must apply (rare).

Examples of comparisons:
- "Contract length must not exceed 4 years." → LEQ.
  LHS describes contract_length; RHS is the integer constant 4.
- "Team salary is below the salary cap." → LT.
  LHS is team_salary; RHS is the named constant salary_cap.
- "The player has at least 10 Years of Service." → GEQ.
  LHS is player_years_of_service; RHS is the integer 10.
- "Contract salary may not exceed 9.12% of the salary cap." → LEQ.
  LHS is contract_first_year_salary; RHS is 9.12% of salary_cap
  (arithmetic: TIMES_CONST(0.0912, salary_cap)).
- "The aggregated incoming salary may not exceed the aggregated outgoing
  salary plus $250,000." → LEQ. LHS is aggregated incoming; RHS is
  aggregated outgoing PLUS_CONST $250,000.

When a single sentence combines a comparison with a Boolean connective
("team salary is at or above the salary cap AND below the first apron"),
classify as AND first; each child will be re-classified on its own call
and individually identified as a comparison. Do not try to embed the
comparison inside the AND output here.

DE MORGAN TRANSFORMATIONS
==========================

When the policy expresses a condition as the negation of a disjunction
("not A or B"), the equivalent positive form is the conjunction of
negations: AND(NOT A, NOT B). Apply this transformation explicitly.

PROVENANCE
============

For each operator you commit to, mark its source:
- "transcribed": the policy explicitly draws this operator.
- "structural": the operator is implied by policy organization.
- "inferred": the operator is the reasonable reader's interpretation
  when the policy is silent.

For inferred operators, include "latent_type" (scope / binding /
edge-case / meta-interpretation) and "confidence" (0.0–1.0).

OUTPUT FORMAT
==============

If the claim is ATOMIC (LEAF), output:
{{
  "type": "leaf",
  "claim": "{claim}",
  "source_span": "<policy section/subsection reference>"
}}

If the claim is BOOLEAN-COMPOSED, output:
{{
  "type": "and" | "or" | "not" | "at_least",
  "n": <integer, only for at_least>,
  "children": [
    {{"claim": "<sub-claim 1>", "source_span": "<reference>"}},
    {{"claim": "<sub-claim 2>", "source_span": "<reference>"}}
  ],
  "surface_label": "<short descriptive label>",
  "provenance": "transcribed" | "structural" | "inferred",
  "source_span": "<policy section/subsection reference>"
}}

If the claim is a COMPARISON, output:
{{
  "type": "comparison",
  "operator": "leq" | "lt" | "geq" | "gt" | "eq",
  "lhs_description": "<short noun phrase describing the LHS, e.g., 'contract first-year salary' or 'team salary'>",
  "rhs_description": "<short phrase describing the RHS, e.g., '9.12% of the salary cap' or 'the integer 4' or 'the salary cap'>",
  "lhs_kind": "numeric_leaf" | "constant" | "arithmetic",
  "rhs_kind": "numeric_leaf" | "constant" | "arithmetic",
  "surface_label": "<short label>",
  "source_span": "<policy reference>",
  "provenance": "transcribed" | "structural" | "inferred"
}}

For inferred operators, also include "latent_type" and "confidence".

The lhs_kind / rhs_kind fields hint at how the LHS/RHS will be
sub-decomposed in a follow-up step. Use:
  - "numeric_leaf" when the term names a case-data attribute.
  - "constant" when the term is a bare integer/decimal or a named
    policy constant (salary cap, threshold values).
  - "arithmetic" when the term is a computed expression (a percentage
    of something, a sum, a difference).

Use the policy's own numbering for source_span (e.g., "2.1(a)",
"1026.13(a)(3)"). Never put a sentence in source_span.

Output ONLY the JSON object. No preamble, no commentary, no markdown
code fences.
"""


def render_prompt(*, role: str, domain: str, background: str,
                  determination_id: str, determination_description: str,
                  scope_section: str, claim: str, path: str,
                  policy_text: str) -> str:
    """Render the typed classification prompt with the given context."""
    return TYPED_DECOMPOSE_PROMPT.format(
        role=role,
        domain=domain,
        background=background,
        determination_id=determination_id,
        determination_description=determination_description,
        scope_section=scope_section,
        claim=claim,
        path=path,
        policy_text=policy_text,
    )
