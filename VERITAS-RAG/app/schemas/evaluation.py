"""Evaluation item contract with per-annotator labels (supports second annotators)."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field, model_validator

from app.schemas.base import IdStr, StrictModel
from app.schemas.enums import ClaimType, Split, VerificationStatus


class AnnotatorLabel(StrictModel):
    """One annotator's support label for one claim."""

    annotator_id: IdStr
    label: VerificationStatus
    annotated_at: datetime | None = None
    notes: str = ""

    @model_validator(mode="after")
    def _label_is_decided(self) -> AnnotatorLabel:
        if self.label == VerificationStatus.NOT_VERIFIED:
            raise ValueError("NOT_VERIFIED is not a valid gold label")
        return self


class GoldPassage(StrictModel):
    """A passage an annotator marked as relevant evidence."""

    document_id: IdStr
    chunk_id: str | None = None
    text: str = Field(min_length=1)
    page_number: int | None = Field(default=None, ge=1)


class GoldClaim(StrictModel):
    """A claim in the reference answer."""

    claim_id: IdStr
    claim_text: str = Field(min_length=1)
    claim_type: ClaimType


class ContradictionLabel(StrictModel):
    """Which papers support, contradict or qualify a claim."""

    claim_id: IdStr
    supporting_document_ids: tuple[IdStr, ...] = ()
    contradicting_document_ids: tuple[IdStr, ...] = ()
    qualifying_document_ids: tuple[IdStr, ...] = ()


class EvalItem(StrictModel):
    """One evaluation question with gold annotations."""

    question_id: IdStr
    question: str = Field(min_length=1)
    expected_answer: str = Field(min_length=1)
    split: Split
    relevant_paper_ids: tuple[IdStr, ...]
    relevant_passages: tuple[GoldPassage, ...] = ()
    claims: tuple[GoldClaim, ...] = ()
    gold_support_labels: dict[str, tuple[AnnotatorLabel, ...]] = Field(default_factory=dict)
    adjudicated_labels: dict[str, VerificationStatus] = Field(default_factory=dict)
    gold_citations: dict[str, tuple[IdStr, ...]] = Field(default_factory=dict)
    contradiction_labels: tuple[ContradictionLabel, ...] = ()

    @model_validator(mode="after")
    def _check_references(self) -> EvalItem:
        claim_ids = {claim.claim_id for claim in self.claims}
        if len(claim_ids) != len(self.claims):
            raise ValueError("duplicate claim_id within item")
        for name, keys in {
            "gold_support_labels": set(self.gold_support_labels),
            "adjudicated_labels": set(self.adjudicated_labels),
            "gold_citations": set(self.gold_citations),
            "contradiction_labels": {c.claim_id for c in self.contradiction_labels},
        }.items():
            unknown = keys - claim_ids
            if unknown:
                raise ValueError(f"{name} references unknown claim ids: {sorted(unknown)}")
        relevant = set(self.relevant_paper_ids)
        for claim_id, docs in self.gold_citations.items():
            stray = set(docs) - relevant
            if stray:
                raise ValueError(
                    f"gold citation for {claim_id!r} not in relevant_paper_ids: {sorted(stray)}"
                )
        for claim_id, labels in self.gold_support_labels.items():
            annotators = [label.annotator_id for label in labels]
            if len(set(annotators)) != len(annotators):
                raise ValueError(f"claim {claim_id!r} has repeated annotator ids")
        for passage in self.relevant_passages:
            if passage.document_id not in relevant:
                raise ValueError(
                    f"passage document {passage.document_id!r} not in relevant_paper_ids"
                )
        return self
