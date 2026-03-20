"""Thin wrapper around the Anthropic SDK for the Arxiv Intelligence System.

Provides:
- ``ClaudeClient`` — synchronous text and JSON completion with retry logic
- ``get_client()`` — module-level singleton accessor
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Dict, Optional

import anthropic
from rich.logging import RichHandler

from arxiv_intel.config import get_config

# ---------------------------------------------------------------------------
# Logger
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[RichHandler(rich_tracebacks=True, show_path=False)],
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ClaudeClient
# ---------------------------------------------------------------------------

_MAX_RETRIES = 3
_BACKOFF_BASE = 2.0  # seconds — doubled on each retry


class ClaudeClient:
    """Wrapper around ``anthropic.Anthropic`` with retry logic.

    Parameters
    ----------
    model:
        Claude model ID to use.  Defaults to the value from ``config.yaml``.
    """

    def __init__(self, model: Optional[str] = None) -> None:
        cfg = get_config()
        self.model: str = model or cfg.claude_model
        self._client = anthropic.Anthropic(api_key=cfg.anthropic_api_key)
        logger.debug("ClaudeClient initialised with model=%s", self.model)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def complete(
        self,
        system: str,
        user: str,
        max_tokens: int = 2000,
    ) -> str:
        """Send a request to Claude and return the raw text response.

        Parameters
        ----------
        system:
            System prompt string.
        user:
            User message string.
        max_tokens:
            Maximum tokens in the completion.

        Returns
        -------
        str
            The model's text response.

        Raises
        ------
        anthropic.APIError
            If all retries are exhausted.
        """
        last_exc: Optional[Exception] = None
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                response = self._client.messages.create(
                    model=self.model,
                    max_tokens=max_tokens,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                )
                text: str = response.content[0].text
                logger.debug(
                    "Claude response received (attempt=%d, chars=%d)",
                    attempt,
                    len(text),
                )
                return text
            except anthropic.RateLimitError as exc:
                last_exc = exc
                wait = _BACKOFF_BASE ** attempt
                logger.warning(
                    "Rate limit hit (attempt %d/%d) — waiting %.1fs",
                    attempt,
                    _MAX_RETRIES,
                    wait,
                )
                time.sleep(wait)
            except anthropic.APIStatusError as exc:
                # Retry on transient server errors (5xx)
                if exc.status_code and exc.status_code >= 500:
                    last_exc = exc
                    wait = _BACKOFF_BASE ** attempt
                    logger.warning(
                        "Server error %d (attempt %d/%d) — waiting %.1fs",
                        exc.status_code,
                        attempt,
                        _MAX_RETRIES,
                        wait,
                    )
                    time.sleep(wait)
                else:
                    raise
            except anthropic.APIConnectionError as exc:
                last_exc = exc
                wait = _BACKOFF_BASE ** attempt
                logger.warning(
                    "Connection error (attempt %d/%d) — waiting %.1fs",
                    attempt,
                    _MAX_RETRIES,
                    wait,
                )
                time.sleep(wait)

        raise RuntimeError(
            f"Claude API call failed after {_MAX_RETRIES} retries"
        ) from last_exc

    def complete_json(
        self,
        system: str,
        user: str,
        max_tokens: int = 2000,
    ) -> Dict[str, Any]:
        """Send a request to Claude and parse the response as JSON.

        The method first tries to decode the entire response as JSON.  If that
        fails it looks for the first ``{…}`` block in the response (Claude
        sometimes wraps JSON in markdown fences).

        Parameters
        ----------
        system:
            System prompt string.
        user:
            User message string.
        max_tokens:
            Maximum tokens in the completion.

        Returns
        -------
        dict
            Parsed JSON object.

        Raises
        ------
        ValueError
            If no valid JSON object can be extracted from the response.
        """
        raw = self.complete(system=system, user=user, max_tokens=max_tokens)
        return _extract_json(raw)


# ---------------------------------------------------------------------------
# JSON extraction helper
# ---------------------------------------------------------------------------

def _extract_json(text: str) -> Dict[str, Any]:
    """Extract the first valid JSON object from *text*.

    Tries three strategies in order:
    1. Parse the whole response directly.
    2. Strip a ```json … ``` markdown fence and parse.
    3. Find the first ``{`` … last ``}`` substring and parse.
    """
    # Strategy 1: direct parse
    stripped = text.strip()
    try:
        result = json.loads(stripped)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    # Strategy 2: markdown code fence
    fence_match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", stripped)
    if fence_match:
        try:
            result = json.loads(fence_match.group(1))
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

    # Strategy 3: first { … last }
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            result = json.loads(stripped[start : end + 1])
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

    raise ValueError(
        f"No valid JSON object found in Claude response.  "
        f"First 200 chars: {text[:200]!r}"
    )


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_client_instance: Optional[ClaudeClient] = None


def get_client() -> ClaudeClient:
    """Return the module-level ``ClaudeClient`` singleton."""
    global _client_instance
    if _client_instance is None:
        _client_instance = ClaudeClient()
    return _client_instance
