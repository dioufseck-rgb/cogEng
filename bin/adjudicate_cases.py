"""
adjudicate_cases.py — generic typed-Map adjudication runner.

Takes a built DAG pickle + RuleArena case file + model + batch_size, and
produces per-case adjudication output:

  - Each case run through Map (bind every atom from the case description)
  - Each determination evaluated against the resulting FactBundle
  - Per-case JSON audit with: per-atom Map binding, per-determination
    Kleene result, aggregate RuleKit disposition, ground truth, trace

USAGE:
    python bin/adjudicate_cases.py \
        --built built_nba.pkl \
        --cases RuleArena/nba/annotated_problems/comp_0.json \
        --case-ids comp_0_1_op_A,comp_0_6_op_A,comp_0_30_op_A \
        --aliases domains/nba/ruleArena_family_aliases.yaml \
        --model claude-sonnet-4-6 \
        --batch-size 1 \
        --out-dir audits/

DESIGN PRINCIPLES:
  - Generic library shape: no NBA-specific code, just config-driven
  - batch_size=1 by default to preserve the architecture's per-atom
    focus claim (see typed.py:18-21)
  - Per-case audit is the unit of accountability for the empirical claim
  - Aggregation rule:
      RuleKit disposition for a case is "illegal" if ANY relevant
      determination returned FALSE; "legal" if ALL returned TRUE;
      "uncertain" if any returned UNDETERMINED.
      Maps to RuleArena's binary is_illegal for comparison.
"""
from __future__ import annotations
import argparse
import json
import os
import pickle
import sys
from datetime import datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

import yaml
from rulekit.schema import Atom
from rulekit.engine import Kleene
from rulekit.map.typed import (
    TypedNarrativeLLMSubstrate, TypedAtom, AtomType,
    map_case_to_typed_bundle, NumericValue,
)
from rulekit.map.structured import (
    StructuredOutputSubstrate, map_case_to_typed_bundle_structured,
)
from rulekit.build.decomposer import LLMCaller
from rulekit.cases.rulearena_adapter import load_ruleArena_cases


def load_alias_table(path: str) -> dict[str, str]:
    """Load the RuleArena rule family → determination alias YAML."""
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data["ruleArena_family_to_determination"]


def case_determinations(case, aliases: dict[str, str]) -> set[str]:
    """Map a case's relevant_rules to the set of determinations to evaluate."""
    rules = case.ground_truth.get("relevant_rules", [])
    return {aliases[r] for r in rules if r in aliases}


def case_is_in_scope(case, aliases: dict[str, str]) -> bool:
    """A case is in scope if every relevant_rule has an alias entry."""
    rules = case.ground_truth.get("relevant_rules", [])
    return all(r in aliases for r in rules)


def build_typed_atoms_from_dag(atoms: dict[str, Atom]) -> dict[str, TypedAtom]:
    """Convert the Build's atom registry into a TypedAtom dict for Map."""
    typed = {}
    for aid, atom in atoms.items():
        atype = (AtomType.NUMERIC if atom.atom_type == "numeric"
                 else AtomType.BOOLEAN)
        typed[aid] = TypedAtom(atom=atom, atom_type=atype)
    return typed


def kleene_to_str(k: Kleene) -> str:
    """Stable string representation of a Kleene value for JSON output."""
    if k == Kleene.TRUE:
        return "TRUE"
    if k == Kleene.FALSE:
        return "FALSE"
    return "UNDETERMINED"


def numeric_value_to_dict(nv) -> dict:
    """Serialize a NumericValue or Kleene into JSON-safe dict."""
    if isinstance(nv, Kleene):
        return {"type": "kleene", "value": kleene_to_str(nv)}
    if isinstance(nv, NumericValue):
        if nv.is_undetermined:
            return {"type": "numeric", "value": "UNDETERMINED"}
        return {"type": "numeric", "value": str(nv.value)}
    return {"type": "unknown", "value": str(nv)}


def serialize_trace_entry(entry) -> dict:
    """Serialize one trace entry into JSON-safe dict.

    Engine trace entries are typically dicts already, but may contain
    Decimal or other non-serializable objects. We stringify aggressively.
    """
    if isinstance(entry, dict):
        return {k: _safe_str(v) for k, v in entry.items()}
    return {"raw": _safe_str(entry)}


def _safe_str(v):
    """JSON-safe representation of arbitrary values."""
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    if isinstance(v, list):
        return [_safe_str(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _safe_str(v2) for k, v2 in v.items()}
    return str(v)


def aggregate_disposition(per_det_results: dict[str, str]) -> str:
    """Aggregate per-determination Kleene results to a case-level disposition.

    Returns one of:
      'illegal'    — any determination returned FALSE
      'legal'      — all relevant determinations returned TRUE
      'uncertain'  — any determination returned UNDETERMINED (and none FALSE)
    """
    vals = list(per_det_results.values())
    if any(v == "FALSE" for v in vals):
        return "illegal"
    if any(v == "UNDETERMINED" for v in vals):
        return "uncertain"
    return "legal"


def adjudicate_case(case, build, aliases, substrate, typed_atoms) -> dict:
    """Adjudicate one case end-to-end. Returns a serializable audit dict.

    Steps:
      1. Identify which determinations are relevant via aliases
      2. Run Map to bind all atoms from the case description
      3. Evaluate each relevant determination against the FactBundle
      4. Aggregate to a case-level disposition
      5. Compare with ground truth
    """
    relevant_det_ids = case_determinations(case, aliases)

    # Run Map — bind ALL atoms (we could subset to only atoms referenced
    # by relevant determinations, but binding all keeps the Map call
    # uniform per case and produces a complete audit).
    # Substrate's bind_typed is the same interface for both per-atom and
    # structured-output substrates.
    bundle = substrate.bind_typed(case.description, typed_atoms)

    # Evaluate each determination
    per_det_results = {}
    per_det_traces = {}
    for det_id in sorted(relevant_det_ids):
        if det_id not in build.determinations:
            per_det_results[det_id] = "MISSING"
            continue
        det = build.determinations[det_id]
        # Determination.evaluate(bundle) returns (Kleene, trace_list)
        kleene, trace = det.evaluate(bundle)
        per_det_results[det_id] = kleene_to_str(kleene)
        per_det_traces[det_id] = [serialize_trace_entry(e) for e in (trace or [])]

    rulekit_disposition = aggregate_disposition(per_det_results)
    ground_truth_is_illegal = case.ground_truth["is_illegal"]
    rulekit_says_illegal = (rulekit_disposition == "illegal")
    agreement = (rulekit_says_illegal == ground_truth_is_illegal)

    # Serialize the FactBundle
    atom_bindings = {aid: numeric_value_to_dict(v)
                     for aid, v in bundle.values.items()}

    return {
        "case_id": case.case_id,
        "ground_truth": {
            "is_illegal": ground_truth_is_illegal,
            "relevant_rules": case.ground_truth.get("relevant_rules", []),
            "illegal_operation_letter": case.ground_truth.get(
                "illegal_operation_letter", ""),
        },
        "rulekit": {
            "disposition": rulekit_disposition,
            "says_illegal": rulekit_says_illegal,
            "relevant_determinations": sorted(relevant_det_ids),
            "per_determination_kleene": per_det_results,
        },
        "agreement_with_ground_truth": agreement,
        "atom_bindings": atom_bindings,
        "per_determination_traces": per_det_traces,
        "case_description": case.description,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Adjudicate RuleArena cases through a built DAG using typed Map."
    )
    parser.add_argument("--built", required=True,
                        help="Path to built DAG pickle (from build_dag.py)")
    parser.add_argument("--cases", required=True,
                        help="RuleArena case JSON file")
    parser.add_argument("--case-ids", default=None,
                        help="Comma-separated list of case_ids to adjudicate; "
                             "if omitted, all in-scope cases are run")
    parser.add_argument("--aliases", required=True,
                        help="RuleArena family → determination alias YAML")
    parser.add_argument("--model", default="claude-sonnet-4-6",
                        help="Model for Map (default: claude-sonnet-4-6)")
    parser.add_argument("--substrate", choices=["per-atom", "structured"],
                        default="structured",
                        help="Map substrate: 'per-atom' (one LLM call per atom; "
                             "slow but preserves architectural-purity claim) or "
                             "'structured' (one LLM call per case; production-"
                             "deployable). Default: structured.")
    parser.add_argument("--batch-size", type=int, default=1,
                        help="Per-atom substrate batch size (default: 1, ignored "
                             "for structured substrate)")
    parser.add_argument("--out-dir", default="audits",
                        help="Output directory for per-case audit JSON")
    args = parser.parse_args()

    # Load artifacts
    print(f"Loading built DAG from {args.built}")
    with open(args.built, "rb") as f:
        build = pickle.load(f)
    print(f"  {len(build.determinations)} determinations, "
          f"{len(build.atoms)} atoms")

    print(f"Loading alias table from {args.aliases}")
    aliases = load_alias_table(args.aliases)

    print(f"Loading cases from {args.cases}")
    all_cases = load_ruleArena_cases(args.cases, only_single_op=True)

    # Filter to requested case_ids or in-scope cases
    if args.case_ids:
        requested = set(args.case_ids.split(","))
        cases = [c for c in all_cases if c.case_id in requested]
        missing = requested - {c.case_id for c in cases}
        if missing:
            print(f"  WARNING: requested case_ids not found: {missing}")
    else:
        cases = [c for c in all_cases if case_is_in_scope(c, aliases)]
    print(f"  Adjudicating {len(cases)} cases")

    # Set up Map substrate
    print(f"Model: {args.model}")
    print(f"Substrate: {args.substrate}")
    if args.substrate == "per-atom":
        print(f"Batch size: {args.batch_size} "
              f"(one-per-atom)" if args.batch_size == 1 else "")
    print()

    llm = LLMCaller(model=args.model)
    if args.substrate == "structured":
        substrate = StructuredOutputSubstrate(llm=llm)
    else:
        substrate = TypedNarrativeLLMSubstrate(
            llm=llm,
            batch_size=args.batch_size if args.batch_size > 0 else None,
        )
    typed_atoms = build_typed_atoms_from_dag(build.atoms)

    # Run adjudication
    os.makedirs(args.out_dir, exist_ok=True)
    run_summary = {
        "run_id": datetime.now().strftime("%Y%m%d_%H%M%S"),
        "built": args.built,
        "model": args.model,
        "batch_size": args.batch_size,
        "case_count": len(cases),
        "results": [],
    }

    for i, case in enumerate(cases, 1):
        print(f"[{i}/{len(cases)}] {case.case_id} "
              f"(ground_truth: is_illegal={case.ground_truth['is_illegal']})")
        try:
            audit = adjudicate_case(case, build, aliases, substrate, typed_atoms)
        except Exception as e:
            print(f"  ERROR: {e}")
            audit = {
                "case_id": case.case_id,
                "error": str(e),
                "ground_truth": case.ground_truth,
            }

        # Write per-case audit
        audit_path = os.path.join(args.out_dir, f"case_{case.case_id}.json")
        with open(audit_path, "w", encoding="utf-8") as f:
            json.dump(audit, f, indent=2)

        # Print summary line
        if "error" in audit:
            print(f"  → ERROR")
        else:
            agree = "AGREE" if audit["agreement_with_ground_truth"] else "DISAGREE"
            disp = audit["rulekit"]["disposition"]
            print(f"  → RuleKit: {disp} ({agree})")
            per_det = audit["rulekit"]["per_determination_kleene"]
            for did, kl in per_det.items():
                print(f"     {did}: {kl}")

        run_summary["results"].append({
            "case_id": case.case_id,
            "agreement_with_ground_truth": audit.get(
                "agreement_with_ground_truth"),
            "rulekit_disposition": audit.get("rulekit", {}).get("disposition"),
            "ground_truth_is_illegal": case.ground_truth["is_illegal"],
        })

    # Run summary
    summary_path = os.path.join(args.out_dir, f"_summary_{run_summary['run_id']}.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(run_summary, f, indent=2)

    # Print aggregate
    print()
    print("=" * 70)
    print(f"RUN SUMMARY (saved to {summary_path})")
    print("=" * 70)
    agreements = sum(1 for r in run_summary["results"]
                     if r.get("agreement_with_ground_truth"))
    errors = sum(1 for r in run_summary["results"]
                 if r.get("agreement_with_ground_truth") is None)
    total = len(run_summary["results"])
    print(f"  Total cases: {total}")
    print(f"  Agreement with ground truth: {agreements}/{total - errors}")
    if errors:
        print(f"  Errored: {errors}")


if __name__ == "__main__":
    main()
