"""FastAPI app: startup (tables + interrupted-run recovery), passcode gate, routes."""

from __future__ import annotations

import hmac
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException

from app.api.routes import router
from app.config import get_settings
from app.db.engine import init_db
from app.pipeline.runner import recover_interrupted_runs
from app.rules.catalog import CATALOG_VERSION


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    init_db()
    recover_interrupted_runs()  # any run "in progress" at boot was cut off by a restart: fail closed
    yield


def require_passcode(x_app_passcode: str | None = Header(default=None)) -> None:
    """When APP_PASSCODE is set (always in production), the whole API requires it: uploads spend OpenAI
    credit and case data shouldn't be readable by anyone who finds the URL. Open locally when unset."""
    expected = get_settings().app_passcode
    if expected and not hmac.compare_digest(x_app_passcode or "", expected):
        raise HTTPException(401, "Missing or wrong passcode")


app = FastAPI(title="Vendor Onboarding", version="0.3.0", lifespan=lifespan)


@app.get("/api/health")
def health() -> dict:
    """Open (no passcode) so the host's health check works."""
    return {"status": "ok", "rule_catalog_version": CATALOG_VERSION}


app.include_router(router, dependencies=[Depends(require_passcode)])
