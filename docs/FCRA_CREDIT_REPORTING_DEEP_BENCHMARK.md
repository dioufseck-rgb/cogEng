# FCRA Credit Reporting Deep Benchmark

Status: initial deterministic benchmark fixture

This benchmark is a realistic credit-reporting dispute policy bundle for
testing whether RuleKit separates from direct LLM disposition as policy depth
increases. It is not legal advice and is not a complete FCRA compliance
program.

## Source Scope

The seed models selected public-law duties from:

- 15 U.S.C. 1681i, Procedure in case of disputed accuracy:
  https://uscode.house.gov/view.xhtml?req=(title:15%20section:1681i%20edition:prelim)
- 15 U.S.C. 1681s-2, Responsibilities of furnishers:
  https://uscode.house.gov/view.xhtml?edition=prelim&num=0&req=granuleid:USC-prelim-title15-section1681s-2
- 12 CFR 1022.43, Regulation V direct disputes:
  https://www.consumerfinance.gov/rules-policy/regulations/1022/43/
- CFPB Circular 2022-07 on reasonable investigation and forwarding relevant
  primary evidence:
  https://www.consumerfinance.gov/compliance/circulars/consumer-financial-protection-circular-2022-07-reasonable-investigation-of-consumer-reporting-disputes/

## Artifact

Seed:

```text
rulekit/orchestrator/example_seeds/fcra_credit_reporting_dispute_deep.yaml
```

CLI template name:

```text
fcra-credit-reporting-deep
```

Current shape:

```text
atoms: 120
nodes: 169
determinations: 15
cases: 11
deterministic dispositions: 165
expected-outcome replay: 165/165
```

## Determination Families

The benchmark covers:

- CRA reinvestigation trigger validity.
- Frivolous or irrelevant dispute termination.
- CRA reinvestigation requirement and timeliness.
- CRA notice to furnisher and forwarding of all relevant information.
- CRA consideration of consumer primary-source evidence.
- Treatment of inaccurate, incomplete, or unverifiable information.
- Results-notice content and timing.
- Reinsertion certification and notice safeguards.
- Furnisher duties after CRA notice.
- Furnisher direct-dispute duties under Regulation V.
- Reseller forwarding/correction duties.
- Consumer statement handling.
- Human-review routing triggers.

## Stress Cases

The case suite includes:

- Clean verified auto-loan dispute.
- Bank statement/settlement evidence not forwarded to furnisher.
- Late CRA reinvestigation with no extension.
- 45-day extension with corrected date-of-first-delinquency reporting.
- Unverifiable collection account left reporting.
- Valid frivolous termination for missing account identity.
- Invalid duplicate-dispute termination despite new documents.
- Reinsertion without furnisher certification or notice.
- Direct furnisher dispute found inaccurate but CRAs not corrected.
- Reseller forwarding path.
- Mixed-file and identity-theft ambiguity with unresolved source gaps.

## Why This Is The Right Next Benchmark

This domain stresses the parts of RuleKit that should matter in production:

- Multiple institutional actors with different obligations.
- Deadline arithmetic and conditional extensions.
- Source-scope semantics for missing and forwarded evidence.
- Primary-document handling versus generic dispute coding.
- Defect treatment after inaccurate, incomplete, or unverifiable findings.
- Routing logic that is distinct from substantive compliance.
- Deep cross-cutting facts where direct LLMs may overgeneralize from one issue
  to another.

The next experiment should run the same 11 cases through:

```text
direct terse
direct governed
RuleKit single-map + engine
RuleKit pruned/repair + engine
```

The key metrics should be accuracy, false-compliance overclaims, false
noncompliance overclaims, human-review misuse, cost, latency, and trace
completeness.
