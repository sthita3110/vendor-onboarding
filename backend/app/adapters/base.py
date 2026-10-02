"""External verification interfaces.

The mocks in `mock.py` implement these exactly as a real integration would
(GST portal / GSP API; penny drop via Razorpay / Cashfree). Swapping providers is a
change confined to this package.
"""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel


class AdapterError(Exception):
    """Raised when a provider can't be reached or returns garbage. Pipeline fails closed."""


class GstRegistryRecord(BaseModel):
    gstin: str
    status: Literal["active", "inactive", "cancelled", "not_found"]
    legal_name: str | None = None
    trade_name: str | None = None
    provider: str
    fixture: bool = True  # False when the mock answered from its sandbox default


class BankVerification(BaseModel):
    account_number: str
    ifsc: str
    status: Literal["verified", "not_found", "closed", "invalid"]
    holder_name: str | None = None  # name as registered with the bank
    provider: str
    fixture: bool = True


class GstRegistry(Protocol):
    def lookup(self, gstin: str) -> GstRegistryRecord: ...


class BankVerifier(Protocol):
    def verify(
        self, account_number: str, ifsc: str, submitted_holder: str | None = None
    ) -> BankVerification: ...
