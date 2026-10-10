from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.evaluation.validation import contradiction_clusters, contradiction_coverage_problems
from app.ingestion.manifest import load_manifest
from app.schemas.enums import Split
from tests.conftest import make_paper

pytestmark = pytest.mark.unit


def _manifest(tmp_path: Path, *papers: dict[str, Any]):  # type: ignore[no-untyped-def]
    path = tmp_path / "m.yaml"
    data = {"manifest_version": "1", "corpus_name": "t", "papers": list(papers)}
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return load_manifest(path)


def _p(i: int, cluster: str, role: str, split: str, planned: str | None = None) -> dict[str, Any]:
    return make_paper(
        paper_id=f"synthetic-{i:04d}",
        title=f"Synthetic {i}",
        sha256=f"{i:064x}",
        cluster_id=cluster,
        evidence_role=role,
        split=split,
        planned_split=planned or split,
    )


def test_real_manifest_plan_has_independent_dev_and_test_clusters(repo_root: Path) -> None:
    manifest = load_manifest(repo_root / "data/corpus_manifest.yaml")
    plan = contradiction_clusters(manifest, planned=True)
    assert plan == {"lora-family": {Split.TEST}, "soft-prompts": {Split.DEV}}
    assert contradiction_coverage_problems(manifest, planned=True) == []
    # nothing is included yet, so the ACTUAL policy is (correctly) not satisfied
    assert contradiction_coverage_problems(manifest)


def test_actual_coverage_when_each_split_has_a_cluster(tmp_path: Path) -> None:
    m = _manifest(
        tmp_path,
        _p(1, "a", "claim", "test"),
        _p(2, "a", "qualifies", "test"),
        _p(3, "b", "claim", "dev"),
        _p(4, "b", "qualifies", "dev"),
    )
    assert contradiction_coverage_problems(m) == []


@pytest.mark.edge
def test_missing_cluster_in_a_split_is_reported(tmp_path: Path) -> None:
    m = _manifest(tmp_path, _p(1, "a", "claim", "test"), _p(2, "a", "qualifies", "test"))
    problems = contradiction_coverage_problems(m)
    assert problems == ["no contradiction cluster is wholly in split 'dev'"]


@pytest.mark.edge
def test_claim_without_qualifier_is_not_a_contradiction_cluster(tmp_path: Path) -> None:
    m = _manifest(tmp_path, _p(1, "a", "claim", "test"), _p(2, "a", "claim", "test"))
    assert contradiction_clusters(m) == {}


@pytest.mark.edge
def test_planned_split_conflicts_are_rejected(tmp_path: Path) -> None:
    one = make_paper(
        paper_id="c-1", title="C one", status="candidate", cluster_id="a", planned_split="dev"
    )
    two = make_paper(
        paper_id="c-2",
        title="C two",
        sha256="b" * 64,
        status="candidate",
        cluster_id="a",
        planned_split="test",
    )
    with pytest.raises(Exception, match="conflicting planned splits"):
        _manifest(tmp_path, one, two)
    with pytest.raises(Exception, match="differs from planned_split"):
        _manifest(tmp_path, _p(1, "a", "claim", "dev", "test"))


# ---- copyright hygiene ---------------------------------------------------------------------------
_SKIP = {
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
}
_IGNORED_DATA = {("data", "raw"), ("data", "processed")}


def test_no_pdf_or_parsed_paper_text_in_tracked_locations(repo_root: Path) -> None:
    offenders: list[str] = []
    for root, dirs, files in os.walk(repo_root):
        rel = Path(root).relative_to(repo_root).parts
        dirs[:] = [d for d in dirs if d not in _SKIP and not d.endswith(".egg-info")]
        if rel[:2] in _IGNORED_DATA:
            dirs[:] = []
            continue
        for name in files:
            if name.lower().endswith(".pdf"):
                offenders.append(str(Path(root, name).relative_to(repo_root)))
            if (
                name.endswith(".json")
                and "full_text"
                in Path(root, name).read_text(encoding="utf-8", errors="ignore")[:2_000_000]
            ):
                offenders.append(str(Path(root, name).relative_to(repo_root)))
    assert offenders == []


def test_gitignore_protects_paper_data(repo_root: Path) -> None:
    lines = (repo_root / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "data/raw/*" in lines and "data/processed/*" in lines
    assert ".env" in lines and "configs/models.local.yaml" in lines
