import argparse
import json
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy import select, update

from db import SessionLocal
from models import ChatSession, ChatVisitor, SessionExperienceRating


@dataclass
class DedupeStats:
    visitors_scanned: int = 0
    duplicate_groups: int = 0
    duplicate_profiles_removed: int = 0
    sessions_repointed: int = 0
    ratings_repointed: int = 0


def _normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def _sort_key(visitor: ChatVisitor) -> tuple[datetime, str]:
    return (visitor.created_at, str(visitor.id))


def run_dedupe(*, tenant_id: Optional[str], apply_changes: bool) -> dict:
    db = SessionLocal()
    stats = DedupeStats()
    try:
        stmt = select(ChatVisitor)
        tenant_uuid = None
        if tenant_id:
            tenant_uuid = uuid.UUID(tenant_id)
            stmt = stmt.where(ChatVisitor.tenant_id == tenant_uuid)
        visitors = db.execute(stmt).scalars().all()
        stats.visitors_scanned = len(visitors)

        grouped: dict[tuple[uuid.UUID, str], list[ChatVisitor]] = defaultdict(list)
        for visitor in visitors:
            email_norm = _normalize_email(visitor.email)
            if not email_norm:
                continue
            grouped[(visitor.tenant_id, email_norm)].append(visitor)

        preview = []
        for (group_tenant_id, email_norm), rows in grouped.items():
            if len(rows) < 2:
                continue
            stats.duplicate_groups += 1
            rows = sorted(rows, key=_sort_key)
            canonical = rows[0]
            duplicates = rows[1:]

            preview.append(
                {
                    "tenant_id": str(group_tenant_id),
                    "email": email_norm,
                    "canonical_visitor_id": canonical.visitor_id,
                    "duplicate_visitor_ids": [d.visitor_id for d in duplicates],
                }
            )

            for duplicate in duplicates:
                sessions_result = db.execute(
                    update(ChatSession)
                    .where(
                        ChatSession.tenant_id == duplicate.tenant_id,
                        ChatSession.visitor_id == duplicate.visitor_id,
                    )
                    .values(
                        visitor_id=canonical.visitor_id,
                        visitor_name=canonical.name,
                        visitor_email=canonical.email,
                    )
                )
                ratings_result = db.execute(
                    update(SessionExperienceRating)
                    .where(
                        SessionExperienceRating.tenant_id == duplicate.tenant_id,
                        SessionExperienceRating.visitor_id == duplicate.visitor_id,
                    )
                    .values(visitor_id=canonical.visitor_id)
                )
                db.delete(duplicate)
                stats.sessions_repointed += sessions_result.rowcount or 0
                stats.ratings_repointed += ratings_result.rowcount or 0
                stats.duplicate_profiles_removed += 1

        if apply_changes:
            db.commit()
        else:
            db.rollback()

        return {
            "mode": "apply" if apply_changes else "dry-run",
            "tenant_id": str(tenant_uuid) if tenant_uuid else None,
            "stats": {
                "visitors_scanned": stats.visitors_scanned,
                "duplicate_groups": stats.duplicate_groups,
                "duplicate_profiles_removed": stats.duplicate_profiles_removed,
                "sessions_repointed": stats.sessions_repointed,
                "ratings_repointed": stats.ratings_repointed,
            },
            "preview": preview[:20],
            "preview_truncated": len(preview) > 20,
        }
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(
        description="Deduplicate tenant visitors by normalized email and repoint session/rating references."
    )
    parser.add_argument("--tenant-id", help="Optional tenant UUID. If omitted, processes all tenants.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist changes. Without this flag, command runs as dry-run and rolls back.",
    )
    args = parser.parse_args()

    result = run_dedupe(tenant_id=args.tenant_id, apply_changes=args.apply)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
