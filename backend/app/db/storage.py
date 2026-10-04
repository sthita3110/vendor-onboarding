"""Upload storage, content-addressed: <uploads_dir>/<case_id>/<sha256><ext>.

Naming by hash means a re-uploaded identical file isn't stored twice, the stored file can be verified
against its recorded hash, and the user's filename (kept in the DB) never becomes a filesystem path.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from app.config import get_settings
from app.documents.inspect import sniff_mime

_EXT = {"application/pdf": ".pdf", "image/png": ".png", "image/jpeg": ".jpg"}


def uploads_root() -> Path:
    return get_settings().uploads_dir


def store_file(case_id: int, data: bytes) -> tuple[str, str]:
    """Write bytes; return (sha256, path relative to the uploads root)."""
    sha = hashlib.sha256(data).hexdigest()
    rel = Path(str(case_id)) / f"{sha}{_EXT.get(sniff_mime(data) or '', '.bin')}"
    dest = uploads_root() / rel
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, dest)
    return sha, str(rel)


def read_file(rel_path: str) -> bytes:
    return (uploads_root() / rel_path).read_bytes()
