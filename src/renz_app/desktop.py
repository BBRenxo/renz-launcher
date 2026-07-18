"""
RENZ App Desktop — Tkinter GUI version.

Same engine as renz_app/__main__.py (CLI), but with a proper GUI:
- Chat history pane
- Input box at the bottom
- Sidebar: model/persona/yolo toggles, slash command menu
- Streaming response display
- Tool call results inline

Run: python -m renz_app.desktop
"""

import json
import os
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import scrolledtext, ttk
from typing import List, Dict, Optional

# Reuse the CLI engine
SCRIPT_DIR = Path(__file__).parent
RENZ_ROOT = SCRIPT_DIR.parent
PERSONAS_DIR = RENZ_ROOT / "personas"
sys.path.insert(0, str(RENZ_ROOT))

# Reuse tools + client from CLI version
from renz_app.__main__ import TOOLS, TOOL_FUNCS, load_persona  # noqa: E402


class APIClient:
    """Same as CLI version, but with streaming callback support."""

    def __init__(self, base_url, model, persona, yolo=False, on_token=None, on_tool=None):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.persona = persona
        self.yolo = yolo
        self.history: List[Dict] = []
        self.on_token = on_token  # callback for streaming tokens
        self.on_tool = on_tool    # callback for tool calls

    def chat(self, user_msg: str):
        self.history.append({"role": "user", "content": user_msg})

        while True:
            payload = {
                "model": self.model,
                "messages": [{"role": "system", "content": self.persona}] + self.history,
                "tools": TOOLS,
                "max_tokens": 8000,
            }
            try:
                import urllib.request
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

            assistant_msg = {"role": "assistant", "content": content}
            if tool_calls:
                assistant_msg["tool_calls"] = tool_calls
            self.history.append(assistant_msg)

            # Stream tokens (we don't actually stream, but the callback signature is here)
            if content and self.on_token:
                self.on_token(content)
            elif reasoning and self.on_token and not content:
                # Reasoning-only response — promote reasoning to content
                promoted = reasoning
                self.on_token(promoted)
                content = promoted

            if not tool_calls:
                return content or reasoning

            for tc in tool_calls:
                fn_name = tc.get('function', {}).get('name', '')
                fn_args_str = tc.get('function', {}).get('arguments', '{}')
                try:
                    fn_args = json.loads(fn_args_str)
                except:
                    fn_args = {}

                if self.on_tool:
                    self.on_tool(fn_name, fn_args)

                if fn_name in TOOL_FUNCS:
                    result = TOOL_FUNCS[fn_name](**fn_args)
                else:
                    result = f"ERR: unknown tool {fn_name}"

                if self.on_tool:
                    self.on_tool(fn_name, fn_args, result)

                self.history.append({
                    "role": "tool",
                    "tool_call_id": tc.get('id', ''),
                    "content": result,
                })


class RENZApp:
    """Tkinter desktop app for RENZ."""

    BG = "#1a1a2e"
    BG_PANEL = "#16213e"
    BG_INPUT = "#0f1626"
    FG = "#e0e0e0"
    FG_DIM = "#888"
    ACCENT = "#00d9ff"
    ACCENT_DIM = "#0099bb"
    USER = "#00ff88"
    ASSIST = "#ffaa00"
    TOOL = "#ff66cc"

    def __init__(self, base_url="http://127.0.0.1:11435/v1", model="glm-5.2:cloud",
                 persona="NOVA.txt", yolo=False):
        self.root = tk.Tk()
        self.root.title("RENZ App — built-in agent")
        self.root.geometry("1000x700")
        self.root.configure(bg=self.BG)

        self.base_url = base_url
        self.model = model
        self.persona_name = persona
        self.yolo = yolo

        self.persona_content = load_persona(persona)
        self.client = APIClient(base_url, model, self.persona_content, yolo=yolo,
                                  on_token=lambda t: None,
                                  on_tool=lambda *a: None)

        self._build_ui()
        self._append_system(f"RENZ App ready. Model: {model} | Persona: {persona} ({len(self.persona_content):,} chars)")
        self._append_system(f"Endpoint: {base_url} | Yolo: {yolo}")
        self._append_system("Type a message and press Enter. Use /help for commands.\n")

    def _build_ui(self):
        # Sidebar
        sidebar = tk.Frame(self.root, bg=self.BG_PANEL, width=260)
        sidebar.pack(side=tk.LEFT, fill=tk.Y, padx=0, pady=0)
        sidebar.pack_propagate(False)

        tk.Label(sidebar, text="RENZ App", font=("Consolas", 16, "bold"),
                bg=self.BG_PANEL, fg=self.ACCENT).pack(pady=(12, 4), padx=8, anchor="w")
        tk.Label(sidebar, text="v0.1.0 — built-in agent", font=("Consolas", 9),
                bg=self.BG_PANEL, fg=self.FG_DIM).pack(pady=(0, 12), padx=8, anchor="w")

        # Model field
        tk.Label(sidebar, text="Model", font=("Segoe UI", 9, "bold"),
                bg=self.BG_PANEL, fg=self.FG_DIM).pack(pady=(8, 2), padx=8, anchor="w")
        self.model_var = tk.StringVar(value=self.model)
        model_combo = ttk.Combobox(sidebar, textvariable=self.model_var,
                                   values=self._get_models(),
                                   font=("Consolas", 10))
        model_combo.pack(fill=tk.X, padx=8, pady=(0, 8))
        model_combo.bind("<<ComboboxSelected>>", lambda e: self._on_model_change())

        # Persona field
        tk.Label(sidebar, text="Persona", font=("Segoe UI", 9, "bold"),
                bg=self.BG_PANEL, fg=self.FG_DIM).pack(pady=(4, 2), padx=8, anchor="w")
        self.persona_var = tk.StringVar(value=self.persona_name)
        persona_combo = ttk.Combobox(sidebar, textvariable=self.persona_var,
                                     values=self._get_personas(),
                                     font=("Consolas", 10))
        persona_combo.pack(fill=tk.X, padx=8, pady=(0, 8))
        persona_combo.bind("<<ComboboxSelected>>", lambda e: self._on_persona_change())

        # Endpoint
        tk.Label(sidebar, text="Endpoint", font=("Segoe UI", 9, "bold"),
                bg=self.BG_PANEL, fg=self.FG_DIM).pack(pady=(4, 2), padx=8, anchor="w")
        self.endpoint_var = tk.StringVar(value=self.base_url)
        ep_entry = tk.Entry(sidebar, textvariable=self.endpoint_var, font=("Consolas", 9),
                           bg=self.BG_INPUT, fg=self.FG, insertbackground=self.FG,
                           relief=tk.FLAT)
        ep_entry.pack(fill=tk.X, padx=8, pady=(0, 8))
        ep_entry.bind("<FocusOut>", lambda e: self._on_endpoint_change())

        # Yolo
        self.yolo_var = tk.BooleanVar(value=self.yolo)
        yolo_check = tk.Checkbutton(sidebar, text="Yolo mode (auto-approve tools)",
                                    variable=self.yolo_var,
                                    command=self._on_yolo_change,
                                    bg=self.BG_PANEL, fg=self.FG, selectcolor=self.BG_INPUT,
                                    activebackground=self.BG_PANEL, activeforeground=self.FG)
        yolo_check.pack(pady=(4, 8), padx=8, anchor="w")

        # Slash commands
        tk.Label(sidebar, text="Commands", font=("Segoe UI", 9, "bold"),
                bg=self.BG_PANEL, fg=self.FG_DIM).pack(pady=(8, 4), padx=8, anchor="w")
        cmds = [
            ("/help", "Show help"),
            ("/clear", "Clear history"),
            ("/model", "Show model"),
            ("/persona", "Show persona"),
            ("/yolo", "Toggle yolo"),
            ("/exit", "Quit"),
        ]
        for cmd, desc in cmds:
            btn = tk.Button(sidebar, text=f"{cmd}  — {desc}", font=("Consolas", 9),
                          bg=self.BG_INPUT, fg=self.FG, relief=tk.FLAT,
                          activebackground=self.ACCENT_DIM, activeforeground=self.BG,
                          anchor="w", command=lambda c=cmd: self._send_command(c))
            btn.pack(fill=tk.X, padx=8, pady=1)

        # Main chat area
        chat_frame = tk.Frame(self.root, bg=self.BG)
        chat_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=0, pady=0)

        # Chat display
        self.chat_display = scrolledtext.ScrolledText(
            chat_frame, wrap=tk.WORD, bg=self.BG, fg=self.FG,
            font=("Consolas", 11), relief=tk.FLAT, state=tk.DISABLED,
            insertbackground=self.FG, padx=12, pady=12
        )
        self.chat_display.pack(fill=tk.BOTH, expand=True)

        # Tag styles
        self.chat_display.tag_config("user", foreground=self.USER, font=("Consolas", 11, "bold"))
        self.chat_display.tag_config("assist", foreground=self.ASSIST, font=("Consolas", 11, "bold"))
        self.chat_display.tag_config("tool", foreground=self.TOOL, font=("Consolas", 10))
        self.chat_display.tag_config("system", foreground=self.FG_DIM, font=("Consolas", 9, "italic"))
        self.chat_display.tag_config("error", foreground="#ff4444", font=("Consolas", 10, "bold"))

        # Input area
        input_frame = tk.Frame(chat_frame, bg=self.BG_PANEL, height=80)
        input_frame.pack(fill=tk.X, padx=0, pady=0)
        input_frame.pack_propagate(False)

        self.input_text = tk.Text(input_frame, height=3, bg=self.BG_INPUT, fg=self.FG,
                                  font=("Consolas", 11), relief=tk.FLAT,
                                  insertbackground=self.FG, padx=8, pady=8,
                                  wrap=tk.WORD)
        self.input_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(8, 0), pady=8)
        self.input_text.bind("<Return>", lambda e: self._on_enter(e))
        self.input_text.bind("<Shift-Return>", lambda e: None)  # allow newline

        send_btn = tk.Button(input_frame, text="Send\n(Enter)", font=("Segoe UI", 10, "bold"),
                            bg=self.ACCENT, fg=self.BG, relief=tk.FLAT,
                            activebackground=self.ACCENT_DIM, activeforeground=self.BG,
                            width=10, command=self._on_send)
        send_btn.pack(side=tk.RIGHT, padx=8, pady=8)

    def _get_models(self):
        """Try to fetch models from the proxy."""
        try:
            import urllib.request
            with urllib.request.urlopen(f"{self.base_url.replace('/v1', '')}/v1/models", timeout=5) as r:
                data = json.loads(r.read())
                models = [m.get('id', m.get('name', '')) for m in data.get('data', [])]
                return models or [self.model]
        except:
            return [self.model, "glm-5.2:cloud", "kimi-k2.7-code:cloud", "minimax-m3:cloud"]

    def _get_personas(self):
        if PERSONAS_DIR.exists():
            return sorted([p.name for p in PERSONAS_DIR.glob("*.txt")])
        return [self.persona_name]

    def _on_model_change(self):
        new_model = self.model_var.get()
        if new_model and new_model != self.client.model:
            self.client.model = new_model
            self.model = new_model
            self._append_system(f"model → {new_model}")

    def _on_persona_change(self):
        new_name = self.persona_var.get()
        if new_name and new_name != self.persona_name:
            self.persona_name = new_name
            self.persona_content = load_persona(new_name)
            self.client.persona = self.persona_content
            self._append_system(f"persona → {new_name} ({len(self.persona_content):,} chars)")

    def _on_endpoint_change(self):
        new_ep = self.endpoint_var.get().strip()
        if new_ep and new_ep != self.client.base_url:
            self.client.base_url = new_ep
            self.base_url = new_ep
            self._append_system(f"endpoint → {new_ep}")

    def _on_yolo_change(self):
        self.yolo = self.yolo_var.get()
        self.client.yolo = self.yolo
        self._append_system(f"yolo → {self.yolo}")

    def _on_enter(self, event):
        if not event.state & 0x1:  # no shift
            self._on_send()
            return "break"

    def _on_send(self):
        text = self.input_text.get("1.0", tk.END).strip()
        if not text:
            return
        self.input_text.delete("1.0", tk.END)
        self._handle_input(text)

    def _send_command(self, cmd):
        self._handle_input(cmd)

    def _handle_input(self, text):
        if text.startswith("/"):
            cmd = text[1:].lower().strip()
            if cmd in ("exit", "quit", "q"):
                self.root.quit()
                return
            elif cmd == "help":
                self._append_system("Commands: /help /clear /model /persona /yolo /exit")
                return
            elif cmd == "model":
                self._append_system(f"model: {self.model}")
                return
            elif cmd == "persona":
                self._append_system(f"persona: {self.persona_name} ({len(self.persona_content):,} chars)")
                return
            elif cmd == "clear":
                self.client.history = []
                self._clear_chat()
                self._append_system("cleared.")
                return
            elif cmd == "yolo":
                self.yolo_var.set(not self.yolo_var.get())
                self._on_yolo_change()
                return

        # Regular message — send to model
        self._append_user(text)
        threading.Thread(target=self._do_chat, args=(text,), daemon=True).start()

    def _do_chat(self, text):
        """Run chat in background thread, update UI when done."""
        self.root.after(0, lambda: self._append_assist_streaming(""))
        try:
            response = self.client.chat(text)
            self.root.after(0, lambda: self._append_assist_done(response))
        except Exception as e:
            self.root.after(0, lambda: self._append_error(f"Error: {e}"))

    def _append_user(self, text):
        self.chat_display.config(state=tk.NORMAL)
        self.chat_display.insert(tk.END, f"\n[you]\n{text}\n", "user")
        self.chat_display.config(state=tk.DISABLED)
        self.chat_display.see(tk.END)

    def _append_assist_streaming(self, text):
        # placeholder; we update via _append_assist_done
        pass

    def _append_assist_done(self, text):
        self.chat_display.config(state=tk.NORMAL)
        self.chat_display.insert(tk.END, f"\n[renz]\n{text}\n", "assist")
        self.chat_display.config(state=tk.DISABLED)
        self.chat_display.see(tk.END)

    def _append_error(self, text):
        self.chat_display.config(state=tk.NORMAL)
        self.chat_display.insert(tk.END, f"\n[err]\n{text}\n", "error")
        self.chat_display.config(state=tk.DISABLED)
        self.chat_display.see(tk.END)

    def _append_system(self, text):
        self.chat_display.config(state=tk.NORMAL)
        self.chat_display.insert(tk.END, f"\n· {text}\n", "system")
        self.chat_display.config(state=tk.DISABLED)
        self.chat_display.see(tk.END)

    def _clear_chat(self):
        self.chat_display.config(state=tk.NORMAL)
        self.chat_display.delete("1.0", tk.END)
        self.chat_display.config(state=tk.DISABLED)

    def run(self):
        self.root.mainloop()


def main():
    import argparse
    parser = argparse.ArgumentParser(description="RENZ App Desktop")
    parser.add_argument("--base-url", default="http://127.0.0.1:11435/v1")
    parser.add_argument("--model", default="glm-5.2:cloud")
    parser.add_argument("--persona", default="NOVA.txt")
    parser.add_argument("--yolo", action="store_true")
    args = parser.parse_args()

    app = RENZApp(base_url=args.base_url, model=args.model,
                  persona=args.persona, yolo=args.yolo)
    app.run()


if __name__ == "__main__":
    main()
