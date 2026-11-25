# PDF Parser (offline)

Turns PDFs into plain `.txt` files on Windows with no internet connection.

It does three things:

- **Digital text**: reads the text that is stored in the PDF.
- **Tables**: finds tables by their ruling lines and draws them as text grids, in the place where they appear on the page.
- **Scanned pages**: reads them with the bundled Tesseract OCR engine.

It ships as a portable folder with two programs:

| Program | Use |
|---|---|
| `PDFParser.exe` | Window app. Double-click it, add files or folders, then click **Parse PDFs**. |
| `pdfparser-cli.exe` | Command line, e.g. `pdfparser-cli C:\Scans -r -o C:\Text`. Run `pdfparser-cli --help` for all options. |

The end-user guide is [packaging/README.txt](packaging/README.txt), and it is copied into the zip.

## Getting the Windows build

GitHub Actions builds it on every push to `main` ([.github/workflows/build-windows.yml](.github/workflows/build-windows.yml)):

1. Go to **Actions → Build Windows app**, open the latest green run and download **PDFParser-windows-x64**.
2. Unzip the file and run `PDFParser.exe`.

To publish a release with the zip attached, push a tag:

```bash
git tag v1.0.0
```

```bash
git push origin v1.0.0
```

Before uploading, CI runs these checks on Windows:

1. Unit tests.
2. The PyInstaller build.
3. Bundling a trimmed Tesseract (English + OSD).
4. Removing the system Tesseract.
5. A smoke test of the built `.exe` files against generated PDFs ([tests/smoke_test.py](tests/smoke_test.py)).

## How it works

| File | Role |
|---|---|
| [pdfparser/engine.py](pdfparser/engine.py) | Page loop, OCR decision, `.txt` output |
| [pdfparser/tables.py](pdfparser/tables.py) | Table detection, grid drawing, splitting text from tables |
| [pdfparser/ocr.py](pdfparser/ocr.py) | Finds Tesseract (bundled → `PDFPARSER_TESSERACT` → PATH), renders pages, runs OCR through stdin |
| [pdfparser/cli.py](pdfparser/cli.py), [pdfparser/gui.py](pdfparser/gui.py) | The two front ends |
| [pdfparser.spec](pdfparser.spec) | PyInstaller build: two exes that share one `_internal` folder |

In `auto` mode a page is OCR'd only when it has fewer than 25 real characters, when it is mostly an image with little text, or when its text is unmapped `(cid:NN)` glyphs from a broken font.

## Developing (macOS / Linux / Windows)

Tesseract must be installed: on macOS use `brew install tesseract`; on Windows use the UB Mannheim build. You need Python 3.10–3.12.

```bash
python3 -m venv .venv
```

```bash
.venv/bin/pip install -r requirements-dev.txt
```

```bash
.venv/bin/python -m pytest -q
```

```bash
.venv/bin/python pdfparser_cli.py some.pdf --stdout
```

```bash
.venv/bin/python pdfparser_gui.py
```

All bundled components use permissive licences: MIT, Apache-2.0, BSD, PSF. PyMuPDF (AGPL) is deliberately not used. See [packaging/THIRD_PARTY_NOTICES.txt](packaging/THIRD_PARTY_NOTICES.txt).
