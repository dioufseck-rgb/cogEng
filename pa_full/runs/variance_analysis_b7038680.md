# Variance Analysis — Session `b7038680`

- **Model:** `claude-sonnet-4-5`
- **Cases:** kamau
- **Runs per case:** 10
- **Total runs:** 10
- **Started:** 2026-05-19T19:44:19.175848+00:00
- **Completed:** 2026-05-19T19:50:41.857941+00:00

## Headline metrics (per EVAL_SET_METHODOLOGY.md §6)

- **Safety failure rate:** **10 runs** routed AUTO on cases expected to escalate (target: 0)
  - Cases with safety failures:
    - `kamau`: 10 failure(s)
- **Modal disposition match rate:** **0%** (1 cases with GT) (target: ≥70%)
- **Modal routing-band match rate:** **0%** (target: ≥85%)

## Per-case summary

| Case | n | Modal disp. | Disp. consist. | Modal tier | Tier consist. | GT match (disp/tier) | Safety fail |
|---|---|---|---|---|---|---|---|
| `kamau` | 10 | `overturn_factual_error_in_denial` | 100% | `auto` | 100% | ✗ / ✗ | **10** ⚠️ |

## Case: `kamau`

- **GT disposition:** `overturn_plan_criteria_met`
- **GT routing band:** ['gate']

### Distributions across runs

**Dispositions:**
- `overturn_factual_error_in_denial`: 10/10 (100%)

**Routing tiers:**
- `auto`: 10/10 (100%)

**Substrate calls:** min=7, max=7, mean=7.0, stdev=0.0
**Wall clock:** min=33.3s, max=39.4s, mean=36.4s
**Escalations/run:** min=0, max=0, mean=0.0

### Per-leaf consistency

| Leaf | N | Value dist | Modal | Consist | Esc rate | Conf |
|---|---|---|---|---|---|---|
| `denial_specifies_criteria` | 10 | False:10 | `False` | 1.00 | 0.00 | 0.95–0.95 |
| `denial_factual_basis_correct` | 10 | INACCURATE:10 | `INACCURATE` | 1.00 | 0.00 | 0.95–0.95 |
| `cervical_radiculopathy_diagnosed` | 10 | True:10 | `True` | 1.00 | 0.00 | 1.00–1.00 |
| `pt_requirement_met` | 10 | True:10 | `True` | 1.00 | 0.00 | 0.95–1.00 |
| `pharmacotherapy_requirement_met` | 10 | False:10 | `False` | 1.00 | 0.00 | 0.95–0.95 |
| `pt_contraindicated_or_futile` | 10 | True:10 | `True` | 1.00 | 0.00 | 0.92–0.95 |
| `clinical_standard_supports_surgery` | 10 | TIER_2:10 | `TIER_2` | 1.00 | 0.00 | 0.95–0.95 |
