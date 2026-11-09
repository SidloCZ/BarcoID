"""
Single-command builder for generating a standalone zero-installation BarcoID executable
using PyInstaller.

Usage:
    python build_executable.py
"""

import argparse
import subprocess
import sys
from pathlib import Path


def ensure_splash_screen(assets_dir: Path, version: str) -> Path:
    """Generates or updates the high-resolution BarcoID splash screen with a large logo."""
    splash_path = assets_dir / "splash.png"
    logo_path = assets_dir / "logo_transparent_master.png"
    if not logo_path.exists():
        return splash_path

    try:
        from PIL import Image, ImageDraw, ImageFont

        logo = Image.open(logo_path)
        bbox = logo.getbbox()
        if bbox:
            logo = logo.crop(bbox)

        w, h = 640, 420
        img = Image.new("RGB", (w, h), "#FFFFFF")
        draw = ImageDraw.Draw(img)
        draw.rectangle([0, 0, w - 1, h - 1], outline="#CBD5E1", width=1)

        # Large prominent logo in the upper portion
        target_h = 165
        target_w = int(target_h * (logo.width / logo.height))
        logo_res = logo.resize((target_w, target_h), Image.Resampling.LANCZOS)
        x_pos = (w - target_w) // 2
        img.paste(logo_res, (x_pos, 28), logo_res)

        # System fonts (Segoe UI on Windows, fallback to default)
        try:
            font_title = ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf", 36)
            font_sub = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 13)
            font_badge = ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf", 11)
            font_status = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 12)
        except OSError:
            font_title = ImageFont.load_default()
            font_sub = font_badge = font_status = font_title

        # Title
        draw.text((w // 2, 222), "BarcoID", fill="#111111", font=font_title, anchor="mm")

        # Subtitle
        draw.text(
            (w // 2, 258),
            "Multi-Source DNA Barcode Identifier & QC Auditor",
            fill="#475569",
            font=font_sub,
            anchor="mm",
        )

        # Version badge
        badge_text = f"v{version}"
        bw, bh = 80, 22
        bx = (w - bw) // 2
        by = 280
        draw.rounded_rectangle([bx, by, bx + bw, by + bh], radius=6, fill="#EAF4E9", outline="#A7F3D0")
        draw.text((w // 2, by + bh // 2), badge_text, fill="#3B8235", font=font_badge, anchor="mm")

        # Progress / accent line
        pw = 320
        px = (w - pw) // 2
        py = 330
        draw.rounded_rectangle([px, py, px + pw, py + 4], radius=2, fill="#E2E8F0")
        draw.rounded_rectangle([px, py, px + int(pw * 0.45), py + 4], radius=2, fill="#4C9E45")

        # Status text
        draw.text(
            (w // 2, 362),
            "Starting BarcoID application...",
            fill="#64748B",
            font=font_status,
            anchor="mm",
        )

        img.save(splash_path)
    except Exception as exc:
        print(f"Notice: Could not regenerate splash screen ({exc}), using existing if available.")

    return splash_path


def build_executable(windowed: bool = True, name: str = "BarcoID") -> int:
    root_dir = Path(__file__).resolve().parent
    sys.path.insert(0, str(root_dir / "src"))
    from barcoid import __version__

    entry_script = root_dir / "src" / "barcoid" / "cli.py"
    assets_dir = root_dir / "src" / "barcoid" / "assets"
    ico_asset = assets_dir / "app_icon.ico"
    sep = ";" if sys.platform.startswith("win") else ":"

    splash_asset = ensure_splash_screen(assets_dir, __version__)

    ext = ".exe" if sys.platform.startswith("win") else ""
    out_path = root_dir / "dist" / f"{name}{ext}"
    old_path = root_dir / "dist" / f"{name}.old{ext}"
    if old_path.exists():
        try:
            old_path.unlink()
        except OSError:
            pass
    if out_path.exists():
        try:
            out_path.unlink()
        except PermissionError:
            # Windows allows renaming a currently running executable so the new build can be written
            try:
                out_path.rename(old_path)
            except OSError:
                pass

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name",
        name,
        "--paths",
        str(root_dir / "src"),
        "--add-data",
        f"{assets_dir}{sep}barcoid/assets",
        "--hidden-import",
        "barcoid.gui",
        "--hidden-import",
        "Bio.Blast.NCBIXML",
        "--hidden-import",
        "openpyxl",
        "--hidden-import",
        "requests",
        "--hidden-import",
        "urllib3",
    ]

    # Platform-specific icon: Windows accepts .ico, macOS requires .icns
    if sys.platform.startswith("win") and ico_asset.exists():
        cmd.extend(["--icon", str(ico_asset)])

    # High-resolution splash screen
    if splash_asset.exists():
        cmd.extend(["--splash", str(splash_asset)])

    # On Windows, suppress the background terminal console for a clean GUI experience
    if windowed and sys.platform.startswith("win"):
        cmd.append("--windowed")

    cmd.append(str(entry_script))

    print(f"Building standalone executable '{name}'...")
    print("Command:", " ".join(cmd))
    result = subprocess.run(cmd, cwd=str(root_dir))
    if result.returncode == 0:
        ext = ".exe" if sys.platform.startswith("win") else ""
        out_path = root_dir / "dist" / f"{name}{ext}"
        print(f"Build succeeded: {out_path}")
    return result.returncode


def main():
    parser = argparse.ArgumentParser(description="Build standalone BarcoID executable.")
    parser.add_argument(
        "--console",
        action="store_true",
        help="Keep console window attached (default builds a clean windowed GUI executable).",
    )
    parser.add_argument(
        "--name",
        type=str,
        default="BarcoID",
        help="Output binary name (default: 'BarcoID').",
    )
    args = parser.parse_args()
    sys.exit(build_executable(windowed=not args.console, name=args.name))


if __name__ == "__main__":
    main()
