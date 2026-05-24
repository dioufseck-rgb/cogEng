"""
probe_harness.py — common harness for architectural probe experiments.

Each probe is a single bare-question determination over a self-contained
policy passage. The harness runs the production decompose pipeline once,
captures the full LLM audit log (prompts + responses), attempts Stage-4
conversion, evaluates against a synthetic case if requested, and prints a
structured diagnostic.


The four probes test:
  1. Conditional arithmetic (Article II §7 max salary by YOS)
  2. Rule reclassification (§6(f) including (f)(5) deemed-use rule)
  3. Table-driven gating (§2(e) Transaction Restrictions Table)
  4. Cross-domain (FINRA Rule 4210 PDT minimum equity)

Each probe is bounded — one decompose_claim call at the top level, recursive
sub-calls below. Cost is ~$10-15 per probe at Opus 4.7.

USAGE (from a probe script):
    from probe_harness import run_probe, save_audit
    run_probe(
        probe_name="probe_1_conditional_arithmetic",
        policy_text=...,
        determination=...,
        voice=...,
        constants={...},               # optional; for Stage-4 conversion
        synthetic_cases=[...],         # optional; for evaluation
    )
"""
from __future__ import annotations
import json
import os
import sys
import time
import traceback
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Optional

# Make rulekit importable from this directory.
HERE = os.path.dirname(os.path.abspath(__file__))
TESTS_DIR = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(TESTS_DIR)
sys.path.insert(0, REPO_ROOT)

from rulekit.build.decomposer import (
    DeterminationDeclaration, DecomposeState, LLMCaller,
    LeafSpec, OperatorSpec, ComparisonSpec,
    NumericLeafSpec, ConstantSpec, UnaryArithmeticSpec, DerivedAtomSpec,
    decompose_claim, spec_to_engine_node, finalize_spec,
)
from rulekit.build.extract import ReaderVoice
from rulekit.engine import FactBundle, Kleene
from rulekit.engine.typed import NumericValue


# ---------------------------------------------------------------------------
# Logging wrapper around LLMCaller — captures every prompt + response
# ---------------------------------------------------------------------------

class LoggingLLMCaller:
    """Wraps LLMCaller and records every (stage, prompt, response) triple."""

    def __init__(self, inner: LLMCaller):
        self.inner = inner
        self.calls: list[dict] = []
        self.model = inner.model
        self.offline_responses = inner.offline_responses

    def call(self, stage_name: str, prompt: str) -> str:
        start = time.time()
        try:
            response = self.inner.call(stage_name, prompt)
            ok = True
            error = None
        except Exception as e:
            response = ""
            ok = False
            error = f"{type(e).__name__}: {e}"
            raise
        finally:
            elapsed = time.time() - start
            self.calls.append({
                "stage": stage_name,
                "prompt": prompt,
                "response": response,
                "elapsed_seconds": round(elapsed, 2),
                "ok": ok,
                "error": error,
            })
        return response


# ---------------------------------------------------------------------------
# Pretty-printers (lifted from earlier integration tests)
# ---------------------------------------------------------------------------

def describe_spec(spec, indent=0):
    pad = "  " * indent
    if isinstance(spec, LeafSpec):
        return f"{pad}LeafSpec[{spec.source_span or '?'}]: {spec.claim[:90]}"
    if isinstance(spec, OperatorSpec):
        lines = [f"{pad}{spec.operator.upper()}({len(spec.children)}) [{spec.surface_label or '?'}]"]
        for c in spec.children:
            lines.append(describe_spec(c, indent + 1))
        return "\n".join(lines)
    if isinstance(spec, ComparisonSpec):
        lines = [
            f"{pad}COMPARISON({spec.operator}) [{spec.surface_label or '?'}]",
            f"{pad}  LHS '{spec.lhs_description}' [hint={spec.lhs_kind}]:",
            describe_numeric(spec.lhs_spec, indent + 2),
            f"{pad}  RHS '{spec.rhs_description}' [hint={spec.rhs_kind}]:",
            describe_numeric(spec.rhs_spec, indent + 2),
        ]
        return "\n".join(lines)
    return f"{pad}<{type(spec).__name__}>"


def describe_numeric(spec, indent=0):
    pad = "  " * indent
    if spec is None:
        return f"{pad}<None>"
    if isinstance(spec, NumericLeafSpec):
        return (f"{pad}NumericLeafSpec(atom_id_hint={spec.atom_id_hint!r}, "
                f"atom_id={spec.atom_id!r})")
    if isinstance(spec, ConstantSpec):
        if spec.value is not None:
            return f"{pad}ConstantSpec(value={spec.value})"
        return f"{pad}ConstantSpec(label={spec.label!r})"
    if isinstance(spec, UnaryArithmeticSpec):
        const_repr = (f"constant={spec.constant}" if spec.constant is not None
                      else f"constant_label={spec.constant_label!r}")
        return (
            f"{pad}UnaryArithmeticSpec({spec.operator}, {const_repr}):\n"
            + describe_numeric(spec.child, indent + 1)
        )
    if isinstance(spec, DerivedAtomSpec):
        return (f"{pad}DerivedAtomSpec(atom_id_hint={spec.atom_id_hint!r}, "
                f"atom_id={spec.atom_id!r}, "
                f"computation_kind={spec.computation_kind!r})")
    return f"{pad}<{type(spec).__name__}>"


def describe_engine_node(n, indent=0):
    pad = "  " * indent
    t = type(n).__name__
    if hasattr(n, "atom_id"):
        return f"{pad}{t}({n.atom_id!r})"
    if hasattr(n, "value") and hasattr(n, "label") and not hasattr(n, "children"):
        return f"{pad}{t}(value={n.value}, label={n.label!r})"
    if hasattr(n, "left") and hasattr(n, "right"):
        return (f"{pad}{t}\n"
                + describe_engine_node(n.left, indent + 1) + "\n"
                + describe_engine_node(n.right, indent + 1))
    if hasattr(n, "constant") and hasattr(n, "child"):
        return (f"{pad}{t}(constant={n.constant})\n"
                + describe_engine_node(n.child, indent + 1))
    if hasattr(n, "child"):
        return f"{pad}{t}\n" + describe_engine_node(n.child, indent + 1)
    if hasattr(n, "children"):
        n_kw = f" n={n.n}" if hasattr(n, "n") and getattr(n, "n", None) is not None else ""
        lines = [f"{pad}{t}({len(n.children)} children{n_kw})"]
        for c in n.children:
            lines.append(describe_engine_node(c, indent + 1))
        return "\n".join(lines)
    return f"{pad}{t} <?>"


def inventory_spec(spec, counts=None):
    if counts is None:
        counts = {
            "LeafSpec": 0, "OperatorSpec": 0, "ComparisonSpec": 0,
            "NumericLeafSpec": 0, "ConstantSpec": 0,
            "UnaryArithmeticSpec": 0, "DerivedAtomSpec": 0,
            "_max_depth": 0,
        }

    def walk(node, depth):
        counts["_max_depth"] = max(counts["_max_depth"], depth)
        if isinstance(node, LeafSpec):
            counts["LeafSpec"] += 1
        elif isinstance(node, OperatorSpec):
            counts["OperatorSpec"] += 1
            for c in node.children:
                walk(c, depth + 1)
        elif isinstance(node, ComparisonSpec):
            counts["ComparisonSpec"] += 1
            _walk_numeric(node.lhs_spec, depth + 1, counts)
            _walk_numeric(node.rhs_spec, depth + 1, counts)

    walk(spec, 0)
    return counts


def _walk_numeric(node, depth, counts):
    if node is None:
        return
    counts["_max_depth"] = max(counts["_max_depth"], depth)
    t = type(node).__name__
    if t in counts:
        counts[t] += 1
    if isinstance(node, UnaryArithmeticSpec):
        _walk_numeric(node.child, depth + 1, counts)


# ---------------------------------------------------------------------------
# Probe runner
# ---------------------------------------------------------------------------

@dataclass
class ProbeResult:
    """Structured result of a probe run."""
    probe_name: str
    decompose_ok: bool
    spec_tree: Optional[Any]
    inventory: Optional[dict]
    llm_call_count: int
    audit_log: list[dict]
    stage4_ok: bool
    engine_node: Optional[Any]
    stage4_error: Optional[str]
    atoms_registered: Optional[dict]
    case_results: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def run_probe(
    probe_name: str,
    policy_text: str,
    determination: DeterminationDeclaration,
    voice: ReaderVoice,
    constants: Optional[dict[str, Decimal]] = None,
    synthetic_cases: Optional[list[tuple[str, dict[str, Any]]]] = None,
    audit_dir: Optional[str] = None,
    model: str = "claude-opus-4-7",
) -> ProbeResult:
    """
    Run one probe. Returns ProbeResult and writes a JSON audit log to
    audit_dir if provided.
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        if os.environ.get("CLAUDE_API_KEY"):
            os.environ["ANTHROPIC_API_KEY"] = os.environ["CLAUDE_API_KEY"]
        else:
            print("ERROR: set ANTHROPIC_API_KEY (or CLAUDE_API_KEY)")
            sys.exit(2)

    print("=" * 75)
    print(f"PROBE: {probe_name}")
    print("=" * 75)
    print(f"\nDetermination: {determination.id}")
    print(f"  Source: {determination.source_span}")
    print(f"  Question: {determination.description}")
    if determination.scope_hint:
        print(f"  Scope hint: {determination.scope_hint[:120]}...")
    print(f"\nPolicy text: {len(policy_text)} chars")
    print(f"Constants registry: {list((constants or {}).keys())}")
    print(f"Synthetic cases: {len(synthetic_cases or [])}")

    inner_llm = LLMCaller(model=model)
    llm = LoggingLLMCaller(inner_llm)
    state = DecomposeState(
        llm=llm,
        policy_text=policy_text,
        voice=voice,
        determination=determination,
    )

    # ----- Stage 1+2: decompose -----
    print("\n" + "-" * 75)
    print("STAGE 1+2: decompose")
    print("-" * 75)

    decompose_ok = True
    spec_tree = None
    try:
        spec_tree = decompose_claim(
            claim=determination.description,
            path=[determination.id],
            depth=0,
            state=state,
        )
        print(f"\n  LLM calls used: {state.call_count}")
        print(f"  Spec tree:")
        print(describe_spec(spec_tree, indent=2))

        inventory = inventory_spec(spec_tree)
        print(f"\n  Spec inventory: {dict((k, v) for k, v in inventory.items() if v > 0)}")
    except Exception as e:
        decompose_ok = False
        inventory = None
        print(f"\n  DECOMPOSITION FAILED: {type(e).__name__}: {e}")
        traceback.print_exc()

    # ----- Stage 3: finalize (Boolean + numeric atom dedup) -----
    finalize_ok = False
    if decompose_ok:
        print("\n" + "-" * 75)
        print("STAGE 3: finalize (Boolean + numeric atom dedup)")
        print("-" * 75)
        try:
            # Derive abbreviation from the determination ID's leading segment
            # (e.g. 'probe1.max_salary' -> 'probe1')
            abbreviation = determination.id.split(".")[0]
            finalize_audit = finalize_spec(
                {determination.id: spec_tree},
                llm,
                abbreviation=abbreviation,
            )
            finalize_ok = True
            n_boolean = len(finalize_audit.get("boolean_dedup", {}))
            n_numeric = len(finalize_audit.get("numeric_dedup", {}))
            print(f"  OK. Boolean atoms processed: {n_boolean}; "
                  f"numeric atoms processed: {n_numeric}")
        except Exception as e:
            print(f"\n  FINALIZE FAILED: {type(e).__name__}: {e}")
            traceback.print_exc()

    # ----- Stage 4: convert to engine DAG -----
    print("\n" + "-" * 75)
    print("STAGE 4: convert to engine DAG")
    print("-" * 75)

    stage4_ok = False
    engine_node = None
    stage4_error = None
    atoms: dict = {}
    if decompose_ok and finalize_ok:
        try:
            engine_node = spec_to_engine_node(spec_tree, atoms, constants or {})
            stage4_ok = True
            print(f"\n  OK. Engine DAG:")
            print(describe_engine_node(engine_node, indent=2))
            print(f"\n  Atoms registered: {len(atoms)}")
            for aid, atom in atoms.items():
                print(f"    {aid} (type={atom.atom_type}): {atom.statement[:80]}")
        except Exception as e:
            stage4_error = f"{type(e).__name__}: {e}"
            print(f"\n  CONVERSION FAILED: {stage4_error}")
    elif not decompose_ok:
        print("\n  Skipped (decomposition failed)")
    else:
        print("\n  Skipped (finalize failed)")

    # ----- Optional synthetic-case evaluation -----
    case_results: list[dict] = []
    if synthetic_cases and stage4_ok:
        print("\n" + "-" * 75)
        print("EVALUATION: synthetic cases")
        print("-" * 75)
        for label, values in synthetic_cases:
            try:
                bundle = FactBundle(values=values)
                result = engine_node.evaluate(bundle)
                print(f"\n  CASE: {label}")
                print(f"    Result: {result}")
                case_results.append({
                    "label": label,
                    "values": {k: str(v) for k, v in values.items()},
                    "result": str(result),
                    "ok": True,
                })
            except Exception as e:
                print(f"\n  CASE: {label}")
                print(f"    ERROR: {type(e).__name__}: {e}")
                case_results.append({
                    "label": label,
                    "values": {k: str(v) for k, v in values.items()},
                    "result": None,
                    "ok": False,
                    "error": f"{type(e).__name__}: {e}",
                })

    # ----- Summary -----
    print("\n" + "=" * 75)
    print("SUMMARY")
    print("=" * 75)
    print(f"  Decomposition: {'OK' if decompose_ok else 'FAILED'}")
    print(f"  Stage-4 conversion: {'OK' if stage4_ok else 'FAILED' if decompose_ok else 'SKIPPED'}")
    print(f"  LLM calls: {state.call_count}")
    if case_results:
        ok_count = sum(1 for c in case_results if c["ok"])
        print(f"  Cases evaluated: {ok_count}/{len(case_results)} ran without error")

    result = ProbeResult(
        probe_name=probe_name,
        decompose_ok=decompose_ok,
        spec_tree=spec_tree,
        inventory=inventory if decompose_ok else None,
        llm_call_count=state.call_count,
        audit_log=llm.calls,
        stage4_ok=stage4_ok,
        engine_node=engine_node,
        stage4_error=stage4_error,
        atoms_registered={aid: {"type": atom.atom_type, "statement": atom.statement}
                          for aid, atom in atoms.items()},
        case_results=case_results,
    )

    # ----- Write audit log to disk -----
    if audit_dir:
        os.makedirs(audit_dir, exist_ok=True)
        audit_path = os.path.join(audit_dir, f"{probe_name}_audit.json")
        with open(audit_path, "w") as f:
            json.dump({
                "probe_name": probe_name,
                "model": model,
                "determination": {
                    "id": determination.id,
                    "description": determination.description,
                    "source_span": determination.source_span,
                    "scope_hint": determination.scope_hint,
                },
                "policy_text_length": len(policy_text),
                "policy_text": policy_text,
                "constants_registry": [k for k in (constants or {})],
                "decompose_ok": decompose_ok,
                "stage4_ok": stage4_ok,
                "stage4_error": stage4_error,
                "llm_call_count": state.call_count,
                "calls": llm.calls,
                "inventory": result.inventory,
                "atoms_registered": result.atoms_registered,
                "case_results": case_results,
            }, f, indent=2, default=str)
        print(f"\n  Audit written to: {audit_path}")

    return result
