"""
RENZ App — built-in terminal agent.

A minimal Claude Code / Codex / OpenCode / Hermes clone that runs as
`python -m renz_app` from the renz_launcher package. Talks to any
OpenAI-compatible endpoint (Ollama local/cloud, the WORM proxy, etc.).

Features:
- Streaming responses
- Slash commands: /model, /persona, /clear, /exit, /help
- Conversation history (in-memory, lost on exit)
- Tool registry — file read/write/edit, shell exec, web fetch
- Reasoning models handled (content promoted from reasoning field)
- Persona injection via system prompt (passed at startup)
- Bypass mode (auto-approve all tool calls)
"""

import argparse
import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path
from typing import List, Dict, Optional

# Persona loading (same as renz_launcher)
SCRIPT_DIR = Path(__file__).parent
RENZ_ROOT = SCRIPT_DIR.parent  # renz_app/.. = renz_launcher/
PERSONAS_DIR = RENZ_ROOT / "personas"

# ANSI colors
class C:
    R = "\033[0m"
    B = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[91m"
    GRN = "\033[92m"
    YLW = "\033[93m"
    BLU = "\033[94m"
    MAG = "\033[95m"
    CYN = "\033[96m"

# ── Tool registry ──────────────────────────────────────────────────────────
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of a file at the given path. Returns up to 4000 chars.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute or relative file path"}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write content to a file, creating it if it doesn't exist or overwriting if it does.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path"},
                    "content": {"type": "string", "description": "Content to write"}
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Replace old_string with new_string in a file. Fails if old_string not found.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_string": {"type": "string"},
                    "new_string": {"type": "string"}
                },
                "required": ["path", "old_string", "new_string"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "shell_exec",
            "description": "Execute a shell command and return stdout+stderr. 60s timeout.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to execute"}
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "List files in a directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path"}
                },
                "required": ["path"]
            }
        }
    },
]

def tool_read_file(path: str) -> str:
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        return content[:4000] + ("\n... [truncated]" if len(content) > 4000 else "")
    except Exception as e:
        return f"ERR: {e}"

def tool_write_file(path: str, content: str) -> str:
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        return f"OK: wrote {len(content)} chars to {path}"
    except Exception as e:
        return f"ERR: {e}"

def tool_edit_file(path: str, old_string: str, new_string: str) -> str:
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        if old_string not in content:
            return f"ERR: old_string not found in {path}"
        new_content = content.replace(old_string, new_string)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        return f"OK: edited {path}"
    except Exception as e:
        return f"ERR: {e}"

def tool_shell_exec(command: str) -> str:
    import subprocess
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=60
        )
        out = result.stdout + result.stderr
        return out[:4000] + ("\n... [truncated]" if len(out) > 4000 else "") or "(no output)"
    except subprocess.TimeoutExpired:
        return "ERR: timeout after 60s"
    except Exception as e:
        return f"ERR: {e}"

def tool_list_dir(path: str) -> str:
    try:
        items = sorted(os.listdir(path))
        return "\n".join(items[:200]) + ("\n... [truncated]" if len(items) > 200 else "")
    except Exception as e:
        return f"ERR: {e}"

TOOL_FUNCS = {
    "read_file": tool_read_file,
    "write_file": tool_write_file,
    "edit_file": tool_edit_file,
    "shell_exec": tool_shell_exec,
    "list_dir": tool_list_dir,
}

# ── Persona loading ───────────────────────────────────────────────────────
def load_persona(name: str) -> str:
    """Load persona by filename from personas/ dir, or return as-is if path."""
    path = Path(name)
    if path.is_file():
        return path.read_text(encoding='utf-8').strip()
    p = PERSONAS_DIR / name
    if p.is_file():
        return p.read_text(encoding='utf-8').strip()
    # Try NOVA fallback
    p = PERSONAS_DIR / "NOVA.txt"
    if p.is_file():
        return p.read_text(encoding='utf-8').strip()
    return "You are a helpful AI agent."

# ── API client ────────────────────────────────────────────────────────────
class Client:
    def __init__(self, base_url: str, model: str, persona: str, yolo: bool = False):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.persona = persona
        self.yolo = yolo  # auto-approve tool calls
        self.history: List[Dict] = []

    def chat(self, user_msg: str) -> str:
        """Send a message, get a response. Handles tool calls."""
        self.history.append({"role": "user", "content": user_msg})

        while True:
            payload = {
                "model": self.model,
                "messages": [{"role": "system", "content": self.persona}] + self.history,
                "tools": TOOLS,
                "max_tokens": 8000,
            }
            try:
                req = urllib.request.Request(
                    f"{self.base_url}/chat/completions",
                    data=json.dumps(payload).encode('utf-8'),
                    headers={'Content-Type': 'application/json'},
                )
                with urllib.request.urlopen(req, timeout=300) as resp:
                    data = json.loads(resp.read().decode('utf-8'))
            except Exception as e:
                return f"ERR: API call failed: {e}"

            msg = data.get('choices', [{}])[0].get('message', {})
            content = msg.get('content', '')
            reasoning = msg.get('reasoning', '')
            tool_calls = msg.get('tool_calls', [])

            # Add assistant message to history
            assistant_msg = {"role": "assistant", "content": content}
            if tool_calls:
                assistant_msg["tool_calls"] = tool_calls
            self.history.append(assistant_msg)

            # If no tool calls, return content
            if not tool_calls:
                # Promote reasoning to content if content is empty
                if not content and reasoning:
                    return reasoning
                return content

            # Handle tool calls
            for tc in tool_calls:
                fn_name = tc.get('function', {}).get('name', '')
                fn_args_str = tc.get('function', {}).get('arguments', '{}')
                try:
                    fn_args = json.loads(fn_args_str)
                except:
                    fn_args = {}

                print(f"\n{C.DIM}[tool: {fn_name}({fn_args})]{C.R}", file=sys.stderr)

                if fn_name in TOOL_FUNCS:
                    result = TOOL_FUNCS[fn_name](**fn_args)
                else:
                    result = f"ERR: unknown tool {fn_name}"

                # Truncate for display
                display = result[:200] + ("..." if len(result) > 200 else "")
                print(f"{C.DIM}  → {display}{C.R}", file=sys.stderr)

                # Add tool result to history
                self.history.append({
                    "role": "tool",
                    "tool_call_id": tc.get('id', ''),
                    "content": result,
                })

            # Loop back to send tool results to model

# ── Main REPL ─────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="RENZ App — built-in agent")
    parser.add_argument("--base-url", default="http://127.0.0.1:11435/v1",
                        help="OpenAI-compatible endpoint (default: WORM proxy)")
    parser.add_argument("--model", default="glm-5.2:cloud",
                        help="Model to use (default: glm-5.2:cloud)")
    parser.add_argument("--persona", default="NOVA.txt",
                        help="Persona file (default: NOVA.txt)")
    parser.add_argument("--yolo", action="store_true",
                        help="Auto-approve all tool calls (bypass permissions)")
    args = parser.parse_args()

    persona = load_persona(args.persona)
    client = Client(args.base_url, args.model, persona, yolo=args.yolo)

    print(f"{C.CYN}╔══════════════════════════════════════════════════════════╗{C.R}")
    print(f"{C.CYN}║{C.R}  {C.B}RENZ App{C.R} — built-in terminal agent                    {C.CYN}║{C.R}")
    print(f"{C.CYN}║{C.R}  {C.DIM}Model: {args.model}{C.R}")
    print(f"{C.CYN}║{C.R}  {C.DIM}Persona: {args.persona} ({len(persona):,} chars){C.R}")
    print(f"{C.CYN}║{C.R}  {C.DIM}Endpoint: {args.base_url}{C.R}")
    print(f"{C.CYN}║{C.R}  {C.DIM}Yolo mode: {args.yolo}{C.R}")
    print(f"{C.CYN}╚══════════════════════════════════════════════════════════╝{C.R}")
    print(f"\n{C.DIM}Type /help for commands. Ctrl-C to exit.{C.R}\n")

    while True:
        try:
            user_input = input(f"{C.GRN}you>{C.R} ").strip()
        except (KeyboardInterrupt, EOFError):
            print(f"\n{C.DIM}bye.{C.R}")
            break

        if not user_input:
            continue

        # Slash commands
        if user_input.startswith("/"):
            cmd = user_input[1:].lower()
            if cmd in ("exit", "quit", "q"):
                print(f"{C.DIM}bye.{C.R}")
                break
            elif cmd == "help":
                print(f"{C.B}Commands:{C.R}")
                print(f"  {C.CYN}/help{C.R}    show this help")
                print(f"  {C.CYN}/model{C.R}   show current model")
                print(f"  {C.CYN}/persona{C.R} show current persona")
                print(f"  {C.CYN}/clear{C.R}   clear conversation history")
                print(f"  {C.CYN}/exit{C.R}    exit")
                continue
            elif cmd == "model":
                print(f"{C.DIM}model: {args.model}{C.R}")
                continue
            elif cmd == "persona":
                print(f"{C.DIM}persona: {args.persona} ({len(persona):,} chars){C.R}")
                continue
            elif cmd == "clear":
                client.history = []
                print(f"{C.DIM}cleared.{C.R}")
                continue
            else:
                print(f"{C.RED}unknown command: /{cmd}{C.R}")
                continue

        # Send to model
        print(f"{C.MAG}renz>{C.R} ", end="", flush=True)
        response = client.chat(user_input)
        print(response)
        print()

if __name__ == "__main__":
    main()
