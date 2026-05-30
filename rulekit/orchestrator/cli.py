"""Command-line entry point for RuleKit Orchestrator v0.1."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from rulekit.orchestrator.config import load_policy_workspace_seed, save_policy_workspace_seed
from rulekit.orchestrator.factory import (
    AtomDeclaration,
    CaseDeclaration,
    DeterminationDeclaration,
    PolicyWorkspaceSeed,
)
from rulekit.orchestrator.examples.prior_auth_typed import prior_auth_typed_seed
from rulekit.orchestrator.examples.fcra_dispute import fcra_dispute_seed
from rulekit.orchestrator.llm_config import create_map_step
from rulekit.orchestrator.map_governance_eval import run_map_governance_eval
from rulekit.orchestrator.workflow import (
    apply_persisted_program_edits,
    add_persisted_case,
    export_builder_ui,
    export_review_bundle,
    inspect_persisted_run,
    list_branches,
    list_persisted_runs,
    load_program_edit_operations,
    mark_branch_status,
    record_persisted_reviewer_hint,
    reexercise_latest_snapshot,
    run_policy_seed_file,
)
from rulekit.runtime import (
    adjudicate_cases,
    load_program,
    load_runtime_cases,
    write_runtime_result,
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
        if args.command == "hint":
            return _hint(args)
        if args.command == "case":
            return _case(args)
        if args.command == "branches":
            return _branches(args)
        if args.command == "serve":
            return _serve(args)
        if args.command == "ui":
            return _ui(args)
        if args.command == "adjudicate":
            return _adjudicate(args)
        if args.command == "map-eval":
            return _map_eval(args)
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
        choices=["sample", "prior-auth-typed", "fcra-dispute", "uscis-n400"],
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
    _add_map_args(reexercise)
    reexercise.add_argument("--json", action="store_true", help="print JSON summary")

    hint = subcommands.add_parser("hint", help="record a natural-language reviewer hint")
    hint.add_argument("message", help="reviewer hint text")
    hint.add_argument("--root", default=".rulekit_workspaces")
    hint.add_argument("--workspace-id", required=True)
    hint.add_argument("--trajectory-id", required=True)
    hint.add_argument("--target-step-id", default=None)
    hint.add_argument("--case-id", default=None)
    hint.add_argument("--atom-id", action="append", default=[], help="atom the hint concerns; may repeat")
    hint.add_argument("--reviewer-id", default=None)
    hint.add_argument("--reason", default=None)
    hint.add_argument("--reexercise", action="store_true", help="rerun latest snapshot after recording")
    hint.add_argument("--snapshot-id", default=None, help="snapshot to rerun when --reexercise is set")
    _add_map_args(hint)
    hint.add_argument("--json", action="store_true", help="print JSON summary")

    case = subcommands.add_parser("case", help="add reviewer-authored cases")
    case_subcommands = case.add_subparsers(dest="case_command")
    case_add = case_subcommands.add_parser("add", help="add a case to a persisted workspace")
    case_add.add_argument("--root", default=".rulekit_workspaces")
    case_add.add_argument("--workspace-id", required=True)
    case_add.add_argument("--trajectory-id", required=True)
    case_add.add_argument("--suite-id", default=None)
    case_add.add_argument("--case-id", default=None)
    case_add.add_argument("--title", required=True)
    case_add.add_argument("--narrative", required=True)
    case_add.add_argument("--fact", action="append", default=[], help="fact as atom_id=value; may repeat")
    case_add.add_argument(
        "--expected",
        action="append",
        default=[],
        help="expected outcome as determination_id=value; may repeat",
    )
    case_add.add_argument("--reviewer-id", default=None)
    case_add.add_argument("--reason", default=None)
    case_add.add_argument("--reexercise", action="store_true", help="rerun latest snapshot after adding")
    case_add.add_argument("--snapshot-id", default=None, help="snapshot to rerun when --reexercise is set")
    _add_map_args(case_add)
    case_add.add_argument("--json", action="store_true", help="print JSON summary")

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
    _add_map_args(serve)
    serve.add_argument("--json", action="store_true", help="print JSON errors")

    ui = subcommands.add_parser("ui", help="export a static Builder UI")
    ui.add_argument("--root", default=".rulekit_workspaces")
    ui.add_argument("--workspace-id", required=True)
    ui.add_argument("--trajectory-id", required=True)
    ui.add_argument("--out", required=True, help="output directory")
    ui.add_argument("--json", action="store_true", help="print JSON summary")

    adjudicate = subcommands.add_parser(
        "adjudicate",
        help="run runtime cases against an exported DeterminationProgram",
    )
    adjudicate.add_argument("--program", required=True, help="program.json path")
    adjudicate.add_argument("--cases", required=True, help="JSON/YAML runtime cases file")
    adjudicate.add_argument(
        "--determination",
        action="append",
        default=[],
        help="determination id to evaluate; may repeat; defaults to all",
    )
    adjudicate.add_argument("--out", default=None, help="optional output directory")
    _add_map_args(adjudicate)
    adjudicate.add_argument("--json", action="store_true", help="print JSON result")

    map_eval = subcommands.add_parser(
        "map-eval",
        help="run governed Map prompts across multiple LLM providers",
    )
    map_eval.add_argument("--program", required=True, help="program.json path")
    map_eval.add_argument("--cases", required=True, help="JSON/YAML runtime cases file")
    map_eval.add_argument("--out", required=True, help="output evidence directory")
    map_eval.add_argument(
        "--model",
        action="append",
        required=True,
        help="provider:model, e.g. anthropic:claude-opus-4-7; may repeat",
    )
    map_eval.add_argument(
        "--determination",
        action="append",
        default=[],
        help="determination id to evaluate; may repeat; defaults to all",
    )
    map_eval.add_argument("--atom", action="append", default=[], help="atom id to bind; may repeat")
    map_eval.add_argument("--max-atoms", type=int, default=None)
    map_eval.add_argument("--llm-max-tokens", type=int, default=4096)
    map_eval.add_argument("--llm-timeout", type=float, default=120.0)
    map_eval.add_argument("--llm-max-retries", type=int, default=2)
    map_eval.add_argument("--json", action="store_true", help="print JSON summary")
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
    ui_url = _local_ui_url(result.workspace.workspace_id, result.trajectory.trajectory_id)
    payload = {
        "ok": result.validation.ok,
        **result.summary(),
        "ui_url": ui_url,
        "latest_ui_url": "http://127.0.0.1:8000/ui/latest/",
        "serve_command": f"rulekit-orchestrator serve --root {args.root} --port 8000",
    }
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
        map_step=_map_step_from_args(args),
    )
    payload = {"ok": result.validation.ok, **result.summary()}
    _print(payload, args.json)
    return 0 if result.validation.ok else 1


def _hint(args: argparse.Namespace) -> int:
    hint_result = record_persisted_reviewer_hint(
        args.root,
        args.workspace_id,
        args.trajectory_id,
        message=args.message,
        target_step_id=args.target_step_id,
        case_id=args.case_id,
        atom_ids=args.atom_id,
        reviewer_id=args.reviewer_id,
        reason=args.reason,
    )
    payload = {"ok": hint_result.validation.ok, **hint_result.summary()}
    exit_ok = hint_result.validation.ok
    if args.reexercise:
        rerun = reexercise_latest_snapshot(
            args.root,
            args.workspace_id,
            args.trajectory_id,
            snapshot_id=args.snapshot_id,
            map_step=_map_step_from_args(args),
        )
        payload["reexercise"] = {"ok": rerun.validation.ok, **rerun.summary()}
        exit_ok = exit_ok and rerun.validation.ok
    _print(payload, args.json)
    return 0 if exit_ok else 1


def _case(args: argparse.Namespace) -> int:
    if args.case_command == "add":
        case_result = add_persisted_case(
            args.root,
            args.workspace_id,
            args.trajectory_id,
            suite_id=args.suite_id,
            case_id=args.case_id,
            title=args.title,
            narrative=args.narrative,
            facts=_parse_key_values(args.fact),
            expected_outcomes=_parse_expected_values(args.expected),
            reviewer_id=args.reviewer_id,
            reason=args.reason,
        )
        payload = {"ok": case_result.validation.ok, **case_result.summary()}
        exit_ok = case_result.validation.ok
        if args.reexercise:
            rerun = reexercise_latest_snapshot(
                args.root,
                args.workspace_id,
                args.trajectory_id,
                snapshot_id=args.snapshot_id,
                map_step=_map_step_from_args(args),
            )
            payload["reexercise"] = {"ok": rerun.validation.ok, **rerun.summary()}
            exit_ok = exit_ok and rerun.validation.ok
        _print(payload, args.json)
        return 0 if exit_ok else 1
    raise ValueError("case command requires 'add'")


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

    uvicorn.run(
        create_app(
            args.root,
            map_mode=args.map_mode,
            llm_provider=args.llm_provider,
            llm_model=args.llm_model,
            llm_max_tokens=args.llm_max_tokens,
            llm_timeout=args.llm_timeout,
            llm_max_retries=args.llm_max_retries,
        ),
        host=args.host,
        port=args.port,
    )
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


def _adjudicate(args: argparse.Namespace) -> int:
    program = load_program(args.program)
    cases = load_runtime_cases(args.cases)
    result = adjudicate_cases(
        program,
        cases,
        determinations=args.determination or None,
        map_step=_map_step_from_args(args),
    )
    if args.out:
        result["files"] = write_runtime_result(result, args.out)
    result = {"ok": result["mismatch_count"] == 0, **result}
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        _print(
            {
                "ok": result["ok"],
                "case_count": result["case_count"],
                "disposition_count": result["disposition_count"],
                "matched_disposition_count": result["matched_disposition_count"],
                "mismatch_count": result["mismatch_count"],
                "map_mode": result["map_mode"],
                "files": result.get("files", {}),
            },
            False,
        )
    return 0 if result["ok"] else 1


def _map_eval(args: argparse.Namespace) -> int:
    result = run_map_governance_eval(
        program_path=args.program,
        cases_path=args.cases,
        model_specs=args.model,
        output_dir=args.out,
        determinations=args.determination or None,
        atom_ids=args.atom or None,
        max_atoms=args.max_atoms,
        max_tokens=args.llm_max_tokens,
        timeout=args.llm_timeout,
        max_retries=args.llm_max_retries,
    )
    payload = {"ok": True, **result}
    _print(payload, args.json)
    return 0


def _print(payload: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    for key, value in payload.items():
        print(f"{key}: {value}")


def _local_ui_url(workspace_id: str, trajectory_id: str) -> str:
    return f"http://127.0.0.1:8000/ui/{workspace_id}/{trajectory_id}/"


def _add_map_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--map-mode",
        choices=["prebound", "narrative"],
        default="prebound",
        help="Map substrate for reexercise (default: prebound facts)",
    )
    parser.add_argument(
        "--llm-provider",
        choices=["anthropic", "openai", "gemini"],
        default="anthropic",
        help="LLM provider when --map-mode narrative is used",
    )
    parser.add_argument("--llm-model", default=None, help="LLM model override")
    parser.add_argument("--llm-max-tokens", type=int, default=4096)
    parser.add_argument("--llm-timeout", type=float, default=120.0)
    parser.add_argument("--llm-max-retries", type=int, default=2)


def _map_step_from_args(args: argparse.Namespace):
    return create_map_step(
        map_mode=args.map_mode,
        llm_provider=args.llm_provider,
        llm_model=args.llm_model,
        llm_max_tokens=args.llm_max_tokens,
        llm_timeout=args.llm_timeout,
        llm_max_retries=args.llm_max_retries,
    )


def _parse_key_values(items: list[str]) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    for item in items:
        if "=" not in item:
            raise ValueError(f"expected KEY=VALUE, got {item!r}")
        key, value = item.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"expected non-empty key in {item!r}")
        parsed[key] = _parse_scalar(value.strip())
    return parsed


def _parse_scalar(value: str) -> Any:
    lower = value.lower()
    if lower == "true":
        return True
    if lower == "false":
        return False
    if lower in {"undetermined", "none", "null"}:
        return "undetermined"
    return value


def _parse_expected_values(items: list[str]) -> dict[str, str]:
    return {
        key: str(value).lower() if isinstance(value, bool) else str(value)
        for key, value in _parse_key_values(items).items()
    }


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
    if example == "fcra-dispute":
        return fcra_dispute_seed()
    if example == "uscis-n400":
        return load_policy_workspace_seed(
            Path(__file__).parent / "example_seeds" / "uscis_n400_selected.json"
        )
    raise ValueError(f"unknown template example {example!r}")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["main", "sample_seed", "template_seed"]
