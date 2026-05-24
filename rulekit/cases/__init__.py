"""
rulekit.cases — case-shape adapters for the run-time pipeline.

Each adapter converts an institution's native case format (e.g. a
RuleArena JSON file, a SaaS ticketing export, a structured form
submission) into the shape Map and the case runner expect:

    AdaptedCase(
        case_id: str,
        description: str,           # narrative evidence for Map
        ground_truth: Optional[...] # if available (for measurement)
        metadata: dict[str, Any],   # provenance, original case, etc.
    )

The library ships with adapters for benchmark formats (RuleArena).
Institutions wanting to adjudicate their own cases either:
  - use one of the shipped adapters if their format matches
  - write a small adapter following the same shape
  - bypass adapters and produce AdaptedCase instances directly

The adapter layer is the only part of the run-time pipeline that
necessarily sees case-format details. The case runner downstream
operates on AdaptedCase, agnostic to where the case came from.
"""
