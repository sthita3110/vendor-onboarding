"""Run all check stages for a case and decide. Phase 3's orchestrator wraps STAGES one by one
to record per-stage events for the live run view; this function is the synchronous equivalent."""

from __future__ import annotations

from app.adapters.mock import MockGstRegistry, MockPennyDrop
from app.domain.models import CaseInput, Evaluation
from app.reference.data import REFERENCE_DIR, load_reference
from app.rules.checks import STAGES, EvaluationContext, RunState
from app.rules.engine import decide


def default_context() -> EvaluationContext:
    return EvaluationContext(
        ref=load_reference(),
        registry=MockGstRegistry.from_file(REFERENCE_DIR / "gst_registry.json"),
        bank=MockPennyDrop.from_file(REFERENCE_DIR / "penny_drop.json"),
    )


def evaluate(case: CaseInput, ctx: EvaluationContext | None = None) -> Evaluation:
    state = RunState(case=case, ctx=ctx or default_context())
    for _key, _label, run_stage in STAGES:
        run_stage(state)
    return Evaluation(decision=decide(state.results), results=state.results)
