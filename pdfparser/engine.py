"""Parse PDFs into plain text: digital text + table grids, OCR for scanned pages."""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

import pdfplumber

from . import ocr
from .options import ParseOptions
from .tables import is_garbage, page_text, real_char_count

# pdfminer is chatty about harmless PDF quirks.
logging.getLogger("pdfminer").setLevel(logging.ERROR)

ProgressFn = Callable[[int, int], None]  # (page_number, page_count)
EMPTY_PAGE = "[no text found on this page]"
IMAGE_HEAVY_COVERAGE = 0.5  # share of the page covered by images
IMAGE_HEAVY_MAX_CHARS = 200  # ...with less text than this counts as a scan


class Cancelled(Exception):
    pass


@dataclass
class PageResult:
    number: int
    text: str = ""
    method: str = "text"  # "text" or "ocr"
    tables: int = 0
    warning: str | None = None


@dataclass
class ParseResult:
    source: Path
    pages: list[PageResult] = field(default_factory=list)
    output: Path | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def ocr_pages(self) -> int:
        return sum(p.method == "ocr" for p in self.pages)

    @property
    def table_count(self) -> int:
        return sum(p.tables for p in self.pages)

    @property
    def warnings(self) -> list[str]:
        return [f"page {p.number}: {p.warning}" for p in self.pages if p.warning]

    def summary(self) -> str:
        if not self.ok:
            return f"FAILED - {self.error}"
        bits = [f"{len(self.pages)} page{'s' if len(self.pages) != 1 else ''}"]
        if self.ocr_pages:
            bits.append(f"{self.ocr_pages} OCR")
        if self.table_count:
            bits.append(f"{self.table_count} table{'s' if self.table_count != 1 else ''}")
        return ", ".join(bits)


def _image_coverage(page) -> float:
    area = float(page.width * page.height) or 1.0
    covered = 0.0
    for im in page.images:
        w = max(0.0, min(im["x1"], page.bbox[2]) - max(im["x0"], page.bbox[0]))
        h = max(0.0, min(im["bottom"], page.bbox[3]) - max(im["top"], page.bbox[1]))
        covered += w * h
    return min(1.0, covered / area)


def ocr_reason(page, text: str, opts: ParseOptions) -> str | None:
    """Why this page should be OCR'd, or None if its own text is good enough."""
    if is_garbage(text):
        return "text uses an unreadable font encoding"
    chars = real_char_count(text)
    if chars < opts.min_text_chars:
        if not (page.images or page.curves or page.rects or page.lines):
            return None  # genuinely blank page
        return "no selectable text"
    if chars < IMAGE_HEAVY_MAX_CHARS and _image_coverage(page) >= IMAGE_HEAVY_COVERAGE:
        return "page is mostly an image"
    return None


def _friendly_error(exc: BaseException) -> str:
    chain, cur = [], exc
    while cur is not None and len(chain) < 10:
        chain.append(cur)
        cur = cur.__cause__ or cur.__context__
    names = " ".join(type(e).__name__ for e in chain)
    text = " ".join(f"{e} {e.args!r}" for e in chain)
    if "Password" in names or "password" in text.lower():
        return "the PDF is password-protected or the password is wrong (use --password / the Password box)"
    if any(k in names for k in ("PDFSyntaxError", "PSEOF", "MalformedPDF")) or "No /Root" in text:
        return "not a valid PDF, or the file is damaged"
    return f"{type(exc).__name__}: {exc}"


def _looks_like_pdf(path: Path) -> bool:
    with open(path, "rb") as fh:
        return b"%PDF" in fh.read(1024)


def parse_pdf(
    path: str | os.PathLike,
    opts: ParseOptions | None = None,
    progress: ProgressFn | None = None,
    cancel: threading.Event | None = None,
) -> ParseResult:
    """Extract every page of one PDF. Never raises for bad input; see result.error."""
    opts = opts or ParseOptions()
    path = Path(path)
    result = ParseResult(source=path)

    tess: ocr.Tesseract | None = None
    tess_error: str | None = None
    if opts.ocr != "never":
        try:
            tess = ocr.get_tesseract()
            tess.check_lang(opts.lang)
        except ocr.OcrError as exc:
            tess, tess_error = None, str(exc)

    pdfium_doc = None
    try:
        if not path.is_file():
            raise FileNotFoundError(f"file not found: {path}")
        if not _looks_like_pdf(path):
            result.error = "not a PDF file"
            return result
        with pdfplumber.open(path, password=opts.password or None) as pdf:
            count = len(pdf.pages)
            for index, page in enumerate(pdf.pages):
                if cancel is not None and cancel.is_set():
                    raise Cancelled()
                if progress:
                    progress(index + 1, count)
                pr = PageResult(number=index + 1)
                try:
                    if opts.ocr != "always":
                        pr.text, pr.tables = page_text(page, opts.layout, opts.tables)
                    reason = "OCR set to always" if opts.ocr == "always" else ocr_reason(page, pr.text, opts)
                    if reason and opts.ocr == "never":
                        pr.warning = f"{reason}; OCR is turned off"
                    elif reason and tess is None:
                        pr.warning = f"{reason}, but OCR is unavailable: {tess_error}"
                    elif reason and tess is not None:
                        if pdfium_doc is None:
                            pdfium_doc = ocr.open_document(path, opts.password)
                        image, dpi = ocr.render_page(pdfium_doc, index, opts.dpi)
                        pr.text = tess.ocr_image(image, opts.lang, dpi)
                        pr.method, pr.tables = "ocr", 0
                except Cancelled:
                    raise
                except Exception as exc:  # one bad page must not sink the file
                    pr.warning = f"could not read page: {_friendly_error(exc)}"
                finally:
                    close = getattr(page, "close", None)
                    if close:
                        close()
                result.pages.append(pr)
    except Cancelled:
        result.error = "cancelled"
    except Exception as exc:
        result.error = _friendly_error(exc)
    finally:
        if pdfium_doc is not None:
            pdfium_doc.close()
    return result


def format_text(result: ParseResult) -> str:
    chunks = []
    for p in result.pages:
        header = f"===== Page {p.number}{' (OCR)' if p.method == 'ocr' else ''} ====="
        chunks.append(f"{header}\n\n{p.text.strip() or EMPTY_PAGE}\n")
    return "\n".join(chunks)


def collect_pdfs(inputs: Iterable[str | os.PathLike], recursive: bool = False) -> tuple[list[Path], list[str]]:
    """Expand files/folders into a de-duplicated list of PDFs. Returns (pdfs, problems)."""
    pdfs: list[Path] = []
    problems: list[str] = []
    seen: set[Path] = set()

    def add(p: Path) -> None:
        key = p.resolve()
        if key not in seen:
            seen.add(key)
            pdfs.append(p)

    for raw in inputs:
        p = Path(raw)
        if p.is_dir():
            walker = p.rglob("*") if recursive else p.iterdir()
            found = sorted(f for f in walker if f.is_file() and f.suffix.lower() == ".pdf")
            if not found:
                problems.append(f"no PDF files in folder: {p}")
            for f in found:
                add(f)
        elif p.is_file():
            add(p)
        else:
            problems.append(f"not found: {p}")
    return pdfs, problems


def plan_outputs(pdfs: list[Path], out_dir: str | os.PathLike | None) -> list[tuple[Path, Path]]:
    """Pair each PDF with a unique .txt path (next to the PDF, or in out_dir)."""
    taken: set[str] = set()
    pairs = []
    for pdf in pdfs:
        folder = Path(out_dir) if out_dir else pdf.parent
        target = folder / f"{pdf.stem}.txt"
        n = 2
        while str(target.resolve()).lower() in taken:
            target = folder / f"{pdf.stem}_{n}.txt"
            n += 1
        taken.add(str(target.resolve()).lower())
        pairs.append((pdf, target))
    return pairs


def process_file(
    pdf: Path,
    out_path: Path | None,
    opts: ParseOptions,
    progress: ProgressFn | None = None,
    cancel: threading.Event | None = None,
) -> tuple[ParseResult, str]:
    """Parse one PDF and, if out_path is given, write the .txt. Returns (result, text)."""
    result = parse_pdf(pdf, opts, progress, cancel)
    if not result.ok:
        return result, ""
    text = format_text(result)
    if out_path is not None:
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = out_path.with_name(out_path.name + ".partial")
            tmp.write_text(text, encoding="utf-8")
            os.replace(tmp, out_path)
            result.output = out_path
        except OSError as exc:
            result.error = f"could not write {out_path}: {exc.strerror or exc}"
    return result, text
