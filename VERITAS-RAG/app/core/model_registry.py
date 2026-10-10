"""Model registry loading and validation of ``*_ref`` references in the settings."""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from app.core.config import PROJECT_ROOT, Settings, deep_merge, read_yaml_mapping, resolve_path
from app.core.errors import ModelRegistryError
from app.schemas.enums import ModelRole
from app.schemas.models import ModelRegistry, ModelSpec


def load_registry(settings: Settings, root: Path = PROJECT_ROOT) -> ModelRegistry:
    """Load ``models.yaml`` and merge the optional git-ignored ``models.local.yaml`` over it.

    Raises:
        ModelRegistryError: if the base file is missing or the merged registry is invalid.
    """
    base_path = resolve_path(settings.paths.models_config, root)
    if not base_path.is_file():
        raise ModelRegistryError("model registry file not found", path=str(base_path))
    data = read_yaml_mapping(base_path)
    local_path = resolve_path(settings.paths.models_local_config, root)
    if local_path.is_file():
        data = deep_merge(data, read_yaml_mapping(local_path))
    try:
        return ModelRegistry.model_validate(data)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors()
        )
        raise ModelRegistryError(f"invalid model registry: {problems}") from exc


def referenced_models(settings: Settings) -> dict[str, tuple[str, ModelRole]]:
    """Map each setting that references a model to ``(registry key, required role)``."""
    refs = {
        "embedding.model_ref": (settings.embedding.model_ref, ModelRole.EMBEDDER),
        "generation.model_ref": (settings.generation.model_ref, ModelRole.GENERATOR),
        "verification.nli_model_ref": (settings.verification.nli_model_ref, ModelRole.NLI),
    }
    if settings.reranking.enabled:
        refs["reranking.model_ref"] = (settings.reranking.model_ref, ModelRole.RERANKER)
    return refs


def validate_references(settings: Settings, registry: ModelRegistry) -> dict[str, ModelSpec]:
    """Check every model reference exists with the right role; return key -> spec.

    Raises:
        ModelRegistryError: listing all missing or role-mismatched references.
    """
    problems: list[str] = []
    resolved: dict[str, ModelSpec] = {}
    for setting, (key, role) in referenced_models(settings).items():
        spec = registry.models.get(key)
        if spec is None:
            problems.append(f"{setting}: unknown model {key!r}")
        elif spec.role != role:
            problems.append(f"{setting}: {key!r} has role {spec.role.value}, expected {role.value}")
        else:
            resolved[key] = spec
    if problems:
        raise ModelRegistryError("; ".join(problems))
    return resolved
