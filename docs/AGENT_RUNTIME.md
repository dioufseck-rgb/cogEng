# RuleKit Agent Runtime Artifacts

RuleKit's deployable policy artifact is a `DeterminationProgram` JSON document.
It contains the policy DAG, atom catalog, Map specification, constants,
determinations, case input schema, and test cases. The Builder UI and
orchestrator are governance tools around this artifact; agent runtimes should
load the artifact and call the deterministic engine, not ask an LLM to
adjudicate the policy.

## Export

From a persisted orchestrator run:

```powershell
rulekit-orchestrator export `
  --root .rulekit_workspaces `
  --workspace-id <workspace_id> `
  --trajectory-id <trajectory_id> `
  --out exported_rulekit_bundle
```

The deployable DAG is:

```text
exported_rulekit_bundle/program.json
```

The same program also lives inside the latest persisted snapshot:

```text
.rulekit_workspaces/<workspace_id>/trajectories/<trajectory_id>/snapshots/<snapshot_id>.json
```

## Runtime Load

```python
import json

from rulekit.contract import DeterminationProgram, safe_program_to_engine
from rulekit.orchestrator.map_step import TypedNarrativeMapStep
from rulekit.build.llm import LLMCaller

program = DeterminationProgram.model_validate_json(
    open("exported_rulekit_bundle/program.json", encoding="utf-8").read()
)
runtime = safe_program_to_engine(program)
```

At request time, the agent orchestration layer should:

1. Receive the case facts or natural-language case packet.
2. Run a Map substrate to bind case evidence to program atoms.
3. Build a `FactBundle` from the Map record.
4. Evaluate the requested `runtime.determinations[determination_id]`.
5. Return the outcome plus trace, load-bearing path, map record, and program
   version.

The LLM, when used, belongs in step 2 only. It extracts atom values from case
text. The engine performs the actual policy disposition.

## CLI Runner

For end-to-end runtime checks without writing Python:

```powershell
rulekit-orchestrator adjudicate `
  --program exported_rulekit_bundle/program.json `
  --cases runtime_cases.json `
  --determination prior_auth.approved `
  --out runtime_results `
  --json
```

`runtime_cases.json` can be a list or an object with a `cases` list:

```json
{
  "cases": [
    {
      "case_id": "case_001",
      "title": "Appeal packet",
      "narrative": "The patient completed eight weeks of therapy...",
      "facts": {
        "prior_auth.functional_limitation": true,
        "prior_auth.therapy_weeks": 8
      },
      "expected_outcomes": {
        "prior_auth.approved": "true"
      }
    }
  ]
}
```

For real runtime cases without known answers, omit `expected_outcomes`. The
runner still emits dispositions; `matched_expected` will be `null`.

The output directory contains:

```text
summary.json
map_records.json
dispositions.json
results.json
```

## Narrative Map

For natural case text:

```python
llm = LLMCaller(provider="anthropic", model="claude-opus-4-7")
map_step = TypedNarrativeMapStep(llm)
```

For OpenAI:

```python
llm = LLMCaller(provider="openai", model="gpt-5")
map_step = TypedNarrativeMapStep(llm)
```

Set the corresponding provider key in the runtime environment:

```powershell
$env:ANTHROPIC_API_KEY="..."
$env:OPENAI_API_KEY="..."
```

The orchestrator server can also be started in narrative mode:

```powershell
rulekit-orchestrator serve `
  --root .rulekit_workspaces `
  --map-mode narrative `
  --llm-provider anthropic `
  --llm-model claude-opus-4-7
```

Use `--map-mode prebound` for deterministic test suites that already supply
`structured_fields.facts`.
