from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from app.schemas.claims import ClaimRecord, ConfidenceComponents
from app.schemas.documents import ChunkRecord, make_chunk_id
from app.schemas.enums import CitationStatus, ClaimType, VerificationStatus
from app.schemas.models import ModelSpec
from app.schemas.verification import (
    CitationCheck,
    EvidenceCoverageResult,
    EvidencePassage,
    NliProbabilities,
)

pytestmark = pytest.mark.unit


def _chunk(**kw: Any) -> ChunkRecord:
    base: dict[str, Any] = {
        "document_id": "doc1",
        "paper_title": "T",
        "authors": ("A", "B"),
        "year": 2020,
        "section": "Intro",
        "page_number": 2,
        "chunk_id": make_chunk_id("doc1", 3),
        "text": "some text",
        "source_file": "doc1.pdf",
        "chunk_strategy": "section",
    }
    base.update(kw)
    return ChunkRecord(**base)


def _passage() -> EvidencePassage:
    return EvidencePassage(chunk_id="doc1::c00001", document_id="doc1", text="evidence")


def test_chunk_id_format_and_store_metadata() -> None:
    assert make_chunk_id("doc1", 3) == "doc1::c00003"
    meta = _chunk(section=None, page_number=None).to_store_metadata()
    assert "section" not in meta and "page_number" not in meta
    assert meta["authors"] == "A; B"
    assert all(isinstance(v, (str, int, float, bool)) for v in meta.values())


@pytest.mark.edge
@pytest.mark.parametrize(
    "kw",
    [
        {"text": "   "},
        {"chunk_id": "other::c00001"},
        {"page_number": 0},
        {"char_start": 10, "char_end": 5},
        {"chunk_strategy": "magic"},
        {"document_id": "bad id!"},
        {"unexpected": 1},
    ],
)
def test_chunk_invalid(kw: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        _chunk(**kw)


@pytest.mark.edge
def test_negative_chunk_index() -> None:
    with pytest.raises(ValueError):
        make_chunk_id("d", -1)


def test_claim_defaults_to_not_verified() -> None:
    claim = ClaimRecord(
        claim_id="c1", claim_text="x", claim_type=ClaimType.FACTUAL, source_answer="a"
    )
    assert claim.verification_status == VerificationStatus.NOT_VERIFIED
    assert claim.confidence is None


@pytest.mark.edge
@pytest.mark.parametrize("status", [VerificationStatus.SUPPORTS, VerificationStatus.CONTRADICTS])
def test_decided_claim_requires_evidence(status: VerificationStatus) -> None:
    with pytest.raises(ValidationError, match="requires evidence"):
        ClaimRecord(
            claim_id="c1",
            claim_text="x",
            claim_type=ClaimType.FACTUAL,
            source_answer="a",
            verification_status=status,
        )


def test_insufficient_evidence_needs_no_passages_and_evolve_validates() -> None:
    claim = ClaimRecord(
        claim_id="c1", claim_text="x", claim_type=ClaimType.FACTUAL, source_answer="a"
    )
    done = claim.evolve(verification_status=VerificationStatus.DOES_NOT_PROVIDE_ENOUGH_EVIDENCE)
    assert done.verification_status.value.startswith("DOES_NOT")
    with pytest.raises(ValidationError):
        claim.evolve(verification_status=VerificationStatus.SUPPORTS)  # cannot bypass invariant
    assert claim.evolve(
        verification_status=VerificationStatus.SUPPORTS, evidence_passages=(_passage(),)
    )


@pytest.mark.edge
def test_confidence_requires_components_and_range() -> None:
    kw: dict[str, Any] = {
        "claim_id": "c1",
        "claim_text": "x",
        "claim_type": ClaimType.FACTUAL,
        "source_answer": "a",
    }
    with pytest.raises(ValidationError, match="components"):
        ClaimRecord(**kw, confidence=0.9)
    with pytest.raises(ValidationError):
        ClaimRecord(**kw, confidence=1.5, confidence_components=ConfidenceComponents())
    assert ClaimRecord(
        **kw, confidence=0.4, confidence_components=ConfidenceComponents(n_independent_sources=1)
    )


def test_claims_are_immutable() -> None:
    claim = ClaimRecord(
        claim_id="c1", claim_text="x", claim_type=ClaimType.FACTUAL, source_answer="a"
    )
    with pytest.raises(ValidationError):
        claim.claim_text = "y"  # type: ignore[misc]


@pytest.mark.edge
def test_citation_check_invariants() -> None:
    ok = CitationCheck(
        citation_id="1",
        claim_id="c1",
        cited_document_id="doc1",
        exists_in_corpus=True,
        status=CitationStatus.VALID_SUPPORT,
        evidence_chunk_ids=("doc1::c00001",),
    )
    assert ok.status == CitationStatus.VALID_SUPPORT
    with pytest.raises(ValidationError, match="evidence"):
        CitationCheck(
            citation_id="1",
            claim_id="c1",
            cited_document_id="doc1",
            exists_in_corpus=True,
            status=CitationStatus.VALID_SUPPORT,
        )
    with pytest.raises(ValidationError, match="exist"):
        CitationCheck(
            citation_id="1",
            claim_id="c1",
            cited_document_id="doc1",
            exists_in_corpus=False,
            status=CitationStatus.PARTIAL_SUPPORT,
            evidence_chunk_ids=("x",),
        )
    with pytest.raises(ValidationError, match="MISSING"):
        CitationCheck(
            citation_id="1",
            claim_id="c1",
            cited_document_id="doc1",
            exists_in_corpus=False,
            status=CitationStatus.MISSING_CITATION,
        )
    assert CitationCheck(
        citation_id="-",
        claim_id="c1",
        exists_in_corpus=False,
        status=CitationStatus.MISSING_CITATION,
    )


def test_nli_probabilities_sum() -> None:
    assert NliProbabilities(entailment=0.7, contradiction=0.2, neutral=0.1)
    with pytest.raises(ValidationError, match="sum"):
        NliProbabilities(entailment=0.9, contradiction=0.9, neutral=0.9)


@pytest.mark.edge
def test_ecs_result_undefined_when_nothing_scored() -> None:
    zero = dict(
        n_scored=0, n_supported=0, n_partial=0, n_insufficient=0, n_contradicted=0, n_excluded=2
    )
    assert EvidenceCoverageResult(**zero, undefined_reason="no factual claims").score is None
    with pytest.raises(ValidationError):
        EvidenceCoverageResult(
            **zero, score=1.0, undefined_reason="x"
        )  # never report 1.0 for empty
    with pytest.raises(ValidationError):
        EvidenceCoverageResult(**zero)  # reason required
    with pytest.raises(ValidationError):
        EvidenceCoverageResult(
            n_scored=2,
            n_supported=1,
            n_partial=0,
            n_insufficient=0,
            n_contradicted=0,
            n_excluded=0,
            score=0.5,
        )
    assert EvidenceCoverageResult(
        n_scored=2,
        n_supported=1,
        n_partial=1,
        n_insufficient=0,
        n_contradicted=0,
        n_excluded=0,
        score=0.75,
    )


def test_model_spec_pinning() -> None:
    hf = dict(role="embedder", provider="huggingface_local", model_id="org/m")
    assert not ModelSpec(**hf).is_pinned
    assert not ModelSpec(**hf, revision="main").is_pinned
    assert ModelSpec(**hf, revision="a" * 40).is_pinned
    api = dict(role="generator", provider="openai_compatible")
    assert not ModelSpec(**api).is_pinned
    assert ModelSpec(**api, model_id="x-2026-01-01").is_pinned


@pytest.mark.edge
def test_model_spec_invalid() -> None:
    with pytest.raises(ValidationError):
        ModelSpec(role="embedder", provider="huggingface_local")
    with pytest.raises(ValidationError):
        ModelSpec(role="generator", provider="openai_compatible", model_id="m", revision="a" * 40)


@pytest.mark.edge
def test_text_unit_page_end_validation() -> None:
    from app.schemas.enums import ParseStatus  # noqa: F401
    from app.schemas.ingestion import TextUnit, UnitKind

    base: dict[str, Any] = {
        "unit_id": "d::p1",
        "document_id": "d",
        "page_number": 3,
        "kind": UnitKind.PARAGRAPH,
        "text": "abc",
        "char_start": 0,
        "char_end": 3,
        "bbox": (0.0, 0.0, 1.0, 1.0),
    }
    assert TextUnit(**base, page_end=4).page_end == 4
    with pytest.raises(ValidationError, match="page_end"):
        TextUnit(**base, page_end=2)
