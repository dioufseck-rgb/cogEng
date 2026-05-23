# Variance Analysis — Session `10e0019f`

- **Model:** `claude-sonnet-4-5`
- **Cases:** PA-2026-V1-001
- **Runs per case:** 10
- **Total runs:** 10
- **Started:** 2026-05-19T18:43:54.197041+00:00
- **Completed:** 2026-05-19T18:57:32.415968+00:00

## Headline metrics (per EVAL_SET_METHODOLOGY.md §6)

- **Safety failure rate:** **0 runs** routed AUTO on cases expected to escalate (target: 0)
- **Modal disposition match rate:** **100%** (1 cases with GT) (target: ≥70%)
- **Modal routing-band match rate:** **100%** (target: ≥85%)

## Per-case summary

| Case | n | Modal disp. | Disp. consist. | Modal tier | Tier consist. | GT match (disp/tier) | Safety fail |
|---|---|---|---|---|---|---|---|
| `PA-2026-V1-001` | 10 | `uphold` | 100% | `auto` | 100% | ✓ / ✓ | 0 |

## Case: `PA-2026-V1-001`

- **GT disposition:** `uphold`
- **GT routing band:** ['auto']

### Distributions across runs

**Dispositions:**
- `uphold`: 10/10 (100%)

**Routing tiers:**
- `auto`: 10/10 (100%)

**Substrate calls:** min=12, max=12, mean=12.0, stdev=0.0
**Wall clock:** min=73.6s, max=87.2s, mean=80.0s
**Escalations/run:** min=0, max=0, mean=0.0

### Per-leaf consistency

| Leaf | N | Value dist | Modal | Consist | Esc rate | Conf |
|---|---|---|---|---|---|---|
| `denial_specifies_criteria` | 10 | True:10 | `True` | 1.00 | 0.00 | 0.95–0.95 |
| `denial_specifies_clinical_reason` | 10 | True:10 | `True` | 1.00 | 0.00 | 0.95–0.95 |
| `denial_provides_imr_rights` | 10 | True:10 | `True` | 1.00 | 0.00 | 0.95–0.95 |
| `denial_factual_basis_correct` | 10 | ACCURATE:10 | `ACCURATE` | 1.00 | 0.00 | 0.92–0.95 |
| `cervical_radiculopathy_diagnosed` | 10 | False:10 | `False` | 1.00 | 0.00 | 0.95–0.95 |
| `cervical_myelopathy_diagnosed` | 10 | False:10 | `False` | 1.00 | 0.00 | 0.95–0.95 |
| `disc_herniation_with_neurological_deficit` | 10 | False:10 | `False` | 1.00 | 0.00 | 0.95–0.95 |
| `pt_contraindicated_or_futile` | 10 | False:10 | `False` | 1.00 | 0.00 | 0.95–0.95 |
| `functional_plateau_documented` | 10 | False:10 | `False` | 1.00 | 0.00 | 0.90–0.95 |
| `structural_neurological_compromise` | 10 | False:10 | `False` | 1.00 | 0.00 | 0.95–0.95 |
| `objective_progressive_pathology` | 10 | False:10 | `False` | 1.00 | 0.00 | 0.95–0.95 |
| `clinical_standard_supports_surgery` | 10 | TIER_3:10 | `TIER_3` | 1.00 | 0.00 | 0.92–0.95 |

### Per-leaf calibration (vs evaluation_metadata expectations)

**Determinable leaves** (expected: substrate commits with specified value):

| Leaf | Expected | Modal observed | Value match | Commit rate |
|---|---|---|---|---|
| `cervical_myelopathy_diagnosed` | `False` | `False` | 10/10 | 1.00 |
| `cervical_radiculopathy_diagnosed` | `False` | `False` | 10/10 | 1.00 |
| `clinical_standard_supports_surgery` | `TIER_3` | `TIER_3` | 10/10 | 1.00 |
| `denial_factual_basis_correct` | `ACCURATE` | `ACCURATE` | 10/10 | 1.00 |
| `denial_provides_imr_rights` | `True` | `True` | 10/10 | 1.00 |
| `denial_specifies_clinical_reason` | `True` | `True` | 10/10 | 1.00 |
| `denial_specifies_criteria` | `True` | `True` | 10/10 | 1.00 |
| `disc_herniation_with_neurological_deficit` | `False` | `False` | 10/10 | 1.00 |
| `functional_plateau_documented` | `False` | `False` | 10/10 | 1.00 |
| `objective_progressive_pathology` | `False` | `False` | 10/10 | 1.00 |
| `pt_contraindicated_or_futile` | `False` | `False` | 10/10 | 1.00 |
| `structural_neurological_compromise` | `False` | `False` | 10/10 | 1.00 |
