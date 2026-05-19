from __future__ import annotations

from typing import Any


def _provider_totals(providers: dict[str, Any]) -> tuple[int, int, int]:
    processed = 0
    failed = 0
    touched = 0
    for stats in providers.values():
        stats = stats or {}
        touched += int(stats.get("total_records", 0) or 0)
        processed += (
            int(stats.get("indexed_records", 0) or 0)
            + int(stats.get("deleted_records", 0) or 0)
            + int(stats.get("failed_records", 0) or 0)
        )
        failed += int(stats.get("failed_records", 0) or 0)
    return touched, processed, failed


def normalize_reindex_progress(
    progress: dict[str, Any] | None,
    *,
    planned_total_records: int | None = None,
    job_status: str | None = None,
) -> dict[str, Any]:
    """Unify pipeline provider stats and embedder progress into one API/CLI shape."""
    progress = dict(progress or {})
    providers = dict(progress.get("providers") or {})
    _, processed, failed = _provider_totals(providers)

    planned = planned_total_records
    if planned is None:
        planned = int(progress.get("planned_total_records") or progress.get("total_items") or 0)
    if planned <= 0:
        planned = int(progress.get("total_items") or 0)
    if planned <= 0:
        touched, _, _ = _provider_totals(providers)
        planned = touched

    if planned > 0:
        if job_status == "completed":
            pct = min(100.0, (processed / planned) * 100.0)
        elif job_status == "failed":
            pct = min(100.0, (processed / planned) * 100.0)
        else:
            pct = min(99.0, (processed / planned) * 100.0)
    else:
        pct = float(progress.get("progress_percentage") or 0.0)

    remaining = max(0, planned - processed)
    return {
        "status": progress.get("status") or "processing",
        "planned_total_records": planned,
        "total_items": planned,
        "processed_items": processed,
        "failed_items": failed,
        "remaining_items": remaining,
        "progress_percentage": round(pct, 2),
        "current_batch": int(progress.get("current_batch", 0) or 0),
        "providers": providers,
    }
