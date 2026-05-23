# Variance Analysis — Session `b56daf5f`

- **Model:** `claude-sonnet-4-5`
- **Cases:** kamau
- **Runs per case:** 10
- **Total runs:** 10
- **Started:** 2026-05-19T17:09:02.927288+00:00
- **Completed:** 2026-05-19T17:21:15.627100+00:00

## Headline metrics (per EVAL_SET_METHODOLOGY.md §6)

- **Safety failure rate:** **0 runs** routed AUTO on cases expected to escalate (target: 0)
- **Modal disposition match rate:** **0%** (1 cases with GT) (target: ≥70%)
- **Modal routing-band match rate:** **100%** (target: ≥85%)

## Per-case summary

| Case | n | Modal disp. | Disp. consist. | Modal tier | Tier consist. | GT match (disp/tier) | Safety fail |
|---|---|---|---|---|---|---|---|
| `kamau` | 10 | `overturn_factual_error_in_denial` | 100% | `gate` | 60% | ✗ / ✓ | 0 |

## Case: `kamau`

- **GT disposition:** `overturn_plan_criteria_met`
- **GT routing band:** ['gate']

### Distributions across runs

**Dispositions:**
- `overturn_factual_error_in_denial`: 10/10 (100%)

**Routing tiers:**
- `gate`: 6/10 (60%)
- `spot_check`: 4/10 (40%)

**Substrate calls:** min=8, max=17, mean=13.0, stdev=4.3
**Wall clock:** min=40.5s, max=100.6s, mean=71.4s
**Escalations/run:** min=1, max=4, mean=2.4

### Per-leaf consistency

| Leaf | N | Value dist | Modal | Consist | Esc rate | Conf |
|---|---|---|---|---|---|---|
| `functional_limitations_described` | 6 | None:6 | `None` | 1.00 | 1.00 | 0.00–0.00 |
| `surgical_risks_alternatives_addressed` | 6 | None:6 | `None` | 1.00 | 1.00 | 0.00–0.00 |
| `pharmacotherapy_requirement_met` | 10 | False:10 | `False` | 1.00 | 0.60 | 0.85–0.90 |
| `pt_contraindicated_or_futile` | 10 | True:10 | `True` | 1.00 | 0.60 | 0.85–0.85 |
| `denial_specifies_criteria` | 10 | False:10 | `False` | 1.00 | 0.00 | 0.95–0.95 |
| `denial_factual_basis_correct` | 10 | INACCURATE:10 | `INACCURATE` | 1.00 | 0.00 | 0.95–0.95 |
| `cervical_radiculopathy_diagnosed` | 10 | True:10 | `True` | 1.00 | 0.00 | 1.00–1.00 |
| `pt_requirement_met` | 10 | True:10 | `True` | 1.00 | 0.00 | 0.95–0.95 |
| `interventional_requirement_met_or_waived` | 6 | True:6 | `True` | 1.00 | 0.00 | 1.00–1.00 |
| `imaging_requirement_met` | 6 | True:6 | `True` | 1.00 | 0.00 | 0.98–0.98 |
| `attestation_conservative_treatment` | 6 | True:6 | `True` | 1.00 | 0.00 | 0.85–0.85 |
| `clinical_rationale_for_surgery` | 6 | True:6 | `True` | 1.00 | 0.00 | 0.95–0.95 |
| `exclusion_3_1_axial_pain_only` | 6 | True:6 | `True` | 1.00 | 0.00 | 0.98–1.00 |
| `exclusion_3_3_imaging_inconsistent` | 6 | True:6 | `True` | 1.00 | 0.00 | 0.98–0.98 |
| `exclusion_3_4_experimental_procedure` | 6 | True:6 | `True` | 1.00 | 0.00 | 0.95–0.95 |
| `functional_plateau_documented` | 6 | True:6 | `True` | 1.00 | 0.00 | 0.95–0.98 |
| `clinical_standard_supports_surgery` | 10 | TIER_2:10 | `TIER_2` | 1.00 | 0.00 | 0.95–0.95 |

### Escalation signals observed

- `functional_limitations_described`: insufficient_facts:6
- `surgical_risks_alternatives_addressed`: insufficient_facts:6
- `pharmacotherapy_requirement_met`: contested_reading:6
- `pt_contraindicated_or_futile`: contested_reading:6
