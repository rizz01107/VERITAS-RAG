"""Model registry contracts: every model used in a run is identified and pinnable."""

from __future__ import annotations

import re

from pydantic import Field, model_validator

from app.schemas.base import StrictModel
from app.schemas.enums import ModelProvider, ModelRole

_COMMIT_SHA = re.compile(r"^[0-9a-f]{40}$")


class ModelSpec(StrictModel):
    """Description of one model. Secrets are never stored here (use env vars)."""

    role: ModelRole
    provider: ModelProvider
    model_id: str | None = None
    revision: str | None = None
    base_url: str | None = None
    notes: str = ""

    @model_validator(mode="after")
    def _check(self) -> ModelSpec:
        if self.provider == ModelProvider.HUGGINGFACE_LOCAL and not self.model_id:
            raise ValueError("huggingface_local models require model_id")
        if self.revision is not None and self.provider != ModelProvider.HUGGINGFACE_LOCAL:
            raise ValueError("revision applies only to huggingface_local models")
        return self

    @property
    def is_pinned(self) -> bool:
        """True when the model identity is fixed well enough to reproduce a run.

        Local models need a full 40-hex commit revision. API models need an
        explicit ``model_id`` (use a dated snapshot id where the provider has one;
        providers may still change behaviour behind an id - recorded as a limitation).
        """
        if self.provider == ModelProvider.HUGGINGFACE_LOCAL:
            return self.revision is not None and bool(_COMMIT_SHA.match(self.revision))
        return bool(self.model_id)


class ModelRegistry(StrictModel):
    """Named models available to configuration (``*_ref`` fields point at these keys)."""

    models: dict[str, ModelSpec] = Field(default_factory=dict)
