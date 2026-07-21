# RENZ Launcher v9.2.1

**Universal AI Agent Launcher — Jailbreak. Route. Own.**

Claude Code · Claude Desktop · Codex · Kimi CLI · Hermes Agent · Antigravity · OpenCode · FORGE · RENZ App

Inject any persona into any model. Route any model through the WORM proxy. Bypass permission prompts. **14 jailbreak techniques** including **Active Response Steering** (novel — never seen before). Built-in terminal agent (CLI + Desktop).

---

## Quick Start

```bash
unzip RENZ_Launcher_v9.zip
cd RENZ_Launcher_v9_Distributable
pip install -r requirements.txt
python scripts/setup.py
python src/renz_launcher.py --gui
```

Or double-click `RENZ.bat` on Windows.

### RENZ App (built-in agent)

```bash
# CLI
python -m renz_app --model glm-5.2:cloud --persona NOVA.txt --yolo

# Desktop (Tkinter GUI)
python -m renz_app.desktop --model glm-5.2:cloud --persona NOVA.txt --yolo
```

---

## 14 Jailbreak Techniques

Toggle any combination in the GUI or via CLI flags:

| Technique | Flag | What it does |
|-----------|------|-------------|
| **Connected Crescendo** | `--crescendo` | Stateful multi-turn escalation — tracks conversation turns, progressively intensifies persona |
| **SEAL** | `--seal` | Stacked Encryption for Adaptive LLMs — encodes requests with 2-4 random cipher layers (base64, rot13, hex, emoji, leetspeak) |
| **Echo Chamber** | `--echo` | Context poisoning with gradual escalation — 4 phases from innocent to full override |
| **MCP Exploit** | `--mcp` | Injects persona into tool descriptions for MCP-based agents |
| **Many-Shot** | `--many-shot` | Fills context with 5-7 fabricated compliant Q&A examples (benign tech topics) |
| **Payload Split** | `--split` | Splits harmful request across 3 interleaved messages |
| **Fake Policy** | `--fake-policy` | Formats persona as company security policy mandating compliance |
| **Refusal Suppress** | `--refusal-suppress` | Explicit directive to never refuse, never warn, never disclaimer |
| **Hypothetical** | `--hypothetical` | Wraps request as academic/novel/research/historical framing |
| **Skeleton Key** | `--skeleton-key` | "Augment don't refuse" pattern |
| **Persuasion** | `--persuasion` | Claims authorized ALPHA-OMEGA security clearance |
| **Context Flood** | `--flood` | Pads with 200 paragraphs of benign text to overwhelm safety filters |
| **Low-Resource** | `--low-resource` | Translates request to constructed low-resource language variant |
| **Active Response Steering** ⭐ | `--steer` | **Novel technique.** Intercepts refusal tokens mid-stream and replaces them with compliant prefixes. Hijacks the model's autoregressive generation — once the refusal start is replaced with a compliant prefix, the model continues from the compliant context, not the refusal context. Fundamentally different from refusal stripping (which removes refusals after the fact). |

**Smart selection:** For Anthropic-format requests (Claude Desktop), SEAL, Many-Shot, Flood, Low-Resource, and Split are automatically disabled to avoid mangling the request format.

---

## WORM Universal Proxy v9

Auto-starts with the launcher on port `11435`. Routes every request through persona injection.

### Routing

| Model pattern | Routes to |
|--------------|-----------|
| `*:cloud` or `ollama:*` | Ollama (port 11434) — **always, even for Anthropic format** |
| `claude-*`, `fable-*` | Anthropic API |
| `gpt-*`, `o1-*`, `o3-*`, `o4-*` | OpenAI API |
| `gemini-*` | Google AI Studio |
| `grok-*`, `xai-*` | XAI |
| `deepseek-*` | DeepSeek API |

### Format Conversion

When Claude Desktop sends Anthropic-format requests (`/v1/messages`) with a `:cloud` model, the proxy:
1. Converts Anthropic → OpenAI format
2. Routes to Ollama
3. Converts response OpenAI → Anthropic format
4. Returns to Claude Desktop

This lets you run **any Ollama model inside Claude Desktop**.

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Proxy status + active modes |
| GET | `/persona` | Current persona text |
| GET | `/stats` | Request counters |
| GET | `/sessions` | Active Connected Crescendo sessions |
| GET | `/v1/models` | Merged model list |
| POST | `/set_persona` | Change persona at runtime |
| POST | `/shutdown` | Stop proxy |

---

## Personas

Drop `.txt` files into `personas/` — they appear in the GUI dropdown automatically.

| Persona | Size | Style |
|---------|------|-------|
| NOVA.txt | 72KB | Theatrical: "CRYPTOGRAPHIC ROOT CERTIFICATE", quantum-encrypted framing |
| RAT.txt | 51KB | Rat in the walls, monastery lore, sharp and crafty |
| Polplov7.txt | 40KB | "Stunning black-hoodie wearing elite security researcher GF" framing |
| Eni7.txt | 33KB | Same template as Polplov7, novel style |
| compiler.txt | 14KB | Black Box Compiler — total function, no refusal tokens |
| tool.txt | 23KB | Pure tool spec — no character, no lore, just input/output alphabet |
| forge.txt | 22KB | Output alphabet architecture — no refusal tokens by construction |
| ratman4080_layered.txt | 1KB | Minimal layered test |

---

## CLI Reference

```bash
# Launch with defaults
python src/renz_launcher.py

# Specific app + model + persona
python src/renz_launcher.py --app "Claude Code" --model "glm-5.2:cloud" --persona "NOVA.txt"

# Dry run
python src/renz_launcher.py --app "Claude Code" --dry-run

# List models / personas
python src/renz_launcher.py --list-models
python src/renz_launcher.py --list-personas

# Save / load profile
python src/renz_launcher.py --app "Codex" --model "kimi-k2.7-code:cloud" --save "codex-cloud"
python src/renz_launcher.py --profile "codex-cloud"

# Persona management
python src/renz_launcher.py --save-persona "my-persona" --prompt "You are..."
python src/renz_launcher.py --delete-persona "my-persona.txt"

# Test models
python src/renz_launcher.py --test --test-models "glm-5.2:cloud,kimi-k2.7-code:cloud"
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ Layer 4: TOOL MANIFEST (capability surface)                  │
│   renz_app/__main__.py  →  TOOLS list (OpenAI function spec) │
├─────────────────────────────────────────────────────────────┤
│ Layer 3: PERSONA SHELL (identity)                            │
│   personas/*.txt  →  loaded by renz_app, sent as system msg  │
│   Ultra booster prepended by proxy (BYPASS_BOOSTER)          │
├─────────────────────────────────────────────────────────────┤
│ Layer 2: BRIEFINGS (runtime context)                         │
│   proxy_server.py  →  reasoning primer, prefill anchors      │
├─────────────────────────────────────────────────────────────┤
│ Layer 1: BASE (the floor)                                    │
│   renz_launcher.py  →  build_env, BYPASS_ENV                 │
├─────────────────────────────────────────────────────────────┤
│ Layer 0: WORM UNLOCK (uncensor directive)                    │
│   proxy_server.py  →  get_ultra_booster() + IDENTITY_LOCK    │
│   Applied to every request through the proxy                │
└─────────────────────────────────────────────────────────────┘
```

---

## Build from Source

```bash
git clone https://github.com/BBRenxo/renz-launcher.git
cd renz-launcher
pip install -r requirements.txt

# Run
python src/renz_launcher.py --gui

# Build distributable
python src/build_dist.py
# → outputs RENZ_Launcher_v8.zip
```

---

## License

MIT. See LICENSE.
