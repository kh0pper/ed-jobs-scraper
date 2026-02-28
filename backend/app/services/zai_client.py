"""Z.ai API client for AI-powered resume/cover letter generation.

Z.ai provides an OpenAI-compatible API endpoint for GLM models.
Sync-only — all consumers are Celery tasks or sync contexts.
"""

import logging
import time
from dataclasses import dataclass

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class AIResponse:
    """Response from Z.ai API."""
    content: str
    model: str
    usage: dict
    finish_reason: str


class ZAIClient:
    """Sync client for Z.ai API (OpenAI-compatible endpoint)."""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model_routine: str,
        model_complex: str,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model_routine = model_routine
        self.model_complex = model_complex

        self._client = httpx.Client(
            base_url=self.base_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(connect=10, read=120, write=10, pool=10),
        )

    def _request_with_retry(
        self,
        messages: list[dict],
        model: str,
        temperature: float,
        max_tokens: int,
        max_retries: int = 2,
    ) -> AIResponse:
        """Send completion request with retry on 5xx/timeout."""
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        last_error = None
        for attempt in range(max_retries + 1):
            try:
                response = self._client.post("/chat/completions", json=payload)
                response.raise_for_status()
                data = response.json()

                choice = data["choices"][0]
                return AIResponse(
                    content=choice["message"]["content"],
                    model=data.get("model", model),
                    usage=data.get("usage", {}),
                    finish_reason=choice.get("finish_reason", "unknown"),
                )

            except (httpx.HTTPStatusError, httpx.TimeoutException) as e:
                last_error = e
                # Don't retry on 4xx
                if isinstance(e, httpx.HTTPStatusError) and e.response.status_code < 500:
                    raise

                if attempt < max_retries:
                    delay = 2 ** (attempt + 1)  # 2s, 4s
                    logger.warning(
                        "Z.ai request failed (attempt %d/%d), retrying in %ds: %s",
                        attempt + 1, max_retries + 1, delay, e,
                    )
                    time.sleep(delay)
                else:
                    logger.error("Z.ai request failed after %d attempts: %s", max_retries + 1, e)
                    raise

        raise RuntimeError("All retry attempts exhausted")  # Should never reach here

    def complete(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> AIResponse:
        """Completion with routine model (glm-4.5v)."""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        return self._request_with_retry(
            messages=messages,
            model=self.model_routine,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def complete_complex(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 8192,
    ) -> AIResponse:
        """Completion with complex model (glm-4.7)."""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        return self._request_with_retry(
            messages=messages,
            model=self.model_complex,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def close(self):
        self._client.close()


_client: ZAIClient | None = None


def get_zai_client() -> ZAIClient:
    """Get or create singleton Z.ai client from settings."""
    global _client
    if _client is not None:
        return _client

    settings = get_settings()
    if not settings.zai_api_key:
        raise RuntimeError("ZAI_API_KEY not configured")

    _client = ZAIClient(
        api_key=settings.zai_api_key,
        base_url=settings.zai_base_url,
        model_routine=settings.zai_model_routine,
        model_complex=settings.zai_model_complex,
    )
    return _client
