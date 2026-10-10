"""Typed exception hierarchy: every failure is explicit, loggable and attributable."""

from __future__ import annotations

from typing import Any


class VeritasError(Exception):
    """Base class for all project errors.

    Attributes:
        code: Stable machine-readable identifier (used in logs and API errors).
        context: Extra structured details. Callers must never put secrets here.
    """

    code = "veritas_error"

    def __init__(self, message: str, **context: Any) -> None:
        super().__init__(message)
        self.message = message
        self.context = context

    def __str__(self) -> str:
        if not self.context:
            return self.message
        details = ", ".join(f"{key}={value!r}" for key, value in sorted(self.context.items()))
        return f"{self.message} ({details})"


class ConfigError(VeritasError):
    """Invalid, missing or inconsistent configuration or environment."""

    code = "config_error"


class ManifestError(VeritasError):
    """Corpus manifest is invalid or disagrees with files on disk."""

    code = "manifest_error"


class ModelRegistryError(VeritasError):
    """Model registry is invalid or a referenced model is missing/mismatched."""

    code = "model_registry_error"


class BudgetExceededError(VeritasError):
    """The configured LLM call or token budget would be exceeded."""

    code = "budget_exceeded"


class ExperimentError(VeritasError):
    """Experiment record could not be created, updated or is in an invalid state."""

    code = "experiment_error"


class ReproducibilityError(VeritasError):
    """A precondition for a reproducible full evaluation is not met."""

    code = "reproducibility_error"


class EvaluationDataError(VeritasError):
    """Evaluation data violates a validity rule (e.g. split leakage)."""

    code = "evaluation_data_error"


class IngestionFailureError(VeritasError):
    """Raised inside the ingestion pipeline and converted to a structured result at its boundary."""

    code = "ingestion_failure"

    def __init__(self, failure_code: str, message: str, stage: str, **context: object) -> None:
        super().__init__(message, **context)
        self.failure_code = failure_code
        self.stage = stage
