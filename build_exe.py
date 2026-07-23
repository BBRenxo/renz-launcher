#!/usr/bin/env python3
"""
Build script for RENZ Launcher v10.0
Builds standalone EXEs with PyInstaller:
  - dist/renz_launcher.exe     (GUI)
  - dist/renz_app_desktop.exe  (RENZ App Desktop)
  - dist/renz_app_cli.exe      (RENZ App CLI)
  - dist/renz_proxy.exe        (WORM Proxy)
"""

import subprocess
import sys
import os
import shutil


def ensure_pyinstaller():
    """Install PyInstaller if not present."""
    try:
        import PyInstaller
        print("[OK] PyInstaller found")
    except ImportError:
        print("[*] Installing PyInstaller...")
        subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"], check=True)
        print("[OK] PyInstaller installed")


def build_one(name, script, hidden_imports=None, add_data=None, console=False):
    """Build a single EXE with PyInstaller."""
    print(f"\n-> Building {name}.exe from {script}...")
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--clean", "--onefile", "--noconfirm",
        "--name", name,
    ]
    if not console:
        cmd.append("--noconsole")
    if add_data:
        for src, dst in add_data:
            cmd += ["--add-data", f"{src}{os.pathsep}{dst}"]
    if hidden_imports:
        for h in hidden_imports:
            cmd += ["--hidden-import", h]
    cmd.append(script)
    result = subprocess.run(cmd)
    return result.returncode == 0


def main():
    print("=" * 60)
    print("  RENZ Launcher v8.7.0 - Build Script")
    print("  Building 4 EXEs: launcher, desktop, CLI, proxy")
    print("=" * 60)
    print()
    ensure_pyinstaller()
    # Clean
    print("\n-> Cleaning old builds...")
    for d in ["build", "dist", "__pycache__"]:
        if os.path.exists(d):
            shutil.rmtree(d)
            print(f"  Removed {d}/")
    # Build each
    builds = [
        # (name, script, console, hidden_imports, add_data)
        ("renz_launcher", "renz_launcher.py", True,
         ["rich", "rich.console", "rich.panel", "rich.table", "rich.box", "rich.prompt"],
         [("personas", "personas"), ("proxy_server.py", "."), ("renz_app", "renz_app")]),
        ("renz_gui", "renz_gui.py", False,
         ["customtkinter", "rich", "rich.console", "rich.panel", "rich.table", "rich.box", "rich.prompt"],
         [("personas", "personas"), ("proxy_server.py", "."), ("renz_app", "renz_app"), ("renz_launcher.py", ".")]),
        ("renz_app_desktop", "renz_app/desktop.py", False,
         ["PIL", "_tkinter"],
         [("personas", "personas"), ("renz_app", "renz_app")]),
        ("renz_app_cli", "renz_app/__main__.py", True, [], [("personas", "personas")]),
        ("renz_proxy", "proxy_server.py", True, [], []),
    ]
    for name, script, console, hi, ad in builds:
        ok = build_one(name, script, hidden_imports=hi, add_data=ad, console=console)
        if ok:
            print(f"  [OK] {name}.exe")
        else:
            print(f"  [FAIL] {name}.exe")
    print()
    print("=" * 60)
    print("  Done!")
    print("=" * 60)
    if os.path.exists("dist"):
        print("\nBuild artifacts:")
        for f in sorted(os.listdir("dist")):
            if f.endswith(".exe"):
                size = os.path.getsize(os.path.join("dist", f)) / (1024 * 1024)
                print(f"  dist/{f}  ({size:.1f} MB)")


if __name__ == "__main__":
    main()
