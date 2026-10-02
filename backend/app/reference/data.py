"""Reference data: GST state codes, vendor master, debarred list. Loaded from data/reference."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

from app.rules.names import normalize_name
from app.rules.validators import clean_account, clean_id

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
REFERENCE_DIR = DATA_DIR / "reference"
SAMPLES_DIR = DATA_DIR / "samples"


@dataclass(frozen=True)
class MasterVendor:
    vendor_id: str
    legal_name: str
    pan: str
    gstin: str
    bank_account_number: str
    ifsc: str
    status: str


@dataclass(frozen=True)
class DebarredEntity:
    entity_name: str
    pan: str
    list_source: str
    reason: str
    listed_on: str


@dataclass
class ReferenceData:
    state_codes: dict[str, str]  # "29" -> "Karnataka"
    vendor_master: list[MasterVendor]
    debarred: list[DebarredEntity]

    def state_name(self, code: str) -> str | None:
        return self.state_codes.get(code)

    def master_by_pan_or_gstin(self, pan: str | None, gstin: str | None) -> list[MasterVendor]:
        p, g = clean_id(pan), clean_id(gstin)
        return [v for v in self.vendor_master if (p and v.pan == p) or (g and v.gstin == g)]

    def master_by_bank(self, account_number: str, ifsc: str) -> list[MasterVendor]:
        a, i = clean_account(account_number), clean_id(ifsc)
        return [v for v in self.vendor_master if v.bank_account_number == a and v.ifsc == i]

    def debarred_by_pan(self, pans: set[str]) -> list[DebarredEntity]:
        return [d for d in self.debarred if d.pan in pans]

    def debarred_by_name(self, names: set[str]) -> list[DebarredEntity]:
        normalized = {normalize_name(n) for n in names if n}
        return [d for d in self.debarred if normalize_name(d.entity_name) in normalized]


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def load_reference(directory: Path = REFERENCE_DIR) -> ReferenceData:
    state_codes = json.loads((directory / "gst_state_codes.json").read_text())
    vendor_master = [
        MasterVendor(
            vendor_id=r["vendor_id"], legal_name=r["legal_name"], pan=clean_id(r["pan"]),
            gstin=clean_id(r["gstin"]), bank_account_number=clean_account(r["bank_account_number"]),
            ifsc=clean_id(r["ifsc"]), status=r["status"],
        )
        for r in _read_csv(directory / "vendor_master.csv")
    ]
    debarred = [
        DebarredEntity(
            entity_name=r["entity_name"], pan=clean_id(r["pan"]), list_source=r["list_source"],
            reason=r["reason"], listed_on=r["listed_on"],
        )
        for r in _read_csv(directory / "debarred.csv")
    ]
    return ReferenceData(state_codes=state_codes, vendor_master=vendor_master, debarred=debarred)
