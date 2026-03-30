"""Auxiliary LLM client for side tasks (summarization, title generation, classification).

Provides a lightweight async wrapper around OpenAI-compatible chat completion
endpoints using httpx.AsyncClient. No external deps beyond httpx.

Inspired by hermes-agent's auxiliary_client.py but simplified for ultrabot's
architecture: single-class, async-first, configurable base URL.
"""

import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# Default OpenAI-compatible endpoint
_DEFAULT_BASE_URL = "https://api.openai.com/v1"


class AuxiliaryClient:
    """Async client for auxiliary LLM tasks via OpenAI-compatible endpoints.

    Parameters
    ----------
    provider : str
        Human-readable provider name (e.g. "openai", "openrouter").
    model : str
        Model identifier (e.g. "gpt-4o-mini", "google/gemini-flash").
    api_key : str
        Bearer token for the API.
    base_url : str, optional
        Base URL for the OpenAI-compatible endpoint.
        Defaults to ``https://api.openai.com/v1``.
    timeout : float, optional
        Request timeout in seconds. Defaults to 30.
    """

    def __init__(
        self,
        provider: str,
        model: str,
        api_key: str,
        base_url: Optional[str] = None,
        timeout: float = 30.0,
    ) -> None:
        self.provider = provider
        self.model = model
        self.api_key = api_key
        self.base_url = (base_url or _DEFAULT_BASE_URL).rstrip("/")
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_client(self) -> httpx.AsyncClient:
        """Lazy-init the underlying httpx client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=self.timeout,
            )
        return self._client

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # Core completion
    # ------------------------------------------------------------------

    async def complete(
        self,
        messages: list[dict],
        max_tokens: int = 512,
        temperature: float = 0.3,
    ) -> str:
        """Send a chat completion request and return the assistant's text.

        Returns an empty string on any failure (network, API, parsing).
        """
        if not messages:
            return ""

        client = self._get_client()
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        try:
            response = await client.post("/chat/completions", json=payload)
            response.raise_for_status()
            data = response.json()
            choices = data.get("choices", [])
            if not choices:
                return ""
            content = choices[0].get("message", {}).get("content", "")
            return (content or "").strip()
        except Exception as exc:
            logger.debug("AuxiliaryClient.complete failed: %s", exc)
            return ""

    # ------------------------------------------------------------------
    # Convenience methods
    # ------------------------------------------------------------------

    async def summarize(self, text: str, max_tokens: int = 256) -> str:
        """Summarize the given text into a concise paragraph."""
        if not text:
            return ""
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a concise summarizer. Produce a clear, factual "
                    "summary of the provided text. Include key details and "
                    "action items. Be brief."
                ),
            },
            {"role": "user", "content": text},
        ]
        return await self.complete(messages, max_tokens=max_tokens, temperature=0.3)

    async def generate_title(self, messages: list[dict], max_tokens: int = 32) -> str:
        """Generate a short descriptive title for a conversation.

        Parameters
        ----------
        messages : list[dict]
            Conversation messages (typically the first few exchanges).
        max_tokens : int
            Max tokens for the title response.
        """
        if not messages:
            return ""

        # Build a snippet from the messages for the title prompt
        snippet_parts: list[str] = []
        for msg in messages[:4]:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if content:
                snippet_parts.append(f"{role}: {content[:200]}")
        snippet = "\n".join(snippet_parts)

        title_messages = [
            {
                "role": "system",
                "content": (
                    "Generate a short, descriptive title (3-7 words) for this "
                    "conversation. Return ONLY the title text. No quotes, no "
                    "punctuation at the end, no prefixes."
                ),
            },
            {"role": "user", "content": snippet},
        ]
        return await self.complete(title_messages, max_tokens=max_tokens, temperature=0.3)

    async def classify(self, text: str, categories: list[str]) -> str:
        """Classify text into one of the given categories.

        Returns the best-matching category name, or empty string on failure.
        """
        if not text or not categories:
            return ""

        cats_str = ", ".join(categories)
        messages = [
            {
                "role": "system",
                "content": (
                    f"Classify the following text into exactly one of these "
                    f"categories: {cats_str}. Respond with ONLY the category "
                    f"name, nothing else."
                ),
            },
            {"role": "user", "content": text},
        ]
        result = await self.complete(messages, max_tokens=20, temperature=0.1)

        # Normalize: try to match result to one of the canonical categories
        result_lower = result.strip().lower()
        for cat in categories:
            if cat.lower() == result_lower:
                return cat
        # Partial / fuzzy match: if the result contains a category name
        for cat in categories:
            if cat.lower() in result_lower:
                return cat
        # Return raw result if no exact match (caller can handle)
        return result
