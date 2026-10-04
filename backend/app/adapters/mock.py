"""Fixture-backed mock adapters.

Behaviour for identifiers not in the fixtures mirrors a provider sandbox:
- GST registry: unknown GSTIN -> "active" (fixture=False)
- Penny drop: unknown account -> "verified", echoing the submitted holder name (fixture=False)
Both flag `fixture=False` so the UI and audit trail show the answer was a sandbox default.

Every response is marked `simulated=True`, and each call waits `latency_ms` to behave like a provider's
sandbox round-trip (so the stage is visible in the live run view). The UI labels these "Simulated provider".
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from app.adapters.base import AdapterError, BankVerification, GstRegistryRecord
from app.rules.validators import clean_account, clean_id


class MockGstRegistry:
    provider = "mock-gst-registry"

    def __init__(self, fixtures: dict[str, dict], latency_ms: int = 0):
        self._fixtures = {clean_id(k): v for k, v in fixtures.items()}
        self._latency_s = latency_ms / 1000

    @classmethod
    def from_file(cls, path: Path, latency_ms: int = 0) -> "MockGstRegistry":
        return cls(json.loads(path.read_text()), latency_ms)

    def lookup(self, gstin: str) -> GstRegistryRecord:
        time.sleep(self._latency_s)
        key = clean_id(gstin)
        rec = self._fixtures.get(key)
        if rec is None:
            return GstRegistryRecord(gstin=key, status="active", provider=self.provider, fixture=False,
                                     simulated=True)
        return GstRegistryRecord(gstin=key, provider=self.provider, simulated=True, **rec)


class MockPennyDrop:
    provider = "mock-penny-drop"

    def __init__(self, fixtures: dict[str, dict], latency_ms: int = 0):
        self._fixtures = fixtures
        self._latency_s = latency_ms / 1000

    @classmethod
    def from_file(cls, path: Path, latency_ms: int = 0) -> "MockPennyDrop":
        return cls(json.loads(path.read_text()), latency_ms)

    @staticmethod
    def key(account_number: str, ifsc: str) -> str:
        return f"{clean_account(account_number)}|{clean_id(ifsc)}"

    def verify(self, account_number: str, ifsc: str, submitted_holder: str | None = None) -> BankVerification:
        time.sleep(self._latency_s)
        acct, code = clean_account(account_number), clean_id(ifsc)
        rec = self._fixtures.get(self.key(acct, code))
        if rec is None:
            return BankVerification(
                account_number=acct, ifsc=code, status="verified",
                holder_name=submitted_holder, provider=self.provider, fixture=False, simulated=True,
            )
        return BankVerification(account_number=acct, ifsc=code, provider=self.provider, simulated=True, **rec)


class UnavailableAdapter:
    """Simulates a provider outage (failure drill)."""

    def lookup(self, gstin: str) -> GstRegistryRecord:
        raise AdapterError("GST registry unavailable")

    def verify(self, account_number: str, ifsc: str, submitted_holder: str | None = None) -> BankVerification:
        raise AdapterError("Bank verification provider unavailable")
