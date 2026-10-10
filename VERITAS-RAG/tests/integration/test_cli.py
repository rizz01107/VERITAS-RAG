from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.cli import main

pytestmark = pytest.mark.integration


def test_check_config_outputs_summary(capsys: pytest.CaptureFixture[str], repo_root: Path) -> None:
    code = main(["check-config", "--config", str(repo_root / "configs/dev_cpu.yaml")])
    out = json.loads(capsys.readouterr().out)
    assert code == 0
    assert len(out["config_hash"]) == 64 and out["run_mode"] == "dev"
    assert out["full_evaluation_ready"] is False
    assert out["models"]["generator_default"]["pinned"] is False


def test_check_config_is_reproducible(capsys: pytest.CaptureFixture[str], repo_root: Path) -> None:
    cfg = str(repo_root / "configs/dev_cpu.yaml")
    main(["check-config", "--config", cfg])
    first = json.loads(capsys.readouterr().out)["config_hash"]
    main(["check-config", "--config", cfg])
    assert json.loads(capsys.readouterr().out)["config_hash"] == first


def test_strict_mode_exit_code(repo_root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert (
        main(["check-config", "--config", str(repo_root / "configs/eval_full.yaml"), "--strict"])
        == 3
    )
    capsys.readouterr()


@pytest.mark.edge
def test_bad_config_gives_clean_error(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    code = main(["check-config", "--config", str(tmp_path / "missing.yaml")])
    err = json.loads(capsys.readouterr().err)
    assert code == 2 and err["error"] == "config_error"


@pytest.mark.edge
def test_secret_never_printed(
    capsys: pytest.CaptureFixture[str], repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VERITAS_GENERATOR_API_KEY", "sk-should-never-appear-123")
    main(["check-config", "--config", str(repo_root / "configs/dev_cpu.yaml")])
    captured = capsys.readouterr()
    assert "sk-should-never-appear" not in captured.out + captured.err


def test_validate_manifest_and_hardware(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["validate-manifest"]) == 0
    assert json.loads(capsys.readouterr().out)["dataset_version"] == "corpus-empty"
    assert main(["hardware", "--device", "cpu"]) == 0
    assert json.loads(capsys.readouterr().out)["device"]["device"] == "cpu"
