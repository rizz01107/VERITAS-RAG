"""Typed configuration.

Precedence (lowest to highest): defaults in this file < YAML config file(s)
(``extends`` chains allowed) < ``VERITAS_<SECTION>__<KEY>`` environment variables.
Secrets are never part of :class:`Settings`; they come only from the environment
via :func:`load_secrets` so that config hashes and snapshots cannot contain them.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PlainSerializer,
    SecretStr,
    ValidationError,
    model_validator,
)

from app.core.errors import ConfigError
from app.core.hashing import canonical_json, sha256_hex
from app.schemas.enums import ClaimType

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = Path("configs/default.yaml")
ENV_PREFIX = "VERITAS_"
NESTED_SEP = "__"
ENV_CONFIG_PATH = "VERITAS_CONFIG"
ENV_GENERATOR_API_KEY = "VERITAS_GENERATOR_API_KEY"
ENV_API_AUTH_TOKEN = "VERITAS_API_AUTH_TOKEN"  # noqa: S105 - env var NAME, not a secret
_RESERVED_ENV = frozenset({ENV_CONFIG_PATH, ENV_GENERATOR_API_KEY, ENV_API_AUTH_TOKEN})

_LOG = logging.getLogger("veritas.config")

PosixPath = Annotated[Path, PlainSerializer(lambda p: p.as_posix(), return_type=str)]


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, protected_namespaces=())


class RunConfig(_Section):
    """Run-level behaviour. ``full`` enables strict reproducibility checks."""

    mode: Literal["dev", "full"] = "dev"
    seed: int = Field(default=42, ge=0, le=2**32 - 1)
    max_eval_items: int | None = Field(default=None, ge=1)


class PathsConfig(_Section):
    """Filesystem layout. Relative paths resolve against the project root."""

    raw_dir: PosixPath = Path("data/raw")
    processed_dir: PosixPath = Path("data/processed")
    eval_dir: PosixPath = Path("data/evaluation")
    index_dir: PosixPath = Path("data/processed/index")
    manifest_path: PosixPath = Path("data/corpus_manifest.yaml")
    experiments_dir: PosixPath = Path("experiments/registry")
    logs_dir: PosixPath = Path("logs")
    models_config: PosixPath = Path("configs/models.yaml")
    models_local_config: PosixPath = Path("configs/models.local.yaml")


class IngestionConfig(_Section):
    """Upload/parsing limits."""

    allowed_extensions: tuple[str, ...] = (".pdf",)
    max_file_size_mb: float = Field(default=25.0, gt=0, le=500)
    pdf_parser: Literal["pymupdf"] = "pymupdf"
    ocr_enabled: bool = False
    ocr_languages: str = "eng"
    min_chars_per_page: int = Field(default=50, ge=0)
    max_pages: int = Field(default=400, ge=1, le=5000)
    max_chars_per_page_warn: int = Field(default=100_000, ge=1)
    detect_tables: bool = True
    table_detection_max_lines: int = Field(default=400, ge=1)
    detect_unruled_tables: bool = True
    table_max_page_fraction: float = Field(default=0.5, gt=0.0, le=1.0)
    detect_columns: bool = True
    strip_running_headers: bool = True
    exclude_references_from_chunks: bool = True
    heading_size_ratio: float = Field(default=1.12, ge=1.0, le=3.0)
    boilerplate_min_pages: int = Field(default=3, ge=2)
    boilerplate_page_fraction: float = Field(default=0.5, gt=0.0, le=1.0)
    margin_band_fraction: float = Field(default=0.08, gt=0.0, lt=0.5)
    column_gutter_fraction: float = Field(default=0.02, ge=0.0, lt=0.2)

    @model_validator(mode="after")
    def _extensions(self) -> IngestionConfig:
        bad = [e for e in self.allowed_extensions if not e.startswith(".") or e != e.lower()]
        if bad or not self.allowed_extensions:
            raise ValueError("allowed_extensions must be non-empty, lowercase, dot-prefixed")
        return self


class ChunkingConfig(_Section):
    """Chunking. ``chunk_size``/``chunk_overlap`` are counted in whitespace-delimited words."""

    strategy: Literal["fixed", "sentence", "section"] = "section"
    chunk_size: int = Field(default=256, ge=16, le=4096)
    chunk_overlap: int = Field(default=32, ge=0)

    @model_validator(mode="after")
    def _overlap(self) -> ChunkingConfig:
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        return self


class EmbeddingConfig(_Section):
    """Dense embedding settings."""

    model_ref: str = "embedder_default"
    batch_size: int = Field(default=32, ge=1, le=1024)
    normalize: bool = True
    device: Literal["auto", "cpu", "cuda", "mps"] = "auto"


class VectorStoreConfig(_Section):
    """Vector store backend (behind a repository interface)."""

    backend: Literal["chroma"] = "chroma"
    collection_name: str = Field(
        default="veritas_chunks", pattern=r"^[A-Za-z0-9][A-Za-z0-9_\-]{2,62}$"
    )
    distance: Literal["cosine", "l2", "ip"] = "cosine"


class RetrievalConfig(_Section):
    """Retrieval. ``top_k`` is the final context size for *every* system, for fair comparison."""

    mode: Literal["dense", "bm25", "hybrid"] = "hybrid"
    top_k: int = Field(default=5, ge=1, le=100)
    candidate_k: int = Field(default=30, ge=1, le=1000)
    fusion: Literal["rrf", "weighted"] = "rrf"
    rrf_k: int = Field(default=60, ge=1)
    dense_weight: float = Field(default=0.5, ge=0.0, le=1.0)
    similarity_threshold: float | None = None

    @model_validator(mode="after")
    def _pool(self) -> RetrievalConfig:
        if self.candidate_k < self.top_k:
            raise ValueError("candidate_k must be >= top_k")
        return self


class RerankingConfig(_Section):
    """Cross-encoder reranking of the candidate pool."""

    enabled: bool = True
    model_ref: str = "reranker_default"
    batch_size: int = Field(default=16, ge=1, le=512)


class GenerationConfig(_Section):
    """Generator call parameters (provider/model come from the model registry)."""

    model_ref: str = "generator_default"
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    max_tokens: int = Field(default=1024, ge=16, le=32768)
    timeout_s: float = Field(default=60.0, gt=0)
    max_retries: int = Field(default=3, ge=0, le=10)


class ClaimsConfig(_Section):
    """Claim extraction limits."""

    max_claims_per_answer: int = Field(default=30, ge=1)
    min_claim_chars: int = Field(default=15, ge=1)


class VerificationConfig(_Section):
    """Verification. Thresholds are PROVISIONAL until calibrated on the dev split (Phase 9)."""

    nli_model_ref: str = "nli_default"
    support_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    contradiction_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    evidence_top_k: int = Field(default=5, ge=1, le=50)
    max_regeneration_rounds: int = Field(default=1, ge=0, le=3)
    independent_second_pass: bool = True


class EcsConfig(_Section):
    """Evidence Coverage Score parameters. Must be frozen before test-split evaluation."""

    scored_claim_types: tuple[ClaimType, ...] = (
        ClaimType.FACTUAL,
        ClaimType.NUMERICAL,
        ClaimType.COMPARATIVE,
        ClaimType.CAUSAL,
        ClaimType.DEFINITIONAL,
        ClaimType.METHODOLOGICAL,
    )
    partial_credit: float = Field(default=0.5, ge=0.0, le=1.0)


class SecurityConfig(_Section):
    """Input limits. Retrieved text is always treated as untrusted data (not configurable)."""

    max_query_chars: int = Field(default=2000, ge=1)


class LoggingConfig(_Section):
    """Structured logging."""

    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    json_format: bool = True
    log_to_file: bool = False


class BudgetConfig(_Section):
    """Cost guard for LLM usage. ``None`` means unlimited (use only for full runs)."""

    max_llm_calls: int | None = Field(default=100, ge=1)
    max_total_tokens: int | None = Field(default=200_000, ge=1)


class Settings(_Section):
    """Complete validated configuration."""

    run: RunConfig = Field(default_factory=RunConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    ingestion: IngestionConfig = Field(default_factory=IngestionConfig)
    chunking: ChunkingConfig = Field(default_factory=ChunkingConfig)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    vector_store: VectorStoreConfig = Field(default_factory=VectorStoreConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    reranking: RerankingConfig = Field(default_factory=RerankingConfig)
    generation: GenerationConfig = Field(default_factory=GenerationConfig)
    claims: ClaimsConfig = Field(default_factory=ClaimsConfig)
    verification: VerificationConfig = Field(default_factory=VerificationConfig)
    ecs: EcsConfig = Field(default_factory=EcsConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    budget: BudgetConfig = Field(default_factory=BudgetConfig)

    def canonical_dict(self) -> dict[str, Any]:
        """JSON-compatible form used for hashing and experiment snapshots."""
        return self.model_dump(mode="json")

    def config_hash(self) -> str:
        """SHA-256 of the canonical configuration (key-order and OS independent)."""
        return sha256_hex(canonical_json(self.canonical_dict()))


class Secrets(BaseModel):
    """Secrets read only from the environment. Never serialised into configs or logs."""

    model_config = ConfigDict(extra="forbid", frozen=True, protected_namespaces=())

    generator_api_key: SecretStr | None = None
    api_auth_token: SecretStr | None = None


def resolve_path(path: Path, root: Path = PROJECT_ROOT) -> Path:
    """Resolve a config path against ``root`` unless it is already absolute."""
    return path if path.is_absolute() else root / path


def deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    """Recursively merge ``override`` into ``base`` without mutating either."""
    merged: dict[str, Any] = dict(base)
    for key, value in override.items():
        current = merged.get(key)
        if isinstance(current, Mapping) and isinstance(value, Mapping):
            merged[key] = deep_merge(current, value)
        else:
            merged[key] = value
    return merged


def read_yaml_mapping(path: Path) -> dict[str, Any]:
    """Read a YAML file that must contain a mapping (empty file -> ``{}``)."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError("cannot read config file", path=str(path), reason=str(exc)) from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError("invalid YAML", path=str(path), reason=str(exc)) from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError("config root must be a mapping", path=str(path))
    return data


def load_config_dict(path: Path, _chain: tuple[Path, ...] = ()) -> dict[str, Any]:
    """Load a YAML config, following ``extends: <relative path>`` (cycles rejected)."""
    resolved = path.resolve()
    if resolved in _chain:
        raise ConfigError("cyclic 'extends' chain", path=str(path))
    data = read_yaml_mapping(resolved)
    parent = data.pop("extends", None)
    if parent is None:
        return data
    if not isinstance(parent, str):
        raise ConfigError("'extends' must be a path string", path=str(path))
    base = load_config_dict(resolved.parent / parent, (*_chain, resolved))
    return deep_merge(base, data)


def _set_nested(target: dict[str, Any], keys: list[str], value: Any, env_name: str) -> None:
    cursor = target
    for key in keys[:-1]:
        child = cursor.setdefault(key, {})
        if not isinstance(child, dict):
            raise ConfigError("conflicting environment overrides", variable=env_name)
        cursor = child
    cursor[keys[-1]] = value


def env_overrides(environ: Mapping[str, str]) -> dict[str, Any]:
    """Translate ``VERITAS_A__B=value`` variables into a nested dict (value parsed as YAML)."""
    out: dict[str, Any] = {}
    for name in sorted(environ):
        if not name.startswith(ENV_PREFIX) or name in _RESERVED_ENV:
            continue
        body = name[len(ENV_PREFIX) :]
        if NESTED_SEP not in body:
            _LOG.warning("ignoring unrecognised environment variable %s", name)
            continue
        keys = [part.lower() for part in body.split(NESTED_SEP)]
        if any(not part for part in keys):
            raise ConfigError("malformed override variable name", variable=name)
        try:
            value = yaml.safe_load(environ[name])
        except yaml.YAMLError as exc:
            raise ConfigError("override value is not valid YAML", variable=name) from exc
        _set_nested(out, keys, value, name)
    return out


def load_settings(
    config_path: Path | str | None = None,
    environ: Mapping[str, str] | None = None,
    root: Path = PROJECT_ROOT,
) -> Settings:
    """Load, merge and validate configuration.

    Args:
        config_path: Explicit config file (resolved against the current directory).
            Falls back to ``$VERITAS_CONFIG`` and then ``<root>/configs/default.yaml``.
        environ: Environment mapping (defaults to ``os.environ``); injectable for tests.
        root: Project root used for the default config path.

    Raises:
        ConfigError: on any unreadable, malformed, unknown or invalid configuration.
    """
    env = os.environ if environ is None else environ
    if config_path is not None:
        path = Path(config_path)
    elif env.get(ENV_CONFIG_PATH):
        path = Path(env[ENV_CONFIG_PATH])
    else:
        path = root / DEFAULT_CONFIG
    merged = deep_merge(load_config_dict(path), env_overrides(env))
    try:
        return Settings.model_validate(merged)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors()
        )
        raise ConfigError(f"invalid configuration: {problems}", source=str(path)) from exc


def load_secrets(environ: Mapping[str, str] | None = None) -> Secrets:
    """Read secrets from the environment (empty strings count as unset)."""
    env = os.environ if environ is None else environ

    def pick(name: str) -> SecretStr | None:
        value = env.get(name, "")
        return SecretStr(value) if value else None

    return Secrets(
        generator_api_key=pick(ENV_GENERATOR_API_KEY),
        api_auth_token=pick(ENV_API_AUTH_TOKEN),
    )


def require_secret(secret: SecretStr | None, env_name: str) -> str:
    """Return a secret's value or raise a ConfigError naming the variable (not the value)."""
    if secret is None:
        raise ConfigError("required secret is not set", variable=env_name)
    return secret.get_secret_value()
