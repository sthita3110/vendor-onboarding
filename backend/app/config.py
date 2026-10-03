"""Runtime settings from environment variables, with backend/.env loaded for local development.

On Render, set these in the dashboard; .env is git-ignored and never deployed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

_BACKEND = Path(__file__).resolve().parents[1]
load_dotenv(_BACKEND / ".env")


@dataclass(frozen=True)
class Settings:
    openai_api_key: str | None
    openai_model: str
    openai_timeout_s: float
    openai_reasoning_effort: str | None  # only sent if set (reasoning models)
    extraction_cache: bool = True  # EXTRACTION_CACHE=off forces a live model call every time
    extraction_cache_dir: Path = _BACKEND / "data" / "cache" / "extractions"


def get_settings() -> Settings:
    return Settings(
        openai_api_key=os.getenv("OPENAI_API_KEY") or None,
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4.1"),
        openai_timeout_s=float(os.getenv("OPENAI_TIMEOUT_S", "45")),
        openai_reasoning_effort=os.getenv("OPENAI_REASONING_EFFORT") or None,
        extraction_cache=os.getenv("EXTRACTION_CACHE", "on").lower() != "off",
        extraction_cache_dir=Path(os.getenv("EXTRACTION_CACHE_DIR", str(_BACKEND / "data" / "cache" / "extractions"))),
    )
