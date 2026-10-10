"""Evidence, citation-check and Evidence Coverage Score result contracts."""

from __future__ import annotations

from pydantic import Field, model_validator

from app.schemas.base import IdStr, StrictModel
from app.schemas.enums import CitationStatus, NliLabel

_PROB_TOLERANCE = 1e-2


class NliProbabilities(StrictModel):
    """Softmax output of an entailment model for (evidence premise, claim hypothesis)."""

    entailment: float = Field(ge=0.0, le=1.0)
    contradiction: float = Field(ge=0.0, le=1.0)
    neutral: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _sums_to_one(self) -> NliProbabilities:
        total = self.entailment + self.contradiction + self.neutral
        if abs(total - 1.0) > _PROB_TOLERANCE:
            raise ValueError(f"NLI probabilities must sum to 1 (got {total:.4f})")
        return self


class EvidencePassage(StrictModel):
    """A retrieved passage plus the scores that justified using it."""

    chunk_id: str
    document_id: IdStr
    text: str = Field(min_length=1)
    section: str | None = None
    page_number: int | None = Field(default=None, ge=1)
    retrieval_score: float | None = None
    rerank_score: float | None = None
    nli_label: NliLabel | None = None
    nli_probabilities: NliProbabilities | None = None


class CitationCheck(StrictModel):
    """Result of verifying one citation attached to one claim."""

    citation_id: str
    claim_id: str
    cited_document_id: IdStr | None = None
    exists_in_corpus: bool
    status: CitationStatus
    evidence_chunk_ids: tuple[str, ...] = ()
    notes: str = ""

    @model_validator(mode="after")
    def _support_requires_evidence(self) -> CitationCheck:
        if self.status in {CitationStatus.VALID_SUPPORT, CitationStatus.PARTIAL_SUPPORT}:
            if not self.exists_in_corpus:
                raise ValueError("a supporting citation must exist in the corpus")
            if not self.evidence_chunk_ids:
                raise ValueError("a supporting citation must name evidence chunks")
        if self.status == CitationStatus.MISSING_CITATION and self.cited_document_id is not None:
            raise ValueError("MISSING_CITATION cannot name a cited document")
        return self


class EvidenceCoverageResult(StrictModel):
    """Output of the Evidence Coverage Score computation (formula: Phase 12).

    ``score`` is ``None`` (undefined) when no scorable claims exist; it is never
    reported as 1.0 or 0.0 in that case.
    """

    score: float | None = Field(default=None, ge=0.0, le=1.0)
    n_scored: int = Field(ge=0)
    n_supported: int = Field(ge=0)
    n_partial: int = Field(ge=0)
    n_insufficient: int = Field(ge=0)
    n_contradicted: int = Field(ge=0)
    n_excluded: int = Field(ge=0)
    undefined_reason: str | None = None

    @model_validator(mode="after")
    def _check(self) -> EvidenceCoverageResult:
        counted = self.n_supported + self.n_partial + self.n_insufficient + self.n_contradicted
        if counted != self.n_scored:
            raise ValueError("per-status counts must sum to n_scored")
        if self.n_scored == 0:
            if self.score is not None or not self.undefined_reason:
                raise ValueError("score must be None with a reason when n_scored == 0")
        elif self.score is None:
            raise ValueError("score must be defined when n_scored > 0")
        return self
