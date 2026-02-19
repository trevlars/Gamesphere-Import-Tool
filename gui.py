"""
Gamesphere Import Tool — Windows GUI.
Configure paths, API key, and run the importer for Sunshine or Apollo.
"""

import os
import subprocess
import sys
import threading
import queue

# Optional: request admin on Windows so we can write to Program Files (Sunshine/Apollo config).
# Disabled at startup so the GUI always opens; user can right-click exe -> Run as administrator if needed.
def _request_admin_and_rerun():
    if sys.platform != "win32":
        return
    try:
        import ctypes
        if ctypes.windll.shell32.IsUserAnAdmin():
            return  # Already admin
        # Re-launch with "runas" would exit this process and open GUI in elevated one,
        # which often leaves user with no visible window (UAC cancel or different session).
        # So we no longer do that here; GUI opens in current process.
    except Exception:
        pass

# Try CustomTkinter for modern look; fall back to tkinter
import tkinter as tk
from tkinter import messagebox, scrolledtext, filedialog
try:
    import customtkinter as ctk
    HAS_CTK = True
except ImportError:
    ctk = tk  # use standard tk
    HAS_CTK = False

# Env var names as used by main.py (load_dotenv + getenv)
ENV_KEYS = {
    "steam_library_vdf_path": "Steam library VDF path",
    "sunshine_apps_json_path": "Apps.json path",
    "sunshine_grids_folder": "Thumbnails folder",
    "steamgriddb_api_key": "SteamGridDB API key (optional; uses Steam CDN if empty)",
    "STEAM_EXE_PATH": "Steam executable (optional)",
    "SUNSHINE_EXE_PATH": "Host executable (optional)",
}

# Default Windows paths per streaming host (main.py uses same env var names for both)
HOST_DEFAULTS = {
    "sunshine": {
        "steam_library_vdf_path": "C:/Program Files (x86)/Steam/steamapps/libraryfolders.vdf",
        "sunshine_apps_json_path": "C:/Program Files/Sunshine/config/apps.json",
        "sunshine_grids_folder": "C:/Sunshine_Thumbnails",
        "steamgriddb_api_key": "",
        "STEAM_EXE_PATH": "C:/Program Files (x86)/Steam/steam.exe",
        "SUNSHINE_EXE_PATH": "C:/Program Files/Sunshine/sunshine.exe",
    },
    "apollo": {
        "steam_library_vdf_path": "C:/Program Files (x86)/Steam/steamapps/libraryfolders.vdf",
        "sunshine_apps_json_path": "C:/Program Files/Apollo/config/apps.json",
        "sunshine_grids_folder": "C:/Apollo_Thumbnails",
        "steamgriddb_api_key": "",
        "STEAM_EXE_PATH": "C:/Program Files (x86)/Steam/steam.exe",
        "SUNSHINE_EXE_PATH": "C:/Program Files/Apollo/sunshine.exe",
    },
}

# For backwards compatibility (default host)
DEFAULTS = HOST_DEFAULTS["sunshine"]


def _base_dir():
    """Base directory for .env and main.py (script dir, or exe dir when frozen)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def get_dotenv_path():
    """Path to .env in the same directory as this script (or the .exe when frozen)."""
    return os.path.join(_base_dir(), ".env")


def load_env_from_file():
    """Load key=value pairs from .env into a dict. Returns (values_dict, host)."""
    path = get_dotenv_path()
    out = dict(DEFAULTS)
    host = "sunshine"
    if not os.path.exists(path):
        return out, host
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                key, value = key.strip(), value.strip()
                if key == "HOST":
                    host = value.lower() if value.lower() in ("sunshine", "apollo") else "sunshine"
                    continue
                if key in ENV_KEYS:
                    # Remove surrounding quotes if present
                    if value.startswith('"') and value.endswith('"'):
                        value = value[1:-1]
                    if value.startswith("'") and value.endswith("'"):
                        value = value[1:-1]
                    out[key] = value
    return out, host


def save_env_to_file(values, host="sunshine"):
    """Write config dict to .env."""
    path = get_dotenv_path()
    lines = [
        "# Gamesphere Import Tool configuration",
        "# Edit here or use the GUI. HOST = sunshine | apollo",
        "",
        f"HOST={host}",
        "",
    ]
    for key in ENV_KEYS:
        val = values.get(key, "")
        if " " in val or "#" in val:
            val = f'"{val}"'
        lines.append(f"{key}={val}")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def _run_importer_in_process(env_vars, dry_run, verbose, no_restart, log_queue, remove_games=False):
    """Run the importer in-process (used when frozen as .exe). Captures stdout to log_queue."""
    class QueueWriter:
        def __init__(self, q):
            self._q = q
        def write(self, s):
            if s:
                self._q.put(("out", s))
        def flush(self):
            pass

    base_dir = _base_dir()
    old_cwd = os.getcwd()
    old_stdout, old_stderr = sys.stdout, sys.stderr
    out = QueueWriter(log_queue)
    sys.stdout, sys.stderr = out, out
    try:
        os.chdir(base_dir)
        for k, v in env_vars.items():
            if v:
                os.environ[k] = str(v)
        sys.argv = ["main.py"]
        if remove_games:
            sys.argv.append("--remove-games")
        if dry_run:
            sys.argv.append("--dry-run")
        if verbose:
            sys.argv.append("--verbose")
        if no_restart:
            sys.argv.append("--no-restart")
        import main as main_mod
        main_mod.main()
    except SystemExit as e:
        if e.code and e.code != 0:
            log_queue.put(("err", f"\nExited with code {e.code}\n"))
    except Exception as e:
        log_queue.put(("err", str(e) + "\n"))
    finally:
        sys.stdout, sys.stderr = old_stdout, old_stderr
        os.chdir(old_cwd)
    log_queue.put(("done",))


def run_automation(env_vars, dry_run, verbose, no_restart, log_queue, remove_games=False):
    """Run main.py in a subprocess (or in-process when frozen) and push lines to log_queue. Puts ("done",) when finished."""
    base_dir = _base_dir()
    is_frozen = getattr(sys, "frozen", False)

    if is_frozen:
        _run_importer_in_process(env_vars, dry_run, verbose, no_restart, log_queue, remove_games)
        return

    main_py = os.path.join(base_dir, "main.py")
    if not os.path.exists(main_py):
        log_queue.put(("err", "main.py not found.\n"))
        log_queue.put(("done",))
        return
    env = os.environ.copy()
    for k, v in env_vars.items():
        if v:
            env[k] = v
    cmd = [sys.executable, main_py]
    if remove_games:
        cmd.append("--remove-games")
    if dry_run:
        cmd.append("--dry-run")
    if verbose:
        cmd.append("--verbose")
    if no_restart:
        cmd.append("--no-restart")
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=base_dir,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        for line in proc.stdout:
            log_queue.put(("out", line))
        proc.wait()
        if proc.returncode != 0:
            log_queue.put(("err", f"\nProcess exited with code {proc.returncode}\n"))
    except Exception as e:
        log_queue.put(("err", str(e) + "\n"))
    log_queue.put(("done",))


class SunshineGUI:
    def __init__(self):
        if HAS_CTK:
            ctk.set_appearance_mode("dark")
            ctk.set_default_color_theme("blue")
        self.root = ctk.CTk() if HAS_CTK else tk.Tk()
        self.root.title("GameSphere Import Tool")
        self.root.minsize(640, 520)
        self.root.geometry("720x580")

        self.entries = {}
        self.host_var = None
        self.host_dropdown = None
        self.dry_run_var = None
        self.verbose_var = None
        self.no_restart_var = None
        self.run_btn = None
        self.remove_games_btn = None
        self.log_text = None
        self.log_queue = queue.Queue()
        self.running = False

        self._build_ui()
        self._load_config()
        self._poll_log()

    def _frame(self, parent, **kwargs):
        if HAS_CTK:
            return ctk.CTkFrame(parent, **kwargs)
        return tk.Frame(parent, **kwargs)

    def _label(self, parent, text, **kwargs):
        if HAS_CTK:
            return ctk.CTkLabel(parent, text=text, **kwargs)
        return tk.Label(parent, text=text, **kwargs)

    def _entry(self, parent, **kwargs):
        if HAS_CTK:
            return ctk.CTkEntry(parent, **kwargs)
        return tk.Entry(parent, **kwargs)

    def _button(self, parent, text, command, **kwargs):
        if HAS_CTK:
            return ctk.CTkButton(parent, text=text, command=command, **kwargs)
        return tk.Button(parent, text=text, command=command, **kwargs)

    def _checkbox(self, parent, text, variable, **kwargs):
        if HAS_CTK:
            return ctk.CTkCheckBox(parent, text=text, variable=variable, **kwargs)
        return tk.Checkbutton(parent, text=text, variable=variable, **kwargs)

    def _on_host_change(self, choice):
        """Update path fields to defaults for the selected host."""
        host = choice.lower() if choice else "sunshine"
        if host not in HOST_DEFAULTS:
            host = "sunshine"
        defaults = HOST_DEFAULTS[host]
        for key in ("sunshine_apps_json_path", "sunshine_grids_folder", "SUNSHINE_EXE_PATH"):
            self.entries[key].delete(0, "end")
            self.entries[key].insert(0, defaults.get(key, ""))

    def _build_ui(self):
        main = self._frame(self.root)
        main.pack(fill="both", expand=True, padx=12, pady=12)

        # Config section
        config_frame = self._frame(main)
        config_frame.pack(fill="x", pady=(0, 8))
        self._label(config_frame, text="Configuration", font=("", 14, "bold")).pack(anchor="w")

        # Streaming host selector
        host_row = self._frame(config_frame)
        host_row.pack(fill="x", pady=(0, 6))
        self._label(host_row, text="Streaming host:", width=32, anchor="w").pack(side="left", padx=(0, 8))
        self.host_var = tk.StringVar(value="Sunshine")
        if HAS_CTK:
            self.host_dropdown = ctk.CTkOptionMenu(
                host_row,
                variable=self.host_var,
                values=["Sunshine", "Apollo"],
                command=self._on_host_change,
                width=200,
            )
        else:
            self.host_dropdown = tk.OptionMenu(host_row, self.host_var, "Sunshine", "Apollo", command=self._on_host_change)
        self.host_dropdown.pack(side="left")

        for key, label in ENV_KEYS.items():
            row = self._frame(config_frame)
            row.pack(fill="x", pady=2)
            self._label(row, text=label + ":", width=32, anchor="w").pack(side="left", padx=(0, 8))
            entry = self._entry(row)
            entry.pack(side="left", fill="x", expand=True, padx=(0, 4))
            self.entries[key] = entry
            if "optional" in label.lower():
                self._label(row, text="(optional)", font=("", 9)).pack(side="left")
            # Browse button for paths
            if "path" in key.lower() or "folder" in key.lower() or "json" in key.lower():
                def make_browse(e=entry, is_file=("json" in key or "vdf" in key)):
                    def browse():
                        if is_file:
                            path = filedialog.askopenfilename()
                        else:
                            path = filedialog.askdirectory()
                        if path:
                            e.delete(0, "end")
                            e.insert(0, path)
                    return browse
                btn = self._button(row, "Browse…", make_browse())
                btn.pack(side="right")

        # Options
        opt_frame = self._frame(main)
        opt_frame.pack(fill="x", pady=8)
        self._label(opt_frame, text="Options", font=("", 14, "bold")).pack(anchor="w")
        self.dry_run_var = tk.BooleanVar(value=False)
        self.verbose_var = tk.BooleanVar(value=False)
        self.no_restart_var = tk.BooleanVar(value=False)
        self._checkbox(opt_frame, "Dry run (preview only)", self.dry_run_var).pack(anchor="w")
        self._checkbox(opt_frame, "Verbose logging", self.verbose_var).pack(anchor="w")
        self._checkbox(opt_frame, "Do not start Steam or restart host (Sunshine/Apollo)", self.no_restart_var).pack(anchor="w")

        # Buttons
        btn_frame = self._frame(main)
        btn_frame.pack(fill="x", pady=8)
        self._button(btn_frame, "Save config", self._save_config).pack(side="left", padx=(0, 8))
        self.run_btn = self._button(btn_frame, "Run importer", self._on_run)
        self.run_btn.pack(side="left", padx=(0, 8))
        self.remove_games_btn = self._button(btn_frame, "Remove all games", self._on_remove_games)
        self.remove_games_btn.pack(side="left")

        # Log
        self._label(main, text="Log", font=("", 14, "bold")).pack(anchor="w")
        log_frame = self._frame(main)
        log_frame.pack(fill="both", expand=True, pady=4)
        self.log_text = scrolledtext.ScrolledText(
            log_frame, wrap="word", height=12, state="disabled",
            font=("Consolas", 10) if sys.platform == "win32" else ("Monaco", 10),
        )
        self.log_text.pack(fill="both", expand=True)

    def _load_config(self):
        values, host = load_env_from_file()
        for key, entry in self.entries.items():
            entry.delete(0, "end")
            entry.insert(0, values.get(key, ""))
        self.host_var.set(host.capitalize())

    def _get_values(self):
        return {key: entry.get().strip() for key, entry in self.entries.items()}

    def _get_host(self):
        raw = self.host_var.get().strip().lower()
        return raw if raw in ("sunshine", "apollo") else "sunshine"

    def _save_config(self):
        save_env_to_file(self._get_values(), self._get_host())
        messagebox.showinfo("Saved", "Configuration saved to .env")

    def _on_run(self):
        if self.running:
            return
        values = self._get_values()
        # SteamGridDB API key is optional; thumbnails use Steam CDN when not set
        required = [
            "steam_library_vdf_path",
            "sunshine_apps_json_path",
            "sunshine_grids_folder",
        ]
        missing = [k for k in required if not values.get(k)]
        if missing:
            messagebox.showerror(
                "Missing settings",
                "Please set: " + ", ".join(ENV_KEYS.get(k, k) for k in missing),
            )
            return
        # Save so CLI and subprocess see same config
        save_env_to_file(values, self._get_host())
        self.running = True
        self.run_btn.configure(state="disabled")
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.insert("end", "Running...\n\n")
        self.log_text.configure(state="disabled")
        self.log_queue = queue.Queue()
        thread = threading.Thread(
            target=run_automation,
            args=(
                values,
                self.dry_run_var.get(),
                self.verbose_var.get(),
                self.no_restart_var.get(),
                self.log_queue,
            ),
            daemon=True,
        )
        thread.start()

    def _on_remove_games(self):
        """Remove all Steam games from Sunshine/Apollo, keep default apps (Desktop, Steam, etc.)."""
        if self.running:
            return
        values = self._get_values()
        apps_path = values.get("sunshine_apps_json_path", "").strip()
        if not apps_path:
            messagebox.showerror("Missing setting", "Please set the Apps.json path (Sunshine or Apollo config).")
            return
        if not messagebox.askyesno(
            "Remove all games",
            "Remove all Steam games from the host? Default apps (Desktop, Steam client, etc.) will be kept.\n\nContinue?",
            icon="warning",
        ):
            return
        save_env_to_file(values, self._get_host())
        self.running = True
        self.run_btn.configure(state="disabled")
        self.remove_games_btn.configure(state="disabled")
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.insert("end", "Removing all Steam games...\n\n")
        self.log_text.configure(state="disabled")
        self.log_queue = queue.Queue()
        thread = threading.Thread(
            target=run_automation,
            args=(
                values,
                False,
                self.verbose_var.get(),
                self.no_restart_var.get(),
                self.log_queue,
                True,  # remove_games
            ),
            daemon=True,
        )
        thread.start()

    def _poll_log(self):
        try:
            while True:
                msg = self.log_queue.get_nowait()
                if msg[0] == "done":
                    self.running = False
                    try:
                        self.run_btn.configure(state="normal")
                        self.remove_games_btn.configure(state="normal")
                    except Exception:
                        pass
                    continue
                kind, line = msg[0], msg[1]
                self.log_text.configure(state="normal")
                self.log_text.insert("end", line)
                self.log_text.see("end")
                self.log_text.configure(state="disabled")
        except queue.Empty:
            pass
        self.root.after(200, self._poll_log)

    def run(self):
        self.root.mainloop()


def main():
    _request_admin_and_rerun()
    if sys.platform != "win32":
        print("This GUI is intended for Windows. On other platforms use: python main.py")
        # Still allow running for testing on Mac
    app = SunshineGUI()
    app.run()


if __name__ == "__main__":
    main()
