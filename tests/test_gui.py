"""Drive the Tk window end to end (skipped where no display is available)."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

tk = pytest.importorskip("tkinter")

from make_fixtures import make_all  # noqa: E402
from pdfparser.gui import App  # noqa: E402


@pytest.fixture
def root():
    try:
        r = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"no display: {exc}")
    r.withdraw()
    yield r
    r.destroy()


def test_gui_parses_files_into_chosen_folder(root, tmp_path):
    fx = make_all(tmp_path / "in")
    out = tmp_path / "out"
    app = App(root, initial_paths=[str(fx["text"]), str(fx["table"]), str(fx["corrupt"])])
    assert app.listbox.size() == 3

    app.out_mode.set("folder")
    app.out_dir.set(str(out))
    app._sync_out()
    app._start()
    deadline = time.time() + 60
    while app.worker.is_alive() or not app.events.empty():
        root.update()
        assert time.time() < deadline, "GUI parse did not finish"
        time.sleep(0.02)
    root.update()

    log = app.log.get("1.0", "end")
    assert "OK  text.pdf" in log and "OK  table.pdf" in log
    assert "ERR corrupt.pdf" in log and "--- Finished ---" in log
    assert (out / "text.txt").exists() and (out / "table.txt").exists()
    assert str(app.open_btn["state"]) == "normal"
    assert app.progress["value"] == pytest.approx(100)
