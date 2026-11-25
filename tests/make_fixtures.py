"""Generate small test PDFs.

    python tests/make_fixtures.py OUTDIR

Good files go in OUTDIR, broken/encrypted ones in OUTDIR/bad.
EXPECTED lists snippets each output .txt must contain (used by tests and the CI smoke test).
"""

from __future__ import annotations

import sys
from pathlib import Path

from fpdf import FPDF
from PIL import Image, ImageDraw, ImageFont

PASSWORD = "secret"
PARAGRAPH = "The quick brown fox jumps over the lazy dog. Offline parsing keeps documents private."
SCAN_LINES = ["SCANNED INVOICE", "Invoice number 48213", "Customer ACME Limited", "Total amount 1250.00"]
TABLE = [["Item", "Qty", "Price"], ["Apples", "3", "1.20"], ["Bananas", "12", "0.50"], ["Cherries", "7", "3.75"]]

EXPECTED = {
    "text.txt": ["===== Page 1 =====", "The quick brown fox", "Second paragraph"],
    "table.txt": ["Quarterly fruit order", "| Item", "| Apples", "| Cherries", "+--", "Total due"],
    "scanned.txt": ["===== Page 1 (OCR) =====", "48213", "ACME"],
    "mixed.txt": ["===== Page 1 =====", "Digital first page", "===== Page 2 (OCR) =====", "48213"],
}


def _pdf() -> FPDF:
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(True, margin=15)
    pdf.set_font("Helvetica", size=12)
    return pdf


def scan_image(dpi: int = 200) -> Image.Image:
    """A white A4 'scan' with large printed text and no text layer."""
    w, h = int(8.27 * dpi), int(11.69 * dpi)
    img = Image.new("L", (w, h), 255)
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=int(dpi * 0.22))
    y = int(dpi * 1.0)
    for line in SCAN_LINES:
        draw.text((int(dpi * 0.8), y), line, fill=0, font=font)
        y += int(dpi * 0.45)
    return img


def make_all(outdir: str | Path) -> dict[str, Path]:
    out = Path(outdir)
    bad = out / "bad"
    bad.mkdir(parents=True, exist_ok=True)
    files: dict[str, Path] = {}

    pdf = _pdf()
    pdf.add_page()
    pdf.multi_cell(0, 7, PARAGRAPH)
    pdf.ln(4)
    pdf.multi_cell(0, 7, "Second paragraph: invoices, statements and reports all work the same way.")
    files["text"] = out / "text.pdf"
    pdf.output(str(files["text"]))

    pdf = _pdf()
    pdf.add_page()
    pdf.multi_cell(0, 7, "Quarterly fruit order")
    pdf.ln(4)
    with pdf.table(col_widths=(60, 30, 30), text_align="LEFT") as table:
        for row in TABLE:
            r = table.row()
            for cell in row:
                r.cell(cell)
    pdf.ln(6)
    pdf.multi_cell(0, 7, "Total due within 30 days.")
    files["table"] = out / "table.pdf"
    pdf.output(str(files["table"]))

    files["scanned"] = out / "scanned.pdf"
    scan_image().save(files["scanned"], "PDF", resolution=200)

    pdf = _pdf()
    pdf.add_page()
    pdf.multi_cell(0, 7, "Digital first page. " + PARAGRAPH)
    pdf.add_page()
    pdf.image(scan_image(), x=0, y=0, w=210, h=297)
    files["mixed"] = out / "mixed.pdf"
    pdf.output(str(files["mixed"]))

    pdf = _pdf()
    pdf.set_encryption(owner_password="owner-pw", user_password=PASSWORD)
    pdf.add_page()
    pdf.multi_cell(0, 7, "Confidential encrypted content.")
    files["encrypted"] = bad / "encrypted.pdf"
    pdf.output(str(files["encrypted"]))

    files["corrupt"] = bad / "corrupt.pdf"
    files["corrupt"].write_bytes(b"%PDF-1.7\nthis file was truncated and is not a real PDF\n")
    files["not_pdf"] = bad / "notes.pdf"
    files["not_pdf"].write_text("just a text file with a .pdf name", encoding="utf-8")
    return files


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: make_fixtures.py OUTDIR")
    for name, path in make_all(sys.argv[1]).items():
        print(f"{name}: {path}")
