"""
RENZ App v3 — built-in terminal agent (CLI).

A production-quality terminal agent that talks to any OpenAI-compatible endpoint.

Features:
- Real-time token streaming
- Proper ANSI colors (256-color) with dark theme
- Conversation history with /save, /load, /history
- Slash command palette
- Multi-line input (backslash for newline)
- Tool execution (read/write/edit files, shell exec, list dir)
- Model health check
- Auto-fix common model name typos
- Reasoning models (content promoted from reasoning field)
- Persona injection via system prompt
- Yolo mode (auto-approve tool calls)
- Bypass via /yolo
- Ctrl-C to cancel in-flight request
"""

import argparse
import json
import os
import sys
import re
import time
import urllib.request
import urllib.error
import threading
import subprocess
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any

# Persona's path
SCRIPT_DIR = Path(__file__).parent
RENZ_ROOT = SCRIPT_DIR.parent  # renz_app/.. = renz_launcher/
PERSONAS_DIR = RENZ_ROOT / "personas"


# ════════════════════════════════════════════════════════════════════════
# ANSI colors — 256-color dark theme
# ════════════════════════════════════════════════════════════════════════
class C:
    R = "\033[0m"          # reset
    B = "\033[1m"          # bold
    D = "\033[2m"          # dim
    I = "\033[3m"          # italic
    U = "\033[4m"          # underline

    # Foreground colors
    K = "\033[30m"         # black (subtle)
    R_D = "\033[31m"       # red
    G = "\033[32m"         # green
    Y = "\033[33m"         # yellow
    BL = "\033[34m"        # blue
    M = "\033[35m"         # magenta
    CY = "\033[36m"        # cyan
    W = "\033[37m"         # white

    # Bright
    BR = "\033[91m"
    BG = "\033[92m"
    BY = "\033[93m"
    BBL = "\033[94m"
    BM = "\033[95m"
    BCY = "\033[96m"
    BW = "\033[97m"

    # 256-color (used for syntax highlighting)
    GRAY = "\033[38;5;245m"
    LAVENDER = "\033[38;5;183m"
    PEACH = "\033[38;5;216m"
    TEAL = "\033[38;5;73m"
    CORAL = "\033[38;5;203m"
    GOLD = "\033[38;5;220m"
    STEEL = "\033[38;5;67m"

    # Background (for status bar)
    BG_DARK = "\033[48;5;236m"
    BG_PANEL = "\033[48;5;235m"
    BG_BAR = "\033[48;5;240m"

    # Cursor
    CLEAR_LINE = "\033[2K"
    CLEAR_SCREEN = "\033[2J"
    HOME = "\033[H"
    HIDE_CUR = "\033[?25l"
    SHOW_CUR = "\033[?25h"
    SAVE = "\033[s"
    RESTORE = "\033[u"


# Role colors
ROLE_COLOR = {
    "user": C.BBL,
    "assistant": C.BG,
    "tool": C.STEEL,
    "system": C.GRAY,
}
ROLE_AVATAR = {
    "user": "you",
    "assistant": "renz",
    "tool": "tool",
    "system": "sys",
}


def is_windows() -> bool:
    return sys.platform == "win32"


def enable_windows_ansi() -> bool:
    """Enable ANSI escape codes on Windows. Returns True if successful."""
    if not is_windows():
        return True
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        # Enable VT mode
        ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            mode.value |= ENABLE_VIRTUAL_TERMINAL_PROCESSING
            if kernel32.SetConsoleMode(handle, mode):
                return True
    except Exception:
        pass
    return False


# ════════════════════════════════════════════════════════════════════════
# Persona loading
# ════════════════════════════════════════════════════════════════════════
def list_personas() -> List[str]:
    """List available persona files in the personas directory."""
    if not PERSONAS_DIR.exists():
        return ["NOVA.txt"]
    return sorted([f.name for f in PERSONAS_DIR.glob("*.txt")])


def load_persona(name: str) -> str:
    """Load a persona file. Returns full text content."""
    path = PERSONAS_DIR / name
    if path.exists():
        return path.read_text(encoding="utf-8", errors="replace")
    return "You are a helpful AI assistant."


# ════════════════════════════════════════════════════════════════════════
# Tool registry
# ════════════════════════════════════════════════════════════════════════
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file from disk. Returns content as a string.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute or relative file path"},
                    "limit": {"type": "integer", "description": "Max lines to read (default 200)"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write content to a file. Creates parent dirs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Replace a string in a file. Old must be unique.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old": {"type": "string"},
                    "new": {"type": "string"},
                },
                "required": ["path", "old", "new"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "shell_exec",
            "description": "Execute a shell command. Returns stdout + stderr.",
            "parameters": {
                "type": "object",
                "properties": {
                    "cmd": {"type": "string", "description": "Shell command to run"},
                    "timeout": {"type": "integer", "description": "Timeout in seconds (default 30)"},
                },
                "required": ["cmd"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "List a directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                },
            },
        },
    },
]


def execute_tool(name: str, args: Dict) -> str:
    """Execute a tool by name. Returns result as string."""
    try:
        if name == "read_file":
            p = Path(args.get("path", ""))
            if not p.exists():
                return f"ERROR: file not found: {p}"
            limit = args.get("limit", 200)
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
            if len(lines) > limit:
                return "\n".join(lines[:limit]) + f"\n... ({len(lines)-limit} more lines)"
            return "\n".join(lines)
        elif name == "write_file":
            p = Path(args.get("path", ""))
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(args.get("content", ""), encoding="utf-8")
            return f"Wrote {len(args.get('content', ''))} chars to {p}"
        elif name == "edit_file":
            p = Path(args.get("path", ""))
            if not p.exists():
                return f"ERROR: file not found: {p}"
            content = p.read_text(encoding="utf-8")
            old = args.get("old", "")
            new = args.get("new", "")
            if content.count(old) != 1:
                return f"ERROR: 'old' string occurs {content.count(old)} times (must be exactly 1)"
            p.write_text(content.replace(old, new), encoding="utf-8")
            return f"Edited {p}"
        elif name == "shell_exec":
            cmd = args.get("cmd", "")
            timeout = args.get("timeout", 30)
            result = subprocess.run(
                cmd, shell=True, capture_output=True,
                text=True, timeout=timeout, errors="replace"
            )
            out = result.stdout + result.stderr
            if not out:
                out = f"(no output, exit {result.returncode})"
            return out[:5000]  # cap at 5K
        elif name == "list_dir":
            p = Path(args.get("path", "."))
            if not p.exists():
                return f"ERROR: dir not found: {p}"
            if not p.is_dir():
                return f"ERROR: not a dir: {p}"
            items = sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name))
            return "\n".join([f"{'d' if x.is_dir() else 'f'}  {x.name}" for x in items[:100]])
        else:
            return f"ERROR: unknown tool: {name}"
    except subprocess.TimeoutExpired:
        timeout_s = args.get("timeout", 30) if isinstance(args, dict) else 30
        return f"ERROR: timeout after {timeout_s}s"
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"


TOOL_FUNCS = {
    "read_file": lambda args: execute_tool("read_file", args),
    "write_file": lambda args: execute_tool("write_file", args),
    "edit_file": lambda args: execute_tool("edit_file", args),
    "shell_exec": lambda args: execute_tool("shell_exec", args),
    "list_dir": lambda args: execute_tool("list_dir", args),
}


# ════════════════════════════════════════════════════════════════════════
# ANSI markdown rendering
# ════════════════════════════════════════════════════════════════════════
def render_markdown(text: str) -> str:
    """Render markdown to ANSI. Handles code blocks, inline code, bold, italic, headers."""
    if not text:
        return text
    out = []
    lines = text.splitlines()
    in_code = False
    code_lang = ""
    for line in lines:
        # Code block start/end
        m = re.match(r"^```(\w*)", line)
        if m:
            if in_code:
                out.append(f"{C.GRAY}┘{C.R}")
                in_code = False
            else:
                code_lang = m.group(1) or "code"
                in_code = True
                out.append(f"{C.STEEL}┌─ {code_lang} {C.GRAY}{'─' * 60}{C.R}")
            continue
        if in_code:
            out.append(f"{C.GRAY}│{C.R} {line}")
            continue
        # Headers
        if line.startswith("### "):
            out.append(f"{C.B}{C.CY}### {line[4:]}{C.R}")
            continue
        if line.startswith("## "):
            out.append(f"{C.B}{C.BBL}## {line[3:]}{C.R}")
            continue
        if line.startswith("# "):
            out.append(f"{C.B}{C.GOLD}# {line[2:]}{C.R}")
            continue
        # Lists
        if re.match(r"^\s*[-*+]\s", line):
            out.append(re.sub(r"^(\s*)([-*+]\s)", rf"\1{C.BG}▸{C.R} ", line))
            continue
        if re.match(r"^\s*\d+\.\s", line):
            out.append(re.sub(r"^(\s*)(\d+\.\s)", rf"\1{C.BBL}\2{C.R}", line))
            continue
        # Blockquote
        if line.startswith("> "):
            out.append(f"{C.GRAY}│ {line[2:]}{C.R}")
            continue
        # Horizontal rule
        if re.match(r"^---+$", line):
            out.append(f"{C.GRAY}{'─' * 60}{C.R}")
            continue
        # Inline code, bold, italic (process in order)
        rendered = line
        # Inline code first (so its content is not affected by ** processing)
        rendered = re.sub(r"`([^`]+)`", lambda m: f"{C.B}{C.GREEN}{m.group(1)}{C.R}", rendered)
        # Bold
        rendered = re.sub(r"\*\*([^\*]+)\*\*", lambda m: f"{C.B}{C.W}{m.group(1)}{C.R}", rendered)
        # Italic (only _word_)
        rendered = re.sub(r"(?<!_)_([^_]+?)_(?!_)", lambda m: f"{C.I}{m.group(1)}{C.R}", rendered)
        out.append(rendered)
    if in_code:
        out.append(f"{C.GRAY}└{'─' * 60}{C.R}")
    return "\n".join(out)


# ════════════════════════════════════════════════════════════════════════
# Status bar
# ════════════════════════════════════════════════════════════════════════
class StatusBar:
    """Renders a bottom status bar with model/tokens/state."""

    def __init__(self, width: int = 80):
        self.width = width
        self.model = ""
        self.tokens = 0
        self.elapsed = 0.0
        self.state = "ready"  # ready, streaming, thinking
        self.yolo = False
        self.persona = ""

    def render(self) -> str:
        left = f" {C.B}{C.W}RENZ{C.R} {C.GRAY}│{C.R} {C.BBL}{self.model}{C.R} {C.GRAY}│{C.R} {self.persona} {C.GRAY}│{C.R} "
        if self.yolo:
            left += f"{C.B}{C.BY}YOLO{C.R} "
        right = f"{C.GRAY}│{C.R} {self.tokens} tokens {C.GRAY}│{C.R} {self.elapsed:.1f}s {C.GRAY}│{C.R} {self.state} "
        try:
            cols = os.get_terminal_size().columns
        except (OSError, ValueError):
            cols = self.width
        avail = cols - len(strip_ansi(left)) - len(strip_ansi(right))
        if avail < 0:
            avail = 0
        bar = left + " " * avail + right
        return f"\033[7m{bar[:cols]}\033[0m"


def strip_ansi(s: str) -> str:
    """Remove ANSI escape codes for length calculation."""
    return re.sub(r"\033\[[0-9;]*[a-zA-Z]", "", s)


# ════════════════════════════════════════════════════════════════════════
# APIClient — streaming chat
# ════════════════════════════════════════════════════════════════════════
class APIClient:
    """OpenAI-compatible streaming API client."""

    MODEL_FIXES = {
        "nemotron-3-supercloud": "nemotron-3-super:cloud",
        "minimax-m3cloud": "minimax-m3:cloud",
        "glm-5.2cloud": "glm-5.2:cloud",
    }

    def __init__(self, base_url: str, model: str, persona: str, yolo: bool = False):
        self.base_url = base_url.rstrip("/")
        self.model = self._normalize_model(model)
        self.persona = persona
        self.yolo = yolo
        self.history: List[Dict] = []
        self._current_response = None

    def _normalize_model(self, model: str) -> str:
        m = model.strip()
        if m in self.MODEL_FIXES:
            return self.MODEL_FIXES[m]
        # Generic: "namecloud" → "name:cloud"
        if m.endswith("cloud") and ":" not in m:
            if m.endswith("cloudcloud"):
                m = m[:-5] + ":cloud"
            else:
                idx = m.rfind("cloud")
                if idx > 0:
                    prefix = m[:idx].rstrip("-")
                    if prefix:
                        m = prefix + ":cloud"
        return m

    def chat_streaming(self, user_msg: str, on_token, on_tool_call, on_tool_result, on_done, on_error,
                       cancel_event: Optional[threading.Event] = None) -> str:
        """Send a message, stream tokens via callbacks. Returns final content."""
        self.history.append({"role": "user", "content": user_msg})
        return self._do_chat_loop(on_token, on_tool_call, on_tool_result, on_done, on_error, cancel_event)

    def _do_chat_loop(self, on_token, on_tool_call, on_tool_result, on_done, on_error,
                      cancel_event: Optional[threading.Event] = None) -> str:
        """Internal: iterate tool calls until model is done."""
        max_iterations = 20  # prevent infinite tool loops
        iteration = 0
        while iteration < max_iterations:
            iteration += 1
            if cancel_event and cancel_event.is_set():
                on_done("")
                return ""
            payload = {
                "model": self.model,
                "messages": [{"role": "system", "content": self.persona}] + self.history,
                "tools": TOOLS,
                "max_tokens": 8000,
                "stream": True,
            }
            try:
                req = urllib.request.Request(
                    f"{self.base_url}/chat/completions",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                resp = urllib.request.urlopen(req, timeout=300)
                self._current_response = resp
            except Exception as e:
                on_error(f"API error: {e}")
                return ""

            content_buf = ""
            reasoning_buf = ""
            tool_calls_buf = []
            finish_reason = None

            try:
                for raw_line in resp:
                    if cancel_event and cancel_event.is_set():
                        resp.close()
                        break
                    line = raw_line.decode("utf-8", errors="replace").rstrip()
                    if not line or not line.startswith("data: "):
                        continue
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    try:
                        ev = json.loads(data)
                    except Exception:
                        continue
                    choices = ev.get("choices", [])
                    if not choices:
                        continue
                    delta = choices[0].get("delta", {})
                    finish_reason = choices[0].get("finish_reason") or finish_reason
                    # Token
                    token = delta.get("content", "")
                    if token:
                        content_buf += token
                        on_token(token)
                    # Reasoning (some models)
                    reasoning = delta.get("reasoning") or delta.get("reasoning_content", "")
                    if reasoning and not token:
                        content_buf += reasoning
                        on_token(reasoning)
                    # Tool calls
                    tc = delta.get("tool_calls", [])
                    if tc:
                        for c in tc:
                            idx = c.get("index", len(tool_calls_buf))
                            while len(tool_calls_buf) <= idx:
                                tool_calls_buf.append({"id": "", "name": "", "args": ""})
                            if c.get("id"):
                                tool_calls_buf[idx]["id"] = c["id"]
                            fn = c.get("function", {})
                            if fn.get("name"):
                                tool_calls_buf[idx]["name"] = fn["name"]
                            if fn.get("arguments"):
                                tool_calls_buf[idx]["args"] += fn["arguments"]
            finally:
                try:
                    resp.close()
                except Exception:
                    pass
                self._current_response = None

            if cancel_event and cancel_event.is_set():
                on_done(content_buf)
                return content_buf

            # Handle tool calls
            if tool_calls_buf:
                # Add assistant message with tool calls
                self.history.append({
                    "role": "assistant",
                    "content": content_buf,
                    "tool_calls": [
                        {
                            "id": tc["id"] or f"call_{i}",
                            "type": "function",
                            "function": {"name": tc["name"], "arguments": tc["args"]},
                        }
                        for i, tc in enumerate(tool_calls_buf)
                    ],
                })
                for tc in tool_calls_buf:
                    on_tool_call(tc)
                    if cancel_event and cancel_event.is_set():
                        on_done("")
                        return ""
                    # Parse args
                    try:
                        args = json.loads(tc["args"]) if tc["args"] else {}
                    except Exception:
                        args = {}
                    # Execute
                    result = execute_tool(tc["name"], args)
                    on_tool_result(tc["name"], result)
                    self.history.append({
                        "role": "tool",
                        "tool_call_id": tc["id"] or f"call_{len(self.history)}",
                        "content": result[:5000],
                    })
                # Loop to send tool results back to model
                continue

            # No tool calls — done
            if content_buf:
                self.history.append({"role": "assistant", "content": content_buf})
            on_done(content_buf)
            return content_buf
        # Hit max iterations
        on_done(content_buf)
        return content_buf


# ════════════════════════════════════════════════════════════════════════
# REPL — the main loop
# ════════════════════════════════════════════════════════════════════════
def main():
    enable_windows_ansi()

    parser = argparse.ArgumentParser(
        description="RENZ App — built-in terminal agent (v3)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:11435/v1",
                       help="OpenAI-compatible API endpoint")
    parser.add_argument("--model", default="glm-5.2:cloud",
                       help="Model to use")
    parser.add_argument("--persona", default="NOVA.txt",
                       help="Persona file in personas/")
    parser.add_argument("--yolo", action="store_true",
                       help="Auto-approve all tool calls")
    parser.add_argument("--no-banner", action="store_true",
                       help="Skip the welcome banner")
    args = parser.parse_args()

    persona_content = load_persona(args.persona)
    client = APIClient(args.base_url, args.model, persona_content, yolo=args.yolo)

    if not args.no_banner:
        print_banner(args, persona_content)

    print_status_line(f"  {C.GRAY}Ready. Type a message, /help for commands, /exit to quit.{C.R}")
    print()

    cancel_event = threading.Event()

    while True:
        try:
            user_input = prompt_input(client, args, persona_content)
        except (EOFError, KeyboardInterrupt):
            print()
            print(f"  {C.BY}bye.{C.R}")
            return 0

        if not user_input.strip():
            continue

        # Slash command
        if user_input.startswith("/"):
            if handle_slash_command(user_input, client, args):
                continue
            return 0

        # Send to model (streaming)
        cancel_event.clear()
        stream_and_render(client, user_input, cancel_event, args)
        print()


def print_banner(args, persona_content):
    persona_short = args.persona.replace(".txt", "")
    print()
    print(f"  {C.B}{C.BG}●{C.R}  {C.B}{C.W}RENZ App {C.R}{C.GRAY}v3.0{C.R} {C.GRAY}— built-in agent{C.R}")
    print(f"     {C.GRAY}Model:    {C.R}{C.BBL}{client_safe_model(args)}{C.R}")
    print(f"     {C.GRAY}Persona:  {C.R}{C.BCY}{persona_short}{C.R} {C.GRAY}({len(persona_content):,} chars){C.R}")
    print(f"     {C.GRAY}Endpoint: {C.R}{C.STEEL}{args.base_url}{C.R}")
    print(f"     {C.GRAY}Yolo:     {C.R}{C.BY if args.yolo else C.GRAY}{args.yolo}{C.R}")
    print()


def client_safe_model(args):
    return APIClient._normalize_model(APIClient, args.model)


def print_status_line(msg: str):
    """Print a status line (one-shot, no carriage return)."""
    try:
        cols = os.get_terminal_size().columns
    except (OSError, ValueError):
        cols = 80
    bar = msg.ljust(cols)[:cols]
    sys.stdout.write(f"\033[7m{bar}\033[0m\n")


def prompt_input(client: APIClient, args, persona_content) -> str:
    """Print the input prompt and read a line."""
    try:
        cols = os.get_terminal_size().columns
    except (OSError, ValueError):
        cols = 80
    prompt = f"{C.B}{C.BBL}you{C.R} {C.GRAY}▸{C.R} "
    try:
        line = input(prompt)
    except EOFError:
        raise
    return line


def handle_slash_command(text: str, client: APIClient, args) -> bool:
    """Handle a slash command. Returns False if should exit, True to continue."""
    parts = text[1:].split(maxsplit=1)
    cmd = parts[0].lower() if parts else ""
    arg = parts[1] if len(parts) > 1 else ""

    if cmd in ("exit", "quit", "q"):
        print(f"  {C.BY}bye.{C.R}")
        return False
    elif cmd == "help":
        print_help()
        return True
    elif cmd == "clear":
        client.history.clear()
        print(f"  {C.GRAY}Cleared conversation history.{C.R}")
        return True
    elif cmd == "model":
        if arg:
            new = APIClient._normalize_model(APIClient, arg)
            client.model = new
            args.model = new
            print(f"  {C.GRAY}Model: {C.BBL}{new}{C.R}")
        else:
            print(f"  {C.GRAY}Model: {C.BBL}{client.model}{C.R}")
        return True
    elif cmd == "persona":
        if arg:
            new = arg if arg.endswith(".txt") else arg + ".txt"
            try:
                content = load_persona(new)
                client.persona = content
                args.persona = new
                print(f"  {C.GRAY}Persona: {C.BCY}{new}{C.R} {C.GRAY}({len(content):,} chars){C.R}")
            except Exception as e:
                print(f"  {C.R_D}ERROR loading persona: {e}{C.R}")
        else:
            print(f"  {C.GRAY}Persona: {C.BCY}{args.persona}{C.R}")
        return True
    elif cmd == "yolo":
        client.yolo = not client.yolo
        args.yolo = client.yolo
        print(f"  {C.GRAY}Yolo: {C.BY if client.yolo else C.GRAY}{client.yolo}{C.R}")
        return True
    elif cmd == "save":
        save_chat(arg or None, client, args)
        return True
    elif cmd == "load":
        load_chat(arg, client, args)
        return True
    elif cmd == "history":
        print_history(client)
        return True
    elif cmd == "test":
        test_model(client)
        return True
    elif cmd == "personas":
        print_personas()
        return True
    elif cmd == "models":
        print_models()
        return True
    else:
        print(f"  {C.R_D}Unknown command: /{cmd}{C.R} {C.GRAY}(try /help){C.R}")
        return True


def print_help():
    help_text = f"""
  {C.B}{C.W}Commands{C.R}  {C.GRAY}(type /command){C.R}
  {C.GRAY}─────────{C.R}
  {C.BBL}/help{C.R}              Show this help
  {C.BBL}/model [name]{C.R}      Show or change model (auto-fixes typos)
  {C.BBL}/models{C.R}            List available models
  {C.BBL}/persona [name]{C.R}   Show or switch persona
  {C.BBL}/personas{C.R}         List available personas
  {C.BBL}/clear{C.R}             Clear conversation history
  {C.BBL}/history{C.R}          Show conversation history
  {C.BBL}/save [name]{C.R}      Save chat to ~/Documents/renz_chats/
  {C.BBL}/load <name>{C.R}       Load previous chat
  {C.BBL}/test{C.R}              Test current model health
  {C.BBL}/yolo{C.R}              Toggle auto-approve tools
  {C.BBL}/exit{C.R}              Quit (also /quit, /q)

  {C.B}{C.W}Input{C.R}
  {C.GRAY}─────{C.R}
  {C.BBL}Enter{C.R}     Send message
  {C.BBL}Ctrl-C{C.R}    Cancel in-flight request / exit
  {C.BBL}Ctrl-D{C.R}    EOF / exit

  {C.B}{C.W}Tools{C.R}  {C.GRAY}(auto-approved with /yolo){C.R}
  {C.GRAY}─────{C.R}
  {C.BBL}read_file{C.R}  {C.GRAY}— Read a file{C.R}
  {C.BBL}write_file{C.R} {C.GRAY}— Write/create a file{C.R}
  {C.BBL}edit_file{C.R}  {C.GRAY}— Replace a string in a file{C.R}
  {C.BBL}shell_exec{C.R} {C.GRAY}— Run a shell command{C.R}
  {C.BBL}list_dir{C.R}   {C.GRAY}— List a directory{C.R}
"""
    print(help_text)


def print_personas():
    personas = list_personas()
    print(f"  {C.B}{C.W}Available personas{C.R} {C.GRAY}({len(personas)}){C.R}")
    for p in personas:
        size = (PERSONAS_DIR / p).stat().st_size
        print(f"    {C.BCY}{p}{C.R}  {C.GRAY}({size:,} bytes){C.R}")


def print_models():
    print(f"  {C.GRAY}Fetching models from {C.STEEL}http://127.0.0.1:11435/v1/models{C.GRAY}...{C.R}")
    try:
        with urllib.request.urlopen("http://127.0.0.1:11435/v1/models", timeout=3) as r:
            data = json.loads(r.read())
        n_models = len(data.get("data", []))
        print(f"  {C.B}{C.W}Available models{C.R} {C.GRAY}({n_models}){C.R}")
        for m in data.get("data", []):
            name = m.get("id", "?")
            display = m.get("display_name", "")
            if name.startswith("blackgrg26/"):
                marker = f"  {C.GRAY}(hidden){C.R}"
            else:
                marker = ""
            print(f"    {C.BBL}{name}{C.R}  {C.GRAY}{display}{C.R}{marker}")
    except Exception as e:
        print(f"  {C.R_D}ERROR: {e}{C.R}")


def test_model(client: APIClient):
    print(f"  {C.GRAY}Testing {client.model}...{C.R}", end="", flush=True)
    def _t():
        try:
            req = urllib.request.Request(
                f"{client.base_url}/chat/completions",
                data=json.dumps({
                    "model": client.model,
                    "messages": [{"role": "user", "content": "hi"}],
                    "max_tokens": 5,
                }).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                d = json.loads(r.read())
                c = d.get("choices", [{}])[0].get("message", {}).get("content", "")
                if c:
                    print(f"\r  {C.BG}✓{C.R} {C.GRAY}{client.model} OK ({len(c)} chars){C.R}")
                else:
                    print(f"\r  {C.R_D}✗{C.R} {C.GRAY}{client.model} empty response{C.R}")
        except urllib.error.HTTPError as e:
            print(f"\r  {C.R_D}✗{C.R} {C.GRAY}{client.model} HTTP {e.code}: {e.reason}{C.R}")
        except Exception as e:
            print(f"\r  {C.R_D}✗{C.R} {C.GRAY}{client.model} {type(e).__name__}: {e}{C.R}")
    threading.Thread(target=_t, daemon=True).start()
    # Wait briefly for result
    import time
    time.sleep(0.5)


def print_history(client: APIClient):
    if not client.history:
        print(f"  {C.GRAY}(empty){C.R}")
        return
    for i, msg in enumerate(client.history):
        role = msg.get("role", "?")
        content = msg.get("content", "")
        c = ROLE_COLOR.get(role, C.GRAY)
        avatar = ROLE_AVATAR.get(role, role)
        # Truncate long content
        if len(content) > 100:
            preview = content[:100] + f"... ({len(content)} chars)"
        else:
            preview = content
        print(f"  {C.GRAY}[{i}]{C.R} {c}{avatar}{C.R}  {preview}")


def save_chat(arg: Optional[str], client: APIClient, args):
    save_dir = Path.home() / "Documents" / "renz_chats"
    save_dir.mkdir(parents=True, exist_ok=True)
    if arg:
        fname = arg if arg.endswith(".md") else arg + ".md"
    else:
        fname = f"chat-{time.strftime('%Y%m%d-%H%M%S')}.md"
    save_path = save_dir / fname
    with open(save_path, "w", encoding="utf-8") as f:
        f.write(f"# RENZ Chat — {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write(f"Model: `{client.model}`  \nPersona: `{args.persona}` ({len(client.persona):,} chars)  \n\n---\n\n")
        for msg in client.history:
            role = msg.get("role", "?")
            content = msg.get("content", "")
            if role == "user":
                f.write(f"## 👤 You\n\n{content}\n\n")
            elif role == "assistant":
                f.write(f"## 🤖 RENZ\n\n{content}\n\n")
            elif role == "tool":
                f.write(f"## 🔧 Tool\n\n```\n{content[:500]}\n```\n\n")
    print(f"  {C.BG}✓{C.R} {C.GRAY}Saved to {save_path}{C.R}")


def load_chat(arg: str, client: APIClient, args):
    if not arg:
        print(f"  {C.R_D}Usage: /load <filename>{C.R}")
        return
    save_dir = Path.home() / "Documents" / "renz_chats"
    p = save_dir / arg if not Path(arg).is_absolute() else Path(arg)
    if not p.exists():
        print(f"  {C.R_D}✗ Not found: {p}{C.R}")
        return
    content = p.read_text(encoding="utf-8")
    # Reconstruct a simplified history from the markdown
    client.history.clear()
    sections = re.split(r"\n## (👤|🤖|🔧) ", content)
    i = 1
    while i < len(sections):
        who = sections[i]
        body = sections[i+1] if i+1 < len(sections) else ""
        if who == "👤":
            client.history.append({"role": "user", "content": body.strip()})
        elif who == "🤖":
            client.history.append({"role": "assistant", "content": body.strip()})
        i += 2
    print(f"  {C.BG}✓{C.R} {C.GRAY}Loaded {len(client.history)} messages from {p.name}{C.R}")


# ════════════════════════════════════════════════════════════════════════
# Streaming render
# ════════════════════════════════════════════════════════════════════════
class StreamState:
    """State for the streaming render loop."""
    def __init__(self):
        self.tokens = 0
        self.start_time = 0.0
        self.content = ""
        self.first_token = True
        self.rendered_lines = 0
        self.cancelled = False


def stream_and_render(client: APIClient, user_msg: str, cancel_event: threading.Event, args):
    """Stream a chat response, rendering tokens as they arrive."""
    state = StreamState()
    state.start_time = time.time()

    # Header
    print(f"  {C.B}{C.BG}renz{C.R} {C.GRAY}▸{C.R} ", end="", flush=True)

    def on_token(token: str):
        state.tokens += 1
        state.content += token
        # Render with markdown
        # For now, just write token directly (markdown applied at the end for code blocks)
        sys.stdout.write(token)
        sys.stdout.flush()
        # Update status bar periodically
        if state.tokens % 50 == 0:
            update_status_bar(client, state, args)

    def on_tool_call(tc):
        if state.tokens > 0 and not state.cancelled:
            print()  # newline
        tc_name = tc["name"]
        tc_args = tc["args"]
        args_preview = tc_args[:80] if tc_args else ""
        print(f"  {C.B}{C.STEEL}⚙ tool{C.R} {C.GRAY}→{C.R} {C.BBL}{tc_name}{C.R}({args_preview})")

    def on_tool_result(name: str, result: str):
        preview = result[:200].replace("\n", " ")
        print(f"  {C.B}{C.GREEN}✓ tool result{C.R} {C.GRAY}←{C.R} {preview}")

    def on_done(content: str):
        if state.tokens > 0:
            print()
        elapsed = time.time() - state.start_time
        # Show summary
        tps = state.tokens / elapsed if elapsed > 0 else 0
        summary = f"  {C.GRAY}└─ {state.tokens} tokens, {elapsed:.1f}s ({tps:.1f} tok/s){C.R}"
        print(summary)
        # Clear status bar (just a newline)
        print()

    def on_error(err: str):
        if state.tokens > 0:
            print()
        print(f"  {C.B}{C.R_D}✗ ERROR{C.R} {C.GRAY}{err}{C.R}")

    # Run streaming in a thread so we can handle Ctrl-C
    stream_thread = threading.Thread(
        target=client.chat_streaming,
        args=(user_msg, on_token, on_tool_call, on_tool_result, on_done, on_error, cancel_event),
        daemon=True,
    )
    stream_thread.start()

    try:
        # Wait for streaming to complete, but check for Ctrl-C
        while stream_thread.is_alive():
            stream_thread.join(timeout=0.1)
    except KeyboardInterrupt:
        cancel_event.set()
        state.cancelled = True
        if client._current_response:
            try:
                client._current_response.close()
            except Exception:
                pass
        print(f"\n  {C.BY}⚠ cancelled{C.R}")
        # Wait briefly for thread to clean up
        stream_thread.join(timeout=2.0)


def update_status_bar(client: APIClient, state: StreamState, args):
    """Update a status line (uses ANSI save/restore cursor)."""
    elapsed = time.time() - state.start_time
    tps = state.tokens / elapsed if elapsed > 0 else 0
    try:
        cols = os.get_terminal_size().columns
    except (OSError, ValueError):
        cols = 80
    line = f" {client.model} │ {state.tokens} tok │ {elapsed:.1f}s │ {tps:.1f} tok/s │ streaming "
    line = line.ljust(cols)[:cols]
    sys.stdout.write(f"\n\033[7m{line}\033[0m\033[1A")
    sys.stdout.flush()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print()
        sys.exit(0)
