#!/usr/bin/env python3
"""RENZ Launcher v8 -- First-Time Setup Wizard"""
import os
import sys
import shutil
from pathlib import Path

DIST_ROOT = Path(__file__).parent.parent
CONFIG_DIR = DIST_ROOT / "config"

def setup():
    print("=" * 60)
    print("  RENZ Launcher v8 -- Setup Wizard")
    print("=" * 60)
    print()

    if sys.version_info < (3, 10):
        print("[!] Python 3.10+ required")
        sys.exit(1)
    print(f"[+] Python {sys.version_info.major}.{sys.version_info.minor} OK")

    print("[*] Installing dependencies...")
    os.system(f'"{sys.executable}" -m pip install -r "{DIST_ROOT / "requirements.txt"}"')

    template = CONFIG_DIR / "config.template.json"
    config_file = CONFIG_DIR / "config.json"
    if not config_file.exists():
        shutil.copy2(template, config_file)
        print(f"[+] Created {config_file}")

    env_template = CONFIG_DIR / ".env.example"
    env_file = CONFIG_DIR / ".env"
    if not env_file.exists():
        shutil.copy2(env_template, env_file)
        print(f"[+] Created {env_file}")

    print()
    print("=" * 60)
    print("  API Key Setup (Enter to skip)")
    print("=" * 60)
    print()

    env_lines = []
    for key, name in [
        ("ANTHROPIC_API_KEY", "Anthropic (Claude)"),
        ("OPENAI_API_KEY", "OpenAI (GPT/Codex)"),
        ("GOOGLE_API_KEY", "Google (Gemini)"),
        ("XAI_API_KEY", "XAI (Grok)"),
    ]:
        val = input(f"  {name} key: ").strip()
        if val:
            env_lines.append(f"{key}={val}")
            print(f"  [+] {key} set")
        else:
            print(f"  [-] {key} skipped")

    if env_lines:
        with open(env_file, "a", encoding="utf-8") as f:
            f.write("\n" + "\n".join(env_lines) + "\n")

    print()
    print("=" * 60)
    print("  Setup complete!")
    print("=" * 60)
    print()
    print("  Launch GUI:    python src/renz_launcher.py --gui")
    print("  Launch CLI:    python src/renz_launcher.py")
    print()

if __name__ == "__main__":
    try:
        setup()
    except KeyboardInterrupt:
        sys.exit(1)
