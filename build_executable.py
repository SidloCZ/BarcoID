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


def build_executable(windowed: bool = True, name: str = "BarcoID") -> int:
    root_dir = Path(__file__).resolve().parent
    entry_script = root_dir / "src" / "barcoid" / "cli.py"
    assets_dir = root_dir / "src" / "barcoid" / "assets"
    sep = ";" if sys.platform.startswith("win") else ":"

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

    if windowed:
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

