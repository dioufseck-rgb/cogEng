param(
    [string] $OutputDir = "audits\tier1_slice_batch_cross_provider_local",
    [string] $KeysFile = "$HOME\.rulekit\llm_keys.ps1",
    [string] $Python = "python",
    [switch] $SingleMapCall,
    [int] $MaxTokens = 4096,
    [switch] $SkipPull,
    [string[]] $Models = @(
        "anthropic:claude-opus-4-7",
        "openai:gpt-5",
        "gemini:gemini-2.5-pro"
    )
)

$ErrorActionPreference = "Stop"

function Require-Key {
    param([string] $Name, [string] $Provider)
    if (-not [Environment]::GetEnvironmentVariable($Name)) {
        throw "Missing $Name for requested provider '$Provider'. Set it in the shell or in $KeysFile."
    }
}

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

if (-not $SkipPull) {
    git pull
}

if (Test-Path $KeysFile) {
    . $KeysFile
}

if ($env:GEMINI_API_KEY -and -not $env:GOOGLE_API_KEY) {
    $env:GOOGLE_API_KEY = $env:GEMINI_API_KEY
}

$env:PYTHONUTF8 = "1"
$env:PYTHONPATH = $RepoRoot

foreach ($Model in $Models) {
    $Provider = $Model.Split(":")[0]
    if ($Provider -eq "anthropic") { Require-Key "ANTHROPIC_API_KEY" $Provider }
    if ($Provider -eq "openai") { Require-Key "OPENAI_API_KEY" $Provider }
    if ($Provider -eq "gemini") { Require-Key "GOOGLE_API_KEY" $Provider }
}

$ProgramPath = "build\uscis_n400_tier1_bundle\program.json"
$BuildProgram = @'
import json
from pathlib import Path
from pydantic_core import to_jsonable_python
from rulekit.orchestrator.config import load_policy_workspace_seed
from rulekit.orchestrator.factory import create_candidate_program

seed = load_policy_workspace_seed(
    Path("rulekit/orchestrator/example_seeds/uscis_n400_selected.json")
)
program = create_candidate_program(
    program_id="prog_uscis_n400",
    program_name=seed.workspace_name,
    version=seed.version_label or "0.1",
    determinations=seed.determinations,
    atoms=seed.atoms,
    nodes=seed.nodes,
    constants=seed.constants,
)
out = Path("build/uscis_n400_tier1_bundle/program.json")
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(
    json.dumps(to_jsonable_python(program), indent=2, sort_keys=True),
    encoding="utf-8",
)
print(out)
'@

$BuildProgram | & $Python -

$ArgsList = @(
    "-m", "rulekit.orchestrator.cli", "map-eval",
    "--program", $ProgramPath,
    "--cases", "rulekit\orchestrator\example_cases\uscis_n400_tier1_broad_evidence_packets.json",
    "--out", $OutputDir,
    "--price", "anthropic:claude-opus-4-7=15,75",
    "--price", "openai:gpt-5=1.25,10",
    "--price", "gemini:gemini-2.5-pro=1.25,10",
    "--atom-scope", "determination-slice",
    "--batch-size", "8",
    "--determination", "n400.continuous_residence_satisfied",
    "--determination", "n400.physical_presence_satisfied",
    "--determination", "n400.state_residence_satisfied",
    "--determination", "n400.english_requirement_satisfied",
    "--determination", "n400.civics_requirement_satisfied",
    "--determination", "n400.oath_attachment_satisfied",
    "--determination", "n400.good_moral_character_satisfied",
    "--determination", "n400.human_review_required",
    "--llm-timeout", "240",
    "--llm-max-retries", "2",
    "--llm-max-tokens", "$MaxTokens",
    "--json"
)

if ($SingleMapCall) {
    $ArgsList += @("--single-map-call")
}

foreach ($Model in $Models) {
    $ArgsList += @("--model", $Model)
}

& $Python $ArgsList

Write-Host ""
Write-Host "Multi-provider audit written to: $OutputDir"
Write-Host "Aggregate summary: $OutputDir\summary.json"
