#!/usr/bin/env python3
"""Build backend/dialogue/data/golden.jsonl from acceptance + bitext + manual rows."""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[2]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from dialogue.acceptance_golden import acceptance_rows, manual_rows  # noqa: E402
from dialogue.registry import load_registry  # noqa: E402
from dialogue.scripts.sample_bitext_for_eval import sample_bitext_rows  # noqa: E402

GOLDEN_PATH = _BACKEND / "dialogue" / "data" / "golden.jsonl"
BITEXT_CSV = _BACKEND.parent / "data" / "bitext-retail-ecommerce-llm-chatbot-training-dataset.csv"


def build_corpus() -> list[dict]:
    registry = load_registry()
    rows: list[dict] = []
    seen_ids: set[str] = set()

    def add(row: dict) -> None:
        rid = row["id"]
        if rid in seen_ids:
            raise ValueError(f"duplicate golden id: {rid}")
        if row["expected_intent"] not in registry.intent_ids():
            raise ValueError(f"unknown intent {row['expected_intent']!r} in {rid}")
        seen_ids.add(rid)
        rows.append(row)

    for row in acceptance_rows():
        add(row)
    for row in manual_rows():
        add(row)

    if BITEXT_CSV.is_file():
        for row in sample_bitext_rows(csv_path=BITEXT_CSV, per_intent=8, max_total=350):
            add(row)

    # Ensure every registry intent has >=1 row
    covered = {r["expected_intent"] for r in rows}
    for intent_id in sorted(registry.intent_ids()):
        if intent_id in covered:
            continue
        intent = registry.get_intent(intent_id)
        record = {
            "id": f"gen-gap-{intent_id}",
            "utterance": f"placeholder utterance for {intent_id.replace('_', ' ')}",
            "expected_intent": intent_id,
            "source": "generated",
            "expected_policy": "proceed",
            "eval_layers": ["nlu"],
            "tags": ["gap_fill"],
            "notes": "auto gap-fill for registry coverage",
        }
        if intent.execution.value == "coming_soon":
            record["expected_execution"] = "coming_soon"
        add(record)

    return rows


def coverage_stats(rows: list[dict]) -> dict:
    by_source = Counter(r["source"] for r in rows)
    by_intent = Counter(r["expected_intent"] for r in rows)
    clarify = sum(1 for r in rows if r.get("expected_policy") == "clarify")
    multi = sum(1 for r in rows if r.get("session_seed") or r.get("turns"))
    confused_detail = sum(
        1
        for r in rows
        if "confused_pair" in r.get("tags", [])
        and r.get("expected_intent") == "product_detail"
    )
    confused_avail = sum(
        1
        for r in rows
        if "confused_pair" in r.get("tags", [])
        and r.get("expected_intent") == "variant_availability"
    )
    confused_new = sum(
        1
        for r in rows
        if "confused_pair" in r.get("tags", [])
        and r.get("expected_intent") == "new_search"
    )
    confused_refine = sum(
        1
        for r in rows
        if "confused_pair" in r.get("tags", [])
        and r.get("expected_intent") == "refine_search"
    )
    return {
        "total_rows": len(rows),
        "by_source": dict(by_source),
        "unique_intents": len(by_intent),
        "clarify_rows": clarify,
        "multi_turn_rows": multi,
        "confused_product_detail": confused_detail,
        "confused_variant_availability": confused_avail,
        "confused_new_search": confused_new,
        "confused_refine_search": confused_refine,
        "by_intent": dict(sorted(by_intent.items())),
    }


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> int:
    rows = build_corpus()
    write_jsonl(GOLDEN_PATH, rows)
    stats = coverage_stats(rows)
    print(json.dumps(stats, indent=2))
    print(f"Wrote {len(rows)} rows to {GOLDEN_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
