# RuleKit Positioning and Latest Evaluation

Date: 2026-06-04

Scope: latest comparison only, using the FCRA CRA logic-stress suite and
`anthropic:claude-sonnet-4-6`.

## What RuleKit Is

RuleKit is a governed policy-reasoning system for agentic workflows. Its goal is
not to replace language models, and it is not a direct-prompt adjudicator. It is
a way to build, test, and deploy policy artifacts that can be used by agents
when the agent must make or support a regulated decision.

The central idea is separation of concerns:

1. A policy is represented as a deterministic decision artifact.
2. A case is mapped into policy-relevant findings.
3. The engine composes those findings into determinations.
4. The result includes a trace that can be reviewed, tested, appealed, and
   improved.

This matters because many high-stakes policy workflows cannot rely on an LLM's
free-form final answer. Prior authorization, immigration eligibility, tax
review, credit-reporting disputes, and similar domains need a decision that is
not only plausible, but traceable. If the decision is challenged, the institution
must be able to say what policy rule was applied, what facts were material, what
evidence supported them, where uncertainty remained, and why the final outcome
followed.

## Positioning

RuleKit sits between direct LLM adjudication and fully hand-coded rules.

Direct LLM adjudication is flexible. It can read a narrative and produce a
reasonable-looking answer quickly. But it has weak governance properties:

- the model reasons at the final-disposition level,
- intermediate legal or policy findings are not guaranteed to be stable,
- uncertainty can be laundered into a confident answer,
- appeal traces are post hoc rather than structurally produced,
- and failures may be hard to repair without changing the whole prompt.

Traditional rules engines have the opposite problem. They are deterministic and
auditable, but brittle. They require the case facts to already be normalized
into the exact vocabulary of the rule system. In real workflows, the facts arrive
as narratives, document packets, inconsistent records, allegations, denials,
missing dates, and ambiguous institutional notes.

RuleKit's positioning is neurosymbolic:

- use LLMs for language-to-policy-finding work,
- use deterministic artifacts for policy composition,
- keep final reasoning governed by explicit policy structure,
- and make every intermediate decision inspectable.

The current experiment tests whether the right LLM-facing abstraction is not
microscopic atoms, but branch-level findings with material audit slots.

## Why The Architecture Changed

Earlier total-atom mapping experiments forced the LLM to fill many microscopic
policy atoms. That approach was too expensive and often less accurate than a
direct prompt. The failure mode was not that governed execution was bad; it was
that the LLM was being asked to reason at a semantic level that was too granular
for the case narrative.

The latest architecture uses branch-level findings.

Instead of asking the model to bind every low-level atom, RuleKit asks it to
evaluate each material branch of the policy. Each branch finding includes:

- the determination id,
- whether the branch is applicable,
- whether it is satisfied,
- the branch outcome,
- whether it blocks the final disposition,
- a short rationale,
- and structured `material_findings`.

The `material_findings` are the key addition. They keep the branch from becoming
too aggregate to audit. Each material finding records:

- `slot`: the branch-local audit slot, such as `triggering_event`,
  `timing`, `failure_fact`, or `exception_or_short_circuit`;
- `value`: the fact or conclusion for that slot;
- `status`: `established`, `not_applicable`, `undetermined`, or `conflicting`;
- `basis`: `explicit`, `inferred`, `profile_default`, `not_applicable`,
  `missing`, or `conflicting`;
- `evidence`: short case-grounded support;
- `source_ids`: where the support came from;
- `supports`: whether the slot supports applicability, satisfaction, blocking,
  routing, or context.

This gives the LLM a more natural reasoning target while preserving an audit
surface that can be validated and repaired.

## Latest Evaluation Design

The latest comparison used the FCRA CRA full-policy logic-stress evaluation
suite.

Policy artifact:

`audits/fcra_credit_reporting_deep/rulekit_export_profile2/program.json`

Case suite:

`rulekit/orchestrator/example_cases/fcra_cra_logic_stress_eval.yaml`

Model:

`anthropic:claude-sonnet-4-6`

Cases:

12 synthetic FCRA credit-reporting dispute cases designed to stress nested
branch applicability, exception paths, conditional deadlines, source-scope
issues, conflict propagation, routing, and final disposition composition.

The comparison had two approaches:

1. **RuleKit branch findings with material slots**
   - One LLM call per case.
   - The LLM evaluates branch-level findings and material slots.
   - RuleKit deterministically composes the final disposition from branch
     blockers.
   - The output includes structured material audit findings.

2. **Profiled direct LLM disposition**
   - One LLM call per case.
   - The LLM directly adjudicates all selected determinations.
   - The prompt includes policy text, perspective, and profile guidance.
   - There is no deterministic final-composition layer and no structured branch
     material-finding contract.

This is a relatively fair comparison on cost and call count: both approaches
used 12 calls, the same model, the same policy, and the same cases.

## Results

| Approach | Cases | Calls | Determination Accuracy | Final Accuracy | Routing Accuracy | Est. Cost | Latency |
|---|---:|---:|---:|---:|---:|---:|---:|
| RuleKit branch findings + material slots | 12 | 12 | 174/180, 96.67% | 11/12, 91.67% | 11/12, 91.67% | $1.157 | 782.0s |
| Profiled direct disposition | 12 | 12 | 162/180, 90.00% | 11/12, 91.67% | 11/12, 91.67% | $1.057 | 809.5s |

RuleKit was slightly more expensive by estimated token cost, but materially
better on individual determination accuracy. Both approaches tied on final
disposition and routing accuracy.

The branch/material run also produced a structured audit trace:

| Metric | Value |
|---|---:|
| Branch/routing findings | 168 |
| Material findings | 298 |
| Average material findings per finding | 1.77 |

Material-finding status counts:

| Status | Count |
|---|---:|
| established | 220 |
| not_applicable | 65 |
| undetermined | 9 |
| conflicting | 4 |

Material-finding basis counts:

| Basis | Count |
|---|---:|
| explicit | 190 |
| inferred | 60 |
| profile_default | 46 |
| not_applicable | 2 |

These counts matter because they show that the RuleKit run did not merely output
final labels. It produced a case-by-case structure of what was established, what
was inferred, what was defaulted by profile semantics, what was not applicable,
and what remained uncertain or conflicting.

## What The Comparison Shows

The latest comparison supports the core RuleKit hypothesis more strongly than
the earlier microscopic atom-mapping runs.

The important result is not just that RuleKit scored higher on determinations.
The important result is that RuleKit scored higher while preserving a governed
decision surface:

- branch findings are separated from final composition,
- material facts are visible,
- uncertainty is explicitly represented,
- final disposition is computed from branch blockers,
- and mismatch analysis can identify which part of the architecture failed.

In the direct baseline, the LLM often made semantically plausible mistakes that
were difficult to localize. The largest direct-prompt failure pattern was
`fcra.frivolous_termination_valid`: direct prompting repeatedly treated "no
frivolous termination was invoked" as `true`, because it generalized the rule
"not applicable means satisfied." The branch/material prompt fixed this by
distinguishing existential or event-validity determinations from ordinary
"satisfied or not applicable" duty determinations.

This is exactly the kind of distinction that a governed policy artifact can
stabilize better than a broad direct prompt.

## What RuleKit Got Wrong

RuleKit still had 6 mismatches.

The errors were not random. They fell into three categories:

1. **Benchmark semantics need sharper policy-pack encoding**

Some labels reflect benchmark-specific semantics that are not obvious from the
determination name. For example, in a reseller-own-error case, the model treated
source-CRA reinvestigation as not required because the reseller corrected its
own error. The benchmark expected the broader CRA-trigger determinations to be
true. This suggests the policy pack needs explicit per-determination evaluation
semantics, not just a description and source span.

2. **Routing semantics remain under-specified**

One invalid duplicate/frivolous termination case expected
`human_review_required=true`, while the model treated the defects as clear
substantive failures rather than unresolved review triggers. This is a design
question: should human review route only unresolved uncertainty, or also certain
severe clear defects?

3. **The model can emit contradictory structured fields**

In the public-record exception case, the rationale and material findings said
the public-record exception applied and the outcome should be true, but the JSON
fields emitted `outcome=false`, `satisfied=false`, and `blocks_final=true`. That
single contradiction caused the only final-disposition miss.

This is an engineering opportunity. A consistency validator could catch cases
where the material findings and rationale imply one branch result but the
structured outcome fields say another.

## What Direct LLM Got Wrong

The direct baseline had 18 mismatches.

Its main failure was repeated overgeneralization:

| Determination | Mismatches |
|---|---:|
| `fcra.frivolous_termination_valid` | 9 |
| `fcra.results_notice_satisfied` | 2 |
| `fcra.furnisher_indirect_satisfied` | 2 |
| Other determinations | 5 |

This is significant. Direct prompting was not simply worse in a diffuse way; it
had a systematic semantic failure. It repeatedly collapsed an event-validity
determination into a generic not-applicable-is-satisfied duty determination.

Direct also struggled with trigger timing. In the pending manual-review case, a
post-completion results-notice duty was treated as currently failed even though
the reinvestigation was not complete and the notice deadline had not yet been
triggered. The RuleKit branch prompt was revised to explicitly preserve this as
undetermined unless the trigger and deadline had occurred.

## Interpretation

The latest comparison suggests that RuleKit's best path is not "LLM extracts
every atom, engine does everything else." That was too brittle and costly.

The better path is:

1. The policy pack defines determinations, branch semantics, routing semantics,
   and composition.
2. The LLM evaluates branch-level findings, not microscopic atoms.
3. The LLM must expose material audit slots for each branch.
4. Deterministic code composes the final disposition.
5. Validators check consistency among material findings, branch outcomes,
   blockers, routing, and final results.

This keeps the LLM at a semantic level where it performs well, while still
preventing direct ungoverned final disposition.

The result is a stronger neurosymbolic claim:

RuleKit can match or exceed direct LLM adjudication on determination quality
while producing a more governable artifact: branch findings, material facts,
uncertainty markers, and deterministic final composition.

## Current Limitations

This comparison is promising but not conclusive.

Limitations:

- It used one provider and one model, because only the Anthropic key was loaded
  in this session.
- The cases are synthetic, though designed to stress realistic FCRA logic.
- The case count is 12, with 180 determinations.
- The prompt was tuned during the sanity pass before the full run.
- The final-disposition comparison tied at 11/12, so the headline final outcome
  advantage is not yet proven.
- Some expected labels may encode benchmark-specific semantics that need to be
  made explicit in the policy pack.

The evidence is therefore best read as a directional architecture result, not a
production readiness claim.

## Recommended Next Work

The next build step should be consistency validation for branch findings.

A validator should check:

- if `outcome`, `satisfied`, `blocks_final`, rationale, and material findings
  contradict each other;
- if an exception or short-circuit material finding implies not-applicable or
  satisfied treatment;
- if a post-trigger duty is being treated as failed before its trigger occurs;
- if a routing finding is inconsistent with material conflict or missing-source
  slots;
- and if branch findings violate per-determination evaluation semantics.

The next policy-pack step should be adding explicit evaluation semantics per
determination. Determination names alone are not enough. The pack should state
whether a determination is:

- existential,
- event-validity,
- required-duty,
- satisfied-or-not-applicable,
- routing,
- final-composition,
- or perspective-specific.

That would make the branch/material approach less dependent on prompt wording
and more dependent on durable policy artifacts.

The next evaluation step should be a cross-provider rerun:

- Anthropic Sonnet,
- OpenAI frontier model,
- Gemini frontier model,
- and at least one lower-cost model.

The question to answer is whether the branch/material architecture remains more
accurate and more governable across model families, and whether lower-cost
models can perform branch finding adequately when final composition is
deterministic.

## Bottom Line

The latest comparison is the strongest evidence so far for RuleKit's direction.

Direct LLM adjudication remains competitive on final outcomes, but it is weaker
on intermediate determinations and does not naturally produce a governed audit
surface. RuleKit branch findings with material slots improved determination
accuracy, preserved final/routing performance, and produced inspectable reasons
that make errors easier to diagnose and repair.

The architecture is not finished. The next decisive improvement is validation:
make the system reject or repair internally inconsistent branch findings before
they reach deterministic final composition.
