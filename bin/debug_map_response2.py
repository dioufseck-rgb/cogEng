"""
debug_map_response2.py — replicate Map's first failing call exactly.

Loads the built DAG, sets up the typed substrate, picks one Boolean atom,
runs the EXACT prompt Map would send, and prints what comes back.
"""
import os, sys, pickle, traceback
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

from rulekit.build.decomposer import LLMCaller, _parse_json_response
from rulekit.map.typed import (
    TypedNarrativeLLMSubstrate, TypedAtom, AtomType, BIND_PROMPT, NUMERIC_BIND_PROMPT,
)

# Load actual case description
from rulekit.cases.rulearena_adapter import load_ruleArena_cases
cases = load_ruleArena_cases("RuleArena/nba/annotated_problems/comp_0.json", only_single_op=True)
case = next(c for c in cases if c.case_id == "comp_0_1_op_A")

# Load actual built DAG
with open("built_nba.pkl", "rb") as f:
    build = pickle.load(f)

# Pick one Boolean atom
bool_atoms = [(aid, a) for aid, a in build.atoms.items() if a.atom_type == "boolean"]
print(f"Total Boolean atoms in build: {len(bool_atoms)}")
print(f"First atom: {bool_atoms[0][0]}: {bool_atoms[0][1].statement[:80]}")
print()

# Build the EXACT prompt Map would send for this one atom
atom_listing = f"  {bool_atoms[0][0]}: {bool_atoms[0][1].statement}"
prompt = BIND_PROMPT.format(
    description=case.description,
    atom_listing=atom_listing,
)

print("=" * 70)
print("THE EXACT PROMPT MAP WOULD SEND")
print("=" * 70)
print(prompt[:1500])
print("...")
print(f"(total prompt length: {len(prompt)} chars)")
print()

print("=" * 70)
print("RAW RESPONSE FROM API")
print("=" * 70)
llm = LLMCaller(model="claude-sonnet-4-6")
try:
    raw = llm.call("test", prompt)
    print(f"Type: {type(raw).__name__}")
    print(f"Length: {len(raw) if raw else 0}")
    print(f"Repr (first 1000 chars):")
    print(repr(raw[:1000]) if raw else "(empty)")
    print()
    print("As displayed:")
    print(raw[:1000] if raw else "(empty)")
    print()
    
    # Try to parse
    print("=" * 70)
    print("PARSE ATTEMPT")
    print("=" * 70)
    parsed = _parse_json_response(raw)
    print(f"Parsed OK: {parsed}")
except Exception as e:
    print(f"PARSE FAILED: {type(e).__name__}: {e}")
    traceback.print_exc()
