# Installation

## Windows
```powershell
pip install -r requirements.txt
python scripts\setup.py
python src\renz_launcher.py --gui
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
