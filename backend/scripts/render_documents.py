"""Render each demo case's documents as the PDFs a vendor would upload.

Reads data/samples/<ID>.json (written by generate_data.py) and writes data/samples/<ID>/<filename>.pdf.
The values printed on each document are the sample's `documents.*.fields` values — the same values
the Phase 1 golden tests use — so the JSON doubles as ground truth for measuring extraction accuracy.

Slots listed in a sample's `scanned_slots` are rendered, rasterized, rotated, blurred and JPEG-compressed,
then re-wrapped as an image-only PDF (no text layer), to simulate a scanned upload.

Output is byte-for-byte deterministic (fixed PDF metadata, no randomness), so file hashes — and therefore
the extraction cache keys in step 2c — stay stable across regenerations.

Every document carries a SPECIMEN watermark and no emblems or logos: these are test fixtures, not forgeries.

Run from backend/:  python -m scripts.render_documents
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pymupdf
from PIL import Image, ImageEnhance, ImageFilter
from reportlab.lib.colors import Color, HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import simpleSplit
from reportlab.pdfgen.canvas import Canvas

from app.reference.data import SAMPLES_DIR
from app.rules.validators import gstin_check_char

INK = HexColor("#1f2937")
MUTED = HexColor("#6b7280")
RULE = HexColor("#9ca3af")
FIXED_DATE = "D:20260901000000"  # PDF metadata date for scanned output (determinism)
SCAN_DPI = 200


# ---------- helpers ----------

def _seed(text: str) -> int:
    return sum(ord(c) * (i + 1) for i, c in enumerate(text))


def _date(text: str, base_year: int = 2016, span: int = 8) -> str:
    h = _seed(text)
    return f"{h % 28 + 1:02d}/{h % 12 + 1:02d}/{base_year + h % span}"


def _value(doc: dict, name: str) -> str:
    return (doc["fields"].get(name) or {}).get("value") or ""


def _canvas(buf: io.BytesIO, size: tuple[float, float], title: str) -> Canvas:
    c = Canvas(buf, pagesize=size, invariant=1)  # invariant=1: no timestamps/random IDs in the PDF
    c.setTitle(title)
    c.setAuthor("Vendor onboarding demo — specimen")
    return c


def _watermark(c: Canvas, w: float, h: float, size: int = 34) -> None:
    c.saveState()
    c.setFillColor(Color(0.55, 0.55, 0.6, alpha=0.18))
    c.setFont("Helvetica-Bold", size)
    c.translate(w / 2, h / 2)
    c.rotate(28)
    c.drawCentredString(0, 0, "SPECIMEN - FICTITIOUS DATA")
    c.restoreState()


def _wrapped(c: Canvas, text: str, x: float, y: float, width: float, font: str, size: float, leading: float) -> float:
    """Draw wrapped text; return the y below the last line."""
    c.setFont(font, size)
    for line in simpleSplit(text, font, size, width):
        c.drawString(x, y, line)
        y -= leading
    return y


# ---------- GST registration certificate (Form GST REG-06 layout) ----------

def render_gst_certificate(doc: dict, sub: dict) -> bytes:
    buf = io.BytesIO()
    w, h = A4
    c = _canvas(buf, A4, "GST Registration Certificate (specimen)")
    gstin = _value(doc, "gstin")
    state = _value(doc, "state")
    liability = _date(gstin)

    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 15)
    c.drawCentredString(w / 2, h - 60, "Form GST REG-06")
    c.setFont("Helvetica", 9)
    c.drawCentredString(w / 2, h - 74, "[See Rule 10(1)]")
    c.setFont("Helvetica-Bold", 13)
    c.drawCentredString(w / 2, h - 96, "Registration Certificate")
    c.setFont("Helvetica-Bold", 11)
    c.drawCentredString(w / 2, h - 120, f"Registration Number: {gstin}")

    rows = [
        ("1.", "Legal Name", _value(doc, "legal_name")),
        ("2.", "Trade Name, if any", _value(doc, "trade_name")),
        ("3.", "Constitution of Business", _value(doc, "constitution_of_business")),
        ("4.", "Address of Principal Place of Business", _value(doc, "principal_address")),
        ("5.", "Date of Liability", liability),
        ("6.", "Date of Validity", f"From {liability}    To  Not Applicable"),
        ("7.", "Type of Registration", "Regular"),
        ("8.", "Particulars of Approving Authority",
         f"Signature: Digitally signed (specimen)\nName: Approving Officer (specimen)\n"
         f"Designation: Superintendent\nJurisdictional Office: {state} - Range IV (specimen)"),
        ("9.", "Date of issue of Certificate", liability),
    ]
    x0, x_label, x_value, x1 = 50, 75, 255, w - 50
    y = h - 145
    c.setStrokeColor(RULE)
    c.line(x0, y, x1, y)
    for num, label, value in rows:
        top = y
        y -= 16
        c.setFillColor(INK)
        c.setFont("Helvetica", 9.5)
        c.drawString(x0 + 4, y, num)
        y_label = _wrapped(c, label, x_label, y, x_value - x_label - 10, "Helvetica", 9.5, 12)
        y_val = y
        for part in value.split("\n"):
            y_val = _wrapped(c, part, x_value, y_val, x1 - x_value - 6, "Helvetica-Bold", 9.5, 12)
        y = min(y_label, y_val) - 4
        c.line(x0, y, x1, y)
        c.line(x0, top, x0, y)
        c.line(x_label - 5, top, x_label - 5, y)
        c.line(x_value - 6, top, x_value - 6, y)
        c.line(x1, top, x1, y)

    c.setFillColor(MUTED)
    _wrapped(c, "Note: Specimen generated for a software demonstration. All entities and identifiers are "
                "fictitious. This is not a government-issued document.", x0, y - 24, x1 - x0, "Helvetica-Oblique", 8, 10)
    _watermark(c, w, h)
    c.showPage()
    c.save()
    return buf.getvalue()


# ---------- PAN card ----------

def render_pan_card(doc: dict, sub: dict) -> bytes:
    buf = io.BytesIO()
    w, h = 86 * mm * 2, 54 * mm * 2  # card proportions, 2x size
    c = _canvas(buf, (w, h), "PAN card (specimen)")
    c.setFillColor(HexColor("#e8f0f7"))
    c.setStrokeColor(HexColor("#8aa4bd"))
    c.roundRect(6, 6, w - 12, h - 12, 14, stroke=1, fill=1)

    c.setFillColor(HexColor("#1e3a5f"))
    c.setFont("Helvetica-Bold", 15)
    c.drawCentredString(w / 2, h - 36, "PERMANENT ACCOUNT NUMBER CARD")
    c.setFillColor(MUTED)
    c.setFont("Helvetica-Oblique", 7.5)
    c.drawCentredString(w / 2, h - 49, "Specimen layout - not issued by any authority")

    c.setFillColor(INK)
    x = 30
    c.setFont("Helvetica", 8)
    c.drawString(x, h - 84, "Permanent Account Number")
    c.setFont("Courier-Bold", 22)
    c.drawString(x, h - 108, _value(doc, "pan"))
    c.setFont("Helvetica", 8)
    c.drawString(x, h - 140, "Name")
    _wrapped(c, _value(doc, "name"), x, h - 158, w - 2 * x, "Helvetica-Bold", 13, 16)
    c.setFont("Helvetica", 8)
    c.drawString(x, h - 206, "Date of Incorporation / Formation")
    c.setFont("Helvetica-Bold", 12)
    c.drawString(x, h - 222, _date(_value(doc, "pan"), 2009, 10))

    c.setStrokeColor(MUTED)
    c.line(w - 150, 40, w - 30, 40)
    c.setFont("Helvetica", 7)
    c.drawCentredString(w - 90, 30, "Signature (specimen)")
    _watermark(c, w, h, size=20)
    c.showPage()
    c.save()
    return buf.getvalue()


# ---------- cancelled cheque ----------

def render_cheque(doc: dict, sub: dict) -> bytes:
    buf = io.BytesIO()
    w, h = 202 * mm, 92 * mm  # CTS-2010 cheque size
    c = _canvas(buf, (w, h), "Cancelled cheque (specimen)")
    account, ifsc = _value(doc, "account_number"), _value(doc, "ifsc")
    seed = _seed(account)

    c.setFillColor(HexColor("#f4f7f2"))
    c.setStrokeColor(RULE)
    c.rect(4, 4, w - 8, h - 8, stroke=1, fill=1)

    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 15)
    c.drawString(18, h - 30, _value(doc, "bank_name"))
    c.setFont("Helvetica", 8)
    c.drawString(18, h - 43, f"{sub['address']['city']} Branch")
    c.drawString(18, h - 54, f"IFSC: {ifsc}")

    c.setFont("Helvetica", 8)
    c.drawString(w - 160, h - 30, "Date")
    for i in range(8):
        c.rect(w - 135 + i * 14, h - 34, 12, 14)
    c.drawString(w - 135, h - 46, "D  D   M  M   Y  Y  Y  Y")

    c.setStrokeColor(RULE)
    c.drawString(18, h - 82, "Pay")
    c.line(40, h - 84, w - 40, h - 84)
    c.drawString(18, h - 104, "Rupees")
    c.line(55, h - 106, w - 150, h - 106)
    c.rect(w - 140, h - 114, 110, 20)
    c.drawString(w - 136, h - 108, "INR")

    c.setFont("Helvetica", 8)
    c.drawString(18, h - 140, "A/c No.")
    c.rect(55, h - 148, 150, 18)
    c.setFont("Courier-Bold", 12)
    c.drawString(60, h - 143, account)

    c.setFont("Helvetica-Bold", 9)
    _wrapped(c, f"For {_value(doc, 'account_holder_name')}", w - 230, h - 140, 210, "Helvetica-Bold", 9, 11)
    c.line(w - 200, h - 182, w - 40, h - 182)
    c.setFont("Helvetica", 7.5)
    c.drawCentredString(w - 120, h - 191, "Authorised Signatory")

    micr = f"{seed % 900 + 100}{seed % 1000:03d}{seed % 997:03d}"
    c.setFont("Courier", 11)
    c.drawString(60, 14, f"{seed % 1000000:06d}    {micr}    {account[-6:]}    31")

    c.saveState()  # cancellation marks, kept clear of the account number box
    c.setStrokeColor(Color(0.75, 0.1, 0.1, alpha=0.55))
    c.setFillColor(Color(0.75, 0.1, 0.1, alpha=0.45))
    c.setLineWidth(1.6)
    c.translate(w * 0.55, h * 0.52)
    c.rotate(14)
    c.line(-180, 16, 180, 16)
    c.line(-180, -10, 180, -10)
    c.setFont("Helvetica-Bold", 22)
    c.drawCentredString(0, -2, "CANCELLED")
    c.restoreState()
    _watermark(c, w, h, size=22)
    c.showPage()
    c.save()
    return buf.getvalue()


# ---------- invoice (wrong document for the bank-proof slot) ----------

def render_invoice(doc: dict, sub: dict, gst: dict | None) -> bytes:
    buf = io.BytesIO()
    w, h = A4
    c = _canvas(buf, A4, "Tax invoice (specimen)")
    seller = (gst and _value(gst, "legal_name")) or sub["legal_name"]
    seller_addr = (gst and _value(gst, "principal_address")) or ""
    seller_gstin = (gst and _value(gst, "gstin")) or sub["gstin"]
    buyer_first14 = "33AAFCZ4410L1Z"
    buyer_gstin = buyer_first14 + gstin_check_char(buyer_first14)
    bank = sub["bank"]

    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 18)
    c.drawString(50, h - 60, "TAX INVOICE")
    c.setFont("Helvetica-Bold", 11)
    c.drawString(50, h - 90, seller)
    y = _wrapped(c, seller_addr, 50, h - 104, 280, "Helvetica", 9, 11)
    c.setFont("Helvetica", 9)
    c.drawString(50, y - 2, f"GSTIN: {seller_gstin}")

    c.setFont("Helvetica", 9)
    for i, (k, v) in enumerate([("Invoice No", _value(doc, "invoice_number")),
                                ("Date", _value(doc, "invoice_date")),
                                ("Place of Supply", "Tamil Nadu (33)")]):
        c.drawString(360, h - 90 - i * 14, f"{k}:")
        c.setFont("Helvetica-Bold", 9)
        c.drawString(440, h - 90 - i * 14, v)
        c.setFont("Helvetica", 9)

    c.setFont("Helvetica-Bold", 9)
    c.drawString(50, h - 175, "Bill To")
    c.setFont("Helvetica", 9)
    c.drawString(50, h - 189, "Zenith Consumer Goods Private Limited")
    c.drawString(50, h - 201, "Plot 31, SIPCOT Industrial Park, Sriperumbudur, Tamil Nadu 602105")
    c.drawString(50, h - 213, f"GSTIN: {buyer_gstin}")

    cols = [50, 80, 330, 400, 470]
    y = h - 250
    c.setStrokeColor(RULE)
    c.line(50, y + 14, w - 50, y + 14)
    c.setFont("Helvetica-Bold", 9)
    for x, t in zip(cols, ["#", "Description", "Qty", "Rate", "Amount (INR)"]):
        c.drawString(x, y, t)
    c.line(50, y - 6, w - 50, y - 6)
    c.setFont("Helvetica", 9)
    items = [("1", "Corrugated shipping boxes, 5-ply, 18x12x10 in", "4,000", "24.00", "96,000.00"),
             ("2", "Printed carton sleeves", "6,000", "10.00", "60,000.00")]
    for row in items:
        y -= 20
        for x, t in zip(cols, row):
            c.drawString(x, y, t)
    y -= 14
    c.line(50, y, w - 50, y)
    for label, amount, bold in [("Taxable value", "1,56,000.00", False), ("IGST @ 18%", "28,080.00", False),
                                ("Total", _value(doc, "total_amount"), True)]:
        y -= 18
        c.setFont("Helvetica-Bold" if bold else "Helvetica", 10 if bold else 9)
        c.drawString(380, y, label)
        c.drawRightString(w - 55, y, amount)
    c.setFont("Helvetica-Oblique", 9)
    c.drawString(50, y - 26, "Amount in words: Indian Rupees One Lakh Eighty Four Thousand Eighty Only")

    # Real invoices print payment details — a deliberate trap: the document contains bank fields
    # but is still an invoice, not proof of bank account ownership.
    c.setFont("Helvetica-Bold", 9)
    c.drawString(50, y - 60, "Bank details for payment")
    c.setFont("Helvetica", 9)
    c.drawString(50, y - 74, f"{bank['bank_name']}  |  A/c No. {bank['account_number']}  |  IFSC {bank['ifsc']}")

    c.drawString(w - 220, 110, f"For {seller}")
    c.drawString(w - 220, 70, "Authorised Signatory")
    _watermark(c, w, h)
    c.showPage()
    c.save()
    return buf.getvalue()


# ---------- scan simulation ----------

def to_scanned_pdf(pdf_bytes: bytes) -> bytes:
    """Rasterize page 1 and degrade it like a flatbed scan; output has no text layer."""
    page = pymupdf.open(stream=pdf_bytes, filetype="pdf")[0]
    pix = page.get_pixmap(dpi=SCAN_DPI)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

    bed = Image.new("RGB", (img.width + 120, img.height + 120), (246, 245, 240))
    bed.paste(img, (50, 70))
    img = bed.rotate(1.4, resample=Image.Resampling.BICUBIC, expand=True, fillcolor=(246, 245, 240))
    img = img.filter(ImageFilter.GaussianBlur(0.6))
    img = ImageEnhance.Contrast(img).enhance(0.9)
    img = ImageEnhance.Brightness(img).enhance(0.97)

    jpeg = io.BytesIO()
    img.save(jpeg, "JPEG", quality=55)  # compression artifacts, deterministic

    # Wrap the JPEG as a single image-only page at the scan's physical size.
    out = pymupdf.open()
    pt_w, pt_h = img.width * 72 / SCAN_DPI, img.height * 72 / SCAN_DPI
    out.new_page(width=pt_w, height=pt_h).insert_image(pymupdf.Rect(0, 0, pt_w, pt_h), stream=jpeg.getvalue())
    out.set_metadata({"title": "Scanned document (specimen)", "creationDate": FIXED_DATE, "modDate": FIXED_DATE,
                      "producer": "", "creator": ""})
    return out.tobytes(garbage=3, deflate=True, no_new_id=True)


# ---------- driver ----------

def render_sample(sample: dict, out_dir: Path) -> list[Path]:
    docs = sample["case"]["documents"]
    sub = sample["case"]["submission"]
    scanned = set(sample.get("scanned_slots", []))
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for slot, doc in docs.items():
        kind = doc["classified_type"]
        if kind == "gst_certificate":
            pdf = render_gst_certificate(doc, sub)
        elif kind == "pan_card":
            pdf = render_pan_card(doc, sub)
        elif kind == "bank_proof":
            pdf = render_cheque(doc, sub)
        elif kind == "invoice":
            pdf = render_invoice(doc, sub, docs.get("gst_certificate"))
        else:
            raise ValueError(f"No renderer for document type {kind!r}")
        if slot in scanned:
            pdf = to_scanned_pdf(pdf)
        path = out_dir / doc["filename"]
        path.write_bytes(pdf)
        written.append(path)
    return written


def main() -> None:
    total = 0
    for path in sorted(SAMPLES_DIR.glob("*.json")):
        sample = json.loads(path.read_text())
        out_dir = SAMPLES_DIR / sample["id"]
        for stale in out_dir.glob("*.pdf"):
            stale.unlink()
        files = render_sample(sample, out_dir)
        total += len(files)
        print(f"{sample['id']:4} " + ", ".join(f.name for f in files))
    print(f"Rendered {total} documents.")


if __name__ == "__main__":
    main()
