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
    openai_hedge_after_s: float = 10.0  # send one backup request if a document read is slower than this (0 = off)
    extraction_cache: bool = True  # EXTRACTION_CACHE=off forces a live model call every time
    extraction_cache_dir: Path = _BACKEND / "data" / "cache" / "extractions"
    app_passcode: str | None = None  # if set, endpoints that spend money require X-App-Passcode
    database_url: str = f"sqlite:///{_BACKEND / 'data' / 'app.db'}"
    uploads_dir: Path = _BACKEND / "data" / "uploads"
    mock_latency_ms: int = 400  # simulated provider round-trip; labelled "Simulated provider" in the UI
    seed_demo: bool = True  # on startup, pre-populate demo cases if the database is empty
    frontend_dist: Path = _BACKEND.parent / "frontend" / "dist"  # built React app, served by FastAPI
    demo_reset: bool = True  # allow POST /api/admin/reset-demo (wipe + re-seed); turn off outside demos
    messages_ai: bool = True  # AI-drafted subject/opening/closing for vendor messages (template otherwise)


def get_settings() -> Settings:
    return Settings(
        openai_api_key=os.getenv("OPENAI_API_KEY") or None,
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4.1"),
        openai_timeout_s=float(os.getenv("OPENAI_TIMEOUT_S", "45")),
        openai_reasoning_effort=os.getenv("OPENAI_REASONING_EFFORT") or None,
        openai_hedge_after_s=float(os.getenv("OPENAI_HEDGE_AFTER_S", "10")),
        extraction_cache=os.getenv("EXTRACTION_CACHE", "on").lower() != "off",
        extraction_cache_dir=Path(os.getenv("EXTRACTION_CACHE_DIR", str(_BACKEND / "data" / "cache" / "extractions"))),
        app_passcode=os.getenv("APP_PASSCODE") or None,
        database_url=os.getenv("DATABASE_URL", f"sqlite:///{_BACKEND / 'data' / 'app.db'}"),
        uploads_dir=Path(os.getenv("UPLOADS_DIR", str(_BACKEND / "data" / "uploads"))),
        mock_latency_ms=int(os.getenv("MOCK_LATENCY_MS", "400")),
        seed_demo=os.getenv("SEED_DEMO", "on").lower() != "off",
        frontend_dist=Path(os.getenv("FRONTEND_DIST", str(_BACKEND.parent / "frontend" / "dist"))),
        demo_reset=os.getenv("DEMO_RESET", "on").lower() != "off",
        messages_ai=os.getenv("MESSAGES_AI", "on").lower() != "off",
    )
