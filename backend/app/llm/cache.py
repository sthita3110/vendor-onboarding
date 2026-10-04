"""Extraction cache: raw model output keyed by file content + everything that shapes the output.

Key = sha256(file bytes) + hash(prompt version, model, request settings). Renaming a file doesn't
change the key; changing one byte, the prompt, or the model does. Only the raw model output is cached —
grounding and rules are recomputed every time, so changing them never needs a cache flush.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from app.config import Settings, get_settings
from app.llm.prompts import PROMPT_VERSION

REQUEST_SETTINGS = "pdf-detail-high|temperature-0"  # bump if the request shape changes


def cache_key(data: bytes, model: str) -> str:
    content = hashlib.sha256(data).hexdigest()
    config = hashlib.sha256(f"{PROMPT_VERSION}|{model}|{REQUEST_SETTINGS}".encode()).hexdigest()[:12]
    return f"{content}-{config}"


def make_cache(settings: Settings | None = None) -> "ExtractionCache | None":
    s = settings or get_settings()
    return ExtractionCache(s.extraction_cache_dir) if s.extraction_cache else None


class ExtractionCache:
    def __init__(self, directory: Path):
        self.directory = directory

    def get(self, key: str) -> dict[str, Any] | None:
        path = self.directory / f"{key}.json"
        try:
            return json.loads(path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    def put(self, key: str, entry: dict[str, Any]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        tmp = self.directory / f".{key}.tmp"
        tmp.write_text(json.dumps(entry))
        os.replace(tmp, self.directory / f"{key}.json")  # atomic: no half-written entries
