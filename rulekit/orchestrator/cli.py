"""Command-line entry point for RuleKit Orchestrator v0.1."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from rulekit.orchestrator.config import save_policy_workspace_seed
from rulekit.orchestrator.factory import (
    AtomDeclaration,
    CaseDeclaration,
    DeterminationDeclaration,
    PolicyWorkspaceSeed,
)
from rulekit.orchestrator.examples.prior_auth_typed import prior_auth_typed_seed
from rulekit.orchestrator.workflow import (
    apply_persisted_program_edits,
    export_builder_ui,
    export_review_bundle,
    inspect_persisted_run,
    list_branches,
    list_persisted_runs,
    load_program_edit_operations,
    mark_branch_status,
    reexercise_latest_snapshot,
    run_policy_seed_file,
)


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "template":
            return _template(args)
        if args.command == "run":
            return _run(args)
        if args.command == "list":
            return _list(args)
        if args.command == "inspect":
            return _inspect(args)
        if args.command == "export":
            return _export(args)
        if args.command == "edit":
            return _edit(args)
        if args.command == "reexercise":
            return _reexercise(args)
        if args.command == "branches":
            return _branches(args)
        if args.command == "serve":
            return _serve(args)
        if args.command == "ui":
            return _ui(args)
    except Exception as exc:  # pragma: no cover - exercised through return behavior
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}, indent=2, sort_keys=True))
        else:
            print(f"error: {exc}")
        return 1
    parser.print_help()
    return 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rulekit-orchestrator",
        description="Run and inspect RuleKit Orchestrator policy workspaces.",
    )
    subcommands = parser.add_subparsers(dest="command")

    template = subcommands.add_parser("template", help="write a generic seed template")
    template.add_argument("path", help="output .json/.yaml/.yml path")
    template.add_argument(
        "--example",
        choices=["sample", "prior-auth-typed"],
        default="sample",
        help="seed example to write (default: sample)",
    )
    template.add_argument("--json", action="store_true", help="print JSON status")

    run = subcommands.add_parser("run", help="run a generic policy seed")
    run.add_argument("seed", help="input .json/.yaml/.yml policy seed")
    run.add_argument(
        "--root",
        default=".rulekit_workspaces",
        help="workspace persistence root (default: .rulekit_workspaces)",
    )
    run.add_argument("--k", type=int, default=2, help="stochastic run count")
    run.add_argument("--program-id", default=None, help="program id for the snapshot")
    run.add_argument("--program-version", default="0.1", help="program version label")
    run.add_argument("--json", action="store_true", help="print JSON summary")

    list_cmd = subcommands.add_parser("list", help="list persisted trajectories")
    list_cmd.add_argument("--root", default=".rulekit_workspaces")
    list_cmd.add_argument("--json", action="store_true", help="print JSON summary")

    inspect = subcommands.add_parser("inspect", help="inspect a persisted trajectory")
    inspect.add_argument("--root", default=".rulekit_workspaces")
    inspect.add_argument("--workspace-id", required=True)
    inspect.add_argument("--trajectory-id", required=True)
    inspect.add_argument("--json", action="store_true", help="print JSON summary")

    export = subcommands.add_parser("export", help="export review artifacts")
    export.add_argument("--root", default=".rulekit_workspaces")
    export.add_argument("--workspace-id", required=True)
    export.add_argument("--trajectory-id", required=True)
    export.add_argument("--out", required=True, help="output directory")
    export.add_argument("--json", action="store_true", help="print JSON summary")

    edit = subcommands.add_parser("edit", help="apply typed edits to a persisted snapshot")
    edit.add_argument("operations", help="JSON/YAML operations file")
    edit.add_argument("--root", default=".rulekit_workspaces")
    edit.add_argument("--workspace-id", required=True)
    edit.add_argument("--trajectory-id", required=True)
    edit.add_argument("--snapshot-id", default=None, help="snapshot to edit; defaults to latest")
    edit.add_argument("--json", action="store_true", help="print JSON summary")

    reexercise = subcommands.add_parser(
        "reexercise",
        help="re-run cases against a persisted snapshot",
    )
    reexercise.add_argument("--root", default=".rulekit_workspaces")
    reexercise.add_argument("--workspace-id", required=True)
    reexercise.add_argument("--trajectory-id", required=True)
    reexercise.add_argument("--snapshot-id", default=None, help="snapshot to run; defaults to latest")
    reexercise.add_argument("--json", action="store_true", help="print JSON summary")

    branches = subcommands.add_parser("branches", help="list or mark trajectory branches")
    branches_subcommands = branches.add_subparsers(dest="branch_command")
    branches_list = branches_subcommands.add_parser("list", help="list branches")
    branches_list.add_argument("--root", default=".rulekit_workspaces")
    branches_list.add_argument("--workspace-id", required=True)
    branches_list.add_argument("--trajectory-id", required=True)
    branches_list.add_argument("--json", action="store_true", help="print JSON summary")
    branches_mark = branches_subcommands.add_parser("mark", help="mark a branch settled or abandoned")
    branches_mark.add_argument("--root", default=".rulekit_workspaces")
    branches_mark.add_argument("--workspace-id", required=True)
    branches_mark.add_argument("--trajectory-id", required=True)
    branches_mark.add_argument("--branch-id", required=True)
    branches_mark.add_argument("--status", choices=["settled", "abandoned"], required=True)
    branches_mark.add_argument("--reviewer-id", default=None)
    branches_mark.add_argument("--reason", default=None)
    branches_mark.add_argument("--json", action="store_true", help="print JSON summary")

    serve = subcommands.add_parser("serve", help="run the optional API server")
    serve.add_argument("--root", default=".rulekit_workspaces")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--json", action="store_true", help="print JSON errors")

    ui = subcommands.add_parser("ui", help="export a static Builder UI")
    ui.add_argument("--root", default=".rulekit_workspaces")
    ui.add_argument("--workspace-id", required=True)
    ui.add_argument("--trajectory-id", required=True)
    ui.add_argument("--out", required=True, help="output directory")
    ui.add_argument("--json", action="store_true", help="print JSON summary")
    return parser


def _template(args: argparse.Namespace) -> int:
    seed = template_seed(args.example)
    path = save_policy_workspace_seed(seed, args.path)
    payload = {"ok": True, "path": str(path), "example": args.example}
    _print(payload, args.json)
    return 0


def _run(args: argparse.Namespace) -> int:
    result = run_policy_seed_file(
        args.seed,
        args.root,
        k=args.k,
        program_id=args.program_id,
        program_version=args.program_version,
    )
    payload = {"ok": result.validation.ok, **result.summary()}
    _print(payload, args.json)
    return 0 if result.validation.ok else 1


def _inspect(args: argparse.Namespace) -> int:
    payload = inspect_persisted_run(args.root, args.workspace_id, args.trajectory_id)
    payload = {"ok": payload["validation_ok"], **payload}
    _print(payload, args.json)
    return 0 if payload["validation_ok"] else 1


def _list(args: argparse.Namespace) -> int:
    runs = list_persisted_runs(args.root)
    payload = {"ok": True, "count": len(runs), "runs": runs}
    _print(payload, args.json)
    return 0


def _export(args: argparse.Namespace) -> int:
    payload = export_review_bundle(
        args.root,
        args.workspace_id,
        args.trajectory_id,
        args.out,
    )
    payload = {"ok": payload["validation_ok"], **payload}
    _print(payload, args.json)
    return 0 if payload["validation_ok"] else 1


def _edit(args: argparse.Namespace) -> int:
    operations = load_program_edit_operations(args.operations)
    result = apply_persisted_program_edits(
        args.root,
        args.workspace_id,
        args.trajectory_id,
        operations,
        snapshot_id=args.snapshot_id,
    )
    payload = {"ok": result.validation.ok, **result.summary()}
    _print(payload, args.json)
    return 0 if result.validation.ok else 1


def _reexercise(args: argparse.Namespace) -> int:
    result = reexercise_latest_snapshot(
        args.root,
        args.workspace_id,
        args.trajectory_id,
        snapshot_id=args.snapshot_id,
    )
    payload = {"ok": result.validation.ok, **result.summary()}
    _print(payload, args.json)
    return 0 if result.validation.ok else 1


def _branches(args: argparse.Namespace) -> int:
    if args.branch_command == "list":
        branches = list_branches(args.root, args.workspace_id, args.trajectory_id)
        payload = {"ok": True, "count": len(branches), "branches": branches}
        _print(payload, args.json)
        return 0
    if args.branch_command == "mark":
        payload = mark_branch_status(
            args.root,
            args.workspace_id,
            args.trajectory_id,
            args.branch_id,
            args.status,
            reviewer_id=args.reviewer_id,
            reason=args.reason,
        )
        payload = {"ok": payload["validation_ok"], **payload}
        _print(payload, args.json)
        return 0 if payload["validation_ok"] else 1
    raise ValueError("branches command requires 'list' or 'mark'")


def _serve(args: argparse.Namespace) -> int:
    try:
        import uvicorn
    except ImportError as exc:
        raise RuntimeError("Install rulekit[api] to use 'serve'") from exc
    from rulekit.orchestrator.api import create_app

    uvicorn.run(create_app(args.root), host=args.host, port=args.port)
    return 0


def _ui(args: argparse.Namespace) -> int:
    payload = export_builder_ui(
        args.root,
        args.workspace_id,
        args.trajectory_id,
        args.out,
    )
    payload = {"ok": payload["validation_ok"], **payload}
    _print(payload, args.json)
    return 0 if payload["validation_ok"] else 1


def _print(payload: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    for key, value in payload.items():
        print(f"{key}: {value}")


def sample_seed() -> PolicyWorkspaceSeed:
    return PolicyWorkspaceSeed(
        workspace_name="Sample Policy Workspace",
        policy_title="Sample eligibility policy",
        policy_text=(
            "A request is eligible when requirement A and requirement B are both met."
        ),
        version_label="draft",
        determinations=[
            DeterminationDeclaration(
                determination_id="sample.eligible",
                description="The request is eligible.",
                atom_ids=["sample.requirement_a", "sample.requirement_b"],
                operator="and",
                source_span="requirement A and requirement B are both met",
            )
        ],
        atoms=[
            AtomDeclaration(
                atom_id="sample.requirement_a",
                statement="Requirement A is met.",
                source_span="requirement A",
            ),
            AtomDeclaration(
                atom_id="sample.requirement_b",
                statement="Requirement B is met.",
                source_span="requirement B",
            ),
        ],
        cases=[
            CaseDeclaration(
                case_id="case_yes",
                title="Both requirements",
                narrative="Requirement A and requirement B are met.",
                structured_fields={
                    "facts": {
                        "sample.requirement_a": True,
                        "sample.requirement_b": True,
                    }
                },
                expected_outcomes={"sample.eligible": "true"},
            ),
            CaseDeclaration(
                case_id="case_no",
                title="Missing requirement B",
                narrative="Requirement A is met, but requirement B is not met.",
                structured_fields={
                    "facts": {
                        "sample.requirement_a": True,
                        "sample.requirement_b": False,
                    }
                },
                expected_outcomes={"sample.eligible": "false"},
            ),
        ],
    )


def template_seed(example: str) -> PolicyWorkspaceSeed:
    if example == "sample":
        return sample_seed()
    if example == "prior-auth-typed":
        return prior_auth_typed_seed()
    raise ValueError(f"unknown template example {example!r}")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["main", "sample_seed", "template_seed"]
