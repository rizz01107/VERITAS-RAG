"""CPU-first device selection and hardware reporting. Never assumes torch/CUDA exist."""

from __future__ import annotations

import importlib
import importlib.metadata
import importlib.util
import os
import platform
from dataclasses import asdict, dataclass
from typing import Any

from app.core.errors import ConfigError

TRACKED_PACKAGES = (
    "pydantic",
    "PyYAML",
    "torch",
    "numpy",
    "transformers",
    "sentence-transformers",
    "chromadb",
    "rank-bm25",
    "pymupdf",
    "fastapi",
)
_VALID = ("auto", "cpu", "cuda", "mps")


@dataclass(frozen=True)
class DeviceInfo:
    """Resolved compute device and why it was chosen."""

    device: str
    torch_version: str | None
    cuda_available: bool
    mps_available: bool
    reason: str


def load_torch() -> Any | None:
    """Import torch lazily; return ``None`` if it is absent or unusable."""
    if importlib.util.find_spec("torch") is None:
        return None
    try:
        return importlib.import_module("torch")
    except Exception:  # broken installs raise many error types
        return None


def detect_device(preference: str = "auto") -> DeviceInfo:
    """Resolve ``preference`` to a concrete device.

    ``auto`` picks CUDA, then MPS, then CPU. An explicit ``cuda``/``mps`` request that
    cannot be satisfied raises instead of silently falling back, so results are never
    attributed to hardware that was not used.

    Raises:
        ConfigError: unknown preference, or an explicit accelerator is unavailable.
    """
    if preference not in _VALID:
        raise ConfigError("unknown device preference", preference=preference, valid=_VALID)
    torch = load_torch()
    if torch is None:
        if preference in {"cuda", "mps"}:
            raise ConfigError(
                "accelerator requested but torch is not available", preference=preference
            )
        return DeviceInfo("cpu", None, False, False, "torch not installed; using CPU")
    cuda = bool(torch.cuda.is_available())
    mps_backend = getattr(getattr(torch, "backends", None), "mps", None)
    mps = bool(mps_backend.is_available()) if mps_backend is not None else False
    version = str(getattr(torch, "__version__", "unknown"))
    if preference == "cuda" and not cuda:
        raise ConfigError("cuda requested but not available")
    if preference == "mps" and not mps:
        raise ConfigError("mps requested but not available")
    if preference == "auto":
        chosen = "cuda" if cuda else "mps" if mps else "cpu"
        reason = "auto-detected"
    else:
        chosen, reason = preference, "explicitly requested"
    return DeviceInfo(chosen, version, cuda, mps, reason)


def package_versions() -> dict[str, str]:
    """Versions of tracked packages that are installed (absent ones are omitted)."""
    found: dict[str, str] = {}
    for name in TRACKED_PACKAGES:
        try:
            found[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            continue
    return found


def hardware_info(preference: str = "auto") -> dict[str, Any]:
    """Machine/environment description stored in every experiment record."""
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu_count": os.cpu_count(),
        "pythonhashseed": os.environ.get("PYTHONHASHSEED"),
        "device": asdict(detect_device(preference)),
        "packages": package_versions(),
    }
