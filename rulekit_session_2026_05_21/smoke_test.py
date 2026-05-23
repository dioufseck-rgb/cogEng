"""Smoke test — verifies the rulekit package imports and evaluates correctly."""

from rulekit import (
    Kleene, CardinalityNode, NotNode, Leaf,
    FactBundle, Determination, Provenance,
    at_least_n, invert,
)


def test_kleene_basics():
    """Verify Kleene truth tables."""
    assert invert(Kleene.TRUE) == Kleene.FALSE
    assert invert(Kleene.FALSE) == Kleene.TRUE
    assert invert(Kleene.UNDETERMINED) == Kleene.UNDETERMINED
    print("OK — Kleene NOT")


def test_cardinality_at_least_n():
    """Verify cardinality semantics across AND/OR/AT-LEAST-N."""
    T, F, U = Kleene.TRUE, Kleene.FALSE, Kleene.UNDETERMINED

    # AND (N = k)
    assert at_least_n([T, T, T], 3) == T
    assert at_least_n([T, F, T], 3) == F
    assert at_least_n([T, U, T], 3) == U

    # OR (N = 1)
    assert at_least_n([F, F, T], 1) == T
    assert at_least_n([F, F, F], 1) == F
    assert at_least_n([F, U, F], 1) == U

    # AT-LEAST-2 over 4
    assert at_least_n([T, T, F, F], 2) == T
    assert at_least_n([T, F, F, F], 2) == F   # only 1 true, 0 undet — can't reach 2
    assert at_least_n([T, U, F, F], 2) == U   # 1 true, 1 undet — could reach 2
    print("OK — Cardinality AT-LEAST-N (AND/OR/AT-LEAST-2 cases)")


def test_simple_tree_evaluation():
    """Build a tiny tree and verify evaluation."""
    leaf_a = Leaf(atom_id="a")
    leaf_b = Leaf(atom_id="b")
    leaf_c = Leaf(atom_id="c")
    and_node = CardinalityNode(
        n=3, children=[leaf_a, leaf_b, leaf_c],
        surface_label="ALL", provenance=Provenance.TRANSCRIBED,
    )
    not_node = NotNode(child=and_node, provenance=Provenance.INFERRED)

    bundle_all_true = FactBundle(values={"a": Kleene.TRUE, "b": Kleene.TRUE, "c": Kleene.TRUE})
    assert and_node.evaluate(bundle_all_true) == Kleene.TRUE
    assert not_node.evaluate(bundle_all_true) == Kleene.FALSE

    bundle_one_undet = FactBundle(values={"a": Kleene.TRUE, "b": Kleene.UNDETERMINED, "c": Kleene.TRUE})
    assert and_node.evaluate(bundle_one_undet) == Kleene.UNDETERMINED
    assert not_node.evaluate(bundle_one_undet) == Kleene.UNDETERMINED

    bundle_one_false = FactBundle(values={"a": Kleene.TRUE, "b": Kleene.FALSE, "c": Kleene.TRUE})
    assert and_node.evaluate(bundle_one_false) == Kleene.FALSE
    assert not_node.evaluate(bundle_one_false) == Kleene.TRUE
    print("OK — Tree evaluation (AND, NOT) under Kleene")


def test_de_morgan_for_cardinality():
    """Verify that NOT AT-LEAST-N over k children equals AT-LEAST-(k-N+1) over negated children."""
    T, F, U = Kleene.TRUE, Kleene.FALSE, Kleene.UNDETERMINED

    for values in [
        [T, T, F, F], [T, F, F, F], [T, U, F, F],
        [T, T, T, T], [F, F, F, F], [U, U, U, U],
        [T, U, U, F],
    ]:
        for n in [1, 2, 3, 4]:
            direct = invert(at_least_n(values, n))
            k = len(values)
            negated_values = [invert(v) for v in values]
            de_morgan = at_least_n(negated_values, k - n + 1)
            assert direct == de_morgan, f"De Morgan failure: NOT AT-LEAST-{n} of {values} = {direct} vs {de_morgan}"
    print("OK — De Morgan generalization for cardinality")


if __name__ == "__main__":
    test_kleene_basics()
    test_cardinality_at_least_n()
    test_simple_tree_evaluation()
    test_de_morgan_for_cardinality()
    print("\nAll smoke tests passed.")
