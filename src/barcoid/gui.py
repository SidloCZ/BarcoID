"""
Standalone Desktop GUI for BarcoID.
Click-through 3-step wizard with native High-DPI text rendering, a minimalist 2-color
palette (#1F2421 neutral charcoal + #4C9E45 botanical green accent), and an in-app
interactive Metadata Table Preview & Column Picker.
"""

import ctypes
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
from barcoid.parsers.headers import DEFAULT_GENUS_PREFIXES
from barcoid.parsers.metadata import MetadataParser
from barcoid.pipeline import BarcoIDPipeline

# Strict Minimalist Palette: Neutral Monochrome + Single Accent (#4C9E45)
PALETTE = {
    "bg_canvas": "#FAF8F5",       # Clean light neutral background
    "card_outer": "#EFECE6",      # Subtle warm-gray container border/surface
    "card_inner": "#FFFFFF",      # Crisp white surface
    "border": "#D5DBD6",          # Subtle 1px divider
    "primary": "#4C9E45",         # Single brand accent green (used sparingly)
    "primary_hover": "#3B8235",   # Hover state for primary button
    "primary_tint": "#EAF4E9",    # Soft green tint for active selection
    "text_dark": "#1F2421",       # High-contrast charcoal text
    "text_muted": "#5C6660",      # Secondary neutral text
}

# Strictly 3 Font Styles Across the Entire Application
FONT_TITLE = ("Segoe UI", 16, "bold")
FONT_HEADING = ("Segoe UI", 11, "bold")
FONT_BODY = ("Segoe UI", 11)

SVG_ICON_PATH = Path(__file__).resolve().parent / "assets" / "logo_4streams.svg"


def enable_high_dpi():
    """Enables native Per-Monitor High-DPI rendering on Windows so fullscreen text is crisp."""
    if sys.platform.startswith("win"):
        try:
            # PROCESS_PER_MONITOR_DPI_AWARE_V2 = 2
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
    """Main click-through desktop wizard for BarcoID."""

    def __init__(self, root: tk.Tk):
        self.root = root
        self._apply_dpi_scaling()
        self.root.title(f"BarcoID v{__version__}")
        self.root.geometry("1120x760")
        self.root.minsize(900, 640)
        self.root.configure(bg=PALETTE["bg_canvas"])

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
        self.click_target_var = tk.StringVar(value="morpho")  # "morpho" or "sample"
        self.morpho_preview_var = tk.StringVar(
            value="Optional: Load a metadata file (.csv, .tsv, .xlsx) to preview rows and click the Morphospecies column."
        )
        self.run_overview_var = tk.StringVar(value="")

        # Execution state
        self.is_running = False
        self.last_excel_path: Optional[Path] = None
        self.log_queue: "queue.Queue[str]" = queue.Queue()
        self.ui_queue: "queue.Queue[Tuple[str, Any]]" = queue.Queue()

        self._configure_styles()
        self._build_layout()
        self._attach_logging()
        self.show_step(0)
        self._poll_queues()

    def _apply_dpi_scaling(self):
        """Synchronizes Tkinter's internal font/widget scaling factor with the monitor DPI."""
        try:
            dpi = self.root.winfo_fpixels("1i")
            scale = max(1.0, float(dpi) / 72.0)
            self.root.tk.call("tk", "scaling", scale)
            self.dpi_scale = float(dpi) / 96.0
        except Exception:
            self.dpi_scale = 1.0

    def _configure_styles(self):
        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")

        row_h = max(30, int(30 * self.dpi_scale))
        style.configure(
            "Treeview",
            background=PALETTE["card_inner"],
            fieldbackground=PALETTE["card_inner"],
            foreground=PALETTE["text_dark"],
            rowheight=row_h,
            font=FONT_BODY,
            borderwidth=0,
        )
        style.configure(
            "Treeview.Heading",
            background=PALETTE["bg_canvas"],
            foreground=PALETTE["text_dark"],
            font=FONT_HEADING,
            relief="flat",
            padding=(10, 8),
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
            troughcolor=PALETTE["bg_canvas"],
            background=PALETTE["primary"],
            bordercolor=PALETTE["border"],
            lightcolor=PALETTE["primary"],
            darkcolor=PALETTE["primary"],
            thickness=max(16, int(16 * self.dpi_scale)),
        )
        style.configure(
            "TCombobox",
            fieldbackground=PALETTE["card_inner"],
            background=PALETTE["bg_canvas"],
            foreground=PALETTE["text_dark"],
            padding=6,
        )

    def _draw_4streams_icon(self, canvas: tk.Canvas):
        """
        Renders the 4-streams-knotting-together vector icon (matching assets/logo_4streams.svg)
        at native resolution onto the header canvas.
        """
        # Rounded badge background
        canvas.create_oval(2, 2, 46, 46, fill=PALETTE["primary_tint"], outline=PALETTE["primary"], width=2)

        # Stream 1 (Top outer -> knots through center -> right node)
        canvas.create_line(
            9, 12, 20, 13, 25, 31, 33, 24, 40, 24,
            fill=PALETTE["text_dark"], width=2.4, smooth=True, capstyle="round"
        )
        # Stream 4 (Bottom outer -> knots through center -> right node)
        canvas.create_line(
            9, 36, 20, 35, 25, 17, 33, 24, 40, 24,
            fill=PALETTE["text_dark"], width=2.4, smooth=True, capstyle="round"
        )
        # Stream 2 (Upper inner - primary green)
        canvas.create_line(
            9, 20, 19, 20, 25, 15, 31, 24, 40, 24,
            fill=PALETTE["primary"], width=2.8, smooth=True, capstyle="round"
        )
        # Stream 3 (Lower inner - primary green)
        canvas.create_line(
            9, 28, 19, 28, 25, 33, 31, 24, 40, 24,
            fill=PALETTE["primary"], width=2.8, smooth=True, capstyle="round"
        )

        # 4 origin dots on the left
        for y_pos, col in [(12, PALETTE["text_dark"]), (20, PALETTE["primary"]), (28, PALETTE["primary"]), (36, PALETTE["text_dark"])]:
            canvas.create_oval(6.5, y_pos - 2.5, 11.5, y_pos + 2.5, fill=col, outline="")

        # Central knot ring & unified consensus node on the right
        canvas.create_oval(22.5, 20.5, 29.5, 27.5, fill=PALETTE["card_inner"], outline=PALETTE["primary"], width=2)
        canvas.create_oval(37, 20.5, 44, 27.5, fill=PALETTE["primary"], outline="")

    def _build_layout(self):
        # 1. Header Bar + Stepper Navigation
        top_bar = tk.Frame(
            self.root,
            bg=PALETTE["card_inner"],
            highlightbackground=PALETTE["border"],
            highlightthickness=1,
            padx=28,
            pady=14,
        )
        top_bar.pack(fill="x")

        brand_frame = tk.Frame(top_bar, bg=PALETTE["card_inner"])
        brand_frame.pack(side="left")

        logo_canvas = tk.Canvas(
            brand_frame, width=48, height=48, bg=PALETTE["card_inner"], highlightthickness=0
        )
        logo_canvas.pack(side="left", padx=(0, 12))
        self._draw_4streams_icon(logo_canvas)

        tk.Label(
            brand_frame,
            text="BarcoID",
            font=FONT_TITLE,
            fg=PALETTE["text_dark"],
            bg=PALETTE["card_inner"],
        ).pack(side="left")

        # Click-through Wizard Step Tabs on the right of the header
        stepper_frame = tk.Frame(top_bar, bg=PALETTE["card_inner"])
        stepper_frame.pack(side="right")

        self.step_buttons: List[tk.Button] = []
        step_titles = [
            "1. Sequences & Parameters",
            "2. Metadata Column Picker",
            "3. Run & Results",
        ]
        for idx, title in enumerate(step_titles):
            btn = tk.Button(
                stepper_frame,
                text=title,
                command=lambda i=idx: self.show_step(i),
                font=FONT_HEADING,
                relief="flat",
                bd=0,
                padx=16,
                pady=8,
                cursor="hand2",
            )
            btn.pack(side="left", padx=(8, 0))
            self.step_buttons.append(btn)

        # 2. Main Step Page Container (holds one active page at a time)
        self.page_container = tk.Frame(self.root, bg=PALETTE["bg_canvas"], padx=28, pady=20)
        self.page_container.pack(fill="both", expand=True)

        self.step_frames: List[tk.Frame] = []
        self._build_step1_sequences()
        self._build_step2_metadata()
        self._build_step3_run()

    # ------------------------------------------------------------------
    # STEP 1: SEQUENCES & PARAMETERS
    # ------------------------------------------------------------------
    def _build_step1_sequences(self):
        page = tk.Frame(
            self.page_container,
            bg=PALETTE["card_inner"],
            highlightbackground=PALETTE["border"],
            highlightthickness=1,
            padx=32,
            pady=28,
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
            text="Choose your query DNA barcode FASTA file and target taxon filter before moving to optional metadata.",
            font=FONT_BODY,
            fg=PALETTE["text_muted"],
            bg=PALETTE["card_inner"],
            anchor="w",
        ).pack(fill="x", pady=(0, 24))

        form = tk.Frame(page, bg=PALETTE["card_inner"])
        form.pack(fill="x")
        form.columnconfigure(1, weight=1)

        # FASTA File
        tk.Label(
            form, text="Input FASTA File:", font=FONT_HEADING,
            fg=PALETTE["text_dark"], bg=PALETTE["card_inner"]
        ).grid(row=0, column=0, sticky="w", padx=(0, 16), pady=10)

        tk.Entry(
            form, textvariable=self.fasta_var, font=FONT_BODY,
            bg=PALETTE["bg_canvas"], fg=PALETTE["text_dark"], relief="solid", bd=1
        ).grid(row=0, column=1, sticky="ew", padx=(0, 12), pady=10, ipady=6)

        self._make_button(form, "Browse FASTA", self.browse_fasta, primary=True).grid(
            row=0, column=2, sticky="ew", pady=10
        )

        # Output Folder
        tk.Label(
            form, text="Output Folder:", font=FONT_HEADING,
            fg=PALETTE["text_dark"], bg=PALETTE["card_inner"]
        ).grid(row=1, column=0, sticky="w", padx=(0, 16), pady=10)

        tk.Entry(
            form, textvariable=self.output_dir_var, font=FONT_BODY,
            bg=PALETTE["bg_canvas"], fg=PALETTE["text_dark"], relief="solid", bd=1
        ).grid(row=1, column=1, sticky="ew", padx=(0, 12), pady=10, ipady=6)

        self._make_button(form, "Browse Folder", self.browse_output_dir, primary=False).grid(
            row=1, column=2, sticky="ew", pady=10
        )

        # Target Taxon
        tk.Label(
            form, text="Target Taxon Filter:", font=FONT_HEADING,
            fg=PALETTE["text_dark"], bg=PALETTE["card_inner"]
        ).grid(row=2, column=0, sticky="w", padx=(0, 16), pady=10)

        taxon_row = tk.Frame(form, bg=PALETTE["card_inner"])
        taxon_row.grid(row=2, column=1, columnspan=2, sticky="w", pady=10)

        taxon_combo = ttk.Combobox(
            taxon_row,
            textvariable=self.taxon_var,
            values=["Formicidae", "Hymenoptera", "Insecta", "Arthropoda", "Animalia", "Fungi", "Plantae"],
            width=22,
            font=FONT_BODY,
        )
        taxon_combo.pack(side="left", padx=(0, 24))

        tk.Label(
            taxon_row, text="Max Sequences (optional):", font=FONT_BODY,
            fg=PALETTE["text_muted"], bg=PALETTE["card_inner"]
        ).pack(side="left", padx=(0, 10))

        tk.Entry(
            taxon_row, textvariable=self.max_seq_var, width=10, font=FONT_BODY,
            bg=PALETTE["bg_canvas"], fg=PALETTE["text_dark"], relief="solid", bd=1
        ).pack(side="left", ipady=4)

        # Checkboxes
        flags_row = tk.Frame(form, bg=PALETTE["card_inner"])
        flags_row.grid(row=3, column=1, columnspan=2, sticky="w", pady=10)

        tk.Checkbutton(
            flags_row, text="Dry Run (inspect cache only)", variable=self.dry_run_var,
            bg=PALETTE["card_inner"], fg=PALETTE["text_dark"],
            activebackground=PALETTE["card_inner"], selectcolor=PALETTE["bg_canvas"], font=FONT_BODY
        ).pack(side="left", padx=(0, 24))

        tk.Checkbutton(
            flags_row, text="Force Refresh (bypass disk cache)", variable=self.force_refresh_var,
            bg=PALETTE["card_inner"], fg=PALETTE["text_dark"],
            activebackground=PALETTE["card_inner"], selectcolor=PALETTE["bg_canvas"], font=FONT_BODY
        ).pack(side="left")

        # Footer Navigation
        footer1 = tk.Frame(page, bg=PALETTE["card_inner"])
        footer1.pack(side="bottom", fill="x", pady=(20, 0))

        self._make_button(
            footer1, "Next: Metadata Column Picker ->", lambda: self.show_step(1), primary=True
        ).pack(side="right")

    # ------------------------------------------------------------------
    # STEP 2: INTERACTIVE METADATA VIEWER & COLUMN PICKER
    # ------------------------------------------------------------------
    def _build_step2_metadata(self):
        page = tk.Frame(
            self.page_container,
            bg=PALETTE["card_inner"],
            highlightbackground=PALETTE["border"],
            highlightthickness=1,
            padx=32,
            pady=24,
        )
        self.step_frames.append(page)

        tk.Label(
            page,
            text="Step 2: Choose Metadata File & Click Morphospecies Column",
            font=FONT_TITLE,
            fg=PALETTE["text_dark"],
            bg=PALETTE["card_inner"],
            anchor="w",
        ).pack(fill="x", pady=(0, 12))

        # Top Controls Row
        meta_bar = tk.Frame(page, bg=PALETTE["card_inner"])
        meta_bar.pack(fill="x", pady=(0, 12))

        self._make_button(
            meta_bar, "Choose Metadata File (.csv / .tsv / .xlsx)", self.browse_metadata, primary=True
        ).pack(side="left", padx=(0, 10))

        self._make_button(
            meta_bar, "Clear Metadata", self.clear_metadata, primary=False
        ).pack(side="left", padx=(0, 20))

        tk.Label(
            meta_bar, text="Morphospecies Column:", font=FONT_HEADING,
            fg=PALETTE["text_dark"], bg=PALETTE["card_inner"]
        ).pack(side="left", padx=(0, 8))

        self.morpho_combo = ttk.Combobox(
            meta_bar, textvariable=self.morpho_col_var, state="readonly", width=20, font=FONT_BODY
        )
        self.morpho_combo.pack(side="left", padx=(0, 18))
        self.morpho_combo.bind("<<ComboboxSelected>>", lambda _e: self._refresh_column_badges())

        tk.Label(
            meta_bar, text="Sample ID Column:", font=FONT_HEADING,
            fg=PALETTE["text_dark"], bg=PALETTE["card_inner"]
        ).pack(side="left", padx=(0, 8))

        self.sample_combo = ttk.Combobox(
            meta_bar, textvariable=self.sample_col_var, state="readonly", width=18, font=FONT_BODY
        )
        self.sample_combo.pack(side="left")
        self.sample_combo.bind("<<ComboboxSelected>>", lambda _e: self._refresh_column_badges())

        # Header Click Mode Bar + Live Preview Banner
        sub_bar = tk.Frame(page, bg=PALETTE["primary_tint"], padx=14, pady=8)
        sub_bar.pack(fill="x", pady=(0, 12))

        tk.Label(
            sub_bar,
            textvariable=self.morpho_preview_var,
            font=FONT_BODY,
            fg=PALETTE["text_dark"],
            bg=PALETTE["primary_tint"],
            anchor="w",
        ).pack(side="left", fill="x", expand=True)

        mode_box = tk.Frame(sub_bar, bg=PALETTE["primary_tint"])
        mode_box.pack(side="right")
        tk.Label(
            mode_box, text="Clicking column header sets:", font=FONT_HEADING,
            fg=PALETTE["text_dark"], bg=PALETTE["primary_tint"]
        ).pack(side="left", padx=(0, 8))
        tk.Radiobutton(
            mode_box, text="Morphospecies", variable=self.click_target_var, value="morpho",
            bg=PALETTE["primary_tint"], fg=PALETTE["text_dark"], selectcolor=PALETTE["card_inner"],
            activebackground=PALETTE["primary_tint"], font=FONT_BODY
        ).pack(side="left", padx=(0, 8))
        tk.Radiobutton(
            mode_box, text="Sample ID", variable=self.click_target_var, value="sample",
            bg=PALETTE["primary_tint"], fg=PALETTE["text_dark"], selectcolor=PALETTE["card_inner"],
            activebackground=PALETTE["primary_tint"], font=FONT_BODY
        ).pack(side="left")

        # Footer Navigation (packed before expanding table so it stays anchored at bottom)
        footer2 = tk.Frame(page, bg=PALETTE["card_inner"])
        footer2.pack(side="bottom", fill="x", pady=(14, 0))

        self._make_button(
            footer2, "<- Back: Sequences", lambda: self.show_step(0), primary=False
        ).pack(side="left")

        self._make_button(
            footer2, "Next: Run & Results ->", lambda: self.show_step(2), primary=True
        ).pack(side="right")

        # Full-page Interactive Spreadsheet Preview Table
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
    # STEP 3: RUN & RESULTS
    # ------------------------------------------------------------------
    def _build_step3_run(self):
        page = tk.Frame(
            self.page_container,
            bg=PALETTE["card_inner"],
            highlightbackground=PALETTE["border"],
            highlightthickness=1,
            padx=32,
            pady=24,
        )
        self.step_frames.append(page)

        tk.Label(
            page,
            text="Step 3: Four-Stream Taxonomic Resolution & Audit Results",
            font=FONT_TITLE,
            fg=PALETTE["text_dark"],
            bg=PALETTE["card_inner"],
            anchor="w",
        ).pack(fill="x", pady=(0, 8))

        tk.Label(
            page,
            textvariable=self.run_overview_var,
            font=FONT_BODY,
            fg=PALETTE["text_muted"],
            bg=PALETTE["card_inner"],
            anchor="w",
        ).pack(fill="x", pady=(0, 14))

        # 4 Evidence Stream Cards (strictly 2 colors: neutral when idle, #4C9E45 when active/done)
        srv_row = tk.Frame(page, bg=PALETTE["card_inner"])
        srv_row.pack(fill="x", pady=(0, 16))
        self.service_cards: Dict[str, tk.Frame] = {}
        self.service_titles: Dict[str, tk.Label] = {}
        self.service_labels: Dict[str, tk.Label] = {}

        streams = [
            ("morpho", "1. Morphological Prior"),
            ("bold", "2. BOLD Systems v5"),
            ("ncbi", "3. NCBI GenBank BLAST"),
            ("gbif", "4. GBIF Backbone"),
        ]
        for idx, (key, title) in enumerate(streams):
            srv_row.columnconfigure(idx, weight=1)
            card = tk.Frame(
                srv_row,
                bg=PALETTE["bg_canvas"],
                highlightbackground=PALETTE["border"],
                highlightthickness=1,
                padx=12,
                pady=10,
            )
            card.grid(row=0, column=idx, sticky="ew", padx=(0 if idx == 0 else 10, 0))
            t_lbl = tk.Label(
                card, text=title, font=FONT_HEADING, fg=PALETTE["text_dark"], bg=PALETTE["bg_canvas"]
            )
            t_lbl.pack(side="left")
            s_lbl = tk.Label(
                card, text="Idle", font=FONT_BODY, fg=PALETTE["text_muted"], bg=PALETTE["bg_canvas"]
            )
            s_lbl.pack(side="right")
            self.service_cards[key] = card
            self.service_titles[key] = t_lbl
            self.service_labels[key] = s_lbl

        # Action Controls + Progress Bar
        ctrl_row = tk.Frame(page, bg=PALETTE["card_inner"])
        ctrl_row.pack(fill="x", pady=(0, 14))

        self.run_btn = self._make_button(
            ctrl_row, "Run Identification", self.start_run, primary=True
        )
        self.run_btn.pack(side="left", padx=(0, 10))

        self.open_excel_btn = self._make_button(
            ctrl_row, "Open Excel Report", self.open_last_excel, primary=False
        )
        self.open_excel_btn.pack(side="left", padx=(0, 10))
        self.open_excel_btn.configure(state="disabled")

        self.open_folder_btn = self._make_button(
            ctrl_row, "Open Results Folder", self.open_output_folder, primary=False
        )
        self.open_folder_btn.pack(side="left", padx=(0, 20))

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
            padx=14,
            pady=10,
            anchor="w",
        ).pack(fill="x", pady=(0, 12))

        # Footer Navigation
        footer3 = tk.Frame(page, bg=PALETTE["card_inner"])
        footer3.pack(side="bottom", fill="x", pady=(14, 0))

        self._make_button(
            footer3, "<- Back: Metadata Column Picker", lambda: self.show_step(1), primary=False
        ).pack(side="left")

        # Live Log Console
        self.log_text = tk.Text(
            page,
            font=FONT_BODY,
            bg=PALETTE["bg_canvas"],
            fg=PALETTE["text_dark"],
            relief="solid",
            bd=1,
            padx=10,
            pady=8,
            state="disabled",
        )
        self.log_text.pack(fill="both", expand=True)

    # ------------------------------------------------------------------
    # Step Navigation & Button Helpers
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
                btn.configure(bg=PALETTE["primary"], fg="#FFFFFF")
            else:
                btn.configure(bg=PALETTE["bg_canvas"], fg=PALETTE["text_dark"])

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
        bg = PALETTE["primary"] if primary else PALETTE["bg_canvas"]
        fg = "#FFFFFF" if primary else PALETTE["text_dark"]
        active_bg = PALETTE["primary_hover"] if primary else PALETTE["border"]
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg=bg,
            fg=fg,
            activebackground=active_bg,
            activeforeground=fg,
            relief="flat",
            bd=0,
            padx=18,
            pady=8,
            font=FONT_HEADING,
            cursor="hand2",
        )

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
        """Updates the 4 stream cards using strictly neutral (Idle/Pending) or #4C9E45 (Active/Done)."""
        for key, state in kwargs.items():
            if key not in self.service_labels:
                continue
            card = self.service_cards[key]
            t_lbl = self.service_titles[key]
            s_lbl = self.service_labels[key]
            s_lbl.configure(text=state)

            if state == "Active":
                card.configure(bg=PALETTE["primary"], highlightbackground=PALETTE["primary"])
                t_lbl.configure(bg=PALETTE["primary"], fg="#FFFFFF")
                s_lbl.configure(bg=PALETTE["primary"], fg="#FFFFFF")
            elif state == "Done":
                card.configure(bg=PALETTE["primary_tint"], highlightbackground=PALETTE["primary"])
                t_lbl.configure(bg=PALETTE["primary_tint"], fg=PALETTE["text_dark"])
                s_lbl.configure(bg=PALETTE["primary_tint"], fg=PALETTE["primary"])
            else:
                card.configure(bg=PALETTE["bg_canvas"], highlightbackground=PALETTE["border"])
                t_lbl.configure(bg=PALETTE["bg_canvas"], fg=PALETTE["text_dark"])
                s_lbl.configure(bg=PALETTE["bg_canvas"], fg=PALETTE["text_muted"])

    def _poll_queues(self):
        while True:
            try:
                msg = self.log_queue.get_nowait()
            except queue.Empty:
                break
            self.log_text.configure(state="normal")
            self.log_text.insert("end", msg + "\n")
            self.log_text.see("end")
            self.log_text.configure(state="disabled")

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
                    f"Concordance Summary:   Total: {len(rows)}   |   "
                    f"CONCORDANT: {counts['CONCORDANT']}   |   "
                    f"NEW_ASSIGNMENT: {counts['NEW_ASSIGNMENT']}   |   "
                    f"MISMATCH_ALERT: {counts['MISMATCH_ALERT']}   |   "
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
    """Enables High-DPI rendering and launches the BarcoID desktop wizard."""
    enable_high_dpi()
    root = tk.Tk()
    BarcoIDApp(root)
    root.mainloop()


if __name__ == "__main__":
    launch_gui()
