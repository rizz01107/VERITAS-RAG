from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from app.core.config import load_settings
from app.core.errors import (
    EvaluationDataError,
    ManifestError,
    ModelRegistryError,
    ReproducibilityError,
)
from app.core.model_registry import load_registry, validate_references
from app.core.readiness import assert_ready_for_full_evaluation, full_evaluation_problems
from app.evaluation.annotation import (
    SINGLE_ANNOTATOR_STATEMENT,
    agreement_statement,
    annotation_coverage,
)
from app.evaluation.validation import check_split_consistency
from app.ingestion.manifest import corpus_fingerprint, load_manifest, sha256_file, verify_files
from app.schemas.evaluation import EvalItem
from app.schemas.manifest import CorpusManifest
from tests.conftest import make_paper

pytestmark = pytest.mark.unit
Writer = Callable[[str, dict[str, Any]], Path]


def _manifest(write_yaml: Writer, *papers: dict[str, Any]) -> CorpusManifest:
    path = write_yaml(
        "m.yaml", {"manifest_version": "0.1", "corpus_name": "t", "papers": list(papers)}
    )
    return load_manifest(path)


# ---- manifest ----------------------------------------------------------------------------
def test_real_manifest_is_valid_and_has_no_included_papers(repo_root: Path) -> None:
    manifest = load_manifest(repo_root / "data/corpus_manifest.yaml")
    assert len(manifest.papers) >= 1
    assert all(p.status.value == "candidate" for p in manifest.papers)
    assert all(p.license == "UNVERIFIED" for p in manifest.papers)  # never pre-verified
    assert corpus_fingerprint(manifest) == "corpus-empty"  # nothing is included yet


def test_valid_included_paper(write_yaml: Writer) -> None:
    assert len(_manifest(write_yaml, make_paper()).papers) == 1


@pytest.mark.edge
@pytest.mark.parametrize(
    "bad",
    [
        {"license": "UNVERIFIED"},
        {"license_source": None},
        {"access_status": "unchecked"},
        {"access_status": "restricted"},
        {"license_verified_on": None},
        {"access_checked_on": None},
        {"sha256": None},
        {"version": None},
        {"split": None},
        {"local_path": None},
        {"source_url": None},
        {"sha256": "xyz"},
    ],
)
def test_included_requires_verification(write_yaml: Writer, bad: dict[str, Any]) -> None:
    with pytest.raises(ManifestError):
        _manifest(write_yaml, make_paper(**bad))


@pytest.mark.edge
def test_duplicates_rejected(write_yaml: Writer) -> None:
    p2 = make_paper(paper_id="synthetic-0002v1", title="Another", local_path="two.pdf")
    with pytest.raises(ManifestError, match="identical file hash"):
        _manifest(write_yaml, make_paper(), p2)
    p3 = make_paper(paper_id="synthetic-0003v1", sha256="b" * 64, title="synthetic paper ONE!")
    with pytest.raises(ManifestError, match="same title"):
        _manifest(write_yaml, make_paper(), p3)
    with pytest.raises(ManifestError, match="duplicate paper_id"):
        _manifest(write_yaml, make_paper(), make_paper(sha256="c" * 64, title="x"))


def test_duplicate_marked_excluded_is_accepted(write_yaml: Writer) -> None:
    dup = make_paper(
        paper_id="synthetic-0001v2",
        status="excluded",
        duplicate_of="synthetic-0001v1",
        split=None,
        license="UNVERIFIED",
    )
    assert len(_manifest(write_yaml, make_paper(), dup).papers) == 2


@pytest.mark.edge
def test_duplicate_of_rules(write_yaml: Writer) -> None:
    with pytest.raises(ManifestError, match="excluded"):
        _manifest(write_yaml, make_paper(duplicate_of="synthetic-0009v1"))
    dup = make_paper(paper_id="d1", status="excluded", duplicate_of="ghost", split=None)
    with pytest.raises(ManifestError, match="unknown"):
        _manifest(write_yaml, dup)
    with pytest.raises(ManifestError, match="itself"):
        _manifest(write_yaml, make_paper(status="excluded", duplicate_of="synthetic-0001v1"))
    with pytest.raises(ManifestError, match="exclusion_reason"):
        _manifest(write_yaml, make_paper(status="excluded"))


@pytest.mark.edge
def test_cluster_cannot_span_splits(write_yaml: Writer) -> None:
    a = make_paper(cluster_id="fam", split="dev")
    b = make_paper(
        paper_id="synthetic-0002v1", title="Two", sha256="b" * 64, cluster_id="fam", split="test"
    )
    with pytest.raises(ManifestError, match="multiple splits"):
        _manifest(write_yaml, a, b)


def test_fingerprint_stable_order_independent_and_sensitive(write_yaml: Writer) -> None:
    a = make_paper()
    b = make_paper(paper_id="synthetic-0002v1", title="Two", sha256="b" * 64)
    f1 = corpus_fingerprint(_manifest(write_yaml, a, b))
    f2 = corpus_fingerprint(_manifest(write_yaml, b, a))
    f3 = corpus_fingerprint(
        _manifest(
            write_yaml, a, make_paper(paper_id="synthetic-0002v1", title="Two", sha256="d" * 64)
        )
    )
    assert f1 == f2 and f1 != f3 and f1.startswith("corpus-")


def test_verify_files(write_yaml: Writer, tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "one.pdf").write_bytes(b"hello")
    good = hashlib.sha256(b"hello").hexdigest()
    assert sha256_file(raw / "one.pdf") == good
    assert verify_files(_manifest(write_yaml, make_paper(sha256=good)), raw) == []
    assert "mismatch" in verify_files(_manifest(write_yaml, make_paper()), raw)[0]
    assert (
        "missing" in verify_files(_manifest(write_yaml, make_paper(local_path="gone.pdf")), raw)[0]
    )


@pytest.mark.edge
def test_load_manifest_errors(tmp_path: Path) -> None:
    with pytest.raises(ManifestError):
        load_manifest(tmp_path / "missing.yaml")
    bad = tmp_path / "bad.yaml"
    bad.write_text("papers: not-a-list\n", encoding="utf-8")
    with pytest.raises(ManifestError):
        load_manifest(bad)


# ---- model registry / readiness ----------------------------------------------------------
def test_real_registry_and_references(repo_root: Path) -> None:
    settings = load_settings(environ={}, root=repo_root)
    resolved = validate_references(settings, load_registry(settings, repo_root))
    assert set(resolved) == {
        "embedder_default",
        "reranker_default",
        "nli_default",
        "generator_default",
    }


def test_local_registry_override_is_merged(repo_root: Path, tmp_path: Path) -> None:
    (tmp_path / "configs").mkdir()
    (tmp_path / "configs/models.yaml").write_text(
        (repo_root / "configs/models.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (tmp_path / "configs/models.local.yaml").write_text(
        "models:\n  generator_default:\n    model_id: my-model-2026\n", encoding="utf-8"
    )
    settings = load_settings(environ={}, root=repo_root)
    registry = load_registry(settings, tmp_path)
    assert registry.models["generator_default"].model_id == "my-model-2026"
    assert registry.models["generator_default"].is_pinned
    assert registry.models["embedder_default"].model_id == "BAAI/bge-small-en-v1.5"


@pytest.mark.edge
def test_reference_errors(repo_root: Path) -> None:
    settings = load_settings(
        environ={
            "VERITAS_EMBEDDING__MODEL_REF": "generator_default",
            "VERITAS_RERANKING__MODEL_REF": "nope",
        },
        root=repo_root,
    )
    with pytest.raises(ModelRegistryError) as info:
        validate_references(settings, load_registry(settings, repo_root))
    text = str(info.value)
    assert "expected embedder" in text and "unknown model 'nope'" in text


@pytest.mark.edge
def test_missing_registry_file(repo_root: Path, tmp_path: Path) -> None:
    settings = load_settings(environ={}, root=repo_root)
    with pytest.raises(ModelRegistryError, match="not found"):
        load_registry(settings, tmp_path)


def test_readiness_blocks_unpinned_models_and_empty_manifest(repo_root: Path) -> None:
    settings = load_settings(repo_root / "configs/eval_full.yaml", environ={})
    registry = load_registry(settings, repo_root)
    manifest = load_manifest(repo_root / "data/corpus_manifest.yaml")
    problems = full_evaluation_problems(settings, registry, manifest)
    joined = " | ".join(problems)
    assert "embedding.model_ref" in joined and "generation.model_ref" in joined
    assert "no included papers" in joined
    with pytest.raises(ReproducibilityError):
        assert_ready_for_full_evaluation(settings, registry, manifest)


def test_readiness_flags_dev_mode_and_missing_manifest(repo_root: Path) -> None:
    settings = load_settings(environ={}, root=repo_root)
    problems = full_evaluation_problems(settings, load_registry(settings, repo_root), None)
    assert any("run.mode" in p for p in problems) and any(
        "manifest not loaded" in p for p in problems
    )


# ---- evaluation schema / annotation / leakage -----------------------------------------------
def _item(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "question_id": "q1",
        "question": "Q?",
        "expected_answer": "A.",
        "split": "dev",
        "relevant_paper_ids": ["synthetic-0001v1"],
        "claims": [{"claim_id": "c1", "claim_text": "X holds.", "claim_type": "factual"}],
        "gold_support_labels": {"c1": [{"annotator_id": "ann1", "label": "SUPPORTS"}]},
        "gold_citations": {"c1": ["synthetic-0001v1"]},
    }
    base.update(over)
    return base


def test_eval_item_valid_and_coverage_statement() -> None:
    item = EvalItem.model_validate(_item())
    cov = annotation_coverage([item])
    assert (cov.n_labelled, cov.n_double_annotated) == (1, 0)
    assert agreement_statement(cov) == SINGLE_ANNOTATOR_STATEMENT
    two = EvalItem.model_validate(
        _item(
            gold_support_labels={
                "c1": [
                    {"annotator_id": "ann1", "label": "SUPPORTS"},
                    {"annotator_id": "ann2", "label": "CONTRADICTS"},
                ]
            }
        )
    )
    cov2 = annotation_coverage([item, two])
    assert cov2.double_annotated_fraction == 0.5
    assert "1 of 2" in agreement_statement(cov2)


def test_coverage_with_no_labels_is_undefined() -> None:
    cov = annotation_coverage([])
    assert cov.double_annotated_fraction is None
    assert agreement_statement(cov) == SINGLE_ANNOTATOR_STATEMENT


@pytest.mark.edge
@pytest.mark.parametrize(
    "bad",
    [
        {"gold_support_labels": {"zz": [{"annotator_id": "a", "label": "SUPPORTS"}]}},
        {"gold_support_labels": {"c1": [{"annotator_id": "a", "label": "NOT_VERIFIED"}]}},
        {
            "gold_support_labels": {
                "c1": [
                    {"annotator_id": "a", "label": "SUPPORTS"},
                    {"annotator_id": "a", "label": "SUPPORTS"},
                ]
            }
        },
        {"gold_citations": {"c1": ["other-paper"]}},
        {"split": "validation"},
        {"adjudicated_labels": {"nope": "SUPPORTS"}},
        {"relevant_passages": [{"document_id": "stray", "text": "t"}]},
    ],
)
def test_eval_item_invalid(bad: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        EvalItem.model_validate(_item(**bad))


@pytest.mark.edge
def test_split_leakage_detected(write_yaml: Writer) -> None:
    manifest = _manifest(write_yaml, make_paper(split="test"))
    item = EvalItem.model_validate(_item(split="dev"))
    with pytest.raises(EvaluationDataError, match="split"):
        check_split_consistency([item], manifest)
    check_split_consistency([EvalItem.model_validate(_item(split="test"))], manifest)
    with pytest.raises(EvaluationDataError, match="not in manifest"):
        check_split_consistency(
            [
                EvalItem.model_validate(
                    _item(relevant_paper_ids=["synthetic-0001v1", "ghost"], gold_citations={})
                )
            ],
            manifest,
        )
