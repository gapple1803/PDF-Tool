"""Window front end (Tkinter). Double-click PDFParser.exe, or drop PDFs onto it."""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import traceback
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import APP_NAME, __version__, ocr
from .engine import ParseResult, collect_pdfs, plan_outputs, process_file
from .options import ParseOptions

OCR_CHOICES = {
    "Auto - only pages without text (scans)": "auto",
    "Always - OCR every page": "always",
    "Never - digital text only": "never",
}


def open_folder(path: Path) -> None:
    if sys.platform.startswith("win"):
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


class App:
    def __init__(self, root: tk.Tk, initial_paths: list[str] | None = None):
        self.root = root
        self.events: queue.Queue = queue.Queue()
        self.cancel = threading.Event()
        self.worker: threading.Thread | None = None
        self.files: list[Path] = []
        self.last_output_dir: Path | None = None
        self.ocr_ready = False

        root.title(f"{APP_NAME} {__version__} (offline)")
        root.geometry("860x660")
        root.minsize(680, 520)
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._build()
        self._add_paths(initial_paths or [])
        threading.Thread(target=self._probe_ocr, daemon=True).start()
        root.after(100, self._poll)

    # ---------- layout ----------
    def _build(self) -> None:
        pad = {"padx": 8, "pady": 4}
        main = ttk.Frame(self.root, padding=10)
        main.pack(fill="both", expand=True)
        main.columnconfigure(0, weight=1)
        main.rowconfigure(0, weight=1)
        main.rowconfigure(3, weight=1)

        # Files
        files = ttk.LabelFrame(main, text="PDF files", padding=6)
        files.grid(row=0, column=0, sticky="nsew")
        files.columnconfigure(0, weight=1)
        files.rowconfigure(1, weight=1)
        bar = ttk.Frame(files)
        bar.grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Button(bar, text="Add files...", command=self._pick_files).pack(side="left")
        ttk.Button(bar, text="Add folder...", command=self._pick_folder).pack(side="left", padx=4)
        self.recursive = tk.BooleanVar(value=True)
        ttk.Checkbutton(bar, text="include subfolders", variable=self.recursive).pack(side="left", padx=(0, 12))
        ttk.Button(bar, text="Remove selected", command=self._remove_selected).pack(side="left")
        ttk.Button(bar, text="Clear", command=self._clear).pack(side="left", padx=4)
        self.listbox = tk.Listbox(files, selectmode="extended", height=8, activestyle="none")
        self.listbox.grid(row=1, column=0, sticky="nsew", pady=(6, 0))
        sb = ttk.Scrollbar(files, orient="vertical", command=self.listbox.yview)
        sb.grid(row=1, column=1, sticky="ns", pady=(6, 0))
        self.listbox.configure(yscrollcommand=sb.set)
        self.count_label = ttk.Label(files, text="No files added")
        self.count_label.grid(row=2, column=0, sticky="w", pady=(4, 0))

        # Options
        opts = ttk.LabelFrame(main, text="Options", padding=6)
        opts.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        opts.columnconfigure(2, weight=1)

        ttk.Label(opts, text="Save .txt files:").grid(row=0, column=0, sticky="w", **pad)
        self.out_mode = tk.StringVar(value="beside")
        ttk.Radiobutton(opts, text="next to each PDF", value="beside", variable=self.out_mode,
                        command=self._sync_out).grid(row=0, column=1, sticky="w")
        out_row = ttk.Frame(opts)
        out_row.grid(row=1, column=1, columnspan=3, sticky="ew")
        out_row.columnconfigure(1, weight=1)
        ttk.Radiobutton(out_row, text="in this folder:", value="folder", variable=self.out_mode,
                        command=self._sync_out).grid(row=0, column=0, sticky="w")
        self.out_dir = tk.StringVar()
        self.out_entry = ttk.Entry(out_row, textvariable=self.out_dir)
        self.out_entry.grid(row=0, column=1, sticky="ew", padx=4)
        self.out_btn = ttk.Button(out_row, text="Browse...", command=self._pick_out_dir)
        self.out_btn.grid(row=0, column=2)

        ttk.Label(opts, text="OCR (scanned pages):").grid(row=2, column=0, sticky="w", **pad)
        self.ocr_choice = tk.StringVar(value=next(iter(OCR_CHOICES)))
        ttk.Combobox(opts, textvariable=self.ocr_choice, values=list(OCR_CHOICES), state="readonly",
                     width=38).grid(row=2, column=1, columnspan=2, sticky="w")

        self.tables = tk.BooleanVar(value=True)
        self.layout = tk.BooleanVar(value=False)
        ttk.Checkbutton(opts, text="Detect tables and draw them as grids", variable=self.tables).grid(
            row=3, column=1, columnspan=2, sticky="w")
        ttk.Checkbutton(opts, text="Keep page layout (columns side by side)", variable=self.layout).grid(
            row=4, column=1, columnspan=2, sticky="w")

        ttk.Label(opts, text="PDF password (if any):").grid(row=5, column=0, sticky="w", **pad)
        self.password = tk.StringVar()
        ttk.Entry(opts, textvariable=self.password, show="*", width=24).grid(row=5, column=1, sticky="w")
        self._sync_out()

        # Actions + progress
        act = ttk.Frame(main)
        act.grid(row=2, column=0, sticky="ew", pady=(10, 4))
        act.columnconfigure(3, weight=1)
        self.parse_btn = ttk.Button(act, text="Parse PDFs", command=self._start)
        self.parse_btn.grid(row=0, column=0)
        self.stop_btn = ttk.Button(act, text="Stop", command=self._stop, state="disabled")
        self.stop_btn.grid(row=0, column=1, padx=4)
        self.open_btn = ttk.Button(act, text="Open output folder", command=self._open_output, state="disabled")
        self.open_btn.grid(row=0, column=2)
        self.progress = ttk.Progressbar(act, mode="determinate", maximum=100)
        self.progress.grid(row=0, column=3, sticky="ew", padx=(12, 0))
        self.status = ttk.Label(act, text="Ready")
        self.status.grid(row=1, column=0, columnspan=4, sticky="w", pady=(4, 0))

        # Log
        logf = ttk.LabelFrame(main, text="Log", padding=6)
        logf.grid(row=3, column=0, sticky="nsew")
        logf.columnconfigure(0, weight=1)
        logf.rowconfigure(0, weight=1)
        self.log = tk.Text(logf, height=10, wrap="word", state="disabled")
        self.log.grid(row=0, column=0, sticky="nsew")
        lsb = ttk.Scrollbar(logf, orient="vertical", command=self.log.yview)
        lsb.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=lsb.set)
        self.log.tag_configure("error", foreground="#b00020")
        self.log.tag_configure("warn", foreground="#8a5a00")
        self.log.tag_configure("ok", foreground="#1b6e20")

        self.ocr_label = ttk.Label(main, text="OCR engine: checking...", foreground="#555")
        self.ocr_label.grid(row=4, column=0, sticky="w", pady=(6, 0))

    # ---------- helpers ----------
    def _write(self, msg: str, tag: str | None = None) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", msg + "\n", (tag,) if tag else ())
        self.log.see("end")
        self.log.configure(state="disabled")

    def _sync_out(self) -> None:
        state = "normal" if self.out_mode.get() == "folder" else "disabled"
        self.out_entry.configure(state=state)
        self.out_btn.configure(state=state)

    def _refresh_list(self) -> None:
        self.listbox.delete(0, "end")
        for f in self.files:
            self.listbox.insert("end", str(f))
        n = len(self.files)
        self.count_label.configure(text=f"{n} file{'s' if n != 1 else ''}" if n else "No files added")

    def _add_paths(self, paths) -> None:
        if not paths:
            return
        found, problems = collect_pdfs(paths, self.recursive.get())
        known = {f.resolve() for f in self.files}
        self.files.extend(f for f in found if f.resolve() not in known)
        for p in problems:
            self._write(p, "warn")
        self._refresh_list()

    def _pick_files(self) -> None:
        paths = filedialog.askopenfilenames(title="Choose PDF files",
                                            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")])
        self._add_paths(list(paths))

    def _pick_folder(self) -> None:
        folder = filedialog.askdirectory(title="Choose a folder with PDF files")
        if folder:
            self._add_paths([folder])

    def _pick_out_dir(self) -> None:
        folder = filedialog.askdirectory(title="Choose where to save the .txt files")
        if folder:
            self.out_dir.set(folder)

    def _remove_selected(self) -> None:
        for i in reversed(self.listbox.curselection()):
            del self.files[i]
        self._refresh_list()

    def _clear(self) -> None:
        self.files.clear()
        self._refresh_list()

    def _probe_ocr(self) -> None:
        try:
            self.events.put(("ocr", True, ocr.get_tesseract().describe()))
        except ocr.OcrError as exc:
            self.events.put(("ocr", False, f"{exc}. Scanned pages will be skipped."))

    # ---------- run ----------
    def _start(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        if not self.files:
            messagebox.showinfo(APP_NAME, "Add one or more PDF files first.")
            return
        out_dir = None
        if self.out_mode.get() == "folder":
            out_dir = self.out_dir.get().strip()
            if not out_dir:
                messagebox.showinfo(APP_NAME, "Choose an output folder, or select 'next to each PDF'.")
                return
        opts = ParseOptions(
            ocr=OCR_CHOICES[self.ocr_choice.get()],
            layout=self.layout.get(),
            tables=self.tables.get(),
            password=self.password.get() or None,
        )
        pairs = plan_outputs(list(self.files), out_dir)
        self.last_output_dir = Path(out_dir) if out_dir else None
        self.cancel.clear()
        self.parse_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.progress["value"] = 0
        self._write(f"--- Parsing {len(pairs)} file(s) ---")
        self.worker = threading.Thread(target=self._work, args=(pairs, opts), daemon=True)
        self.worker.start()

    def _work(self, pairs, opts: ParseOptions) -> None:
        total = len(pairs)
        for i, (pdf, target) in enumerate(pairs):
            if self.cancel.is_set():
                break

            def prog(page: int, pages: int, i=i, name=pdf.name) -> None:
                self.events.put(("page", i, total, name, page, pages))

            self.events.put(("page", i, total, pdf.name, 0, 1))
            try:
                result, _ = process_file(pdf, target, opts, prog, self.cancel)
            except Exception as exc:  # defensive: never kill the worker silently
                result = ParseResult(source=pdf, error=f"unexpected error: {exc}")
            self.events.put(("file", i, total, result))
        self.events.put(("done", self.cancel.is_set()))

    def _stop(self) -> None:
        self.cancel.set()
        self.stop_btn.configure(state="disabled")
        self.status.configure(text="Stopping after the current page...")

    def _poll(self) -> None:
        try:
            while True:
                self._handle(self.events.get_nowait())
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def _handle(self, ev) -> None:
        kind = ev[0]
        if kind == "ocr":
            _, ok, text = ev
            self.ocr_ready = ok
            self.ocr_label.configure(text=f"OCR engine: {text}", foreground="#555" if ok else "#b00020")
        elif kind == "page":
            _, i, total, name, page, pages = ev
            self.progress["value"] = 100 * (i + (page / max(pages, 1))) / total
            if page:
                self.status.configure(text=f"File {i + 1} of {total}: {name} - page {page} of {pages}")
        elif kind == "file":
            _, i, total, result = ev
            self.progress["value"] = 100 * (i + 1) / total
            if result.ok:
                self._write(f"OK  {result.source.name}: {result.summary()} -> {result.output}", "ok")
                if result.output and self.last_output_dir is None:
                    self.last_output_dir = result.output.parent
                for w in result.warnings:
                    self._write(f"    {w}", "warn")
            else:
                self._write(f"ERR {result.source.name}: {result.error}", "error")
        elif kind == "done":
            cancelled = ev[1]
            self.parse_btn.configure(state="normal")
            self.stop_btn.configure(state="disabled")
            self.status.configure(text="Stopped" if cancelled else "Finished")
            self._write("--- Stopped ---" if cancelled else "--- Finished ---")
            if self.last_output_dir and self.last_output_dir.exists():
                self.open_btn.configure(state="normal")

    def _open_output(self) -> None:
        if self.last_output_dir:
            try:
                open_folder(self.last_output_dir)
            except OSError as exc:
                messagebox.showerror(APP_NAME, f"Could not open the folder:\n{exc}")

    def _on_close(self) -> None:
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno(APP_NAME, "Parsing is still running. Stop and quit?"):
                return
            self.cancel.set()
        self.root.destroy()


def _windows_setup() -> None:
    if sys.platform.startswith("win"):
        try:
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(1)  # crisp text on high-DPI screens
        except Exception:
            pass


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # A windowed .exe has no console streams; give stray prints somewhere to go.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")

    if argv[:1] == ["--selftest"]:
        return _selftest(argv[1] if len(argv) > 1 else None)

    _windows_setup()
    root = tk.Tk()
    App(root, initial_paths=argv)
    root.mainloop()
    return 0


def _selftest(report: str | None) -> int:
    """Build the window, check OCR, close. Used by CI to prove the GUI exe starts."""
    lines, code = [], 0
    try:
        root = tk.Tk()
        App(root)
        root.update()
        lines.append(f"window ok (Tk {tk.TkVersion})")
        try:
            lines.append("ocr ok: " + ocr.get_tesseract().describe())
        except ocr.OcrError as exc:
            lines.append(f"ocr missing: {exc}")
            code = 1
        root.after(300, root.destroy)
        root.mainloop()
    except Exception:
        lines.append(traceback.format_exc())
        code = 1
    text = "\n".join(lines) + "\n"
    if report:
        Path(report).write_text(text, encoding="utf-8")
    else:
        print(text)
    return code
