"""Shared Pydantic base class and identifier types."""

from __future__ import annotations

from typing import Annotated, Any, TypeVar

from pydantic import BaseModel, ConfigDict, StringConstraints

ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._\-]{0,127}$"
SHA256_PATTERN = r"^[0-9a-f]{64}$"

IdStr = Annotated[str, StringConstraints(pattern=ID_PATTERN)]
Sha256Str = Annotated[str, StringConstraints(pattern=SHA256_PATTERN)]

T = TypeVar("T", bound="StrictModel")


class StrictModel(BaseModel):
    """Immutable model that rejects unknown fields.

    Updates go through :meth:`evolve`, which re-runs validation so invariants
    (e.g. "SUPPORTS requires evidence") cannot be bypassed by ``model_copy``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, protected_namespaces=())

    def evolve(self: T, **changes: Any) -> T:
        """Return a validated copy with ``changes`` applied."""
        data = {name: getattr(self, name) for name in type(self).model_fields}
        data.update(changes)
        return type(self).model_validate(data)
