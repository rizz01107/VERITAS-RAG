"""Preconditions for a reproducible *full* evaluation (cost-bearing, result-reporting)."""

from __future__ import annotations

from app.core.config import Settings
from app.core.errors import ReproducibilityError
from app.core.model_registry import referenced_models
from app.schemas.enums import ManifestStatus, ModelProvider
from app.schemas.manifest import CorpusManifest
from app.schemas.models import ModelRegistry


def full_evaluation_problems(
    settings: Settings,
    registry: ModelRegistry,
    manifest: CorpusManifest | None,
) -> list[str]:
    """List every reason a full evaluation must not start yet (empty list = ready)."""
    problems: list[str] = []
    if settings.run.mode != "full":
        problems.append(f"run.mode is {settings.run.mode!r}; full evaluation requires 'full'")
    for setting, (key, _role) in referenced_models(settings).items():
        spec = registry.models.get(key)
        if spec is None:
            problems.append(f"{setting}: model {key!r} not in registry")
        elif not spec.is_pinned:
            what = (
                "a 40-hex commit revision"
                if spec.provider == ModelProvider.HUGGINGFACE_LOCAL
                else "an explicit model_id"
            )
            problems.append(f"{setting}: model {key!r} is not pinned (needs {what})")
    if manifest is None:
        problems.append("corpus manifest not loaded")
    elif not any(p.status == ManifestStatus.INCLUDED for p in manifest.papers):
        problems.append("corpus manifest has no included papers")
    return problems


def assert_ready_for_full_evaluation(
    settings: Settings,
    registry: ModelRegistry,
    manifest: CorpusManifest | None,
) -> None:
    """Raise :class:`ReproducibilityError` listing all unmet preconditions."""
    problems = full_evaluation_problems(settings, registry, manifest)
    if problems:
        raise ReproducibilityError("not ready for full evaluation: " + "; ".join(problems))
