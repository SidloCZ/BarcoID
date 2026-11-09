"""
Standalone Desktop GUI for BarcoID.
Click-through 4-step wizard with native High-DPI text rendering, maximized startup,
responsive layouts, custom ModernScrollbar sliders, anti-aliased SVG icons (arrows,
check-circle, spinner, and 4-streams logo), segmented Concordance Summary cards,
interactive column resizing and Excel-style double-click auto-fit, single-cell
highlighting on Concordance_Status and QC_Flag, and Ctrl+Shift+D Diagnostics.
"""

import ctypes
import logging
import math
import os
import platform
import queue
import struct
import subprocess
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
import traceback
import urllib.parse
import webbrowser
import zlib
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable, Dict, List, Optional, Tuple

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
    "bg_canvas": "#FFFFFF",  # Pure white background
    "card_outer": "#FFFFFF",  # Pure white container
    "card_inner": "#FFFFFF",  # Pure white surface
    "border": "#111111",  # Crisp high-contrast black border
    "primary": "#4C9E45",  # Brand accent green
    "primary_hover": "#3B8235",  # Hover green
    "primary_tint": "#EAF4E9",  # Soft green tint (always paired with #111111 text)
    "alert_tint": "#FDECEC",  # Soft alert cell highlight for MISMATCH_ALERT / QC flags
    "text_dark": "#111111",  # High-contrast black text everywhere on light surfaces
    "text_muted": "#111111",  # No gray text: secondary labels also use crisp #111111
}

# Strictly Font Styles Across Application
FONT_TITLE = ("Segoe UI", 16, "bold")
FONT_HEADING = ("Segoe UI", 11, "bold")
FONT_BODY = ("Segoe UI", 11)
FONT_SMALL = ("Segoe UI", 9)

ASSETS_DIR = Path(__file__).resolve().parent / "assets"
SVG_ICON_PATH = ASSETS_DIR / "logo.svg"
PNG_ICON_PATH = ASSETS_DIR / "logo_48.png"
PNG_ICON_HI_PATH = ASSETS_DIR / "logo_96.png"
ICO_ICON_PATH = ASSETS_DIR / "app_icon.ico"
SVG_ARROW_RIGHT_PATH = ASSETS_DIR / "arrow_right.svg"
SVG_ARROW_LEFT_PATH = ASSETS_DIR / "arrow_left.svg"
SVG_CHECK_CIRCLE_PATH = ASSETS_DIR / "check_circle.svg"
SVG_HELP_PATH = ASSETS_DIR / "help.svg"
SVG_BUG_PATH = ASSETS_DIR / "bug.svg"
GUIDE_DIR = ASSETS_DIR / "guide_screenshots"

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

PRIMARY_EXPANDED_COLUMNS = {
    "Sample_ID",
    "Consensus_Species",
    "Concordance_Status",
    "QC_Flag",
}


# ------------------------------------------------------------------
# Sub-Pixel Anti-Aliased SVG / Vector Icon Rasterizer (PPM -> tk.PhotoImage)
# Eliminates jagged Windows GDI polygon edges on circles, checkmarks, and arrows.
# ------------------------------------------------------------------
def _hex_to_rgb(hex_color: str) -> Tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _dist_to_segment(px: float, py: float, x1: float, y1: float, x2: float, y2: float) -> float:
    dx = x2 - x1
    dy = y2 - y1
    len_sq = dx * dx + dy * dy
    if len_sq == 0.0:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / len_sq))
    proj_x = x1 + t * dx
    proj_y = y1 + t * dy
    return math.hypot(px - proj_x, py - proj_y)


def _blend_rgb(
    bg: Tuple[int, int, int], fg: Tuple[int, int, int], alpha: float
) -> Tuple[int, int, int]:
    a = max(0.0, min(1.0, alpha))
    return (
        int(bg[0] * (1.0 - a) + fg[0] * a + 0.5),
        int(bg[1] * (1.0 - a) + fg[1] * a + 0.5),
        int(bg[2] * (1.0 - a) + fg[2] * a + 0.5),
    )


def _rgba_to_png(w: int, h: int, rgba_bytes: bytearray) -> bytes:
    """Encodes raw RGBA bytes into a standard in-memory PNG binary payload."""
    raw = bytearray()
    row_bytes = w * 4
    for y in range(h):
        raw.append(0)  # filter type 0: None
        raw.extend(rgba_bytes[y * row_bytes : (y + 1) * row_bytes])
    compressed = zlib.compress(bytes(raw))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", compressed)
        + chunk(b"IEND", b"")
    )


def render_arrow_photo(direction: str, size: int, color_hex: str) -> tk.PhotoImage:
    """
    Renders `assets/arrow_right.svg` or `assets/arrow_left.svg` with smooth analytical
    anti-aliasing and full alpha transparency (RGBA PNG).
    No background color baked in - seamlessly blends over normal, hover, and active states.
    """
    fg = _hex_to_rgb(color_hex)
    scale = size / 24.0
    half_stroke = 1.35 * scale

    if direction == "right":
        segments = [
            (4.0 * scale, 12.0 * scale, 20.0 * scale, 12.0 * scale),
            (12.5 * scale, 4.5 * scale, 20.0 * scale, 12.0 * scale),
            (12.5 * scale, 19.5 * scale, 20.0 * scale, 12.0 * scale),
        ]
    else:
        segments = [
            (20.0 * scale, 12.0 * scale, 4.0 * scale, 12.0 * scale),
            (11.5 * scale, 4.5 * scale, 4.0 * scale, 12.0 * scale),
            (11.5 * scale, 19.5 * scale, 4.0 * scale, 12.0 * scale),
        ]

    buf = bytearray(size * size * 4)
    for y in range(size):
        py = y + 0.5
        for x in range(size):
            px = x + 0.5
            d = min(_dist_to_segment(px, py, *seg) for seg in segments)
            alpha = max(0.0, min(1.0, (half_stroke + 0.5) - d))
            if alpha > 0.0:
                idx = (y * size + x) * 4
                buf[idx] = fg[0]
                buf[idx + 1] = fg[1]
                buf[idx + 2] = fg[2]
                buf[idx + 3] = int(alpha * 255 + 0.5)

    png_data = _rgba_to_png(size, size, buf)
    return tk.PhotoImage(data=png_data)


def render_radio_photo(selected: bool, size: int) -> tk.PhotoImage:
    """
    Renders an elegant, modern, anti-aliased radio button indicator with true alpha transparency.
    - Unselected: Crisp neutral border (#111111) with clean transparent center.
    - Selected: Smooth botanical green ring (#4C9E45) with vibrant green center dot (#4C9E45).
    """
    buf = bytearray(size * size * 4)
    cx = size / 2.0
    cy = size / 2.0
    r_outer = size * 0.42
    r_inner = size * 0.22

    for y in range(size):
        py = y + 0.5
        for x in range(size):
            px = x + 0.5
            d = math.hypot(px - cx, py - cy)
            border_alpha = max(0.0, min(1.0, (r_outer + 0.5) - d))
            if border_alpha <= 0.0:
                continue

            idx = (y * size + x) * 4
            if selected:
                # Center dot (#4C9E45)
                if d <= r_inner + 0.5:
                    dot_a = max(0.0, min(1.0, (r_inner + 0.5) - d))
                    buf[idx] = 76
                    buf[idx + 1] = 158
                    buf[idx + 2] = 69
                    buf[idx + 3] = int(dot_a * 255 + 0.5)
                # Outer ring (#4C9E45)
                elif d >= r_outer - 1.8:
                    ring_d = abs(d - (r_outer - 0.9))
                    ring_a = max(0.0, min(1.0, (0.9 + 0.5) - ring_d))
                    buf[idx] = 76
                    buf[idx + 1] = 158
                    buf[idx + 2] = 69
                    buf[idx + 3] = int(ring_a * 255 + 0.5)
            else:
                # Unselected neutral border (#111111)
                if d >= r_outer - 1.5:
                    ring_d = abs(d - (r_outer - 0.75))
                    ring_a = max(0.0, min(1.0, (0.75 + 0.5) - ring_d))
                    buf[idx] = 17
                    buf[idx + 1] = 17
                    buf[idx + 2] = 17
                    buf[idx + 3] = int(ring_a * 255 + 0.5)

    return tk.PhotoImage(data=_rgba_to_png(size, size, buf))


def render_help_photo(size: int, color_hex: str = "#444444") -> tk.PhotoImage:
    """
    Renders an anti-aliased dark gray '?' in a circular ring with full RGBA transparency.
    """
    fg = _hex_to_rgb(color_hex)
    scale = size / 24.0
    half_stroke = 1.35 * scale
    cx = size / 2.0
    cy = size / 2.0
    r_outer = size * 0.44

    segments = [
        (8.5 * scale, 9.0 * scale, 9.8 * scale, 7.5 * scale),
        (9.8 * scale, 7.5 * scale, 12.0 * scale, 6.8 * scale),
        (12.0 * scale, 6.8 * scale, 14.2 * scale, 7.5 * scale),
        (14.2 * scale, 7.5 * scale, 15.5 * scale, 9.0 * scale),
        (15.5 * scale, 9.0 * scale, 14.2 * scale, 11.2 * scale),
        (14.2 * scale, 11.2 * scale, 12.0 * scale, 12.8 * scale),
        (12.0 * scale, 12.8 * scale, 12.0 * scale, 14.8 * scale),
    ]
    dot_cx = 12.0 * scale
    dot_cy = 17.5 * scale
    dot_r = 1.3 * scale

    buf = bytearray(size * size * 4)
    for y in range(size):
        py = y + 0.5
        for x in range(size):
            px = x + 0.5
            d_center = math.hypot(px - cx, py - cy)
            ring_dist = abs(d_center - r_outer)
            ring_alpha = max(0.0, min(1.0, (half_stroke + 0.5) - ring_dist))

            q_dist = min(_dist_to_segment(px, py, *seg) for seg in segments)
            q_alpha = max(0.0, min(1.0, (half_stroke + 0.5) - q_dist))

            dot_dist = math.hypot(px - dot_cx, py - dot_cy)
            dot_alpha = max(0.0, min(1.0, (dot_r + 0.5) - dot_dist))

            final_alpha = max(ring_alpha, q_alpha, dot_alpha)
            if final_alpha > 0.0:
                idx = (y * size + x) * 4
                buf[idx] = fg[0]
                buf[idx + 1] = fg[1]
                buf[idx + 2] = fg[2]
                buf[idx + 3] = int(final_alpha * 255 + 0.5)

    return tk.PhotoImage(data=_rgba_to_png(size, size, buf))


def render_bug_photo(size: int, color_hex: str = "#444444") -> tk.PhotoImage:
    """
    Renders an anti-aliased dark gray bug icon with full RGBA transparency.
    """
    fg = _hex_to_rgb(color_hex)
    scale = size / 24.0
    half_stroke = 1.15 * scale

    segments = [
        # Antennae
        (8.0 * scale, 2.0 * scale, 9.9 * scale, 3.9 * scale),
        (16.0 * scale, 2.0 * scale, 14.1 * scale, 3.9 * scale),
        # Legs - top
        (5.0 * scale, 7.0 * scale, 8.0 * scale, 9.0 * scale),
        (19.0 * scale, 7.0 * scale, 16.0 * scale, 9.0 * scale),
        # Legs - mid
        (4.0 * scale, 13.0 * scale, 8.0 * scale, 13.0 * scale),
        (20.0 * scale, 13.0 * scale, 16.0 * scale, 13.0 * scale),
        # Legs - bottom
        (5.0 * scale, 19.0 * scale, 8.0 * scale, 17.0 * scale),
        (19.0 * scale, 19.0 * scale, 16.0 * scale, 17.0 * scale),
        # Center suture
        (12.0 * scale, 10.0 * scale, 12.0 * scale, 20.0 * scale),
        # Collar line
        (8.0 * scale, 10.0 * scale, 16.0 * scale, 10.0 * scale),
    ]

    rx = 4.0 * scale
    body_cx = 12.0 * scale
    top_cy = 10.0 * scale
    bot_cy = 16.0 * scale

    buf = bytearray(size * size * 4)
    for y in range(size):
        py = y + 0.5
        for x in range(size):
            px = x + 0.5

            seg_dist = min(_dist_to_segment(px, py, *seg) for seg in segments)

            clamped_y = max(top_cy, min(bot_cy, py))
            dist_to_core = math.hypot(px - body_cx, py - clamped_y)
            body_dist = abs(dist_to_core - rx)

            min_dist = min(seg_dist, body_dist)
            alpha = max(0.0, min(1.0, (half_stroke + 0.5) - min_dist))

            if alpha > 0.0:
                idx = (y * size + x) * 4
                buf[idx] = fg[0]
                buf[idx + 1] = fg[1]
                buf[idx + 2] = fg[2]
                buf[idx + 3] = int(alpha * 255 + 0.5)

    return tk.PhotoImage(data=_rgba_to_png(size, size, buf))


def render_checkbox_photo(checked: bool, size: int) -> tk.PhotoImage:
    """
    Renders an elegant, modern, anti-aliased checkbox indicator with true alpha transparency.
    - Unchecked: Crisp neutral rounded square border (#111111).
    - Checked: Filled botanical green rounded square (#4C9E45) with crisp white checkmark (#FFFFFF).
    """
    buf = bytearray(size * size * 4)
    scale = size / 24.0
    half_stroke = 1.35 * scale
    check_segs = [
        (6.5 * scale, 12.0 * scale, 10.2 * scale, 16.0 * scale),
        (10.2 * scale, 16.0 * scale, 17.5 * scale, 8.0 * scale),
    ]

    box_pad = 2.8 * scale
    box_r = 2.4 * scale

    for y in range(size):
        py = y + 0.5
        for x in range(size):
            px = x + 0.5
            idx = (y * size + x) * 4

            # Rounded rectangle distance
            dx = max(0.0, max(box_pad + box_r - px, px - (size - box_pad - box_r)))
            dy = max(0.0, max(box_pad + box_r - py, py - (size - box_pad - box_r)))
            corner_dist = math.hypot(dx, dy)
            in_rect = (
                px >= box_pad and px <= size - box_pad and py >= box_pad and py <= size - box_pad
            )
            box_alpha = (
                max(0.0, min(1.0, (box_r + 0.5) - corner_dist))
                if (dx > 0 and dy > 0)
                else (1.0 if in_rect else 0.0)
            )

            if box_alpha <= 0.0:
                continue

            if checked:
                # Filled green background (#4C9E45)
                r, g, b = 76, 158, 69
                d_c = min(_dist_to_segment(px, py, *seg) for seg in check_segs)
                check_a = max(0.0, min(1.0, (half_stroke + 0.5) - d_c))
                if check_a > 0.0:
                    r = int(76 * (1.0 - check_a) + 255 * check_a + 0.5)
                    g = int(158 * (1.0 - check_a) + 255 * check_a + 0.5)
                    b = int(69 * (1.0 - check_a) + 255 * check_a + 0.5)
                buf[idx] = r
                buf[idx + 1] = g
                buf[idx + 2] = b
                buf[idx + 3] = int(box_alpha * 255 + 0.5)
            else:
                # Neutral border (#111111)
                d_edge = min(
                    px - box_pad, (size - box_pad) - px, py - box_pad, (size - box_pad) - py
                )
                border_a = max(0.0, min(1.0, (1.5 * scale + 0.5) - d_edge))
                a = min(box_alpha, border_a)
                if a > 0.0:
                    buf[idx] = 17
                    buf[idx + 1] = 17
                    buf[idx + 2] = 17
                    buf[idx + 3] = int(a * 255 + 0.5)

    return tk.PhotoImage(data=_rgba_to_png(size, size, buf))


def render_check_circle_photo(
    size: int, bg_hex: str, circle_hex: str, check_hex: str
) -> tk.PhotoImage:
    """
    Renders `assets/check_circle.svg` (filled anti-aliased circle + rounded-cap checkmark)
    onto a tk.PhotoImage of `size x size` pixels.
    """
    bg = _hex_to_rgb(bg_hex)
    circle_rgb = _hex_to_rgb(circle_hex)
    check_rgb = _hex_to_rgb(check_hex)
    scale = size / 24.0
    cx = 12.0 * scale
    cy = 12.0 * scale
    radius = 9.8 * scale
    half_stroke = 1.25 * scale

    segments = [
        (7.4 * scale, 12.2 * scale, 10.6 * scale, 15.4 * scale),
        (10.6 * scale, 15.4 * scale, 16.8 * scale, 8.8 * scale),
    ]

    buf = bytearray()
    for y in range(size):
        py = y + 0.5
        for x in range(size):
            px = x + 0.5
            dist_center = math.hypot(px - cx, py - cy)
            circle_alpha = max(0.0, min(1.0, (radius + 0.5) - dist_center))
            pix = _blend_rgb(bg, circle_rgb, circle_alpha)

            if circle_alpha > 0.0:
                d_check = min(_dist_to_segment(px, py, *seg) for seg in segments)
                check_alpha = max(0.0, min(1.0, (half_stroke + 0.5) - d_check))
                if check_alpha > 0.0:
                    pix = _blend_rgb(pix, check_rgb, check_alpha)

            buf.extend(pix)

    header = f"P6\n{size} {size}\n255\n".encode("ascii")
    return tk.PhotoImage(data=header + bytes(buf))


def render_spinner_frame_photo(
    size: int, angle_deg: float, bg_hex: str, track_hex: str, arc_hex: str
) -> tk.PhotoImage:
    """
    Renders a single anti-aliased circular spinner frame onto a tk.PhotoImage.
    """
    bg = _hex_to_rgb(bg_hex)
    track_rgb = _hex_to_rgb(track_hex)
    arc_rgb = _hex_to_rgb(arc_hex)
    scale = size / 24.0
    cx = 12.0 * scale
    cy = 12.0 * scale
    radius = 8.5 * scale
    half_stroke = 1.35 * scale
    start_rad = math.radians(angle_deg % 360.0)
    sweep = math.radians(240.0)

    buf = bytearray()
    for y in range(size):
        py = y + 0.5
        for x in range(size):
            px = x + 0.5
            dx = px - cx
            dy = py - cy
            dist_ring = abs(math.hypot(dx, dy) - radius)
            ring_alpha = max(0.0, min(1.0, (half_stroke + 0.5) - dist_ring))
            if ring_alpha <= 0.0:
                buf.extend(bg)
                continue

            theta = math.atan2(-dy, dx) % (2.0 * math.pi)
            rel = (theta - start_rad) % (2.0 * math.pi)
            color = arc_rgb if rel <= sweep else track_rgb
            buf.extend(_blend_rgb(bg, color, ring_alpha))

    header = f"P6\n{size} {size}\n255\n".encode("ascii")
    return tk.PhotoImage(data=header + bytes(buf))


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
    """Enables native Per-Monitor High-DPI rendering and Windows taskbar process identity."""
    if sys.platform.startswith("win"):
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "barcoid.dna.validator.0.1.0"
            )
        except Exception:
            pass
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


class ModernScrollbar(tk.Canvas):
    """
    Clean, flat, high-contrast scrollbar slider (#FFFFFF track + #4C9E45 thumb)
    replacing Tkinter's legacy Windows 95 gray/beige scrollbar.
    """

    def __init__(
        self,
        parent: tk.Widget,
        orient: str = "vertical",
        command: Optional[Callable[..., Any]] = None,
        thickness: int = 14,
    ):
        self.orient = orient
        self.command = command
        width = thickness if orient == "vertical" else 100
        height = 100 if orient == "vertical" else thickness
        super().__init__(
            parent,
            width=width,
            height=height,
            bg=PALETTE["card_inner"],
            highlightbackground=PALETTE["border"],
            highlightthickness=1,
            bd=0,
        )
        self.first = 0.0
        self.last = 1.0
        self.hover = False
        self.dragging = False
        self.drag_start_coord = 0
        self.drag_start_first = 0.0

        self.bind("<Configure>", lambda _e: self._redraw())
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)

    def set(self, first: Any, last: Any):
        """Standard Tkinter scrollbar callback invoked by scrollable widgets."""
        try:
            self.first = max(0.0, min(1.0, float(first)))
            self.last = max(0.0, min(1.0, float(last)))
        except ValueError:
            self.first, self.last = 0.0, 1.0
        self._redraw()

    def _redraw(self):
        self.delete("all")
        w = max(1, self.winfo_width())
        h = max(1, self.winfo_height())

        span = self.last - self.first
        thumb_color = (
            PALETTE["primary_hover"] if (self.hover or self.dragging) else PALETTE["primary"]
        )
        if span >= 0.999:
            thumb_color = PALETTE["primary_tint"]

        pad = 2
        if self.orient == "vertical":
            track_len = max(1, h - 2 * pad)
            y0 = pad + int(self.first * track_len)
            y1 = pad + max(y0 - pad + 24, int(self.last * track_len))
            y1 = min(h - pad, y1)
            self.create_rectangle(pad, y0, w - pad, y1, fill=thumb_color, outline="")
        else:
            track_len = max(1, w - 2 * pad)
            x0 = pad + int(self.first * track_len)
            x1 = pad + max(x0 - pad + 24, int(self.last * track_len))
            x1 = min(w - pad, x1)
            self.create_rectangle(x0, pad, x1, h - pad, fill=thumb_color, outline="")

    def _on_enter(self, _event):
        self.hover = True
        self._redraw()

    def _on_leave(self, _event):
        self.hover = False
        self._redraw()

    def _on_press(self, event):
        if not self.command:
            return
        w = max(1, self.winfo_width())
        h = max(1, self.winfo_height())
        coord = event.y if self.orient == "vertical" else event.x
        track_len = max(1, h if self.orient == "vertical" else w)
        click_frac = coord / track_len

        if self.first <= click_frac <= self.last:
            self.dragging = True
            self.drag_start_coord = coord
            self.drag_start_first = self.first
        else:
            span = self.last - self.first
            target = max(0.0, min(1.0 - span, click_frac - span / 2.0))
            self.command("moveto", target)
        self._redraw()

    def _on_drag(self, event):
        if not self.dragging or not self.command:
            return
        w = max(1, self.winfo_width())
        h = max(1, self.winfo_height())
        coord = event.y if self.orient == "vertical" else event.x
        track_len = max(1, h if self.orient == "vertical" else w)
        delta_frac = (coord - self.drag_start_coord) / track_len
        span = self.last - self.first
        target = max(0.0, min(1.0 - span, self.drag_start_first + delta_frac))
        self.command("moveto", target)

    def _on_release(self, _event):
        self.dragging = False
        self._redraw()


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
    skip_ncbi: bool = False,
    enable_preliminary_results: bool = True,
    preliminary_interval: int = 50,
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
        skip_ncbi=skip_ncbi,
        enable_preliminary_results=enable_preliminary_results,
        preliminary_interval=preliminary_interval,
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
        self._apply_app_icon()
        self._maximize_window()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close_window)

        # Font measurement helpers for cell truncation & Excel-style auto-fit
        self.tk_font_body = tkfont.Font(root=self.root, font=FONT_BODY)
        self.tk_font_heading = tkfont.Font(root=self.root, font=FONT_HEADING)

        # Logo image for brand header (48x48 or 96x96 on high-DPI)
        self.logo_photo: Optional[tk.PhotoImage] = None
        if PNG_ICON_PATH.exists():
            try:
                self.logo_photo = tk.PhotoImage(file=str(PNG_ICON_PATH))
            except Exception:
                self.logo_photo = None

        # Pre-render anti-aliased SVG icons (arrows, check-circle, and spinner frames)
        self._init_svg_icons()

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
        self.skip_ncbi_var = tk.BooleanVar(value=False)
        self.enable_preliminary_var = tk.BooleanVar(value=True)
        self.preliminary_interval_var = tk.StringVar(value="50")
        self.eta_var = tk.StringVar(value="")
        self.preliminary_rows: List[Dict[str, Any]] = []
        self.preliminary_xlsx_path: Optional[Path] = None

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

        # Execution, Spinner Animation, Results Table & Diagnostics state
        self.is_running = False
        self.spinner_frame_idx = 0
        self.service_states: Dict[str, str] = {
            "morpho": "Idle",
            "bold": "Idle",
            "ncbi": "Idle",
            "gbif": "Idle",
        }
        self.last_results_rows: List[Dict[str, Any]] = []
        self.results_matrix: List[List[str]] = []
        self.results_col_widths: List[int] = self._default_results_col_widths()
        self._resizing_col_idx: Optional[int] = None
        self._resize_start_x: int = 0
        self._resize_start_w: int = 0

        # Summary metric card StringVars (plus legacy summary_var for backward compatibility)
        self.summary_var = tk.StringVar(value="Total: 0")
        self.summary_card_vars: Dict[str, tk.StringVar] = {
            "TOTAL": tk.StringVar(value="0"),
            "CONCORDANT": tk.StringVar(value="0"),
            "NEW_ASSIGNMENT": tk.StringVar(value="0"),
            "MISMATCH_ALERT": tk.StringVar(value="0"),
            "NO_MATCH": tk.StringVar(value="0"),
        }
        self.summary_cards: Dict[str, Tuple[tk.Frame, tk.Label, tk.Label]] = {}

        self.last_excel_path: Optional[Path] = None
        self.last_error_trace: str = ""
        self.log_history: List[str] = []
        self.log_queue: "queue.Queue[str]" = queue.Queue()
        self.ui_queue: "queue.Queue[Tuple[str, Any]]" = queue.Queue()
        self.terminal_win: Optional[tk.Toplevel] = None
        self.terminal_text: Optional[tk.Text] = None
        self.guide_win: Optional[tk.Toplevel] = None

        self._configure_styles()
        self._build_layout()
        self._bind_shortcuts()
        self._attach_logging()
        self.show_step(0)
        self._poll_queues()
        self._animate_spinners()

    def _apply_app_icon(self):
        """Sets the application window icon using multi-resolution crisp PhotoImages (iconphoto)
        and falls back to ICO / logo_48.png."""
        self._app_icon_refs: List[tk.PhotoImage] = []
        try:
            # Multi-resolution iconphoto gives crystal-clear icons in both the
            # window title bar (16x16 / 20x20 / 24x24) and taskbar / Alt-Tab (32x32 / 48x48 / 64x64)
            # without blurry GDI nearest-neighbor downscaling.
            sizes = [16, 20, 24, 32, 40, 48, 64, 96, 128, 256]
            photos: List[tk.PhotoImage] = []
            for sz in sizes:
                icon_path = ASSETS_DIR / f"icon_{sz}.png"
                if icon_path.exists():
                    try:
                        photos.append(tk.PhotoImage(file=str(icon_path)))
                    except Exception:
                        pass
            if photos:
                self.root.iconphoto(True, *photos)
                self._app_icon_refs = photos
                return
        except Exception:
            pass

        # Fallback to single PNG or ICO if multi-resolution PNGs are not present
        try:
            if PNG_ICON_PATH.exists():
                icon_img = tk.PhotoImage(file=str(PNG_ICON_PATH))
                self.root.iconphoto(True, icon_img)
                self._app_icon_refs = [icon_img]
            elif ICO_ICON_PATH.exists() and sys.platform.startswith("win"):
                self.root.iconbitmap(str(ICO_ICON_PATH))
        except Exception:
            pass

    def _maximize_window(self):
        """Maximizes the application window on startup while keeping standard window controls."""
        try:
            if sys.platform.startswith("win"):
                self.root.state("zoomed")
            else:
                self.root.attributes("-zoomed", True)
        except Exception:
            pass

    def _on_close_window(self):
        """Warns the user before exiting if an identification run is currently in progress."""
        if self.is_running:
            confirm = messagebox.askyesno(
                "Run in Progress",
                "An identification run is currently in progress.\n\n"
                "Are you sure you want to stop the run and exit BarcoID?\n"
                "Completed sequences are safely cached and preserved, but unfinished sequences will be aborted.",
                icon="warning",
                parent=self.root,
            )
            if not confirm:
                return
        self.root.destroy()

    def _apply_dpi_scaling(self):
        """Synchronizes Tkinter's internal font/widget scaling factor with the monitor DPI."""
        try:
            dpi = self.root.winfo_fpixels("1i")
            scale = max(1.0, float(dpi) / 72.0)
            self.root.tk.call("tk", "scaling", scale)
            self.dpi_scale = float(dpi) / 96.0
        except Exception:
            self.dpi_scale = 1.0

    def _init_svg_icons(self):
        """Pre-renders smooth anti-aliased PhotoImages for the SVG arrow, radio, check-circle, and spinner icons."""
        # 30% larger arrows with true alpha transparency (seamless blend on hover/click)
        arrow_sz = max(24, int(24 * self.dpi_scale))
        badge_sz = max(22, int(22 * self.dpi_scale))
        radio_sz = max(20, int(20 * self.dpi_scale))
        help_sz = max(24, int(24 * self.dpi_scale))
        self.badge_px = badge_sz

        self.icon_arrow_right = render_arrow_photo("right", arrow_sz, "#FFFFFF")
        self.icon_arrow_left = render_arrow_photo("left", arrow_sz, PALETTE["text_dark"])
        self.icon_radio_unselected = render_radio_photo(False, radio_sz)
        self.icon_radio_selected = render_radio_photo(True, radio_sz)
        self.icon_check_unselected = render_checkbox_photo(False, radio_sz)
        self.icon_check_selected = render_checkbox_photo(True, radio_sz)
        self.icon_help = render_help_photo(help_sz, "#444444")
        self.icon_bug = render_bug_photo(help_sz, "#444444")
        self.icon_check_done = render_check_circle_photo(
            badge_sz, PALETTE["primary_tint"], PALETTE["primary"], "#FFFFFF"
        )
        self.spinner_photos: List[tk.PhotoImage] = [
            render_spinner_frame_photo(
                badge_sz, angle, PALETTE["primary"], PALETTE["primary_hover"], "#FFFFFF"
            )
            for angle in range(0, 360, 24)
        ]

    def _default_results_col_widths(self) -> List[int]:
        """
        Returns initial widths for Step 4 columns:
        - Sample_ID, Consensus_Species, Concordance_Status, QC_Flag are wide & fully visible.
        - Intermediate columns in between start squished (~58px scaled) so key columns fit on screen.
        """
        squished_w = max(56, int(58 * self.dpi_scale))
        expanded_map = {
            "Sample_ID": max(220, int(220 * self.dpi_scale)),
            "Consensus_Species": max(210, int(210 * self.dpi_scale)),
            "Concordance_Status": max(190, int(190 * self.dpi_scale)),
            "QC_Flag": max(195, int(195 * self.dpi_scale)),
        }
        return [expanded_map.get(col, squished_w) for col in RESULTS_COLUMNS]

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
        canvas.create_oval(
            2, 2, 46, 46, fill=PALETTE["primary_tint"], outline=PALETTE["primary"], width=2
        )

        canvas.create_line(
            9,
            12,
            20,
            13,
            25,
            31,
            33,
            24,
            40,
            24,
            fill=PALETTE["text_dark"],
            width=2.4,
            smooth=True,
            capstyle="round",
        )
        canvas.create_line(
            9,
            36,
            20,
            35,
            25,
            17,
            33,
            24,
            40,
            24,
            fill=PALETTE["text_dark"],
            width=2.4,
            smooth=True,
            capstyle="round",
        )
        canvas.create_line(
            9,
            20,
            19,
            20,
            25,
            15,
            31,
            24,
            40,
            24,
            fill=PALETTE["primary"],
            width=2.8,
            smooth=True,
            capstyle="round",
        )
        canvas.create_line(
            9,
            28,
            19,
            28,
            25,
            33,
            31,
            24,
            40,
            24,
            fill=PALETTE["primary"],
            width=2.8,
            smooth=True,
            capstyle="round",
        )

        for y_pos, col in [
            (12, PALETTE["text_dark"]),
            (20, PALETTE["primary"]),
            (28, PALETTE["primary"]),
            (36, PALETTE["text_dark"]),
        ]:
            canvas.create_oval(6.5, y_pos - 2.5, 11.5, y_pos + 2.5, fill=col, outline="")

        canvas.create_oval(
            22.5, 20.5, 29.5, 27.5, fill=PALETTE["card_inner"], outline=PALETTE["primary"], width=2
        )
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

        if self.logo_photo:
            logo_lbl = tk.Label(
                brand_frame, image=self.logo_photo, bg=PALETTE["card_inner"], highlightthickness=0
            )
            logo_lbl.pack(side="left", padx=(0, 10))
        else:
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

        # Small 'Made by SidloCZ' tag positioned immediately to the left of the '?' Help Button
        self.author_tag = tk.Label(
            stepper_frame,
            text="Made by SidloCZ",
            font=FONT_SMALL,
            fg="#888888",
            bg=PALETTE["card_inner"],
            cursor="hand2",
        )
        self.author_tag.pack(side="left", padx=(0, 10))

        def _open_author_github(_event=None):
            webbrowser.open_new_tab("https://github.com/SidloCZ")

        def _on_author_enter(_event=None):
            self.author_tag.configure(fg=PALETTE["primary"], font=("Segoe UI", 9, "underline"))

        def _on_author_leave(_event=None):
            self.author_tag.configure(fg="#888888", font=FONT_SMALL)

        self.author_tag.bind("<Button-1>", _open_author_github)
        self.author_tag.bind("<Enter>", _on_author_enter)
        self.author_tag.bind("<Leave>", _on_author_leave)

        # Bug SVG Icon Button positioned immediately to the left of the '?' Help Button
        self.bug_btn = tk.Button(
            stepper_frame,
            image=self.icon_bug,
            command=self.open_terminal_window,
            bg=PALETTE["card_inner"],
            activebackground=PALETTE["primary_tint"],
            relief="flat",
            bd=0,
            highlightthickness=0,
            cursor="hand2",
            padx=4,
            pady=4,
        )
        self.bug_btn.pack(side="left", padx=(0, 6))

        def _on_bug_enter(_event=None):
            self.bug_btn.configure(bg=PALETTE["primary_tint"])

        def _on_bug_leave(_event=None):
            self.bug_btn.configure(bg=PALETTE["card_inner"])

        self.bug_btn.bind("<Enter>", _on_bug_enter)
        self.bug_btn.bind("<Leave>", _on_bug_leave)

        # Dark Gray '?' SVG Help Button positioned immediately to the left of Step 1 button
        self.help_btn = tk.Button(
            stepper_frame,
            image=self.icon_help,
            command=self.open_guide_window,
            bg=PALETTE["card_inner"],
            activebackground=PALETTE["primary_tint"],
            relief="flat",
            bd=0,
            highlightthickness=0,
            cursor="hand2",
            padx=4,
            pady=4,
        )
        self.help_btn.pack(side="left", padx=(0, 10))

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
                highlightthickness=0,
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
            form,
            text="Input FASTA File:",
            font=FONT_HEADING,
            fg=PALETTE["text_dark"],
            bg=PALETTE["card_inner"],
        ).grid(row=0, column=0, sticky="w", padx=(0, 14), pady=8)

        tk.Entry(
            form,
            textvariable=self.fasta_var,
            font=FONT_BODY,
            bg=PALETTE["card_inner"],
            fg=PALETTE["text_dark"],
            relief="solid",
            bd=1,
        ).grid(row=0, column=1, sticky="ew", padx=(0, 10), pady=8, ipady=6)

        self._make_button(form, "Browse FASTA", self.browse_fasta, primary=True).grid(
            row=0, column=2, sticky="ew", pady=8
        )

        # Output Folder
        tk.Label(
            form,
            text="Output Folder:",
            font=FONT_HEADING,
            fg=PALETTE["text_dark"],
            bg=PALETTE["card_inner"],
        ).grid(row=1, column=0, sticky="w", padx=(0, 14), pady=8)

        tk.Entry(
            form,
            textvariable=self.output_dir_var,
            font=FONT_BODY,
            bg=PALETTE["card_inner"],
            fg=PALETTE["text_dark"],
            relief="solid",
            bd=1,
        ).grid(row=1, column=1, sticky="ew", padx=(0, 10), pady=8, ipady=6)

        self._make_button(form, "Browse Folder", self.browse_output_dir, primary=False).grid(
            row=1, column=2, sticky="ew", pady=8
        )

        # Target Taxon
        tk.Label(
            form,
            text="Target Taxon Filter:",
            font=FONT_HEADING,
            fg=PALETTE["text_dark"],
            bg=PALETTE["card_inner"],
        ).grid(row=2, column=0, sticky="w", padx=(0, 14), pady=8)

        taxon_row = tk.Frame(form, bg=PALETTE["card_inner"])
        taxon_row.grid(row=2, column=1, columnspan=2, sticky="ew", pady=8)

        taxon_combo = ttk.Combobox(
            taxon_row,
            textvariable=self.taxon_var,
            values=[
                "Formicidae",
                "Hymenoptera",
                "Insecta",
                "Arthropoda",
                "Animalia",
                "Fungi",
                "Plantae",
            ],
            width=20,
            font=FONT_BODY,
        )
        taxon_combo.pack(side="left", padx=(0, 20))

        tk.Label(
            taxon_row,
            text="Max Sequences (optional):",
            font=FONT_HEADING,
            fg=PALETTE["text_dark"],
            bg=PALETTE["card_inner"],
        ).pack(side="left", padx=(0, 8))

        tk.Entry(
            taxon_row,
            textvariable=self.max_seq_var,
            width=10,
            font=FONT_BODY,
            bg=PALETTE["card_inner"],
            fg=PALETTE["text_dark"],
            relief="solid",
            bd=1,
        ).pack(side="left", ipady=4)

        # Checkboxes
        flags_row = tk.Frame(form, bg=PALETTE["card_inner"])
        flags_row.grid(row=3, column=1, columnspan=2, sticky="w", pady=8)

        tk.Checkbutton(
            flags_row,
            text="  Dry Run (inspect cache only)",
            variable=self.dry_run_var,
            image=self.icon_check_unselected,
            selectimage=self.icon_check_selected,
            indicatoron=False,
            compound="left",
            relief="flat",
            bd=0,
            highlightthickness=0,
            bg=PALETTE["card_inner"],
            fg=PALETTE["text_dark"],
            activebackground=PALETTE["card_inner"],
            activeforeground=PALETTE["text_dark"],
            font=FONT_BODY,
            cursor="hand2",
        ).pack(side="left", padx=(0, 24))

        tk.Checkbutton(
            flags_row,
            text="  Force Refresh (bypass disk cache)",
            variable=self.force_refresh_var,
            image=self.icon_check_unselected,
            selectimage=self.icon_check_selected,
            indicatoron=False,
            compound="left",
            relief="flat",
            bd=0,
            highlightthickness=0,
            bg=PALETTE["card_inner"],
            fg=PALETTE["text_dark"],
            activebackground=PALETTE["card_inner"],
            activeforeground=PALETTE["text_dark"],
            font=FONT_BODY,
            cursor="hand2",
        ).pack(side="left", padx=(0, 24))

        tk.Checkbutton(
            flags_row,
            text="  Skip NCBI BLAST (BOLD + Morpho only)",
            variable=self.skip_ncbi_var,
            image=self.icon_check_unselected,
            selectimage=self.icon_check_selected,
            indicatoron=False,
            compound="left",
            relief="flat",
            bd=0,
            highlightthickness=0,
            bg=PALETTE["card_inner"],
            fg=PALETTE["text_dark"],
            activebackground=PALETTE["card_inner"],
            activeforeground=PALETTE["text_dark"],
            font=FONT_BODY,
            cursor="hand2",
        ).pack(side="left")

        # Footer Navigation (with anti-aliased SVG arrow icon)
        footer1 = tk.Frame(page, bg=PALETTE["card_inner"])
        footer1.pack(side="bottom", fill="x", pady=(16, 0))

        self._make_button(
            footer1,
            "Next: Metadata Column  ",
            lambda: self.show_step(1),
            primary=True,
            arrow="right",
        ).pack(side="right")

    # ------------------------------------------------------------------
    # STEP 2: INTERACTIVE METADATA VIEWER & COLUMN PICKER (with ModernScrollbar)
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
            top_controls,
            "Choose Metadata File (.csv / .tsv / .xlsx)",
            self.browse_metadata,
            primary=True,
        ).pack(side="left", padx=(0, 8))

        self._make_button(top_controls, "Clear Metadata", self.clear_metadata, primary=False).pack(
            side="left"
        )

        mode_box = tk.Frame(top_controls, bg=PALETTE["card_inner"])
        mode_box.pack(side="right")
        tk.Label(
            mode_box,
            text="Header Click Sets:",
            font=FONT_HEADING,
            fg=PALETTE["text_dark"],
            bg=PALETTE["card_inner"],
        ).pack(side="left", padx=(0, 10))
        tk.Radiobutton(
            mode_box,
            text="  Morphospecies",
            variable=self.click_target_var,
            value="morpho",
            image=self.icon_radio_unselected,
            selectimage=self.icon_radio_selected,
            indicatoron=False,
            compound="left",
            relief="flat",
            bd=0,
            highlightthickness=0,
            bg=PALETTE["card_inner"],
            fg=PALETTE["text_dark"],
            activebackground=PALETTE["card_inner"],
            activeforeground=PALETTE["text_dark"],
            font=FONT_BODY,
            cursor="hand2",
        ).pack(side="left", padx=(0, 14))
        tk.Radiobutton(
            mode_box,
            text="  Sample ID",
            variable=self.click_target_var,
            value="sample",
            image=self.icon_radio_unselected,
            selectimage=self.icon_radio_selected,
            indicatoron=False,
            compound="left",
            relief="flat",
            bd=0,
            highlightthickness=0,
            bg=PALETTE["card_inner"],
            fg=PALETTE["text_dark"],
            activebackground=PALETTE["card_inner"],
            activeforeground=PALETTE["text_dark"],
            font=FONT_BODY,
            cursor="hand2",
        ).pack(side="left")

        # Row 2 of Toolbar: Elastic 4-Column Grid for Morphospecies Column & Sample ID Column
        col_selectors = tk.Frame(page, bg=PALETTE["card_inner"])
        col_selectors.pack(fill="x", pady=(0, 10))
        col_selectors.columnconfigure(1, weight=1)
        col_selectors.columnconfigure(3, weight=1)

        tk.Label(
            col_selectors,
            text="Morphospecies Column:",
            font=FONT_HEADING,
            fg=PALETTE["text_dark"],
            bg=PALETTE["card_inner"],
        ).grid(row=0, column=0, sticky="w", padx=(0, 8), pady=2)

        self.morpho_combo = ttk.Combobox(
            col_selectors, textvariable=self.morpho_col_var, state="readonly", font=FONT_BODY
        )
        self.morpho_combo.grid(row=0, column=1, sticky="ew", padx=(0, 20), pady=2)
        self.morpho_combo.bind("<<ComboboxSelected>>", lambda _e: self._refresh_column_badges())

        tk.Label(
            col_selectors,
            text="Sample ID Column:",
            font=FONT_HEADING,
            fg=PALETTE["text_dark"],
            bg=PALETTE["card_inner"],
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

        # Footer Navigation (with SVG arrow icons)
        footer2 = tk.Frame(page, bg=PALETTE["card_inner"])
        footer2.pack(side="bottom", fill="x", pady=(12, 0))

        self._make_button(
            footer2, "  Back: Sequences", lambda: self.show_step(0), primary=False, arrow="left"
        ).pack(side="left")

        self._make_button(
            footer2, "Next: Run  ", lambda: self.show_step(2), primary=True, arrow="right"
        ).pack(side="right")

        # Interactive Spreadsheet Preview Table with ModernScrollbars
        table_wrap = tk.Frame(
            page,
            bg=PALETTE["card_inner"],
            highlightbackground=PALETTE["border"],
            highlightthickness=1,
        )
        table_wrap.pack(fill="both", expand=True)

        self.meta_tree = ttk.Treeview(table_wrap, show="headings")
        vsb = ModernScrollbar(table_wrap, orient="vertical", command=self.meta_tree.yview)
        hsb = ModernScrollbar(table_wrap, orient="horizontal", command=self.meta_tree.xview)
        self.meta_tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.meta_tree.bind("<Double-Button-1>", self._on_meta_tree_double_click)

        self.meta_tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        table_wrap.rowconfigure(0, weight=1)
        table_wrap.columnconfigure(0, weight=1)

    def _on_meta_tree_double_click(self, event):
        """Excel-style double-click auto-fit on Step 2 Metadata table columns."""
        region = self.meta_tree.identify_region(event.x, event.y)
        if region in ("separator", "heading"):
            col_id = self.meta_tree.identify_column(event.x)
            if col_id and col_id.startswith("#"):
                idx = int(col_id[1:]) - 1
                if 0 <= idx < len(self.meta_columns):
                    col_name = self.meta_columns[idx]
                    heading_txt = self.meta_tree.heading(col_name, "text")
                    max_px = self.tk_font_heading.measure(heading_txt) + 28
                    for r in self.meta_rows:
                        if idx < len(r):
                            w = self.tk_font_body.measure(str(r[idx])) + 24
                            if w > max_px:
                                max_px = w
                    self.meta_tree.column(col_name, width=max_px)

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

        # 4 Evidence Stream Cards in a Responsive 2x2 Grid
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
                card,
                text=title,
                font=FONT_HEADING,
                fg=PALETTE["text_dark"],
                bg=PALETTE["card_inner"],
            )
            t_lbl.pack(side="left")

            s_lbl = tk.Label(
                card,
                text="Idle",
                font=FONT_HEADING,
                fg=PALETTE["text_dark"],
                bg=PALETTE["card_inner"],
            )
            s_lbl.pack(side="right")

            spin_canvas = tk.Canvas(
                card,
                width=self.badge_px,
                height=self.badge_px,
                bg=PALETTE["card_inner"],
                highlightthickness=0,
            )
            spin_canvas.pack(side="right", padx=(6, 6))

            self.service_cards[key] = card
            self.service_titles[key] = t_lbl
            self.service_labels[key] = s_lbl
            self.service_spinners[key] = spin_canvas

        # Progressive preliminary export options in Step 3
        prelim_opts = tk.Frame(page, bg=PALETTE["card_inner"])
        prelim_opts.pack(fill="x", pady=(0, 10))

        tk.Checkbutton(
            prelim_opts,
            text="  Save preliminary results every",
            variable=self.enable_preliminary_var,
            image=self.icon_check_unselected,
            selectimage=self.icon_check_selected,
            indicatoron=False,
            compound="left",
            relief="flat",
            bd=0,
            highlightthickness=0,
            bg=PALETTE["card_inner"],
            fg=PALETTE["text_dark"],
            activebackground=PALETTE["card_inner"],
            activeforeground=PALETTE["text_dark"],
            font=FONT_BODY,
            cursor="hand2",
        ).pack(side="left")

        self.interval_combo = ttk.Combobox(
            prelim_opts,
            textvariable=self.preliminary_interval_var,
            values=["25", "50", "100", "200"],
            width=5,
            state="readonly",
            font=FONT_BODY,
        )
        self.interval_combo.pack(side="left", padx=(6, 6))

        tk.Label(
            prelim_opts,
            text="sequences (uncheck for very large datasets to minimize disk writes)",
            font=FONT_BODY,
            fg=PALETTE["text_dark"],
            bg=PALETTE["card_inner"],
        ).pack(side="left")

        # Run Button + Progress Bar + Dynamic ETA
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
            prog_wrap,
            textvariable=self.stage_var,
            font=FONT_HEADING,
            fg=PALETTE["text_dark"],
            bg=PALETTE["card_inner"],
            anchor="w",
        ).pack(fill="x")

        self.progress_var = tk.DoubleVar(value=0.0)
        self.progress_bar = ttk.Progressbar(
            prog_wrap,
            variable=self.progress_var,
            maximum=100.0,
            style="Green.Horizontal.TProgressbar",
        )
        self.progress_bar.pack(fill="x", pady=(6, 0))

        self.eta_label = tk.Label(
            prog_wrap,
            textvariable=self.eta_var,
            font=FONT_BODY,
            fg=PALETTE["text_dark"],
            bg=PALETTE["card_inner"],
            anchor="w",
        )
        self.eta_label.pack(fill="x", pady=(4, 0))

        # Footer Navigation (with SVG arrow icons)
        footer3 = tk.Frame(page, bg=PALETTE["card_inner"])
        footer3.pack(side="bottom", fill="x", pady=(12, 0))

        self._make_button(
            footer3,
            "  Back: Metadata Column",
            lambda: self.show_step(1),
            primary=False,
            arrow="left",
        ).pack(side="left")

        self.to_results_btn = self._make_button(
            footer3, "Next: Results  ", lambda: self.show_step(3), primary=True, arrow="right"
        )
        self.to_results_btn.pack(side="right")

        self.preliminary_btn = self._make_button(
            footer3,
            "Check Preliminary Results  ",
            self._view_preliminary_results,
            primary=False,
            arrow="right",
        )

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
    # STEP 4: RESULTS (Segmented Summary Cards + Interactive Resizable Table)
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

        # Top Action & Hint Bar
        res_bar = tk.Frame(page, bg=PALETTE["card_inner"])
        res_bar.pack(fill="x", pady=(0, 10))

        self.open_excel_btn = self._make_button(
            res_bar, "Open Excel Report", self.open_last_excel, primary=True
        )
        self.open_excel_btn.pack(side="left", padx=(0, 10))

        self.open_folder_btn = self._make_button(
            res_bar, "Open Results Folder", self.open_output_folder, primary=False
        )
        self.open_folder_btn.pack(side="left", padx=(0, 10))

        self._make_button(
            res_bar, "Reset Column Widths", self.reset_results_column_widths, primary=False
        ).pack(side="left")

        tk.Label(
            res_bar,
            text="Double-click any column header or drag borders to expand/resize columns.",
            font=FONT_BODY,
            fg=PALETTE["text_dark"],
            bg=PALETTE["card_inner"],
        ).pack(side="right")

        # Segmented Concordance Summary Cards (5 distinct boxes instead of '|' pipes)
        summary_grid = tk.Frame(page, bg=PALETTE["card_inner"])
        summary_grid.pack(fill="x", pady=(0, 12))

        summary_defs = [
            ("TOTAL", "Total Sequences"),
            ("CONCORDANT", "Concordant"),
            ("NEW_ASSIGNMENT", "New Assignment"),
            ("MISMATCH_ALERT", "Mismatch Alert"),
            ("NO_MATCH", "No Match"),
        ]
        for idx, (key, label_text) in enumerate(summary_defs):
            summary_grid.columnconfigure(idx, weight=1)
            bg_init = PALETTE["primary_tint"] if key == "TOTAL" else PALETTE["card_inner"]
            border_init = PALETTE["primary"] if key == "TOTAL" else PALETTE["border"]
            card = tk.Frame(
                summary_grid,
                bg=bg_init,
                highlightbackground=border_init,
                highlightthickness=1,
                padx=14,
                pady=8,
            )
            card.grid(row=0, column=idx, sticky="ew", padx=(0 if idx == 0 else 8, 0))
            title_lbl = tk.Label(
                card, text=label_text, font=FONT_BODY, fg=PALETTE["text_dark"], bg=bg_init
            )
            title_lbl.pack(side="left")
            val_lbl = tk.Label(
                card,
                textvariable=self.summary_card_vars[key],
                font=FONT_HEADING,
                fg=PALETTE["text_dark"],
                bg=bg_init,
            )
            val_lbl.pack(side="right")
            self.summary_cards[key] = (card, title_lbl, val_lbl)

        # Footer Navigation (with SVG arrow icon)
        footer4 = tk.Frame(page, bg=PALETTE["card_inner"])
        footer4.pack(side="bottom", fill="x", pady=(12, 0))

        self.back_to_run_btn = self._make_button(
            footer4, "  Back: Run", lambda: self.show_step(2), primary=False, arrow="left"
        )
        self.back_to_run_btn.pack(side="left")

        # Scrollable Canvas Grid with ModernScrollbars
        grid_wrap = tk.Frame(
            page,
            bg=PALETTE["card_inner"],
            highlightbackground=PALETTE["border"],
            highlightthickness=1,
        )
        grid_wrap.pack(fill="both", expand=True)

        self.results_canvas = tk.Canvas(grid_wrap, bg=PALETTE["card_inner"], highlightthickness=0)
        res_vsb = ModernScrollbar(grid_wrap, orient="vertical", command=self.results_canvas.yview)
        res_hsb = ModernScrollbar(grid_wrap, orient="horizontal", command=self.results_canvas.xview)
        self.results_canvas.configure(yscrollcommand=res_vsb.set, xscrollcommand=res_hsb.set)

        self.results_canvas.grid(row=0, column=0, sticky="nsew")
        res_vsb.grid(row=0, column=1, sticky="ns")
        res_hsb.grid(row=1, column=0, sticky="ew")
        grid_wrap.rowconfigure(0, weight=1)
        grid_wrap.columnconfigure(0, weight=1)

        self.results_canvas.bind("<Motion>", self._on_results_motion)
        self.results_canvas.bind("<ButtonPress-1>", self._on_results_press)
        self.results_canvas.bind("<B1-Motion>", self._on_results_drag)
        self.results_canvas.bind("<ButtonRelease-1>", self._on_results_release)
        self.results_canvas.bind("<Double-Button-1>", self._on_results_double_click)
        self.results_canvas.bind(
            "<MouseWheel>",
            lambda e: self.results_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"),
        )

        self.populate_results_table([])

    def _update_summary_cards(self, total: int, counts: Dict[str, int]):
        """Updates the 5 segmented summary cards in Step 4 and highlights non-zero counts."""
        self.summary_card_vars["TOTAL"].set(str(total))
        for key in ("CONCORDANT", "NEW_ASSIGNMENT", "MISMATCH_ALERT", "NO_MATCH"):
            val = counts.get(key, 0)
            self.summary_card_vars[key].set(str(val))
            card, t_lbl, v_lbl = self.summary_cards[key]
            if val > 0 and key == "CONCORDANT":
                bg, fg, border = PALETTE["primary"], "#FFFFFF", PALETTE["primary"]
            elif val > 0 and key == "NEW_ASSIGNMENT":
                bg, fg, border = PALETTE["primary_tint"], PALETTE["text_dark"], PALETTE["primary"]
            elif val > 0 and key == "MISMATCH_ALERT":
                bg, fg, border = PALETTE["alert_tint"], PALETTE["text_dark"], PALETTE["border"]
            else:
                bg, fg, border = PALETTE["card_inner"], PALETTE["text_dark"], PALETTE["border"]
            card.configure(bg=bg, highlightbackground=border)
            t_lbl.configure(bg=bg, fg=fg)
            v_lbl.configure(bg=bg, fg=fg)

        self.summary_var.set(
            f"Total: {total}  CONCORDANT: {counts['CONCORDANT']}  "
            f"NEW_ASSIGNMENT: {counts['NEW_ASSIGNMENT']}  "
            f"MISMATCH_ALERT: {counts['MISMATCH_ALERT']}  NO_MATCH: {counts['NO_MATCH']}"
        )

    # ------------------------------------------------------------------
    # Interactive Results Table Rendering, Truncation & Resizing
    # ------------------------------------------------------------------
    def _fit_text_to_width(self, text: str, max_px: int, is_bold: bool = False) -> str:
        """Truncates text with '...' so squished columns never spill over into adjacent cells."""
        if not text:
            return ""
        font_obj = self.tk_font_heading if is_bold else self.tk_font_body
        avail = max_px - 16
        if avail <= 6:
            return ""
        if font_obj.measure(text) <= avail:
            return text
        ellipsis = "..."
        ell_w = font_obj.measure(ellipsis)
        if avail <= ell_w:
            return "."
        low = 0
        high = len(text)
        best = ""
        while low <= high:
            mid = (low + high) // 2
            cand = text[:mid]
            if font_obj.measure(cand) + ell_w <= avail:
                best = cand
                low = mid + 1
            else:
                high = mid - 1
        return best + ellipsis

    def _compute_autofit_col_width(self, col_idx: int) -> int:
        """Computes the exact pixel width needed to display the header and all values in `col_idx`."""
        col_name = RESULTS_COLUMNS[col_idx]
        max_px = self.tk_font_heading.measure(col_name) + 28
        for row_vals in self.results_matrix:
            if col_idx < len(row_vals):
                val_str = row_vals[col_idx]
                _, _, is_bold = get_cell_highlight(col_name, val_str)
                f_obj = self.tk_font_heading if is_bold else self.tk_font_body
                w = f_obj.measure(val_str) + 28
                if w > max_px:
                    max_px = w
        return max(80, max_px)

    def reset_results_column_widths(self):
        """Resets Step 4 column widths to default (primary columns expanded, middle columns squished)."""
        self.results_col_widths = self._default_results_col_widths()
        for idx, col_name in enumerate(RESULTS_COLUMNS):
            if col_name in PRIMARY_EXPANDED_COLUMNS:
                self.results_col_widths[idx] = max(
                    self.results_col_widths[idx], self._compute_autofit_col_width(idx)
                )
        self._redraw_results_canvas()

    def auto_expand_results_column(self, col_idx: int):
        """
        Excel-style double-click behavior:
        - If the column is narrower than its full auto-fit width, expand it to full auto-fit width.
        - If it is already expanded and is an intermediate column, squish it back to compact width.
        """
        if not (0 <= col_idx < len(RESULTS_COLUMNS)):
            return
        full_w = self._compute_autofit_col_width(col_idx)
        cur_w = self.results_col_widths[col_idx]
        col_name = RESULTS_COLUMNS[col_idx]
        squished_w = max(56, int(58 * self.dpi_scale))

        if cur_w < full_w - 4:
            self.results_col_widths[col_idx] = full_w
        elif col_name not in PRIMARY_EXPANDED_COLUMNS:
            self.results_col_widths[col_idx] = squished_w
        else:
            self.results_col_widths[col_idx] = full_w
        self._redraw_results_canvas()

    def populate_results_table(self, rows: List[Dict[str, Any]]):
        """Extracts cell values from pipeline rows, auto-fits the 4 primary columns, and draws the grid."""
        self.last_results_rows = list(rows)
        self.results_matrix = []
        for r in rows:
            meta = r.get("meta", {})
            bold = r.get("bold", {})
            ncbi = r.get("ncbi", {})
            gbif = r.get("gbif", {})

            bold_pct = bold.get("top_pct_identity", 0.0)
            ncbi_pct = ncbi.get("top_pct_identity", 0.0)

            self.results_matrix.append(
                [
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
            )

        self.reset_results_column_widths()

    def _redraw_results_canvas(self):
        """Renders the Step 4 table using current `self.results_col_widths` with cell clipping."""
        c = self.results_canvas
        c.delete("all")

        row_h = max(34, int(34 * self.dpi_scale))

        # 1. Draw Header Row
        x_offset = 0
        for col_idx, col_name in enumerate(RESULTS_COLUMNS):
            w = self.results_col_widths[col_idx]
            c.create_rectangle(
                x_offset,
                0,
                x_offset + w,
                row_h,
                fill=PALETTE["primary_tint"],
                outline=PALETTE["border"],
                width=1,
            )
            clipped_hdr = self._fit_text_to_width(col_name, w, is_bold=True)
            c.create_text(
                x_offset + 8,
                row_h // 2,
                text=clipped_hdr,
                anchor="w",
                fill=PALETTE["text_dark"],
                font=FONT_HEADING,
            )
            x_offset += w

        total_w = x_offset

        if not self.results_matrix:
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
        for r_idx, cell_values in enumerate(self.results_matrix):
            y0 = (r_idx + 1) * row_h
            y1 = y0 + row_h
            x_pos = 0
            for col_idx, val_str in enumerate(cell_values):
                w = self.results_col_widths[col_idx]
                col_name = RESULTS_COLUMNS[col_idx]
                bg_hex, fg_hex, is_bold = get_cell_highlight(col_name, val_str)

                c.create_rectangle(
                    x_pos, y0, x_pos + w, y1, fill=bg_hex, outline=PALETTE["border"], width=1
                )
                clipped_val = self._fit_text_to_width(val_str, w, is_bold=is_bold)
                c.create_text(
                    x_pos + 8,
                    y0 + (row_h // 2),
                    text=clipped_val,
                    anchor="w",
                    fill=fg_hex,
                    font=FONT_HEADING if is_bold else FONT_BODY,
                )
                x_pos += w

        total_h = (len(self.results_matrix) + 1) * row_h
        c.configure(scrollregion=(0, 0, total_w, total_h))

    def _find_border_col_index(self, canvas_x: float, tolerance: int = 6) -> Optional[int]:
        """Returns the column index whose right border is within `tolerance` px of `canvas_x`."""
        acc = 0
        for idx, w in enumerate(self.results_col_widths):
            acc += w
            if abs(canvas_x - acc) <= tolerance:
                return idx
        return None

    def _find_clicked_col_index(self, canvas_x: float) -> Optional[int]:
        """Returns the column index containing `canvas_x`."""
        acc = 0
        for idx, w in enumerate(self.results_col_widths):
            if acc <= canvas_x <= acc + w:
                return idx
            acc += w
        return None

    def _on_results_motion(self, event):
        cx = self.results_canvas.canvasx(event.x)
        border_idx = self._find_border_col_index(cx)
        if border_idx is not None:
            self.results_canvas.configure(cursor="sb_h_double_arrow")
        else:
            self.results_canvas.configure(
                cursor="hand2" if event.y <= max(34, int(34 * self.dpi_scale)) else ""
            )

    def _on_results_press(self, event):
        cx = self.results_canvas.canvasx(event.x)
        border_idx = self._find_border_col_index(cx)
        if border_idx is not None:
            self._resizing_col_idx = border_idx
            self._resize_start_x = int(cx)
            self._resize_start_w = self.results_col_widths[border_idx]

    def _on_results_drag(self, event):
        if self._resizing_col_idx is None:
            return
        cx = int(self.results_canvas.canvasx(event.x))
        new_w = max(38, self._resize_start_w + (cx - self._resize_start_x))
        self.results_col_widths[self._resizing_col_idx] = new_w
        self._redraw_results_canvas()

    def _on_results_release(self, _event):
        self._resizing_col_idx = None

    def _on_results_double_click(self, event):
        """Double-clicking a column border or column header expands/toggles the column like in Excel."""
        cx = self.results_canvas.canvasx(event.x)
        border_idx = self._find_border_col_index(cx, tolerance=8)
        if border_idx is not None:
            self.auto_expand_results_column(border_idx)
            return
        col_idx = self._find_clicked_col_index(cx)
        if col_idx is not None:
            self.auto_expand_results_column(col_idx)

    # ------------------------------------------------------------------
    # Anti-Aliased Circular Spinner & Check-Circle SVG Rendering
    # ------------------------------------------------------------------
    def _animate_spinners(self):
        """Updates anti-aliased spinner frames and check-circle SVG icons on stream cards."""
        self.spinner_frame_idx = (self.spinner_frame_idx + 1) % len(self.spinner_photos)
        mid = self.badge_px // 2
        for key, canvas in self.service_spinners.items():
            state = self.service_states.get(key, "Idle")
            canvas.delete("all")
            if state == "Active":
                canvas.create_image(mid, mid, image=self.spinner_photos[self.spinner_frame_idx])
            elif state == "Done":
                canvas.create_image(mid, mid, image=self.icon_check_done)

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
            fasta_name = (
                Path(self.fasta_var.get()).name if self.fasta_var.get().strip() else "None selected"
            )
            meta_name = (
                f"{Path(self.metadata_var.get()).name} (Morphospecies: '{self.morpho_col_var.get()}')"
                if self.metadata_var.get().strip()
                else "FASTA deflines only"
            )
            self.run_overview_var.set(
                f"FASTA: {fasta_name}     •     Metadata: {meta_name}     •     Target Taxon: {self.taxon_var.get()}"
            )

        if self.current_step == 3 and hasattr(self, "back_to_run_btn"):
            if self.is_running:
                self.back_to_run_btn.configure(
                    text="  Back to Active Run",
                    bg=PALETTE["primary"],
                    fg="#FFFFFF",
                )
            else:
                self.back_to_run_btn.configure(
                    text="  Back: Run",
                    bg=PALETTE["card_inner"],
                    fg=PALETTE["text_dark"],
                )

    def _view_preliminary_results(self):
        """Switches to Step 4 to inspect live preliminary results while identification continues."""
        if not self.preliminary_rows:
            return
        self.populate_results_table(self.preliminary_rows)
        counts = {
            "CONCORDANT": 0,
            "NEW_ASSIGNMENT": 0,
            "MISMATCH_ALERT": 0,
            "NO_MATCH": 0,
        }
        for r in self.preliminary_rows:
            st = r.get("concordance_status", "")
            if st in counts:
                counts[st] += 1
        self._update_summary_cards(len(self.preliminary_rows), counts)
        self.show_step(3)

    @staticmethod
    def _format_duration(seconds: float) -> str:
        """Formats seconds into MM:SS or HH:MM:SS."""
        secs = int(max(0, round(seconds)))
        mins, s = divmod(secs, 60)
        hrs, m = divmod(mins, 60)
        if hrs > 0:
            return f"{hrs:02d}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"

    def _make_button(
        self,
        parent: tk.Widget,
        text: str,
        command,
        primary: bool = True,
        arrow: Optional[str] = None,
    ) -> tk.Button:
        bg = PALETTE["primary"] if primary else PALETTE["card_inner"]
        fg = "#FFFFFF" if primary else PALETTE["text_dark"]
        active_bg = PALETTE["primary_hover"] if primary else PALETTE["primary_tint"]
        active_fg = "#FFFFFF" if primary else PALETTE["text_dark"]

        kwargs: Dict[str, Any] = {}
        if arrow == "right":
            kwargs["image"] = self.icon_arrow_right
            kwargs["compound"] = "right"
        elif arrow == "left":
            kwargs["image"] = self.icon_arrow_left
            kwargs["compound"] = "left"

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
            highlightthickness=0,
            padx=14,
            pady=6,
            font=FONT_HEADING,
            cursor="hand2",
            **kwargs,
        )

    def _attach_logging(self):
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)
        handler = QueueLogHandler(self.log_queue)
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S")
        )
        root_logger.addHandler(handler)

    def toggle_terminal_window(self, _event=None):
        """Toggles the hidden Diagnostic Terminal & Bug Report window via Ctrl+Shift+D."""
        if self.terminal_win and self.terminal_win.winfo_exists():
            self.terminal_win.destroy()
            self.terminal_win = None
            self.terminal_text = None
            return
        self.open_terminal_window()

    def open_guide_window(self):
        """Opens a clean, step-by-step user guide dialog with screenshots and clear workflow instructions."""
        if self.guide_win and self.guide_win.winfo_exists():
            self.guide_win.lift()
            return

        win = tk.Toplevel(self.root)
        win.title("BarcoID — Step-by-Step User Guide")
        win.geometry("1040x840")
        win.minsize(860, 560)
        win.configure(bg=PALETTE["bg_canvas"])
        self.guide_win = win

        # Window icon is automatically inherited from root.iconphoto(True, ...)
        if getattr(self, "_app_icon_refs", None):
            try:
                win.iconphoto(True, *self._app_icon_refs)
            except Exception:
                pass

        # Top title banner
        banner = tk.Frame(
            win,
            bg=PALETTE["primary_tint"],
            highlightbackground=PALETTE["primary"],
            highlightthickness=1,
            padx=20,
            pady=12,
        )
        banner.pack(fill="x", padx=16, pady=14)

        tk.Label(
            banner,
            text="BarcoID Step-by-Step Guide",
            font=FONT_TITLE,
            fg=PALETTE["text_dark"],
            bg=PALETTE["primary_tint"],
        ).pack(side="left")

        tk.Label(
            banner,
            text="Quick 4-step workflow overview with visual guides",
            font=FONT_BODY,
            fg=PALETTE["text_dark"],
            bg=PALETTE["primary_tint"],
        ).pack(side="right")

        # Scrollable container for steps
        container = tk.Frame(win, bg=PALETTE["bg_canvas"])
        container.pack(fill="both", expand=True, padx=16, pady=(0, 14))

        canvas = tk.Canvas(container, bg=PALETTE["bg_canvas"], highlightthickness=0)
        vsb = ModernScrollbar(container, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)

        scrollable_frame = tk.Frame(canvas, bg=PALETTE["bg_canvas"])
        window_id = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")

        def _on_frame_configure(_event):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _on_canvas_configure(event):
            canvas.itemconfig(window_id, width=event.width)

        scrollable_frame.bind("<Configure>", _on_frame_configure)
        canvas.bind("<Configure>", _on_canvas_configure)

        # Smooth mouse wheel scrolling across canvas and all child widgets
        def _on_guide_mousewheel(event):
            if not canvas.winfo_exists():
                return
            if event.delta:
                canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            elif event.num == 4:
                canvas.yview_scroll(-1, "units")
            elif event.num == 5:
                canvas.yview_scroll(1, "units")

        def _bind_mousewheel_recursive(widget):
            widget.bind("<MouseWheel>", _on_guide_mousewheel, add="+")
            widget.bind("<Button-4>", _on_guide_mousewheel, add="+")
            widget.bind("<Button-5>", _on_guide_mousewheel, add="+")
            for child in widget.winfo_children():
                _bind_mousewheel_recursive(child)

        win.bind("<MouseWheel>", _on_guide_mousewheel, add="+")
        win.bind("<Button-4>", _on_guide_mousewheel, add="+")
        win.bind("<Button-5>", _on_guide_mousewheel, add="+")
        canvas.bind("<MouseWheel>", _on_guide_mousewheel, add="+")
        canvas.bind("<Button-4>", _on_guide_mousewheel, add="+")
        canvas.bind("<Button-5>", _on_guide_mousewheel, add="+")
        scrollable_frame.bind("<MouseWheel>", _on_guide_mousewheel, add="+")
        scrollable_frame.bind("<Button-4>", _on_guide_mousewheel, add="+")
        scrollable_frame.bind("<Button-5>", _on_guide_mousewheel, add="+")

        canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        guide_steps = [
            (
                "Step 1: Sequences & Parameters",
                "1. Click 'Browse FASTA' to select your DNA barcodes file (*.fasta, *.fas, *.fa, *.fna).\n"
                "2. Choose the Target Taxon (e.g. Formicidae for ants, Insecta, or any custom NCBI/BOLD filter).\n"
                "3. Optional: Specify max sequences or enable Dry Run / Force Refresh.\n"
                "4. Output folder automatically defaults to `<fasta_folder>/results`.",
                GUIDE_DIR / "step1.png",
            ),
            (
                "Step 2: Metadata Viewer & Column Picker",
                "1. Click 'Choose Metadata File' to load voucher determinations (.csv, .tsv, or .xlsx).\n"
                "2. The interactive table previews your specimen records. Simply click any column header\n"
                "   to bind the Morphospecies or Sample ID column instantly.\n"
                "3. Morphological determination codes automatically infer the genus prior (e.g. PHEI01 -> Pheidole).",
                GUIDE_DIR / "step2.png",
            ),
            (
                "Step 3: Multi-Source Resolution & Run",
                "1. Click 'Run Identification' to launch concurrent validation across all 3 remote engines:\n"
                "   • BOLD Systems v5 API (COI barcode match engine)\n"
                "   • NCBI GenBank QBLAST (Megablast with stalled RID recovery)\n"
                "   • GBIF Taxonomic Backbone (canonical nomenclature match)\n"
                "2. Live rotating circular spinners display real-time query progress and done badges.",
                GUIDE_DIR / "step3.png",
            ),
            (
                "Step 4: Concordance Summary & Results",
                "1. Review the 5 segmented Concordance metric cards:\n"
                "   • Concordant (green): All engines match the morphological prior.\n"
                "   • New Assignment: Identification established for undetermined specimen.\n"
                "   • Mismatch Alert (red): Morphospecies conflicts with database hits.\n"
                "2. Interactive Results Table: Drag column borders or double-click to expand/squish like Excel.\n"
                "3. Click 'Open Excel Report' for the styled multi-tab workbook or 'Open Results Folder'.",
                GUIDE_DIR / "step4.png",
            ),
            (
                "Data Privacy, Storage & Diagnostic Reports",
                "• Local Execution: All FASTA sequences, specimen files, and metadata sheets are processed\n"
                "  strictly locally on your machine. BarcoID contains zero telemetry or background tracking.\n"
                "• Public Databases: Queries are sent only to official biological reference authorities\n"
                "  (BOLD Systems, NCBI GenBank, GBIF Backbone) solely for sequence and taxonomic matching.\n"
                "• Persistent Cache: Results are hashed (SHA-256) and saved in your local `.id_cache/` folder.\n"
                "• Voluntary Issue Reports: No data is ever transmitted unless you explicitly click 'Report issue'.\n"
                "  The diagnostic log sent to GitHub contains only technical environment metadata:\n"
                "    - BarcoID version, OS platform & architecture, Python runtime, display DPI scale\n"
                "    - Input FASTA filename & sequence count (raw DNA sequence letters are NEVER included)\n"
                "    - Metadata filename & selected column names (individual specimen rows are NEVER included)\n"
                "    - Target taxon filter & API connectivity check results (HTTP status / latency)\n"
                "    - Last error traceback & recent execution log messages",
                None,
            ),
        ]

        # Keep PhotoImage references alive
        win._guide_photos = []
        win._guide_steps = guide_steps

        for title, desc, img_path in guide_steps:
            card = tk.Frame(
                scrollable_frame,
                bg=PALETTE["card_inner"],
                highlightbackground=PALETTE["border"],
                highlightthickness=1,
                padx=18,
                pady=14,
            )
            card.pack(fill="x", pady=(0, 16))

            tk.Label(
                card,
                text=title,
                font=FONT_TITLE,
                fg=PALETTE["primary"],
                bg=PALETTE["card_inner"],
                anchor="w",
            ).pack(fill="x", pady=(0, 6))

            tk.Label(
                card,
                text=desc,
                font=FONT_BODY,
                fg=PALETTE["text_dark"],
                bg=PALETTE["card_inner"],
                justify="left",
                anchor="w",
            ).pack(fill="x", pady=(0, 10))

            if img_path and img_path.exists():
                try:
                    photo = tk.PhotoImage(file=str(img_path))
                    # Only downsample if image significantly exceeds available card width (e.g. >980px)
                    if photo.width() > 980:
                        factor = int(math.ceil(photo.width() / 940))
                        photo = photo.subsample(factor, factor)
                    win._guide_photos.append(photo)

                    img_lbl = tk.Label(
                        card,
                        image=photo,
                        bg=PALETTE["card_inner"],
                        relief="solid",
                        bd=1,
                    )
                    img_lbl.pack(anchor="center", pady=(0, 6))
                except Exception:
                    pass

        # Recursively bind mouse wheel to all cards and child widgets created
        _bind_mousewheel_recursive(scrollable_frame)

        # Close button in bottom bar
        btm = tk.Frame(win, bg=PALETTE["bg_canvas"], padx=16, pady=8)
        btm.pack(fill="x")
        self._make_button(btm, "Close Guide", win.destroy, primary=True).pack(side="right")

    def open_terminal_window(self):
        """Opens the Diagnostic Terminal & Bug Report window."""
        if self.terminal_win and self.terminal_win.winfo_exists():
            self.terminal_win.lift()
            return

        win = tk.Toplevel(self.root)
        win.title("BarcoID — Diagnostics & Bug Report (Ctrl+Shift+D)")
        win_w = max(940, int(940 * self.dpi_scale))
        win_h = max(540, int(540 * self.dpi_scale))
        win.geometry(f"{win_w}x{win_h}")
        win.configure(bg=PALETTE["card_inner"])
        self.terminal_win = win

        bar = tk.Frame(win, bg=PALETTE["card_inner"], padx=14, pady=10)
        bar.pack(fill="x")

        tk.Label(
            bar,
            text="Live Execution & Network Diagnostics",
            font=FONT_HEADING,
            fg=PALETTE["text_dark"],
            bg=PALETTE["card_inner"],
        ).pack(side="left")

        self._make_button(bar, "Report issue", self.report_github_issue, primary=True).pack(
            side="right"
        )

        self._make_button(bar, "Save Bug Report", self.export_bug_report, primary=False).pack(
            side="right", padx=(0, 8)
        )

        self._make_button(
            bar, "Test APIs (BOLD / NCBI / GBIF)", self.run_api_test_async, primary=False
        ).pack(side="right", padx=(0, 8))

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
        logging.info(
            "Testing live connectivity to BOLD Systems v5, NCBI QBLAST, and GBIF Backbone..."
        )

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

    def report_github_issue(self):
        """Pre-fills a new GitHub issue on SidloCZ/BarcoID with diagnostics and opens browser."""
        fasta_str = self.fasta_var.get().strip()
        seq_count = 0
        if fasta_str and Path(fasta_str).exists():
            try:
                seq_count = len(FastaParser.read_sequences(Path(fasta_str)))
            except Exception:
                seq_count = -1

        meta_str = self.metadata_var.get().strip()
        morpho_col = self.morpho_col_var.get().strip()
        sample_col = self.sample_col_var.get().strip()
        taxon_filter = self.taxon_var.get().strip()

        # Build issue title
        if self.last_error_trace:
            last_lines = [
                ln.strip() for ln in self.last_error_trace.strip().splitlines() if ln.strip()
            ]
            err_title = last_lines[-1] if last_lines else "Unknown Exception"
            if len(err_title) > 90:
                err_title = err_title[:87] + "..."
            title = f"[Bug]: {err_title}"
        else:
            title = f"[Bug]: Issue Report — v{__version__}"

        # Tail of recent log history (last 30 entries) to prevent URL length limits
        recent_logs = (
            "\n".join(self.log_history[-30:]) if self.log_history else "<no log entries yet>"
        )

        traceback_block = (
            self.last_error_trace.strip()
            if self.last_error_trace
            else "<no exception trace recorded>"
        )

        body = (
            "### Problem Description\n"
            "<!-- Please describe what happened, what you expected, and any steps to reproduce -->\n\n"
            "### Environment & Diagnostics\n"
            f"- **BarcoID Version:** v{__version__}\n"
            f"- **OS / Platform:** {platform.platform()}\n"
            f"- **Python Runtime:** {sys.version.split()[0]} (Frozen EXE: {getattr(sys, 'frozen', False)})\n"
            f"- **Monitor DPI Scale:** {self.dpi_scale:.2f}x\n"
            f"- **Input FASTA:** {Path(fasta_str).name if fasta_str else '<none>'} ({seq_count} sequences)\n"
            f"- **Metadata File:** {Path(meta_str).name if meta_str else '<none>'}\n"
            f"- **Morphospecies Col:** {morpho_col}\n"
            f"- **Sample ID Col:** {sample_col}\n"
            f"- **Target Taxon:** {taxon_filter}\n"
            f"- **Pipeline Running:** {self.is_running}\n\n"
            "### Error Traceback\n"
            "```text\n"
            f"{traceback_block}\n"
            "```\n\n"
            "### Recent Execution Logs\n"
            "```text\n"
            f"{recent_logs}\n"
            "```\n\n"
            "---\n"
            "*(The full unabridged diagnostic report has also been copied to your clipboard)*\n"
        )

        full_report = self.build_diagnostic_report_text(include_api_ping=False)
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(full_report)
        except Exception:
            pass

        query_params = urllib.parse.urlencode({"title": title, "body": body})
        issue_url = f"https://github.com/SidloCZ/BarcoID/issues/new?{query_params}"
        webbrowser.open_new_tab(issue_url)
        logging.info(
            "Opened GitHub issues in browser. Complete diagnostic report copied to clipboard."
        )

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
            messagebox.showwarning(
                "Empty Metadata", "No column headers found in the selected file."
            )
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
            self.meta_tree.column(col, width=col_w, minwidth=60, anchor="w")
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
                genus_note = (
                    f"Inferred Genus: {inferred}" if inferred else "Unassigned / Indeterminate"
                )
                example_text = f"Preview ({s_val or 'row'}) -> '{m_val}' ({genus_note})"
                break

        if not example_text:
            example_text = "Click any column header below to select the Morphospecies column."

        self.morpho_preview_var.set(
            f"Active Morphospecies Column: '{m_col}'     •     Sample ID: '{s_col}'     •     {example_text}"
        )

    # ------------------------------------------------------------------
    # Pipeline Execution in Background Worker Thread
    # ------------------------------------------------------------------
    def start_run(self):
        if self.is_running:
            return

        fasta_str = self.fasta_var.get().strip()
        if not fasta_str:
            messagebox.showwarning(
                "Missing Input", "Please select an input FASTA file in Step 1 first."
            )
            self.show_step(0)
            return

        fasta_path = Path(fasta_str)
        if not fasta_path.exists():
            messagebox.showerror("File Not Found", f"FASTA file does not exist:\n{fasta_path}")
            self.show_step(0)
            return

        try:
            try:
                prelim_interval_val = max(10, int(self.preliminary_interval_var.get().strip()))
            except Exception:
                prelim_interval_val = 50

            config = build_config_from_inputs(
                fasta_path=fasta_path,
                output_dir=Path(self.output_dir_var.get().strip())
                if self.output_dir_var.get().strip()
                else None,
                taxon=self.taxon_var.get(),
                max_sequences_str=self.max_seq_var.get(),
                ncbi_email=self.ncbi_email_var.get(),
                ncbi_api_key=self.ncbi_key_var.get(),
                dry_run=self.dry_run_var.get(),
                force_refresh=self.force_refresh_var.get(),
                skip_ncbi=self.skip_ncbi_var.get(),
                enable_preliminary_results=self.enable_preliminary_var.get(),
                preliminary_interval=prelim_interval_val,
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
        self.preliminary_rows = []
        self.preliminary_xlsx_path = None
        self.eta_var.set("Starting pipeline...")
        self.preliminary_btn.pack_forget()

        self.run_btn.configure(
            state="disabled",
            text="Running...",
            bg=PALETTE["primary"],
            fg="#FFFFFF",
            disabledforeground="#FFFFFF",
        )
        self.progress_var.set(5.0)
        self._set_service_states(
            morpho="Active",
            bold="Idle",
            ncbi="Skipped" if self.skip_ncbi_var.get() else "Idle",
            gbif="Idle",
        )

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
        def _progress(stage: str, pct: float, metrics: Optional[Dict[str, Any]] = None):
            self.ui_queue.put(("progress", (stage, pct, metrics)))

        def _service(name: str, status: str):
            self.ui_queue.put(("service", (name, status)))

        def _preliminary(rows: List[Dict[str, Any]], prelim_path: Optional[Path]):
            self.ui_queue.put(("preliminary_data", (rows, prelim_path)))

        try:
            pipeline = BarcoIDPipeline(config)
            rows = pipeline.run(
                fasta_path=fasta_path,
                metadata_path=meta_path,
                sample_col=sample_col,
                morpho_col=morpho_col,
                progress_callback=_progress,
                service_callback=_service,
                preliminary_callback=_preliminary,
            )
            xlsx_path = (
                Path(config.output_dir) / f"{fasta_path.stem}_multi_source_identification.xlsx"
            )
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
                payload_tuple = payload
                if isinstance(payload_tuple, tuple) and len(payload_tuple) == 3:
                    stage, pct, metrics = payload_tuple
                else:
                    stage, pct = payload_tuple
                    metrics = None

                self.stage_var.set(stage)
                self.progress_var.set(pct)

                if metrics:
                    elapsed_str = self._format_duration(metrics.get("elapsed_seconds", 0.0))
                    eta_str = self._format_duration(metrics.get("eta_seconds", 0.0))
                    speed = metrics.get("speed", 0.0)
                    done = metrics.get("completed", 0)
                    total = metrics.get("total", 0)
                    pct_val = metrics.get("pct", pct)

                    eta_text = (
                        f"Elapsed: {elapsed_str} | ETA: ~{eta_str} | "
                        f"Speed: {speed:.1f} seq/s | Completed: {done} / {total} ({pct_val:.1f}%)"
                    )
                    self.eta_var.set(eta_text)

            elif event == "preliminary_data":
                prelim_rows, prelim_xlsx = payload
                self.preliminary_rows = prelim_rows
                if prelim_xlsx and Path(prelim_xlsx).exists():
                    self.preliminary_xlsx_path = Path(prelim_xlsx)
                    self.last_excel_path = Path(prelim_xlsx)
                    self.open_excel_btn.configure(
                        bg=PALETTE["primary"],
                        fg="#FFFFFF",
                        text="Open Preliminary Excel Report",
                    )

                # Show and activate Check Preliminary Results button
                self.preliminary_btn.configure(
                    state="normal",
                    text=f"Check Preliminary Results ({len(prelim_rows)})  ",
                    bg=PALETTE["primary_tint"],
                    fg=PALETTE["text_dark"],
                )
                self.preliminary_btn.pack(side="right", padx=(0, 10))

                # Live refresh if user is currently inspecting Step 4
                if self.current_step == 3:
                    self.populate_results_table(prelim_rows)
                    counts = {
                        "CONCORDANT": 0,
                        "NEW_ASSIGNMENT": 0,
                        "MISMATCH_ALERT": 0,
                        "NO_MATCH": 0,
                    }
                    for r in prelim_rows:
                        st = r.get("concordance_status", "")
                        if st in counts:
                            counts[st] += 1
                    self._update_summary_cards(len(prelim_rows), counts)

            elif event == "done":
                rows, xlsx_path, is_dry_run = payload
                self.is_running = False
                self.preliminary_btn.pack_forget()
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

                self._update_summary_cards(len(rows), counts)
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
                messagebox.showerror(
                    "Execution Error", f"An error occurred during identification:\n{payload}"
                )

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
