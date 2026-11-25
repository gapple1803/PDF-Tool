"""Locating and running the Tesseract OCR engine, fully offline.

Search order for tesseract:
  1. <folder of PDFParser.exe>/tesseract/tesseract.exe  (the bundled copy)
  2. the PDFPARSER_TESSERACT environment variable (an exe path or its folder)
  3. "tesseract" on PATH (developer machines)
"""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ENV_VAR = "PDFPARSER_TESSERACT"
EXE_NAME = "tesseract.exe" if os.name == "nt" else "tesseract"
# Keep GUI builds from flashing a console window for every OCR call on Windows.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
MAX_PIXELS = 60_000_000  # cap on rendered page size (memory guard for huge pages)
OCR_TIMEOUT_S = 300


class OcrError(RuntimeError):
    """OCR engine missing, misconfigured or failed."""


def _run(cmd: list[str], cwd: str | None, data: bytes | None = None, timeout: float = 30):
    kwargs = {"input": data} if data is not None else {"stdin": subprocess.DEVNULL}
    return subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=cwd,
        timeout=timeout,
        creationflags=_NO_WINDOW,
        **kwargs,
    )


@dataclass(frozen=True)
class Tesseract:
    exe: Path
    bundled: bool  # True when it ships with the app (uses ./tessdata next to the exe)
    version: str
    languages: tuple[str, ...]

    # The bundled copy runs with its own folder as working directory and a
    # *relative* tessdata path, so non-ASCII install folders (e.g. C:\Users\Jörg\)
    # never reach Tesseract's ANSI file APIs on Windows.
    @property
    def _cwd(self) -> str | None:
        return str(self.exe.parent) if self.bundled else None

    def _cmd(self, *args: str) -> list[str]:
        cmd = [str(self.exe)]
        if self.bundled:
            cmd += ["--tessdata-dir", "tessdata"]
        return cmd + list(args)

    def describe(self) -> str:
        where = "bundled" if self.bundled else str(self.exe)
        return f"Tesseract {self.version} ({where}; languages: {', '.join(self.languages) or 'none'})"

    def check_lang(self, lang: str) -> None:
        missing = [code for code in lang.split("+") if code not in self.languages]
        if missing:
            raise OcrError(
                f"OCR language(s) not installed: {', '.join(missing)}. "
                f"Available: {', '.join(self.languages) or 'none'}"
            )

    def ocr_image(self, image, lang: str = "eng", dpi: int = 300) -> str:
        """OCR a PIL image. The image is piped through stdin (no temp files)."""
        buf = io.BytesIO()
        image.save(buf, format="PNG", compress_level=1, dpi=(dpi, dpi))
        cmd = self._cmd(
            "stdin", "stdout",
            "-l", lang,
            "--psm", "3",
            "--dpi", str(dpi),
            "-c", "preserve_interword_spaces=1",
        )
        try:
            proc = _run(cmd, self._cwd, data=buf.getvalue(), timeout=OCR_TIMEOUT_S)
        except subprocess.TimeoutExpired as exc:
            raise OcrError(f"OCR timed out after {OCR_TIMEOUT_S}s") from exc
        except OSError as exc:
            raise OcrError(f"could not start Tesseract: {exc}") from exc
        if proc.returncode != 0:
            err = proc.stderr.decode("utf-8", "replace").strip()
            raise OcrError(f"Tesseract failed (exit {proc.returncode}): {err[-500:]}")
        return proc.stdout.decode("utf-8", "replace").replace("\f", "").strip()


def _probe(exe: Path, bundled: bool) -> Tesseract:
    stub = Tesseract(exe, bundled, "?", ())
    try:
        ver = _run(stub._cmd("--version"), stub._cwd)
        langs = _run(stub._cmd("--list-langs"), stub._cwd)
    except (OSError, subprocess.SubprocessError) as exc:
        raise OcrError(f"could not run {exe}: {exc}") from exc
    if ver.returncode != 0:
        raise OcrError(f"{exe} --version failed: {ver.stderr.decode('utf-8', 'replace').strip()}")
    first = (ver.stdout or ver.stderr).decode("utf-8", "replace").strip().splitlines()
    version = first[0].replace("tesseract", "").strip().lstrip("v") if first else "?"
    lines = langs.stdout.decode("utf-8", "replace").splitlines()
    languages = tuple(sorted(l.strip() for l in lines[1:] if l.strip()))
    return Tesseract(exe, bundled, version, languages)


def _bundled_candidates() -> list[Path]:
    dirs: list[Path] = []
    if getattr(sys, "frozen", False):
        dirs.append(Path(sys.executable).resolve().parent / "tesseract")
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            dirs.append(Path(meipass) / "tesseract")
    return [d / EXE_NAME for d in dirs]


def find_tesseract() -> Tesseract:
    """Return a working Tesseract or raise OcrError explaining what is missing."""
    for exe in _bundled_candidates():
        if exe.is_file() and (exe.parent / "tessdata").is_dir():
            return _probe(exe, bundled=True)

    env = os.environ.get(ENV_VAR, "").strip().strip('"')
    if env:
        p = Path(env)
        exe = p / EXE_NAME if p.is_dir() else p
        if not exe.is_file():
            raise OcrError(f"{ENV_VAR} points to {env}, but no {EXE_NAME} was found there")
        return _probe(exe, bundled=False)

    found = shutil.which("tesseract")
    if found:
        return _probe(Path(found), bundled=False)
    raise OcrError("Tesseract OCR engine not found (expected a 'tesseract' folder next to the app)")


_cache: dict[str, object] = {}


def get_tesseract() -> Tesseract:
    """Cached find_tesseract(); the lookup runs once per process."""
    if "result" not in _cache:
        try:
            _cache["result"] = find_tesseract()
        except OcrError as exc:
            _cache["result"] = exc
    result = _cache["result"]
    if isinstance(result, OcrError):
        raise result
    return result  # type: ignore[return-value]


def open_document(path: Path, password: str | None):
    import pypdfium2 as pdfium

    return pdfium.PdfDocument(str(path), password=password or None)


def render_page(document, index: int, dpi: int):
    """Render one page to a grayscale PIL image. Returns (image, effective_dpi)."""
    page = document[index]
    try:
        width, height = page.get_size()  # PDF points (1/72 inch)
        scale = dpi / 72
        if width * height * scale * scale > MAX_PIXELS:
            scale = (MAX_PIXELS / (width * height)) ** 0.5
        bitmap = page.render(scale=scale, grayscale=True)
        image = bitmap.to_pil()
        bitmap.close()
        return image, max(1, round(scale * 72))
    finally:
        page.close()
