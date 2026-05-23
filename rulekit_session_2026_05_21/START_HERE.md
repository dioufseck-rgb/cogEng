# START HERE — Tomorrow's instructions

Last updated: 2026-05-22, early hours (continued work session).

## What was added in the late-session continuation

After packaging, we started the tree-builder pipeline. Substage A1 (atom
extraction) is now implemented in `rulekit/builder.py` and tested
against PA Section 2. See `test_a1.py` and the audit file `a1_audit.json`.

The substage produces atomic propositions from policy source text under
the reasonable-reader voice, with a mechanical atomicity check that
flags any atoms containing logical connectives. The check is doing real
work — on the PA test run it flagged four atoms that hid connectives
(including one that the hand-built reference also missed). The flagged
atoms route back for a revision pass in production (not yet implemented).

## What to do first

1. Unzip `rulekit_session_2026_05_21.zip` somewhere on your machine.
2. Open a terminal in the unzipped directory.
3. Verify the build still works:

   ```bash
   python smoke_test.py
   python run_cases.py
   python test_a1.py   # the substage A1 test
   ```

   All three should produce output without errors. `test_a1.py` runs in
   offline mode using a pre-generated response stored in
   `test_data/a1_response_pa_section2.json`. To run with a live API call
   instead, set the `ANTHROPIC_API_KEY` environment variable and remove
   the `offline_response` argument from `run_a1` in `test_a1.py`.

4. If you want to develop against the library:

   ```bash
   pip install -e .
   ```

## What to read first

Read in this order:

1. `README.md` — orientation, what's in the package, what each piece does.
2. `evaluation_output.txt` — see the engine working on real cases.
3. `a1_audit.json` — see the substage A1 builder working on PA Section 2.
   The audit captures the full prompt, the LLM response, and the
   extracted atoms with atomicity flags.
4. `SESSION_HANDOFF_2026-05-21.md` — full architectural detail.

## What to do next, by energy level

**Low energy (30 minutes).** Read the README and skim the evaluation
output and the A1 audit. Get the package re-loaded into your head.

**Medium energy (1-2 hours).** Implement the A1 revision pass — when
atomicity flags fire, route the flagged atoms back to a second LLM
call asking for proper splits. The infrastructure is ready; just need
the prompt for revision plus the loop logic.

Alternatively: implement substage A2 (determination extraction) as a
parallel call to A1, following the same pattern. The handoff describes
the design.

**High energy (a session).** Implement the cross-validation substage B
(coverage checks between A1 and A2's outputs) plus the association
substage C (relationship metadata between atoms and determinations).
This completes the decomposition stage of the pipeline.

## What to do later (not tomorrow)

- Implement refinement (the second stage after decomposition).
- Implement composition (the third stage).
- Implement schema-building (the fourth stage).
- Connect all four stages into a pipeline that takes policy text in and
  produces a complete tree out.
- Implement the `reason` primitive (constraint-solver queries via Z3
  Optimize).
- Implement the `plan` primitive (state-action planning trees).
- Add a third policy that exercises a different drafting culture.
- Confirm `rulekit` is available on PyPI before any public release.
- Run the employment agreement / IP review before any public release.

## What to NOT do

- Don't try to implement the whole builder pipeline in one session.
  It's substantial work that benefits from staged effort.
- Don't add new operators to the engine. The vocabulary is
  AT-LEAST-N + NOT, verified closed under negation via De Morgan.
- Don't add solver dependencies to the core. SMT (Z3) is for the
  optional reasoning module, not the engine.

## How to remember where you are

The handoff document is the canonical state of the design. If anything
in the package surprises you, the handoff explains why it's that way.

The README is the canonical orientation. If you forget what's in the
package, the README tells you.

The evaluation output and the A1 audit are the canonical proof that the
engine and the first builder substage work.

## A small honest note

You did substantial work over a long session. The architecture is in
good shape. The code is small but principled. The handoff is
comprehensive. The first builder substage is now operational. Take
tomorrow at your own pace; nothing is so urgent that it can't wait
for you to be ready.

The work will be here when you are.

