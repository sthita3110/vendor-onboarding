"""FastAPI app: startup (tables, interrupted-run recovery, demo seeding), passcode gate, API routes,
and the built frontend (one URL for the whole product)."""

from __future__ import annotations

import hmac
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.config import get_settings
from app.db.engine import init_db
from app.pipeline.runner import recover_interrupted_runs
from app.pipeline.seed import seed_demo_cases
from app.rules.catalog import CATALOG_VERSION


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    init_db()
    recover_interrupted_runs()  # any run "in progress" at boot was cut off by a restart: fail closed
    if get_settings().seed_demo:
        seed_demo_cases()  # only if the database is empty; never executes the pipeline
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


# ---------- frontend (registered last so /api/* always wins) ----------

_dist = get_settings().frontend_dist
if (_dist / "index.html").is_file():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        """Client-side routes (/cases/3, /runs/7, …) all load index.html; React Router takes over.
        Unknown /api paths stay JSON 404s instead of returning the app."""
        if path.startswith("api/"):
            raise HTTPException(404, "Not found")
        file = (_dist / path).resolve()
        if path and file.is_file() and file.is_relative_to(_dist.resolve()):
            return FileResponse(file)
        return FileResponse(_dist / "index.html")
