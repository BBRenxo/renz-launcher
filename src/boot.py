#!/usr/bin/env python3
"""Renz Launcher v5 — EXE entry point. Routes to CLI mode with arg parsing."""
import sys
import os

# Ensure we can find NOVA.txt and proxy_server.py relative to the EXE
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from renz_launcher import _basic_cli, cli_mode

if __name__ == "__main__":
    if len(sys.argv) > 1:
        _basic_cli()
    else:
        cli_mode()
