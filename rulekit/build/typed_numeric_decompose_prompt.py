"""
typed_numeric_decompose_prompt.py — Piece 2 of the typed Build pipeline.

The Stage-1 classifier (typed_classify_prompt.py) identifies that a claim is a
numeric comparison and produces:
  - operator: the comparison operator (leq, lt, geq, gt, eq)
  - lhs_description, rhs_description: free-text descriptions of each side
  - lhs_kind, rhs_kind: hints — "numeric_leaf", "constant", or "arithmetic"

Piece 2 takes ONE of those (description, kind) pairs and decomposes it into a
structured spec tree the engine conversion stage can consume.

This module is intentionally separate from production decomposer.py until
validated. Same iteration pattern as Piece 1: eval cases first, prompt drafted
here, live LLM validation, promote when stable.

ROUTING DECISIONS
=================

The prompt produces one of four output spec types:

  - numeric_leaf  → engine NumericLeaf bound by Map's extraction
  - constant      → engine Constant with value or named label
  - unary_arithmetic → engine TimesConst / PlusConst / MinusConst /
                       ConstMinus / DivByConst / ConstDivBy node
  - derived_atom  → numeric atom whose VALUE is computed by Map, not by the
                    engine. Used for aggregates, max-of-formulas, conditional
                    formulas, named quantities — anything outside the engine's
                    deliberately-bounded arithmetic vocabulary.

The fourth category (derived_atom) is the architecturally important one.
The typed engine intentionally lacks SumNode, MaxNode, MinNode, and
conditional operators. When the policy expresses computations that need
those, we route them to Map: the LLM produces a single derived numeric atom
per case, and the engine sees a NumericLeaf for that derived value.

This keeps the engine small, bounded, and verifiable. The cost is that the
trace's resolution stops at the derived atom — the engine can show "max
salary ceiling = $42,176,400" but can't expand "= max(25% × cap, 105% ×
prior)" inline. Acceptable trade-off: the derivation can be inspected via
Map's audit log; the engine's job is composition, not arithmetic.
"""

from __future__ import annotations


NUMERIC_DECOMPOSE_PROMPT = """You are decomposing a numeric expression into a
structured spec the rule engine can evaluate.

You are given:
  - A free-text DESCRIPTION of a numeric expression (e.g., "9.12% of the
    Salary Cap" or "team salary" or "outgoing salary plus $250,000").
  - A KIND hint from the upstream classifier: "numeric_leaf", "constant",
    or "arithmetic".

Your job: produce a structured spec for this expression.

The KIND hint is usually right but not always; if the description clearly
indicates a different category, use your judgment.

Description: "{description}"
Kind hint: "{kind}"

YOU MUST PRODUCE ONE OF FOUR SPEC TYPES
========================================

(1) numeric_leaf
    Used when the expression names a single numeric attribute that will be
    extracted from case data per case (e.g., "team salary", "contract first-
    year salary", "player Years of Service"). The Map substrate's LLM will
    extract the value for each case.

(2) constant
    Used when the expression is either:
    - A bare numeric literal (an integer, decimal, dollar amount): output
      "value" with the number.
    - A named policy constant whose value is known and stable (e.g., "the
      salary cap", "the First Apron Level", "the Second Apron Level"):
      output "label" with a stable snake_case name.

(3) unary_arithmetic
    Used when the expression is one of the SIX engine-expressible unary
    arithmetic operations:

      - times_const   : child × constant
                        Examples: "9.12% of cap", "105% of prior salary",
                                  "1.25 times outgoing salary"
      - plus_const    : child + constant
                        Examples: "outgoing salary plus $250,000",
                                  "prior salary plus $1 million"
      - minus_const   : child − constant  (constant subtracted from child)
                        Examples: "team salary minus $5 million"
      - const_minus   : constant − child  (child subtracted from constant)
                        Examples: "salary cap minus team salary",
                                  "First Apron minus current salary"
      - div_by_const  : child ÷ constant
                        Examples: "team salary divided by 2"
      - const_div_by  : constant ÷ child
                        Examples: "12 divided by the multiplier"

    Each unary_arithmetic spec has:
      - operator: one of the six above
      - constant: a number (if literal) OR constant_label (if named)
      - child: a nested spec (numeric_leaf, constant, or another
        unary_arithmetic — RECURSE if the child is itself arithmetic)

(4) derived_atom
    Used when the expression is arithmetic the engine CANNOT express:

      - aggregate_sum: sum over multiple instances
        Examples: "aggregate first-year salaries of all contracts signed
                   under MLE", "sum of outgoing players' salaries"

      - max_of / min_of: max or min over two or more terms
        Examples: "the greater of 25% of cap or 105% of prior salary",
                  "the lesser of $5M or 20% of cap"

      - conditional: arithmetic whose form depends on a condition
        Examples: "25% of cap if YOS<7, otherwise 30% of cap"

      - named_quantity: a named derived quantity defined elsewhere in the
        policy (e.g., "the Maximum Annual Salary under Section 7")

    derived_atom specs do NOT decompose further. They become a single
    NumericLeaf at the engine level. Map computes the value per case.

CRITICAL ROUTING RULE
======================

The engine vocabulary is INTENTIONALLY limited to unary arithmetic with a
constant. If you see an expression that requires SUM over multiple instances,
MAX/MIN over multiple terms, or any conditional formula, route it to
derived_atom — do not attempt to expand it into a tree of engine nodes.

If you are unsure whether arithmetic is engine-expressible: ask whether it
can be written as one of the six unary operators with a single constant and
a single (possibly recursive) child. If yes → unary_arithmetic. If no →
derived_atom.

OUTPUT FORMAT
==============

For numeric_leaf:
{{
  "spec_type": "numeric_leaf",
  "atom_id_hint": "<snake_case identifier — e.g. 'team_salary', 'player_years_of_service'>",
  "statement": "<one-sentence description of what Map should extract>"
}}

For constant (bare value):
{{
  "spec_type": "constant",
  "value": <number as integer or decimal — no quotes>
}}

For constant (named label):
{{
  "spec_type": "constant",
  "label": "<snake_case label — e.g. 'salary_cap', 'first_apron_level', 'second_apron_level', 'tax_level'>"
}}

For unary_arithmetic:
{{
  "spec_type": "unary_arithmetic",
  "operator": "times_const" | "plus_const" | "minus_const" | "const_minus" | "div_by_const" | "const_div_by",
  "constant": <number as integer or decimal>,             // EITHER this
  "constant_label": "<snake_case label>",                  // OR this (named constant)
  "child": {{ ... nested spec — RECURSE if child is itself arithmetic ... }}
}}

For derived_atom:
{{
  "spec_type": "derived_atom",
  "atom_id_hint": "<snake_case identifier>",
  "statement": "<one-sentence description of what Map should compute>",
  "computation_kind": "aggregate_sum" | "max_of" | "min_of" | "conditional" | "named_quantity"
}}

EXAMPLES
=========

Description: "team salary"
Kind hint: numeric_leaf
Output:
{{
  "spec_type": "numeric_leaf",
  "atom_id_hint": "team_salary",
  "statement": "The team's current team salary in US dollars."
}}

Description: "the integer 4"
Kind hint: constant
Output:
{{
  "spec_type": "constant",
  "value": 4
}}

Description: "the Salary Cap"
Kind hint: constant
Output:
{{
  "spec_type": "constant",
  "label": "salary_cap"
}}

Description: "9.12% of the Salary Cap"
Kind hint: arithmetic
Output:
{{
  "spec_type": "unary_arithmetic",
  "operator": "times_const",
  "constant": 0.0912,
  "child": {{
    "spec_type": "constant",
    "label": "salary_cap"
  }}
}}

Description: "outgoing aggregated salary plus $250,000"
Kind hint: arithmetic
Output:
{{
  "spec_type": "unary_arithmetic",
  "operator": "plus_const",
  "constant": 250000,
  "child": {{
    "spec_type": "numeric_leaf",
    "atom_id_hint": "aggregated_outgoing_pre_trade_salary",
    "statement": "Sum of pre-trade first-year salaries of all players the team is sending in the trade."
  }}
}}

Description: "the salary cap minus the team's current salary"
Kind hint: arithmetic
Output:
{{
  "spec_type": "unary_arithmetic",
  "operator": "const_minus",
  "constant_label": "salary_cap",
  "child": {{
    "spec_type": "numeric_leaf",
    "atom_id_hint": "team_salary",
    "statement": "The team's current team salary in US dollars."
  }}
}}

Description: "the greater of 25% of the Salary Cap or 105% of the player's prior-year salary"
Kind hint: arithmetic
Output:
{{
  "spec_type": "derived_atom",
  "atom_id_hint": "max_salary_ceiling",
  "statement": "The greater of 25% of the Salary Cap or 105% of the player's prior-year salary.",
  "computation_kind": "max_of"
}}

Description: "aggregate first-year Salaries of all Player Contracts signed under the MLE"
Kind hint: arithmetic
Output:
{{
  "spec_type": "derived_atom",
  "atom_id_hint": "aggregated_mle_first_year_salary",
  "statement": "Sum of first-year salaries of all contracts the team has signed under the MLE in this Salary Cap Year.",
  "computation_kind": "aggregate_sum"
}}

Description: "9.12% of (the Salary Cap minus the prior-year contract salary)"
Kind hint: arithmetic
Output:
{{
  "spec_type": "unary_arithmetic",
  "operator": "times_const",
  "constant": 0.0912,
  "child": {{
    "spec_type": "unary_arithmetic",
    "operator": "const_minus",
    "constant_label": "salary_cap",
    "child": {{
      "spec_type": "numeric_leaf",
      "atom_id_hint": "player_prior_year_salary",
      "statement": "The player's salary in the final season of his prior contract."
    }}
  }}
}}

Output ONLY the JSON spec. No preamble, no commentary, no markdown code
fences.
"""


def render_numeric_decompose_prompt(*, description: str, kind: str) -> str:
    """Render the numeric sub-decomposer prompt for one (description, kind) pair."""
    return NUMERIC_DECOMPOSE_PROMPT.format(description=description, kind=kind)
