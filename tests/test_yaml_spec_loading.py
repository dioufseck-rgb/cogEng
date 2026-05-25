"""
test_yaml_spec_loading.py -- unit tests for the generic YAML config schema.

The library claim is that an institution can author a config file declaring
its policy + voice + constants + determinations, with NO Python written by
the institution. This test verifies the YAML loader supports that:

  - Inline voice block (library-native path)
  - Constants block (institution declares named numeric values)
  - Legacy voice_key path (backward compat with PA/FCBA YAMLs)
  - Decimal coercion for constants (no float-binary errors)
  - Error cases (missing required fields, both voice paths set)

No LLM calls. Run: python tests/test_yaml_spec_loading.py
"""
from __future__ import annotations
import os
import sys
import tempfile
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rulekit.build.decomposer import (
    load_spec_from_yaml, BuildSpec, DeterminationDeclaration,
)
from rulekit.build.extract import ReaderVoice


# ---------------------------------------------------------------------------
# Test infrastructure: simple PASS/FAIL printer
# ---------------------------------------------------------------------------

_results = {"passed": 0, "failed": 0}

def check(label: str, condition: bool, detail: str = ""):
    if condition:
        _results["passed"] += 1
        print(f"  PASS  {label}")
    else:
        _results["failed"] += 1
        print(f"  FAIL  {label}" + (f"  ({detail})" if detail else ""))


def section(title: str):
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def write_temp_yaml(content: str) -> str:
    """Write YAML content to a temp file and return its path."""
    fd, path = tempfile.mkstemp(suffix=".yaml")
    with os.fdopen(fd, "w") as f:
        f.write(content)
    return path


# ---------------------------------------------------------------------------
# Test 1: Inline voice block (library-native path)
# ---------------------------------------------------------------------------

section("Test 1: Inline voice block")

yaml_inline = """
policy:
  name: "Generic test policy"
  source: "/dev/null"
  abbreviation: "tst"

voice:
  role: "experienced test reader"
  domain: "test domain"
  background: |
    Multi-line background
    spanning several lines.

determinations:
  - id: "tst.D1"
    description: "Is the test condition satisfied?"
    polarity: "positive"
    source_span: "Section 1"
    composition: "derived"
"""

path = write_temp_yaml(yaml_inline)
try:
    spec = load_spec_from_yaml(path)
    check("voice is set", spec.voice is not None)
    check("voice_key is None when inline voice used", spec.voice_key is None)
    check("voice.role correct", spec.voice.role == "experienced test reader")
    check("voice.domain correct", spec.voice.domain == "test domain")
    check("voice.background is multi-line",
          "Multi-line background" in spec.voice.background and
          "spanning several lines." in spec.voice.background)
    check("constants default to empty dict", spec.constants == {})
    check("one determination loaded", len(spec.determinations) == 1)
    check("determination id correct", spec.determinations[0].id == "tst.D1")
finally:
    os.unlink(path)


# ---------------------------------------------------------------------------
# Test 2: Constants block -- Decimal coercion across input types
# ---------------------------------------------------------------------------

section("Test 2: Constants block, Decimal coercion")

yaml_constants = """
policy:
  name: "Constants test"
  source: "/dev/null"
  abbreviation: "tst"

voice:
  role: "tester"
  domain: "test"
  background: "test"

constants:
  integer_value: 140588000
  float_value: 0.0912
  string_with_dollars: "$178,132,000"
  string_plain: "188931000"

determinations:
  - id: "tst.D1"
    description: "test"
"""

path = write_temp_yaml(yaml_constants)
try:
    spec = load_spec_from_yaml(path)
    check("integer coerced to Decimal",
          spec.constants["integer_value"] == Decimal("140588000"))
    check("float coerced to Decimal preserving precision",
          spec.constants["float_value"] == Decimal("0.0912"),
          detail=f"got {spec.constants['float_value']!r}")
    check("string with $ and commas stripped and coerced",
          spec.constants["string_with_dollars"] == Decimal("178132000"))
    check("plain string coerced",
          spec.constants["string_plain"] == Decimal("188931000"))
    check("all constants are Decimal instances",
          all(isinstance(v, Decimal) for v in spec.constants.values()))
finally:
    os.unlink(path)


# ---------------------------------------------------------------------------
# Test 3: Legacy voice_key path with registry (backward compat for PA/FCBA)
# ---------------------------------------------------------------------------

section("Test 3: Legacy voice_key + registry resolution")

yaml_legacy = """
policy:
  name: "Legacy test"
  source: "/dev/null"
  abbreviation: "lt"
  voice: "test_voice"

determinations:
  - id: "lt.D1"
    description: "test"
"""

# Build a tiny registry as a domain integrator would
def _test_voice() -> ReaderVoice:
    return ReaderVoice(
        role="registry-resolved reader",
        domain="test",
        background="test",
    )

test_registry = {"test_voice": _test_voice}

path = write_temp_yaml(yaml_legacy)
try:
    # WITHOUT registry: voice_key kept, voice is None
    spec_no_reg = load_spec_from_yaml(path)
    check("legacy without registry: voice_key preserved",
          spec_no_reg.voice_key == "test_voice")
    check("legacy without registry: voice is None",
          spec_no_reg.voice is None)

    # WITH registry: voice resolved, voice_key cleared
    spec_with_reg = load_spec_from_yaml(path, voices_registry=test_registry)
    check("legacy with registry: voice resolved",
          spec_with_reg.voice is not None and
          spec_with_reg.voice.role == "registry-resolved reader")
    check("legacy with registry: voice_key cleared",
          spec_with_reg.voice_key is None)
finally:
    os.unlink(path)


# ---------------------------------------------------------------------------
# Test 4: Inline voice takes precedence over registry voice_key (if both)
# ---------------------------------------------------------------------------

section("Test 4: Inline voice takes precedence over registry")

yaml_both = """
policy:
  name: "Both voice paths"
  source: "/dev/null"
  abbreviation: "bp"
  voice: "test_voice"

voice:
  role: "inline reader"
  domain: "test"
  background: "test"

determinations:
  - id: "bp.D1"
    description: "test"
"""

path = write_temp_yaml(yaml_both)
try:
    spec = load_spec_from_yaml(path, voices_registry=test_registry)
    check("inline voice wins over registry key",
          spec.voice.role == "inline reader",
          detail=f"got {spec.voice.role!r}")
finally:
    os.unlink(path)


# ---------------------------------------------------------------------------
# Test 5: Error case -- neither voice nor voice_key set
# ---------------------------------------------------------------------------

section("Test 5: Error when no voice provided")

yaml_no_voice = """
policy:
  name: "No voice"
  source: "/dev/null"
  abbreviation: "nv"

determinations:
  - id: "nv.D1"
    description: "test"
"""

path = write_temp_yaml(yaml_no_voice)
try:
    raised = False
    try:
        spec = load_spec_from_yaml(path)
    except ValueError as e:
        raised = True
        check("error message mentions voice",
              "voice" in str(e).lower(),
              detail=f"got: {e}")
    check("ValueError raised when no voice", raised)
finally:
    os.unlink(path)


# ---------------------------------------------------------------------------
# Test 6: scope_hint flows through to DeterminationDeclaration
# ---------------------------------------------------------------------------

section("Test 6: scope_hint passes through")

yaml_scope = """
policy:
  name: "Scope test"
  source: "/dev/null"
  abbreviation: "sc"

voice:
  role: "test reader"
  domain: "test"
  background: "test"

determinations:
  - id: "sc.D1"
    description: "Is X satisfied?"
    polarity: "positive"
    composition: "derived"
    scope_hint: "Focus on aspects A and B. Express as OR over branches."
"""

path = write_temp_yaml(yaml_scope)
try:
    spec = load_spec_from_yaml(path)
    det = spec.determinations[0]
    check("scope_hint loaded into determination",
          det.scope_hint == "Focus on aspects A and B. Express as OR over branches.")
finally:
    os.unlink(path)


# ---------------------------------------------------------------------------
# Test 7: Real legacy YAML (PA determinations.yaml) still loads
# ---------------------------------------------------------------------------

section("Test 7: Existing PA YAML backward compat")

pa_path = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "domains", "pa", "determinations.yaml"
)
if os.path.exists(pa_path):
    # Without registry -- voice_key preserved
    spec_no_reg = load_spec_from_yaml(pa_path)
    check("PA legacy: voice_key='pa' preserved",
          spec_no_reg.voice_key == "pa")
    check("PA legacy: two determinations loaded",
          len(spec_no_reg.determinations) == 2)

    # With the actual PA registry -- voice resolved
    from domains.voices import VOICES
    spec_resolved = load_spec_from_yaml(pa_path, voices_registry=VOICES)
    check("PA legacy with registry: voice resolved to pa_reviewer",
          spec_resolved.voice is not None and
          "medical director" in spec_resolved.voice.role)
else:
    print(f"  SKIP  PA YAML not present at {pa_path}")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print("\n" + "=" * 70)
print(f"RESULTS: {_results['passed']} passed, {_results['failed']} failed")
print("=" * 70)

if _results["failed"] > 0:
    sys.exit(1)
