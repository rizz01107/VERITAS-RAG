"""Experiment identity and immutable-by-default experiment records.

ID format: ``<system>-<YYYYMMDDTHHMMSSZ>-<config_hash[:8]>`` where ``system`` is a
lowercase slug such as ``exp_a_llm_only`` or ``abl_no_bm25``. Records live at
``<experiments_dir>/<experiment_id>/record.json``. A run never overwrites another.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess  # noqa: S404 - used only to read git state with fixed arguments
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import PROJECT_ROOT, Settings, resolve_path
from app.core.device import hardware_info
from app.core.errors import ExperimentError
from app.core.logconfig import redact
from app.schemas.enums import ExperimentStatus
from app.schemas.experiments import ExperimentRecord
from app.schemas.models import ModelSpec

_SYSTEM_SLUG = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
RECORD_FILENAME = "record.json"


def make_experiment_id(system: str, config_hash: str, now: datetime | None = None) -> str:
    """Build a deterministic experiment id from system slug, UTC time and config hash."""
    if not _SYSTEM_SLUG.match(system):
        raise ExperimentError("invalid system slug (use [a-z][a-z0-9_]{0,39})", system=system)
    if not re.fullmatch(r"[0-9a-f]{8,64}", config_hash):
        raise ExperimentError("config_hash must be lowercase hex")
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return f"{system}-{moment:%Y%m%dT%H%M%SZ}-{config_hash[:8]}"


def git_state(root: Path) -> tuple[str | None, bool | None]:
    """Return ``(commit, dirty)``; ``(None, None)`` if git or a repository is unavailable."""
    git = shutil.which("git")
    if git is None:
        return None, None

    def run(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: S603 - fixed argv, no shell, no user input
            [git, "-C", str(root), *args],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

    head = run("rev-parse", "HEAD")
    if head.returncode != 0:
        return None, None
    status = run("status", "--porcelain")
    dirty = bool(status.stdout.strip()) if status.returncode == 0 else None
    return head.stdout.strip(), dirty


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


class ExperimentRecorder:
    """Creates and finalises experiment records on disk."""

    def __init__(self, settings: Settings, root: Path = PROJECT_ROOT) -> None:
        self._settings = settings
        self._root = root
        self._base = resolve_path(settings.paths.experiments_dir, root)

    def record_path(self, experiment_id: str) -> Path:
        """Path of the record file for ``experiment_id``."""
        return self._base / experiment_id / RECORD_FILENAME

    def start(
        self,
        system: str,
        models: Mapping[str, ModelSpec],
        dataset_version: str | None = None,
        notes: str = "",
        now: datetime | None = None,
    ) -> ExperimentRecord:
        """Create the record (status RUNNING) and its directory.

        Raises:
            ExperimentError: if an experiment with the same id already exists.
        """
        moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        config_hash = self._settings.config_hash()
        experiment_id = make_experiment_id(system, config_hash, moment)
        directory = self._base / experiment_id
        try:
            directory.mkdir(parents=True, exist_ok=False)
        except FileExistsError as exc:
            raise ExperimentError("experiment already exists", experiment_id=experiment_id) from exc
        commit, dirty = git_state(self._root)
        record = ExperimentRecord(
            experiment_id=experiment_id,
            system=system,
            status=ExperimentStatus.RUNNING,
            created_at=moment,
            config_hash=config_hash,
            config=redact(self._settings.canonical_dict()),
            models=dict(models),
            dataset_version=dataset_version,
            seed=self._settings.run.seed,
            git_commit=commit,
            git_dirty=dirty,
            hardware=hardware_info(self._settings.embedding.device),
            notes=notes,
        )
        self._write(record)
        return record

    def finalize(
        self,
        record: ExperimentRecord,
        status: ExperimentStatus,
        metrics: Mapping[str, float | None] | None = None,
        latency: Mapping[str, float] | None = None,
        token_usage: Mapping[str, Any] | None = None,
        errors: tuple[str, ...] = (),
        now: datetime | None = None,
    ) -> ExperimentRecord:
        """Move a RUNNING record to COMPLETED or FAILED and persist it atomically."""
        if status == ExperimentStatus.RUNNING:
            raise ExperimentError("finalize requires COMPLETED or FAILED")
        on_disk = self._read(record.experiment_id)
        if on_disk.status != ExperimentStatus.RUNNING:
            raise ExperimentError(
                "experiment already finalised", experiment_id=record.experiment_id
            )
        final = on_disk.evolve(
            status=status,
            finished_at=(now or datetime.now(timezone.utc)).astimezone(timezone.utc),
            metrics=dict(metrics or {}),
            latency=dict(latency or {}),
            token_usage=redact(dict(token_usage or {})),
            errors=tuple(redact(list(errors))),
        )
        self._write(final)
        return final

    def _write(self, record: ExperimentRecord) -> None:
        payload = json.dumps(record.model_dump(mode="json"), indent=2, sort_keys=True)
        _atomic_write(self.record_path(record.experiment_id), payload + "\n")

    def _read(self, experiment_id: str) -> ExperimentRecord:
        path = self.record_path(experiment_id)
        try:
            return ExperimentRecord.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ExperimentError("cannot read experiment record", path=str(path)) from exc
