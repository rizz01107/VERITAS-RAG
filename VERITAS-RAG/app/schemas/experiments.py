"""Experiment record contract (one JSON file per run)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field, model_validator

from app.schemas.base import StrictModel
from app.schemas.enums import ExperimentStatus
from app.schemas.models import ModelSpec


class ExperimentRecord(StrictModel):
    """Everything needed to identify, audit and rerun an experiment.

    ``metrics`` values of ``None`` mean "not computed"; an empty ``metrics`` dict
    means no results exist yet (NOT RUN / PENDING EXPERIMENT).
    """

    experiment_id: str
    system: str
    status: ExperimentStatus
    created_at: datetime
    finished_at: datetime | None = None
    config_hash: str
    config: dict[str, Any]
    models: dict[str, ModelSpec] = Field(default_factory=dict)
    dataset_version: str | None = None
    seed: int
    git_commit: str | None = None
    git_dirty: bool | None = None
    hardware: dict[str, Any] = Field(default_factory=dict)
    metrics: dict[str, float | None] = Field(default_factory=dict)
    latency: dict[str, float] = Field(default_factory=dict)
    token_usage: dict[str, Any] = Field(default_factory=dict)
    errors: tuple[str, ...] = ()
    notes: str = ""

    @model_validator(mode="after")
    def _check_times(self) -> ExperimentRecord:
        if self.created_at.tzinfo is None:
            raise ValueError("created_at must be timezone-aware (UTC)")
        if self.finished_at is not None:
            if self.finished_at.tzinfo is None:
                raise ValueError("finished_at must be timezone-aware (UTC)")
            if self.finished_at < self.created_at:
                raise ValueError("finished_at precedes created_at")
        return self
