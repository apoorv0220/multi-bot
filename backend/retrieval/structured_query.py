from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


IntentType = Literal["catalog", "support", "general"]
CategoryApply = Literal["filter", "hint"]
FacetCombine = Literal["OR", "AND"]


@dataclass
class CategorySpec:
    values: list[str] = field(default_factory=list)
    confidence: float = 0.0
    apply: CategoryApply = "hint"

    def to_dict(self) -> dict[str, Any]:
        return {
            "values": list(self.values),
            "confidence": self.confidence,
            "apply": self.apply,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "CategorySpec":
        if not data:
            return cls()
        return cls(
            values=[str(v) for v in (data.get("values") or [])],
            confidence=float(data.get("confidence") or 0.0),
            apply=data.get("apply") or "hint",  # type: ignore[arg-type]
        )


@dataclass
class FacetSpec:
    values: list[str] = field(default_factory=list)
    combine: FacetCombine = "OR"

    def to_dict(self) -> dict[str, Any]:
        return {"values": list(self.values), "combine": self.combine}

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "FacetSpec":
        if not data:
            return cls()
        combine = data.get("combine") or "OR"
        if combine not in ("OR", "AND"):
            combine = "OR"
        return cls(
            values=[str(v) for v in (data.get("values") or [])],
            combine=combine,  # type: ignore[arg-type]
        )


@dataclass
class PriceSpec:
    min: float | None = None
    max: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"min": self.min, "max": self.max}

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "PriceSpec":
        if not data:
            return cls()
        return cls(
            min=data.get("min"),
            max=data.get("max"),
        )


@dataclass
class SessionSpec:
    inherit: bool = True
    clear: dict[str, Any] = field(default_factory=lambda: {
        "facets": [],
        "category": False,
        "price": False,
        "stock_status": False,
    })

    def to_dict(self) -> dict[str, Any]:
        return {"inherit": self.inherit, "clear": dict(self.clear)}

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "SessionSpec":
        if not data:
            return cls()
        clear = dict(data.get("clear") or {})
        clear.setdefault("facets", [])
        clear.setdefault("category", False)
        clear.setdefault("price", False)
        clear.setdefault("stock_status", False)
        return cls(inherit=bool(data.get("inherit", True)), clear=clear)


@dataclass
class StructuredQuery:
    intent: IntentType = "general"
    free_text: str = ""
    retrieval_rewrite: str = ""
    category: CategorySpec = field(default_factory=CategorySpec)
    facets: dict[str, FacetSpec] = field(default_factory=dict)
    price: PriceSpec = field(default_factory=PriceSpec)
    stock_status: str | None = None
    session: SessionSpec = field(default_factory=SessionSpec)

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "free_text": self.free_text,
            "retrieval_rewrite": self.retrieval_rewrite,
            "category": self.category.to_dict(),
            "facets": {k: v.to_dict() for k, v in self.facets.items()},
            "price": self.price.to_dict(),
            "stock_status": self.stock_status,
            "session": self.session.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "StructuredQuery":
        if not data:
            return cls()
        intent = data.get("intent") or "general"
        if intent not in ("catalog", "support", "general"):
            intent = "general"
        facets_raw = data.get("facets") or {}
        facets = {str(k): FacetSpec.from_dict(v) for k, v in facets_raw.items() if isinstance(v, dict)}
        return cls(
            intent=intent,  # type: ignore[arg-type]
            free_text=str(data.get("free_text") or "").strip(),
            retrieval_rewrite=str(data.get("retrieval_rewrite") or "").strip(),
            category=CategorySpec.from_dict(data.get("category")),
            facets=facets,
            price=PriceSpec.from_dict(data.get("price")),
            stock_status=data.get("stock_status"),
            session=SessionSpec.from_dict(data.get("session")),
        )

    def copy(self) -> "StructuredQuery":
        return StructuredQuery.from_dict(self.to_dict())


def empty_structured_query(*, intent: IntentType = "general") -> StructuredQuery:
    return StructuredQuery(intent=intent)
