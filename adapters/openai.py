"""OpenAI adapter for the extract pattern.

Install: pip install openai
Auth: set OPENAI_API_KEY in environment.

Usage:
    from extract import extract, FieldSpec
    from adapters.openai import OpenAIClient

    client = OpenAIClient(model="gpt-4o")
    results = extract(source, fields, client)
"""

from typing import Optional

from openai import OpenAI


class OpenAIClient:
    """Adapter from the OpenAI SDK to the pattern's LLMClient protocol."""

    def __init__(
        self,
        model: str = "gpt-4o",
        client: Optional[OpenAI] = None,
    ):
        self.model = model
        self.client = client or OpenAI()

    def __call__(self, prompt: str) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content
