"""
Build-side spec — the institution's declarative input to the LLM-driven
build pipeline.

A BuildSpec describes what the build process needs to receive in order
to produce a determination program: policy metadata, the reader voice
that shapes how the LLM reads the policy, named numeric constants, and
the list of declared determinations.

These types are deliberately separate from the contract module. The
contract (rulekit/contract/) is what producers EMIT — a domain-agnostic
DeterminationProgram. BuildSpec is what the LLM-driven build CONSUMES —
domain-specific inputs (policy text path, reader voice, abbreviation).
Other producers (hand authors, translators, future UI editors) may
consume entirely different inputs and emit the same contract.

This module was extracted from decomposer.py in Phase 2 of the contract
migration. decomposer.py re-exports BuildSpec, DeterminationDeclaration,
and load_spec_from_yaml for backward compatibility with existing
consumers.

Contents:

    DeterminationDeclaration
        Per-determination declaration. The institution names what
        determinations the build must produce and gives the LLM a
        starting point (description, polarity, optional scope hint).
        composition="derived" means the LLM composes the tree;
        composition="complement" means the determination is structurally
        NOT(linked_to).

    BuildSpec
        The full institutional input. Carries policy metadata,
        reader voice, named numeric constants, and the determinations.
        The voice may be inline (a ReaderVoice instance) or a registry
        key — exactly one must be set.

    load_spec_from_yaml(path, voices_registry=None) -> BuildSpec
        YAML loader. Constants are coerced to Decimal via
        to_decimal_constant. Voice block (preferred) or policy.voice
        registry key (legacy) is resolved.

Stability
=========

These types are stable for the migration window. They will eventually be
revisited when the build pipeline itself emits contract programs
(Phase 4), but BuildSpec will likely survive that work because it
represents inputs that have no contract analog — policy text isn't part
of a DeterminationProgram, but the build needs to read it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

from rulekit.build.extract import ReaderVoice
from rulekit.build.llm import to_decimal_constant


# ---------------------------------------------------------------------------
# Determination declaration
# ---------------------------------------------------------------------------

@dataclass
class DeterminationDeclaration:
    """Institution-declared determination — what the build must produce.

    Mirrors what the contract layer calls a DeterminationSpec (in
    rulekit/contract/program.py), but stays a plain dataclass on the
    build side because it's an *input* to the build process, not part
    of the contract's serializable surface.

    `id` is the determination's identifier (e.g., "fcba.D1"). `description`
    is the institution's prose name. `polarity` indicates whether the
    determination is approve/positive ("the request is approved"),
    deny/negative ("the request is denied"), or neutral.
    `composition="derived"` is the common case — the build LLM composes
    the tree. `composition="complement"` says this determination is the
    structural NOT of `linked_to` — common for approve/deny pairs where
    only one of the two requires its own tree.

    `scope_hint` is an optional natural-language hint that the build
    threads into LLM prompts to focus decomposition.
    """
    id: str
    description: str
    polarity: str = "neutral"
    linked_to: Optional[str] = None
    source_span: str = ""
    composition: str = "derived"
    scope_hint: Optional[str] = None


# ---------------------------------------------------------------------------
# Build spec
# ---------------------------------------------------------------------------

@dataclass
class BuildSpec:
    """Full institutional spec for a build.

    The spec is the institution's declarative input. It carries everything
    a domain-agnostic library needs to produce a runnable adjudicator from
    policy text:

      - policy metadata (name, source path, short abbreviation)
      - the reader voice (role/domain/background) — either inline as a
        ``voice`` field, or as a ``voice_key`` referencing a registered
        named voice (legacy/example use)
      - named numeric constants used by the policy (e.g. salary cap,
        threshold values), as a dict from snake_case label to Decimal
      - the list of declared determinations the build must produce

    The library is policy-domain-agnostic — NBA, FINRA, FCBA, PA, tax,
    insurance, healthcare adjudication all express the same shape here.
    """
    policy_name: str
    policy_source: str
    abbreviation: str
    determinations: list[DeterminationDeclaration]
    # Voice: either inline (preferred for library use) or registry key
    # (legacy). Exactly one of `voice` and `voice_key` must be set.
    voice: Optional[ReaderVoice] = None
    voice_key: Optional[str] = None
    # Named numeric constants (e.g., {"salary_cap": Decimal("140588000")}).
    # Threaded into Stage-4 engine conversion so ConstantSpec(label=...) and
    # UnaryArithmeticSpec(constant_label=...) resolve to real values.
    constants: dict[str, Decimal] = field(default_factory=dict)

    def __post_init__(self):
        if self.voice is None and self.voice_key is None:
            raise ValueError(
                f"BuildSpec requires either a `voice` (inline ReaderVoice) "
                f"or a `voice_key` (registered name). Got neither for "
                f"policy {self.policy_name!r}."
            )
        if self.voice is not None and self.voice_key is not None:
            raise ValueError(
                f"BuildSpec requires exactly one of `voice` or `voice_key`, "
                f"not both. Got both for policy {self.policy_name!r}."
            )


# ---------------------------------------------------------------------------
# YAML loader
# ---------------------------------------------------------------------------

def load_spec_from_yaml(
    path: str,
    voices_registry: Optional[dict] = None,
) -> BuildSpec:
    """Load a YAML build spec from a path.

    The YAML may declare the voice in either of two ways:

      1. INLINE (preferred, domain-agnostic):
         voice:
           role: "experienced adjudicator at ..."
           domain: "..."
           background: |
             Multi-line background...

      2. REGISTRY LOOKUP (legacy / built-in examples):
         policy:
           voice: "pa"        # key into voices_registry

    Constants may be declared inline:
         constants:
           some_named_value: 140588000

    Values are coerced to Decimal at load time via to_decimal_constant so
    the engine's arithmetic is precision-preserving (avoiding float
    binary-representation errors).

    Backward-compat: existing PA/FCBA YAMLs that use ``policy.voice``
    as a registry key continue to work as long as ``voices_registry``
    is passed (typically ``domains.voices.VOICES``). If both inline
    ``voice`` block and ``policy.voice`` key are present, the inline
    block takes precedence.

    Uses PyYAML; install via `pip install pyyaml`.
    """
    import yaml

    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    # Voice resolution: inline block beats legacy registry key
    voice: Optional[ReaderVoice] = None
    voice_key: Optional[str] = None
    if "voice" in data:
        # Inline voice block — preferred path
        v = data["voice"]
        voice = ReaderVoice(
            role=v["role"],
            domain=v["domain"],
            background=v["background"],
        )
    elif "voice" in data.get("policy", {}):
        # Legacy: policy.voice is a registry key
        voice_key = data["policy"]["voice"]
        if voices_registry is not None and voice_key in voices_registry:
            voice = voices_registry[voice_key]()
            voice_key = None  # consumed
        # If no registry passed in, BuildSpec stores voice_key and the
        # caller is responsible for resolution.

    # Constants block: optional, coerced to Decimal via to_decimal_constant
    # which handles int/float/str including currency-formatted strings.
    constants: dict[str, Decimal] = {}
    for label, value in (data.get("constants") or {}).items():
        if not isinstance(value, (int, float, str)):
            raise ValueError(
                f"Constants value for {label!r} must be int/float/str, "
                f"got {type(value).__name__}: {value!r}"
            )
        constants[label] = to_decimal_constant(value, label_for_error=label)

    return BuildSpec(
        policy_name=data["policy"]["name"],
        policy_source=data["policy"]["source"],
        abbreviation=data["policy"]["abbreviation"],
        voice=voice,
        voice_key=voice_key,
        constants=constants,
        determinations=[
            DeterminationDeclaration(**d) for d in data["determinations"]
        ],
    )


__all__ = [
    "DeterminationDeclaration",
    "BuildSpec",
    "load_spec_from_yaml",
]
