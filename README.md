# RENZ Launcher v6 -- Universal

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
