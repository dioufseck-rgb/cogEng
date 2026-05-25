"""
test_build_state_dir.py -- exercises the streaming/resume mechanism
in build_from_spec.

Uses a mock LLM that records call counts so we can verify:
  - Initial Build with state_dir writes per-determination pickles
  - Re-running Build with same state_dir skips already-decomposed
    determinations (LLM call count drops accordingly)
"""
from __future__ import annotations
import os
import pickle
import shutil
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

from decimal import Decimal
from rulekit.build.decomposer import (
    BuildSpec, DeterminationDeclaration, build_from_spec, LeafSpec,
)
from rulekit.build.extract import ReaderVoice


passed = 0
failed = 0


def check(condition, label):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS  {label}")
    else:
        failed += 1
        print(f"  FAIL  {label}")


# Mock LLM that returns context-appropriate JSON based on what's being called.
# - Decompose calls get a leaf JSON
# - Dedup calls (used in finalize) get an empty mapping
class MockLLM:
    def __init__(self):
        self.call_count = 0
        self.decompose_call_count = 0
        self.dedup_call_count = 0

    def call(self, prompt, *args, **kwargs):
        self.call_count += 1
        prompt_str = str(prompt) if prompt else ""
        # Dedup prompts (Boolean and numeric) contain "atom" and "mapping"
        # somewhere in them. Return empty mapping.
        prompt_lower = prompt_str.lower()
        if "mapping" in prompt_lower or "dedup" in prompt_lower or "consolidat" in prompt_lower:
            self.dedup_call_count += 1
            return "{}"
        # Otherwise it's a decompose call
        self.decompose_call_count += 1
        return '{"type": "leaf", "claim": "test claim", "source_span": "test span"}'

    def __call__(self, *args, **kwargs):
        return self.call(*args, **kwargs)


def make_spec_with_two_determinations(tmp_dir):
    """Build a minimal BuildSpec with 2 determinations and a tiny policy file."""
    policy_path = os.path.join(tmp_dir, "policy.txt")
    with open(policy_path, "w") as f:
        f.write("Test policy text.\nRule A: foo.\nRule B: bar.\n")

    voice = ReaderVoice(
        role="test reader",
        domain="test domain",
        background="test background",
    )

    spec = BuildSpec(
        policy_name="Test Policy",
        policy_source=policy_path,
        abbreviation="test",
        voice=voice,
        constants={"some_constant": Decimal("100")},
        determinations=[
            DeterminationDeclaration(
                id="test.det_one",
                description="Is rule A satisfied?",
                polarity="positive",
                source_span="Rule A",
                composition="derived",
            ),
            DeterminationDeclaration(
                id="test.det_two",
                description="Is rule B satisfied?",
                polarity="positive",
                source_span="Rule B",
                composition="derived",
            ),
        ],
    )
    return spec


print("=" * 70)
print("Test 1: state_dir writes per-determination pickles")
print("=" * 70)

with tempfile.TemporaryDirectory() as tmp_dir:
    spec = make_spec_with_two_determinations(tmp_dir)
    state_dir = os.path.join(tmp_dir, "state")
    llm = MockLLM()

    result = build_from_spec(
        spec, llm=llm, refine=False, state_dir=state_dir
    )

    check(os.path.isdir(state_dir), "state_dir created")
    saved_files = sorted(os.listdir(state_dir))
    check(
        "decompose_test.det_one.pkl" in saved_files,
        "decompose_test.det_one.pkl saved",
    )
    check(
        "decompose_test.det_two.pkl" in saved_files,
        "decompose_test.det_two.pkl saved",
    )

    # Inspect saved pickle
    with open(os.path.join(state_dir, "decompose_test.det_one.pkl"), "rb") as f:
        saved = pickle.load(f)
    check("spec" in saved, "saved pickle has 'spec' key")
    check("audit" in saved, "saved pickle has 'audit' key")
    check(saved["spec"] is not None, "saved spec is not None")

    initial_call_count = llm.decompose_call_count
    print(f"  (Initial decompose used {initial_call_count} LLM calls)")
    check(initial_call_count >= 2, "at least 2 decompose calls for 2 determinations")


print()
print("=" * 70)
print("Test 2: re-running with same state_dir skips already-decomposed")
print("=" * 70)

with tempfile.TemporaryDirectory() as tmp_dir:
    spec = make_spec_with_two_determinations(tmp_dir)
    state_dir = os.path.join(tmp_dir, "state")

    # First run -- populates state_dir
    llm1 = MockLLM()
    result1 = build_from_spec(
        spec, llm=llm1, refine=False, state_dir=state_dir
    )
    first_run_decompose_calls = llm1.decompose_call_count
    print(f"  (First run: {first_run_decompose_calls} decompose calls)")

    # Second run with same state_dir -- should reuse saves, do 0 decompose calls
    llm2 = MockLLM()
    result2 = build_from_spec(
        spec, llm=llm2, refine=False, state_dir=state_dir
    )
    second_run_decompose_calls = llm2.decompose_call_count
    print(f"  (Second run: {second_run_decompose_calls} decompose calls -- should be 0)")

    check(
        second_run_decompose_calls == 0,
        "second run does zero decompose calls (all loaded from disk)",
    )
    check(
        second_run_decompose_calls < first_run_decompose_calls,
        "second run is cheaper than first (decompose skipped)",
    )

    # Both runs should produce the same determinations
    check(
        set(result1.determinations.keys()) == set(result2.determinations.keys()),
        "same determinations produced in both runs",
    )


print()
print("=" * 70)
print("Test 3: partial state_dir (only one det saved) triggers partial resume")
print("=" * 70)

with tempfile.TemporaryDirectory() as tmp_dir:
    spec = make_spec_with_two_determinations(tmp_dir)
    state_dir = os.path.join(tmp_dir, "state")

    # First run
    llm1 = MockLLM()
    build_from_spec(spec, llm=llm1, refine=False, state_dir=state_dir)

    # Delete only one save to simulate a crash mid-Build
    os.remove(os.path.join(state_dir, "decompose_test.det_two.pkl"))

    # Re-run -- should only decompose det_two
    llm2 = MockLLM()
    result = build_from_spec(
        spec, llm=llm2, refine=False, state_dir=state_dir
    )

    # det_two needed decompose calls; det_one was loaded from disk
    # We can't easily count "decompose calls just for det_two" but
    # we can check the result is complete
    check(
        "test.det_one" in result.determinations,
        "det_one (from disk) present in result",
    )
    check(
        "test.det_two" in result.determinations,
        "det_two (re-decomposed) present in result",
    )


print()
print("=" * 70)
print("Test 4: state_dir=None preserves backward compatibility")
print("=" * 70)

with tempfile.TemporaryDirectory() as tmp_dir:
    spec = make_spec_with_two_determinations(tmp_dir)
    llm = MockLLM()
    result = build_from_spec(spec, llm=llm, refine=False, state_dir=None)
    check(
        len(result.determinations) == 2,
        "build_from_spec(state_dir=None) still produces both determinations",
    )
    check(llm.call_count >= 2, "LLM was called normally")


print()
print("=" * 70)
print(f"RESULTS: {passed} passed, {failed} failed")
print("=" * 70)
sys.exit(0 if failed == 0 else 1)
