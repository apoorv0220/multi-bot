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
    exclude_values: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        blob: dict[str, Any] = {"values": list(self.values), "combine": self.combine}
        if self.exclude_values:
            blob["exclude_values"] = list(self.exclude_values)
        return blob

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
            exclude_values=[str(v) for v in (data.get("exclude_values") or [])],
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
class CatalogCoverageSpec:
    in_catalog: bool | None = None
    missing_terms: list[str] = field(default_factory=list)
    confidence: float = 0.0
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        blob: dict[str, Any] = {
            "missing_terms": list(self.missing_terms),
            "confidence": self.confidence,
        }
        if self.in_catalog is not None:
            blob["in_catalog"] = self.in_catalog
        if self.source:
            blob["source"] = self.source
        return blob

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "CatalogCoverageSpec":
        if not data:
            return cls()
        in_catalog = data.get("in_catalog")
        if in_catalog is not None:
            in_catalog = bool(in_catalog)
        missing = [str(v).strip() for v in (data.get("missing_terms") or []) if str(v).strip()]
        try:
            confidence = float(data.get("confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        return cls(
            in_catalog=in_catalog,
            missing_terms=missing,
            confidence=max(0.0, min(confidence, 1.0)),
            source=str(data.get("source") or "").strip(),
        )


@dataclass
class StructuredQuery:
    intent: IntentType = "general"
    free_text: str = ""
    retrieval_rewrite: str = ""
    category: CategorySpec = field(default_factory=CategorySpec)
    facets: dict[str, FacetSpec] = field(default_factory=dict)
    price: PriceSpec = field(default_factory=PriceSpec)
    stock_status: str | None = None
    sort: str | None = None
    session: SessionSpec = field(default_factory=SessionSpec)
    catalog_coverage: CatalogCoverageSpec = field(default_factory=CatalogCoverageSpec)
    validation_meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        blob: dict[str, Any] = {
            "intent": self.intent,
            "free_text": self.free_text,
            "retrieval_rewrite": self.retrieval_rewrite,
            "category": self.category.to_dict(),
            "facets": {k: v.to_dict() for k, v in self.facets.items()},
            "price": self.price.to_dict(),
            "stock_status": self.stock_status,
            "session": self.session.to_dict(),
        }
        if self.sort:
            blob["sort"] = self.sort
        if self.catalog_coverage.in_catalog is not None or self.catalog_coverage.missing_terms:
            blob["catalog_coverage"] = self.catalog_coverage.to_dict()
        if self.validation_meta:
            blob["validation_meta"] = dict(self.validation_meta)
        return blob

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
            sort=data.get("sort"),
            session=SessionSpec.from_dict(data.get("session")),
            catalog_coverage=CatalogCoverageSpec.from_dict(data.get("catalog_coverage")),
            validation_meta=dict(data.get("validation_meta") or {}),
        )

    def copy(self) -> "StructuredQuery":
        return StructuredQuery.from_dict(self.to_dict())


def empty_structured_query(*, intent: IntentType = "general") -> StructuredQuery:
    return StructuredQuery(intent=intent)
