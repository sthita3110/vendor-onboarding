"""Strict JSON schema for extraction output, and which fields belong to each document type.

Strict structured output requires every property to be listed in `required` and
`additionalProperties: false`; "optional" is expressed as a nullable type.
"""

from __future__ import annotations

from typing import Any

DOC_TYPES = ["gst_certificate", "pan_card", "bank_proof", "invoice", "other"]

FIELDS_BY_TYPE: dict[str, list[str]] = {
    "gst_certificate": ["legal_name", "trade_name", "gstin", "constitution_of_business", "principal_address", "state"],
    "pan_card": ["name", "pan"],
    "bank_proof": ["account_holder_name", "account_number", "ifsc", "bank_name"],
    "invoice": ["invoice_number", "invoice_date", "total_amount"],
    "other": [],
}

ALL_FIELDS: list[str] = list(dict.fromkeys(f for fields in FIELDS_BY_TYPE.values() for f in fields))

_FIELD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "value": {"type": ["string", "null"]},
        "quote": {"type": ["string", "null"]},
        "page": {"type": ["integer", "null"]},
    },
    "required": ["value", "quote", "page"],
    "additionalProperties": False,
}

EXTRACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "doc_type": {"type": "string", "enum": DOC_TYPES},
        "readable": {"type": "boolean"},
        "fields": {
            "type": "object",
            "properties": {name: _FIELD_SCHEMA for name in ALL_FIELDS},
            "required": ALL_FIELDS,
            "additionalProperties": False,
        },
    },
    "required": ["doc_type", "readable", "fields"],
    "additionalProperties": False,
}
