"""
debug_prefill.py — test whether assistant-prefill of '{' suppresses reasoning.

If the API responds with continuation of '{ ... }' instead of reasoning,
that's a free 50-90% cost reduction on Map calls.
"""
import os, sys
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

import anthropic

PROMPT = """For each atom_id below, decide whether the case description supports the claim as TRUE, FALSE, or UNDETERMINED.

CASE: Player A is a 28-year-old NBA player with 5 years of service. Signed a 4-year contract at $35M/year.

ATOMS:
  a001: The player has completed at least 7 Years of Service.
  a002: The player signed a 4-year contract.
  a003: The contract was signed during a Moratorium Period.

Reply with ONLY a JSON object mapping each atom_id to "true", "false", or "undetermined"."""

client = anthropic.Anthropic()

print("=" * 70)
print("TEST 1: No prefill (current behavior)")
print("=" * 70)
r1 = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=4096,
    messages=[{"role": "user", "content": PROMPT}],
)
text1 = r1.content[0].text
print(f"Length: {len(text1)} chars")
print(f"First 300:")
print(text1[:300])

print()
print("=" * 70)
print("TEST 2: WITH assistant prefill of '{'")
print("=" * 70)
r2 = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=4096,
    messages=[
        {"role": "user", "content": PROMPT},
        {"role": "assistant", "content": "{"},
    ],
)
text2 = r2.content[0].text
print(f"Length: {len(text2)} chars")
print(f"First 300:")
print(text2[:300])
print()
print(f"Reconstructed JSON (with leading '{{'):")
reconstructed = "{" + text2
print(reconstructed[:300])

import json
try:
    parsed = json.loads(reconstructed)
    print(f"\nParsed successfully: {parsed}")
except Exception as e:
    print(f"\nParse error: {e}")

# Token comparison
print()
print(f"COST: Test 1 generates ~{len(text1)//4} output tokens; Test 2 ~{len(text2)//4}")
print(f"Savings if prefill works: {100*(1 - len(text2)/len(text1)):.0f}%")
