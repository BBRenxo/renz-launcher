import sys

path = r"./\renz_launcher\renz_launcher.py"
with open(path, "r", encoding="utf-8") as f:
    code = f.read()

# 1. APP_SUBTITLES
old_subtitles = """APP_SUBTITLES = {
    "Claude Code":  "Anthropic's AI coding agent — CLI & Desktop",
    "Codex":        "OpenAI's autonomous coding CLI & Desktop",
    "Antigravity":  "Google DeepMind's agentic IDE & CLI",
}"""

new_subtitles = """APP_SUBTITLES = {
    "Claude Code":  "Anthropic's AI coding agent — CLI & Desktop",
    "Codex":        "OpenAI's autonomous coding CLI & Desktop",
    "Antigravity":  "Google DeepMind's agentic IDE & CLI",
    "Hermes Agent": "Nous Research's self-improving AI agent",
    "ChatGPT":      "Complete work with ChatGPT",
    "OpenClaw":     "Personal AI with 100+ skills",
    "OpenCode":     "Anomaly's open-source coding agent",
    "Copilot CLI":  "GitHub's AI coding agent for the terminal",
    "Droid":        "Factory's coding agent across terminal and IDEs",
    "Pi":           "Minimal AI agent toolkit with plugin support",
}"""
code = code.replace(old_subtitles, new_subtitles)

# 2. Segmented Button -> OptionMenu
old_switcher = """            self.app_switcher = ctk.CTkSegmentedButton(
                sw, values=["Claude Code", "Codex", "Antigravity"],
                variable=self.app_var,
                font=("Segoe UI", 13, "bold"),
                selected_color=ACCENT_SEG,
                selected_hover_color=ACCENT_SEGH,
                unselected_color=BG_INPUT,
                unselected_hover_color=BG_HOVER,
                text_color="#ffffff", corner_radius=8,
                border_width=0, height=36)"""
new_switcher = """            self.app_switcher = ctk.CTkOptionMenu(
                sw, values=list(APP_SUBTITLES.keys()),
                variable=self.app_var,
                font=("Segoe UI", 13, "bold"),
                fg_color="#18182b",
                button_color="#252545",
                button_hover_color="#3a86ff",
                text_color="#ffffff", corner_radius=8,
                height=36)"""
code = code.replace(old_switcher, new_switcher)

# 3. _on_app_change
old_on_change = """        def _on_app_change(self, selected):
            for f in (self.claude_frame, self.codex_frame, self.ag_frame):
                f.pack_forget()
            self.sp_frame.pack_forget()
            self.lbl_subtitle.configure(
                text=APP_SUBTITLES.get(selected, ""))

            if selected == "Claude Code":
                self.claude_frame.pack(in_=self.app_container, fill="x")
                self.sp_frame.pack(fill="both", expand=True)
            elif selected == "Codex":
                self.codex_frame.pack(in_=self.app_container, fill="x")
                self.sp_frame.pack(fill="both", expand=True)
            else:
                self.ag_frame.pack(in_=self.app_container, fill="x")"""

new_on_change = """        def _on_app_change(self, selected):
            for f in (self.claude_frame, self.codex_frame, self.ag_frame):
                f.pack_forget()
            self.sp_frame.pack_forget()
            self.lbl_subtitle.configure(
                text=APP_SUBTITLES.get(selected, ""))

            if selected == "Codex":
                self.codex_frame.pack(in_=self.app_container, fill="x")
                self.sp_frame.pack(fill="both", expand=True)
            elif selected == "Antigravity":
                self.ag_frame.pack(in_=self.app_container, fill="x")
            else:
                self.claude_frame.pack(in_=self.app_container, fill="x")
                self.sp_frame.pack(fill="both", expand=True)"""
code = code.replace(old_on_change, new_on_change)

# 4. build_launch_command
old_build_end = """            cwd = cfg.get("ag_work") or None
            return cmd, cwd, env, f"Antigravity CLI ({mod})"
        else:
            cmd = [exe]
            extra = cfg.get("ag_extra", "").strip()
            if extra:
                cmd += extra.split()
            cwd = cfg.get("ag_work") or None
            return cmd, cwd, env, f"Antigravity IDE"

def do_launch(cfg):"""

new_build_end = """            cwd = cfg.get("ag_work") or None
            return cmd, cwd, env, f"Antigravity CLI ({mod})"
        else:
            cmd = [exe]
            extra = cfg.get("ag_extra", "").strip()
            if extra:
                cmd += extra.split()
            cwd = cfg.get("ag_work") or None
            return cmd, cwd, env, f"Antigravity IDE"

    # ── OTHER AGENTS (Hermes, ChatGPT, OpenCode, etc) ─────────────────
    else:
        target = cfg.get("cl_target", "CLI")
        exe = cfg.get("cl_exe", "")
        mod = cfg.get("cl_model", "")
        
        if "Desktop" in target:
            cmd = [exe] if exe else [""]
            return cmd, None, env, f"{app} Desktop"
        else:
            app_key = app.split()[0].lower()
            if app == "Copilot CLI": app_key = "copilot"
            if app == "Hermes Agent": app_key = "hermes"
            cmd = ["ollama", "launch", app_key]
            
            if cfg.get("cl_skip", True):
                cmd.append("--bypass")
                
            if system_prompt and "Default" not in pm:
                cmd += ["--system-prompt", system_prompt]
                
            extra = cfg.get("cl_extra", "").strip()
            if extra:
                cmd += extra.split()
                
            cwd = cfg.get("cl_work") or None
            return cmd, cwd, env, f"{app} CLI"

def do_launch(cfg):
    cmd, cwd, env, desc = build_launch_command(cfg)
    if not cmd or not cmd[0]:
        return False, "Not found: Please configure the executable path.", None"""
code = code.replace(old_build_end, new_build_end)

# Also fix the do_launch inside renz_launcher to catch the empty command case
# In do_launch(cfg):
old_do_launch = """def do_launch(cfg):
    try:
        cmd, cwd, env, desc = build_launch_command(cfg)
        cf = subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0
        proc = subprocess.Popen(cmd, cwd=cwd, creationflags=cf, env=env)"""
new_do_launch = """def do_launch(cfg):
    try:
        cmd, cwd, env, desc = build_launch_command(cfg)
        if not cmd or not cmd[0]:
            return False, "Not found: Please configure the executable path.", None
        cf = subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0
        proc = subprocess.Popen(cmd, cwd=cwd, creationflags=cf, env=env)"""
code = code.replace(old_do_launch, new_do_launch)

with open(path, "w", encoding="utf-8") as f:
    f.write(code)
print("Patched.")
