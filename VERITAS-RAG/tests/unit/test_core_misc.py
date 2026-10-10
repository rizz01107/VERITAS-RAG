from __future__ import annotations

import random
import subprocess
import sys
import threading
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from app.core import device
from app.core.budget import UsageTracker
from app.core.config import Settings, load_settings
from app.core.errors import BudgetExceededError, ConfigError, ExperimentError
from app.core.experiment import ExperimentRecorder, make_experiment_id
from app.core.hashing import canonical_json
from app.core.seed import set_global_seed
from app.schemas.enums import ExperimentStatus, ModelProvider, ModelRole
from app.schemas.models import ModelSpec

pytestmark = pytest.mark.unit
NOW = datetime(2026, 10, 3, 12, 0, 0, tzinfo=timezone.utc)


# ---- hashing / experiment ids ---------------------------------------------------------
def test_canonical_json_sorted_and_compact() -> None:
    assert canonical_json({"b": 1, "a": [1, 2]}) == '{"a":[1,2],"b":1}'


@pytest.mark.edge
def test_canonical_json_rejects_nan_and_unknown_types() -> None:
    with pytest.raises(ValueError):
        canonical_json({"x": float("nan")})
    with pytest.raises(TypeError):
        canonical_json({"x": object()})


def test_experiment_id_deterministic_and_formatted() -> None:
    a = make_experiment_id("exp_e_veritas", "abcdef0123456789", NOW)
    assert a == "exp_e_veritas-20261003T120000Z-abcdef01"
    assert a == make_experiment_id("exp_e_veritas", "abcdef0123456789", NOW)


@pytest.mark.edge
@pytest.mark.parametrize("system", ["Exp A", "1abc", "", "a-b", "x" * 41])
def test_experiment_id_rejects_bad_system(system: str) -> None:
    with pytest.raises(ExperimentError):
        make_experiment_id(system, "abcdef01", NOW)


def test_experiment_id_converts_to_utc() -> None:
    local = NOW.astimezone(timezone(timedelta(hours=5)))
    assert make_experiment_id("s", "abcdef01", local) == make_experiment_id("s", "abcdef01", NOW)


# ---- recorder ----------------------------------------------------------------------------
def _settings(tmp_path: Path, repo_root: Path) -> Settings:
    return load_settings(
        environ={"VERITAS_PATHS__EXPERIMENTS_DIR": str(tmp_path / "reg")}, root=repo_root
    )


def _models() -> dict[str, ModelSpec]:
    return {
        "generator_default": ModelSpec(
            role=ModelRole.GENERATOR, provider=ModelProvider.OPENAI_COMPATIBLE, model_id="m"
        )
    }


def test_recorder_start_and_finalize(tmp_path: Path, repo_root: Path) -> None:
    settings = _settings(tmp_path, repo_root)
    rec = ExperimentRecorder(settings, repo_root)
    record = rec.start("exp_a_llm_only", _models(), dataset_version="corpus-x", now=NOW)
    assert record.status == ExperimentStatus.RUNNING
    assert record.config_hash == settings.config_hash()
    assert record.metrics == {}  # nothing run yet
    assert rec.record_path(record.experiment_id).is_file()
    final = rec.finalize(
        record,
        ExperimentStatus.COMPLETED,
        metrics={"recall@5": 0.5, "mrr": None},
        token_usage={"total_tokens": 10, "api_key": "sk-leakleakleak"},
        now=NOW + timedelta(seconds=5),
    )
    assert final.metrics["mrr"] is None
    assert final.token_usage["api_key"] == "[REDACTED]"
    on_disk = rec.record_path(record.experiment_id).read_text(encoding="utf-8")
    assert "sk-leakleakleak" not in on_disk
    assert "COMPLETED" in on_disk


@pytest.mark.edge
def test_recorder_refuses_overwrite_and_double_finalize(tmp_path: Path, repo_root: Path) -> None:
    rec = ExperimentRecorder(_settings(tmp_path, repo_root), repo_root)
    record = rec.start("s", _models(), now=NOW)
    with pytest.raises(ExperimentError, match="already exists"):
        rec.start("s", _models(), now=NOW)
    rec.finalize(record, ExperimentStatus.FAILED, errors=("boom Bearer abcdefghijkl",), now=NOW)
    with pytest.raises(ExperimentError, match="finalised"):
        rec.finalize(record, ExperimentStatus.COMPLETED, now=NOW)
    assert "abcdefghijkl" not in rec.record_path(record.experiment_id).read_text(encoding="utf-8")


@pytest.mark.edge
def test_finalize_rejects_running_status(tmp_path: Path, repo_root: Path) -> None:
    rec = ExperimentRecorder(_settings(tmp_path, repo_root), repo_root)
    record = rec.start("s", _models(), now=NOW)
    with pytest.raises(ExperimentError):
        rec.finalize(record, ExperimentStatus.RUNNING)


# ---- budget ----------------------------------------------------------------------------------
def test_budget_call_limit() -> None:
    t = UsageTracker(2, None)
    t.begin_call()
    t.begin_call()
    with pytest.raises(BudgetExceededError):
        t.begin_call()


def test_budget_token_limit_and_estimate_flag() -> None:
    t = UsageTracker(None, 100)
    t.begin_call()
    t.record_usage(60, 50, estimated=True)
    with pytest.raises(BudgetExceededError):
        t.begin_call()
    s = t.summary()
    assert s["total_tokens"] == 110 and s["calls_with_estimated_tokens"] == 1


@pytest.mark.edge
def test_budget_negative_tokens_rejected() -> None:
    with pytest.raises(ValueError):
        UsageTracker(None, None).record_usage(-1, 0, estimated=False)


@pytest.mark.edge
def test_budget_is_thread_safe() -> None:
    t = UsageTracker(10, None)
    ok: list[int] = []

    def worker() -> None:
        try:
            t.begin_call()
            ok.append(1)
        except BudgetExceededError:
            pass

    threads = [threading.Thread(target=worker) for _ in range(40)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert len(ok) == 10


# ---- device / seed -----------------------------------------------------------------------------
def _fake_torch(cuda: bool, mps: bool = False) -> Any:
    mod = types.SimpleNamespace(
        __version__="0.0-test",
        cuda=types.SimpleNamespace(is_available=lambda: cuda),
        backends=types.SimpleNamespace(mps=types.SimpleNamespace(is_available=lambda: mps)),
    )
    return mod


def test_device_cpu_without_torch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(device, "load_torch", lambda: None)
    info = device.detect_device("auto")
    assert info.device == "cpu" and info.torch_version is None


def test_device_auto_picks_cuda_then_cpu(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(device, "load_torch", lambda: _fake_torch(True))
    assert device.detect_device("auto").device == "cuda"
    monkeypatch.setattr(device, "load_torch", lambda: _fake_torch(False))
    assert device.detect_device("auto").device == "cpu"
    assert device.detect_device("cpu").device == "cpu"


@pytest.mark.edge
def test_explicit_accelerator_unavailable_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(device, "load_torch", lambda: None)
    with pytest.raises(ConfigError):
        device.detect_device("cuda")
    monkeypatch.setattr(device, "load_torch", lambda: _fake_torch(False))
    with pytest.raises(ConfigError):
        device.detect_device("cuda")
    with pytest.raises(ConfigError):
        device.detect_device("tpu")


def test_hardware_info_has_expected_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(device, "load_torch", lambda: None)
    info = device.hardware_info()
    assert {"python", "platform", "cpu_count", "device", "packages"} <= set(info)
    assert "pydantic" in info["packages"]


def test_seed_reproducible() -> None:
    assert "random" in set_global_seed(123)
    a = [random.random() for _ in range(3)]
    set_global_seed(123)
    assert a == [random.random() for _ in range(3)]


@pytest.mark.edge
def test_seed_out_of_range() -> None:
    with pytest.raises(ValueError):
        set_global_seed(-1)


def test_importing_core_does_not_import_torch() -> None:
    code = (
        "import sys, app.core.config, app.core.experiment, app.core.seed, app.cli;"
        "assert 'torch' not in sys.modules"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
