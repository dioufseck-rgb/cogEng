# RuleKit Orchestrator CLI

The Orchestrator CLI is a thin v0.1 command surface over the generic policy
seed workflow. It creates domain-neutral workspaces, candidate programs,
trajectory event logs, reports, diagnostics, and persisted sidecars.

The current workflow uses the governed `PreboundFactsMapStep`, which reads
case facts from `structured_fields.facts` and emits standard
`MapExtractionRecord` objects. Future Map implementations can replace that
step while preserving the same persisted record shape.

## Commands

Write a starter seed:

```powershell
rulekit-orchestrator template sample_policy.yaml
```

Run a seed:

```powershell
rulekit-orchestrator run sample_policy.yaml --root .rulekit_workspaces --json
```

Inspect a persisted trajectory:

```powershell
rulekit-orchestrator inspect `
  --root .rulekit_workspaces `
  --workspace-id ws_... `
  --trajectory-id traj_... `
  --json
```

List persisted trajectories:

```powershell
rulekit-orchestrator list --root .rulekit_workspaces --json
```

Export a reviewer bundle:

```powershell
rulekit-orchestrator export `
  --root .rulekit_workspaces `
  --workspace-id ws_... `
  --trajectory-id traj_... `
  --out review_bundle `
  --json
```

The exported bundle includes `summary.json`, `workspace.json`,
`trajectory_events.json`, `program.json`, `snapshots.json`, `reports.json`,
`diagnostics.json`, `dispositions.json`, and `map_records.json`.

Apply governed edits to the latest snapshot:

```powershell
rulekit-orchestrator edit edits.yaml `
  --root .rulekit_workspaces `
  --workspace-id ws_... `
  --trajectory-id traj_... `
  --json
```

Edit files may be a list, or an object with an `operations` list:

```yaml
operations:
  - kind: update_boolean_atom
    payload:
      atom_id: sample.requirement_b
      notes: Reviewer clarified this requirement.
```

An edit creates a persisted `program_edits/<edit_id>.json` sidecar, appends a
reviewer intervention, creates a child branch, appends a `program_edit_applied`
trajectory event on that branch, and writes a new program snapshot.

List branches:

```powershell
rulekit-orchestrator branches list `
  --root .rulekit_workspaces `
  --workspace-id ws_... `
  --trajectory-id traj_... `
  --json
```

Mark a branch settled or abandoned:

```powershell
rulekit-orchestrator branches mark `
  --root .rulekit_workspaces `
  --workspace-id ws_... `
  --trajectory-id traj_... `
  --branch-id br_... `
  --status settled `
  --json
```

Re-exercise the latest snapshot against persisted cases:

```powershell
rulekit-orchestrator reexercise `
  --root .rulekit_workspaces `
  --workspace-id ws_... `
  --trajectory-id traj_... `
  --json
```

Re-exercise appends fresh Map records, dispositions, diagnostics, coverage,
source-text coverage, sensitivity, and regression reports. Use `--snapshot-id`
to re-run a specific snapshot instead of the latest one.

Export a static Builder UI:

```powershell
rulekit-orchestrator ui `
  --root .rulekit_workspaces `
  --workspace-id ws_... `
  --trajectory-id traj_... `
  --out builder_ui `
  --json
```

Open `builder_ui/index.html` from a local static server. The UI reads
`projection.json` and renders overview, case results, timeline, reports, and
branch state.

## Optional API Server

Install the optional API extra to run the HTTP surface:

```powershell
pip install -e .[api]
rulekit-orchestrator serve --root .rulekit_workspaces --port 8000
```

The API exposes the same workflow layer used by the CLI:

- `GET /health`
- `GET /runs`
- `GET /projection`
- `POST /runs`
- `GET /workspaces/{workspace_id}/trajectories/{trajectory_id}`
- `GET /workspaces/{workspace_id}/trajectories/{trajectory_id}/projection`
- `GET /workspaces/{workspace_id}/trajectories/{trajectory_id}/branches`
- `POST /workspaces/{workspace_id}/trajectories/{trajectory_id}/edit`
- `POST /workspaces/{workspace_id}/trajectories/{trajectory_id}/reexercise`
- `POST /workspaces/{workspace_id}/trajectories/{trajectory_id}/export`

## Seed Shape

A seed declares policy text, atoms, determinations, and cases. The v0.1
workflow expects facts for test cases in `structured_fields.facts`.

```yaml
workspace_name: Sample Policy Workspace
policy_title: Sample eligibility policy
policy_text: A request is eligible when requirement A and requirement B are both met.
determinations:
  - determination_id: sample.eligible
    description: The request is eligible.
    atom_ids:
      - sample.requirement_a
      - sample.requirement_b
    operator: and
atoms:
  - atom_id: sample.requirement_a
    statement: Requirement A is met.
  - atom_id: sample.requirement_b
    statement: Requirement B is met.
cases:
  - case_id: case_yes
    title: Both requirements
    narrative: Requirement A and requirement B are met.
    structured_fields:
      facts:
        sample.requirement_a: true
        sample.requirement_b: true
    expected_outcomes:
      sample.eligible: "true"
```

Supported factory operators are the RuleKit boolean engine operators:
`and`, `or`, `not`, and `at_least`.
