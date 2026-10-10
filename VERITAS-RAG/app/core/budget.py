"""Cost guard: refuses LLM calls once the configured budget is exhausted."""

from __future__ import annotations

import threading
from typing import Any

from app.core.errors import BudgetExceededError


class UsageTracker:
    """Thread-safe counter of LLM calls and tokens with hard limits.

    ``None`` limits mean unlimited. Token counts flagged ``estimated`` (provider did
    not report usage) are tracked separately so reports can say how exact they are.
    """

    def __init__(self, max_llm_calls: int | None, max_total_tokens: int | None) -> None:
        self._max_calls = max_llm_calls
        self._max_tokens = max_total_tokens
        self._lock = threading.Lock()
        self._calls = 0
        self._prompt = 0
        self._completion = 0
        self._estimated_calls = 0

    def begin_call(self) -> None:
        """Reserve one call slot; raise if the call or token budget is already used up."""
        with self._lock:
            if self._max_calls is not None and self._calls >= self._max_calls:
                raise BudgetExceededError(
                    "LLM call budget exhausted", max_llm_calls=self._max_calls
                )
            total = self._prompt + self._completion
            if self._max_tokens is not None and total >= self._max_tokens:
                raise BudgetExceededError(
                    "token budget exhausted", max_total_tokens=self._max_tokens
                )
            self._calls += 1

    def record_usage(self, prompt_tokens: int, completion_tokens: int, estimated: bool) -> None:
        """Add token usage for a completed call."""
        if prompt_tokens < 0 or completion_tokens < 0:
            raise ValueError("token counts must be non-negative")
        with self._lock:
            self._prompt += prompt_tokens
            self._completion += completion_tokens
            if estimated:
                self._estimated_calls += 1

    def summary(self) -> dict[str, Any]:
        """Snapshot for the experiment record."""
        with self._lock:
            return {
                "llm_calls": self._calls,
                "prompt_tokens": self._prompt,
                "completion_tokens": self._completion,
                "total_tokens": self._prompt + self._completion,
                "calls_with_estimated_tokens": self._estimated_calls,
                "max_llm_calls": self._max_calls,
                "max_total_tokens": self._max_tokens,
            }
