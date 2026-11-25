"""Smoke-test a *built* app folder (dist/PDFParser), the way a user would run it.

    python tests/smoke_test.py DIST_DIR FIXTURES_DIR OUT_DIR [--expect-bundled]

FIXTURES_DIR comes from tests/make_fixtures.py. With --expect-bundled the OCR
engine must be the copy inside DIST_DIR/tesseract (proves the zip is self-contained).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_fixtures import EXPECTED, PASSWORD  # noqa: E402

EXE = ".exe" if os.name == "nt" else ""
failures: list[str] = []


def check(cond: bool, what: str) -> None:
    print(("  ok   " if cond else "  FAIL ") + what)
    if not cond:
        failures.append(what)


def run(cmd: list[str], timeout: int = 300) -> subprocess.CompletedProcess:
    print("$ " + " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    if proc.stdout.strip():
        print(proc.stdout.rstrip()[:2000])
    if proc.stderr.strip():
        print(proc.stderr.rstrip()[:2000])
    return proc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dist")
    ap.add_argument("fixtures")
    ap.add_argument("out")
    ap.add_argument("--expect-bundled", action="store_true")
    args = ap.parse_args()
    dist, fixtures, out = Path(args.dist), Path(args.fixtures), Path(args.out)
    cli = str(dist / f"pdfparser-cli{EXE}")
    gui = str(dist / f"PDFParser{EXE}")

    ver = run([cli, "--version"])
    check(ver.returncode == 0, "cli --version exits 0")
    check("Tesseract" in ver.stdout, "OCR engine found")
    if args.expect_bundled:
        check("bundled" in ver.stdout, "OCR engine is the bundled copy")

    res = run([cli, str(fixtures), "-o", str(out)])
    check(res.returncode == 0, "parsing good fixtures exits 0")
    for name, snippets in EXPECTED.items():
        path = out / name
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        check(path.exists(), f"{name} written")
        for s in snippets:
            check(s in text, f"{name} contains {s!r}")

    enc = run([cli, str(fixtures / "bad" / "encrypted.pdf"), "--password", PASSWORD, "--stdout", "-q"])
    check(enc.returncode == 0 and "Confidential" in enc.stdout, "encrypted PDF opens with --password")

    bad = run([cli, str(fixtures / "bad"), "-o", str(out / "bad")])
    check(bad.returncode == 1, "broken files exit 1 without crashing")

    report = out / "gui-selftest.txt"
    try:
        g = run([gui, "--selftest", str(report)], timeout=120)
        text = report.read_text(encoding="utf-8") if report.exists() else ""
        print(text)
        check(g.returncode == 0 and "window ok" in text, "window app starts (Tk bundled)")
        if args.expect_bundled:
            check("ocr ok" in text and "bundled" in text, "window app finds bundled OCR")
    except subprocess.TimeoutExpired:
        check(False, "window app self-test finished within 120s")

    print(f"\n{'PASSED' if not failures else f'FAILED ({len(failures)})'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
