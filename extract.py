"""
Extract pattern: structured extraction from text per a typed specification.

This is the pattern artifact in the project's three-layer architecture:
- Preprocessing utilities (separate) produce the source text.
- This pattern operationalizes the cognitive operation of extraction.
- The harness (separate) handles validation, retry, calibration measurement, etc.

The pattern is substrate-agnostic. It defines what it needs from an LLM
(a callable that takes a prompt and returns a text response) and accepts
any implementation. Reference adapters for Gemini, Claude, and OpenAI are
provided in the adapters/ directory.

The pattern performs direct retrieval. When a value is not directly
retrievable, the pattern returns null with relevant evidence the source
contains, so a downstream inference operation can do the computation.
Inference is out of scope for this pattern.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Optional, Literal, Any, Protocol
from pathlib import Path


# -- Configuration input format ---------------------------------------------

FieldType = Literal["string", "number", "date", "time", "boolean", "enumerated"]
Cardinality = Literal["single", "multi"]
Domain = Literal["open", "enumerated"]


@dataclass
class FieldSpec:
    """Specification of one field to extract."""
    name: str
    type: FieldType
    cardinality: Cardinality
    description: str
    domain: Domain = "open"
    enumeration: Optional[list[str]] = None
    units: Optional[str] = None
    examples: Optional[list[str]] = None

    def to_dict(self) -> dict[str, Any]:
        d = {
            "name": self.name,
            "type": self.type,
            "cardinality": self.cardinality,
            "description": self.description,
            "domain": self.domain,
        }
        if self.enumeration is not None:
            d["enumeration"] = self.enumeration
        if self.units is not None:
            d["units"] = self.units
        if self.examples is not None:
            d["examples"] = self.examples
        return d


@dataclass
class Evidence:
    """One piece of evidence supporting (or relevant to) a field.

    Populated when direct retrieval fails but the source contains content
    that bears on the field. A downstream inference operation can consume
    evidence to produce values the pattern itself doesn't compute.
    """
    fact: str
    attribution: str


@dataclass
class ExtractionResult:
    """One result for one field.

    Three behaviors:

    1. Direct retrieval: value is populated, evidence is empty.
    2. Evidence-only: value is None, evidence contains relevant facts
       a downstream inference step would need.
    3. Absent: value is None, evidence is empty.

    For single-valued fields, multiple ExtractionResults in a list represent
    competing candidates. For multi-valued fields, they represent co-existing
    values.
    """
    value: Any  # None when not directly retrievable
    attribution: str
    confidence: float
    evidence: list[Evidence] = field(default_factory=list)


class ExtractParseError(Exception):
    """Raised when the LLM response cannot be parsed.

    Carries the raw response text so the caller (harness) can inspect what
    the model actually produced. Without this, debugging parse failures
    requires re-running with manual logging.
    """
    def __init__(self, message: str, raw_response: str, original: Exception):
        super().__init__(message)
        self.raw_response = raw_response
        self.original = original


# -- Substrate interface ----------------------------------------------------

class LLMClient(Protocol):
    """The minimal interface the pattern requires from an LLM substrate.

    Any object with a __call__ method that takes a prompt string and returns
    a response string satisfies this protocol.
    """

    def __call__(self, prompt: str) -> str:
        """Send the prompt to the LLM, return the text response."""
        ...


# -- The pattern's core logic -----------------------------------------------

TEMPLATE_PATH = Path(__file__).parent / "template.txt"


def load_template() -> str:
    """Load the prompt template from disk."""
    return TEMPLATE_PATH.read_text()


def build_prompt(source: str, fields: list[FieldSpec]) -> str:
    """Merge the template with the source and specification."""
    template = load_template()
    spec_json = json.dumps([f.to_dict() for f in fields], indent=2)
    prompt = template.replace("{{source}}", source).replace(
        "{{specification}}", spec_json
    )
    return prompt


def _strip_code_fence(text: str) -> str:
    """Remove markdown code fences if the model wrapped JSON in them.

    Minimal salvage logic kept in the pattern because some models
    consistently emit fences regardless of prompt instructions.
    """
    text = text.strip()
    fence_pattern = r"^```(?:json)?\s*\n?(.*?)\n?```$"
    match = re.match(fence_pattern, text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text


def parse_response(response_text: str) -> dict[str, list[ExtractionResult]]:
    """Parse the LLM's JSON response into structured ExtractionResults.

    Raises ExtractParseError carrying the raw response when parsing fails,
    so callers can inspect what the model actually produced.
    """
    cleaned = _strip_code_fence(response_text)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ExtractParseError(
            f"Response is not valid JSON: {e}",
            raw_response=response_text,
            original=e,
        )

    out: dict[str, list[ExtractionResult]] = {}
    try:
        for field_name, results in parsed.items():
            out[field_name] = []
            for r in results:
                evidence_list = []
                for e in r.get("evidence", []) or []:
                    evidence_list.append(Evidence(
                        fact=e.get("fact", ""),
                        attribution=e.get("attribution", ""),
                    ))
                out[field_name].append(ExtractionResult(
                    value=r.get("value"),
                    attribution=r.get("attribution", ""),
                    confidence=float(r.get("confidence", 0.0)),
                    evidence=evidence_list,
                ))
    except (AttributeError, TypeError, ValueError) as e:
        raise ExtractParseError(
            f"Response JSON is valid but does not match expected structure: {e}",
            raw_response=response_text,
            original=e,
        )

    return out


def extract(
    source: str,
    fields: list[FieldSpec],
    client: LLMClient,
) -> dict[str, list[ExtractionResult]]:
    """Run extraction on a source document.

    Args:
        source: The text to extract from.
        fields: The specification of fields to extract.
        client: Any object satisfying the LLMClient protocol.

    Returns:
        Dictionary mapping field name to list of ExtractionResults.

    Raises:
        ExtractParseError: If the response is not valid JSON or has the
            wrong structure. Carries the raw response for inspection.
        Exceptions from the underlying LLM client: For API failures.
    """
    prompt = build_prompt(source, fields)
    response_text = client(prompt)
    return parse_response(response_text)


def extract_raw(
    source: str,
    fields: list[FieldSpec],
    client: LLMClient,
) -> tuple[str, dict[str, list[ExtractionResult]]]:
    """Run extraction and also return the raw response.

    Useful for harness contexts where you want to capture the raw text
    regardless of whether parsing succeeds. If parsing fails, raises
    ExtractParseError with the raw response attached.

    Returns:
        Tuple of (raw_response_text, parsed_results).
    """
    prompt = build_prompt(source, fields)
    response_text = client(prompt)
    parsed = parse_response(response_text)
    return response_text, parsed
