"""Command line front end: pdfparser-cli <files|folders> [options]."""

from __future__ import annotations

import argparse
import sys

from . import __version__, ocr
from .engine import collect_pdfs, plan_outputs, process_file
from .options import OCR_MODES, ParseOptions

EXIT_OK, EXIT_SOME_FAILED, EXIT_USAGE = 0, 1, 2


def _ocr_status() -> str:
    try:
        return ocr.get_tesseract().describe()
    except ocr.OcrError as exc:
        return f"unavailable - {exc}"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pdfparser-cli",
        description="Extract text and tables from PDF files into .txt files. "
        "Works fully offline; scanned pages are read with the bundled OCR engine.",
        epilog="Examples:\n"
        "  pdfparser-cli report.pdf\n"
        "  pdfparser-cli C:\\Scans -r -o C:\\Text\n"
        "  pdfparser-cli statement.pdf --stdout > statement.txt",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("inputs", nargs="+", metavar="PATH", help="PDF files and/or folders containing PDFs")
    p.add_argument("-o", "--out-dir", metavar="DIR", help="write .txt files here (default: next to each PDF)")
    p.add_argument("-r", "--recursive", action="store_true", help="include PDFs in subfolders")
    p.add_argument("--ocr", choices=OCR_MODES, default="auto",
                   help="auto = only pages without usable text (default); always; never")
    p.add_argument("--lang", default="eng", help="OCR language(s), e.g. eng or eng+deu (default: eng)")
    p.add_argument("--dpi", type=int, default=300, help="OCR render resolution (default: 300)")
    p.add_argument("--layout", action="store_true", help="keep the page layout (columns side by side)")
    p.add_argument("--no-tables", action="store_true", help="do not draw detected tables as grids")
    p.add_argument("--password", help="password for encrypted PDFs")
    p.add_argument("--stdout", action="store_true", help="print the text instead of writing .txt files")
    p.add_argument("-q", "--quiet", action="store_true", help="only print errors")
    p.add_argument("--version", action=_VersionAction)
    return p


class _VersionAction(argparse.Action):
    """Print the version and OCR engine status (probed only when asked)."""

    def __init__(self, option_strings, dest, **kwargs):
        super().__init__(option_strings, dest, nargs=0, help="show version and OCR engine status, then exit")

    def __call__(self, parser, namespace, values, option_string=None):
        print(f"pdfparser-cli {__version__}\nOCR engine: {_ocr_status()}")
        parser.exit()


def _utf8_streams() -> None:
    # Redirected output on Windows would otherwise use the legacy code page.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    _utf8_streams()
    args = build_parser().parse_args(argv)
    err = sys.stderr

    def say(msg: str) -> None:
        if not args.quiet:
            print(msg, file=err, flush=True)

    try:
        opts = ParseOptions(
            ocr=args.ocr, lang=args.lang, dpi=args.dpi, layout=args.layout,
            tables=not args.no_tables, password=args.password,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=err)
        return EXIT_USAGE

    if opts.ocr != "never":
        try:
            ocr.get_tesseract().check_lang(opts.lang)
        except ocr.OcrError as exc:
            if opts.ocr == "always":
                print(f"error: {exc}", file=err)
                return EXIT_USAGE
            say(f"warning: {exc}. Scanned pages will be skipped.")

    pdfs, problems = collect_pdfs(args.inputs, args.recursive)
    for problem in problems:
        print(f"error: {problem}", file=err)
    if not pdfs:
        print("error: no PDF files to parse", file=err)
        return EXIT_USAGE

    pairs = plan_outputs(pdfs, None if args.stdout else args.out_dir)
    failed = len(problems)
    live = err.isatty() and not args.quiet
    for n, (pdf, target) in enumerate(pairs, 1):
        prefix = f"[{n}/{len(pairs)}] {pdf.name}"

        def progress(page: int, total: int, prefix=prefix) -> None:
            if live:
                print(f"\r{prefix}: page {page}/{total}", end="", file=err, flush=True)

        result, text = process_file(pdf, None if args.stdout else target, opts, progress)
        if live:
            print("\r\033[K", end="", file=err)
        if not result.ok:
            failed += 1
            print(f"{prefix}: FAILED - {result.error}", file=err, flush=True)
            continue
        dest = "stdout" if args.stdout else str(result.output)
        say(f"{prefix}: {result.summary()} -> {dest}")
        for w in result.warnings:
            say(f"    warning: {w}")
        if args.stdout:
            if len(pairs) > 1:
                print(f"##### {pdf.name} #####\n")
            print(text, flush=True)

    if len(pairs) > 1 or failed:
        parsed = len(pairs) - (failed - len(problems))
        say(f"Done: {parsed} parsed, {failed} failed.")
    return EXIT_SOME_FAILED if failed else EXIT_OK
