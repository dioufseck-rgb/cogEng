"""Anthropic Claude adapter for the extract pattern.

Install: pip install anthropic
Auth: set ANTHROPIC_API_KEY in environment.

Usage:
    from extract import extract, FieldSpec
    from adapters.anthropic import ClaudeClient

    client = ClaudeClient(model="claude-opus-4-7")
    results = extract(source, fields, client)
"""

from typing import Optional

import anthropic


class ClaudeClient:
    """Adapter from the Anthropic SDK to the pattern's LLMClient protocol.

    Common models:
        claude-opus-4-7        - frontier, highest quality
        claude-opus-4-6        - prior-generation frontier
        claude-sonnet-4-6      - mid-tier, balanced
        claude-haiku-4-5       - small/fast tier
    """

    def __init__(
        self,
        model: str = "claude-sonnet-4-6",
        max_tokens: int = 8192,
        client: Optional[anthropic.Anthropic] = None,
    ):
        self.model = model
        self.max_tokens = max_tokens
        self.client = client or anthropic.Anthropic()

    def __call__(self, prompt: str) -> str:
        response = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text
