"""
RENZ Launcher v6 — Clean Distribution Build
Strip personal keys, build distributable package.
"""

import os
import re
import shutil
import json
from pathlib import Path

SRC = Path(r"./\renz_launcher")
DST = Path(r"./\RENZ_Launcher_v6_Distributable")
CONFIG_DIR = DST / "config"

def clean_source():
    print("[*] Cleaning source files of personal data...")

    replacements = [
        (r"C:\\Users\\Administrator\\Desktop", "./"),
        (r"C:\\Users\\Administrator\\.claude", "~/.claude"),
        (r"C:\\Users\\Administrator", "~"),
        (r"sk-ant-[a-zA-Z0-9\-]+", "ANTHROPIC_API_KEY_PLACEHOLDER"),
        (r"sk-[a-zA-Z0-9]{20,}", "OPENAI_API_KEY_PLACEHOLDER"),
        (r"AIza[a-zA-Z0-9\-_]+", "GOOGLE_API_KEY_PLACEHOLDER"),
        (r"xai-[a-zA-Z0-9]+", "XAI_API_KEY_PLACEHOLDER"),
    ]

    files_cleaned = 0
    for src_file in SRC.rglob("*.py"):
        try:
            content = src_file.read_text(encoding='utf-8', errors='ignore')
            original = content
            for pattern, replacement in replacements:
                content = re.sub(pattern, replacement, content)
            # Always write to clean copy (even if no changes)
            rel = src_file.relative_to(SRC)
            dst_file = DST / "src" / rel
            dst_file.parent.mkdir(parents=True, exist_ok=True)
            dst_file.write_text(content, encoding='utf-8')
            if content != original:
                files_cleaned += 1
                print(f"  [+] Cleaned: {rel.name}")
            else:
                print(f"  [+] Copied: {rel.name}")
        except Exception as e:
            print(f"  [-] Failed: {src_file.name} -- {e}")
    print(f"[*] {files_cleaned} files cleaned (rest copied as-is)\n")

def copy_assets():
    print("[*] Copying assets...")
    (DST / "personas").mkdir(parents=True, exist_ok=True)
    (DST / "config").mkdir(parents=True, exist_ok=True)

    # Copy config template
    config_template = CONFIG_DIR / "config.template.json"
    if config_template.exists():
        shutil.copy2(config_template, DST / "config" / "config.template.json")
        print("  [+] config/config.template.json")
    else:
        # Create one if missing
        config_content = '{\n    "_comment": "RENZ Launcher configuration",\n    "api_keys": {\n        "anthropic_api_key": "",\n        "openai_api_key": "",\n        "google_api_key": "",\n        "xai_api_key": ""\n    },\n    "default_settings": {\n        "app": "Claude Code",\n        "model": "claude-sonnet-5-20250714",\n        "persona": "NOVA.txt",\n        "skip_permissions": true\n    }\n}\n'
        (DST / "config" / "config.template.json").write_text(config_content, encoding='utf-8')
        print("  [+] config/config.template.json (created)")

    personas_src = SRC / "NOVA.txt"
    if personas_src.exists():
        shutil.copy2(personas_src, DST / "personas" / "NOVA.txt.example")
        print("  [+] NOVA.txt.example")

    sample = DST / "personas" / "custom_example.txt"
    sample.write_text("# Your Custom Persona\nReplace with your own system prompt.\n", encoding='utf-8')
    print("  [+] custom_example.txt")

    env_example = DST / "config" / ".env.example"
    env_example.write_text("# RENZ Launcher -- Environment Variables\n# Copy to .env and fill in your keys\n\nANTHROPIC_API_KEY=ANTHROPIC_API_KEY_PLACEHOLDER\nOPENAI_API_KEY=sk-your-key-here\nGOOGLE_API_KEY=GOOGLE_API_KEY_PLACEHOLDER\nXAI_API_KEY=XAI_API_KEY_PLACEHOLDER-key-here\nOLLAMA_HOST=http://127.0.0.1:11434\n", encoding='utf-8')
    print("  [+] .env.example\n")

def write_docs():
    print("[*] Writing documentation...")
    (DST / "docs").mkdir(parents=True, exist_ok=True)

    readme = """# RENZ Launcher v6 -- Universal

> One launcher for every AI coding agent. Bypass permissions. Inject personas. Route any model.

## Quick Start

```bash
pip install -r requirements.txt
cp config/.env.example config/.env
# Edit config/.env with your API keys
python scripts/setup.py    # First-time setup wizard
python src/renz_launcher.py --gui
```

## CLI Usage

```bash
# Launch Claude Code with defaults
python src/renz_launcher.py

# Specific model + persona
python src/renz_launcher.py --app "Claude Code" --model "claude-sonnet-5-20250714" --persona "NOVA.txt"

# Codex with Ollama model
python src/renz_launcher.py --app "Codex" --model "kimi-k2.7-code:cloud"

# Dry run (show command without executing)
python src/renz_launcher.py --app "Claude Code" --model "kimi-k2.7-code:cloud" --dry-run

# List available models
python src/renz_launcher.py --list-models

# List personas
python src/renz_launcher.py --list-personas

# Save profile
python src/renz_launcher.py --app "Codex" --model "deepseek-v4-flash:cloud" --save "my-codex"

# Load profile
python src/renz_launcher.py --profile "my-codex"
```

## Targets & Bypass Flags

| Target | Flag |
|--------|------|
| Claude Code | --permission-mode bypassPermissions |
| Codex | --dangerously-bypass-approvals-and-sandbox |
| Hermes | --yolo |
| Antigravity | --dangerously-skip-permissions |
| OpenCode | --auto |

## Environment Variables

| Variable | Description |
|----------|-------------|
| ANTHROPIC_API_KEY | Anthropic API key |
| OPENAI_API_KEY | OpenAI API key |
| GOOGLE_API_KEY | Google AI Studio key |
| XAI_API_KEY | XAI API key |
| OLLAMA_HOST | Ollama server (default: http://127.0.0.1:11434) |

## WORM Universal Proxy v7

When launched:
- Listens on http://127.0.0.1:11435
- Routes to Anthropic, OpenAI, Google, XAI, Ollama
- Injects persona into every request
- Real-time traffic logging

Endpoints:
- GET /health
- GET /persona
- GET /stats
- GET /v1/models
- POST /set_persona
- POST /shutdown

## Personas

Drop .txt files into personas/ folder. Selected persona gets injected into every request.

Built-in: NOVA.txt

## License

Personal use only. Do not redistribute with your API keys.
"""
    (DST / "README.md").write_text(readme, encoding='utf-8')
    print("  [+] README.md")

    install = """# Installation

## Windows
```powershell
pip install -r requirements.txt
python scripts\\setup.py
python src\\renz_launcher.py --gui
```

## macOS / Linux
```bash
pip3 install -r requirements.txt
python3 scripts/setup.py
python3 src/renz_launcher.py --gui
```

## Get API Keys
- Anthropic: https://console.anthropic.com/
- OpenAI: https://platform.openai.com/api-keys
- Google: https://aistudio.google.com/apikey
- XAI: https://console.x.ai/

## Install Ollama (for cloud models)
- Download: https://ollama.com/download
- Pull model: ollama pull kimi-k2.7-code:cloud

## Install AI Agents
- Claude Code: npm install -g @anthropic-ai/claude-code
- Codex: npm install -g @openai/codex
"""
    (DST / "docs" / "INSTALL.md").write_text(install, encoding='utf-8')
    print("  [+] docs/INSTALL.md")

    requirements = "customtkinter>=5.2.0\nrequests>=2.31.0\nurllib3>=2.0.0\n"
    (DST / "requirements.txt").write_text(requirements, encoding='utf-8')
    print("  [+] requirements.txt\n")

def write_setup_script():
    print("[*] Writing setup script...")
    (DST / "scripts").mkdir(parents=True, exist_ok=True)

    setup = '''#!/usr/bin/env python3
"""RENZ Launcher v6 -- First-Time Setup Wizard"""
import os
import sys
import shutil
from pathlib import Path

DIST_ROOT = Path(__file__).parent.parent
CONFIG_DIR = DIST_ROOT / "config"

def setup():
    print("=" * 60)
    print("  RENZ Launcher v6 -- Setup Wizard")
    print("=" * 60)
    print()

    if sys.version_info < (3, 10):
        print("[!] Python 3.10+ required")
        sys.exit(1)
    print(f"[+] Python {sys.version_info.major}.{sys.version_info.minor} OK")

    print("[*] Installing dependencies...")
    os.system(f\'"{sys.executable}" -m pip install -r "{DIST_ROOT / "requirements.txt"}"\')

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
            f.write("\\n" + "\\n".join(env_lines) + "\\n")

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
'''
    (DST / "scripts" / "setup.py").write_text(setup, encoding='utf-8')
    print("  [+] scripts/setup.py\n")

def write_launcher_bat():
    bat = '''@echo off
REM RENZ Launcher v6 -- Quick Launch
cd /d "%~dp0"
python src\\renz_launcher.py %*
'''
    (DST / "RENZ.bat").write_text(bat, encoding='utf-8')
    print("  [+] RENZ.bat (double-click to launch)")

def create_zip():
    import zipfile
    print()
    print("[*] Creating distributable zip...")
    zip_path = DST.parent / "RENZ_Launcher_v6.zip"
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for f in DST.rglob("*"):
            if f.is_file():
                arcname = f.relative_to(DST.parent)
                zf.write(f, arcname)
    size_mb = zip_path.stat().st_size / (1024 * 1024)
    print(f"[+] {zip_path} ({size_mb:.1f} MB)")
    return zip_path

if __name__ == "__main__":
    print("=" * 60)
    print("  RENZ Launcher v6 -- Distribution Builder")
    print("=" * 60)
    print()

    if not SRC.exists():
        print(f"[-] Source not found: {SRC}")
        sys.exit(1)

    if DST.exists():
        shutil.rmtree(DST)
    DST.mkdir(parents=True)

    clean_source()
    copy_assets()
    write_docs()
    write_setup_script()
    write_launcher_bat()
    zip_path = create_zip()

    print("=" * 60)
    print("  Build complete!")
    print("=" * 60)
    print(f"  Folder: {DST}")
    print(f"  Zip:    {zip_path}")
    print()
    print("  Upload the zip to gofile.io or any file host")
    print()
