# Map Governance Eval Output

Use this directory for live multi-provider governed Map runs. The committed
README keeps the report location in the repo; generated run artifacts are JSON
and text files written by `rulekit-orchestrator map-eval`.

Recommended run:

```powershell
rulekit-orchestrator map-eval `
  --program build/map_governance_uscis/program.json `
  --cases rulekit/orchestrator/example_cases/uscis_n400_gmc_evidence_packets.json `
  --model anthropic:claude-opus-4-7 `
  --model openai:gpt-5 `
  --model gemini:gemini-2.5-pro `
  --determination n400.good_moral_character_satisfied `
  --determination n400.human_review_required `
  --atom n400.aggravated_felony_after_1990 `
  --atom n400.murder_conviction `
  --atom n400.pending_criminal_charge `
  --atom n400.false_testimony_for_immigration_benefit `
  --out audits/map_governance_eval/live_n400_gmc `
  --json
```

The live run will create `summary.json`, per-model result files, raw prompts,
raw model responses, parsed bindings, validation reports, and dispositions.
