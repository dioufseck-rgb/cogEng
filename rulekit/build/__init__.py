"""
RuleKit build pipeline.

The build pipeline turns policy text + declared determinations into a
DAG that the engine can evaluate against fact bundles.

Stages (Path 2: top-down decomposer, which is the surviving build path):

- ``extract.py`` — A1 atom extraction (formerly ``builder.py``). The
  Extract primitive at the policy level: takes policy text + reader
  voice, produces a list of atomic claims with stable IDs.

- ``decomposer.py`` — top-down DAG decomposition. Takes declared
  determinations (institution input, YAML) and recursively decomposes
  each against the policy text. Each LLM call asks: "is this claim
  atomic, or is it an operator with N children?"

- ``refinement.py`` — atom-level refinement pass that resolves
  ambiguities flagged during decomposition.

The institution declares the determinations. The decomposer builds
the trees. The deduplication pass at the end merges semantically
equivalent atoms across determinations, turning the tree into a DAG.
"""

from rulekit.build.extract import (
    ReaderVoice,
    A1Result,
    run_a1,
    check_atomicity,
    build_a1_prompt,
    parse_a1_response,
)

__all__ = [
    "ReaderVoice", "A1Result",
    "run_a1", "check_atomicity",
    "build_a1_prompt", "parse_a1_response",
]
