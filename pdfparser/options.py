"""Settings shared by the command line and the window app."""

from __future__ import annotations

from dataclasses import dataclass

OCR_MODES = ("auto", "always", "never")


@dataclass
class ParseOptions:
    ocr: str = "auto"  # auto: only pages without usable text; always; never
    lang: str = "eng"  # Tesseract language code(s), e.g. "eng" or "eng+deu"
    dpi: int = 300  # render resolution for OCR
    layout: bool = False  # keep physical layout (columns side by side)
    tables: bool = True  # detect ruled tables and draw them as text grids
    password: str | None = None
    min_text_chars: int = 25  # below this many real characters a page counts as "no text"

    def __post_init__(self) -> None:
        if self.ocr not in OCR_MODES:
            raise ValueError(f"ocr must be one of {', '.join(OCR_MODES)}")
        if not 50 <= self.dpi <= 1200:
            raise ValueError("dpi must be between 50 and 1200")
