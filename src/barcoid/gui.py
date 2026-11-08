"""
Standalone Desktop GUI for BarcoID.
Light theme inspired by the BIEN visual architecture with #4C9E45 primary botanical green
and an in-app interactive Metadata Table Preview & Column Picker.
"""

import logging
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Dict, List, Optional, Tuple

from barcoid import __version__
from barcoid.config import BarcoIDConfig
from barcoid.parsers.metadata import MetadataParser
from barcoid.pipeline import BarcoIDPipeline

# BIEN-inspired Light Theme Palette anchored on #4C9E45
PALETTE = {
    "bg_canvas": "#FAF8F5",       # Warm ivory background
    "card_outer": "#EFECE6",      # Soft sand section container
    "card_inner": "#FFFFFF",      # Crisp white inner surface
    "border": "#DDD7CE",          # Subtle warm border
    "primary": "#4C9E45",         # Primary botanical green
    "primary_hover": "#3B8235",   # Deeper green for hover/active
    "primary_tint": "#EAF5E9",    # Soft sage highlight tint
    "tab_inactive": "#E2DDD5",    # Inactive folder tab
    "text_dark": "#2B332C",       # Primary charcoal text
    "text_muted": "#667067",      # Secondary muted label text
    "srv_morpho": "#4C9E45",      # Service 1: Morphological Prior (Green)
    "srv_bold": "#D97F6C",        # Service 2: BOLD Systems v5 (Terracotta)
    "srv_ncbi": "#4E598C",        # Service 3: NCBI GenBank BLAST (Slate Indigo)
    "srv_gbif": "#52858C",        # Service 4: GBIF Backbone (Teal)
    "alert_warn": "#C85A44",      # Mismatch / alert accent
}


class QueueLogHandler(logging.Handler):
    """Routes Python logging records into a thread-safe queue for the GUI log console."""

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
    """Main Tkinter desktop window for BarcoID."""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(f"BarcoID v{__version__} — Multi-Source DNA Barcode Identifier")
        self.root.geometry("1060x820")
        self.root.minsize(920, 720)
        self.root.configure(bg=PALETTE["bg_canvas"])

        # State variables
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
        self.click_target_var = tk.StringVar(value="morpho")  # "morpho" or "sample"
        self.morpho_preview_var = tk.StringVar(
            value="No metadata file loaded (FASTA deflines will be used unless a metadata sheet is chosen)."
        )

        # Execution state
        self.is_running = False
        self.last_excel_path: Optional[Path] = None
        self.log_queue: "queue.Queue[str]" = queue.Queue()
        self.ui_queue: "queue.Queue[Tuple[str, Any]]" = queue.Queue()

        self._configure_styles()
        self._build_layout()
        self._attach_logging()
        self._poll_queues()

    def _configure_styles(self):
        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")

        style.configure(
            "Treeview",
            background=PALETTE["card_inner"],
            fieldbackground=PALETTE["card_inner"],
            foreground=PALETTE["text_dark"],
            rowheight=25,
            font=("Segoe UI", 9),
            borderwidth=0,
        )
        style.configure(
            "Treeview.Heading",
            background=PALETTE["card_outer"],
            foreground=PALETTE["text_dark"],
            font=("Segoe UI", 9, "bold"),
            relief="flat",
            padding=(6, 5),
        )
        style.map(
            "Treeview.Heading",
            background=[("active", PALETTE["primary_tint"])],
        )
        style.map(
            "Treeview",
            background=[("selected", PALETTE["primary_tint"])],
            foreground=[("selected", PALETTE["text_dark"])],
        )
        style.configure(
            "Green.Horizontal.TProgressbar",
            troughcolor=PALETTE["card_outer"],
            background=PALETTE["primary"],
            bordercolor=PALETTE["border"],
            lightcolor=PALETTE["primary"],
            darkcolor=PALETTE["primary"],
            thickness=14,
        )
        style.configure(
            "TCombobox",
            fieldbackground=PALETTE["card_inner"],
            background=PALETTE["card_outer"],
            foreground=PALETTE["text_dark"],
            padding=4,
        )

    def _build_layout(self):
        # 1. Top Brand Header (BIEN style logo + leaf emblem + tagline)
        header_frame = tk.Frame(self.root, bg=PALETTE["bg_canvas"], padx=22, pady=12)
        header_frame.pack(fill="x")

        logo_canvas = tk.Canvas(
            header_frame, width=44, height=44, bg=PALETTE["bg_canvas"], highlightthickness=0
        )
        logo_canvas.pack(side="left", padx=(0, 10))
        # Circular soft sage backdrop + vector botanical leaf in #4C9E45
        logo_canvas.create_oval(2, 2, 42, 42, fill=PALETTE["primary_tint"], outline=PALETTE["primary"], width=1.5)
        logo_canvas.create_polygon(
            22, 7, 34, 17, 31, 31, 22, 37, 13, 31, 10, 17,
            fill=PALETTE["primary"], outline="", smooth=True
        )
        logo_canvas.create_line(22, 37, 22, 11, fill="#FFFFFF", width=2)
        logo_canvas.create_line(22, 24, 28, 19, fill="#FFFFFF", width=1.5)
        logo_canvas.create_line(22, 28, 16, 22, fill="#FFFFFF", width=1.5)

        title_box = tk.Frame(header_frame, bg=PALETTE["bg_canvas"])
        title_box.pack(side="left")
        tk.Label(
            title_box,
            text="BarcoID",
            font=("Segoe UI", 19, "bold"),
            fg=PALETTE["text_dark"],
            bg=PALETTE["bg_canvas"],
        ).pack(side="left")
        tk.Label(
            title_box,
            text=f"  v{__version__}",
            font=("Segoe UI", 10, "bold"),
            fg=PALETTE["primary"],
            bg=PALETTE["bg_canvas"],
        ).pack(side="left", pady=(6, 0))
        tk.Label(
            header_frame,
            text="Four-Source DNA Barcode Taxonomic Identifier & QC Auditor",
            font=("Segoe UI", 10),
            fg=PALETTE["text_muted"],
            bg=PALETTE["bg_canvas"],
        ).pack(side="right", pady=(6, 0))

        # Main container
        main_wrap = tk.Frame(self.root, bg=PALETTE["bg_canvas"], padx=22, pady=2)
        main_wrap.pack(fill="both", expand=True)

        # ------------------------------------------------------------------
        # CARD 1: INPUT SEQUENCES & PARAMETERS (with BIEN folder-tab header)
        # ------------------------------------------------------------------
        self._create_tab_header(main_wrap, "1. SEQUENCES & PARAMETERS", PALETTE["primary"])
        card1 = tk.Frame(
            main_wrap,
            bg=PALETTE["card_outer"],
            highlightbackground=PALETTE["border"],
            highlightthickness=1,
            padx=14,
            pady=10,
        )
        card1.pack(fill="x", pady=(0, 10))

        inner1 = tk.Frame(card1, bg=PALETTE["card_inner"], padx=12, pady=10)
        inner1.pack(fill="x")
        inner1.columnconfigure(1, weight=1)
        inner1.columnconfigure(4, weight=1)

        # Row 0: FASTA Input & Output Dir
        tk.Label(
            inner1, text="FASTA File:", font=("Segoe UI", 9, "bold"),
            fg=PALETTE["text_dark"], bg=PALETTE["card_inner"]
        ).grid(row=0, column=0, sticky="w", padx=(0, 8), pady=4)

        fasta_entry = tk.Entry(
            inner1, textvariable=self.fasta_var, font=("Segoe UI", 9),
            bg="#FAF8F5", fg=PALETTE["text_dark"], relief="solid", bd=1
        )
        fasta_entry.grid(row=0, column=1, sticky="ew", padx=(0, 6), pady=4, ipady=3)

        self._make_button(
            inner1, "Browse FASTA", self.browse_fasta, primary=True
        ).grid(row=0, column=2, padx=(0, 18), pady=4)

        tk.Label(
            inner1, text="Output Folder:", font=("Segoe UI", 9, "bold"),
            fg=PALETTE["text_dark"], bg=PALETTE["card_inner"]
        ).grid(row=0, column=3, sticky="w", padx=(0, 8), pady=4)

        out_entry = tk.Entry(
            inner1, textvariable=self.output_dir_var, font=("Segoe UI", 9),
            bg="#FAF8F5", fg=PALETTE["text_dark"], relief="solid", bd=1
        )
        out_entry.grid(row=0, column=4, sticky="ew", padx=(0, 6), pady=4, ipady=3)

        self._make_button(
            inner1, "Browse", self.browse_output_dir, primary=False
        ).grid(row=0, column=5, pady=4)

        # Row 1: Taxon filter, Max sequences, Checkboxes
        opts_frame = tk.Frame(inner1, bg=PALETTE["card_inner"])
        opts_frame.grid(row=1, column=0, columnspan=6, sticky="ew", pady=(6, 0))

        tk.Label(
            opts_frame, text="Target Taxon:", font=("Segoe UI", 9, "bold"),
            fg=PALETTE["text_dark"], bg=PALETTE["card_inner"]
        ).pack(side="left", padx=(0, 6))

        taxon_combo = ttk.Combobox(
            opts_frame,
            textvariable=self.taxon_var,
            values=["Formicidae", "Hymenoptera", "Insecta", "Arthropoda", "Animalia", "Fungi", "Plantae"],
            width=16,
            font=("Segoe UI", 9),
        )
        taxon_combo.pack(side="left", padx=(0, 16))

        tk.Label(
            opts_frame, text="Max Sequences (optional):", font=("Segoe UI", 9),
            fg=PALETTE["text_muted"], bg=PALETTE["card_inner"]
        ).pack(side="left", padx=(0, 6))

        tk.Entry(
            opts_frame, textvariable=self.max_seq_var, width=8, font=("Segoe UI", 9),
            bg="#FAF8F5", fg=PALETTE["text_dark"], relief="solid", bd=1
        ).pack(side="left", padx=(0, 16), ipady=2)

        tk.Checkbutton(
            opts_frame, text="Dry Run (inspect cache only)", variable=self.dry_run_var,
            bg=PALETTE["card_inner"], fg=PALETTE["text_dark"],
            activebackground=PALETTE["card_inner"], selectcolor="#FAF8F5", font=("Segoe UI", 9)
        ).pack(side="left", padx=(0, 12))

        tk.Checkbutton(
            opts_frame, text="Force Refresh (ignore cache)", variable=self.force_refresh_var,
            bg=PALETTE["card_inner"], fg=PALETTE["text_dark"],
            activebackground=PALETTE["card_inner"], selectcolor="#FAF8F5", font=("Segoe UI", 9)
        ).pack(side="left")

        # ------------------------------------------------------------------
        # CARD 2: INTERACTIVE METADATA VIEWER & MORPHOSPECIES COLUMN PICKER
        # ------------------------------------------------------------------
        self._create_tab_header(
            main_wrap, "2. METADATA VIEWER & MORPHOSPECIES COLUMN PICKER", PALETTE["srv_gbif"]
        )
        card2 = tk.Frame(
            main_wrap,
            bg=PALETTE["card_outer"],
            highlightbackground=PALETTE["border"],
            highlightthickness=1,
            padx=14,
            pady=10,
        )
        card2.pack(fill="both", expand=True, pady=(0, 10))

        inner2 = tk.Frame(card2, bg=PALETTE["card_inner"], padx=12, pady=8)
        inner2.pack(fill="both", expand=True)

        # Metadata Top Bar
        meta_bar = tk.Frame(inner2, bg=PALETTE["card_inner"])
        meta_bar.pack(fill="x", pady=(0, 6))

        self._make_button(
            meta_bar, "Choose Metadata File (.csv / .tsv / .xlsx)", self.browse_metadata, primary=True
        ).pack(side="left", padx=(0, 8))

        self._make_button(
            meta_bar, "Clear", self.clear_metadata, primary=False
        ).pack(side="left", padx=(0, 14))

        # Morphospecies Column selector
        tk.Label(
            meta_bar, text="Morphospecies Column:", font=("Segoe UI", 9, "bold"),
            fg=PALETTE["primary"], bg=PALETTE["card_inner"]
        ).pack(side="left", padx=(0, 4))

        self.morpho_combo = ttk.Combobox(
            meta_bar, textvariable=self.morpho_col_var, state="readonly", width=20, font=("Segoe UI", 9)
        )
        self.morpho_combo.pack(side="left", padx=(0, 14))
        self.morpho_combo.bind("<<ComboboxSelected>>", lambda _e: self._refresh_column_badges())

        # Sample ID Column selector
        tk.Label(
            meta_bar, text="Sample ID Column:", font=("Segoe UI", 9, "bold"),
            fg=PALETTE["srv_ncbi"], bg=PALETTE["card_inner"]
        ).pack(side="left", padx=(0, 4))

        self.sample_combo = ttk.Combobox(
            meta_bar, textvariable=self.sample_col_var, state="readonly", width=18, font=("Segoe UI", 9)
        )
        self.sample_combo.pack(side="left", padx=(0, 10))
        self.sample_combo.bind("<<ComboboxSelected>>", lambda _e: self._refresh_column_badges())

        # Header click mode selector
        click_mode_frame = tk.Frame(meta_bar, bg=PALETTE["primary_tint"], padx=6, pady=2)
        click_mode_frame.pack(side="right")
        tk.Label(
            click_mode_frame, text="Header Click Sets:", font=("Segoe UI", 8, "bold"),
            fg=PALETTE["text_dark"], bg=PALETTE["primary_tint"]
        ).pack(side="left", padx=(0, 4))
        tk.Radiobutton(
            click_mode_frame, text="Morphospecies", variable=self.click_target_var, value="morpho",
            bg=PALETTE["primary_tint"], fg=PALETTE["primary"], selectcolor="#FFFFFF",
            activebackground=PALETTE["primary_tint"], font=("Segoe UI", 8, "bold")
        ).pack(side="left")
        tk.Radiobutton(
            click_mode_frame, text="Sample ID", variable=self.click_target_var, value="sample",
            bg=PALETTE["primary_tint"], fg=PALETTE["srv_ncbi"], selectcolor="#FFFFFF",
            activebackground=PALETTE["primary_tint"], font=("Segoe UI", 8, "bold")
        ).pack(side="left")

        # Live preview banner of selected Morphospecies column
        preview_banner = tk.Frame(inner2, bg=PALETTE["primary_tint"], padx=10, pady=4)
        preview_banner.pack(fill="x", pady=(0, 6))
        tk.Label(
            preview_banner,
            textvariable=self.morpho_preview_var,
            font=("Segoe UI", 9),
            fg=PALETTE["text_dark"],
            bg=PALETTE["primary_tint"],
            anchor="w",
        ).pack(fill="x")

        # Interactive Treeview Table for Metadata
        table_wrap = tk.Frame(
            inner2, bg=PALETTE["card_inner"], highlightbackground=PALETTE["border"], highlightthickness=1
        )
        table_wrap.pack(fill="both", expand=True)

        self.meta_tree = ttk.Treeview(table_wrap, show="headings", height=6)
        vsb = ttk.Scrollbar(table_wrap, orient="vertical", command=self.meta_tree.yview)
        hsb = ttk.Scrollbar(table_wrap, orient="horizontal", command=self.meta_tree.xview)
        self.meta_tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.meta_tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        table_wrap.rowconfigure(0, weight=1)
        table_wrap.columnconfigure(0, weight=1)

        # ------------------------------------------------------------------
        # CARD 3: BIEN-STYLE SERVICES, EXECUTION & LIVE RESULTS
        # ------------------------------------------------------------------
        self._create_tab_header(
            main_wrap, "3. TAXONOMIC RESOLUTION SERVICES & RESULTS", PALETTE["srv_bold"]
        )
        card3 = tk.Frame(
            main_wrap,
            bg=PALETTE["card_outer"],
            highlightbackground=PALETTE["border"],
            highlightthickness=1,
            padx=14,
            pady=10,
        )
        card3.pack(fill="both", expand=False, pady=(0, 10))

        inner3 = tk.Frame(card3, bg=PALETTE["card_inner"], padx=12, pady=10)
        inner3.pack(fill="both", expand=True)

        # 4 BIEN Service Pills Row
        srv_row = tk.Frame(inner3, bg=PALETTE["card_inner"])
        srv_row.pack(fill="x", pady=(0, 8))
        self.service_labels: Dict[str, tk.Label] = {}
        services_spec = [
            ("morpho", "Morphological Prior", PALETTE["srv_morpho"]),
            ("bold", "BOLD Systems v5", PALETTE["srv_bold"]),
            ("ncbi", "NCBI GenBank BLAST", PALETTE["srv_ncbi"]),
            ("gbif", "GBIF Backbone", PALETTE["srv_gbif"]),
        ]
        for idx, (key, title, color) in enumerate(services_spec):
            srv_row.columnconfigure(idx, weight=1)
            pill = tk.Frame(srv_row, bg=color, padx=10, pady=5)
            pill.grid(row=0, column=idx, sticky="ew", padx=(0 if idx == 0 else 6, 0))
            tk.Label(
                pill, text=title.upper(), font=("Segoe UI", 8, "bold"), fg="#FFFFFF", bg=color
            ).pack(side="left")
            status_lbl = tk.Label(
                pill, text="Idle", font=("Segoe UI", 8), fg="#FFFFFF", bg=color
            )
            status_lbl.pack(side="right")
            self.service_labels[key] = status_lbl

        # Action Controls + Progress Bar
        ctrl_row = tk.Frame(inner3, bg=PALETTE["card_inner"])
        ctrl_row.pack(fill="x", pady=(0, 8))

        self.run_btn = self._make_button(
            ctrl_row, "Run Identification", self.start_run, primary=True, big=True
        )
        self.run_btn.pack(side="left", padx=(0, 10))

        self.open_excel_btn = self._make_button(
            ctrl_row, "Open Excel Report", self.open_last_excel, primary=False
        )
        self.open_excel_btn.pack(side="left", padx=(0, 8))
        self.open_excel_btn.configure(state="disabled")

        self.open_folder_btn = self._make_button(
            ctrl_row, "Open Results Folder", self.open_output_folder, primary=False
        )
        self.open_folder_btn.pack(side="left", padx=(0, 16))

        prog_wrap = tk.Frame(ctrl_row, bg=PALETTE["card_inner"])
        prog_wrap.pack(side="left", fill="x", expand=True)

        self.stage_var = tk.StringVar(value="Ready — Select a FASTA file and click Run Identification.")
        tk.Label(
            prog_wrap, textvariable=self.stage_var, font=("Segoe UI", 9, "bold"),
            fg=PALETTE["text_dark"], bg=PALETTE["card_inner"], anchor="w"
        ).pack(fill="x")

        self.progress_var = tk.DoubleVar(value=0.0)
        self.progress_bar = ttk.Progressbar(
            prog_wrap, variable=self.progress_var, maximum=100.0, style="Green.Horizontal.TProgressbar"
        )
        self.progress_bar.pack(fill="x", pady=(3, 0))

        # Concordance Summary Counters + Log Console
        bottom_split = tk.Frame(inner3, bg=PALETTE["card_inner"])
        bottom_split.pack(fill="both", expand=True)

        self.summary_var = tk.StringVar(
            value="Concordance Summary: Total: 0  |  CONCORDANT: 0  |  NEW_ASSIGNMENT: 0  |  MISMATCH_ALERT: 0  |  NO_MATCH: 0"
        )
        tk.Label(
            bottom_split,
            textvariable=self.summary_var,
            font=("Segoe UI", 9, "bold"),
            fg=PALETTE["primary"],
            bg=PALETTE["primary_tint"],
            padx=10,
            pady=4,
            anchor="w",
        ).pack(fill="x", pady=(0, 6))

        self.log_text = tk.Text(
            bottom_split,
            height=6,
            font=("Consolas", 8),
            bg="#FAF8F5",
            fg=PALETTE["text_dark"],
            relief="solid",
            bd=1,
            state="disabled",
        )
        self.log_text.pack(fill="both", expand=True)

    def _create_tab_header(self, parent: tk.Widget, text: str, bg_color: str):
        """Creates a BIEN-style folder-tab header above a section card."""
        tab_bar = tk.Frame(parent, bg=PALETTE["bg_canvas"])
        tab_bar.pack(fill="x")
        tab = tk.Label(
            tab_bar,
            text=text,
            font=("Segoe UI", 9, "bold"),
            fg="#FFFFFF",
            bg=bg_color,
            padx=14,
            pady=3,
        )
        tab.pack(side="left")

    def _make_button(
        self,
        parent: tk.Widget,
        text: str,
        command,
        primary: bool = True,
        big: bool = False,
    ) -> tk.Button:
        bg = PALETTE["primary"] if primary else PALETTE["card_outer"]
        fg = "#FFFFFF" if primary else PALETTE["text_dark"]
        active_bg = PALETTE["primary_hover"] if primary else PALETTE["border"]
        font = ("Segoe UI", 10, "bold") if big else ("Segoe UI", 9, "bold")
        padx = 16 if big else 10
        pady = 6 if big else 3
        btn = tk.Button(
            parent,
            text=text,
            command=command,
            bg=bg,
            fg=fg,
            activebackground=active_bg,
            activeforeground=fg,
            relief="flat",
            bd=0,
            padx=padx,
            pady=pady,
            font=font,
            cursor="hand2",
        )
        return btn

    def _attach_logging(self):
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)
        handler = QueueLogHandler(self.log_queue)
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S"))
        root_logger.addHandler(handler)

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
            "No metadata file loaded (FASTA deflines will be used unless a metadata sheet is chosen)."
        )

    def load_metadata_file(self, path: Path):
        """Loads a metadata spreadsheet into the in-app preview table and auto-detects columns."""
        try:
            headers, rows = MetadataParser.read_preview(path, max_rows=25)
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

        # Populate Treeview columns and rows
        self.meta_tree.delete(*self.meta_tree.get_children())
        self.meta_tree["columns"] = headers

        for col in headers:
            self.meta_tree.column(col, width=140, minwidth=90, anchor="w")
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

        # Build a live preview example from the first non-empty row in the selected morphospecies column
        m_idx = self.meta_columns.index(m_col) if m_col in self.meta_columns else -1
        s_idx = self.meta_columns.index(s_col) if s_col in self.meta_columns else -1

        example_text = ""
        from barcoid.parsers.headers import DEFAULT_GENUS_PREFIXES

        helper = MetadataParser.__new__(MetadataParser)
        helper.prefix_map = dict(DEFAULT_GENUS_PREFIXES)

        for row in self.meta_rows:
            m_val = row[m_idx].strip() if 0 <= m_idx < len(row) else ""
            s_val = row[s_idx].strip() if 0 <= s_idx < len(row) else ""
            if m_val:
                inferred = helper.infer_genus_from_morpho(m_val)
                genus_note = f"Inferred Genus: {inferred}" if inferred else "Unassigned / Indeterminate"
                example_text = f"Example row ({s_val or 'row'}) -> '{m_val}' ({genus_note})"
                break

        if not example_text:
            example_text = "Click any column header below to select the column with Morphospecies names."

        self.morpho_preview_var.set(
            f"Loaded {Path(self.metadata_var.get()).name}  |  Morphospecies Column: '{m_col}'  |  "
            f"Sample ID Column: '{s_col}'  |  {example_text}"
        )

    # ------------------------------------------------------------------
    # Pipeline Execution in Background Worker Thread
    # ------------------------------------------------------------------
    def start_run(self):
        if self.is_running:
            return

        fasta_str = self.fasta_var.get().strip()
        if not fasta_str:
            messagebox.showwarning("Missing Input", "Please select an input FASTA file first.")
            return

        fasta_path = Path(fasta_str)
        if not fasta_path.exists():
            messagebox.showerror("File Not Found", f"FASTA file does not exist:\n{fasta_path}")
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

        self.is_running = True
        self.run_btn.configure(state="disabled", text="Running...")
        self.open_excel_btn.configure(state="disabled")
        self.progress_var.set(2.0)
        self._set_service_states(morpho="Active", bold="Pending", ncbi="Pending", gbif="Pending")

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

        try:
            pipeline = BarcoIDPipeline(config)
            rows = pipeline.run(
                fasta_path=fasta_path,
                metadata_path=meta_path,
                sample_col=sample_col,
                morpho_col=morpho_col,
                progress_callback=_progress,
            )
            xlsx_path = Path(config.output_dir) / f"{fasta_path.stem}_multi_source_identification.xlsx"
            self.ui_queue.put(("done", (rows, xlsx_path, config.dry_run)))
        except Exception as exc:
            logging.error(f"Pipeline execution error: {exc}")
            self.ui_queue.put(("error", str(exc)))

    def _set_service_states(self, **kwargs: str):
        for key, text in kwargs.items():
            if key in self.service_labels:
                self.service_labels[key].configure(text=text)

    def _poll_queues(self):
        # 1. Drain log messages
        while True:
            try:
                msg = self.log_queue.get_nowait()
            except queue.Empty:
                break
            self.log_text.configure(state="normal")
            self.log_text.insert("end", msg + "\n")
            self.log_text.see("end")
            self.log_text.configure(state="disabled")

        # 2. Drain UI state events
        while True:
            try:
                event, payload = self.ui_queue.get_nowait()
            except queue.Empty:
                break

            if event == "progress":
                stage, pct = payload
                self.stage_var.set(stage)
                self.progress_var.set(pct)
                if pct <= 15:
                    self._set_service_states(morpho="Active", bold="Pending", ncbi="Pending", gbif="Pending")
                elif pct <= 40:
                    self._set_service_states(morpho="Done", bold="Active", ncbi="Pending", gbif="Pending")
                elif pct <= 70:
                    self._set_service_states(morpho="Done", bold="Done", ncbi="Active", gbif="Pending")
                elif pct < 100:
                    self._set_service_states(morpho="Done", bold="Done", ncbi="Done", gbif="Active")
                else:
                    self._set_service_states(morpho="Done", bold="Done", ncbi="Done", gbif="Done")

            elif event == "done":
                rows, xlsx_path, is_dry_run = payload
                self.is_running = False
                self.run_btn.configure(state="normal", text="Run Identification")
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
                    f"Concordance Summary: Total: {len(rows)}  |  "
                    f"CONCORDANT: {counts['CONCORDANT']}  |  "
                    f"NEW_ASSIGNMENT: {counts['NEW_ASSIGNMENT']}  |  "
                    f"MISMATCH_ALERT: {counts['MISMATCH_ALERT']}  |  "
                    f"NO_MATCH: {counts['NO_MATCH']}"
                )

                if not is_dry_run and xlsx_path.exists():
                    self.last_excel_path = xlsx_path
                    self.open_excel_btn.configure(state="normal")

            elif event == "error":
                self.is_running = False
                self.run_btn.configure(state="normal", text="Run Identification")
                self.stage_var.set(f"Error: {payload}")
                messagebox.showerror("Execution Error", f"An error occurred during identification:\n{payload}")

        self.root.after(100, self._poll_queues)

    def open_last_excel(self):
        if self.last_excel_path and self.last_excel_path.exists():
            open_path_in_os(self.last_excel_path)

    def open_output_folder(self):
        out_dir = Path(self.output_dir_var.get().strip() or "results")
        out_dir.mkdir(parents=True, exist_ok=True)
        open_path_in_os(out_dir)


def launch_gui():
    """Creates and runs the main BarcoID desktop application window."""
    root = tk.Tk()
    BarcoIDApp(root)
    root.mainloop()


if __name__ == "__main__":
    launch_gui()
