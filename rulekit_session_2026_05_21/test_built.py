"""
test_built.py — self-binding test harness for built trees.

Walks each determination's tree to identify its actual leaves, then evaluates
test cases against those leaves directly. No need to know atom IDs in advance
or maintain test cases that match a particular build.

A test case is a function from atom-to-statement → truth value. The harness
inspects each atom's statement and decides what value to assign based on the
case's semantic intent. This way cases are portable across different builds
of the same policy.
"""

import sys
import os
import pickle

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from rulekit import Kleene, FactBundle, format_trace, Leaf, AndNode, OrNode, AtLeastNode, NotNode


T, F, U = Kleene.TRUE, Kleene.FALSE, Kleene.UNDETERMINED


# ---------------------------------------------------------------------------
# Leaf identification — walk the tree, collect every Leaf node's atom_id
# ---------------------------------------------------------------------------

def collect_leaves(node, leaves=None):
    """Recursively collect all leaf atom_ids in a tree."""
    if leaves is None:
        leaves = set()
    if isinstance(node, Leaf):
        leaves.add(node.atom_id)
    elif isinstance(node, NotNode):
        collect_leaves(node.child, leaves)
    elif isinstance(node, (AndNode, OrNode, AtLeastNode)):
        for child in node.children:
            collect_leaves(child, leaves)
    return leaves


# ---------------------------------------------------------------------------
# Case definition by semantic predicate
# ---------------------------------------------------------------------------

class Case:
    """
    A case is a name + a function (atom_id, statement) -> Kleene.
    The harness applies the function to every leaf in the tree to produce
    a fact bundle. The function is the case's semantic specification.
    """
    def __init__(self, name, expected, decide_fn):
        self.name = name
        self.expected = expected   # Kleene value expected
        self.decide_fn = decide_fn  # (atom_id, statement) -> Kleene


def has_any(statement_lower, words):
    return any(w in statement_lower for w in words)


# ---------------------------------------------------------------------------
# PA cases — defined semantically, not by atom ID
# ---------------------------------------------------------------------------

def pa_case_standard_approval(atom_id, statement):
    """
    Radiculopathy patient with full standard conservative treatment.
    Expected: TRUE for an approval determination.
    """
    s = statement.lower()
    aid = atom_id.lower()

    # Diagnosis: radiculopathy is the diagnosis. Myelopathy and disc herniation are absent.
    if "radiculopathy" in s and "myelopathy" not in s:
        return T
    if "radicular" in s and "dermatomal" in s:
        return T
    if "nerve root compression" in s:
        return T
    if "radicular" in s and has_any(s, ["pain", "numbness", "weakness"]):
        return T
    if "myelopathy" in s or "myelopathic" in s:
        return F
    if "cord compression" in s:
        return F
    if "disc herniation" in s:
        return F
    if "hoffman" in s or "hyperreflexia" in s or "gait" in s:
        return F
    if "bowel" in s or "bladder" in s:
        return F
    if "bilateral" in s and "weakness" in s:
        return F

    # Imaging: MRI present, structural pathology demonstrated
    if "mri" in s and "6 months" in s:
        return T
    if "ct myelogram" in s:
        return F
    if "structural pathology" in s:
        return T
    if "imaging" in s and "interpreted" in s and "radiologist" in s:
        return T
    if "imaging" in s and "interpreted" in s and "specialist" in s:
        return F
    if "surgical level" in s:
        return T

    # PT: completed standard 6-week course with all qualifiers
    if ("6 weeks" in s or "six weeks" in s) and "physical therapy" in s:
        return T
    if "physical therapy" in s and "supervised" in s:
        return T
    if ("functional outcomes" in s and "physical therapy" in s) or \
       ("physical therapy" in s and "documented" in s and "functional" in s):
        return T
    if "physical therapy" in s and ("directed" in s or "cervical condition" in s):
        return T

    # Exception path: not active
    if "exception" in s or ("4 weeks" in s and "physical therapy" in s) or \
       ("primary diagnosis" in s and "myelopathy" in s):
        return F
    if "interventional treatment" in s and ("waived" in s or "risk" in s):
        return F

    # Pharma: NSAIDs and neuropathic agents, 4 weeks each — at least 2 classes
    if "nsaid" in s:
        return T
    if "neuropathic" in s and ("trial" in s or "trialed" in s):
        return T
    if "muscle relaxant" in s:
        return F
    if "corticosteroid" in s:
        return F
    if "at least two" in s and "pharmacotherapy" in s:
        return T
    if "pharmacotherapy" in s and "duration" in s:
        return T
    # Pharmacotherapy category-definitions (real-LLM build had these)
    if "qualifies as a pharmacotherapy" in s or "qualify as a pharmacotherapy" in s:
        return T

    # Interventional: ESI received
    if "epidural steroid injection" in s or "esi" in aid:
        return T
    if "medial branch block" in s:
        return F
    if "trigger point" in s:
        return F

    # Documentation: all four provided
    if "attestation" in s and "conservative" in s:
        return T
    if "clinical rationale" in s:
        return T
    if "functional limitations" in s and "physician" in s:
        return T
    if "surgical risks" in s:
        return T
    if "surgical alternatives" in s or "alternatives considered" in s:
        return T

    # Unknown → UNDETERMINED (would surface a missing case-rule)
    return U


def pa_case_myelopathy_exception(atom_id, statement):
    """
    Primary myelopathy with 4-week PT and waived interventional treatment.
    Expected: TRUE for an approval determination.
    """
    s = statement.lower()
    aid = atom_id.lower()

    # Diagnosis: myelopathy is the diagnosis, primary diagnosis.
    if "radiculopathy" in s and "myelopathy" not in s:
        return F
    if "radicular" in s and "dermatomal" in s:
        return F
    if "nerve root compression" in s:
        return F
    if "radicular" in s and has_any(s, ["pain", "numbness", "weakness"]):
        return F
    if "myelopathy" in s and "primary" in s:
        return T
    if "myelopathy" in s and "exception" not in s:
        return T
    if "myelopathic" in s:
        return T
    if "cord compression" in s:
        return T
    if "gait" in s:
        return T
    if "bilateral" in s and "weakness" in s:
        return T
    if "hyperreflexia" in s:
        return T
    if "hoffman" in s:
        return T
    if "bowel" in s or "bladder" in s:
        return F
    if "disc herniation" in s:
        return F
    if "neurological deficit" in s and "objective" in s:
        return F

    # Imaging: MRI demonstrates structural pathology
    if "mri" in s:
        return T
    if "ct myelogram" in s:
        return F
    if "structural pathology" in s:
        return T
    if "surgical level" in s:
        return T
    if "imaging" in s and "interpreted" in s and "radiologist" in s:
        return T
    if "imaging" in s and "interpreted" in s and "specialist" in s:
        return F

    # Standard PT: not completed (only 4 weeks per exception)
    if ("6 weeks" in s or "six weeks" in s) and "physical therapy" in s:
        return F

    # Exception PT (4 weeks) + qualifiers
    if "4 weeks" in s and "physical therapy" in s:
        return T
    if "physical therapy" in s and "supervised" in s:
        return T
    if "physical therapy" in s and ("functional outcomes" in s or "documented" in s):
        return T
    if "physical therapy" in s and ("directed" in s or "cervical condition" in s):
        return T
    if "exception" in s and "physical therapy" in s and "reduced" in s:
        return T

    # Exception pharma: same as standard
    if "exception" in s and "pharmacotherapy" in s and "remains" in s:
        return T
    if "nsaid" in s:
        return T
    if "neuropathic" in s and ("trial" in s or "trialed" in s):
        return T
    if "muscle relaxant" in s:
        return F
    if "corticosteroid" in s:
        return F
    if "at least two" in s and "pharmacotherapy" in s:
        return T
    if "pharmacotherapy" in s and "duration" in s:
        return T
    if "qualifies as a pharmacotherapy" in s or "qualify as a pharmacotherapy" in s:
        return T

    # Interventional: WAIVED by physician documentation
    if "epidural steroid injection" in s or "esi" in aid:
        return F
    if "medial branch block" in s:
        return F
    if "trigger point" in s:
        return F
    if ("waived" in s or "neurological deterioration" in s) and "interventional" in s:
        return T
    if "interv_waived" in aid:
        return T

    # Documentation: complete
    if "attestation" in s and "conservative" in s:
        return T
    if "clinical rationale" in s:
        return T
    if "functional limitations" in s and "physician" in s:
        return T
    if "surgical risks" in s:
        return T
    if "surgical alternatives" in s or "alternatives considered" in s:
        return T

    return U


def pa_case_insufficient_evidence(atom_id, statement):
    """
    Radiculopathy patient but some atoms have partial documentation.
    Expected: UNDETERMINED for an approval determination.
    """
    s = statement.lower()

    # Mostly start from the standard approval case, then knock a few atoms to U.
    # Symptoms specifically — undocumented.
    if "radicular" in s and has_any(s, ["pain", "numbness", "weakness"]):
        return U
    # Functional outcomes — incomplete documentation.
    if "physical therapy" in s and ("functional outcomes" in s or ("documented" in s and "functional" in s)):
        return U
    # Pharma neuropathic — possibly trialed, unclear.
    if "neuropathic" in s and ("trial" in s or "trialed" in s):
        return U
    # Muscle relaxant trial — unclear.
    if "muscle relaxant" in s:
        return U
    # Physician's functional limitations description — informal, not documented per requirement.
    if "functional limitations" in s and "physician" in s:
        return U

    # Everything else: same as standard approval.
    return pa_case_standard_approval(atom_id, statement)


def pa_case_denial(atom_id, statement):
    """
    No qualifying diagnosis, no imaging pathology demonstrated.
    Expected: FALSE for D1 (approval), TRUE for D2 (denial).
    """
    s = statement.lower()

    # No diagnosis matches.
    if "radiculopathy" in s or "radicular" in s:
        return F
    if "nerve root compression" in s:
        return F
    if "myelopathy" in s or "myelopathic" in s:
        return F
    if "cord compression" in s:
        return F
    if "gait" in s or "hyperreflexia" in s or "hoffman" in s:
        return F
    if "bowel" in s or "bladder" in s:
        return F
    if "bilateral" in s and "weakness" in s:
        return F
    if "disc herniation" in s:
        return F
    if "neurological deficit" in s and "objective" in s:
        return F

    # No imaging pathology.
    if "structural pathology" in s:
        return F
    if "surgical level" in s:
        return F
    if "imaging" in s and "interpreted" in s and "specialist" in s:
        return F

    # MRI exists but interpretation/pathology fails above.
    if "mri" in s:
        return T
    if "ct myelogram" in s:
        return F
    if "imaging" in s and "interpreted" in s and "radiologist" in s:
        return T

    # PT done but moot.
    if ("6 weeks" in s or "six weeks" in s) and "physical therapy" in s:
        return T
    if "physical therapy" in s and ("supervised" in s or "directed" in s or "documented" in s or "functional outcomes" in s):
        return T
    if "physical therapy" in s and "cervical condition" in s:
        return T

    if "4 weeks" in s and "physical therapy" in s:
        return F

    # Exception inactive.
    if "exception" in s:
        return F
    if "interventional" in s and ("waived" in s or "neurological deterioration" in s):
        return F

    # Pharma trial done, but moot.
    if "nsaid" in s:
        return T
    if "muscle relaxant" in s:
        return T
    if "neuropathic" in s and ("trial" in s or "trialed" in s):
        return F
    if "corticosteroid" in s:
        return F
    if "at least two" in s and "pharmacotherapy" in s:
        return T
    if "pharmacotherapy" in s and "duration" in s:
        return T
    if "qualifies as a pharmacotherapy" in s or "qualify as a pharmacotherapy" in s:
        return T

    # No interventional.
    if "epidural" in s or "medial branch" in s or "trigger point" in s:
        return F

    # Documentation complete.
    if "attestation" in s or "rationale" in s or "functional limitations" in s:
        return T
    if "surgical risks" in s or "surgical alternatives" in s or "alternatives considered" in s:
        return T

    return U


# ---------------------------------------------------------------------------
# FCBA cases — defined semantically
# ---------------------------------------------------------------------------

def fcba_case_unauthorized(atom_id, statement):
    """
    A charge appeared on the statement; the consumer didn't make it and
    no one with authority made it. Expected: TRUE.
    """
    s = statement.lower()

    # (a)(1) — extension exists, not made to consumer, not made to authorized person.
    if "extension of credit" in s and ("1026.13(a)(1)" in atom_id or "a1" in atom_id):
        return T
    if "not made to the consumer" in s:
        return T
    if "not made to a person" in s and ("authority" in s or "authorized" in s):
        return T

    # (a)(2) — extension exists but other category not triggered.
    if "1026.7" in s or "1026.8" in s or "section 1026.7" in s or "section 1026.8" in s:
        return F
    if "not identified" in s and "1026" in s:
        return F

    # (a)(3) — property/services issue not triggered.
    if "property" in s or "services" in s or "delivered" in s or "accepted" in s:
        return F

    # (a)(4)-(a)(7) — none triggered.
    if "failure to credit" in s or "credit properly" in s:
        return F
    if "computational" in s:
        return F
    if "clarification" in s or "documentary evidence" in s:
        return F
    if "failure to mail" in s or "failed to mail" in s or "failed to deliver a periodic statement" in s or "failure to deliver a periodic statement" in s:
        return F

    # Standalone "extension of credit" for other (a)(N) — set TRUE since the
    # transaction did appear on the statement.
    if "extension of credit" in s and "reflection" in s:
        return T

    return U


def fcba_case_undelivered(atom_id, statement):
    """
    Subscription service charged but not delivered as agreed. (a)(3).
    Expected: TRUE.
    """
    s = statement.lower()

    # (a)(1) — extension exists but was authorized.
    if "not made to the consumer" in s:
        return F
    if "not made to a person" in s and ("authority" in s or "authorized" in s):
        return F

    # (a)(2) — properly identified.
    if "1026.7" in s or "1026.8" in s or "not identified" in s:
        return F

    # (a)(3) — services not delivered as agreed.
    if "property" in s and "services" not in s and "extension" in s:
        return F
    if "services" in s and "extension" in s and "credit for" in s:
        return T
    if "extension" in s and "for property" in s and "services" not in s:
        return F
    if "not delivered" in s and ("as agreed" in s or "designee" in s):
        return T
    if "not accepted" in s and ("consumer" in s or "designee" in s):
        return F

    # Other categories not triggered.
    if "failure to credit" in s:
        return F
    if "computational" in s:
        return F
    if "clarification" in s or "documentary evidence" in s:
        return F
    if "failure to mail" in s or "failed to mail" in s or "failed to deliver a periodic statement" in s or "failure to deliver a periodic statement" in s:
        return F

    # General "extension of credit" appearing in statement → TRUE.
    if "extension of credit" in s and "reflection" in s:
        return T

    return U


def fcba_case_valid_charge(atom_id, statement):
    """
    Authorized, properly identified, valid charge. Customer requests
    clarification but no billing error exists. Expected: FALSE.
    """
    s = statement.lower()

    # Charge exists, was authorized, properly identified.
    if "not made to the consumer" in s:
        return F
    if "not made to a person" in s and ("authority" in s or "authorized" in s):
        return F
    if "not identified" in s and "1026" in s:
        return F

    # No property/services issue.
    if "not delivered" in s or "not accepted" in s:
        return F

    # No payment failure, no computational error.
    if "failure to credit" in s:
        return F
    if "computational" in s:
        return F

    # Consumer requested clarification but only that — not a billing error category alone.
    if "clarification" in s or "documentary evidence" in s:
        return F
    # The (a)(6) requirement is extension AND clarification request — clarification absent
    # makes the (a)(6) category false.

    # Statement was delivered.
    if ("failure to mail" in s or "failed to mail" in s or
        "failure to deliver a periodic statement" in s or
        "failed to deliver a periodic statement" in s):
        return F

    # The transaction did appear on the statement.
    if "extension of credit" in s and "reflection" in s:
        return T

    return U


def fcba_case_undetermined(atom_id, statement):
    """
    Alleged unauthorized charge, but authorized users haven't all been checked.
    The "not made to authorized person" atom is UNDETERMINED. (a)(1) becomes
    undetermined; everything else firmly FALSE. Expected: UNDETERMINED.
    """
    s = statement.lower()

    if "not made to the consumer" in s:
        return T
    if "not made to a person" in s and ("authority" in s or "authorized" in s):
        return U

    if "1026.7" in s or "1026.8" in s or "not identified" in s:
        return F
    if "not delivered" in s or "not accepted" in s:
        return F
    if "failure to credit" in s:
        return F
    if "computational" in s:
        return F
    if "clarification" in s or "documentary evidence" in s:
        return F
    if "failure to mail" in s or "failed to mail" in s or "failed to deliver a periodic statement" in s or "failure to deliver a periodic statement" in s:
        return F

    if "extension of credit" in s and "reflection" in s:
        return T

    return U


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------

def bind_case_to_tree(case, tree_leaves, atoms):
    """
    Given a Case and the leaf atom IDs of a tree, produce a fact bundle by
    applying the case's decide_fn to each leaf.
    """
    values = {}
    for atom_id in tree_leaves:
        if atom_id in atoms:
            statement = atoms[atom_id].statement
        else:
            statement = ""
        values[atom_id] = case.decide_fn(atom_id, statement)
    return FactBundle(values=values)


def run_case(case, det, atoms, show_trace_on_fail=True):
    leaves = collect_leaves(det.tree)
    bundle = bind_case_to_tree(case, leaves, atoms)
    result, trace = det.evaluate(bundle)
    matches = (result == case.expected)
    marker = "PASS" if matches else "FAIL"
    print(f"  [{marker}] {case.name}: expected={case.expected}, got={result}")
    if not matches and show_trace_on_fail:
        print()
        print(format_trace(trace))
        # Also show which leaves got which values
        print("\n  Bundle:")
        for aid in sorted(leaves):
            stmt_preview = atoms[aid].statement[:60] if aid in atoms else "?"
            print(f"    {aid} = {bundle.values[aid]}  ({stmt_preview}...)")
    return matches


def main():
    if len(sys.argv) < 2:
        print("Usage: python test_built.py BUILT_PKL [BUILT_PKL ...]")
        sys.exit(1)

    total = 0
    passed = 0

    for pkl_path in sys.argv[1:]:
        with open(pkl_path, "rb") as f:
            result = pickle.load(f)

        print(f"\n{'=' * 72}")
        print(f"BUILT: {pkl_path}")
        print(f"  {len(result.atoms)} atoms, {len(result.determinations)} determinations")
        print('=' * 72)

        # Heuristic: PA or FCBA based on atom prefix
        is_pa = any("pa." in aid for aid in result.atoms)
        is_fcba = any("fcba." in aid for aid in result.atoms)

        if is_pa and "pa.D1" in result.determinations:
            d1 = result.determinations["pa.D1"]
            d2 = result.determinations.get("pa.D2")

            cases_d1 = [
                Case("Standard approval (radiculopathy + full conservative tx)", T, pa_case_standard_approval),
                Case("Myelopathy exception (4-wk PT + waived interventional)", T, pa_case_myelopathy_exception),
                Case("Insufficient evidence (partial documentation)", U, pa_case_insufficient_evidence),
                Case("Denial (no qualifying diagnosis or pathology)", F, pa_case_denial),
            ]
            for case in cases_d1:
                total += 1
                if run_case(case, d1, result.atoms):
                    passed += 1
            # D2 — the denial case
            if d2:
                total += 1
                d2_denial_case = Case("Denial via D2 (same case as denial above)", T, pa_case_denial)
                if run_case(d2_denial_case, d2, result.atoms):
                    passed += 1

        if is_fcba and "fcba.D1" in result.determinations:
            d1 = result.determinations["fcba.D1"]
            d2 = result.determinations.get("fcba.D2")

            cases_d1 = [
                Case("Unauthorized charge (a)(1)", T, fcba_case_unauthorized),
                Case("Undelivered services (a)(3)", T, fcba_case_undelivered),
                Case("Valid authorized charge — not a billing error", F, fcba_case_valid_charge),
                Case("Undetermined (partial evidence on unauthorized)", U, fcba_case_undetermined),
            ]
            for case in cases_d1:
                total += 1
                if run_case(case, d1, result.atoms):
                    passed += 1
            if d2:
                total += 1
                d2_valid_case = Case("Valid charge via D2 (not a billing error → D2 true)", T, fcba_case_valid_charge)
                if run_case(d2_valid_case, d2, result.atoms):
                    passed += 1

    print(f"\n{'=' * 72}")
    print(f"SUMMARY: {passed}/{total} cases produced expected outcomes")
    print('=' * 72)


if __name__ == "__main__":
    main()
