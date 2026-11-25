# -*- mode: python ; coding: utf-8 -*-
# PyInstaller build: two executables sharing one folder of libraries.
#   PDFParser.exe      windowed app (no console)
#   pdfparser-cli.exe  console tool
# Build:  pyinstaller --noconfirm --clean pdfparser.spec   ->  dist/PDFParser/
# The Tesseract folder is copied in afterwards (see .github/workflows/build-windows.yml).

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

datas = (
    collect_data_files("pdfminer")  # CMap tables for CJK and other encodings
    + collect_data_files("pypdfium2")
    + collect_data_files("pypdfium2_raw")
)
binaries = collect_dynamic_libs("pypdfium2_raw")  # pdfium.dll
excludes = ["pytest", "fpdf", "fontTools", "PyInstaller", "setuptools", "pip"]


def analysis(script):
    return Analysis(
        [script],
        pathex=[],
        binaries=binaries,
        datas=datas,
        hiddenimports=[],
        hookspath=[],
        runtime_hooks=[],
        excludes=excludes,
        noarchive=False,
    )


a_gui = analysis("pdfparser_gui.py")
a_cli = analysis("pdfparser_cli.py")

exe_gui = EXE(
    PYZ(a_gui.pure),
    a_gui.scripts,
    [],
    exclude_binaries=True,
    name="PDFParser",
    console=False,
    upx=False,
)
exe_cli = EXE(
    PYZ(a_cli.pure),
    a_cli.scripts,
    [],
    exclude_binaries=True,
    name="pdfparser-cli",
    console=True,
    upx=False,
)

coll = COLLECT(
    exe_gui,
    a_gui.binaries,
    a_gui.datas,
    exe_cli,
    a_cli.binaries,
    a_cli.datas,
    name="PDFParser",
    upx=False,
)
