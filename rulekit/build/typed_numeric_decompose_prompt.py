"""
typed_numeric_decompose_prompt.py - Piece 2 of the typed Build pipeline.

The Stage-1 classifier (typed_classify_prompt.py) identifies that a claim is a
numeric comparison and produces:
  - operator: the comparison operator (leq, lt, geq, gt, eq)
  - lhs_description, rhs_description: free-text descriptions of each side
  - lhs_kind, rhs_kind: hints - "numeric_leaf", "constant", or "arithmetic"

Piece 2 takes ONE of those (description, kind) pairs and decomposes it into a
structured spec tree the engine conversion stage can consume.

ROUTING DECISIONS
=================

The prompt produces one of TEN output spec types, grouped by purpose:

  Primitive extraction (Map binds the value):
    - numeric_leaf       -> engine NumericLeaf bound by Map's extraction
    - constant           -> engine Constant with value or named label

  Single-operand-and-constant arithmetic (engine-computed):
    - unary_arithmetic   -> engine TimesConst / PlusConst / MinusConst /
                            ConstMinus / DivByConst / ConstDivBy

  Multi-operand arithmetic (engine-computed; NEW as of Phase 3):
    - plus / minus / mul -> engine PlusNode / MinusNode / MulNode (binary)
    - sum / max / min    -> engine SumNode / MaxNode / MinNode (variadic, N>=2)

  Map-evaluated quantities (engine cannot express):
    - derived_atom       -> numeric atom whose VALUE is computed by Map.
                            ONLY for "conditional" arithmetic (form depends
                            on a runtime condition) and "named_quantity"
                            (defined elsewhere in the policy).

DESIGN NOTE (PHASE 3 CHANGE)
=============================

Earlier versions of this prompt routed aggregates (sum), maxes, and mins
to derived_atom on the assumption that Map could compute them per case.
Phase 2 empirical findings showed Map (Sonnet 4.6 and Opus 4.7) reliably
extracts case-stated facts but does NOT reliably compute derived values
across atom boundaries, even when explicitly permitted. The architecture
now expresses sum/max/min via dedicated engine nodes that compose
primitive atom bindings.

The result is sharper division of labor: Map extracts case-stated
primitive facts; the engine composes derived facts through structural
arithmetic. The trace can show "max_salary_ceiling = max(25% x cap,
105% x prior) = max(35147000, 31500000) = 35147000" with every step
visible to audit.
"""

from __future__ import annotations


NUMERIC_DECOMPOSE_PROMPT = """You are decomposing a numeric expression into a
structured spec the rule engine can evaluate.

You are given:
  - A free-text DESCRIPTION of a numeric expression (e.g., "the greater of
    25% of the Salary Cap or 105% of the player's prior-year salary").
  - A KIND hint from the upstream classifier: "numeric_leaf", "constant",
    or "arithmetic".

Your job: produce a structured spec for this expression.

The KIND hint is usually right but not always; if the description clearly
indicates a different category, use your judgment.

Description: "{description}"
Kind hint: "{kind}"

YOU MUST PRODUCE ONE OF TEN SPEC TYPES
=======================================

(1) numeric_leaf
    The expression names a single numeric attribute that will be
    extracted from case data per case (e.g., "team salary", "contract
    first-year salary", "player Years of Service"). Map's LLM extracts
    the value for each case.

(2) constant
    The expression is either:
    - A bare numeric literal (an integer, decimal, dollar amount): output
      "value" with the number.
    - A named policy constant whose value is known and stable (e.g., "the
      salary cap", "the First Apron Level", "the Second Apron Level"):
      output "label" with a stable snake_case name.

(3) unary_arithmetic
    The expression is one of the SIX engine unary operations
    (child OP constant or constant OP child):

      - times_const   : child * constant
                        Examples: "9.12% of cap", "105% of prior salary",
                                  "1.25 times outgoing salary"
      - plus_const    : child + constant
                        Examples: "outgoing salary plus $250,000",
                                  "prior salary plus $1 million"
      - minus_const   : child - constant
                        Examples: "team salary minus $5 million"
      - const_minus   : constant - child
                        Examples: "salary cap minus team salary",
                                  "First Apron minus current salary"
      - div_by_const  : child / constant
                        Examples: "team salary divided by 2"
      - const_div_by  : constant / child
                        Examples: "12 divided by the multiplier"

    Use unary_arithmetic when ONE side of the operation is a constant
    (literal or named) and the other side is a single numeric expression.

(4) plus / minus / mul   [binary; both operands are arbitrary expressions]
    Use these when the expression combines TWO case-bound quantities (or
    derived sub-expressions), neither of which is a fixed constant:

      - plus  : left + right
                Examples:
                  "team salary plus the first-year salary of the new contract"
                  "the team salary immediately after the signing" (= pre-
                  signing salary + the signing's first-year salary)
                  "the player's prior salary plus the contract's bonus pool"

      - minus : left - right
                Examples:
                  "the assignee team's salary minus the incoming salaries"
                  "post-trade team salary minus outgoing aggregate salary"

      - mul   : left * right
                Examples:
                  "the multiplier times the player's qualifying offer salary"
                  (rare; most multiplicative operations are times_const)

    Each binary spec has:
      - "left":  nested spec for the left operand (any numeric spec type)
      - "right": nested spec for the right operand (any numeric spec type)

(5) sum / max / min   [variadic; N >= 2 children]
    Use these when the expression aggregates over a known set of terms:

      - sum : add N children together
              Examples:
                "the sum of player A's salary and player B's salary"
                "team salary plus the new contract's first-year salary
                 plus the new contract's bonus" (3-way add)

      - max : the greater of N terms
              Examples:
                "the greater of 25% of the Salary Cap or 105% of the
                 player's prior-year salary"
                "the highest of $5 million, 35% of the cap, or 105% of
                 prior salary"

      - min : the lesser of N terms
              Examples:
                "the lesser of $5 million or 20% of the cap"
                "the lesser of the agreed contract value and the
                 maximum allowed under section 7"

    Each variadic spec has:
      - "children": a list of nested specs (any numeric spec types)

    The engine's UNDETERMINED semantics: if any operand is unknown,
    the entire variadic result is UNDETERMINED. This is the correct
    architectural behavior: we cannot claim a value is the max if some
    inputs are unknown.

(6) derived_atom   [Map-evaluated; reserved for two specific cases]
    Use derived_atom ONLY when one of these applies:

      - conditional: arithmetic whose form depends on a runtime
                     condition the engine cannot pre-compose.
                     Example: "25% of cap if YOS < 7, otherwise 30% of
                     cap" - the form of the computation differs by case.

      - named_quantity: a named derived quantity defined elsewhere in
                        the policy that requires document-level
                        interpretation, OR an aggregate over an unknown-
                        cardinality set the case does not enumerate.
                        Example: "the Maximum Annual Salary under
                        Section 7" - the value depends on a multi-page
                        rule. Example: "the sum of all contracts signed
                        under the MLE this year" - the set of contracts
                        is not enumerated in the case.

    DO NOT use derived_atom for sum / max / min over enumerable terms -
    those have dedicated engine specs above (5).

CRITICAL ROUTING RULES
======================

Rule 1: "the greater/lesser of X or Y" / "max/min/maximum/minimum of"
        ALWAYS routes to max or min - NEVER derived_atom.

Rule 2: A sum of NAMED quantities (case-enumerable) routes to sum.
        An aggregate over an unspecified set routes to derived_atom
        with computation_kind=named_quantity.

Rule 3: A combination of two case-bound quantities with + or - or *
        routes to plus, minus, or mul. If ONE side is a constant
        (literal or named), use unary_arithmetic instead.

Rule 4: Reserve derived_atom for cases where the computation truly
        cannot be expressed as a tree of the above specs - typically
        only "conditional" formulas and "named_quantity" references.

OUTPUT FORMAT
==============

For numeric_leaf:
{{
  "spec_type": "numeric_leaf",
  "atom_id_hint": "<snake_case identifier>",
  "statement": "<one-sentence description of what Map should extract>"
}}

For constant:
{{
  "spec_type": "constant",
  "value": <number>          // EITHER a bare literal
  // OR
  "label": "<snake_case>"     // a named constant
}}

For unary_arithmetic:
{{
  "spec_type": "unary_arithmetic",
  "operator": "times_const" | "plus_const" | "minus_const" | "const_minus" | "div_by_const" | "const_div_by",
  "constant": <number>,                // EITHER a literal
  "constant_label": "<snake_case>",     // OR a named constant
  "child": {{ ...nested spec... }}
}}

For binary (plus / minus / mul):
{{
  "spec_type": "plus" | "minus" | "mul",
  "left":  {{ ...nested spec... }},
  "right": {{ ...nested spec... }},
  "surface_label": "<optional short description for the trace>"
}}

For variadic (sum / max / min):
{{
  "spec_type": "sum" | "max" | "min",
  "children": [
    {{ ...nested spec 1... }},
    {{ ...nested spec 2... }},
    ...
  ],
  "surface_label": "<optional short description for the trace>"
}}

For derived_atom (conditional or named_quantity only):
{{
  "spec_type": "derived_atom",
  "atom_id_hint": "<snake_case identifier>",
  "statement": "<one-sentence description of what Map should compute>",
  "computation_kind": "conditional" | "named_quantity"
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

Description: "the team's team salary immediately after the signing"
Kind hint: arithmetic
Output:
{{
  "spec_type": "plus",
  "left": {{
    "spec_type": "numeric_leaf",
    "atom_id_hint": "pre_signing_team_salary",
    "statement": "The team's team salary immediately before the signing in question."
  }},
  "right": {{
    "spec_type": "numeric_leaf",
    "atom_id_hint": "first_year_salary_plus_unlikely_bonuses",
    "statement": "The first-year Salary plus first-year Unlikely Bonuses of the signing in question."
  }},
  "surface_label": "team_salary_post_signing"
}}

Description: "the greater of 25% of the Salary Cap or 105% of the player's prior-year salary"
Kind hint: arithmetic
Output:
{{
  "spec_type": "max",
  "children": [
    {{
      "spec_type": "unary_arithmetic",
      "operator": "times_const",
      "constant": 0.25,
      "child": {{
        "spec_type": "constant",
        "label": "salary_cap"
      }}
    }},
    {{
      "spec_type": "unary_arithmetic",
      "operator": "times_const",
      "constant": 1.05,
      "child": {{
        "spec_type": "numeric_leaf",
        "atom_id_hint": "player_prior_year_salary",
        "statement": "The player's salary in the final season of his prior contract."
      }}
    }}
  ],
  "surface_label": "max_salary_ceiling"
}}

Description: "the lesser of $5,000,000 or 20% of the Salary Cap"
Kind hint: arithmetic
Output:
{{
  "spec_type": "min",
  "children": [
    {{
      "spec_type": "constant",
      "value": 5000000
    }},
    {{
      "spec_type": "unary_arithmetic",
      "operator": "times_const",
      "constant": 0.20,
      "child": {{
        "spec_type": "constant",
        "label": "salary_cap"
      }}
    }}
  ],
  "surface_label": "mle_or_20pct_cap"
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

Description: "25% of the Salary Cap if the player has fewer than 7 Years of Service, otherwise 30%"
Kind hint: arithmetic
Output:
{{
  "spec_type": "derived_atom",
  "atom_id_hint": "max_salary_pct_by_yos_bracket",
  "statement": "25% of the Salary Cap if YOS<7, 30% if YOS>=7.",
  "computation_kind": "conditional"
}}

Description: "the sum of first-year Salaries of all Player Contracts the team signs under the MLE"
Kind hint: arithmetic
Output:
{{
  "spec_type": "derived_atom",
  "atom_id_hint": "aggregated_mle_first_year_salary",
  "statement": "Sum of first-year Salaries of all Player Contracts the team has signed under the MLE in this Salary Cap Year.",
  "computation_kind": "named_quantity"
}}

NOTE: The aggregate above is derived_atom because the set of contracts
is not enumerable from a single case description. If the case explicitly
listed each contract, use sum with one child per stated contract.

Output ONLY the JSON spec. No preamble, no commentary, no markdown code
fences.
"""


def render_numeric_decompose_prompt(*, description: str, kind: str) -> str:
    """Render the numeric sub-decomposer prompt for one (description, kind) pair."""
    return NUMERIC_DECOMPOSE_PROMPT.format(description=description, kind=kind)
