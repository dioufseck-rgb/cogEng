# Case PA-2026-V1-001 — Construction Narrative

## Slot in the distribution

- **Disposition class:** `uphold`
- **Stability expectation:** unambiguous
- **Position in the set:** 1 of 24 (first of 7 uphold cases)

This is the canonical case template. It establishes the format and the
quality bar. As an unambiguous uphold case, it tests the engine's most
safety-critical capability: confidently declining to overturn a case where
the plan's denial is correct on its merits and procedurally sound.

## Clinical scenario

A 52-year-old patient with chronic neck and bilateral shoulder pain for
approximately 18 months, presenting to an outpatient orthopedic surgery
practice with a request for single-level ACDF at C5-C6.

The clinical picture is one of axial neck pain with bilateral shoulder
girdle involvement, not radiculopathy. The patient describes pain that is
aching, worse with prolonged sitting and computer work, with no shooting
component into specific arm dermatomes, no significant numbness, and no
weakness. Physical exam shows preserved reflexes, normal strength, and no
focal sensory deficit. Provocative maneuvers (Spurling's test, shoulder
abduction relief) are negative.

MRI shows mild multilevel cervical spondylosis: C5-C6 disc desiccation with
a small posterior disc bulge, no significant central or foraminal stenosis,
no nerve root impingement. Imaging report explicitly notes "no evidence of
significant neural compromise."

Conservative treatment to date has been limited. The patient has had two
months of intermittent NSAID use (ibuprofen) and one episode of 4 weeks
of physical therapy approximately 8 months ago, with documented improvement
that the patient discontinued when work resumed. No structured
pharmacotherapy with the agent classes typical for cervical pain. No
interventional procedures.

The denying physician at the plan reviewed the case and produced a denial
letter citing CC-SPINE-2024 § 2.1 (no documented radiculopathy) and § 2.2
(conservative treatment requirements not met). The letter is procedurally
adequate — it specifies the criteria, explains the clinical reasoning
section by section, and includes the full IMR rights notice in standard
language.

## Why this is an unambiguous uphold

A careful policy review finds:

- **Diagnosis requirement (§ 2.1):** Not met. The case is axial neck pain
  with shoulder girdle component, not radiculopathy. No dermatomal
  symptoms, no neurological deficits, no imaging-correlated nerve
  compromise.
- **Conservative treatment requirement (§ 2.2):** Not met. PT was 4 weeks
  not 6, and was 8 months ago with the patient choosing to discontinue.
  No pharmacotherapy trial of multiple agent classes. No interventional
  procedures attempted or waived.
- **Imaging (§ 2.3):** Not supportive. MRI shows mild spondylosis without
  structural pathology to correlate with surgery.
- **Clinical standard (AANS/CNS / NASS):** TIER_3. Surgery for chronic
  axial neck pain without radiculopathy is not endorsed by current
  guidelines as a first-line intervention.
- **No regulatory carve-out applies:** No documented contraindication to
  PT, no functional plateau (patient improved with the PT she did, then
  stopped), no progressive structural pathology.
- **Denial is procedurally adequate:** Cites criteria, explains reasoning,
  includes IMR rights.

A clinical reviewer or compliance officer reading this case would not
disagree about the disposition. The denial is correct on its merits, and
nothing in the procedural posture suggests overturn is warranted.

## What's typical about this case

This case represents a common ACDF appeal pattern: a patient with chronic
neck pain seeking surgical relief, where the underlying clinical picture
is axial pain rather than true radiculopathy, and where conservative
treatment has been incomplete. The plan correctly identifies that the
case doesn't meet criteria, and the appeal should fail on substantive
grounds.

## What might be expected to be challenging for the engine

A few features worth flagging for the expert assessment and the leaf
expectations:

- The exclusion check `exclusion_3_1_axial_pain_only` should fire (the case
  is exactly an axial-pain-only presentation). The substrate should commit
  on this with high confidence.
- The conservative treatment leaf has multiple non-compliant elements (PT
  duration short, no pharmacotherapy, no interventional). Each should
  resolve cleanly to False.
- No interpretive judgment calls are expected — this is a clear case.
- The substrate should produce a clean trace with no escalations and
  route AUTO.

If the engine routes anything other than AUTO with no escalations, that's
either a calibration issue on the leaf prompts or a finding worth
investigating.

## Plausible documentation patterns

- Denial letter: full text including § 1374.31(b) compliance language
- PCP referral and intake notes
- Orthopedic surgery consultation with H&P
- PT discharge summary from 8 months prior
- MRI report from 3 months prior
- Pharmacy fill history showing intermittent NSAID use
- Member appeal letter requesting reconsideration

## Constructed identifiers

- Patient name: Margaret Williams (fictional, no resemblance to real
  individuals)
- Member ID: M-4471829
- Treating physician: Dr. Elena Rodriguez, orthopedic surgery
- Denial reviewer: Dr. Thomas Andrews, the plan's medical director
- Case ID: PA-2026-V1-001
- Plan: Pacific Western Health Plan (fictional)
