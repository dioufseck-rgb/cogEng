"""
RuleKit contract: the boundary between producers of determination
programs and consumers of them (the engine plus Map).

A DeterminationProgram is the complete artifact a producer ships per
set of determinations. It contains the DAG (as a registry of nodes),
the Map spec (atom catalog plus extraction policy), the case input
schema, the test suite, and metadata about the program and its
production.

The contract is domain-agnostic. It does not assume that a
determination program was derived from a policy, that there is a
reader voice, or that the producer is an LLM. Domain-specific
concerns live in the producer's spec (e.g. `rulekit/build/spec.py`
for the LLM-driven build), not in the contract.

Public API:

    DeterminationProgram     -- top-level model
    ProgramMetadata          -- identification
    ProductionRecord         -- who built this and when
    DeterminationSpec        -- a named determination

    MapSpec                  -- atom catalog plus extraction policy
    BooleanAtom              -- atom returning Kleene
    NumericAtom              -- atom returning Decimal-or-UND
    AnyAtomSpec              -- discriminated union of the two

    AtomRef                  -- boolean leaf
    AndNodeSpec OrNodeSpec NotNodeSpec AtLeastNodeSpec
                             -- boolean operators
    ComparisonSpec           -- bridge from numeric to boolean

    NumericAtomRef           -- numeric leaf
    ConstantSpec             -- build-time numeric constant
    UnaryArithmeticSpec      -- child OP constant
    BinaryArithmeticSpec     -- left OP right (both numeric)
    VariadicArithmeticSpec   -- sum/max/min over N children
    ConditionalNumericSpec   -- IF condition THEN if_true ELSE if_false
    NamedQuantitySpec        -- numeric quantity delegated to Map

    AnyNodeSpec              -- discriminated union of all node specs
    BOOLEAN_NODE_KINDS       -- set of kind tags that are boolean-valued
    NUMERIC_NODE_KINDS       -- set of kind tags that are numeric-valued

    CaseInputSchema          -- shape of case input
    CaseInput                -- one case
    ExpectedOutcome          -- expected determination value
    TestCase                 -- map-input plus expected outcomes

    Provenance               -- TRANSCRIBED / STRUCTURAL / INFERRED
    EvaluationMode           -- CHARACTERIZED / COMPUTED / LOOKED_UP

    validate_program         -- run cross-model validators
    ValidationReport         -- result of validate_program
"""
from rulekit.contract.atoms import (
    AnyAtomSpec,
    BooleanAtom,
    NumericAtom,
)
from rulekit.contract.base import (
    AtomId,
    EvaluationMode,
    NodeId,
    NodeRef,
    Provenance,
)
from rulekit.contract.boolean import (
    AndNodeSpec,
    AtLeastNodeSpec,
    AtomRef,
    ComparisonSpec,
    NotNodeSpec,
    OrNodeSpec,
)
from rulekit.contract.cases import (
    CaseInput,
    CaseInputSchema,
    ExpectedOutcome,
    TestCase,
)
from rulekit.contract.map import MapSpec
from rulekit.contract.numeric import (
    BinaryArithmeticSpec,
    ConditionalNumericSpec,
    ConstantSpec,
    NamedQuantitySpec,
    NumericAtomRef,
    UnaryArithmeticSpec,
    VariadicArithmeticSpec,
)
from rulekit.contract.program import (
    BOOLEAN_NODE_KINDS,
    NUMERIC_NODE_KINDS,
    AnyNodeSpec,
    DeterminationProgram,
    DeterminationSpec,
    ProductionRecord,
    ProgramMetadata,
)
from rulekit.contract.validators import (
    ValidationReport,
    validate_program,
)
from rulekit.contract.convert import (
    EngineRuntime,
    ProgramValidationError,
    safe_program_to_engine,
)

__all__ = [
    # Top-level
    "DeterminationProgram",
    "ProgramMetadata",
    "ProductionRecord",
    "DeterminationSpec",
    # Map
    "MapSpec",
    "BooleanAtom",
    "NumericAtom",
    "AnyAtomSpec",
    # Boolean nodes
    "AtomRef",
    "AndNodeSpec",
    "OrNodeSpec",
    "NotNodeSpec",
    "AtLeastNodeSpec",
    "ComparisonSpec",
    # Numeric nodes
    "NumericAtomRef",
    "ConstantSpec",
    "UnaryArithmeticSpec",
    "BinaryArithmeticSpec",
    "VariadicArithmeticSpec",
    "ConditionalNumericSpec",
    "NamedQuantitySpec",
    # Unions and tag sets
    "AnyNodeSpec",
    "BOOLEAN_NODE_KINDS",
    "NUMERIC_NODE_KINDS",
    # Cases
    "CaseInputSchema",
    "CaseInput",
    "ExpectedOutcome",
    "TestCase",
    # Primitives
    "AtomId",
    "NodeId",
    "NodeRef",
    "Provenance",
    "EvaluationMode",
    # Validation
    "validate_program",
    "ValidationReport",
    "EngineRuntime",
    "ProgramValidationError",
    "safe_program_to_engine",
]
