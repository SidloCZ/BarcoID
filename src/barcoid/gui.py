"""
Standalone Desktop GUI for BarcoID.
Click-through 4-step wizard with native High-DPI text rendering, maximized startup,
responsive layouts for smaller window sizes, strict high-contrast palette (#111111 black
on #FFFFFF white + #4C9E45 botanical green), concurrent 4-stream circular spinners,
Step 4 Results table with single-cell highlighting on Concordance_Status and QC_Flag,
and a hidden Diagnostics / Bug Report terminal triggered via Ctrl+Shift+D.
"""

import ctypes
import logging
import os
import platform
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
import traceback
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Dict, List, Optional, Tuple

import requests

from barcoid import __version__
from barcoid.config import BarcoIDConfig
from barcoid.parsers.fasta import FastaParser
from barcoid.parsers.headers import DEFAULT_GENUS_PREFIXES
from barcoid.parsers.metadata import MetadataParser
from barcoid.pipeline import BarcoIDPipeline

# Strict High-Contrast Palette: Pure White (#FFFFFF) + Pure Black (#111111) + Green (#4C9E45)
# Plus subtle alert tint (#FDECEC) used exclusively for MISMATCH_ALERT / non-OK QC single cells.
PALETTE = {
    "bg_canvas": "#FFFFFF",       # Pure white background
    "card_outer": "#FFFFFF",      # Pure white container
    "card_inner": "#FFFFFF",      # Pure white surface
    "border": "#111111",          # Crisp high-contrast black border
    "primary": "#4C9E45",         # Brand accent green
    "primary_hover": "#3B8235",   # Hover green
    "primary_tint": "#EAF4E9",    # Soft green tint (always paired with #111111 text)
    "alert_tint": "#FDECEC",      # Soft alert cell highlight for MISMATCH_ALERT / QC flags
    "text_dark": "#111111",       # High-contrast black text everywhere on light surfaces
    "text_muted": "#111111",      # No gray text: secondary labels also use crisp #111111
}

# Strictly 3 Font Styles Across the Entire Application
FONT_TITLE = ("Segoe UI", 16, "bold")
FONT_HEADING = ("Segoe UI", 11, "bold")
FONT_BODY = ("Segoe UI", 11)

SVG_ICON_PATH = Path(__file__).resolve().parent / "assets" / "logo_4streams.svg"

RESULTS_COLUMNS = [
    "Sample_ID",
    "Field_Morpho",
    "Field_Genus",
    "BOLD_Taxon",
    "BOLD_%",
    "NCBI_Taxon",
    "NCBI_%",
    "GBIF_Name",
    "Consensus_Species",
    "Concordance_Status",
    "QC_Flag",
]


def get_cell_highlight(col_name: str, value: str) -> Tuple[str, str, bool]:
    """
    Returns (bg_color, fg_color, is_bold) for a single cell in the Step 4 Results table.
    Only Concordance_Status and QC_Flag cells are colored; all other cells remain #FFFFFF / #111111.
    """
    val = (value or "").strip()
    if col_name == "Concordance_Status":
        if val == "CONCORDANT":
            return PALETTE["primary"], "#FFFFFF", True
        if val == "NEW_ASSIGNMENT":
            return PALETTE["primary_tint"], PALETTE["text_dark"], True
        if val == "MISMATCH_ALERT":
            return PALETTE["alert_tint"], PALETTE["text_dark"], True
        return PALETTE["card_inner"], PALETTE["text_dark"], False

    if col_name == "QC_Flag":
        if val == "OK":
            return PALETTE["primary"], "#FFFFFF", True
        if val:
            return PALETTE["alert_tint"], PALETTE["text_dark"], True
        return PALETTE["card_inner"], PALETTE["text_dark"], False

    return PALETTE["card_inner"], PALETTE["text_dark"], False


def enable_high_dpi():
    """Enables native Per-Monitor High-DPI rendering on Windows so fullscreen text is crisp."""
    if sys.platform.startswith("win"):
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(1)
            except Exception:
                try:
                    ctypes.windll.user32.SetProcessDPIAware()
                except Exception:
                    pass


class QueueLogHandler(logging.Handler):
    """Routes Python logging records into a thread-safe queue for the GUI and Terminal."""

    def __init__(self, log_queue: "queue.Queue[str]"):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record: logging.LogRecord):
        try:
            msg = self.format(record)
            self.log_queue.put(msg)
        except Exception:
            self.handleError(record)


def default_portable_base_dir(fasta_path: Optional[Path] = None) -> Path:
    """Determines a sensible base folder for output and cache in portable/GUI mode."""
    if fasta_path and fasta_path.parent.exists():
        return fasta_path.parent
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def build_config_from_inputs(
    fasta_path: Path,
    output_dir: Optional[Path] = None,
    taxon: str = "Formicidae",
    max_sequences_str: str = "",
    ncbi_email: str = "",
    ncbi_api_key: str = "",
    dry_run: bool = False,
    force_refresh: bool = False,
) -> BarcoIDConfig:
    """Constructs a validated BarcoIDConfig from GUI form values."""
    base_dir = default_portable_base_dir(fasta_path)
    resolved_out = Path(output_dir) if output_dir else (base_dir / "results")
    resolved_cache = base_dir / ".id_cache"

    max_seq: Optional[int] = None
    if max_sequences_str and max_sequences_str.strip():
        val = int(max_sequences_str.strip())
        if val > 0:
            max_seq = val

    cfg = BarcoIDConfig(
        cache_dir=resolved_cache,
        output_dir=resolved_out,
        max_sequences=max_seq,
        dry_run=dry_run,
        force_refresh=force_refresh,
        ncbi_email=ncbi_email.strip() or None,
        ncbi_api_key=ncbi_api_key.strip() or None,
    )
    clean_taxon = taxon.strip()
    if clean_taxon:
        cfg.ncbi_entrez_query = f"{clean_taxon}[Organism:exp]"
    return cfg


def check_api_endpoints() -> List[str]:
    """Pings BOLD v5, NCBI BLAST, and GBIF APIs to verify live network reachability."""
    endpoints = [
        ("BOLD Systems v5", "https://id.boldsystems.org/"),
        ("NCBI GenBank QBLAST", "https://blast.ncbi.nlm.nih.gov/Blast.cgi?CMD=Info"),
        ("GBIF Backbone API", "https://api.gbif.org/v1/species/match?name=Formica"),
    ]
    report_lines: List[str] = []
    for name, url in endpoints:
        t0 = time.perf_counter()
        try:
            resp = requests.get(url, timeout=10)
            ms = int((time.perf_counter() - t0) * 1000)
            report_lines.append(f"[OK] {name}: HTTP {resp.status_code} ({ms} ms) -> {url}")
        except Exception as exc:
            ms = int((time.perf_counter() - t0) * 1000)
            report_lines.append(f"[FAIL] {name}: {exc} ({ms} ms) -> {url}")
    return report_lines


def open_path_in_os(target: Path):
    """Opens a file or directory in the operating system's native explorer/viewer."""
    target = Path(target).resolve()
    if not target.exists():
        return
    if sys.platform.startswith("win"):
        os.startfile(str(target))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(target)])
    else:
        subprocess.Popen(["xdg-open", str(target)])


class BarcoIDApp:
    """Main click-through 4-step desktop wizard for BarcoID."""

    def __init__(self, root: tk.Tk):
        self.root = root
        self._apply_dpi_scaling()
        self.root.title(f"BarcoID v{__version__}")
        self.root.geometry("1120x760")
        self.root.minsize(760, 560)
        self.root.configure(bg=PALETTE["bg_canvas"])
        self._maximize_window()

        # State variables
        self.current_step = 0
        self.fasta_var = tk.StringVar()
        self.metadata_var = tk.StringVar()
        self.output_dir_var = tk.StringVar(value=str(default_portable_base_dir() / "results"))
        self.taxon_var = tk.StringVar(value="Formicidae")
        self.max_seq_var = tk.StringVar(value="")
        self.ncbi_email_var = tk.StringVar(value=os.environ.get("NCBI_EMAIL", ""))
        self.ncbi_key_var = tk.StringVar(value=os.environ.get("NCBI_API_KEY", ""))
        self.dry_run_var = tk.BooleanVar(value=False)
        self.force_refresh_var = tk.BooleanVar(value=False)

        # Metadata preview & column picker state
        self.meta_columns: List[str] = []
        self.meta_rows: List[List[str]] = []
        self.sample_col_var = tk.StringVar(value="sample_id")
        self.morpho_col_var = tk.StringVar(value="field_morphospecies")
        self.click_target_var = tk.StringVar(value="morpho")
        self.morpho_preview_var = tk.StringVar(
            value="Optional: Load a metadata file (.csv, .tsv, .xlsx) to preview rows and click the Morphospecies column."
        )
        self.run_overview_var = tk.StringVar(value="")

        # Execution, Spinner Animation, Results & Diagnostics state
        self.is_running = False
        self.spinner_angle = 0
        self.service_states: Dict[str, str] = {
            "morpho": "Idle",
            "bold": "Idle",
            "ncbi": "Idle",
            "gbif": "Idle",
        }
        self.last_results_rows: List[Dict[str, Any]] = []
        self.last_excel_path: Optional[Path] = None
        self.last_error_trace: str = ""
        self.log_history: List[str] = []
        self.log_queue: "queue.Queue[str]" = queue.Queue()
        self.ui_queue: "queue.Queue[Tuple[str, Any]]" = queue.Queue()
        self.terminal_win: Optional[tk.Toplevel] = None
        self.terminal_text: Optional[tk.Text] = None

        self._configure_styles()
        self._build_layout()
        self._bind_shortcuts()
        self._attach_logging()
        self.show_step(0)
        self._poll_queues()
        self._animate_spinners()

    def _maximize_window(self):
        """Maximizes the application window on startup while keeping standard window controls."""
        try:
            if sys.platform.startswith("win"):
                self.root.state("zoomed")
            else:
                self.root.attributes("-zoomed", True)
        except Exception:
            pass

    def _apply_dpi_scaling(self):
        """Synchronizes Tkinter's internal font/widget scaling factor with the monitor DPI."""
        try:
            dpi = self.root.winfo_fpixels("1i")
            scale = max(1.0, float(dpi) / 72.0)
            self.root.tk.call("tk", "scaling", scale)
            self.dpi_scale = float(dpi) / 96.0
        except Exception:
            self.dpi_scale = 1.0

    def _bind_shortcuts(self):
        """Binds Ctrl+Shift+D to toggle the hidden Diagnostics & Bug Report window."""
        self.root.bind_all("<Control-Shift-D>", self.toggle_terminal_window)
        self.root.bind_all("<Control-Shift-d>", self.toggle_terminal_window)

    def _configure_styles(self):
        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")

        row_h = max(32, int(32 * self.dpi_scale))
        style.configure(
            "Treeview",
            background=PALETTE["card_inner"],
            fieldbackground=PALETTE["card_inner"],
            foreground=PALETTE["text_dark"],
            rowheight=row_h,
            font=FONT_BODY,
            borderwidth=1,
        )
        style.configure(
            "Treeview.Heading",
            background=PALETTE["primary_tint"],
            foreground=PALETTE["text_dark"],
            font=FONT_HEADING,
            relief="solid",
            borderwidth=1,
            padding=(10, 8),
        )
        style.map(
            "Treeview.Heading",
            background=[("active", PALETTE["primary"])],
            foreground=[("active", "#FFFFFF")],
        )
        style.map(
            "Treeview",
            background=[("selected", PALETTE["primary_tint"])],
            foreground=[("selected", PALETTE["text_dark"])],
        )
        style.configure(
            "Green.Horizontal.TProgressbar",
            troughcolor=PALETTE["card_inner"],
            background=PALETTE["primary"],
            bordercolor=PALETTE["border"],
            lightcolor=PALETTE["primary"],
            darkcolor=PALETTE["primary"],
            thickness=max(18, int(18 * self.dpi_scale)),
        )
        style.configure(
            "TCombobox",
            fieldbackground=PALETTE["card_inner"],
            background=PALETTE["card_inner"],
            foreground=PALETTE["text_dark"],
            bordercolor=PALETTE["border"],
            arrowcolor=PALETTE["text_dark"],
            padding=6,
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", PALETTE["card_inner"])],
            foreground=[("readonly", PALETTE["text_dark"])],
        )

    def _draw_4streams_icon(self, canvas: tk.Canvas):
        """Renders the 4-streams-knotting-together vector icon onto the header canvas."""
        canvas.create_oval(2, 2, 46, 46, fill=PALETTE["primary_tint"], outline=PALETTE["primary"], width=2)

        canvas.create_line(
            9, 12, 20, 13, 25, 31, 33, 24, 40, 24,
            fill=PALETTE["text_dark"], width=2.4, smooth=True, capstyle="round"
        )
        canvas.create_line(
            9, 36, 20, 35, 25, 17, 33, 24, 40, 24,
            fill=PALETTE["text_dark"], width=2.4, smooth=True, capstyle="round"
        )
        canvas.create_line(
            9, 20, 19, 20, 25, 15, 31, 24, 40, 24,
            fill=PALETTE["primary"], width=2.8, smooth=True, capstyle="round"
        )
        canvas.create_line(
            9, 28, 19, 28, 25, 33, 31, 24, 40, 24,
            fill=PALETTE["primary"], width=2.8, smooth=True, capstyle="round"
        )

        for y_pos, col in [
            (12, PALETTE["text_dark"]),
            (20, PALETTE["primary"]),
            (28, PALETTE["primary"]),
            (36, PALETTE["text_dark"]),
        ]:
            canvas.create_oval(6.5, y_pos - 2.5, 11.5, y_pos + 2.5, fill=col, outline="")

        canvas.create_oval(22.5, 20.5, 29.5, 27.5, fill=PALETTE["card_inner"], outline=PALETTE["primary"], width=2)
        canvas.create_oval(37, 20.5, 44, 27.5, fill=PALETTE["primary"], outline="")

    def _build_layout(self):
        # 1. Header Bar + 4-Step Wizard Navigation
        top_bar = tk.Frame(
            self.root,
            bg=PALETTE["card_inner"],
            highlightbackground=PALETTE["border"],
            highlightthickness=1,
            padx=20,
            pady=10,
        )
        top_bar.pack(fill="x")

        brand_frame = tk.Frame(top_bar, bg=PALETTE["card_inner"])
        brand_frame.pack(side="left")

        logo_canvas = tk.Canvas(
            brand_frame, width=48, height=48, bg=PALETTE["card_inner"], highlightthickness=0
        )
        logo_canvas.pack(side="left", padx=(0, 10))
        self._draw_4streams_icon(logo_canvas)

        tk.Label(
            brand_frame,
            text="BarcoID",
            font=FONT_TITLE,
            fg=PALETTE["text_dark"],
            bg=PALETTE["card_inner"],
        ).pack(side="left")

        # Click-through Wizard Step Tabs (4 Steps)
        stepper_frame = tk.Frame(top_bar, bg=PALETTE["card_inner"])
        stepper_frame.pack(side="right")

        self.step_buttons: List[tk.Button] = []
        step_titles = [
            "1. Sequences",
            "2. Metadata Column",
            "3. Run",
            "4. Results",
        ]
        for idx, title in enumerate(step_titles):
            btn = tk.Button(
                stepper_frame,
                text=title,
                command=lambda i=idx: self.show_step(i),
                font=FONT_HEADING,
                relief="solid",
                bd=1,
                padx=12,
                pady=6,
                cursor="hand2",
            )
            btn.pack(side="left", padx=(6, 0))
            self.step_buttons.append(btn)

        # 2. Main Step Page Container
        self.page_container = tk.Frame(self.root, bg=PALETTE["bg_canvas"], padx=20, pady=16)
        self.page_container.pack(fill="both", expand=True)

        self.step_frames: List[tk.Frame] = []
        self._build_step1_sequences()
        self._build_step2_metadata()
        self._build_step3_run()
        self._build_step4_results()

    # ------------------------------------------------------------------
    # STEP 1: SEQUENCES & PARAMETERS
    # ------------------------------------------------------------------
    def _build_step1_sequences(self):
        page = tk.Frame(
            self.page_container,
            bg=PALETTE["card_inner"],
            highlightbackground=PALETTE["border"],
            highlightthickness=1,
            padx=28,
            pady=24,
        )
        self.step_frames.append(page)

        tk.Label(
            page,
            text="Step 1: Select Input FASTA & Taxonomic Scope",
            font=FONT_TITLE,
            fg=PALETTE["text_dark"],
            bg=PALETTE["card_inner"],
            anchor="w",
        ).pack(fill="x", pady=(0, 6))

        tk.Label(
            page,
            text="Choose your query DNA barcode FASTA file and target taxon filter.",
            font=FONT_BODY,
            fg=PALETTE["text_dark"],
            bg=PALETTE["card_inner"],
            anchor="w",
        ).pack(fill="x", pady=(0, 20))

        form = tk.Frame(page, bg=PALETTE["card_inner"])
        form.pack(fill="x")
        form.columnconfigure(1, weight=1)

        # FASTA File
        tk.Label(
            form, text="Input FASTA File:", font=FONT_HEADING,
            fg=PALETTE["text_dark"], bg=PALETTE["card_inner"]
        ).grid(row=0, column=0, sticky="w", padx=(0, 14), pady=8)

        tk.Entry(
            form, textvariable=self.fasta_var, font=FONT_BODY,
            bg=PALETTE["card_inner"], fg=PALETTE["text_dark"], relief="solid", bd=1
        ).grid(row=0, column=1, sticky="ew", padx=(0, 10), pady=8, ipady=6)

        self._make_button(form, "Browse FASTA", self.browse_fasta, primary=True).grid(
            row=0, column=2, sticky="ew", pady=8
        )

        # Output Folder
        tk.Label(
            form, text="Output Folder:", font=FONT_HEADING,
            fg=PALETTE["text_dark"], bg=PALETTE["card_inner"]
        ).grid(row=1, column=0, sticky="w", padx=(0, 14), pady=8)

        tk.Entry(
            form, textvariable=self.output_dir_var, font=FONT_BODY,
            bg=PALETTE["card_inner"], fg=PALETTE["text_dark"], relief="solid", bd=1
        ).grid(row=1, column=1, sticky="ew", padx=(0, 10), pady=8, ipady=6)

        self._make_button(form, "Browse Folder", self.browse_output_dir, primary=False).grid(
            row=1, column=2, sticky="ew", pady=8
        )

        # Target Taxon
        tk.Label(
            form, text="Target Taxon Filter:", font=FONT_HEADING,
            fg=PALETTE["text_dark"], bg=PALETTE["card_inner"]
        ).grid(row=2, column=0, sticky="w", padx=(0, 14), pady=8)

        taxon_row = tk.Frame(form, bg=PALETTE["card_inner"])
        taxon_row.grid(row=2, column=1, columnspan=2, sticky="ew", pady=8)

        taxon_combo = ttk.Combobox(
            taxon_row,
            textvariable=self.taxon_var,
            values=["Formicidae", "Hymenoptera", "Insecta", "Arthropoda", "Animalia", "Fungi", "Plantae"],
            width=20,
            font=FONT_BODY,
        )
        taxon_combo.pack(side="left", padx=(0, 20))

        tk.Label(
            taxon_row, text="Max Sequences (optional):", font=FONT_HEADING,
            fg=PALETTE["text_dark"], bg=PALETTE["card_inner"]
        ).pack(side="left", padx=(0, 8))

        tk.Entry(
            taxon_row, textvariable=self.max_seq_var, width=10, font=FONT_BODY,
            bg=PALETTE["card_inner"], fg=PALETTE["text_dark"], relief="solid", bd=1
        ).pack(side="left", ipady=4)

        # Checkboxes
        flags_row = tk.Frame(form, bg=PALETTE["card_inner"])
        flags_row.grid(row=3, column=1, columnspan=2, sticky="w", pady=8)

        tk.Checkbutton(
            flags_row, text="Dry Run (inspect cache only)", variable=self.dry_run_var,
            bg=PALETTE["card_inner"], fg=PALETTE["text_dark"],
            activebackground=PALETTE["card_inner"], selectcolor=PALETTE["card_inner"], font=FONT_BODY
        ).pack(side="left", padx=(0, 20))

        tk.Checkbutton(
            flags_row, text="Force Refresh (bypass disk cache)", variable=self.force_refresh_var,
            bg=PALETTE["card_inner"], fg=PALETTE["text_dark"],
            activebackground=PALETTE["card_inner"], selectcolor=PALETTE["card_inner"], font=FONT_BODY
        ).pack(side="left")

        # Footer Navigation
        footer1 = tk.Frame(page, bg=PALETTE["card_inner"])
        footer1.pack(side="bottom", fill="x", pady=(16, 0))

        self._make_button(
            footer1, "Next: Metadata Column ->", lambda: self.show_step(1), primary=True
        ).pack(side="right")

    # ------------------------------------------------------------------
    # STEP 2: INTERACTIVE METADATA VIEWER & COLUMN PICKER (Responsive 2-Row Toolbar)
    # ------------------------------------------------------------------
    def _build_step2_metadata(self):
        page = tk.Frame(
            self.page_container,
            bg=PALETTE["card_inner"],
            highlightbackground=PALETTE["border"],
            highlightthickness=1,
            padx=28,
            pady=20,
        )
        self.step_frames.append(page)

        tk.Label(
            page,
            text="Step 2: Choose Metadata File & Click Morphospecies Column",
            font=FONT_TITLE,
            fg=PALETTE["text_dark"],
            bg=PALETTE["card_inner"],
            anchor="w",
        ).pack(fill="x", pady=(0, 10))

        # Row 1 of Toolbar: File picker buttons on left, Header click mode on right
        top_controls = tk.Frame(page, bg=PALETTE["card_inner"])
        top_controls.pack(fill="x", pady=(0, 8))

        self._make_button(
            top_controls, "Choose Metadata File (.csv / .tsv / .xlsx)", self.browse_metadata, primary=True
        ).pack(side="left", padx=(0, 8))

        self._make_button(
            top_controls, "Clear Metadata", self.clear_metadata, primary=False
        ).pack(side="left")

        mode_box = tk.Frame(top_controls, bg=PALETTE["card_inner"])
        mode_box.pack(side="right")
        tk.Label(
            mode_box, text="Header Click Sets:", font=FONT_HEADING,
            fg=PALETTE["text_dark"], bg=PALETTE["card_inner"]
        ).pack(side="left", padx=(0, 6))
        tk.Radiobutton(
            mode_box, text="Morphospecies", variable=self.click_target_var, value="morpho",
            bg=PALETTE["card_inner"], fg=PALETTE["text_dark"], selectcolor=PALETTE["card_inner"],
            activebackground=PALETTE["card_inner"], font=FONT_BODY
        ).pack(side="left", padx=(0, 6))
        tk.Radiobutton(
            mode_box, text="Sample ID", variable=self.click_target_var, value="sample",
            bg=PALETTE["card_inner"], fg=PALETTE["text_dark"], selectcolor=PALETTE["card_inner"],
            activebackground=PALETTE["card_inner"], font=FONT_BODY
        ).pack(side="left")

        # Row 2 of Toolbar: Elastic 4-Column Grid for Morphospecies Column & Sample ID Column
        # Ensures both dropdowns are ALWAYS visible and resize proportionally in smaller windows.
        col_selectors = tk.Frame(page, bg=PALETTE["card_inner"])
        col_selectors.pack(fill="x", pady=(0, 10))
        col_selectors.columnconfigure(1, weight=1)
        col_selectors.columnconfigure(3, weight=1)

        tk.Label(
            col_selectors, text="Morphospecies Column:", font=FONT_HEADING,
            fg=PALETTE["text_dark"], bg=PALETTE["card_inner"]
        ).grid(row=0, column=0, sticky="w", padx=(0, 8), pady=2)

        self.morpho_combo = ttk.Combobox(
            col_selectors, textvariable=self.morpho_col_var, state="readonly", font=FONT_BODY
        )
        self.morpho_combo.grid(row=0, column=1, sticky="ew", padx=(0, 20), pady=2)
        self.morpho_combo.bind("<<ComboboxSelected>>", lambda _e: self._refresh_column_badges())

        tk.Label(
            col_selectors, text="Sample ID Column:", font=FONT_HEADING,
            fg=PALETTE["text_dark"], bg=PALETTE["card_inner"]
        ).grid(row=0, column=2, sticky="w", padx=(0, 8), pady=2)

        self.sample_combo = ttk.Combobox(
            col_selectors, textvariable=self.sample_col_var, state="readonly", font=FONT_BODY
        )
        self.sample_combo.grid(row=0, column=3, sticky="ew", pady=2)
        self.sample_combo.bind("<<ComboboxSelected>>", lambda _e: self._refresh_column_badges())

        # Live Preview Banner
        sub_bar = tk.Frame(
            page,
            bg=PALETTE["primary_tint"],
            highlightbackground=PALETTE["primary"],
            highlightthickness=1,
            padx=12,
            pady=6,
        )
        sub_bar.pack(fill="x", pady=(0, 10))

        tk.Label(
            sub_bar,
            textvariable=self.morpho_preview_var,
            font=FONT_BODY,
            fg=PALETTE["text_dark"],
            bg=PALETTE["primary_tint"],
            anchor="w",
        ).pack(fill="x")

        # Footer Navigation
        footer2 = tk.Frame(page, bg=PALETTE["card_inner"])
        footer2.pack(side="bottom", fill="x", pady=(12, 0))

        self._make_button(
            footer2, "<- Back: Sequences", lambda: self.show_step(0), primary=False
        ).pack(side="left")

        self._make_button(
            footer2, "Next: Run ->", lambda: self.show_step(2), primary=True
        ).pack(side="right")

        # Interactive Spreadsheet Preview Table
        table_wrap = tk.Frame(
            page, bg=PALETTE["card_inner"], highlightbackground=PALETTE["border"], highlightthickness=1
        )
        table_wrap.pack(fill="both", expand=True)

        self.meta_tree = ttk.Treeview(table_wrap, show="headings")
        vsb = ttk.Scrollbar(table_wrap, orient="vertical", command=self.meta_tree.yview)
        hsb = ttk.Scrollbar(table_wrap, orient="horizontal", command=self.meta_tree.xview)
        self.meta_tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.meta_tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        table_wrap.rowconfigure(0, weight=1)
        table_wrap.columnconfigure(0, weight=1)

    # ------------------------------------------------------------------
    # STEP 3: RUN (Dedicated Execution Page with 2x2 Responsive Stream Cards)
    # ------------------------------------------------------------------
    def _build_step3_run(self):
        page = tk.Frame(
            self.page_container,
            bg=PALETTE["card_inner"],
            highlightbackground=PALETTE["border"],
            highlightthickness=1,
            padx=28,
            pady=20,
        )
        self.step_frames.append(page)

        tk.Label(
            page,
            text="Step 3: Run Parallel Four-Stream Identification",
            font=FONT_TITLE,
            fg=PALETTE["text_dark"],
            bg=PALETTE["card_inner"],
            anchor="w",
        ).pack(fill="x", pady=(0, 6))

        tk.Label(
            page,
            textvariable=self.run_overview_var,
            font=FONT_BODY,
            fg=PALETTE["text_dark"],
            bg=PALETTE["card_inner"],
            anchor="w",
        ).pack(fill="x", pady=(0, 12))

        # 4 Evidence Stream Cards in a Responsive 2x2 Grid (never overflows in smaller windows)
        srv_grid = tk.Frame(page, bg=PALETTE["card_inner"])
        srv_grid.pack(fill="x", pady=(0, 14))
        srv_grid.columnconfigure(0, weight=1)
        srv_grid.columnconfigure(1, weight=1)

        self.service_cards: Dict[str, tk.Frame] = {}
        self.service_titles: Dict[str, tk.Label] = {}
        self.service_labels: Dict[str, tk.Label] = {}
        self.service_spinners: Dict[str, tk.Canvas] = {}

        streams = [
            ("morpho", "1. Morphological Prior", 0, 0),
            ("bold", "2. BOLD Systems v5", 0, 1),
            ("ncbi", "3. NCBI GenBank BLAST", 1, 0),
            ("gbif", "4. GBIF Backbone", 1, 1),
        ]
        for key, title, r_idx, c_idx in streams:
            card = tk.Frame(
                srv_grid,
                bg=PALETTE["card_inner"],
                highlightbackground=PALETTE["border"],
                highlightthickness=1,
                padx=14,
                pady=10,
            )
            card.grid(
                row=r_idx,
                column=c_idx,
                sticky="ew",
                padx=(0 if c_idx == 0 else 10, 0),
                pady=(0 if r_idx == 0 else 8, 0),
            )
            t_lbl = tk.Label(
                card, text=title, font=FONT_HEADING, fg=PALETTE["text_dark"], bg=PALETTE["card_inner"]
            )
            t_lbl.pack(side="left")

            s_lbl = tk.Label(
                card, text="Idle", font=FONT_HEADING, fg=PALETTE["text_dark"], bg=PALETTE["card_inner"]
            )
            s_lbl.pack(side="right")

            spin_canvas = tk.Canvas(
                card, width=22, height=22, bg=PALETTE["card_inner"], highlightthickness=0
            )
            spin_canvas.pack(side="right", padx=(6, 6))

            self.service_cards[key] = card
            self.service_titles[key] = t_lbl
            self.service_labels[key] = s_lbl
            self.service_spinners[key] = spin_canvas

        # Run Button + Progress Bar
        ctrl_row = tk.Frame(page, bg=PALETTE["card_inner"])
        ctrl_row.pack(fill="x", pady=(0, 12))

        self.run_btn = self._make_button(
            ctrl_row, "Run Identification", self.start_run, primary=True
        )
        self.run_btn.pack(side="left", padx=(0, 16))

        prog_wrap = tk.Frame(ctrl_row, bg=PALETTE["card_inner"])
        prog_wrap.pack(side="left", fill="x", expand=True)

        self.stage_var = tk.StringVar(value="Ready — Click Run Identification to start.")
        tk.Label(
            prog_wrap, textvariable=self.stage_var, font=FONT_HEADING,
            fg=PALETTE["text_dark"], bg=PALETTE["card_inner"], anchor="w"
        ).pack(fill="x")

        self.progress_var = tk.DoubleVar(value=0.0)
        self.progress_bar = ttk.Progressbar(
            prog_wrap, variable=self.progress_var, maximum=100.0, style="Green.Horizontal.TProgressbar"
        )
        self.progress_bar.pack(fill="x", pady=(6, 0))

        # Footer Navigation
        footer3 = tk.Frame(page, bg=PALETTE["card_inner"])
        footer3.pack(side="bottom", fill="x", pady=(12, 0))

        self._make_button(
            footer3, "<- Back: Metadata Column", lambda: self.show_step(1), primary=False
        ).pack(side="left")

        self.to_results_btn = self._make_button(
            footer3, "Next: Results ->", lambda: self.show_step(3), primary=True
        )
        self.to_results_btn.pack(side="right")

        # Live Log Console
        self.log_text = tk.Text(
            page,
            font=FONT_BODY,
            bg=PALETTE["card_inner"],
            fg=PALETTE["text_dark"],
            relief="solid",
            bd=1,
            padx=10,
            pady=8,
            state="disabled",
        )
        self.log_text.pack(fill="both", expand=True)

    # ------------------------------------------------------------------
    # STEP 4: RESULTS (Table Viewer with Single-Cell Highlighting)
    # ------------------------------------------------------------------
    def _build_step4_results(self):
        page = tk.Frame(
            self.page_container,
            bg=PALETTE["card_inner"],
            highlightbackground=PALETTE["border"],
            highlightthickness=1,
            padx=28,
            pady=20,
        )
        self.step_frames.append(page)

        tk.Label(
            page,
            text="Step 4: Taxonomic Concordance & QC Results",
            font=FONT_TITLE,
            fg=PALETTE["text_dark"],
            bg=PALETTE["card_inner"],
            anchor="w",
        ).pack(fill="x", pady=(0, 10))

        # Top Action & Summary Bar
        res_bar = tk.Frame(page, bg=PALETTE["card_inner"])
        res_bar.pack(fill="x", pady=(0, 10))

        self.open_excel_btn = self._make_button(
            res_bar, "Open Excel Report", self.open_last_excel, primary=True
        )
        self.open_excel_btn.pack(side="left", padx=(0, 10))

        self.open_folder_btn = self._make_button(
            res_bar, "Open Results Folder", self.open_output_folder, primary=False
        )
        self.open_folder_btn.pack(side="left")

        # Concordance Summary Banner
        self.summary_var = tk.StringVar(
            value="Concordance Summary:   Total: 0   |   CONCORDANT: 0   |   NEW_ASSIGNMENT: 0   |   MISMATCH_ALERT: 0   |   NO_MATCH: 0"
        )
        tk.Label(
            page,
            textvariable=self.summary_var,
            font=FONT_HEADING,
            fg=PALETTE["text_dark"],
            bg=PALETTE["primary_tint"],
            highlightbackground=PALETTE["primary"],
            highlightthickness=1,
            padx=12,
            pady=8,
            anchor="w",
        ).pack(fill="x", pady=(0, 10))

        # Footer Navigation
        footer4 = tk.Frame(page, bg=PALETTE["card_inner"])
        footer4.pack(side="bottom", fill="x", pady=(12, 0))

        self._make_button(
            footer4, "<- Back: Run", lambda: self.show_step(2), primary=False
        ).pack(side="left")

        # Scrollable Canvas Grid for Single-Cell Highlighted Results Table
        grid_wrap = tk.Frame(
            page, bg=PALETTE["card_inner"], highlightbackground=PALETTE["border"], highlightthickness=1
        )
        grid_wrap.pack(fill="both", expand=True)

        self.results_canvas = tk.Canvas(
            grid_wrap, bg=PALETTE["card_inner"], highlightthickness=0
        )
        res_vsb = ttk.Scrollbar(grid_wrap, orient="vertical", command=self.results_canvas.yview)
        res_hsb = ttk.Scrollbar(grid_wrap, orient="horizontal", command=self.results_canvas.xview)
        self.results_canvas.configure(yscrollcommand=res_vsb.set, xscrollcommand=res_hsb.set)

        self.results_canvas.grid(row=0, column=0, sticky="nsew")
        res_vsb.grid(row=0, column=1, sticky="ns")
        res_hsb.grid(row=1, column=0, sticky="ew")
        grid_wrap.rowconfigure(0, weight=1)
        grid_wrap.columnconfigure(0, weight=1)

        # Mousewheel support on the results table canvas
        self.results_canvas.bind(
            "<MouseWheel>",
            lambda e: self.results_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"),
        )

        self.populate_results_table([])

    def populate_results_table(self, rows: List[Dict[str, Any]]):
        """
        Renders the identification results table onto `self.results_canvas` with
        individual cell highlighting on `Concordance_Status` and `QC_Flag`.
        """
        self.last_results_rows = list(rows)
        c = self.results_canvas
        c.delete("all")

        row_h = max(34, int(34 * self.dpi_scale))
        base_widths = [
            190,  # Sample_ID
            120,  # Field_Morpho
            130,  # Field_Genus
            165,  # BOLD_Taxon
            85,   # BOLD_%
            165,  # NCBI_Taxon
            85,   # NCBI_%
            165,  # GBIF_Name
            175,  # Consensus_Species
            165,  # Concordance_Status
            180,  # QC_Flag
        ]
        col_widths = [max(w, int(w * self.dpi_scale)) for w in base_widths]

        # 1. Draw Header Row
        x_offset = 0
        for col_idx, col_name in enumerate(RESULTS_COLUMNS):
            w = col_widths[col_idx]
            c.create_rectangle(
                x_offset, 0, x_offset + w, row_h,
                fill=PALETTE["primary_tint"], outline=PALETTE["border"], width=1
            )
            c.create_text(
                x_offset + 10,
                row_h // 2,
                text=col_name,
                anchor="w",
                fill=PALETTE["text_dark"],
                font=FONT_HEADING,
            )
            x_offset += w

        total_w = x_offset

        if not rows:
            c.create_text(
                20,
                row_h + 28,
                text="No results yet — Run Identification in Step 3 to view the concordance table here.",
                anchor="w",
                fill=PALETTE["text_dark"],
                font=FONT_BODY,
            )
            c.configure(scrollregion=(0, 0, total_w, row_h * 3))
            return

        # 2. Draw Data Rows (with single-cell highlighting on Concordance_Status & QC_Flag)
        for r_idx, r in enumerate(rows):
            y0 = (r_idx + 1) * row_h
            y1 = y0 + row_h

            meta = r.get("meta", {})
            bold = r.get("bold", {})
            ncbi = r.get("ncbi", {})
            gbif = r.get("gbif", {})

            bold_pct = bold.get("top_pct_identity", 0.0)
            ncbi_pct = ncbi.get("top_pct_identity", 0.0)

            cell_values = [
                str(meta.get("sample_id", "")),
                str(meta.get("field_morpho_code", "")),
                str(meta.get("field_inferred_genus", "")),
                str(bold.get("top_species") or bold.get("top_genus") or ""),
                f"{bold_pct:.1f}" if bold_pct else "",
                str(ncbi.get("top_species") or ncbi.get("top_genus") or ""),
                f"{ncbi_pct:.1f}" if ncbi_pct else "",
                str(gbif.get("canonicalName", "")),
                str(r.get("consensus_species") or r.get("consensus_genus") or ""),
                str(r.get("concordance_status", "")),
                str(r.get("qc_flag", "")),
            ]

            x_pos = 0
            for col_idx, val_str in enumerate(cell_values):
                w = col_widths[col_idx]
                col_name = RESULTS_COLUMNS[col_idx]
                bg_hex, fg_hex, is_bold = get_cell_highlight(col_name, val_str)

                c.create_rectangle(
                    x_pos, y0, x_pos + w, y1,
                    fill=bg_hex, outline=PALETTE["border"], width=1
                )
                c.create_text(
                    x_pos + 10,
                    y0 + (row_h // 2),
                    text=val_str,
                    anchor="w",
                    fill=fg_hex,
                    font=FONT_HEADING if is_bold else FONT_BODY,
                )
                x_pos += w

        total_h = (len(rows) + 1) * row_h
        c.configure(scrollregion=(0, 0, total_w, total_h))

    # ------------------------------------------------------------------
    # Circular Spinner Animation & Service Card Updates
    # ------------------------------------------------------------------
    def _animate_spinners(self):
        """Rotates circular arc spinners on any stream card currently in 'Active' state."""
        self.spinner_angle = (self.spinner_angle - 24) % 360
        for key, canvas in self.service_spinners.items():
            state = self.service_states.get(key, "Idle")
            canvas.delete("all")
            if state == "Active":
                canvas.create_oval(3, 3, 19, 19, outline="#3B8235", width=2)
                canvas.create_arc(
                    3, 3, 19, 19,
                    start=self.spinner_angle,
                    extent=250,
                    style="arc",
                    outline="#FFFFFF",
                    width=2.5,
                )
            elif state == "Done":
                canvas.create_oval(3, 3, 19, 19, outline=PALETTE["primary"], width=2)
                canvas.create_line(7, 11, 10, 14, 15, 8, fill=PALETTE["primary"], width=2)

        self.root.after(60, self._animate_spinners)

    def _set_service_states(self, **kwargs: str):
        """Updates the 4 stream cards and synchronizes their circular spinner canvases."""
        for key, state in kwargs.items():
            if key not in self.service_labels:
                continue
            self.service_states[key] = state
            card = self.service_cards[key]
            t_lbl = self.service_titles[key]
            s_lbl = self.service_labels[key]
            spin = self.service_spinners[key]
            s_lbl.configure(text=state)

            if state == "Active":
                bg = PALETTE["primary"]
                fg = "#FFFFFF"
                border = PALETTE["primary"]
            elif state == "Done":
                bg = PALETTE["primary_tint"]
                fg = PALETTE["text_dark"]
                border = PALETTE["primary"]
            else:
                bg = PALETTE["card_inner"]
                fg = PALETTE["text_dark"]
                border = PALETTE["border"]

            card.configure(bg=bg, highlightbackground=border)
            t_lbl.configure(bg=bg, fg=fg)
            s_lbl.configure(bg=bg, fg=fg)
            spin.configure(bg=bg)

    # ------------------------------------------------------------------
    # Step Navigation, Buttons & Hidden Ctrl+Shift+D Diagnostics
    # ------------------------------------------------------------------
    def show_step(self, step_idx: int):
        """Switches the active wizard page and updates step button highlighting."""
        self.current_step = max(0, min(step_idx, len(self.step_frames) - 1))
        for idx, frame in enumerate(self.step_frames):
            if idx == self.current_step:
                frame.pack(fill="both", expand=True)
            else:
                frame.pack_forget()

        for idx, btn in enumerate(self.step_buttons):
            if idx == self.current_step:
                btn.configure(bg=PALETTE["primary"], fg="#FFFFFF", disabledforeground="#FFFFFF")
            else:
                btn.configure(
                    bg=PALETTE["card_inner"],
                    fg=PALETTE["text_dark"],
                    disabledforeground=PALETTE["text_dark"],
                )

        if self.current_step == 2:
            fasta_name = Path(self.fasta_var.get()).name if self.fasta_var.get().strip() else "None selected"
            meta_name = (
                f"{Path(self.metadata_var.get()).name} (Morphospecies: '{self.morpho_col_var.get()}')"
                if self.metadata_var.get().strip()
                else "FASTA deflines only"
            )
            self.run_overview_var.set(
                f"FASTA: {fasta_name}   |   Metadata: {meta_name}   |   Target Taxon: {self.taxon_var.get()}"
            )

    def _make_button(
        self,
        parent: tk.Widget,
        text: str,
        command,
        primary: bool = True,
    ) -> tk.Button:
        bg = PALETTE["primary"] if primary else PALETTE["card_inner"]
        fg = "#FFFFFF" if primary else PALETTE["text_dark"]
        active_bg = PALETTE["primary_hover"] if primary else PALETTE["primary_tint"]
        active_fg = "#FFFFFF" if primary else PALETTE["text_dark"]
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg=bg,
            fg=fg,
            disabledforeground=fg,
            activebackground=active_bg,
            activeforeground=active_fg,
            relief="solid",
            bd=1,
            padx=14,
            pady=6,
            font=FONT_HEADING,
            cursor="hand2",
        )

    def _attach_logging(self):
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)
        handler = QueueLogHandler(self.log_queue)
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S"))
        root_logger.addHandler(handler)

    def toggle_terminal_window(self, _event=None):
        """Toggles the hidden Diagnostic Terminal & Bug Report window via Ctrl+Shift+D."""
        if self.terminal_win and self.terminal_win.winfo_exists():
            self.terminal_win.destroy()
            self.terminal_win = None
            self.terminal_text = None
            return
        self.open_terminal_window()

    def open_terminal_window(self):
        """Opens the Diagnostic Terminal & Bug Report window."""
        if self.terminal_win and self.terminal_win.winfo_exists():
            self.terminal_win.lift()
            return

        win = tk.Toplevel(self.root)
        win.title("BarcoID — Diagnostics & Bug Report (Ctrl+Shift+D)")
        win.geometry("880x520")
        win.configure(bg=PALETTE["card_inner"])
        self.terminal_win = win

        bar = tk.Frame(win, bg=PALETTE["card_inner"], padx=14, pady=10)
        bar.pack(fill="x")

        tk.Label(
            bar, text="Live Execution & Network Diagnostics", font=FONT_HEADING,
            fg=PALETTE["text_dark"], bg=PALETTE["card_inner"]
        ).pack(side="left")

        self._make_button(
            bar, "Save Bug Report", self.export_bug_report, primary=True
        ).pack(side="right")

        self._make_button(
            bar, "Test APIs (BOLD / NCBI / GBIF)", self.run_api_test_async, primary=False
        ).pack(side="right", padx=(0, 10))

        txt = tk.Text(
            win,
            font=FONT_BODY,
            bg="#111111",
            fg="#FFFFFF",
            insertbackground="#FFFFFF",
            relief="solid",
            bd=1,
            padx=12,
            pady=10,
        )
        txt.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        if self.log_history:
            txt.insert("end", "\n".join(self.log_history) + "\n")
            txt.see("end")
        self.terminal_text = txt

    def run_api_test_async(self):
        """Runs a live network ping against BOLD, NCBI, and GBIF in a background thread."""
        logging.info("Testing live connectivity to BOLD Systems v5, NCBI QBLAST, and GBIF Backbone...")

        def _worker():
            lines = check_api_endpoints()
            for line in lines:
                logging.info(line)

        threading.Thread(target=_worker, daemon=True).start()

    def build_diagnostic_report_text(self, include_api_ping: bool = True) -> str:
        """Compiles a complete diagnostic and bug report string."""
        fasta_str = self.fasta_var.get().strip()
        seq_count = 0
        if fasta_str and Path(fasta_str).exists():
            try:
                seq_count = len(FastaParser.read_sequences(Path(fasta_str)))
            except Exception:
                seq_count = -1

        lines = [
            "======================================================================",
            f"BarcoID Diagnostic & Bug Report — v{__version__}",
            f"Generated: {datetime.now().isoformat(timespec='seconds')}",
            "======================================================================",
            f"OS / Platform:      {platform.platform()}",
            f"Python Runtime:     {sys.version.split()[0]} (Frozen EXE: {getattr(sys, 'frozen', False)})",
            f"Monitor DPI Scale:  {self.dpi_scale:.2f}x",
            f"Input FASTA:        {fasta_str or '<none>'} (Sequences detected: {seq_count})",
            f"Metadata File:      {self.metadata_var.get().strip() or '<none>'}",
            f"Morphospecies Col:  {self.morpho_col_var.get()}",
            f"Sample ID Col:      {self.sample_col_var.get()}",
            f"Output Directory:   {self.output_dir_var.get()}",
            f"Target Taxon:       {self.taxon_var.get()}",
            f"Pipeline Running:   {self.is_running}",
            "",
        ]
        if include_api_ping:
            lines.append("--- Live API Connectivity Check ---")
            lines.extend(check_api_endpoints())
            lines.append("")

        if self.last_error_trace:
            lines.append("--- Last Exception Traceback ---")
            lines.append(self.last_error_trace)
            lines.append("")

        lines.append("--- Execution Log History ---")
        lines.extend(self.log_history if self.log_history else ["<no log entries yet>"])
        return "\n".join(lines) + "\n"

    def export_bug_report(self):
        """Generates a diagnostic report file in the output directory and opens it."""
        out_dir = Path(self.output_dir_var.get().strip() or "results")
        out_dir.mkdir(parents=True, exist_ok=True)
        report_path = out_dir / "barcoid_bug_report.txt"

        logging.info("Generating diagnostic bug report...")

        def _worker():
            text = self.build_diagnostic_report_text(include_api_ping=True)
            report_path.write_text(text, encoding="utf-8")
            logging.info(f"Bug report saved to: {report_path}")
            self.ui_queue.put(("bug_report_ready", report_path))

        threading.Thread(target=_worker, daemon=True).start()

    # ------------------------------------------------------------------
    # File Browsers & Interactive Metadata Table Loading
    # ------------------------------------------------------------------
    def browse_fasta(self):
        path = filedialog.askopenfilename(
            title="Select Input DNA Barcodes FASTA File",
            filetypes=[
                ("FASTA Files", "*.fasta *.fas *.fa *.fna *.txt"),
                ("All Files", "*.*"),
            ],
        )
        if path:
            p = Path(path)
            self.fasta_var.set(str(p))
            self.output_dir_var.set(str(p.parent / "results"))

    def browse_output_dir(self):
        folder = filedialog.askdirectory(title="Select Output Folder for Reports")
        if folder:
            self.output_dir_var.set(str(Path(folder)))

    def browse_metadata(self):
        path = filedialog.askopenfilename(
            title="Select Specimen Metadata Spreadsheet",
            filetypes=[
                ("Spreadsheet Files", "*.csv *.tsv *.tab *.xlsx *.xlsm"),
                ("CSV / TSV", "*.csv *.tsv *.tab"),
                ("Excel Workbook", "*.xlsx *.xlsm"),
                ("All Files", "*.*"),
            ],
        )
        if path:
            self.load_metadata_file(Path(path))

    def clear_metadata(self):
        self.metadata_var.set("")
        self.meta_columns = []
        self.meta_rows = []
        self.meta_tree.delete(*self.meta_tree.get_children())
        self.meta_tree["columns"] = ()
        self.morpho_combo["values"] = []
        self.sample_combo["values"] = []
        self.morpho_preview_var.set(
            "Optional: Load a metadata file (.csv, .tsv, .xlsx) to preview rows and click the Morphospecies column."
        )

    def load_metadata_file(self, path: Path):
        """Loads a metadata spreadsheet into the in-app preview table and auto-detects columns."""
        try:
            headers, rows = MetadataParser.read_preview(path, max_rows=35)
        except Exception as exc:
            messagebox.showerror("Metadata Load Error", f"Could not read metadata file:\n{exc}")
            return

        if not headers:
            messagebox.showwarning("Empty Metadata", "No column headers found in the selected file.")
            return

        self.metadata_var.set(str(path))
        self.meta_columns = headers
        self.meta_rows = rows

        guessed_sample, guessed_morpho = MetadataParser.guess_columns(headers)
        self.sample_col_var.set(guessed_sample)
        self.morpho_col_var.set(guessed_morpho)

        self.sample_combo["values"] = headers
        self.morpho_combo["values"] = headers

        self.meta_tree.delete(*self.meta_tree.get_children())
        self.meta_tree["columns"] = headers

        col_w = max(160, int(160 * self.dpi_scale))
        for col in headers:
            self.meta_tree.column(col, width=col_w, minwidth=110, anchor="w")
            self.meta_tree.heading(
                col,
                text=col,
                command=lambda c=col: self.on_column_header_clicked(c),
            )

        for r in rows:
            self.meta_tree.insert("", "end", values=r)

        self._refresh_column_badges()

    def on_column_header_clicked(self, col_name: str):
        """Handles clicking a column header in the metadata preview table."""
        if self.click_target_var.get() == "sample":
            self.sample_col_var.set(col_name)
        else:
            self.morpho_col_var.set(col_name)
        self._refresh_column_badges()

    def _refresh_column_badges(self):
        """Updates column header badges and shows live sample -> morphospecies -> genus preview."""
        if not self.meta_columns:
            return

        s_col = self.sample_col_var.get()
        m_col = self.morpho_col_var.get()

        for col in self.meta_columns:
            tags = []
            if col == m_col:
                tags.append("MORPHOSPECIES")
            if col == s_col:
                tags.append("SAMPLE ID")
            label = f"{col}  [{' & '.join(tags)}]" if tags else col
            self.meta_tree.heading(
                col,
                text=label,
                command=lambda c=col: self.on_column_header_clicked(c),
            )

        m_idx = self.meta_columns.index(m_col) if m_col in self.meta_columns else -1
        s_idx = self.meta_columns.index(s_col) if s_col in self.meta_columns else -1

        example_text = ""
        helper = MetadataParser.__new__(MetadataParser)
        helper.prefix_map = dict(DEFAULT_GENUS_PREFIXES)

        for row in self.meta_rows:
            m_val = row[m_idx].strip() if 0 <= m_idx < len(row) else ""
            s_val = row[s_idx].strip() if 0 <= s_idx < len(row) else ""
            if m_val:
                inferred = helper.infer_genus_from_morpho(m_val)
                genus_note = f"Inferred Genus: {inferred}" if inferred else "Unassigned / Indeterminate"
                example_text = f"Preview ({s_val or 'row'}) -> '{m_val}' ({genus_note})"
                break

        if not example_text:
            example_text = "Click any column header below to select the Morphospecies column."

        self.morpho_preview_var.set(
            f"Active Morphospecies Column: '{m_col}'   |   Sample ID: '{s_col}'   |   {example_text}"
        )

    # ------------------------------------------------------------------
    # Pipeline Execution in Background Worker Thread
    # ------------------------------------------------------------------
    def start_run(self):
        if self.is_running:
            return

        fasta_str = self.fasta_var.get().strip()
        if not fasta_str:
            messagebox.showwarning("Missing Input", "Please select an input FASTA file in Step 1 first.")
            self.show_step(0)
            return

        fasta_path = Path(fasta_str)
        if not fasta_path.exists():
            messagebox.showerror("File Not Found", f"FASTA file does not exist:\n{fasta_path}")
            self.show_step(0)
            return

        try:
            config = build_config_from_inputs(
                fasta_path=fasta_path,
                output_dir=Path(self.output_dir_var.get().strip()) if self.output_dir_var.get().strip() else None,
                taxon=self.taxon_var.get(),
                max_sequences_str=self.max_seq_var.get(),
                ncbi_email=self.ncbi_email_var.get(),
                ncbi_api_key=self.ncbi_key_var.get(),
                dry_run=self.dry_run_var.get(),
                force_refresh=self.force_refresh_var.get(),
            )
        except ValueError as exc:
            messagebox.showerror("Invalid Parameter", f"Please check numeric inputs:\n{exc}")
            return

        meta_str = self.metadata_var.get().strip()
        meta_path = Path(meta_str) if meta_str else None
        sample_col = self.sample_col_var.get().strip() or "sample_id"
        morpho_col = self.morpho_col_var.get().strip() or "field_morphospecies"

        self.show_step(2)
        self.is_running = True
        self.run_btn.configure(
            state="disabled",
            text="Running...",
            bg=PALETTE["primary"],
            fg="#FFFFFF",
            disabledforeground="#FFFFFF",
        )
        self.progress_var.set(5.0)
        self._set_service_states(morpho="Active", bold="Idle", ncbi="Idle", gbif="Idle")

        worker = threading.Thread(
            target=self._run_pipeline_worker,
            args=(config, fasta_path, meta_path, sample_col, morpho_col),
            daemon=True,
        )
        worker.start()

    def _run_pipeline_worker(
        self,
        config: BarcoIDConfig,
        fasta_path: Path,
        meta_path: Optional[Path],
        sample_col: str,
        morpho_col: str,
    ):
        def _progress(stage: str, pct: float):
            self.ui_queue.put(("progress", (stage, pct)))

        def _service(name: str, status: str):
            self.ui_queue.put(("service", (name, status)))

        try:
            pipeline = BarcoIDPipeline(config)
            rows = pipeline.run(
                fasta_path=fasta_path,
                metadata_path=meta_path,
                sample_col=sample_col,
                morpho_col=morpho_col,
                progress_callback=_progress,
                service_callback=_service,
            )
            xlsx_path = Path(config.output_dir) / f"{fasta_path.stem}_multi_source_identification.xlsx"
            self.ui_queue.put(("done", (rows, xlsx_path, config.dry_run)))
        except Exception as exc:
            self.last_error_trace = traceback.format_exc()
            logging.error(f"Pipeline execution error: {exc}")
            self.ui_queue.put(("error", str(exc)))

    def _poll_queues(self):
        while True:
            try:
                msg = self.log_queue.get_nowait()
            except queue.Empty:
                break
            self.log_history.append(msg)
            self.log_text.configure(state="normal")
            self.log_text.insert("end", msg + "\n")
            self.log_text.see("end")
            self.log_text.configure(state="disabled")

            if self.terminal_text and self.terminal_text.winfo_exists():
                self.terminal_text.insert("end", msg + "\n")
                self.terminal_text.see("end")

        while True:
            try:
                event, payload = self.ui_queue.get_nowait()
            except queue.Empty:
                break

            if event == "service":
                srv_name, srv_status = payload
                self._set_service_states(**{srv_name: srv_status})

            elif event == "progress":
                stage, pct = payload
                self.stage_var.set(stage)
                self.progress_var.set(pct)

            elif event == "done":
                rows, xlsx_path, is_dry_run = payload
                self.is_running = False
                self.run_btn.configure(
                    state="normal",
                    text="Run Identification",
                    bg=PALETTE["primary"],
                    fg="#FFFFFF",
                )
                self._set_service_states(morpho="Done", bold="Done", ncbi="Done", gbif="Done")

                counts = {
                    "CONCORDANT": 0,
                    "NEW_ASSIGNMENT": 0,
                    "MISMATCH_ALERT": 0,
                    "NO_MATCH": 0,
                }
                for r in rows:
                    st = r.get("concordance_status", "")
                    if st in counts:
                        counts[st] += 1

                self.summary_var.set(
                    f"Concordance Summary:   Total: {len(rows)}   |   "
                    f"CONCORDANT: {counts['CONCORDANT']}   |   "
                    f"NEW_ASSIGNMENT: {counts['NEW_ASSIGNMENT']}   |   "
                    f"MISMATCH_ALERT: {counts['MISMATCH_ALERT']}   |   "
                    f"NO_MATCH: {counts['NO_MATCH']}"
                )

                self.populate_results_table(rows)

                if not is_dry_run and xlsx_path.exists():
                    self.last_excel_path = xlsx_path
                    self.open_excel_btn.configure(
                        bg=PALETTE["primary"],
                        fg="#FFFFFF",
                        text="Open Excel Report (Ready)",
                    )
                if rows:
                    self.show_step(3)

            elif event == "bug_report_ready":
                report_path = payload
                open_path_in_os(report_path)

            elif event == "error":
                self.is_running = False
                self.run_btn.configure(
                    state="normal",
                    text="Run Identification",
                    bg=PALETTE["primary"],
                    fg="#FFFFFF",
                )
                self.stage_var.set(f"Error: {payload}")
                messagebox.showerror("Execution Error", f"An error occurred during identification:\n{payload}")

        self.root.after(100, self._poll_queues)

    def open_last_excel(self):
        if self.last_excel_path and self.last_excel_path.exists():
            open_path_in_os(self.last_excel_path)
        else:
            messagebox.showinfo(
                "No Excel Report Yet",
                "Run Identification in Step 3 first (with Dry Run unchecked) to generate the Excel report.",
            )

    def open_output_folder(self):
        out_dir = Path(self.output_dir_var.get().strip() or "results")
        out_dir.mkdir(parents=True, exist_ok=True)
        open_path_in_os(out_dir)


def launch_gui():
    """Enables High-DPI rendering and launches the BarcoID desktop wizard."""
    enable_high_dpi()
    root = tk.Tk()
    BarcoIDApp(root)
    root.mainloop()


if __name__ == "__main__":
    launch_gui()
