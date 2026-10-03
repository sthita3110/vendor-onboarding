"""Generate reference data and demo case packets.

Writes:
  data/reference/  gst_state_codes.json, vendor_master.csv, debarred.csv, gst_registry.json, penny_drop.json
  data/samples/    H1.json, E1.json, E2.json, E3.json, E3R.json, E4.json, E5.json
                   (documents rendered as PDFs by scripts/render_documents.py)

All entities are fictitious. Identifiers are structurally valid: PAN 4th char = holder type,
5th char = first letter of the name; GSTIN check digits are computed, not typed.

Run from backend/:  python -m scripts.generate_data
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from app.rules.validators import gstin_check_char

ROOT = Path(__file__).resolve().parents[1] / "data"
REF, SAMPLES = ROOT / "reference", ROOT / "samples"

STATE_CODES = {
    "01": "Jammu and Kashmir", "02": "Himachal Pradesh", "03": "Punjab", "04": "Chandigarh",
    "05": "Uttarakhand", "06": "Haryana", "07": "Delhi", "08": "Rajasthan", "09": "Uttar Pradesh",
    "10": "Bihar", "11": "Sikkim", "12": "Arunachal Pradesh", "13": "Nagaland", "14": "Manipur",
    "15": "Mizoram", "16": "Tripura", "17": "Meghalaya", "18": "Assam", "19": "West Bengal",
    "20": "Jharkhand", "21": "Odisha", "22": "Chhattisgarh", "23": "Madhya Pradesh", "24": "Gujarat",
    "26": "Dadra and Nagar Haveli and Daman and Diu", "27": "Maharashtra", "28": "Andhra Pradesh",
    "29": "Karnataka", "30": "Goa", "31": "Lakshadweep", "32": "Kerala", "33": "Tamil Nadu",
    "34": "Puducherry", "35": "Andaman and Nicobar Islands", "36": "Telangana", "37": "Andhra Pradesh",
    "38": "Ladakh",
}


def gstin(state: str, pan: str, entity_no: str = "1") -> str:
    first14 = f"{state}{pan}{entity_no}Z"
    return first14 + gstin_check_char(first14)


# ---------- reference data ----------

MASTER = [
    # vendor_id, legal_name, pan, state, account, ifsc, status
    ("V-1001", "Sahyadri Steel Traders Private Limited", "AAJCS2210L", "27", "50100234567811", "HDFC0000240", "active"),
    ("V-1002", "Coromandel Freight Services Private Limited", "AAECC8834D", "33", "912010045678321", "UTIB0000112", "active"),
    ("V-1003", "Deccan Office Supplies Private Limited", "AAFCD5521B", "36", "38291045672", "SBIN0020345", "active"),
    ("V-1004", "Indus Printworks Private Limited", "AABCI7745N", "07", "002105012345", "ICIC0000021", "active"),
    ("V-1005", "Malabar Spice Exports Private Limited", "AAGCM3390E", "32", "10230045671234", "KKBK0000561", "active"),
    ("V-1006", "Meridian Office Solutions Private Limited", "AAKCM6612R", "36", "50200011122233", "HDFC0001876", "active"),
    ("V-1007", "Narmada Agro Industries Private Limited", "AADCN4471F", "24", "6011234509", "SBIN0003310", "active"),
    ("V-1008", "Pinnacle Facility Management Private Limited", "AAHCP9902Q", "29", "914020056781234", "UTIB0002233", "active"),
    ("V-1009", "Ganga Electricals Private Limited", "AACCG1188M", "09", "1234567890123", "PUNB0123400", "active"),
    ("V-1010", "Vindhya Cables Private Limited", "AAICV5530H", "23", "40011223344", "BKID0004455", "inactive"),
    ("V-1011", "Konkan Logistics LLP", "AAKFK2201J", "27", "50100987654321", "HDFC0000533", "active"),
    ("V-1012", "Suresh Patil", "AXRPP4412K", "27", "31234567890", "SBIN0001122", "active"),  # proprietor of Shree Ganesh Caterers
]

DEBARRED = [
    ("Apex Industrial Supplies Private Limited", "AAGCA5517R", "Simulated public-procurement debarment list",
     "Supply of substandard materials under government contract", "2025-03-14"),
    ("Sunrise Infra Projects Private Limited", "AAMCS7781K", "Internal blocklist",
     "Invoice fraud incident", "2024-11-02"),
    ("Orion Global Trading Private Limited", "AANCO3318P", "Simulated sanctions list",
     "Sanctions designation", "2023-06-20"),
    ("Blue Lotus Trading Co", "AABFB1122C", "Internal blocklist",
     "Repeated non-delivery after advance payment", "2024-02-09"),
]


# ---------- demo cases ----------

def field(value: str, label: str, grounded: str = "text") -> dict:
    return {"value": value, "quote": f"{label}: {value}", "page": 1, "grounded": grounded}


def gst_doc(legal: str, trade: str, g: str, address: str, constitution: str = "Private Limited Company") -> dict:
    return {
        "slot": "gst_certificate", "filename": "gst_certificate.pdf", "classified_type": "gst_certificate",
        "fields": {
            "legal_name": field(legal, "Legal Name"),
            "trade_name": field(trade, "Trade Name, if any"),
            "gstin": field(g, "Registration Number"),
            "constitution_of_business": field(constitution, "Constitution of Business"),
            "principal_address": field(address, "Address of Principal Place of Business"),
            "state": field(STATE_CODES[g[:2]], "State"),
        },
    }


def pan_doc(name: str, pan: str, scanned: bool = False) -> dict:
    """`scanned=True` -> rendered as an image-only PDF (no text layer); values can't be text-grounded."""
    g = "image" if scanned else "text"
    return {
        "slot": "pan_card", "filename": "pan_card_scan.pdf" if scanned else "pan_card.pdf",
        "classified_type": "pan_card",
        "fields": {"name": field(name, "Name", g), "pan": field(pan, "Permanent Account Number", g)},
    }


def cheque_doc(holder: str, account: str, ifsc: str, bank: str) -> dict:
    return {
        "slot": "bank_proof", "filename": "cancelled_cheque.pdf", "classified_type": "bank_proof",
        "fields": {
            "account_holder_name": field(holder, "For"),
            "account_number": field(account, "A/c No"),
            "ifsc": field(ifsc, "IFSC"),
            "bank_name": field(bank, "Bank"),
        },
    }


def invoice_in_bank_slot() -> dict:
    return {
        "slot": "bank_proof", "filename": "INV-2026-0418.pdf", "classified_type": "invoice",
        "fields": {
            "invoice_number": field("INV-2026-0418", "Invoice No"),
            "invoice_date": field("2026-09-18", "Date"),
            "total_amount": field("1,84,080.00", "Total"),
        },
    }


def vendor(*, legal, trade=None, entity="company", line1, city, state, pin, contact, email,
           g, pan, holder=None, account, ifsc, bank) -> dict:
    return {
        "legal_name": legal, "trade_name": trade, "entity_type": entity,
        "address": {"line1": line1, "city": city, "state": state, "pin_code": pin},
        "contact_name": contact, "contact_email": email, "gstin": g, "pan": pan,
        "bank": {"account_holder_name": holder or legal, "account_number": account, "ifsc": ifsc, "bank_name": bank},
    }


def build_cases() -> tuple[list[dict], dict, dict]:
    """Returns (cases, registry fixtures, penny-drop fixtures) for the demo cases."""
    registry: dict[str, dict] = {}
    bank: dict[str, dict] = {}
    cases: list[dict] = []

    def reg(g: str, legal: str, trade: str | None = None, status: str = "active") -> None:
        registry[g] = {"status": status, "legal_name": legal, "trade_name": trade}

    def drop(account: str, ifsc: str, holder: str | None, status: str = "verified") -> None:
        bank[f"{account}|{ifsc}"] = {"status": status, "holder_name": holder}

    def add(cid, title, description, expected, sub, docs):
        scanned = [d["slot"] for d in docs if all(f["grounded"] == "image" for f in d["fields"].values())]
        cases.append({"id": cid, "title": title, "description": description, "expected": expected,
                      "scanned_slots": scanned,
                      "case": {"submission": sub, "documents": {d["slot"]: d for d in docs}}})

    # H1 — clean vendor
    pan, g = "AAACL4821K", gstin("29", "AAACL4821K")
    legal, addr = "Lumen Analytics Private Limited", "4th Floor, 21 Residency Road, Bengaluru, Karnataka 560025"
    sub = vendor(legal=legal, line1="4th Floor, 21 Residency Road", city="Bengaluru", state="Karnataka",
                 pin="560025", contact="Ananya Rao", email="accounts@lumenanalytics.example", g=g, pan=pan,
                 account="50200074561238", ifsc="HDFC0000075", bank="HDFC Bank")
    add("H1", "Clean vendor", "Complete, consistent packet. Bank returns an abbreviated company name.",
        {"status": "APPROVED", "sub_state": None, "failing_rules": []}, sub,
        [gst_doc(legal.upper(), "LUMEN ANALYTICS", g, addr), pan_doc("LUMEN ANALYTICS PRIVATE LIMITED", pan, scanned=True),
         cheque_doc("LUMEN ANALYTICS PVT. LTD.", "50200074561238", "HDFC0000075", "HDFC Bank")])
    reg(g, legal.upper(), "LUMEN ANALYTICS")
    drop("50200074561238", "HDFC0000075", "LUMEN ANALYTICS PVT LTD")

    # E1 — GSTIN valid but embeds a different PAN
    pan, other_pan = "AAECB7302M", "AAFCB1156Q"
    g = gstin("27", other_pan)
    legal, addr = "Brightpath Logistics Private Limited", "Unit 12, Marol Industrial Estate, Andheri East, Mumbai, Maharashtra 400059"
    sub = vendor(legal=legal, line1="Unit 12, Marol Industrial Estate, Andheri East", city="Mumbai",
                 state="Maharashtra", pin="400059", contact="Vikram Desai", email="finance@brightpath.example",
                 g=g, pan=pan, account="912020034567890", ifsc="UTIB0000246", bank="Axis Bank")
    add("E1", "GSTIN belongs to a different PAN",
        "GSTIN has a valid format and check digit, but the PAN inside it doesn't match the PAN card.",
        {"status": "PENDING", "sub_state": "INTERNAL_REVIEW", "failing_rules": ["TAX-03"]}, sub,
        [gst_doc(legal.upper(), "BRIGHTPATH LOGISTICS", g, addr), pan_doc(legal.upper(), pan),
         cheque_doc(legal.upper(), "912020034567890", "UTIB0000246", "Axis Bank")])
    reg(g, legal.upper(), "BRIGHTPATH LOGISTICS")
    drop("912020034567890", "UTIB0000246", "BRIGHTPATH LOGISTICS PRIVATE LIMITED")

    # E2 — bank account belongs to an individual
    pan, g = "AABCN6419H", gstin("07", "AABCN6419H")
    legal, addr = "Northwind Supplies Private Limited", "B-44, Okhla Industrial Area Phase II, New Delhi, Delhi 110020"
    sub = vendor(legal=legal, line1="B-44, Okhla Industrial Area Phase II", city="New Delhi", state="Delhi",
                 pin="110020", contact="Rakesh Sharma", email="rakesh@northwindsupplies.example", g=g, pan=pan,
                 account="003101567823", ifsc="ICIC0000031", bank="ICICI Bank")
    add("E2", "Bank account holder is an individual",
        "Everything matches on paper, but the bank reports the account holder as a person, not the company.",
        {"status": "PENDING", "sub_state": "INTERNAL_REVIEW", "failing_rules": ["BANK-03"]}, sub,
        [gst_doc(legal.upper(), "NORTHWIND SUPPLIES", g, addr), pan_doc(legal.upper(), pan),
         cheque_doc(legal.upper(), "003101567823", "ICIC0000031", "ICICI Bank")])
    reg(g, legal.upper(), "NORTHWIND SUPPLIES")
    drop("003101567823", "ICIC0000031", "RAKESH K SHARMA")

    # E3 — invoice in bank slot + Karnataka GSTIN for a Tamil Nadu business
    pan = "AADCK3390P"
    g_ka, g_tn = gstin("29", pan), gstin("33", pan)
    legal = "Kaveri Packaging Private Limited"
    addr_ka = "Plot 7, Peenya Industrial Area, Bengaluru, Karnataka 560058"
    addr_tn = "18 Industrial Estate Road, Guindy, Chennai, Tamil Nadu 600032"
    base = dict(legal=legal, line1="18 Industrial Estate Road, Guindy", city="Chennai", state="Tamil Nadu",
                pin="600032", contact="Meena Krishnan", email="vendor.ops@kaveripack.example", pan=pan,
                account="20031045678912", ifsc="SBIN0001789", bank="State Bank of India")
    add("E3", "Wrong document and wrong-state GSTIN",
        "An invoice was uploaded instead of a cancelled cheque, and the GSTIN is the Karnataka registration "
        "for a Tamil Nadu address.",
        {"status": "PENDING", "sub_state": "AWAITING_VENDOR", "failing_rules": ["DOC-01", "TAX-04"]},
        vendor(g=g_ka, **base),
        [gst_doc(legal.upper(), "KAVERI PACKAGING", g_ka, addr_ka), pan_doc(legal.upper(), pan),
         invoice_in_bank_slot()])
    add("E3R", "Wrong document and wrong-state GSTIN — resubmitted",
        "Vendor's corrected resubmission of E3: Tamil Nadu GSTIN and a cancelled cheque.",
        {"status": "APPROVED", "sub_state": None, "failing_rules": []},
        vendor(g=g_tn, **base),
        [gst_doc(legal.upper(), "KAVERI PACKAGING", g_tn, addr_tn), pan_doc(legal.upper(), pan),
         cheque_doc("KAVERI PACKAGING PVT LTD", "20031045678912", "SBIN0001789", "State Bank of India")])
    reg(g_ka, legal.upper(), "KAVERI PACKAGING")
    reg(g_tn, legal.upper(), "KAVERI PACKAGING")
    drop("20031045678912", "SBIN0001789", "KAVERI PACKAGING PVT LTD")

    # E4 — debarred entity
    pan, g = "AAGCA5517R", gstin("27", "AAGCA5517R")
    legal, addr = "Apex Industrial Supplies Private Limited", "Gat No. 112, Chakan MIDC, Pune, Maharashtra 410501"
    sub = vendor(legal=legal, line1="Gat No. 112, Chakan MIDC", city="Pune", state="Maharashtra", pin="410501",
                 contact="Sanjay Kulkarni", email="sales@apexindustrial.example", g=g, pan=pan,
                 account="50100345612789", ifsc="HDFC0000180", bank="HDFC Bank")
    add("E4", "Debarred entity", "Clean, consistent packet, but the PAN is on the debarred list.",
        {"status": "REJECTED", "sub_state": None, "failing_rules": ["RISK-01"]}, sub,
        [gst_doc(legal.upper(), "APEX INDUSTRIAL SUPPLIES", g, addr), pan_doc(legal.upper(), pan),
         cheque_doc(legal.upper(), "50100345612789", "HDFC0000180", "HDFC Bank")])
    reg(g, legal.upper(), "APEX INDUSTRIAL SUPPLIES")
    drop("50100345612789", "HDFC0000180", "APEX INDUSTRIAL SUPPLIES PVT LTD")

    # E5 — existing vendor, new bank account
    pan, g = "AAKCM6612R", gstin("36", "AAKCM6612R")
    legal, addr = "Meridian Office Solutions Private Limited", "Plot 9, HITEC City Phase 2, Hyderabad, Telangana 500081"
    sub = vendor(legal=legal, line1="Plot 9, HITEC City Phase 2", city="Hyderabad", state="Telangana",
                 pin="500081", contact="Farah Siddiqui", email="ap@meridianoffice.example", g=g, pan=pan,
                 account="7712345609", ifsc="KKBK0007788", bank="Kotak Mahindra Bank")
    add("E5", "Existing vendor with new bank details",
        "Already in the vendor master; the submission carries a different bank account.",
        {"status": "PENDING", "sub_state": "INTERNAL_REVIEW", "failing_rules": ["DUP-01"]}, sub,
        [gst_doc(legal.upper(), "MERIDIAN OFFICE SOLUTIONS", g, addr), pan_doc(legal.upper(), pan),
         cheque_doc(legal.upper(), "7712345609", "KKBK0007788", "Kotak Mahindra Bank")])
    drop("7712345609", "KKBK0007788", "MERIDIAN OFFICE SOLUTIONS PVT LTD")

    return cases, registry, bank


def main() -> None:
    REF.mkdir(parents=True, exist_ok=True)
    SAMPLES.mkdir(parents=True, exist_ok=True)

    (REF / "gst_state_codes.json").write_text(json.dumps(STATE_CODES, indent=2) + "\n")

    registry: dict[str, dict] = {}
    bank: dict[str, dict] = {}
    with (REF / "vendor_master.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["vendor_id", "legal_name", "pan", "gstin", "bank_account_number", "ifsc", "status"])
        for vid, legal, pan, state, acct, ifsc, status in MASTER:
            g = gstin(state, pan)
            w.writerow([vid, legal, pan, g, acct, ifsc, status])
            registry[g] = {"status": "active", "legal_name": legal.upper(), "trade_name": None}
            bank[f"{acct}|{ifsc}"] = {"status": "verified", "holder_name": legal.upper()}

    with (REF / "debarred.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["entity_name", "pan", "list_source", "reason", "listed_on"])
        w.writerows(DEBARRED)

    cases, case_registry, case_bank = build_cases()
    registry.update(case_registry)
    bank.update(case_bank)
    # Non-demo fixtures so the adapters' negative paths are exercisable from the UI.
    registry[gstin("19", "AAPCR4410G")] = {"status": "cancelled", "legal_name": "RIVERSTONE TEXTILES PRIVATE LIMITED", "trade_name": None}
    bank["99990000111122|HDFC0000999"] = {"status": "closed", "holder_name": None}

    (REF / "gst_registry.json").write_text(json.dumps(registry, indent=2) + "\n")
    (REF / "penny_drop.json").write_text(json.dumps(bank, indent=2) + "\n")
    for c in cases:
        (SAMPLES / f"{c['id']}.json").write_text(json.dumps(c, indent=2) + "\n")
    print(f"Wrote {len(MASTER)} master vendors, {len(DEBARRED)} debarred, {len(registry)} registry, "
          f"{len(bank)} bank fixtures, {len(cases)} sample cases.")


if __name__ == "__main__":
    main()
