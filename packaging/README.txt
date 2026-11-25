PDF Parser - offline PDF to text
================================

Everything runs on this computer. Nothing is uploaded and no internet
connection is needed. Text, tables and scanned pages (OCR) are all
handled locally.

FIRST RUN
---------
1. Unzip the whole folder somewhere, e.g. Documents\PDFParser.
   Keep all the files together: the program needs the _internal and
   tesseract folders that sit next to it.
2. Double-click PDFParser.exe.
   This app is not code-signed, so Windows may show "Windows protected
   your PC". Click "More info", then "Run anyway". This only happens
   the first time.

WINDOW APP (PDFParser.exe)
--------------------------
- Click "Add files..." or "Add folder...". You can also drop PDFs
  onto the PDFParser.exe icon.
- Choose where the .txt files go: next to each PDF, or one folder.
- Click "Parse PDFs". The log shows each file, how many pages were
  read with OCR and how many tables were found.
- Click "Open output folder" to see the results.

COMMAND LINE (pdfparser-cli.exe)
--------------------------------
Open Command Prompt or PowerShell in this folder, then for example:

  pdfparser-cli report.pdf
  pdfparser-cli C:\Scans -r -o C:\Text
  pdfparser-cli statement.pdf --stdout > statement.txt
  pdfparser-cli locked.pdf --password MyPassword
  pdfparser-cli --help

Options:
  -o DIR        write .txt files into DIR (default: next to each PDF)
  -r            include PDFs in subfolders
  --ocr MODE    auto (default) | always | never
  --layout      keep the page layout (columns side by side)
  --no-tables   do not draw tables as grids
  --password    password for protected PDFs
  --stdout      print the text instead of writing files

Exit codes: 0 = all files parsed, 1 = some files failed, 2 = bad usage.

WHAT YOU GET
------------
One UTF-8 .txt file per PDF:

  ===== Page 1 =====
  ...text...
  +----------+-----+
  | Item     | Qty |      <- tables drawn as grids
  +----------+-----+

  ===== Page 2 (OCR) =====     <- scanned page read with OCR
  ...text...

GOOD TO KNOW
------------
- Auto OCR runs only on pages with no usable text, such as scans,
  photos of documents or broken fonts. Use "Always" if a page's
  text looks wrong.
- Tables are found from their ruling lines. Tables without borders
  come out as ordinary aligned text. Tables on scanned pages come out
  as OCR text lines, not grids.
- OCR language: English. OCR takes a few seconds per page.
