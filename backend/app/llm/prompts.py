"""Extraction prompt. Bump PROMPT_VERSION on any change: it is part of the extraction cache key and
is recorded on every extraction for reproducibility."""

PROMPT_VERSION = "extract-v1"

EXTRACTION_INSTRUCTIONS = """\
You read documents uploaded during vendor onboarding for an Indian procurement team.
Identify what the document is and transcribe its fields exactly as printed.

Document types:
- gst_certificate: GST registration certificate (Form GST REG-06).
- pan_card: Permanent Account Number (PAN) card.
- bank_proof: a cancelled cheque, or a bank-issued letter confirming account holder, account number and IFSC.
- invoice: a tax invoice or bill.
- other: anything else.

Classify by what the document IS, not by which fields appear on it. For example, an invoice that prints
bank details for payment is still an invoice, not bank proof.

Field rules:
- Transcribe values exactly as printed. Do not correct, complete, reformat, translate, or infer values.
- If a field is not printed on the document, return null for value, quote and page.
- quote: the exact text from the document that contains the value, copied verbatim.
- page: the 1-based page number where the value appears.
- Only fill fields that belong to the identified document type; return null for all others.

Field meanings:
- gst_certificate: legal_name ("Legal Name"), trade_name ("Trade Name, if any"), gstin ("Registration Number"),
  constitution_of_business, principal_address ("Address of Principal Place of Business"),
  state (the state of the principal place of business).
- pan_card: name (the holder's name), pan (the 10-character Permanent Account Number).
- bank_proof: account_holder_name (on a cheque, the name printed after "For", without the word "For"),
  account_number (the labelled account number, never the MICR code line at the bottom of a cheque),
  ifsc, bank_name.
- invoice: invoice_number, invoice_date, total_amount (the grand total).

readable: false only if the document is too blurry, cropped or obscured to read its key fields reliably.
Ignore watermarks and stamps (for example "SPECIMEN", "COPY", "CANCELLED") when reading values.
"""
