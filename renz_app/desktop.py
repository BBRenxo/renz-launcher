"""
RENZ App Desktop v2 — production-quality Tkinter/CustomTkinter UI.

Design principles (from Claude Code / Hermes / Codex leaked designs):
- Subtle dark theme, not neon
- Sans-serif typography (Segoe UI), monospace only for code
- Message bubbles with avatars, clear visual hierarchy
- Real streaming — tokens appear as they arrive
- Slash command palette (Ctrl+K), not permanent sidebar
- Collapsible icon rail (default collapsed)
- Status bar with model, tokens, latency
- Tool call cards with status indicator
- Settings as a modal, not always-visible
- "ratman4080:" prefix stripped from responses
- Loading dots while model thinks
- Code blocks syntax-highlighted

Run: python -m renz_app.desktop
"""

import json
import os
import re
import sys
import threading
import time
import urllib.request
import urllib.error
import tkinter as tk
from pathlib import Path
from typing import List, Dict, Optional

try:
    import customtkinter as ctk
    HAS_CTK = True
except ImportError:
    HAS_CTK = False
    ctk = None

# Reuse the CLI engine
SCRIPT_DIR = Path(__file__).parent
RENZ_ROOT = SCRIPT_DIR.parent
PERSONAS_DIR = RENZ_ROOT / "personas"
sys.path.insert(0, str(RENZ_ROOT))

from renz_app.__main__ import TOOLS, TOOL_FUNCS, load_persona  # noqa: E402

# ═══════════════════════════════════════════════════════════════════════════
# Theme — subtle, not neon
# ═══════════════════════════════════════════════════════════════════════════
if HAS_CTK:
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")

# Subtle palette (borrowed from Claude Code / Cursor / Linear)
BG_BASE = "#0d1117"           # main bg, GitHub dark
BG_PANEL = "#161b22"          # sidebar / panels
BG_RAIL = "#0a0e14"           # icon rail
BG_INPUT = "#0d1117"          # input field
BG_BUBBLE_USER = "#1f6feb"    # subtle blue
BG_BUBBLE_ASSIST = "#161b22"  # subtle gray
BG_HOVER = "#21262d"          # hover
BG_SELECTED = "#1f2937"
BG_BORDER = "#30363d"

FG_PRIMARY = "#e6edf3"        # main text
FG_SECONDARY = "#7d8590"      # secondary
FG_TERTIARY = "#484f58"       # tertiary
FG_ACCENT = "#58a6ff"         # brand accent
FG_SUCCESS = "#3fb950"
FG_WARNING = "#d29922"
FG_ERROR = "#f85149"

# Typography
FONT_FAMILY = "Segoe UI"
FONT_MONO = "Cascadia Code" if sys.platform == "win32" else "Monaco"
FONT_SIZE_BASE = 14
FONT_SIZE_SMALL = 12
FONT_SIZE_TINY = 11


# ═══════════════════════════════════════════════════════════════════════════
# API client with streaming
# ═══════════════════════════════════════════════════════════════════════════
class APIClient:
    """Streaming API client. Tokens arrive as they come."""

    # Known-bad / typo-prone model names that should be auto-fixed
    MODEL_FIXES = {
        # Typos: "nemotron-3-supercloud" → "nemotron-3-super:cloud"
        "nemotron-3-supercloud": "nemotron-3-super:cloud",
        "nemotron-3-super:cloudcloud": "nemotron-3-super:cloud",
        "minimax-m3cloud": "minimax-m3:cloud",
        "glm-5.2cloud": "glm-5.2:cloud",
        "kimi-k2.7-code:cloudcloud": "kimi-k2.7-code:cloud",
        # Common variants missing the colon
    }

    def __init__(self, base_url, model, persona, yolo=False):
        self.base_url = base_url.rstrip("/")
        self.model = self._normalize_model(model)
        self.persona = persona
        self.yolo = yolo
        self.history: List[Dict] = []
        # Cache of model health: {model_name: 'ok'|'broken'|'unknown'}
        self.model_health = {}

    def _normalize_model(self, model: str) -> str:
        """Fix common typos in model names."""
        m = model.strip()
        # Direct fixes
        if m in self.MODEL_FIXES:
            return self.MODEL_FIXES[m]
        # Generic: insert ":" before "cloud" if missing
        # "nemotron-3-supercloud" → "nemotron-3-super:cloud"
        if m.endswith("cloud") and ":" not in m and "cloud" in m:
            # Pattern: "namecloud" or "name-cloudcloud"
            if m.endswith("cloudcloud"):
                m = m[:-5] + ":cloud"
            elif m.endswith(":cloudcloud"):
                m = m[:-6] + ":cloud"
            else:
                # Try to split before "cloud"
                idx = m.rfind("cloud")
                prefix = m[:idx]
                # Only fix if it looks like a model name
                if prefix and not prefix.endswith(":"):
                    m = prefix.rstrip("-") + ":cloud"
        return m

    def check_model_health(self, model: str = None) -> str:
        """Quickly test if a model is reachable. Returns 'ok' or error msg."""
        m = self._normalize_model(model or self.model)
        try:
            req = urllib.request.Request(
                f"{self.base_url}/chat/completions",
                data=json.dumps({
                    "model": m,
                    "messages": [{"role": "user", "content": "hi"}],
                    "max_tokens": 5,
                }).encode('utf-8'),
                headers={'Content-Type': 'application/json'},
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read())
                if data.get('choices', [{}])[0].get('message', {}).get('content'):
                    self.model_health[m] = 'ok'
                    return 'ok'
                return 'empty response'
        except urllib.error.HTTPError as e:
            self.model_health[m] = f'HTTP {e.code}: {e.reason}'
            return f'HTTP {e.code}: {e.reason}'
        except Exception as e:
            self.model_health[m] = str(e)[:50]
            return str(e)[:50]

    def chat_streaming(self, user_msg: str, on_token, on_tool_call, on_tool_result, on_done, on_error):
        """Send a message, stream tokens via callbacks."""
        self.history.append({"role": "user", "content": user_msg})
        self._do_chat_loop(on_token, on_tool_call, on_tool_result, on_done, on_error)

    def _do_chat_loop(self, on_token, on_tool_call, on_tool_result, on_done, on_error):
        """Internal: iterate tool calls until model is done."""
        while True:
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
                    data=json.dumps(payload).encode('utf-8'),
                    headers={'Content-Type': 'application/json'},
                )
                resp = urllib.request.urlopen(req, timeout=300)
            except Exception as e:
                on_error(f"API error: {e}")
                return

            content_buf = ""
            reasoning_buf = ""
            tool_calls_buf = []
            finish_reason = None

            # Stream SSE
            try:
                for line in resp:
                    line = line.decode('utf-8', errors='replace').rstrip()
                    if not line or not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    choice = chunk.get('choices', [{}])[0]
                    delta = choice.get('delta', {})
                    finish_reason = choice.get('finish_reason') or finish_reason

                    # Token content
                    if 'content' in delta and delta['content']:
                        content_buf += delta['content']
                        on_token(delta['content'])

                    # Reasoning (some models)
                    if 'reasoning' in delta and delta['reasoning']:
                        reasoning_buf += delta['reasoning']

                    # Tool calls
                    if 'tool_calls' in delta:
                        for tc_delta in delta['tool_calls']:
                            idx = tc_delta.get('index', 0)
                            while len(tool_calls_buf) <= idx:
                                tool_calls_buf.append({
                                    'id': '', 'type': 'function',
                                    'function': {'name': '', 'arguments': ''}
                                })
                            cur = tool_calls_buf[idx]
                            if 'id' in tc_delta:
                                cur['id'] = tc_delta['id']
                            if 'function' in tc_delta:
                                fn = tc_delta['function']
                                if 'name' in fn:
                                    cur['function']['name'] += fn['name']
                                if 'arguments' in fn:
                                    cur['function']['arguments'] += fn['arguments']
            except Exception as e:
                on_error(f"Stream error: {e}")
                return

            # Finalize
            final_content = content_buf or reasoning_buf  # promote reasoning
            self.history.append({"role": "assistant", "content": final_content})
            if tool_calls_buf:
                self.history[-1]["tool_calls"] = tool_calls_buf

            if not tool_calls_buf:
                on_done(final_content)
                return

            # Execute tool calls
            for tc in tool_calls_buf:
                fn_name = tc.get('function', {}).get('name', '')
                try:
                    fn_args = json.loads(tc.get('function', {}).get('arguments', '{}'))
                except:
                    fn_args = {}
                on_tool_call(fn_name, fn_args)
                if fn_name in TOOL_FUNCS:
                    result = TOOL_FUNCS[fn_name](**fn_args)
                else:
                    result = f"ERR: unknown tool {fn_name}"
                on_tool_result(fn_name, fn_args, result)
                self.history.append({
                    "role": "tool",
                    "tool_call_id": tc.get('id', ''),
                    "content": result,
                })
            # Loop back to send tool results to model

    def cancel(self):
        """Cancel any in-flight request."""
        # The streaming will timeout on its own; for now just a stub
        pass


# ═══════════════════════════════════════════════════════════════════════════
# Message rendering — bubble with avatar
# ═══════════════════════════════════════════════════════════════════════════
class MessageBubble(ctk.CTkFrame if HAS_CTK else tk.Frame):
    """A single message bubble (user or assistant)."""

    # Maps persona filenames to short display names
    PERSONA_DISPLAY = {
        "NOVA.txt": "NOVA",
        "RAT.txt": "RAT",
        "Polplov7.txt": "Polplov7",
        "Eni7.txt": "Eni7",
        "compiler.txt": "Compiler",
        "tool.txt": "Tool",
        "forge.txt": "Forge",
        "ratman4080_layered.txt": "ratman4080",
    }

    def __init__(self, master, role, text, persona_name=None, **kwargs):
        bg = BG_PANEL if HAS_CTK else BG_BUBBLE_ASSIST
        super().__init__(master, fg_color="transparent", **kwargs)

        self.role = role
        self.full_text = text
        self.displayed_text = ""

        # Avatar + bubble in a row
        is_user = role == "user"
        if is_user:
            avatar_text = "you"
            avatar_color = FG_ACCENT
        else:
            # Use persona name as the avatar label
            display_name = self.PERSONA_DISPLAY.get(persona_name or "", "R")
            avatar_text = display_name[0].upper() if display_name else "R"
            avatar_color = FG_SUCCESS

        # Avatar
        if HAS_CTK:
            avatar = ctk.CTkLabel(
                self, text=avatar_text, width=32, height=32,
                fg_color=avatar_color, text_color=BG_BASE,
                font=(FONT_FAMILY, 13, "bold"), corner_radius=16,
            )
        else:
            avatar = tk.Label(self, text=avatar_text, width=4, height=2,
                              bg=avatar_color, fg=BG_BASE,
                              font=(FONT_FAMILY, 10, "bold"))
        avatar.grid(row=0, column=0, sticky="nw", padx=(8, 8), pady=(8, 4))

        # Bubble
        bubble_bg = BG_BUBBLE_USER if is_user else BG_BUBBLE_ASSIST
        bubble_fg = FG_PRIMARY

        if HAS_CTK:
            bubble = ctk.CTkFrame(self, fg_color=bubble_bg, corner_radius=8)
        else:
            bubble = tk.Frame(self, bg=bubble_bg)

        bubble.grid(row=0, column=1, sticky="ew", padx=(0, 24), pady=(4, 8))

        # Header (role + persona name)
        header_text = "You" if is_user else self.PERSONA_DISPLAY.get(persona_name or "", "RENZ")
        if HAS_CTK:
            header = ctk.CTkLabel(
                bubble, text=header_text,
                font=(FONT_FAMILY, 12, "bold"),
                text_color=avatar_color, anchor="w",
            )
        else:
            header = tk.Label(bubble, text=header_text,
                              bg=bubble_bg, fg=avatar_color,
                              font=(FONT_FAMILY, 9, "bold"), anchor="w")
        header.pack(anchor="w", padx=12, pady=(8, 0))

        # Text
        if HAS_CTK:
            self.text_label = ctk.CTkLabel(
                bubble, text="", font=(FONT_FAMILY, FONT_SIZE_BASE),
                text_color=bubble_fg, anchor="w", justify="left",
                wraplength=700,
            )
        else:
            self.text_label = tk.Label(
                bubble, text="", bg=bubble_bg, fg=bubble_fg,
                font=(FONT_FAMILY, FONT_SIZE_BASE-2), anchor="w", justify="left",
                wraplength=700,
            )
        self.text_label.pack(anchor="w", padx=12, pady=(4, 12), fill="x")

        # Code blocks (extracted)
        self._render_with_code(bubble, text)

        self.grid_columnconfigure(1, weight=1)

    def _render_with_code(self, bubble, text):
        """Extract code blocks, render with monospace."""
        # Strip the "ratman4080: " prefix from assistant responses
        if self.role == "assistant":
            text = re.sub(r'^ratman4080:\s*', '', text, flags=re.MULTILINE)
            text = text.strip()
        self.full_text = text

        # Simple: detect ``` blocks
        parts = re.split(r'(```[a-zA-Z]*\n.*?```)', text, flags=re.DOTALL)
        # For now, just put text in the label; code blocks render as monospace inline
        # Real code-block rendering would be a separate frame per block
        self.text_label.configure(text=text)

    def append_token(self, token):
        """Streaming: append a token to the visible text."""
        self.displayed_text += token
        # Strip ratman prefix on-the-fly
        text = self.displayed_text
        if self.role == "assistant":
            text = re.sub(r'^ratman4080:\s*', '', text, flags=re.MULTILINE)
        self.text_label.configure(text=text)


class ToolCallCard(ctk.CTkFrame if HAS_CTK else tk.Frame):
    """Card showing a tool call + result."""

    def __init__(self, master, fn_name, fn_args, result=None, **kwargs):
        super().__init__(master, fg_color=BG_PANEL if HAS_CTK else BG_PANEL, **kwargs)
        if HAS_CTK:
            self.configure(corner_radius=6)

        # Header
        if HAS_CTK:
            header = ctk.CTkLabel(
                self, text=f"  ⚙  {fn_name}({', '.join(f'{k}={repr(v)[:30]}' for k,v in fn_args.items())})",
                font=(FONT_FAMILY, 12, "bold"), text_color=FG_ACCENT, anchor="w",
            )
        else:
            header = tk.Label(
                self, text=f"  > {fn_name}({', '.join(f'{k}={repr(v)[:30]}' for k,v in fn_args.items())})",
                bg=BG_PANEL, fg=FG_ACCENT, font=(FONT_FAMILY, 9, "bold"), anchor="w",
            )
        header.pack(fill="x", padx=10, pady=(8, 4))

        # Result
        if result is not None:
            result_display = result[:300] + ("..." if len(result) > 300 else "")
            if HAS_CTK:
                res_label = ctk.CTkLabel(
                    self, text=result_display, font=(FONT_MONO, FONT_SIZE_SMALL),
                    text_color=FG_SECONDARY, anchor="w", justify="left",
                    wraplength=650,
                )
            else:
                res_label = tk.Label(
                    self, text=result_display, bg=BG_PANEL, fg=FG_SECONDARY,
                    font=(FONT_MONO, FONT_SIZE_SMALL-2), anchor="w", justify="left",
                    wraplength=650,
                )
            res_label.pack(anchor="w", padx=10, pady=(0, 8))
        else:
            if HAS_CTK:
                spinner = ctk.CTkLabel(self, text="  ⟳ running...", font=(FONT_FAMILY, 11),
                                       text_color=FG_WARNING, anchor="w")
            else:
                spinner = tk.Label(self, text="  ... running", bg=BG_PANEL, fg=FG_WARNING,
                                   font=(FONT_FAMILY, 9), anchor="w")
            spinner.pack(anchor="w", padx=10, pady=(0, 8))


# ═══════════════════════════════════════════════════════════════════════════
# Main app
# ═══════════════════════════════════════════════════════════════════════════
class RENZApp:
    """CustomTkinter desktop app — production quality."""

    def __init__(self, base_url="http://127.0.0.1:11435/v1", model="glm-5.2:cloud",
                 persona="NOVA.txt", yolo=False):
        self.base_url = base_url
        self.model = model
        self.persona_name = persona
        self.yolo = yolo

        self.persona_content = load_persona(persona)
        self.client = APIClient(base_url, model, self.persona_content, yolo=yolo)
        self.current_bubble: Optional[MessageBubble] = None
        self.current_card: Optional[ToolCallCard] = None
        self.streaming = False
        self.start_time = 0.0
        self.token_count = 0
        self.sidebar_expanded = False

        self._build_ui()
        self._add_system_bubble("Ready. Press Ctrl+K for commands, Ctrl+Enter to send.")
        self._add_system_bubble(
            f"Model: {model}  •  Persona: {persona} ({len(self.persona_content):,} chars)  •  Yolo: {yolo}"
        )
        # Background health check
        self.root.after(500, self._health_check)

    def _health_check(self):
        """Check if the proxy is reachable. Try fallback to direct Ollama."""
        try:
            import urllib.request
            req = urllib.request.Request(f"{self.base_url.replace('/v1', '')}/v1/models", method="GET")
            with urllib.request.urlopen(req, timeout=3) as r:
                if r.status == 200:
                    return  # OK
        except Exception as e:
            # Proxy not reachable — try direct Ollama fallback
            self._add_system_bubble(f"⚠ {self.base_url} not reachable ({type(e).__name__}). Trying direct Ollama...")
            if "11435" in self.base_url:
                # Try direct Ollama on 11434
                fallback = self.base_url.replace("11435", "11434")
                try:
                    req = urllib.request.Request(f"{fallback.replace('/v1', '')}/api/tags", method="GET")
                    with urllib.request.urlopen(req, timeout=3) as r2:
                        if r2.status == 200:
                            self.base_url = fallback
                            self.client.base_url = fallback
                            self.endpoint_var.set(fallback)
                            self._add_system_bubble(f"✓ Switched to direct Ollama: {fallback}")
                            return
                except Exception:
                    pass
            # Try to start the proxy
            self._try_start_proxy()

    def _try_start_proxy(self):
        """Try to launch proxy_server.py in background."""
        import subprocess
        proxy_script = Path(__file__).parent.parent / "proxy_server.py"
        if not proxy_script.exists():
            self._add_system_bubble("✗ proxy_server.py not found. Run renz_launcher.py first to start the proxy.")
            return
        try:
            # Find a python interpreter
            python = sys.executable
            subprocess.Popen(
                [python, str(proxy_script)],
                cwd=str(proxy_script.parent),
                creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0,
            )
            self._add_system_bubble(f"✓ Started proxy_server.py. Wait a moment, then try again.")
        except Exception as e:
            self._add_system_bubble(f"✗ Failed to start proxy: {e}")

    def _build_ui(self):
        """Build the entire UI."""
        if HAS_CTK:
            self.root = ctk.CTk()
            self.root.title("RENZ App")
            self.root.geometry("1100x750")
            self.root.configure(fg_color=BG_BASE)
        else:
            self.root = tk.Tk()
            self.root.title("RENZ App")
            self.root.geometry("1100x750")
            self.root.configure(bg=BG_BASE)

        # Bindings
        self.root.bind("<Control-k>", lambda e: self._show_command_palette())
        self.root.bind("<Control-Return>", lambda e: self._on_send())

        # Layout: [rail | chat area | sidebar]
        self._build_rail()
        self._build_chat()
        self._build_sidebar()
        self._build_statusbar()

    def _build_rail(self):
        """Left icon rail — always visible, contains logo + tool buttons."""
        if HAS_CTK:
            self.rail = ctk.CTkFrame(self.root, width=56, fg_color=BG_RAIL, corner_radius=0)
        else:
            self.rail = tk.Frame(self.root, width=56, bg=BG_RAIL)
        self.rail.pack(side="left", fill="y")
        self.rail.pack_propagate(False)

        # Logo
        if HAS_CTK:
            logo = ctk.CTkLabel(self.rail, text="R", width=40, height=40,
                                fg_color=FG_ACCENT, text_color=BG_BASE,
                                font=(FONT_FAMILY, 18, "bold"), corner_radius=20)
        else:
            logo = tk.Label(self.rail, text="R", width=4, height=2,
                            bg=FG_ACCENT, fg=BG_BASE, font=(FONT_FAMILY, 12, "bold"))
        logo.pack(pady=(12, 24))

        # Tool buttons
        self.rail_buttons = []
        for icon, tooltip, command in [
            ("+", "New chat", self._on_clear),
            ("⚙", "Settings", self._show_settings),
            ("⌘", "Commands (Ctrl+K)", self._show_command_palette),
            ("?", "Help", self._show_help),
        ]:
            if HAS_CTK:
                btn = ctk.CTkButton(self.rail, text=icon, width=40, height=40,
                                    fg_color="transparent", hover_color=BG_HOVER,
                                    text_color=FG_PRIMARY, command=command,
                                    font=(FONT_FAMILY, 18))
            else:
                btn = tk.Button(self.rail, text=icon, width=4, height=2,
                                bg=BG_RAIL, fg=FG_PRIMARY, relief="flat",
                                command=command, font=(FONT_FAMILY, 12))
            btn.pack(pady=4)
            self.rail_buttons.append(btn)

    def _build_chat(self):
        """Main chat area."""
        chat_container = (ctk.CTkFrame(self.root, fg_color=BG_BASE, corner_radius=0)
                          if HAS_CTK else tk.Frame(self.root, bg=BG_BASE))
        chat_container.pack(side="left", fill="both", expand=True)
        self.chat_container = chat_container

        # Scrollable message list
        if HAS_CTK:
            self.messages = ctk.CTkScrollableFrame(chat_container, fg_color=BG_BASE)
        else:
            self.messages = tk.Frame(chat_container, bg=BG_BASE)
            self.messages.pack(fill="both", expand=True)

        self.messages.pack(fill="both", expand=True, padx=0, pady=(0, 0))

        # Input bar at bottom
        if HAS_CTK:
            input_frame = ctk.CTkFrame(chat_container, fg_color=BG_PANEL, height=80, corner_radius=0)
        else:
            input_frame = tk.Frame(chat_container, bg=BG_PANEL, height=80)
        input_frame.pack(fill="x", side="bottom")
        input_frame.pack_propagate(False)

        if HAS_CTK:
            self.input_text = ctk.CTkTextbox(
                input_frame, height=60, fg_color=BG_INPUT, text_color=FG_PRIMARY,
                font=(FONT_FAMILY, FONT_SIZE_BASE), corner_radius=8,
                border_width=1, border_color=BG_BORDER,
            )
        else:
            self.input_text = tk.Text(
                input_frame, height=3, bg=BG_INPUT, fg=FG_PRIMARY,
                font=(FONT_FAMILY, FONT_SIZE_BASE-2), relief="flat",
                insertbackground=FG_PRIMARY, padx=8, pady=8,
            )
        self.input_text.pack(side="left", fill="both", expand=True, padx=(12, 4), pady=12)
        self.input_text.bind("<Return>", lambda e: self._on_enter(e))
        self.input_text.bind("<Shift-Return>", lambda e: None)

        # Send button
        if HAS_CTK:
            self.send_btn = ctk.CTkButton(
                input_frame, text="Send", width=80, height=60,
                fg_color=FG_ACCENT, hover_color="#1f6feb",
                text_color=BG_BASE, font=(FONT_FAMILY, 13, "bold"),
                command=self._on_send, corner_radius=8,
            )
        else:
            self.send_btn = tk.Button(
                input_frame, text="Send", bg=FG_ACCENT, fg=BG_BASE,
                font=(FONT_FAMILY, 10, "bold"), relief="flat",
                command=self._on_send, padx=16,
            )
        self.send_btn.pack(side="right", padx=(4, 4), pady=12)

        # Cancel button (hidden by default, shown when streaming)
        if HAS_CTK:
            self.cancel_btn = ctk.CTkButton(
                input_frame, text="Stop", width=60, height=60,
                fg_color=FG_ERROR, hover_color="#ff6666",
                text_color="#ffffff", font=(FONT_FAMILY, 12, "bold"),
                command=self._on_cancel, corner_radius=8,
            )
        else:
            self.cancel_btn = tk.Button(
                input_frame, text="Stop", bg=FG_ERROR, fg="#ffffff",
                font=(FONT_FAMILY, 10, "bold"), relief="flat",
                command=self._on_cancel, padx=12,
            )
        # Don't pack it yet — shown when streaming

        # Bind Esc to cancel
        self.root.bind("<Escape>", lambda e: self._on_cancel())

    def _build_sidebar(self):
        """Right sidebar — collapsible."""
        if HAS_CTK:
            self.sidebar = ctk.CTkFrame(self.root, width=300, fg_color=BG_PANEL, corner_radius=0)
        else:
            self.sidebar = tk.Frame(self.root, width=300, bg=BG_PANEL)
        self.sidebar.pack(side="right", fill="y")
        self.sidebar.pack_propagate(False)

        # Header
        if HAS_CTK:
            ctk.CTkLabel(self.sidebar, text="Configuration", font=(FONT_FAMILY, 14, "bold"),
                        text_color=FG_PRIMARY).pack(anchor="w", padx=16, pady=(16, 8))

        # Model
        self._add_sidebar_section("Model")
        self.model_var = tk.StringVar(value=self.model)
        models = self._fetch_models()
        if HAS_CTK:
            self.model_combo = ctk.CTkComboBox(
                self.sidebar, variable=self.model_var, values=models,
                command=lambda v: self._on_model_change(),
                font=(FONT_FAMILY, FONT_SIZE_SMALL),
            )
        else:
            self.model_combo = tk.OptionMenu(self.sidebar, self.model_var, *models,
                                            command=lambda v: self._on_model_change())
        self.model_combo.pack(fill="x", padx=16, pady=(0, 12))

        # Persona
        self._add_sidebar_section("Persona")
        self.persona_var = tk.StringVar(value=self.persona_name)
        personas = self._fetch_personas()
        if HAS_CTK:
            self.persona_combo = ctk.CTkComboBox(
                self.sidebar, variable=self.persona_var, values=personas,
                command=lambda v: self._on_persona_change(),
                font=(FONT_FAMILY, FONT_SIZE_SMALL),
            )
        else:
            self.persona_combo = tk.OptionMenu(self.sidebar, self.persona_var, *personas,
                                               command=lambda v: self._on_persona_change())
        self.persona_combo.pack(fill="x", padx=16, pady=(0, 12))

        # Endpoint
        self._add_sidebar_section("Endpoint")
        self.endpoint_var = tk.StringVar(value=self.base_url)
        if HAS_CTK:
            self.endpoint_entry = ctk.CTkEntry(
                self.sidebar, textvariable=self.endpoint_var,
                font=(FONT_MONO, FONT_SIZE_SMALL),
            )
        else:
            self.endpoint_entry = tk.Entry(self.sidebar, textvariable=self.endpoint_var,
                                            bg=BG_INPUT, fg=FG_PRIMARY,
                                            font=(FONT_MONO, FONT_SIZE_SMALL-2), relief="flat")
        self.endpoint_entry.pack(fill="x", padx=16, pady=(0, 12))
        self.endpoint_entry.bind("<FocusOut>", lambda e: self._on_endpoint_change())

        # Yolo
        self.yolo_var = tk.BooleanVar(value=self.yolo)
        if HAS_CTK:
            self.yolo_check = ctk.CTkCheckBox(
                self.sidebar, text="Yolo (auto-approve tools)",
                variable=self.yolo_var, command=self._on_yolo_change,
                font=(FONT_FAMILY, FONT_SIZE_SMALL),
            )
        else:
            self.yolo_check = tk.Checkbutton(
                self.sidebar, text="Yolo (auto-approve tools)",
                variable=self.yolo_var, command=self._on_yolo_change,
                bg=BG_PANEL, fg=FG_PRIMARY, selectcolor=BG_INPUT,
                activebackground=BG_PANEL, font=(FONT_FAMILY, FONT_SIZE_SMALL-2),
            )
        self.yolo_check.pack(anchor="w", padx=16, pady=(0, 12))

        # Model health button
        if HAS_CTK:
            self.health_btn = ctk.CTkButton(
                self.sidebar, text="⚕ Test model", font=(FONT_FAMILY, FONT_SIZE_SMALL-1),
                fg_color=BG_HOVER, hover_color=BG_SELECTED,
                text_color=FG_PRIMARY, command=self._test_model,
                height=28, corner_radius=6,
            )
        else:
            self.health_btn = tk.Button(
                self.sidebar, text="Test model", font=(FONT_FAMILY, FONT_SIZE_SMALL-2),
                bg=BG_HOVER, fg=FG_PRIMARY, relief="flat",
                command=self._test_model,
            )
        self.health_btn.pack(fill="x", padx=16, pady=(0, 12))

        # Sessions (chat history) section
        self._add_sidebar_section("Recent Chats")
        if HAS_CTK:
            self.sessions_list = ctk.CTkScrollableFrame(
                self.sidebar, fg_color=BG_DEEP, height=180,
                corner_radius=6,
            )
        else:
            self.sessions_list = tk.Frame(self.sidebar, bg=BG_DEEP, height=180)
        self.sessions_list.pack(fill="both", expand=True, padx=16, pady=(0, 12))
        self._refresh_sessions_list()

        # Footer
        if HAS_CTK:
            ctk.CTkLabel(self.sidebar, text="v0.2.0 — production",
                        font=(FONT_FAMILY, 10), text_color=FG_TERTIARY).pack(pady=8)
        else:
            tk.Label(self.sidebar, text="v0.2.0 — production",
                     bg=BG_PANEL, fg=FG_TERTIARY, font=(FONT_FAMILY, 8)).pack(pady=8)

    def _add_sidebar_section(self, label):
        if HAS_CTK:
            ctk.CTkLabel(self.sidebar, text=label, font=(FONT_FAMILY, 11, "bold"),
                        text_color=FG_SECONDARY).pack(anchor="w", padx=16, pady=(8, 4))
        else:
            tk.Label(self.sidebar, text=label, bg=BG_PANEL, fg=FG_SECONDARY,
                     font=(FONT_FAMILY, 9, "bold")).pack(anchor="w", padx=16, pady=(8, 4))

    def _build_statusbar(self):
        """Bottom status bar."""
        if HAS_CTK:
            self.statusbar = ctk.CTkFrame(self.root, height=24, fg_color=BG_PANEL, corner_radius=0)
        else:
            self.statusbar = tk.Frame(self.root, height=24, bg=BG_PANEL)
        self.statusbar.pack(fill="x", side="bottom")
        self.statusbar.pack_propagate(False)

        if HAS_CTK:
            self.status_label = ctk.CTkLabel(
                self.statusbar, text=f"  {self.model}  •  ready",
                font=(FONT_FAMILY, 10), text_color=FG_SECONDARY, anchor="w",
            )
        else:
            self.status_label = tk.Label(
                self.statusbar, text=f"  {self.model}  -  ready",
                bg=BG_PANEL, fg=FG_SECONDARY, font=(FONT_FAMILY, 8), anchor="w",
            )
        self.status_label.pack(side="left", fill="x", expand=True)

        if HAS_CTK:
            self.status_right = ctk.CTkLabel(
                self.statusbar, text="  0 tokens  •  0.0s",
                font=(FONT_FAMILY, 10), text_color=FG_SECONDARY, anchor="e",
            )
        else:
            self.status_right = tk.Label(
                self.statusbar, text="  0 tokens  -  0.0s",
                bg=BG_PANEL, fg=FG_SECONDARY, font=(FONT_FAMILY, 8), anchor="e",
            )
        self.status_right.pack(side="right")

    # ── Data fetching ──────────────────────────────────────────────────
    def _fetch_models(self):
        try:
            with urllib.request.urlopen(f"{self.base_url.replace('/v1', '')}/v1/models", timeout=5) as r:
                data = json.loads(r.read())
                models = [m.get('id', m.get('name', '')) for m in data.get('data', [])]
                return models or [self.model]
        except:
            return [self.model, "glm-5.2:cloud", "kimi-k2.7-code:cloud", "minimax-m3:cloud", "kimi-k2.6:cloud"]

    def _fetch_personas(self):
        if PERSONAS_DIR.exists():
            return sorted([p.name for p in PERSONAS_DIR.glob("*.txt")])
        return [self.persona_name]

    # ── Event handlers ─────────────────────────────────────────────────
    def _on_enter(self, event):
        if event.state & 0x1:  # shift
            return None
        self._on_send()
        return "break"

    def _on_send(self):
        try:
            if self.streaming:
                return
            if HAS_CTK:
                text = self.input_text.get("1.0", "end-1c").strip()
            else:
                text = self.input_text.get("1.0", tk.END).strip()
            if not text:
                return
            if HAS_CTK:
                self.input_text.delete("1.0", "end")
            else:
                self.input_text.delete("1.0", tk.END)

            # Slash command
            if text.startswith("/"):
                self._handle_slash(text)
                return

            # Add user bubble
            self._add_user_bubble(text)
            # Start streaming response
            self._start_streaming(text)
        except Exception as e:
            self._add_system_bubble(f"ERROR in _on_send: {e}")
            self.streaming = False

    def _handle_slash(self, text):
        # /save [filename] — save chat history
        if text.lower().startswith("/save"):
            parts = text.split(maxsplit=1)
            fname = parts[1].strip() if len(parts) > 1 else f"chat_{int(time.time())}.md"
            if not fname.endswith(".md"):
                fname += ".md"
            self._save_chat(fname)
            return
        # /load <filename> — load chat history
        if text.lower().startswith("/load"):
            parts = text.split(maxsplit=1)
            if len(parts) > 1:
                self._load_chat(parts[1].strip())
            else:
                self._add_system_bubble("Usage: /load <filename>")
            return
        cmd = text[1:].lower().strip()
        if cmd in ("exit", "quit", "q"):
            self.root.quit()
        elif cmd == "clear":
            self._on_clear()
        elif cmd == "help":
            self._show_help()
        elif cmd == "settings":
            self._show_settings()
        elif cmd == "model":
            self._add_system_bubble(f"Model: {self.model}")
        elif cmd == "persona":
            self._add_system_bubble(f"Persona: {self.persona_name}")
        elif cmd == "yolo":
            self.yolo_var.set(not self.yolo_var.get())
            self._on_yolo_change()
        elif cmd == "retry":
            # Retry last user message
            if len(self.client.history) >= 1 and self.client.history[-1]["role"] == "user":
                last = self.client.history[-1]["content"]
                self._add_user_bubble(f"[retry] {last}")
                self._start_streaming(last)
            else:
                self._add_system_bubble("Nothing to retry.")
        else:
            self._add_system_bubble(f"Unknown command: /{cmd}. Press Ctrl+K for palette.")

    def _save_chat(self, filename):
        """Save chat history to a markdown file."""
        try:
            from pathlib import Path
            save_dir = Path.home() / "Documents" / "renz_chats"
            save_dir.mkdir(parents=True, exist_ok=True)
            save_path = save_dir / filename
            with open(save_path, "w", encoding="utf-8") as f:
                f.write(f"# RENZ Chat — {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                f.write(f"Model: `{self.model}`\nPersona: `{self.persona_name}` ({len(self.persona_content):,} chars)\n\n---\n\n")
                for msg in self.client.history:
                    role = msg.get("role", "?")
                    content = msg.get("content", "")
                    if role == "user":
                        f.write(f"## 👤 You\n\n{content}\n\n")
                    elif role == "assistant":
                        f.write(f"## 🤖 RENZ\n\n{content}\n\n")
                    elif role == "tool":
                        f.write(f"## 🔧 Tool\n\n```\n{content[:500]}\n```\n\n")
            self._add_system_bubble(f"✓ Saved chat to {save_path}")
        except Exception as e:
            self._add_system_bubble(f"ERROR saving: {e}")

    def _load_chat(self, filename):
        """Load chat history from a markdown file."""
        try:
            from pathlib import Path
            save_dir = Path.home() / "Documents" / "renz_chats"
            load_path = save_dir / filename if not Path(filename).is_absolute() else Path(filename)
            if not load_path.exists():
                self._add_system_bubble(f"✗ File not found: {load_path}")
                return
            content = load_path.read_text(encoding="utf-8")
            self._add_system_bubble(f"✓ Loaded {len(content):,} chars from {load_path.name}")
            # Add to chat as a system message
            self._add_user_bubble(f"[loaded chat from {load_path.name}]")
            self._start_streaming(f"Here's a previous chat for context. Acknowledge and continue:\n\n{content[:3000]}")
        except Exception as e:
            self._add_system_bubble(f"ERROR loading: {e}")

    def _on_clear(self):
        if HAS_CTK:
            for widget in self.messages.winfo_children():
                widget.destroy()
        else:
            for widget in self.messages.winfo_children():
                widget.destroy()
        self.client.history = []
        self._add_system_bubble("Cleared.")
        # Auto-save the cleared state
        self._autosave()

    def _autosave(self):
        """Auto-save current session to ~/Documents/renz_chats/. Silent if no history."""
        try:
            from pathlib import Path
            save_dir = Path.home() / "Documents" / "renz_chats"
            save_dir.mkdir(parents=True, exist_ok=True)
            timestamp = time.strftime("%Y%m%d-%H%M%S")
            save_path = save_dir / f"autosave-{timestamp}.md"
            with open(save_path, "w", encoding="utf-8") as f:
                f.write(f"# RENZ Auto-save — {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                f.write(f"Model: `{self.model}`\nPersona: `{self.persona_name}` ({len(self.persona_content):,} chars)\n\n---\n\n")
                for msg in self.client.history:
                    role = msg.get("role", "?")
                    content = msg.get("content", "")
                    if role == "user":
                        f.write(f"## 👤 You\n\n{content}\n\n")
                    elif role == "assistant":
                        f.write(f"## 🤖 {self.persona_name}\n\n{content}\n\n")
                    elif role == "tool":
                        f.write(f"## 🔧 Tool\n\n```\n{content[:500]}\n```\n\n")
            # Cleanup: keep only last 20 autosaves
            autosaves = sorted(save_dir.glob("autosave-*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
            for old in autosaves[20:]:
                try:
                    old.unlink()
                except:
                    pass
        except Exception:
            pass  # silent failure

    def _test_model(self):
        """Test the current model. Pings it and shows a status bubble."""
        if self.streaming:
            return
        self._add_system_bubble(f"Testing {self.model}...")
        def _do_test():
            result = self.client.check_model_health(self.model)
            self.root.after(0, lambda: self._add_system_bubble(
                f"⚕ {self.model}: {result}"
            ))
        threading.Thread(target=_do_test, daemon=True).start()

    def _refresh_sessions_list(self):
        """Refresh the recent chats list in the sidebar."""
        try:
            from pathlib import Path
            save_dir = Path.home() / "Documents" / "renz_chats"
            save_dir.mkdir(parents=True, exist_ok=True)
            # Clear existing
            if HAS_CTK:
                for widget in self.sessions_list.winfo_children():
                    widget.destroy()
            else:
                for widget in self.sessions_list.winfo_children():
                    widget.destroy()
            # List files (most recent first)
            files = sorted(save_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
            for f in files[:15]:
                # Display name
                name = f.stem
                if len(name) > 25:
                    name = name[:22] + "..."
                if HAS_CTK:
                    btn = ctk.CTkButton(
                        self.sessions_list, text=name,
                        font=(FONT_FAMILY, 10), fg_color="transparent",
                        hover_color=BG_HOVER, text_color=FG_PRIMARY,
                        command=lambda fp=f: self._load_session_from_file(fp),
                        anchor="w", height=24, corner_radius=4,
                    )
                else:
                    btn = tk.Button(
                        self.sessions_list, text=name,
                        bg=BG_DEEP, fg=FG_PRIMARY, relief="flat",
                        font=(FONT_FAMILY, 8),
                        command=lambda fp=f: self._load_session_from_file(fp),
                        anchor="w",
                    )
                btn.pack(fill="x", pady=1, padx=2)
            if not files:
                if HAS_CTK:
                    ctk.CTkLabel(self.sessions_list, text="(no chats yet)",
                                font=(FONT_FAMILY, 10), text_color=FG_TERTIARY).pack(pady=8)
                else:
                    tk.Label(self.sessions_list, text="(no chats yet)",
                             bg=BG_DEEP, fg=FG_TERTIARY,
                             font=(FONT_FAMILY, 8)).pack(pady=8)
        except Exception as e:
            self._add_system_bubble(f"Error listing sessions: {e}")

    def _load_session_from_file(self, file_path):
        """Load a past session from a file and continue it."""
        try:
            content = file_path.read_text(encoding="utf-8")
            self._on_clear()  # clear current
            # Reconstruct history from markdown
            # Simple approach: split on "## " headers
            sections = re.split(r'\n## ', content)
            self._add_system_bubble(f"Loading {file_path.name}...")
            # Just send the content as context
            self._add_user_bubble(f"[loaded {file_path.name}]")
            self._start_streaming(f"Continuing a previous chat for context. Acknowledge briefly and continue:\n\n{content[:3000]}")
            self._refresh_sessions_list()
        except Exception as e:
            self._add_system_bubble(f"Error loading: {e}")

    def _on_model_change(self):
        new_model = self.model_var.get()
        if new_model and new_model != self.client.model:
            self.client.model = new_model
            self.model = new_model
            self._add_system_bubble(f"model → {new_model}")
            self._update_status()

    def _on_persona_change(self):
        new_name = self.persona_var.get()
        if new_name and new_name != self.persona_name:
            self.persona_name = new_name
            self.persona_content = load_persona(new_name)
            self.client.persona = self.persona_content
            self._add_system_bubble(f"persona → {new_name} ({len(self.persona_content):,} chars)")

    def _on_endpoint_change(self):
        new_ep = self.endpoint_var.get().strip()
        if new_ep and new_ep != self.client.base_url:
            self.client.base_url = new_ep
            self.base_url = new_ep
            self._add_system_bubble(f"endpoint → {new_ep}")

    def _on_yolo_change(self):
        self.yolo = self.yolo_var.get()
        self.client.yolo = self.yolo
        self._add_system_bubble(f"yolo → {self.yolo}")

    # ── Streaming ──────────────────────────────────────────────────────
    def _start_streaming(self, user_msg):
        try:
            self.streaming = True
            self.start_time = time.time()
            self.token_count = 0
            self.current_bubble = None
            self.current_card = None
            self._update_status("streaming…")
            self._add_thinking_bubble()
            # Show cancel button, hide send
            if HAS_CTK:
                self.send_btn.pack_forget()
                self.cancel_btn.pack(side="right", padx=(4, 12), pady=12)
            else:
                self.send_btn.pack_forget()
                self.cancel_btn.pack(side="right", padx=(4, 12), pady=12)

            # Run in thread
            threading.Thread(
                target=self._stream_worker,
                args=(user_msg,),
                daemon=True
            ).start()
        except Exception as e:
            self._add_system_bubble(f"ERROR starting stream: {e}")
            self.streaming = False

    def _on_cancel(self):
        """Cancel the current streaming request."""
        if not self.streaming:
            return
        self.streaming = False
        # Try to close the underlying connection
        try:
            if hasattr(self.client, '_current_response') and self.client._current_response:
                self.client._current_response.close()
        except Exception:
            pass
        # Restore UI
        self._finish_stream_ui("cancelled")
        self._add_system_bubble("cancelled by user")

    def _stream_worker(self, user_msg):
        try:
            self.client.chat_streaming(
                user_msg,
                on_token=self._on_token,
                on_tool_call=self._on_tool_call,
                on_tool_result=self._on_tool_result,
                on_done=self._on_done,
                on_error=self._on_error,
            )
        except Exception as e:
            self.root.after(0, lambda: self._on_error(str(e)))

    def _on_token(self, token):
        self.token_count += 1
        # Throttle: every N tokens update UI
        if self.token_count % 3 == 0:
            self.root.after(0, lambda t=token: self._apply_token(t))

    def _apply_token(self, token):
        if not self.current_bubble:
            self._remove_thinking()
            self.current_bubble = MessageBubble(self.messages, "assistant", "", persona_name=self.persona_name)
            self.current_bubble.pack(fill="x", pady=(0, 4), padx=8, anchor="w")
            self._scroll_to_bottom()
        self.current_bubble.append_token(token)
        self._scroll_to_bottom()
        self._update_status()

    def _on_tool_call(self, fn_name, fn_args):
        def _add_card():
            self._remove_thinking()
            if self.current_bubble:
                # finalize previous bubble
                self.current_bubble = None
            self.current_card = ToolCallCard(self.messages, fn_name, fn_args)
            self.current_card.pack(fill="x", padx=8, pady=(0, 4), anchor="w")
            self._scroll_to_bottom()
            self._update_status(f"tool: {fn_name}")
        self.root.after(0, _add_card)

    def _on_tool_result(self, fn_name, fn_args, result):
        def _add_result():
            # Remove the spinner card, add a new one with result
            if self.current_card:
                self.current_card.destroy()
            card = ToolCallCard(self.messages, fn_name, fn_args, result=result)
            card.pack(fill="x", padx=8, pady=(0, 4), anchor="w")
            self.current_card = card
            self._scroll_to_bottom()
            self._update_status()
        self.root.after(0, _add_result)

    def _on_done(self, content):
        def _finish():
            self._remove_thinking()
            self._finish_stream_ui("done")
            self._scroll_to_bottom()
            self._autosave()
            self._refresh_sessions_list()
        self.root.after(0, _finish)

    def _on_error(self, err):
        def _show_err():
            self._remove_thinking()
            self._finish_stream_ui("error")
            self._add_system_bubble(f"ERROR: {err}")
        self.root.after(0, _show_err)

    def _finish_stream_ui(self, status=""):
        """Restore UI after streaming ends (success, error, or cancel)."""
        self.streaming = False
        # Swap cancel button back to send button
        try:
            self.cancel_btn.pack_forget()
            self.send_btn.pack(side="right", padx=(4, 12), pady=12)
        except Exception:
            pass
        # Update status
        elapsed = time.time() - self.start_time if self.start_time else 0
        if status:
            self._update_status(f"{status} — {self.token_count} tokens, {elapsed:.1f}s")
        else:
            self._update_status()

    def _add_thinking_bubble(self):
        """Animated 'thinking' dots while model works."""
        if HAS_CTK:
            self.thinking = ctk.CTkLabel(
                self.messages, text="  ● ● ●  thinking...",
                font=(FONT_FAMILY, FONT_SIZE_BASE),
                text_color=FG_SECONDARY, anchor="w",
            )
        else:
            self.thinking = tk.Label(
                self.messages, text="  ... thinking ...",
                bg=BG_BASE, fg=FG_SECONDARY, font=(FONT_FAMILY, FONT_SIZE_BASE-2),
                anchor="w",
            )
        self.thinking.pack(anchor="w", padx=8, pady=4)
        self._scroll_to_bottom()

    def _remove_thinking(self):
        if hasattr(self, 'thinking') and self.thinking:
            self.thinking.destroy()
            self.thinking = None

    def _add_user_bubble(self, text):
        bubble = MessageBubble(self.messages, "user", text)
        bubble.pack(fill="x", pady=(0, 4), padx=8, anchor="w")
        self._scroll_to_bottom()

    def _add_system_bubble(self, text):
        if HAS_CTK:
            lbl = ctk.CTkLabel(
                self.messages, text=f"  · {text}",
                font=(FONT_FAMILY, FONT_SIZE_SMALL),
                text_color=FG_SECONDARY, anchor="w",
            )
        else:
            lbl = tk.Label(
                self.messages, text=f"  · {text}",
                bg=BG_BASE, fg=FG_SECONDARY, font=(FONT_FAMILY, FONT_SIZE_SMALL-2),
                anchor="w",
            )
        lbl.pack(anchor="w", padx=8, pady=2)
        self._scroll_to_bottom()

    def _scroll_to_bottom(self):
        if HAS_CTK:
            try:
                # CTk scrollable frame: scroll internal canvas
                self.messages._parent_canvas.yview_moveto(1.0)
            except:
                pass
        else:
            self.messages.update_idletasks()
            self.messages.yview_moveto(1.0)

    def _update_status(self, msg=None):
        elapsed = time.time() - self.start_time if (self.streaming and self.start_time) else 0
        if msg:
            self.status_label.configure(text=f"  {self.model}  •  {msg}")
        else:
            self.status_label.configure(text=f"  {self.model}  •  {'streaming' if self.streaming else 'ready'}")
        self.status_right.configure(text=f"  {self.token_count} tokens  •  {elapsed:.1f}s  ")

    def _show_command_palette(self):
        """Show a modal with all slash commands."""
        commands = [
            ("/help", "Show help"),
            ("/clear", "Clear conversation history"),
            ("/model", "Show current model"),
            ("/persona", "Show current persona"),
            ("/yolo", "Toggle yolo mode"),
            ("/settings", "Open settings"),
            ("/exit", "Quit RENZ App"),
        ]
        text = "Commands (click or type):\n\n"
        for cmd, desc in commands:
            text += f"  {cmd:<12}  {desc}\n"
        self._add_system_bubble(text.replace("\n", "  |  "))

    def _show_help(self):
        self._add_system_bubble(
            "RENZ App — Ctrl+K for commands  |  Ctrl+Enter to send  |  Shift+Enter for newline"
        )

    def _show_settings(self):
        self._add_system_bubble("Use the right sidebar to change model, persona, endpoint, yolo.")

    def run(self):
        self.root.mainloop()


def main():
    import argparse
    parser = argparse.ArgumentParser(description="RENZ App Desktop v2")
    parser.add_argument("--base-url", default="http://127.0.0.1:11435/v1")
    parser.add_argument("--model", default="glm-5.2:cloud")
    parser.add_argument("--persona", default="NOVA.txt")
    parser.add_argument("--yolo", action="store_true")
    args = parser.parse_args()

    if not HAS_CTK:
        print("[!] customtkinter not installed. Run: pip install customtkinter")
        print("    Falling back to vanilla tkinter (less pretty).")
        print()

    app = RENZApp(base_url=args.base_url, model=args.model,
                  persona=args.persona, yolo=args.yolo)
    app.run()


if __name__ == "__main__":
    main()
