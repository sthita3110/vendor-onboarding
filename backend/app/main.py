"""FastAPI app. Phase 1 exposes the decision core directly; Phase 3 adds cases, runs, and review."""

from __future__ import annotations

import json
from functools import lru_cache

from fastapi import FastAPI, HTTPException

from app.domain.models import CaseInput, Evaluation
from app.reference.data import SAMPLES_DIR
from app.rules.catalog import CATALOG_VERSION, RULES
from app.rules.checks import EvaluationContext
from app.rules.evaluate import default_context, evaluate

app = FastAPI(title="Vendor Onboarding", version="0.1.0")


@lru_cache
def context() -> EvaluationContext:
    return default_context()


def _samples() -> dict[str, dict]:
    return {p.stem: json.loads(p.read_text()) for p in sorted(SAMPLES_DIR.glob("*.json"))}


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "rule_catalog_version": CATALOG_VERSION}


@app.get("/api/rules")
def rules() -> list[dict]:
    return [
        {"id": r.id, "stage": r.stage, "group": r.group, "name": r.name,
         "outcome": r.outcome.value, "required": r.required}
        for r in RULES.values()
    ]


@app.get("/api/samples")
def list_samples() -> list[dict]:
    return [{"id": s["id"], "title": s["title"], "description": s["description"]} for s in _samples().values()]


@app.get("/api/samples/{sample_id}")
def get_sample(sample_id: str) -> dict:
    sample = _samples().get(sample_id)
    if sample is None:
        raise HTTPException(404, f"Unknown sample '{sample_id}'")
    return {k: sample[k] for k in ("id", "title", "description", "case")}  # expected outcome not exposed


@app.post("/api/evaluate")
def evaluate_case(case: CaseInput) -> Evaluation:
    return evaluate(case, context())


@app.post("/api/samples/{sample_id}/evaluate")
def evaluate_sample(sample_id: str) -> Evaluation:
    return evaluate_case(CaseInput.model_validate(get_sample(sample_id)["case"]))
