"""Gemini adapter for the extract pattern.

Install: pip install google-genai
Auth: set GEMINI_API_KEY in environment.

Usage:
    from extract import extract, FieldSpec
    from adapters.gemini import GeminiClient

    client = GeminiClient(model="gemini-2.5-pro")
    results = extract(source, fields, client)
"""

from typing import Optional

from google import genai


class GeminiClient:
    """Adapter from Gemini's google-genai SDK to the pattern's LLMClient protocol.

    Available models include:
        gemini-2.5-pro       - highest quality, slowest, most expensive
        gemini-2.5-flash     - balanced (good default)
        gemini-2.5-flash-lite - cheapest, fastest
    """

    def __init__(
        self,
        model: str = "gemini-2.5-flash",
        client: Optional[genai.Client] = None,
    ):
        self.model = model
        self.client = client or genai.Client()

    def __call__(self, prompt: str) -> str:
        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
        )
        return response.text
