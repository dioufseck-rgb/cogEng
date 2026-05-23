# Extract pattern

Structured extraction from text according to a typed field specification.
One pattern in the project's working set of cognitive operations.

## What this is

The extract pattern operationalizes *direct retrieval* — pulling specified
values from source content where the values appear literally. It also
identifies relevant *evidence* in the source when direct retrieval fails
but the source contains content that bears on the field, so downstream
inference operations can do the computation the pattern itself does not.

Inference is out of scope for this pattern.

## Package contents

```
extract_pattern/
├── extract.py          # Pattern core: FieldSpec, Evidence, ExtractionResult, extract()
├── template.txt        # Prompt template
├── harness.py          # Light harness: five test cases, multi-substrate runner
├── README.md           # This file
└── adapters/
    ├── gemini.py
    ├── anthropic.py
    └── openai.py
```

The pattern itself is small. Operational concerns — validation beyond JSON
parsing, retry on failure, cost tracking, calibration measurement,
evaluation — belong in the harness layer or a larger evaluation framework.

## Setup

Pick a substrate. Install only what you'll use:

```bash
# Gemini
pip install google-genai
export GEMINI_API_KEY=...

# Claude
pip install anthropic
export ANTHROPIC_API_KEY=...

# OpenAI
pip install openai
export OPENAI_API_KEY=...
```

## Pattern usage

```python
from extract import FieldSpec, extract
from adapters.gemini import GeminiClient

fields = [
    FieldSpec(
        name="purchase_price",
        type="number",
        cardinality="single",
        description="Total purchase price.",
        units="USD",
    ),
]

client = GeminiClient(model="gemini-2.5-flash")
results = extract(source_text, fields, client)

for ext in results["purchase_price"]:
    print(ext.value, ext.attribution, ext.confidence)
    for ev in ext.evidence:
        print("  evidence:", ev.fact)
```

## Output contract

For each requested field, a list of `ExtractionResult` objects, each with:

- `value` — the extracted value (typed per the field spec), or `None` when
  the field could not be filled by direct retrieval.
- `attribution` — for non-null values, the source span that supports the
  value. For null values, a description of where the model searched.
- `confidence` — calibrated estimate of correctness, 0.0 to 1.0.
- `evidence` — list of `Evidence(fact, attribution)` items. Empty when
  direct retrieval succeeded. Populated when value is null but the source
  contains content a downstream inference operation could use.

Three behaviors per field:

1. **Direct retrieval succeeded.** value populated, evidence empty.
2. **Evidence-only.** value None, evidence contains relevant facts.
3. **Absent.** value None, evidence empty.

## Single-valued vs multi-valued

Each field's `cardinality` is `single` (one correct answer; multiple
results = competing candidates with confidences as probability mass) or
`multi` (multiple co-existing values; each confidence independent).

## Why evidence-only behavior

Strict direct-retrieval-only would mean any inferential field returns
just null with attribution. A downstream inference operation would then
have to re-read the source from scratch to find the inputs to its
computation. Evidence-only behavior makes extract a more useful primitive
in composed workflows: it does what it specializes in (locating and
returning content from source), stops where its specialty ends
(interpretation and computation), and produces a clean handoff to derive
or similar inference patterns.

For "effective tax rate" when the source contains pretax income and tax
expense but no stated rate:
- value: None
- evidence: [pretax income figure with attribution, tax expense with
  attribution]
- A downstream operation reading this can compute the rate.

For "year of birth" when the source says "in his 41 years of life" in a
2026-dated document:
- value: None  
- evidence: [the phrase establishing age, the document date]
- Downstream inference can compute 2026 - 41 = 1985.

The pattern stops at locating inputs; it does not perform the
computation.

## Light harness

`harness.py` runs the pattern through five test cases of increasing
difficulty, across one or more substrates, with cost/latency capture.

```bash
# Run all cases on Gemini
python harness.py --substrate gemini

# Run on multiple substrates
python harness.py --substrate gemini --substrate claude

# Run specific cases
python harness.py --substrate gemini --case 1 --case 3 --case 5

# Override default model
python harness.py --substrate claude --model claude-opus-4-7

# Write results to JSON
python harness.py --substrate gemini --output results.json
```

The nine cases:

1. **Floor check.** Short clean source, simple spec. Tests pattern works
   end-to-end.
2. **Cardinality and absence.** Multi-valued fields, fields not in
   source. Tests multi/single distinction and null-with-attribution.
3. **Distractor discrimination.** SEC income statement with multiple
   periods and segments. Tests period disambiguation.
4. **Signal degradation.** Same content as case 3 with OCR-like noise.
   Tests recognition robustness.
5. **Stress + evidence handoff.** Includes a field requiring inference
   (effective tax rate). Tests that the pattern returns evidence rather
   than fabricating the computed value.
6. **Genuine ambiguity.** Contract with amendment supersedes original
   price. Tests competing-probability-mass behavior for single-valued
   fields when source contains multiple candidates including
   revision-related ones.
7. **Enumerated domain and type-gated content.** Lease document with
   spec that includes a document-type enumeration plus fields that only
   apply to purchase agreements.
8. **Large schema with mixed behaviors.** Realistic enterprise extraction:
   18 fields spanning direct retrieval, multi-valued, evidence-only,
   absent, and enumerated.
9. **Merger agreement, multi-dimensional stress.** Substantial document
   (~1,200 words) combining many stress dimensions in one call: 23 fields,
   two amendments creating revision chains, multiple inferential fields,
   negated/categorical statements, enumerated constraints, structurally
   distant content, and a realistic combination of behaviors a production
   extraction call would face.

Results print to stdout for manual reading. Use `--output` to save JSON
for later inspection.

## Salvage

The harness applies known repairs to model responses before parsing
(controllable with `--no-salvage`). Current repairs:

- Strips non-contract keys some models inject between result objects
  and their enclosing array brackets (e.g., Gemini's `reasoning: "..."`).
- Removes trailing commas before closing brackets.

When salvage repairs are applied successfully, the harness reports them
above the results so it's visible the response was repaired rather than
clean.

Salvage lives in the harness, not the pattern. Substrate-specific
quirks accumulate here so the pattern stays clean.

## Pattern specification details

### Field specification

Each `FieldSpec` has:

- `name` (required)
- `type` (required): string, number, date, time, boolean, enumerated
- `cardinality` (required): single or multi
- `description` (required)
- `domain`: open (default) or enumerated
- `enumeration`: required when domain is enumerated
- `units`: for numeric fields
- `examples`: optional few-shot examples

### Calibration

Confidence values are calibrated estimates of correctness:

- 0.95-1.00: explicitly stated, unambiguous
- 0.80-0.94: clearly present, light interpretation
- 0.60-0.79: ambiguity, or strongest among competing candidates
- 0.40-0.59: real interpretation or inference involved
- Below 0.40: hypothesis

Whether the LLM actually produces calibrated confidence is a measurable
property and a primary evaluation concern.

### Canonicalization

Typed values are canonicalized: ISO 8601 for dates, decimal numbers
without currency symbols, etc. Free-text fields preserve source wording.
Attribution preserves source surface form regardless.

## Design decisions

**Substrate as injected dependency.** The pattern accepts any client
conforming to a minimal protocol rather than instantiating a specific
SDK.

**Evidence as separate output field.** When inference is needed, the
pattern returns evidence rather than performing inference or returning
opaque null. Keeps the pattern's scope clean while making composition
with downstream inference operations work.

**Attribution as substring rather than offset.** Easier for the LLM to
produce reliably, human-readable in output. Offsets can be derived by
string search if needed.

**Confidence as single number.** Simplest representation supporting the
consumer's primary use.

**Null with attribution rather than omission.** Distinguishes "processed
and not found" from "not processed."

**Cardinality declared on the field.** Determines confidence semantics
(competing vs co-existing).

**Minimal salvage in the pattern.** Strips markdown code fences (common
across models). Heavier salvage, retry, and error recovery belong in
larger evaluation infrastructure.

## What this is not

Not a production extraction library. LangExtract, Instructor, and
similar libraries are mature and appropriate for production use. This
pattern artifact exists as a clean reference implementation of the
methodology's specifications, scoped to be small enough to understand
fully.
