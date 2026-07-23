#!/usr/bin/env python3
"""
Renz GUI Launcher — auto-passes --gui flag.
Built as renz_gui.exe with --noconsole so no cmd window.
"""
import sys, os

# Inject --gui before running the main launcher
if "--gui" not in sys.argv:
    sys.argv.insert(1, "--gui")

# Find renz_launcher.py — works both frozen (sys._MEIPASS) and source
if hasattr(sys, '_MEIPASS'):
    base = sys._MEIPASS
else:
    base = os.path.dirname(os.path.abspath(__file__))

launcher_path = os.path.join(base, "renz_launcher.py")
if os.path.exists(launcher_path):
    with open(launcher_path, "r", encoding="utf-8") as f:
        code = f.read()
    exec(code)
else:
    print(f"ERROR: renz_launcher.py not found at {launcher_path}")
    sys.exit(1)
