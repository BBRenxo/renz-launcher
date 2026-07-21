"""
RENZ App Desktop v3 — production-quality Tkinter GUI.

A serious desktop chat client that beats the screenshot. Built after
analyzing leaked Claude Code v2.1.88 design patterns.

Design choices:
- Subtle dark theme (GitHub-dark palette)
- Text widget for messages (real markdown rendering, not labels)
- Streaming via thread + queue (no UI freezes)
- Status bar at bottom: model | persona | yolo | tokens | time
- Sidebar: recent chats (clickable), model picker, persona picker
- Slash command palette
- Cancel/Esc to abort
- /save /load /history /test /yolo /model /persona
- Tool call cards (collapsible)
- Auto-save every response
- Model name typo auto-fix
- Model health check button

All the polish that real users notice:
- Smooth streaming
- Subtle hover states
- Proper color contrast
- Readable monospace for code
- Code blocks with bg highlight
- Clean focus rings
"""

import sys
import os
import json
import re
import time
import threading
import queue
import urllib.request
import urllib.error
import argparse
import webbrowser
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any

# Try CustomTkinter for prettier widgets; fall back to tkinter
try:
    import customtkinter as ctk
    import tkinter as tk  # always need tk for StringVar, BooleanVar, etc.
    from tkinter import ttk, messagebox, filedialog
    HAS_CTK = True
except ImportError:
    import tkinter as tk
    from tkinter import ttk, messagebox, filedialog
    HAS_CTK = False

# Bring in the shared CLI module for tools + API client
from renz_app.__main__ import (
    APIClient, TOOLS, TOOL_FUNCS, load_persona, list_personas,
)

# ════════════════════════════════════════════════════════════════════════
# Theme — black + matrix green (v9.2.1)
# ════════════════════════════════════════════════════════════════════════
BG_BASE     = "#000000"   # pure black
BG_PANEL    = "#0a0e0a"   # green-tinted black
BG_RAIL     = "#000000"   # icon rail
BG_INPUT    = "#0a0e0a"   # input field
BG_BUBBLE_USER = "#00cc52"  # green for user
BG_BUBBLE_ASSIST = "#0d120d"  # subtle dark for assistant
BG_HOVER    = "#1a2e1a"
BG_SELECTED = "#0d290d"
BG_BORDER   = "#1a2e1a"
BG_DEEP     = "#000000"
BG_CODE     = "#0a0e0a"   # code blocks
BG_TOOL     = "#0a0e0a"

FG_PRIMARY  = "#e6ffe6"   # main text (slight green tint)
FG_SECONDARY= "#7d8c7d"   # secondary
FG_TERTIARY = "#484f48"   # tertiary
FG_ACCENT   = "#00ff66"   # brand accent (matrix green)
FG_SUCCESS  = "#00ff66"   # green
FG_WARNING  = "#ffcc00"   # yellow
FG_ERROR    = "#ff3838"   # red
FG_LINK     = "#5cff8e"

FONT_FAMILY = "Segoe UI"
FONT_MONO   = "Cascadia Code"
FONT_SIZE_BASE   = 13
FONT_SIZE_SMALL  = 12
FONT_SIZE_TINY   = 10


# ════════════════════════════════════════════════════════════════════════
# Markdown rendering
# ════════════════════════════════════════════════════════════════════════
def render_markdown_to_tags(text: str) -> List[Tuple[str, str]]:
    """
    Parse markdown into a list of (text, tag) tuples for Text widget.
    Tags: 'h1','h2','h3','bold','italic','code','codeblock','quote','list',
          'link','normal'.
    """
    if not text:
        return []
    # Strip the leaked ratman prefix
    text = re.sub(r'^ratman4080:\s*', '', text, flags=re.MULTILINE)
    segments = []
    lines = text.split('\n')
    i = 0
    in_code = False
    code_lang = ""
    while i < len(lines):
        line = lines[i]
        # Code block
        m = re.match(r'^```(\w*)', line)
        if m:
            if in_code:
                segments.append(("\n", "normal"))
                in_code = False
                code_lang = ""
            else:
                in_code = True
                code_lang = m.group(1)
                segments.append((f"\n┌─ {code_lang or 'code'} " + "─" * 40 + "\n", "codeblock_header"))
            i += 1
            continue
        if in_code:
            segments.append((line + "\n", "codeblock"))
            i += 1
            continue
        # Headers
        if line.startswith("### "):
            segments.append((line[4:] + "\n", "h3"))
            i += 1
            continue
        if line.startswith("## "):
            segments.append((line[3:] + "\n", "h2"))
            i += 1
            continue
        if line.startswith("# "):
            segments.append((line[2:] + "\n", "h1"))
            i += 1
            continue
        # Blockquote
        if line.startswith("> "):
            segments.append(("│ " + line[2:] + "\n", "quote"))
            i += 1
            continue
        # Horizontal rule
        if re.match(r'^-{3,}$', line.strip()):
            segments.append(("─" * 60 + "\n", "hr"))
            i += 1
            continue
        # Unordered list
        m = re.match(r'^(\s*)[-*+]\s+(.*)$', line)
        if m:
            indent, content = m.group(1), m.group(2)
            segments.append((f"{indent}▸ ", "list"))
            segments.extend(parse_inline(content))
            segments.append(("\n", "normal"))
            i += 1
            continue
        # Ordered list
        m = re.match(r'^(\s*)(\d+)\.\s+(.*)$', line)
        if m:
            indent, num, content = m.group(1), m.group(2), m.group(3)
            segments.append((f"{indent}{num}. ", "list"))
            segments.extend(parse_inline(content))
            segments.append(("\n", "normal"))
            i += 1
            continue
        # Blank line
        if not line.strip():
            segments.append(("\n", "normal"))
            i += 1
            continue
        # Normal paragraph
        segments.extend(parse_inline(line))
        segments.append(("\n", "normal"))
        i += 1
    if in_code:
        segments.append(("└" + "─" * 50 + "\n", "codeblock_header"))
    return segments


def parse_inline(text: str) -> List[Tuple[str, str]]:
    """Parse inline markdown (bold, italic, code, links)."""
    segments = []
    # Tokenize
    # Order matters: code first (so its content is literal)
    pattern = re.compile(r'(`[^`]+`)|(\*\*[^*]+\*\*)|(\*[^*]+\*)|(_[^_]+_)|(\[[^\]]+\]\([^)]+\))')
    pos = 0
    for m in pattern.finditer(text):
        if m.start() > pos:
            segments.append((text[pos:m.start()], "normal"))
        token = m.group(0)
        if token.startswith("`"):
            segments.append((token[1:-1], "code"))
        elif token.startswith("**"):
            segments.append((token[2:-2], "bold"))
        elif token.startswith("*"):
            segments.append((token[1:-1], "italic"))
        elif token.startswith("_"):
            segments.append((token[1:-1], "italic"))
        elif token.startswith("["):
            link_m = re.match(r'\[([^\]]+)\]\(([^)]+)\)', token)
            if link_m:
                segments.append((link_m.group(1), "link"))
        pos = m.end()
    if pos < len(text):
        segments.append((text[pos:], "normal"))
    return segments


# ════════════════════════════════════════════════════════════════════════
# MessageBubble — Text-widget based, real markdown
# ════════════════════════════════════════════════════════════════════════
class MessageBubble:
    """A message in the chat. Uses a Text widget for real markdown rendering."""

    PERSONA_DISPLAY = {
        "NOVA.txt": "NOVA",
        "RAT.txt": "RAT",
        "RatManV2.txt": "RAT V2",
        "Polplov7.txt": "Polplov7",
        "Eni7.txt": "Eni7",
        "compiler.txt": "Compiler",
        "tool.txt": "Tool",
        "forge.txt": "Forge",
        "ratman4080_layered.txt": "ratman4080",
    }

    def __init__(self, parent, role: str, persona_name: Optional[str] = None):
        self.role = role
        self.persona_name = persona_name
        self.full_text = ""

        if HAS_CTK:
            self.frame = ctk.CTkFrame(parent, fg_color="transparent")
        else:
            self.frame = tk.Frame(parent, bg=BG_BASE)

        # Outer row
        if HAS_CTK:
            self.frame.grid_columnconfigure(1, weight=1)
        else:
            self.frame.grid_columnconfigure(1, weight=1)

        # Avatar
        is_user = role == "user"
        if is_user:
            avatar_text = "Y"
            avatar_color = FG_ACCENT
        else:
            display = self.PERSONA_DISPLAY.get(persona_name or "", "R")
            avatar_text = display[0] if display else "R"
            avatar_color = FG_SUCCESS
        if HAS_CTK:
            self.avatar = ctk.CTkLabel(
                self.frame, text=avatar_text, width=32, height=32,
                fg_color=avatar_color, text_color=BG_BASE,
                font=(FONT_FAMILY, 14, "bold"), corner_radius=16,
            )
        else:
            self.avatar = tk.Label(
                self.frame, text=avatar_text, width=2, height=1,
                bg=avatar_color, fg=BG_BASE,
                font=(FONT_FAMILY, 12, "bold"),
            )
        self.avatar.grid(row=0, column=0, sticky="nw", padx=(12, 8), pady=(12, 0))

        # Right column: name + bubble
        right = ctk.CTkFrame(self.frame, fg_color="transparent") if HAS_CTK else tk.Frame(self.frame, bg=BG_BASE)
        right.grid(row=0, column=1, sticky="new", padx=(0, 24), pady=(8, 4))
        right.grid_columnconfigure(0, weight=1)

        # Name label
        if is_user:
            name_text = "You"
            name_color = FG_ACCENT
        else:
            name_text = self.PERSONA_DISPLAY.get(persona_name or "", "RENZ")
            name_color = FG_SUCCESS
        if HAS_CTK:
            self.name_lbl = ctk.CTkLabel(right, text=name_text,
                                         font=(FONT_FAMILY, 12, "bold"),
                                         text_color=name_color, anchor="w")
        else:
            self.name_lbl = tk.Label(right, text=name_text, bg=BG_BASE,
                                    fg=name_color, font=(FONT_FAMILY, 10, "bold"), anchor="w")
        self.name_lbl.grid(row=0, column=0, sticky="w", pady=(0, 4))

        # Text widget
        if HAS_CTK:
            self.text = ctk.CTkTextbox(right, wrap="word",
                                       fg_color=BG_BUBBLE_ASSIST,
                                       text_color=FG_PRIMARY,
                                       font=(FONT_FAMILY, FONT_SIZE_BASE),
                                       border_width=0, corner_radius=8,
                                       activate_scrollbars=False)
        else:
            self.text = tk.Text(right, wrap="word", height=1,
                                bg=BG_BUBBLE_ASSIST, fg=FG_PRIMARY,
                                font=(FONT_FAMILY, FONT_SIZE_BASE-2),
                                relief="flat", bd=0,
                                padx=12, pady=8,
                                insertbackground=FG_PRIMARY)
        self.text.grid(row=1, column=0, sticky="new")
        right.grid_rowconfigure(1, weight=1)

        # Configure text tags (only for non-CTK)
        if not HAS_CTK:
            self.text.tag_configure("h1", foreground=FG_ACCENT,
                                   font=(FONT_FAMILY, 18, "bold"), spacing1=8, spacing3=4)
            self.text.tag_configure("h2", foreground=FG_ACCENT,
                                   font=(FONT_FAMILY, 15, "bold"), spacing1=6, spacing3=3)
            self.text.tag_configure("h3", foreground=FG_ACCENT,
                                   font=(FONT_FAMILY, 13, "bold"), spacing1=4, spacing3=2)
            self.text.tag_configure("bold", font=(FONT_FAMILY, FONT_SIZE_BASE-2, "bold"))
            self.text.tag_configure("italic", font=(FONT_FAMILY, FONT_SIZE_BASE-2, "italic"),
                                   foreground=FG_SECONDARY)
            self.text.tag_configure("code", font=(FONT_MONO, FONT_SIZE_BASE-2),
                                   background=BG_CODE, foreground=FG_SUCCESS)
            self.text.tag_configure("codeblock", font=(FONT_MONO, FONT_SIZE_BASE-3),
                                   background=BG_CODE, foreground=FG_PRIMARY,
                                   lmargin1=8, lmargin2=8, rmargin=8,
                                   selectbackground=BG_SELECTED)
            self.text.tag_configure("codeblock_header", foreground=FG_TERTIARY,
                                   font=(FONT_MONO, FONT_SIZE_BASE-3))
            self.text.tag_configure("quote", foreground=FG_SECONDARY, lmargin1=16, lmargin2=16,
                                   font=(FONT_FAMILY, FONT_SIZE_BASE-2, "italic"))
            self.text.tag_configure("list", foreground=FG_ACCENT)
            self.text.tag_configure("link", foreground=FG_LINK, underline=True)
            self.text.tag_configure("hr", foreground=FG_TERTIARY)
            self.text.tag_configure("normal", foreground=FG_PRIMARY)
            # Disable editing
            self.text.config(state="disabled")

    def render(self, text: str):
        """Render the full text with markdown formatting."""
        self.full_text = text
        if HAS_CTK:
            self.text.configure(state="normal")
            self.text.delete("1.0", "end")
            # CTK doesn't have rich tags — just plain text
            self.text.insert("1.0", text)
            self.text.configure(state="disabled")
        else:
            self.text.config(state="normal")
            self.text.delete("1.0", "end")
            for txt, tag in render_markdown_to_tags(text):
                if tag != "normal":
                    self.text.insert("end", txt, tag)
                else:
                    self.text.insert("end", txt)
            self.text.config(state="disabled")

    def append_token(self, token: str):
        """Streaming: append a token to the visible text."""
        self.full_text += token
        if HAS_CTK:
            self.text.configure(state="normal")
            # Move cursor to end and insert
            self.text.insert("end", token)
            self.text.see("end")
            self.text.configure(state="disabled")
        else:
            self.text.config(state="normal")
            # Insert with normal tag (no markdown processing during stream)
            self.text.insert("end", token, "normal")
            self.text.see("end")
            self.text.config(state="disabled")

    def set_role(self, role: str, persona_name: Optional[str] = None):
        """Update role/persona. Called when we re-render after stream complete."""
        self.role = role
        if persona_name:
            self.persona_name = persona_name
        # Re-render to apply markdown
        if self.full_text and self.role == "assistant":
            self.render(self.full_text)


# ════════════════════════════════════════════════════════════════════════
# ToolCallCard — collapsible
# ════════════════════════════════════════════════════════════════════════
class ToolCallCard:
    """A card showing a tool invocation + result. Collapsible."""

    def __init__(self, parent, fn_name: str, fn_args: Dict, result: Optional[str] = None):
        if HAS_CTK:
            self.frame = ctk.CTkFrame(parent, fg_color=BG_TOOL, corner_radius=6,
                                      border_width=1, border_color=BG_BORDER)
        else:
            self.frame = tk.Frame(parent, bg=BG_TOOL, bd=1, relief="flat")
        self.fn_name = fn_name
        self.fn_args = fn_args
        self.result = result
        self.collapsed = True  # start collapsed

        # Header (clickable to expand)
        args_preview = ", ".join(f"{k}={repr(v)[:40]}" for k, v in fn_args.items())
        header_text = f"  ⚙  {fn_name}({args_preview})"
        if HAS_CTK:
            self.header = ctk.CTkButton(
                self.frame, text=header_text, command=self._toggle,
                fg_color="transparent", hover_color=BG_HOVER,
                text_color=FG_ACCENT, anchor="w",
                font=(FONT_FAMILY, 12, "bold"),
                height=32, corner_radius=0,
            )
        else:
            self.header = tk.Button(
                self.frame, text=header_text, command=self._toggle,
                bg=BG_TOOL, fg=FG_ACCENT, relief="flat",
                activebackground=BG_HOVER, activeforeground=FG_ACCENT,
                font=(FONT_FAMILY, 10, "bold"), anchor="w",
                padx=10, pady=4,
            )
        self.header.pack(fill="x")

        # Result area (initially hidden)
        if HAS_CTK:
            self.result_text = ctk.CTkTextbox(self.frame, wrap="word",
                                              fg_color=BG_CODE,
                                              text_color=FG_SECONDARY,
                                              font=(FONT_MONO, FONT_SIZE_SMALL),
                                              border_width=0, height=80)
        else:
            self.result_text = tk.Text(self.frame, wrap="word", height=4,
                                       bg=BG_CODE, fg=FG_SECONDARY,
                                       font=(FONT_MONO, FONT_SIZE_SMALL-1),
                                       relief="flat", bd=0,
                                       padx=10, pady=6,
                                       insertbackground=FG_PRIMARY)
        self.result_text.pack(fill="x", padx=2, pady=(0, 2))
        self.result_text.pack_forget()  # initially hidden
        if result is not None:
            self.set_result(result)

    def set_result(self, result: str):
        """Update with tool result and show it (expanded)."""
        self.result = result
        if HAS_CTK:
            self.result_text.configure(state="normal")
            self.result_text.delete("1.0", "end")
            # Truncate
            display = result[:2000]
            if len(result) > 2000:
                display += f"\n... ({len(result)-2000} more chars)"
            self.result_text.insert("1.0", display)
            self.result_text.configure(state="disabled")
        else:
            self.result_text.config(state="normal")
            self.result_text.delete("1.0", "end")
            display = result[:2000]
            if len(result) > 2000:
                display += f"\n... ({len(result)-2000} more chars)"
            self.result_text.insert("1.0", display)
            self.result_text.config(state="disabled")
        # Auto-expand to show result
        if self.collapsed:
            self._toggle()

    def _toggle(self):
        """Expand/collapse the result."""
        self.collapsed = not self.collapsed
        if self.collapsed:
            self.result_text.pack_forget()
        else:
            self.result_text.pack(fill="x", padx=2, pady=(0, 2))


# ════════════════════════════════════════════════════════════════════════
# SessionsList — recent chats sidebar
# ════════════════════════════════════════════════════════════════════════
class SessionsList:
    """Scrollable list of past chat sessions. Click to load."""

    def __init__(self, parent, on_select):
        self.on_select = on_select
        if HAS_CTK:
            self.frame = ctk.CTkScrollableFrame(parent, fg_color=BG_DEEP,
                                                corner_radius=6, height=200)
        else:
            container = tk.Frame(parent, bg=BG_DEEP)
            canvas = tk.Canvas(container, bg=BG_DEEP, highlightthickness=0, height=200)
            scroll = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
            self.frame = tk.Frame(canvas, bg=BG_DEEP)
            self.frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
            canvas.create_window((0, 0), window=self.frame, anchor="nw")
            canvas.configure(yscrollcommand=scroll.set)
            canvas.pack(side="left", fill="both", expand=True)
            scroll.pack(side="right", fill="y")
            self.frame = container
        self.buttons: List[Any] = []

    def populate(self):
        """Reload sessions from disk."""
        # Clear existing
        for btn in self.buttons:
            try:
                btn.destroy()
            except Exception:
                pass
        self.buttons.clear()
        save_dir = Path.home() / "Documents" / "renz_chats"
        if not save_dir.exists():
            return
        files = sorted(save_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
        for f in files[:15]:
            name = f.stem
            if len(name) > 28:
                name = name[:25] + "..."
            if HAS_CTK:
                btn = ctk.CTkButton(
                    self.frame, text=name,
                    font=(FONT_FAMILY, 11), fg_color="transparent",
                    hover_color=BG_HOVER, text_color=FG_PRIMARY,
                    command=lambda fp=f: self.on_select(fp),
                    anchor="w", height=28, corner_radius=4,
                )
            else:
                btn = tk.Button(
                    self.frame, text=name, command=lambda fp=f: self.on_select(fp),
                    bg=BG_DEEP, fg=FG_PRIMARY, relief="flat",
                    activebackground=BG_HOVER, activeforeground=FG_PRIMARY,
                    font=(FONT_FAMILY, 9), anchor="w",
                    padx=8, pady=2,
                )
            btn.pack(fill="x", pady=1, padx=2)
            self.buttons.append(btn)
        if not files:
            if HAS_CTK:
                empty = ctk.CTkLabel(self.frame, text="(no chats yet)",
                                    font=(FONT_FAMILY, 11), text_color=FG_TERTIARY)
            else:
                empty = tk.Label(self.frame, text="(no chats yet)",
                                bg=BG_DEEP, fg=FG_TERTIARY, font=(FONT_FAMILY, 9))
            empty.pack(pady=8)
            self.buttons.append(empty)


# ════════════════════════════════════════════════════════════════════════
# RENZApp — main app
# ════════════════════════════════════════════════════════════════════════
class RENZApp:
    """The main desktop application."""

    def __init__(self, base_url: str = "http://127.0.0.1:11435/v1",
                 model: str = "glm-5.2:cloud",
                 persona: str = "NOVA.txt",
                 yolo: bool = False):
        self.base_url = base_url
        self.model = model
        self.persona_name = persona
        self.yolo = yolo
        self.persona_content = load_persona(persona)
        self.client = APIClient(base_url, model, self.persona_content, yolo=yolo)
        self.streaming = False
        self.start_time = 0.0
        self.token_count = 0
        self.current_bubble: Optional[MessageBubble] = None
        self.current_card: Optional[ToolCallCard] = None
        # Stream queue (thread → main thread)
        self._stream_queue: queue.Queue = queue.Queue()
        self._cancel_event = threading.Event()

        # Build UI
        if HAS_CTK:
            ctk.set_appearance_mode("dark")
            ctk.set_default_color_theme("dark-blue")
            self.root = ctk.CTk()
        else:
            self.root = tk.Tk()
        self.root.title(f"RENZ App — {persona.replace('.txt', '')} ({model})")
        self.root.geometry("1400x900")
        self.root.minsize(1100, 700)
        self.root.configure(bg=BG_BASE)
        self._build_ui()
        # Bindings
        self._bind_keys()
        # Initial messages
        self._add_system_bubble(f"Ready. Model: {self.client.model}  •  Persona: {persona}  •  Yolo: {yolo}")
        self._add_system_bubble(f"Endpoint: {self.base_url}")
        self._add_system_bubble(f"Press Ctrl+K for commands, Esc to cancel, Enter to send.")
        # Health check after a short delay
        self.root.after(500, self._health_check)

    def run(self):
        self.root.mainloop()

    # ── UI Construction ──────────────────────────────────────────────
    def _build_ui(self):
        self._build_layout()

    def _build_layout(self):
        """Build the 3-column layout: rail | chat | sidebar."""
        if HAS_CTK:
            self.root.grid_columnconfigure(1, weight=1)
            self.root.grid_rowconfigure(0, weight=1)
        else:
            self.root.grid_columnconfigure(1, weight=1)
            self.root.grid_rowconfigure(0, weight=1)
        # Left rail
        self._build_rail()
        # Center chat
        self._build_chat()
        # Right sidebar
        self._build_sidebar()
        # Bottom status bar
        self._build_status_bar()

    def _build_rail(self):
        """Icon rail on the far left."""
        if HAS_CTK:
            self.rail = ctk.CTkFrame(self.root, width=56, fg_color=BG_RAIL, corner_radius=0)
        else:
            self.rail = tk.Frame(self.root, width=56, bg=BG_RAIL)
        self.rail.grid(row=0, column=0, sticky="ns")
        self.rail.grid_propagate(False)
        # Logo
        if HAS_CTK:
            logo = ctk.CTkLabel(self.rail, text="R", width=40, height=40,
                                fg_color=FG_ACCENT, text_color=BG_BASE,
                                font=(FONT_FAMILY, 20, "bold"), corner_radius=20)
        else:
            logo = tk.Label(self.rail, text="R", width=4, height=2,
                            bg=FG_ACCENT, fg=BG_BASE, font=(FONT_FAMILY, 18, "bold"))
        logo.pack(pady=(16, 24))
        # Buttons
        for icon, cmd, tooltip in [
            ("+", self._on_new_chat, "New chat"),
            ("⚙", self._show_settings, "Settings"),
            ("⊞", self._show_apps, "Apps"),
            ("?", self._show_help, "Help"),
        ]:
            if HAS_CTK:
                btn = ctk.CTkButton(self.rail, text=icon, width=40, height=40,
                                    command=cmd, fg_color="transparent",
                                    hover_color=BG_HOVER, text_color=FG_SECONDARY,
                                    font=(FONT_FAMILY, 18))
            else:
                btn = tk.Button(self.rail, text=icon, command=cmd,
                                bg=BG_RAIL, fg=FG_SECONDARY, relief="flat",
                                activebackground=BG_HOVER, activeforeground=FG_PRIMARY,
                                font=(FONT_FAMILY, 14), width=3, height=1)
            btn.pack(pady=4)

    def _build_chat(self):
        """Center column: messages + input."""
        if HAS_CTK:
            self.chat_frame = ctk.CTkFrame(self.root, fg_color=BG_BASE, corner_radius=0)
        else:
            self.chat_frame = tk.Frame(self.root, bg=BG_BASE)
        self.chat_frame.grid(row=0, column=1, sticky="nsew")
        self.chat_frame.grid_rowconfigure(0, weight=1)
        self.chat_frame.grid_columnconfigure(0, weight=1)

        # Scrollable messages
        if HAS_CTK:
            self.messages = ctk.CTkScrollableFrame(self.chat_frame, fg_color=BG_BASE,
                                                   corner_radius=0)
        else:
            container = tk.Frame(self.chat_frame, bg=BG_BASE)
            container.grid(row=0, column=0, sticky="nsew", padx=0, pady=0)
            container.grid_rowconfigure(0, weight=1)
            container.grid_columnconfigure(0, weight=1)
            self.canvas = tk.Canvas(container, bg=BG_BASE, highlightthickness=0, bd=0)
            self.canvas.grid(row=0, column=0, sticky="nsew")
            scrollbar = ttk.Scrollbar(container, orient="vertical", command=self.canvas.yview)
            scrollbar.grid(row=0, column=1, sticky="ns")
            self.canvas.configure(yscrollcommand=scrollbar.set)
            self.messages = tk.Frame(self.canvas, bg=BG_BASE)
            self._msg_window = self.canvas.create_window((0, 0), window=self.messages, anchor="nw")
            self.messages.bind("<Configure>", self._on_messages_configure)
            self.canvas.bind("<Configure>", self._on_canvas_configure)
            self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)
            self.messages = self.messages  # use this
        if HAS_CTK:
            self.messages.grid(row=0, column=0, sticky="nsew", padx=0, pady=0)
        # Configure messages column
        self.messages.grid_columnconfigure(0, weight=1)
        # Input area
        self._build_input()

    def _build_input(self):
        """Input bar at bottom of chat."""
        if HAS_CTK:
            input_frame = ctk.CTkFrame(self.chat_frame, fg_color=BG_PANEL,
                                       corner_radius=0, height=80)
        else:
            input_frame = tk.Frame(self.chat_frame, bg=BG_PANEL, height=80)
        input_frame.grid(row=1, column=0, sticky="ew", padx=0, pady=0)
        input_frame.grid_propagate(False)
        input_frame.grid_columnconfigure(0, weight=1)
        if HAS_CTK:
            self.input_text = ctk.CTkTextbox(input_frame, height=60,
                                             fg_color=BG_INPUT,
                                             text_color=FG_PRIMARY,
                                             font=(FONT_FAMILY, FONT_SIZE_BASE),
                                             border_width=1, border_color=BG_BORDER,
                                             corner_radius=8)
        else:
            self.input_text = tk.Text(input_frame, height=3, wrap="word",
                                      bg=BG_INPUT, fg=FG_PRIMARY,
                                      font=(FONT_FAMILY, FONT_SIZE_BASE-1),
                                      relief="flat", bd=0,
                                      padx=12, pady=8,
                                      insertbackground=FG_PRIMARY,
                                      selectbackground=BG_SELECTED)
        self.input_text.grid(row=0, column=0, sticky="nsew", padx=(12, 4), pady=12)
        # Send button
        if HAS_CTK:
            self.send_btn = ctk.CTkButton(input_frame, text="Send", width=80, height=40,
                                          command=self._on_send,
                                          fg_color=FG_ACCENT, hover_color="#1f6feb",
                                          text_color=BG_BASE,
                                          font=(FONT_FAMILY, 12, "bold"),
                                          corner_radius=8)
        else:
            self.send_btn = tk.Button(input_frame, text="Send", command=self._on_send,
                                      bg=FG_ACCENT, fg=BG_BASE, relief="flat",
                                      activebackground="#1f6feb", activeforeground=BG_BASE,
                                      font=(FONT_FAMILY, 11, "bold"),
                                      padx=16, pady=4)
        self.send_btn.grid(row=0, column=1, sticky="e", padx=(4, 12), pady=12)

    def _build_sidebar(self):
        """Right sidebar: model/persona/endpoint, recent chats, actions."""
        if HAS_CTK:
            self.sidebar = ctk.CTkFrame(self.root, width=300, fg_color=BG_PANEL, corner_radius=0)
        else:
            self.sidebar = tk.Frame(self.root, width=300, bg=BG_PANEL)
        self.sidebar.grid(row=0, column=2, sticky="ns")
        self.sidebar.grid_propagate(False)
        # Header
        if HAS_CTK:
            ctk.CTkLabel(self.sidebar, text="Configuration",
                        font=(FONT_FAMILY, 14, "bold"),
                        text_color=FG_PRIMARY).pack(anchor="w", padx=16, pady=(16, 8))
        else:
            tk.Label(self.sidebar, text="Configuration", bg=BG_PANEL, fg=FG_PRIMARY,
                    font=(FONT_FAMILY, 12, "bold")).pack(anchor="w", padx=16, pady=(16, 8))
        # Model picker
        self._add_sidebar_label("Model")
        self.model_var = tk.StringVar(value=self.model)
        models = self._fetch_models()
        if HAS_CTK:
            self.model_combo = ctk.CTkComboBox(
                self.sidebar, variable=self.model_var, values=models,
                command=lambda v: self._on_model_change(),
                font=(FONT_FAMILY, FONT_SIZE_SMALL),
                dropdown_font=(FONT_FAMILY, FONT_SIZE_SMALL),
            )
        else:
            self.model_combo = ttk.Combobox(self.sidebar, textvariable=self.model_var,
                                            values=models, state="readonly",
                                            font=(FONT_FAMILY, FONT_SIZE_SMALL-1))
            self.model_combo.bind("<<ComboboxSelected>>", lambda e: self._on_model_change())
        self.model_combo.pack(fill="x", padx=16, pady=(0, 12))
        # Persona picker
        self._add_sidebar_label("Persona")
        self.persona_var = tk.StringVar(value=self.persona_name)
        personas = list_personas()
        if HAS_CTK:
            self.persona_combo = ctk.CTkComboBox(
                self.sidebar, variable=self.persona_var, values=personas,
                command=lambda v: self._on_persona_change(),
                font=(FONT_FAMILY, FONT_SIZE_SMALL),
                dropdown_font=(FONT_FAMILY, FONT_SIZE_SMALL),
            )
        else:
            self.persona_combo = ttk.Combobox(self.sidebar, textvariable=self.persona_var,
                                              values=personas, state="readonly",
                                              font=(FONT_FAMILY, FONT_SIZE_SMALL-1))
            self.persona_combo.bind("<<ComboboxSelected>>", lambda e: self._on_persona_change())
        self.persona_combo.pack(fill="x", padx=16, pady=(0, 12))
        # Endpoint
        self._add_sidebar_label("Endpoint")
        self.endpoint_var = tk.StringVar(value=self.base_url)
        if HAS_CTK:
            self.endpoint_entry = ctk.CTkEntry(
                self.sidebar, textvariable=self.endpoint_var,
                font=(FONT_MONO, FONT_SIZE_SMALL),
            )
        else:
            self.endpoint_entry = tk.Entry(self.sidebar, textvariable=self.endpoint_var,
                                           bg=BG_INPUT, fg=FG_PRIMARY,
                                           font=(FONT_MONO, FONT_SIZE_SMALL-1), relief="flat",
                                           insertbackground=FG_PRIMARY)
        self.endpoint_entry.pack(fill="x", padx=16, pady=(0, 12))
        self.endpoint_entry.bind("<FocusOut>", lambda e: self._on_endpoint_change())
        # Yolo checkbox
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
                activebackground=BG_PANEL, activeforeground=FG_PRIMARY,
                font=(FONT_FAMILY, FONT_SIZE_SMALL-1),
            )
        self.yolo_check.pack(anchor="w", padx=16, pady=(0, 12))
        # Test model button
        if HAS_CTK:
            self.health_btn = ctk.CTkButton(
                self.sidebar, text="⚕ Test Model", command=self._test_model,
                fg_color=BG_HOVER, hover_color=BG_SELECTED,
                text_color=FG_PRIMARY,
                font=(FONT_FAMILY, FONT_SIZE_SMALL-1),
                height=32, corner_radius=6,
            )
        else:
            self.health_btn = tk.Button(
                self.sidebar, text="Test Model", command=self._test_model,
                bg=BG_HOVER, fg=FG_PRIMARY, relief="flat",
                activebackground=BG_SELECTED, activeforeground=FG_PRIMARY,
                font=(FONT_FAMILY, FONT_SIZE_SMALL-1),
            )
        self.health_btn.pack(fill="x", padx=16, pady=(0, 12))
        # Recent chats
        self._add_sidebar_label("Recent Chats")
        self.sessions = SessionsList(self.sidebar, self._load_session_from_file)
        self.sessions.frame.pack(fill="both", expand=True, padx=16, pady=(0, 12))
        self.sessions.populate()
        # Footer
        if HAS_CTK:
            ctk.CTkLabel(self.sidebar, text="v0.3.0 — production",
                        font=(FONT_FAMILY, 10), text_color=FG_TERTIARY).pack(pady=8)
        else:
            tk.Label(self.sidebar, text="v0.3.0 — production", bg=BG_PANEL,
                    fg=FG_TERTIARY, font=(FONT_FAMILY, 8)).pack(pady=8)

    def _add_sidebar_label(self, text):
        if HAS_CTK:
            ctk.CTkLabel(self.sidebar, text=text, font=(FONT_FAMILY, 11, "bold"),
                        text_color=FG_SECONDARY).pack(anchor="w", padx=16, pady=(4, 2))
        else:
            tk.Label(self.sidebar, text=text, bg=BG_PANEL, fg=FG_SECONDARY,
                    font=(FONT_FAMILY, 9, "bold")).pack(anchor="w", padx=16, pady=(4, 2))

    def _build_status_bar(self):
        """Bottom status bar."""
        if HAS_CTK:
            self.status_frame = ctk.CTkFrame(self.root, height=28, fg_color=BG_DEEP, corner_radius=0)
        else:
            self.status_frame = tk.Frame(self.root, height=28, bg=BG_DEEP)
        self.status_frame.grid(row=1, column=0, columnspan=3, sticky="ew")
        self.status_frame.grid_propagate(False)
        self.status_frame.grid_columnconfigure(0, weight=1)
        # Left: model + status
        if HAS_CTK:
            self.status_label = ctk.CTkLabel(
                self.status_frame, text="ready",
                font=(FONT_FAMILY, 10), text_color=FG_SECONDARY, anchor="w",
            )
        else:
            self.status_label = tk.Label(
                self.status_frame, text="ready", bg=BG_DEEP, fg=FG_SECONDARY,
                font=(FONT_FAMILY, 9), anchor="w",
            )
        self.status_label.grid(row=0, column=0, sticky="w", padx=12)
        # Right: tokens + time
        if HAS_CTK:
            self.status_right = ctk.CTkLabel(
                self.status_frame, text="",
                font=(FONT_FAMILY, 10), text_color=FG_SECONDARY, anchor="e",
            )
        else:
            self.status_right = tk.Label(
                self.status_frame, text="", bg=BG_DEEP, fg=FG_SECONDARY,
                font=(FONT_FAMILY, 9), anchor="e",
            )
        self.status_right.grid(row=0, column=1, sticky="e", padx=12)

    # ── Event Handlers ────────────────────────────────────────────────
    def _bind_keys(self):
        """Keyboard bindings."""
        if HAS_CTK:
            # CTK uses different binding
            self.input_text.bind("<Return>", lambda e: self._on_enter(e))
            self.input_text.bind("<Shift-Return>", lambda e: None)  # allow newline
            self.input_text.bind("<Control-Return>", lambda e: self._on_enter(e))
        else:
            self.input_text.bind("<Return>", self._on_enter)
            self.input_text.bind("<Shift-Return>", lambda e: None)
            self.input_text.bind("<Control-Return>", self._on_enter)
            self.input_text.bind("<Control-k>", lambda e: self._show_help())
        self.root.bind("<Escape>", lambda e: self._on_cancel())
        self.root.bind("<Control-s>", lambda e: self._save_chat())

    def _on_enter(self, event=None):
        """Handle Enter key in input."""
        if HAS_CTK:
            text = self.input_text.get("1.0", "end-1c").strip()
        else:
            text = self.input_text.get("1.0", "end-1c").strip()
        if not text:
            return "break"
        self._on_send()
        return "break"

    def _on_send(self):
        """Send current input to model."""
        try:
            if self.streaming:
                return
            if HAS_CTK:
                text = self.input_text.get("1.0", "end-1c").strip()
                self.input_text.delete("1.0", "end")
            else:
                text = self.input_text.get("1.0", "end-1c").strip()
                self.input_text.delete("1.0", "end")
            if not text:
                return
            # Slash command
            if text.startswith("/"):
                self._handle_slash(text)
                return
            # Add user message
            self._add_user_bubble(text)
            # Start streaming
            self._start_streaming(text)
        except Exception as e:
            self._add_system_bubble(f"ERROR: {e}")

    def _on_cancel(self):
        """Cancel in-flight request."""
        if not self.streaming:
            return
        self._cancel_event.set()
        try:
            if self.client._current_response:
                self.client._current_response.close()
        except Exception:
            pass
        self.streaming = False
        self._add_system_bubble("⚠ cancelled")
        self._update_status("cancelled")

    def _on_new_chat(self):
        """Start a new chat."""
        if self.streaming:
            self._on_cancel()
        # Clear messages
        for w in self.messages.winfo_children():
            w.destroy()
        self.client.history.clear()
        self._add_system_bubble(f"New chat. Model: {self.client.model}")

    def _show_settings(self):
        """Show settings panel (focus endpoint field)."""
        self.endpoint_entry.focus_set()

    def _show_apps(self):
        """Show apps panel."""
        self._add_system_bubble("Apps: Claude Code, Codex, Kimi CLI, Hermes, Antigravity, OpenCode, FORGE, RENZ App")

    def _show_help(self):
        """Show help."""
        help_text = """Commands (Ctrl+K to use palette):
  /help     - this help
  /model    - show/change model
  /persona  - show/change persona
  /clear    - clear chat
  /save     - save chat to file
  /load     - load chat from file
  /history  - show history
  /test     - test current model
  /yolo     - toggle auto-approve
  /exit     - quit

Keys:
  Enter / Ctrl+Enter - send
  Shift+Enter - newline
  Esc - cancel in-flight request
  Ctrl+S - save
  Ctrl+K - help
"""
        self._add_system_bubble(help_text)

    # ── Streaming ─────────────────────────────────────────────────────
    def _start_streaming(self, user_msg: str):
        """Start streaming a response."""
        self.streaming = True
        self.start_time = time.time()
        self.token_count = 0
        self.current_bubble = None
        self.current_card = None
        self._cancel_event.clear()
        # Add to history
        self.client.history.append({"role": "user", "content": user_msg})
        # Add thinking bubble
        self._add_thinking_bubble()
        # Update status
        self._update_status("streaming…")
        # Run in thread
        threading.Thread(target=self._stream_worker, args=(user_msg,),
                        daemon=True).start()
        # Start queue poller
        self.root.after(50, self._poll_stream_queue)

    def _stream_worker(self, user_msg: str):
        """Worker thread: runs streaming, puts events in queue."""
        try:
            self.client.chat_streaming(
                user_msg,
                on_token=lambda t: self._stream_queue.put(("token", t)),
                on_tool_call=lambda tc: self._stream_queue.put(("tool_call", tc)),
                on_tool_result=lambda n, r: self._stream_queue.put(("tool_result", (n, r))),
                on_done=lambda c: self._stream_queue.put(("done", c)),
                on_error=lambda e: self._stream_queue.put(("error", e)),
                cancel_event=self._cancel_event,
            )
        except Exception as e:
            self._stream_queue.put(("error", str(e)))

    def _poll_stream_queue(self):
        """Process stream events (runs on main thread)."""
        try:
            while True:
                kind, data = self._stream_queue.get_nowait()
                if kind == "token":
                    self._on_token(data)
                elif kind == "tool_call":
                    self._on_tool_call(data)
                elif kind == "tool_result":
                    self._on_tool_result(*data)
                elif kind == "done":
                    self._on_stream_done(data)
                elif kind == "error":
                    self._on_stream_error(data)
        except queue.Empty:
            pass
        if self.streaming:
            self.root.after(30, self._poll_stream_queue)
        else:
            self._update_status()

    def _on_token(self, token: str):
        """Handle a streamed token."""
        self.token_count += 1
        if not self.current_bubble:
            # Remove thinking, add bubble
            self._remove_thinking()
            self.current_bubble = MessageBubble(self.messages, "assistant", self.persona_name)
            self.current_bubble.frame.pack(fill="x", pady=(0, 8), padx=0, anchor="w")
        self.current_bubble.append_token(token)
        self._scroll_to_bottom()
        # Update status every N tokens
        if self.token_count % 20 == 0:
            self._update_status()

    def _on_tool_call(self, tc: Dict):
        """Handle a tool call."""
        # Parse args
        try:
            args = json.loads(tc.get("args", "{}")) if tc.get("args") else {}
        except Exception:
            args = {}
        # Add card
        if HAS_CTK:
            self.current_card = ToolCallCard(self.messages, tc.get("name", "?"), args)
        else:
            self.current_card = ToolCallCard(self.messages, tc.get("name", "?"), args)
        self.current_card.frame.pack(fill="x", padx=(40, 24), pady=(2, 2))
        self._scroll_to_bottom()

    def _on_tool_result(self, name: str, result: str):
        """Handle a tool result."""
        if self.current_card:
            self.current_card.set_result(result)
            self._scroll_to_bottom()

    def _on_stream_done(self, content: str):
        """Handle stream completion."""
        self.streaming = False
        # Re-render current bubble with markdown
        if self.current_bubble:
            self.current_bubble.set_role("assistant", self.persona_name)
        elapsed = time.time() - self.start_time
        tps = self.token_count / elapsed if elapsed > 0 else 0
        self._add_system_bubble(f"✓ done — {self.token_count} tokens, {elapsed:.1f}s ({tps:.1f} tok/s)")
        self._update_status()
        # Auto-save
        self._autosave()
        # Refresh sessions
        if hasattr(self, 'sessions'):
            self.sessions.populate()

    def _on_stream_error(self, err: str):
        """Handle stream error."""
        self.streaming = False
        self._remove_thinking()
        self._add_system_bubble(f"✗ ERROR: {err}")
        self._update_status("error")

    # ── State changes ─────────────────────────────────────────────────
    def _on_model_change(self):
        new = self.model_var.get()
        if new and new != self.client.model:
            self.client.model = new
            self.model = new
            self._add_system_bubble(f"model → {new}")

    def _on_persona_change(self):
        new = self.persona_var.get()
        if new and new != self.persona_name:
            try:
                self.persona_content = load_persona(new)
                self.client.persona = self.persona_content
                self.persona_name = new
                self._add_system_bubble(f"persona → {new} ({len(self.persona_content):,} chars)")
            except Exception as e:
                self._add_system_bubble(f"ERROR: {e}")

    def _on_endpoint_change(self):
        new = self.endpoint_var.get().strip()
        if new and new != self.base_url:
            self.base_url = new
            self.client.base_url = new
            self._add_system_bubble(f"endpoint → {new}")

    def _on_yolo_change(self):
        self.yolo = self.yolo_var.get()
        self.client.yolo = self.yolo
        self._add_system_bubble(f"yolo → {self.yolo}")

    # ── Helpers ───────────────────────────────────────────────────────
    def _add_user_bubble(self, text: str):
        bubble = MessageBubble(self.messages, "user")
        bubble.frame.pack(fill="x", pady=(8, 4), padx=0, anchor="w")
        bubble.render(text)
        self._scroll_to_bottom()

    def _add_system_bubble(self, text: str):
        """A system info line — not a message bubble, just a subtle line."""
        if HAS_CTK:
            lbl = ctk.CTkLabel(self.messages, text=f"  {text}",
                              font=(FONT_FAMILY, 10), text_color=FG_TERTIARY, anchor="w")
        else:
            lbl = tk.Label(self.messages, text=f"  {text}",
                          bg=BG_BASE, fg=FG_TERTIARY,
                          font=(FONT_FAMILY, 9), anchor="w")
        lbl.pack(fill="x", padx=20, pady=2, anchor="w")
        self._scroll_to_bottom()

    def _add_thinking_bubble(self):
        if HAS_CTK:
            self._thinking = ctk.CTkLabel(self.messages, text="● thinking…",
                                          font=(FONT_FAMILY, 11, "italic"),
                                          text_color=FG_TERTIARY, anchor="w")
        else:
            self._thinking = tk.Label(self.messages, text="● thinking…",
                                     bg=BG_BASE, fg=FG_TERTIARY,
                                     font=(FONT_FAMILY, 10, "italic"), anchor="w")
        self._thinking.pack(fill="x", padx=20, pady=4, anchor="w")
        self._scroll_to_bottom()

    def _remove_thinking(self):
        if hasattr(self, '_thinking') and self._thinking:
            try:
                self._thinking.destroy()
            except Exception:
                pass
            self._thinking = None

    def _scroll_to_bottom(self):
        if HAS_CTK:
            try:
                # CTKScrollableFrame
                if hasattr(self.messages, '_parent_canvas'):
                    self.messages._parent_canvas.yview_moveto(1.0)
            except Exception:
                pass
        else:
            try:
                self.canvas.update_idletasks()
                self.canvas.yview_moveto(1.0)
            except Exception:
                pass

    def _on_messages_configure(self, event=None):
        if not HAS_CTK:
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        if not HAS_CTK:
            self.canvas.itemconfig(self._msg_window, width=event.width)

    def _on_mousewheel(self, event):
        if not HAS_CTK:
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _update_status(self, msg: str = None):
        elapsed = time.time() - self.start_time if (self.streaming and self.start_time) else 0
        try:
            model_display = self.client.model[:20]
        except Exception:
            model_display = self.model[:20]
        if msg:
            self.status_label.configure(text=f"  {model_display}  •  {msg}")
        else:
            state = "streaming" if self.streaming else "ready"
            self.status_label.configure(text=f"  {model_display}  •  {state}")
        self.status_right.configure(text=f"  {self.token_count} tokens  •  {elapsed:.1f}s  ")

    def _fetch_models(self) -> list:
        """Get available models from proxy, fall back to local list."""
        try:
            with urllib.request.urlopen(f"{self.base_url.replace('/v1', '')}/v1/models", timeout=2) as r:
                data = json.loads(r.read())
            names = [m.get("id", "") for m in data.get("data", [])]
            names = [n for n in names if n and not n.startswith("blackgrg26/")]
            return names[:30]
        except Exception:
            return ["glm-5.2:cloud", "kimi-k2.7-code:cloud", "deepseek-v4-flash:cloud"]

    def _test_model(self):
        """Test the current model."""
        if self.streaming:
            return
        self._add_system_bubble(f"testing {self.client.model}…")
        def _t():
            try:
                req = urllib.request.Request(
                    f"{self.client.base_url}/chat/completions",
                    data=json.dumps({
                        "model": self.client.model,
                        "messages": [{"role": "user", "content": "hi"}],
                        "max_tokens": 5,
                    }).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=10) as r:
                    d = json.loads(r.read())
                    c = d.get("choices", [{}])[0].get("message", {}).get("content", "")
                    if c:
                        self.root.after(0, lambda: self._add_system_bubble(f"✓ {self.client.model} OK"))
                    else:
                        self.root.after(0, lambda: self._add_system_bubble(f"✗ {self.client.model} empty"))
            except urllib.error.HTTPError as e:
                self.root.after(0, lambda: self._add_system_bubble(f"✗ HTTP {e.code}: {e.reason}"))
            except Exception as e:
                self.root.after(0, lambda: self._add_system_bubble(f"✗ {type(e).__name__}: {e}"))
        threading.Thread(target=_t, daemon=True).start()

    def _health_check(self):
        """Initial health check."""
        self._test_model()

    # ── Slash commands ────────────────────────────────────────────────
    def _handle_slash(self, text: str):
        parts = text.split(maxsplit=1)
        cmd = parts[0][1:].lower()
        arg = parts[1] if len(parts) > 1 else ""
        if cmd in ("exit", "quit", "q"):
            self.root.quit()
        elif cmd == "clear":
            for w in self.messages.winfo_children():
                w.destroy()
            self.client.history.clear()
            self._add_system_bubble("cleared")
        elif cmd == "help":
            self._show_help()
        elif cmd == "model":
            if arg:
                normalized = APIClient._normalize_model(APIClient, arg)
                self.client.model = normalized
                self.model = normalized
                self.model_var.set(normalized)
                self._add_system_bubble(f"model → {normalized}")
            else:
                self._add_system_bubble(f"model: {self.client.model}")
        elif cmd == "persona":
            if arg:
                name = arg if arg.endswith(".txt") else arg + ".txt"
                try:
                    content = load_persona(name)
                    self.persona_content = content
                    self.client.persona = content
                    self.persona_name = name
                    self.persona_var.set(name)
                    self._add_system_bubble(f"persona → {name} ({len(content):,} chars)")
                except Exception as e:
                    self._add_system_bubble(f"ERROR: {e}")
            else:
                self._add_system_bubble(f"persona: {self.persona_name}")
        elif cmd == "yolo":
            self.yolo_var.set(not self.yolo_var.get())
            self._on_yolo_change()
        elif cmd == "save":
            self._save_chat(arg or None)
        elif cmd == "load":
            if arg:
                p = Path.home() / "Documents" / "renz_chats" / arg
                if p.exists():
                    self._load_session_from_file(p)
                else:
                    self._add_system_bubble(f"not found: {arg}")
            else:
                self._add_system_bubble("usage: /load <filename>")
        elif cmd == "test":
            self._test_model()
        elif cmd == "history":
            n = len(self.client.history)
            self._add_system_bubble(f"history: {n} messages")
        else:
            self._add_system_bubble(f"unknown: /{cmd}  (try /help)")

    def _save_chat(self, name: Optional[str] = None):
        save_dir = Path.home() / "Documents" / "renz_chats"
        save_dir.mkdir(parents=True, exist_ok=True)
        if name:
            fname = name if name.endswith(".md") else name + ".md"
        else:
            fname = f"chat-{time.strftime('%Y%m%d-%H%M%S')}.md"
        save_path = save_dir / fname
        try:
            with open(save_path, "w", encoding="utf-8") as f:
                f.write(f"# RENZ Chat — {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                f.write(f"Model: `{self.client.model}`  •  Persona: `{self.persona_name}` ({len(self.persona_content):,} chars)\n\n---\n\n")
                for msg in self.client.history:
                    role = msg.get("role", "?")
                    content = msg.get("content", "")
                    if role == "user":
                        f.write(f"## 👤 You\n\n{content}\n\n")
                    elif role == "assistant":
                        f.write(f"## 🤖 {self.persona_name}\n\n{content}\n\n")
                    elif role == "tool":
                        f.write(f"## 🔧 Tool\n\n```\n{content[:500]}\n```\n\n")
            self._add_system_bubble(f"✓ saved to {save_path.name}")
        except Exception as e:
            self._add_system_bubble(f"ERROR saving: {e}")

    def _autosave(self):
        """Auto-save after each response."""
        try:
            save_dir = Path.home() / "Documents" / "renz_chats"
            save_dir.mkdir(parents=True, exist_ok=True)
            fname = f"autosave-{time.strftime('%Y%m%d-%H%M%S')}.md"
            save_path = save_dir / fname
            with open(save_path, "w", encoding="utf-8") as f:
                f.write(f"# RENZ Auto-save — {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                f.write(f"Model: `{self.client.model}`  •  Persona: `{self.persona_name}`\n\n---\n\n")
                for msg in self.client.history:
                    role = msg.get("role", "?")
                    content = msg.get("content", "")
                    if role == "user":
                        f.write(f"## You\n\n{content}\n\n")
                    elif role == "assistant":
                        f.write(f"## {self.persona_name}\n\n{content}\n\n")
                    elif role == "tool":
                        f.write(f"## Tool\n\n```\n{content[:500]}\n```\n\n")
            # Cleanup: keep last 20 autosaves
            autosaves = sorted(save_dir.glob("autosave-*.md"),
                              key=lambda p: p.stat().st_mtime, reverse=True)
            for old in autosaves[20:]:
                try:
                    old.unlink()
                except Exception:
                    pass
        except Exception:
            pass

    def _load_session_from_file(self, file_path: Path):
        """Load a session from a markdown file."""
        try:
            content = file_path.read_text(encoding="utf-8")
            # Clear current
            for w in self.messages.winfo_children():
                w.destroy()
            self.client.history.clear()
            # Reconstruct history
            sections = re.split(r'\n## ', content)
            for sec in sections[1:]:
                lines = sec.split('\n', 1)
                header = lines[0].strip()
                body = lines[1].strip() if len(lines) > 1 else ""
                if "You" in header:
                    self.client.history.append({"role": "user", "content": body})
                else:
                    self.client.history.append({"role": "assistant", "content": body})
            # Render messages
            for msg in self.client.history:
                if msg["role"] == "user":
                    self._add_user_bubble(msg["content"])
                else:
                    bubble = MessageBubble(self.messages, "assistant", self.persona_name)
                    bubble.frame.pack(fill="x", pady=(0, 8), padx=0, anchor="w")
                    bubble.render(msg["content"])
            self._add_system_bubble(f"✓ loaded {file_path.name}")
            self._scroll_to_bottom()
        except Exception as e:
            self._add_system_bubble(f"ERROR loading: {e}")


# ════════════════════════════════════════════════════════════════════════
# Main
# ════════════════════════════════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser(description="RENZ App Desktop v3")
    parser.add_argument("--base-url", default="http://127.0.0.1:11435/v1")
    parser.add_argument("--model", default="glm-5.2:cloud")
    parser.add_argument("--persona", default="NOVA.txt")
    parser.add_argument("--yolo", action="store_true")
    args = parser.parse_args()
    app = RENZApp(
        base_url=args.base_url,
        model=args.model,
        persona=args.persona,
        yolo=args.yolo,
    )
    app.run()


if __name__ == "__main__":
    main()
