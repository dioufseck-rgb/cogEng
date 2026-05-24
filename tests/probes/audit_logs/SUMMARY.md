# Architectural Probe Summary

Total runtime: 228.5 seconds
Probes run: 4

## probe_1_conditional_arithmetic

  - Elapsed: 15.9s
  - LLM calls: 3
  - Decomposition: OK
  - Stage-4 conversion: OK
  - Spec inventory: `{'ComparisonSpec': 1, 'NumericLeafSpec': 1, 'DerivedAtomSpec': 1, '_max_depth': 1}`
  - Atoms registered: 2

## probe_2_reclassification

  - Elapsed: 71.4s
  - LLM calls: 26
  - Decomposition: OK
  - Stage-4 conversion: FAILED
    - Error: `ValueError: Leaf has no atom_id (run deduplicate_leaves first): The Team has not already used the Mid-Level Salary Exception for Room Teams in the same Salary Cap Year as required by Section 6(f)(2).`
  - Spec inventory: `{'LeafSpec': 6, 'OperatorSpec': 5, 'ComparisonSpec': 5, 'NumericLeafSpec': 3, 'ConstantSpec': 5, 'DerivedAtomSpec': 2, '_max_depth': 4}`
  - Atoms registered: 3

## probe_3_table_gating

  - Elapsed: 93.5s
  - LLM calls: 35
  - Decomposition: OK
  - Stage-4 conversion: FAILED
    - Error: `ValueError: Leaf has no atom_id (run deduplicate_leaves first): The transaction is a Team signing or acquiring a player using the Bi-annual Exception (Row A).`
  - Spec inventory: `{'LeafSpec': 17, 'OperatorSpec': 9, 'ComparisonSpec': 3, 'NumericLeafSpec': 3, 'ConstantSpec': 2, 'DerivedAtomSpec': 1, '_max_depth': 6}`
  - Atoms registered: 0

## probe_4_cross_domain_finra

  - Elapsed: 47.6s
  - LLM calls: 20
  - Decomposition: OK
  - Stage-4 conversion: OK
  - Spec inventory: `{'OperatorSpec': 5, 'ComparisonSpec': 5, 'NumericLeafSpec': 6, 'ConstantSpec': 4, 'UnaryArithmeticSpec': 1, '_max_depth': 5}`
  - Atoms registered: 4

---

## Reading guide

Each probe writes a full audit log at `tests/probes/audit_logs/{probe_name}_audit.json` containing every prompt sent and every response received.

For each probe, the diagnostic questions are printed at the end of its run output. Review the spec tree and atoms-registered output against those questions to determine whether the construct is expressible in the current architecture.

Update `docs/STATE_OF_RULEKIT.md` §6 (Architectural Unknowns) with the findings — converting each unknown into a 'Probed Unknown' with named evidence.