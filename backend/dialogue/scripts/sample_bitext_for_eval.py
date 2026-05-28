#!/usr/bin/env python3
"""Sample Bitext CSV utterances for golden eval (stratified per canonical intent)."""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
import sys
from collections import defaultdict
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[2]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from dialogue.registry import load_registry  # noqa: E402

DEFAULT_CSV = (
    Path(__file__).resolve().parents[3]
    / "data"
    / "bitext-retail-ecommerce-llm-chatbot-training-dataset.csv"
)


def _slug(text: str, intent: str, idx: int) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:32]
    return f"bitext-{intent}-{idx}-{base}"


def sample_bitext_rows(
    *,
    csv_path: Path,
    per_intent: int = 8,
    seed: int = 42,
    max_total: int = 350,
) -> list[dict]:
    registry = load_registry()
    by_intent: dict[str, list[str]] = defaultdict(list)

    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            bitext_label = (row.get("intent") or "").strip()
            utterance = (row.get("instruction") or "").strip()
            if not bitext_label or not utterance or len(utterance) < 4:
                continue
            canonical = registry.map_bitext_label(bitext_label)
            if not canonical:
                continue
            if len(utterance) > 240:
                continue
            by_intent[canonical].append(utterance)

    rng = random.Random(seed)
    out: list[dict] = []
    for intent_id in sorted(by_intent.keys()):
        pool = by_intent[intent_id]
        if not pool:
            continue
        rng.shuffle(pool)
        take = min(per_intent, len(pool))
        for i, utterance in enumerate(pool[:take]):
            record = {
                "id": _slug(utterance, intent_id, i),
                "utterance": utterance,
                "expected_intent": intent_id,
                "source": "bitext",
                "expected_policy": "proceed",
                "eval_layers": ["nlu"],
                "tags": ["bitext"],
            }
            intent_def = registry.get_intent(intent_id)
            if intent_def.execution.value == "coming_soon":
                record["expected_execution"] = "coming_soon"
            out.append(record)
            if len(out) >= max_total:
                return out
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Sample Bitext rows for golden.jsonl")
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--per-intent", type=int, default=8)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-total", type=int, default=350)
    parser.add_argument("--dry-run", action="store_true", help="Print summary only")
    parser.add_argument("--output", type=Path, help="Write JSONL to path")
    args = parser.parse_args()

    if not args.csv.is_file():
        print(f"Bitext CSV not found: {args.csv}", file=sys.stderr)
        return 1

    rows = sample_bitext_rows(
        csv_path=args.csv,
        per_intent=args.per_intent,
        seed=args.seed,
        max_total=args.max_total,
    )

    by_intent: dict[str, int] = defaultdict(int)
    for row in rows:
        by_intent[row["expected_intent"]] += 1

    print(f"Sampled {len(rows)} bitext rows across {len(by_intent)} intents")
    for intent_id, count in sorted(by_intent.items(), key=lambda x: (-x[1], x[0]))[:15]:
        print(f"  {intent_id}: {count}")
    if len(by_intent) > 15:
        print(f"  ... and {len(by_intent) - 15} more intents")

    if args.dry_run:
        return 0

    if args.output:
        with args.output.open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"Wrote {args.output}")
    else:
        for row in rows:
            print(json.dumps(row, ensure_ascii=False))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
