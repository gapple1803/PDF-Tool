from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from make_fixtures import EXPECTED, PASSWORD, make_all  # noqa: E402
from pdfparser import cli, ocr  # noqa: E402
from pdfparser.engine import collect_pdfs, format_text, parse_pdf, plan_outputs, process_file  # noqa: E402
from pdfparser.options import ParseOptions  # noqa: E402
from pdfparser.tables import is_garbage, real_char_count, render_grid  # noqa: E402


def _has_tesseract() -> bool:
    try:
        ocr.get_tesseract().check_lang("eng")
        return True
    except ocr.OcrError:
        return False


needs_ocr = pytest.mark.skipif(not _has_tesseract(), reason="Tesseract with 'eng' not installed")


@pytest.fixture(scope="session")
def fx(tmp_path_factory):
    return make_all(tmp_path_factory.mktemp("fixtures"))


def text_of(path, **kw) -> str:
    result = parse_pdf(path, ParseOptions(**kw))
    assert result.ok, result.error
    return format_text(result)


# ---------- digital text and tables ----------

def test_plain_text(fx):
    out = text_of(fx["text"])
    for snippet in EXPECTED["text.txt"]:
        assert snippet in out


def test_table_drawn_as_grid_in_reading_order(fx):
    result = parse_pdf(fx["table"])
    assert result.table_count == 1
    out = format_text(result)
    for snippet in EXPECTED["table.txt"]:
        assert snippet in out
    assert out.index("Quarterly fruit order") < out.index("| Item") < out.index("Total due")
    assert "| Bananas  | 12  | 0.50  |" in out
    # table words must not be repeated as loose text outside the grid
    assert out.count("Bananas") == 1


def test_no_tables_option_keeps_words(fx):
    out = text_of(fx["table"], tables=False)
    assert "+--" not in out and "Bananas" in out


def test_layout_mode_runs(fx):
    out = text_of(fx["table"], layout=True)
    assert "Quarterly fruit order" in out and "| Apples" in out


# ---------- OCR ----------

@needs_ocr
def test_scanned_page_is_ocrd_automatically(fx):
    result = parse_pdf(fx["scanned"])
    assert result.pages[0].method == "ocr"
    out = format_text(result)
    for snippet in EXPECTED["scanned.txt"]:
        assert snippet in out


@needs_ocr
def test_mixed_document_ocrs_only_the_scanned_page(fx):
    result = parse_pdf(fx["mixed"])
    assert [p.method for p in result.pages] == ["text", "ocr"]
    out = format_text(result)
    for snippet in EXPECTED["mixed.txt"]:
        assert snippet in out


@needs_ocr
def test_ocr_always(fx):
    result = parse_pdf(fx["text"], ParseOptions(ocr="always"))
    assert result.pages[0].method == "ocr"
    assert "quick brown fox" in result.pages[0].text


def test_ocr_never_leaves_scan_empty_with_warning(fx):
    result = parse_pdf(fx["scanned"], ParseOptions(ocr="never"))
    assert result.ok and result.pages[0].method == "text"
    assert "[no text found on this page]" in format_text(result)
    assert "OCR is turned off" in result.warnings[0]


def test_missing_ocr_engine_degrades_gracefully(fx, monkeypatch):
    monkeypatch.setattr(ocr, "_cache", {"result": ocr.OcrError("Tesseract OCR engine not found")})
    result = parse_pdf(fx["mixed"])
    assert result.ok
    assert result.pages[0].method == "text" and "Digital first page" in result.pages[0].text
    assert "OCR is unavailable" in result.pages[1].warning


# ---------- bad input ----------

def test_encrypted_needs_password(fx):
    result = parse_pdf(fx["encrypted"])
    assert not result.ok and "password" in result.error
    assert "Confidential" in text_of(fx["encrypted"], password=PASSWORD)


@pytest.mark.parametrize("name, message", [("corrupt", "damaged"), ("not_pdf", "not a PDF")])
def test_broken_files_report_errors(fx, name, message):
    result = parse_pdf(fx[name])
    assert not result.ok and message in result.error


def test_missing_file(tmp_path):
    result = parse_pdf(tmp_path / "missing.pdf")
    assert not result.ok and "not found" in result.error


# ---------- files and output ----------

def test_collect_and_unique_outputs(tmp_path, fx):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    for d in (a, b):
        (d / "report.pdf").write_bytes(fx["text"].read_bytes())
    pdfs, problems = collect_pdfs([a, b, tmp_path / "nope"])
    assert len(pdfs) == 2 and problems == [f"not found: {tmp_path / 'nope'}"]
    outs = [o.name for _, o in plan_outputs(pdfs, tmp_path / "out")]
    assert outs == ["report.txt", "report_2.txt"]
    nested, _ = collect_pdfs([tmp_path], recursive=True)
    assert len(nested) == 2


def test_process_file_writes_txt(tmp_path, fx):
    target = tmp_path / "out" / "text.txt"
    result, text = process_file(fx["text"], target, ParseOptions())
    assert result.ok and result.output == target
    assert target.read_text(encoding="utf-8") == text
    assert not list(target.parent.glob("*.partial"))


# ---------- CLI ----------

def test_cli_exit_codes(tmp_path, fx):
    good_dir = fx["text"].parent
    assert cli.main([str(good_dir), "-o", str(tmp_path / "o1"), "--ocr", "never", "-q"]) == 0
    assert sorted(p.name for p in (tmp_path / "o1").iterdir()) == sorted(EXPECTED)
    assert cli.main([str(fx["text"]), str(fx["corrupt"]), "-o", str(tmp_path / "o2"), "-q"]) == 1
    assert cli.main([str(tmp_path / "missing.pdf")]) == 2
    with pytest.raises(SystemExit) as exc:
        cli.main(["--ocr", "sometimes", "x.pdf"])
    assert exc.value.code == 2


def test_cli_stdout(capsys, fx):
    assert cli.main([str(fx["text"]), "--stdout", "-q"]) == 0
    assert "The quick brown fox" in capsys.readouterr().out


# ---------- helpers ----------

def test_render_grid_handles_ragged_and_multiline_cells():
    grid = render_grid([["Name", "Notes"], ["A", "line one\nline two"], ["B"]])
    lines = grid.splitlines()
    assert len({len(line) for line in lines}) == 1  # every line the same width
    assert "| A    | line one |" in grid and "|      | line two |" in grid


def test_render_grid_wraps_long_cells():
    grid = render_grid([["k", "v"], ["x", "word " * 30]], max_width=20)
    assert max(len(line) for line in grid.splitlines()) <= 20 + 1 + 7


def test_garbage_detection():
    assert is_garbage("(cid:12)(cid:45)(cid:77) (cid:3)(cid:9)")
    assert not is_garbage("Normal text with one (cid:3) glyph in a long sentence of words.")
    assert real_char_count("(cid:1) ab  c") == 3
