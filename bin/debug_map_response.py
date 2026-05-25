"""
debug_map_response.py — see what Map's LLM call actually returns.

Sends a real Map BIND_PROMPT and prints the raw response, so we can see
why JSON parse is failing.
"""
import os, sys
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

from rulekit.build.decomposer import LLMCaller

# Build a minimal Map-style prompt manually (same shape as BIND_PROMPT)
prompt = """You are evaluating whether each Boolean atom holds, based on a case description.

For each atom_id below, decide based on the case description whether the statement is TRUE, FALSE, or UNDETERMINED.

Output a JSON object mapping each atom_id to one of those three strings. Output ONLY the JSON object — no preamble, no markdown.

CASE DESCRIPTION
================
Player A is a 28-year-old NBA player who has completed 5 Years of Service. He signed a 4-year contract with Team A for an annual salary of $35 million.

ATOMS TO EVALUATE
=================
  a001: The player has completed at least 7 Years of Service.

OUTPUT
======
A JSON object like: {"a001": "FALSE"}
"""

print("=" * 70)
print("Testing claude-sonnet-4-6")
print("=" * 70)
llm = LLMCaller(model="claude-sonnet-4-6")
try:
    raw = llm.call("test", prompt)
    print(f"Type: {type(raw).__name__}")
    print(f"Length: {len(raw) if raw else 0}")
    print(f"Repr (first 500 chars):")
    print(repr(raw[:500]) if raw else "(empty)")
    print()
    print(f"As-displayed (first 500 chars):")
    print(raw[:500] if raw else "(empty)")
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}")

print()
print("=" * 70)
print("Inspecting raw response.content list directly")
print("=" * 70)
import anthropic
client = anthropic.Anthropic()
response = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=4096,
    messages=[{"role": "user", "content": prompt}],
)
print(f"response.content has {len(response.content)} block(s)")
for i, block in enumerate(response.content):
    print(f"  [{i}] type: {type(block).__name__}")
    print(f"      attrs: {[a for a in dir(block) if not a.startswith('_')]}")
    if hasattr(block, "text"):
        print(f"      text (first 300): {repr(block.text[:300])}")
    if hasattr(block, "thinking"):
        print(f"      thinking (first 300): {repr(block.thinking[:300])}")
