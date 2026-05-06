"""Local tenant-uploaded files (avatars). Use TENANT_ASSETS_DIR + a Docker volume for persistence."""

from __future__ import annotations

import os
import re
import uuid

def tenant_assets_dir() -> str:
    return os.environ.get("TENANT_ASSETS_DIR", "/tmp/tenant-assets").rstrip("/")


def ensure_tenant_assets_dir() -> str:
    base = tenant_assets_dir()
    os.makedirs(base, exist_ok=True)
    return base


def _normalized_tenant_uuid(tenant_id: str) -> str | None:
    try:
        return str(uuid.UUID(str(tenant_id).strip()))
    except (ValueError, TypeError, AttributeError):
        return None


def _avatar_file_belongs_to_tenant(filename: str, tid_normalized: str) -> bool:
    m = re.match(r"^tenant-([0-9a-fA-F-]{36})-avatar(\.[^/]+)?$", filename, re.I)
    if not m:
        return False
    try:
        return str(uuid.UUID(m.group(1))) == tid_normalized
    except ValueError:
        return False


def remove_local_avatar_files_for_tenant(tenant_id: str) -> None:
    """Delete on-disk avatar variants for this tenant (tenant-<uuid>-avatar*)."""
    tid = _normalized_tenant_uuid(tenant_id)
    if not tid:
        return
    base = tenant_assets_dir()
    if not os.path.isdir(base):
        return
    base_real = os.path.realpath(base)
    try:
        for name in os.listdir(base):
            if not _avatar_file_belongs_to_tenant(name, tid):
                continue
            path = os.path.join(base, name)
            try:
                rp = os.path.realpath(path)
                if not (rp.startswith(base_real + os.sep) or rp == base_real):
                    continue
                if os.path.isfile(rp):
                    os.unlink(rp)
            except OSError:
                continue
    except OSError:
        pass


_ALLOWED_AVATAR_EXT = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif"})


def next_avatar_filename(tenant_id: str, ext: str) -> str:
    tid = _normalized_tenant_uuid(tenant_id)
    if not tid:
        raise ValueError("Invalid tenant_id")
    e = (ext or ".png").lower()
    if not e.startswith("."):
        e = f".{e}"
    if e not in _ALLOWED_AVATAR_EXT:
        e = ".png"
    return f"tenant-{tid}-avatar{e}"
