#!/usr/bin/env python3
"""
Build script for Renz Launcher v7
Creates standalone EXE with PyInstaller
"""

import subprocess
import sys
import os

def build():
    print("=" * 60)
    print("  Renz Launcher v7 -- Build Script")
    print("  Building UNIVERSAL jailbreak EXE")
    print("=" * 60)
    print()

    # Check if PyInstaller is installed
    try:
        import PyInstaller
        print("[OK] PyInstaller found")
    except ImportError:
        print("[*] PyInstaller not found. Installing...")
        subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"], check=True)
        print("[OK] PyInstaller installed")

    # Clean old builds
    print("\n-> Cleaning old builds...")
    for d in ["build", "dist", "__pycache__"]:
        if os.path.exists(d):
            import shutil
            shutil.rmtree(d)
            print(f"  Removed {d}/")

    # Build the EXE
    print("\n-> Building EXE with PyInstaller...")
    print("  This may take a few minutes...")
    print()

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--clean",
        "--onefile",
        "--name", "renz_launcher",
        "--add-data", "personas;personas",
        "--add-data", "proxy_server.py;.",
        "--add-data", "test_models.py;.",
        "--hidden-import", "customtkinter",
        "--hidden-import", "rich",
        "--hidden-import", "rich.console",
        "--hidden-import", "rich.panel",
        "--hidden-import", "rich.table",
        "--hidden-import", "rich.box",
        "--hidden-import", "rich.prompt",
        "renz_launcher.py"
    ]

    result = subprocess.run(cmd)

    if result.returncode == 0:
        print()
        print("=" * 60)
        print("  [OK] Build successful!")
        print("=" * 60)
        print()
        print("  Output: dist/renz_launcher.exe")
        print()
        print("  Usage:")
        print("    dist\\renz_launcher.exe           # Launch GUI")
        print("    dist\\renz_launcher.exe --cli     # Launch CLI")
        print("    dist\\renz_launcher.exe --help    # Show help")
        print()
        print("  Files included:")
        print("    - NOVA v7 (998 lines, 72KB — Identity Lock)")
        print("    - WORM Proxy v7 (Universal API support, robust streaming)")
        print("    - Launcher v7 (GPT-5.6 / multi-session)")
        print()

        # Show file size
        exe_path = "dist/renz_launcher.exe"
        if os.path.exists(exe_path):
            size = os.path.getsize(exe_path)
            print(f"  Size: {size / (1024*1024):.1f} MB")
            print()
    else:
        print()
        print("  [FAIL] Build failed!")
        print(f"  Exit code: {result.returncode}")
        sys.exit(1)

if __name__ == "__main__":
    build()
