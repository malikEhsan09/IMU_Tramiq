import tkinter as tk
from tkinter import messagebox, ttk
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.widgets as widgets
from matplotlib.patches import Rectangle
import os
import subprocess
import glob
import io
import contextily as ctx   # <-- NEW: for map tiles

# ─────────────────────────────────────────────────────────────────────────────
#  Color palette & font constants – Light theme
# ─────────────────────────────────────────────────────────────────────────────
C_BG        = "#f8f9fa"   # window background (off-white)
C_SURFACE   = "#ffffff"   # card / panel background (white)
C_BORDER    = "#dee2e6"   # subtle borders (light grey)
C_ACCENT    = "#0d6efd"   # blue accent (Run button)
C_ACCENT_H  = "#0b5ed7"   # accent hover
C_DANGER    = "#dc3545"   # red (Exit button)
C_DANGER_H  = "#bb2d3b"
C_TEXT      = "#212529"   # primary text (dark grey)
C_MUTED     = "#6c757d"   # secondary / placeholder text
C_HIGHLIGHT = "#0d6efd"   # blue – radio / focus ring
C_BADGE_BG  = "#e9ecef"   # badge / pill background
C_STATUS_OK = "#198754"
C_STATUS_ERR= "#dc3545"

FONT_HEAD   = ("Segoe UI", 18, "bold")
FONT_SUB    = ("Segoe UI", 10)
FONT_LABEL  = ("Segoe UI", 10)
FONT_MONO   = ("Consolas", 9)
FONT_BTN    = ("Segoe UI Semibold", 10, "bold")
FONT_SMALL  = ("Segoe UI", 8)

# ─────────────────────────────────────────────────────────────────────────────

class INS_GUI:
    def __init__(self, root):
        self.root = root
        self.root.title("TRAMIQ INS/GNSS Navigation Solution System")
        self.root.geometry("820x680")
        self.root.configure(bg=C_BG)
        self.root.resizable(True, True)

        # Data containers
        self.config          = None
        self.errors_df       = None
        self.traj_df         = None
        self.gnss_ref_df     = None
        self.prn_df = None
        self.outages         = []
        self.outage_info     = []  # Store outage intervals for patches
        self.outage_points   = []  # Store end-of-outage points
        self.config_dir      = ""
        self.sim_mode        = tk.StringVar(value="LCA")

        # Changes to Run in AGX
        self.app_dir = os.path.dirname(os.path.abspath(__file__))

        self._apply_style()
        self.create_widgets()
    
    def _resolve_config_relative_path(self, config_file, path_value):
        """Resolve dataset paths relative to the config file directory."""
        if not path_value:
            return ""
        if os.path.isabs(path_value):
            return path_value
        return os.path.normpath(os.path.join(os.path.dirname(config_file), path_value))


    def compute_display_time_bounds(self, config_file, config):
        """
        Compute the actual old_time and end_time values for display in the outage editor.
        If config uses explicit numeric values, keep them.
        If config uses 'auto', compute them from IMU and GNSS reference files.
        """
        old_time_value = config.get('old_time', 'auto')
        end_time_value = config.get('end_time', 'auto')

        # If both are already numeric, nothing to compute
        if old_time_value != 'auto' and end_time_value != 'auto':
            return old_time_value, end_time_value

        imu_path = self._resolve_config_relative_path(config_file, config.get('imu_file', ''))
        gnss_ref_path = self._resolve_config_relative_path(config_file, config.get('gnss_file', ''))

        try:
            imu_df = pd.read_csv(imu_path, header=None)
            gnss_df = pd.read_csv(gnss_ref_path, header=None)

            # old_time auto = max(IMUData[99], referenceLLA[9 + referenceLLA.size(0)])
            # Python equivalent:
            #   IMUData[99] -> 100th row, column 1
            #   referenceLLA[9 + rows] -> 10th row, column 2
            if old_time_value == 'auto':
                if len(imu_df) > 99 and len(gnss_df) > 9 and imu_df.shape[1] > 0 and gnss_df.shape[1] > 1:
                    old_time_value = max(
                        float(imu_df.iloc[99, 0]),
                        float(gnss_df.iloc[9, 1])
                    )

            # end_time auto = min(last IMU time, last reference time)
            if end_time_value == 'auto':
                if not imu_df.empty and not gnss_df.empty and imu_df.shape[1] > 0 and gnss_df.shape[1] > 1:
                    end_time_value = min(
                        float(imu_df.iloc[-1, 0]),
                        float(gnss_df.iloc[-1, 1])
                    )

        except Exception as e:
            print(f"Warning: could not compute auto time bounds from files: {e}")

        return old_time_value, end_time_value
    
    # ─── runtime config for outages ──────────────────────────────────────────────────
    def create_runtime_config(self, original_config_file, updated_outages, selected_algo, gnss_intend_no_meas=None):
        """Create a temporary config file with edited outage values."""
        with open(original_config_file, "r") as f:
            lines = f.readlines()

        filtered_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("outage_") or stripped.startswith("outage_intervals_count"):
                continue
            if stripped.startswith("gnss_intend_no_meas"):
                continue
            filtered_lines.append(line.rstrip("\n"))

        if selected_algo == "TCA" and gnss_intend_no_meas is not None:
            filtered_lines.append(f"gnss_intend_no_meas={gnss_intend_no_meas}")

        filtered_lines.append(f"outage_intervals_count={len(updated_outages)}")

        for i, outage in enumerate(updated_outages, start=1):
            if selected_algo == "TCA":
                if len(outage) >= 3:
                    start, end, sat_count = outage[0], outage[1], outage[2]
                else:
                    start, end, sat_count = outage[0], outage[1], 0.0
                filtered_lines.append(f"outage_{i}={start},{end},{sat_count}")
            else:
                start, end = outage[0], outage[1]
                filtered_lines.append(f"outage_{i}={start},{end}")

        runtime_config_file = os.path.join(
            os.path.dirname(original_config_file),
            "_runtime_config.txt"
        )

        with open(runtime_config_file, "w") as f:
            f.write("\n".join(filtered_lines) + "\n")

        return runtime_config_file

    def _format_comment_block(self, comment_text):
        lines = comment_text.rstrip("\n").splitlines()
        block = ['comment = """']
        block.extend(lines)
        block.append('"""')
        return block

    def save_config_comment(self, config_file, comment_text):
        with open(config_file, 'r') as f:
            lines = f.readlines()

        def is_comment_key_line(line):
            stripped = line.strip()
            if not stripped or '=' not in stripped:
                return False
            key = stripped.split('=', 1)[0].strip()
            return key == 'comment'

        new_lines = []
        i = 0
        while i < len(lines):
            line = lines[i]
            if is_comment_key_line(line):
                stripped = line.strip()
                value = stripped.split('=', 1)[1].strip()
                if value.startswith('"""') or value.startswith("'''"):
                    quote = value[:3]
                    if value.endswith(quote) and len(value) >= 6:
                        i += 1
                        continue
                    i += 1
                    while i < len(lines):
                        if lines[i].strip().endswith(quote):
                            i += 1
                            break
                        i += 1
                    continue
                i += 1
                continue
            new_lines.append(line.rstrip('\n'))
            i += 1

        if comment_text.strip():
            if new_lines and new_lines[-1].strip() != "":
                new_lines.append("")
            new_lines.extend(self._format_comment_block(comment_text))

        with open(config_file, 'w') as f:
            f.write("\n".join(new_lines).rstrip("\n") + "\n")

    def ask_comment_edit(self, config_file, current_comment):
        dialog = tk.Toplevel(self.root)
        dialog.title("Edit Dataset Comment")
        dialog.configure(bg=C_BG)
        dialog.transient(self.root)
        dialog.resizable(True, True)
        # dialog.grab_set()

        body = tk.Frame(dialog, bg=C_BG)
        body.pack(fill=tk.BOTH, expand=True, padx=16, pady=16)

        tk.Label(body, text="Edit dataset comment:",
                 font=FONT_LABEL, bg=C_BG, fg=C_TEXT).pack(anchor=tk.W, pady=(0, 8))

        text_frame = tk.Frame(body, bg=C_SURFACE)
        text_frame.pack(fill=tk.BOTH, expand=True)

        txt = tk.Text(text_frame,
                      font=FONT_LABEL, bg=C_SURFACE, fg=C_TEXT,
                      insertbackground=C_TEXT, relief="flat", bd=0,
                      wrap=tk.WORD, highlightthickness=0)
        txt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        vsb = tk.Scrollbar(text_frame, command=txt.yview)
        txt.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        if current_comment:
            txt.insert(tk.END, current_comment)

        result = {'comment': None}

        def on_save():
            result['comment'] = txt.get("1.0", tk.END).rstrip()
            try:
                self.save_config_comment(config_file, result['comment'])
                dialog.destroy()
            except Exception as exc:
                messagebox.showerror(
                    "Save Error",
                    f"Could not save comment to config file:\n{exc}",
                    parent=dialog
                )

        def on_cancel():
            dialog.destroy()

        btn_row = tk.Frame(body, bg=C_BG)
        btn_row.pack(fill=tk.X, pady=(12, 0))
        self._flat_btn(btn_row, "✔  Save", on_save,
                       bg=C_ACCENT, hover=C_ACCENT_H).pack(side=tk.RIGHT)
        self._flat_btn(btn_row, "✕  Close", on_cancel,
                       bg=C_DANGER, hover=C_DANGER_H).pack(side=tk.RIGHT,
                                                        padx=(8, 0))

        dialog.update_idletasks()
        pw = self.root.winfo_x() + self.root.winfo_width() // 2
        ph = self.root.winfo_y() + self.root.winfo_height() // 2
        dw, dh = dialog.winfo_width(), dialog.winfo_height()
        dialog.geometry(f"+{pw - dw//2}+{ph - dh//2}")
        dialog.lift()
        dialog.focus_force()
        txt.focus_set()

        self.root.wait_window(dialog)
        return result['comment']

    # ─── ttk / global style ──────────────────────────────────────────────────
    def _apply_style(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(".",
                        background=C_BG, foreground=C_TEXT,
                        font=FONT_LABEL, borderwidth=0)
        style.configure("TFrame",  background=C_BG)
        style.configure("Card.TFrame", background=C_SURFACE,
                        relief="flat", borderwidth=1)
        style.configure("TLabel",  background=C_BG, foreground=C_TEXT)
        style.configure("Muted.TLabel", foreground=C_MUTED, background=C_BG)
        style.configure("TRadiobutton",
                        background=C_SURFACE, foreground=C_TEXT,
                        selectcolor=C_HIGHLIGHT, indicatorcolor=C_HIGHLIGHT,
                        font=FONT_LABEL)
        style.map("TRadiobutton",
                  background=[("active", C_SURFACE)],
                  foreground=[("active", C_TEXT)])

    # ─── Widget creation ──────────────────────────────────────────────────────
    def create_widgets(self):
        # ── Top header strip ────────────────────────────────────────────────
        header = tk.Frame(self.root, bg=C_BG, height=64)
        header.pack(fill=tk.X)
        header.pack_propagate(False)

        # Tiny "logo" dot
        dot = tk.Canvas(header, width=10, height=10,
                        bg=C_BG, highlightthickness=0)
        dot.pack(side=tk.LEFT, padx=(20, 6), pady=22)
        dot.create_oval(0, 0, 10, 10, fill=C_ACCENT, outline="")

        tk.Label(header,
                 text="INS/GNSS  Loosely & Tightly Coupled Integration",
                 font=FONT_HEAD, bg=C_BG, fg=C_TEXT).pack(side=tk.LEFT)
        tk.Label(header, text="Visualization & Analysis Tool",
                 font=FONT_SMALL, bg=C_BG, fg=C_MUTED).pack(
                 side=tk.LEFT, padx=(12, 0), pady=(8, 0))

        # ── Thin accent line ─────────────────────────────────────────────────
        tk.Frame(self.root, height=2, bg=C_HIGHLIGHT).pack(fill=tk.X)

        # ── Main scrollable content area ─────────────────────────────────────
        outer = tk.Frame(self.root, bg=C_BG)
        outer.pack(fill=tk.BOTH, expand=True, padx=24, pady=16)

        # ── Section: Algorithm ───────────────────────────────────────────────
        self._section_label(outer, "ALGORITHM")
        algo_card = self._card(outer)

        # Square radio buttons using checkbuttons with indicatoron=0
        self.radio_vars = {}
        self.algo_buttons = {}
        modes = [("LCA – Loosely Coupled Algorithm", "LCA"),
                 ("TCA – Tightly Coupled Algorithm",  "TCA")]

        for text, val in modes:
            var = tk.IntVar(value=1 if val == "LCA" else 0)
            self.radio_vars[val] = var
            btn = tk.Checkbutton(
                algo_card,
                text=text,
                variable=var,
                onvalue=1,
                offvalue=0,
                command=lambda v=val: self._exclusive_radio(v),
                bg=C_SURFACE,
                fg=C_TEXT,
                activebackground=C_SURFACE,
                activeforeground=C_ACCENT,
                selectcolor=C_HIGHLIGHT,
                font=FONT_LABEL,
                cursor="hand2",
                indicatoron=0,
                relief="raised",
                bd=1,
                padx=10,
                pady=5,
                highlightthickness=0)
            btn.pack(anchor=tk.W, padx=14, pady=4)
            self.algo_buttons[val] = btn
            if val == "LCA":
                var.set(1)

        self._update_algo_button_colors()

        # ── Section: Dataset ─────────────────────────────────────────────────
        self._section_label(outer, "DATASET")
        ds_card = self._card(outer)

        script_dir = os.path.dirname(os.path.abspath(__file__))

        # Collect LCA_Traj*_PreRec*_config.txt and TCA_Traj*_PreRec*_config.txt.
        # Group by (TrajN, PreRecN); store both algo paths per dataset.
        import re
        _pat = re.compile(
            r"(LCA|TCA)_Traj(\d+)_PreRec(\d+)_config\.txt$", re.IGNORECASE)
        _dataset_map = {}   # (traj, prerec) -> {'LCA': path|None, 'TCA': path|None}
        for p in sorted(
            glob.glob(os.path.join(script_dir, "LCA_Traj*_PreRec*_config.txt")) +
            glob.glob(os.path.join(script_dir, "TCA_Traj*_PreRec*_config.txt"))
        ):
            m = _pat.search(os.path.basename(p))
            if m:
                algo = m.group(1).upper()
                key  = (int(m.group(2)), int(m.group(3)))
                if key not in _dataset_map:
                    _dataset_map[key] = {'LCA': None, 'TCA': None}
                _dataset_map[key][algo] = p

        # self.dataset_paths: list of {'LCA': str|None, 'TCA': str|None}
        self.dataset_vars  = []
        self.dataset_paths = []

        if _dataset_map:
            from collections import defaultdict
            _traj_groups = defaultdict(list)
            for (traj_num, prerec_num), paths in _dataset_map.items():
                _traj_groups[traj_num].append((prerec_num, paths))

            for traj_num in sorted(_traj_groups):
                # Trajectory header
                traj_hdr = tk.Frame(ds_card, bg=C_SURFACE)
                traj_hdr.pack(fill=tk.X, padx=14, pady=(10, 2))
                tk.Label(traj_hdr,
                         text=f"Trajectory {traj_num}",
                         font=("Segoe UI", 10, "bold"),
                         bg=C_SURFACE, fg=C_ACCENT).pack(side=tk.LEFT)
                tk.Frame(traj_hdr, height=1, bg=C_BORDER).pack(
                    side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 0), pady=6)

                for prerec_num, paths in sorted(_traj_groups[traj_num]):
                    var = tk.IntVar()
                    row_frame = tk.Frame(ds_card, bg=C_SURFACE)
                    row_frame.pack(fill=tk.X, padx=28, pady=2)

                    cb = tk.Checkbutton(
                        row_frame,
                        text=f"Prerecorded Data {prerec_num}",
                        variable=var,
                        command=lambda v=var: self._only_one_selected(v),
                        bg=C_SURFACE, fg=C_TEXT,
                        activebackground=C_SURFACE, activeforeground=C_ACCENT,
                        selectcolor=C_BADGE_BG,
                        font=FONT_LABEL,
                        cursor="hand2",
                        relief="flat", bd=0,
                        highlightthickness=0)
                    cb.pack(side=tk.LEFT)

                    for algo in ("LCA", "TCA"):
                        if paths[algo]:
                            tk.Label(row_frame, text=algo,
                                     font=FONT_SMALL,
                                     bg=C_BADGE_BG, fg=C_MUTED,
                                     padx=5, pady=1,
                                     relief="flat").pack(side=tk.RIGHT, padx=2)

                    self.dataset_vars.append(var)
                    self.dataset_paths.append(paths)

            tk.Frame(ds_card, bg=C_SURFACE, height=6).pack()

        else:
            tk.Label(ds_card,
                     text="⚠  No LCA/TCA_Traj*_PreRec*_config.txt files found in script directory.",
                     bg=C_SURFACE, fg="#e3b341",
                     font=FONT_LABEL).pack(padx=14, pady=10)

        # ── Section: Actions ─────────────────────────────────────────────────
        self._section_label(outer, "ACTIONS")
        btn_card = self._card(outer)
        btn_row  = tk.Frame(btn_card, bg=C_SURFACE)
        btn_row.pack(padx=14, pady=12)

        self._flat_btn(btn_row, "▶  Run Algorithm",
                       self.run_simulation,
                       bg=C_ACCENT, hover=C_ACCENT_H).pack(side=tk.LEFT, padx=(0, 10))
        self._flat_btn(btn_row, "✕  Exit",
                       self.root.quit,
                       bg=C_DANGER, hover=C_DANGER_H).pack(side=tk.LEFT)

        # ── Status bar ───────────────────────────────────────────────────────
        status_bar = tk.Frame(self.root, bg=C_BG, height=28)
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)
        status_bar.pack_propagate(False)

        self._status_dot = tk.Canvas(status_bar, width=8, height=8,
                                     bg=C_BG, highlightthickness=0)
        self._status_dot.pack(side=tk.LEFT, padx=(12, 4), pady=10)
        self._status_dot_id = self._status_dot.create_oval(
            0, 0, 8, 8, fill=C_MUTED, outline="")

        self.status = tk.Label(status_bar,
                               text="Ready — select a dataset and algorithm to begin.",
                               font=FONT_SMALL, bg=C_BG, fg=C_MUTED,
                               anchor=tk.W)
        self.status.pack(side=tk.LEFT, fill=tk.X)

    # ─── UI helpers ──────────────────────────────────────────────────────────
    def _section_label(self, parent, text):
        row = tk.Frame(parent, bg=C_BG)
        row.pack(fill=tk.X, pady=(12, 4))
        tk.Label(row, text=text,
                 font=("Segoe UI", 8, "bold"),
                 bg=C_BG, fg=C_MUTED).pack(side=tk.LEFT)
        tk.Frame(row, height=1, bg=C_BORDER).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 0), pady=6)

    def _card(self, parent):
        outer = tk.Frame(parent, bg=C_BORDER, bd=0)
        outer.pack(fill=tk.X, pady=(0, 4))
        inner = tk.Frame(outer, bg=C_SURFACE, bd=0)
        inner.pack(fill=tk.X, padx=1, pady=1)
        return inner

    def _flat_btn(self, parent, text, cmd, bg, hover):
        text_color = 'white' if bg in (C_ACCENT, C_ACCENT_H, C_DANGER, C_DANGER_H, C_HIGHLIGHT) else C_TEXT
        btn = tk.Button(parent, text=text, command=cmd,
                        font=FONT_BTN,
                        bg=bg, fg=text_color,
                        activebackground=hover, activeforeground=text_color,
                        relief="flat", bd=0, cursor="hand2",
                        padx=20, pady=8,
                        highlightthickness=0)
        btn.bind("<Enter>", lambda e, b=btn, h=hover: b.config(bg=h))
        btn.bind("<Leave>", lambda e, b=btn, n=bg:    b.config(bg=n))
        return btn

    def _set_status(self, msg, state="idle"):
        colour = {
            "idle":  C_MUTED,
            "busy":  "#fd7e14",
            "ok":    C_STATUS_OK,
            "error": C_STATUS_ERR,
        }.get(state, C_MUTED)
        self.status.config(text=msg, fg=colour)
        self._status_dot.itemconfig(self._status_dot_id, fill=colour)
        self.root.update()

    def _update_algo_button_colors(self):
        for val, btn in self.algo_buttons.items():
            if self.radio_vars[val].get() == 1:
                btn.config(fg='white')
            else:
                btn.config(fg=C_TEXT)

    def _only_one_selected(self, selected_var):
        for var in self.dataset_vars:
            if var is not selected_var:
                var.set(0)

    def _exclusive_radio(self, selected_val):
        for val, var in self.radio_vars.items():
            if val == selected_val:
                var.set(1)
            else:
                var.set(0)
        self.sim_mode.set(selected_val)
        self._update_algo_button_colors()

    # ─── Outage editor dialog (ONLY for LCA) ────────────────────────────────
    def ask_outage_changes(self, config_file, default_outages,
                       old_time_value='auto', end_time_value='auto',
                       include_sat_count=False, gnss_intend_no_meas=40):
        dialog = tk.Toplevel(self.root)
        dialog.title("Outage Intervals")
        dialog.configure(bg=C_BG)
        dialog.resizable(False, False)
        # dialog.grab_set()

        hdr = tk.Frame(dialog, bg=C_BG)
        hdr.pack(fill=tk.X)
        tk.Label(hdr, text="Outage Intervals",
                font=FONT_HEAD, bg=C_BG, fg=C_TEXT,
                padx=20, pady=14).pack(side=tk.LEFT)
        tk.Frame(dialog, height=2, bg=C_HIGHLIGHT).pack(fill=tk.X)

        body = tk.Frame(dialog, bg=C_BG, padx=20, pady=14)
        body.pack(fill=tk.BOTH, expand=True)

        tk.Label(body,
                text=f"Config file:  {os.path.basename(config_file)}",
                font=FONT_MONO, bg=C_BG, fg=C_MUTED).pack(anchor=tk.W, pady=(0, 10))
        boundary_text = (
            f"Allowed outage boundary  →  start: {old_time_value} s   |   stop: {end_time_value} s"
        )

        tk.Label(body,
                text=boundary_text,
                font=FONT_MONO,
                bg=C_BG,
                fg=C_ACCENT,
                justify=tk.LEFT).pack(anchor=tk.W, pady=(0, 8))

        info_text = (
            "Edit start / end times (seconds) below.\n"
            "Add or remove rows as needed, then click Apply & Continue.\n"
            "NOTE: Maximum outage duration is 20 seconds. Changes are used only for this run."
        )
        if include_sat_count:
            info_text = (
            "Edit start / end times and max GNSS measurements below.\n"
            "For TCA, max allowable GNSS sats in normal condition (without outage).\n"
            "NOTE: Maximum outage duration is 20 seconds."
            )

        tk.Label(body, text=info_text,
                font=FONT_LABEL, bg=C_BG, fg=C_TEXT,
                justify=tk.LEFT).pack(anchor=tk.W, pady=(0, 12))

        gnss_intend_no_meas_var = tk.StringVar(value=str(gnss_intend_no_meas))
        if include_sat_count:
            param_row = tk.Frame(body, bg=C_BG)
            param_row.pack(fill=tk.X, pady=(0, 10))
            tk.Label(param_row, text="Max GNSS sats for TCA:",
                    font=FONT_LABEL, bg=C_BG, fg=C_TEXT).pack(side=tk.LEFT)
            tk.Entry(param_row, textvariable=gnss_intend_no_meas_var,
                     font=FONT_MONO, width=6,
                     bg=C_BADGE_BG, fg=C_TEXT,
                     insertbackground=C_TEXT,
                     relief="flat", bd=4,
                     highlightthickness=1,
                     highlightcolor=C_HIGHLIGHT,
                     highlightbackground=C_BORDER).pack(side=tk.LEFT, padx=(8, 0))
            tk.Label(param_row,
                    text="(3–40)",
                    font=FONT_SMALL, bg=C_BG, fg=C_MUTED).pack(side=tk.LEFT, padx=(8, 0))

        col_hdr = tk.Frame(body, bg=C_BG)
        col_hdr.pack(fill=tk.X)

        columns = [("#", 3), ("Start (s)", 12), ("End (s)", 12)]

        for col_text, w in columns:
            tk.Label(col_hdr, text=col_text,
                    font=("Segoe UI", 9, "bold"),
                    bg=C_BG, fg=C_MUTED, width=w,
                    anchor=tk.W).pack(side=tk.LEFT, padx=4)

        list_outer = tk.Frame(body, bg=C_BORDER)
        list_outer.pack(fill=tk.X, pady=(4, 12))
        list_inner = tk.Frame(list_outer, bg=C_SURFACE)
        list_inner.pack(fill=tk.X, padx=1, pady=1)

        entry_rows = []

        def _make_entry(parent, textvariable, w=12):
            e = tk.Entry(parent, textvariable=textvariable,
                        font=FONT_MONO, width=w,
                        bg=C_BADGE_BG, fg=C_TEXT,
                        insertbackground=C_TEXT,
                        relief="flat", bd=4,
                        highlightthickness=1,
                        highlightcolor=C_HIGHLIGHT,
                        highlightbackground=C_BORDER)
            return e

        def add_row(start_val="", end_val="", sat_count_val="0"):
            idx = len(entry_rows) + 1
            rf = tk.Frame(list_inner, bg=C_SURFACE)
            rf.pack(fill=tk.X, pady=2, padx=6)

            tk.Label(rf, text=str(idx), width=3,
                    font=FONT_MONO, bg=C_SURFACE, fg=C_MUTED,
                    anchor=tk.W).pack(side=tk.LEFT, padx=4)

            sv = tk.StringVar(value=str(start_val))
            ev = tk.StringVar(value=str(end_val))
            scv = tk.StringVar(value=str(sat_count_val))

            _make_entry(rf, sv).pack(side=tk.LEFT, padx=4)
            _make_entry(rf, ev).pack(side=tk.LEFT, padx=4)


            def _remove_row(rt):
                rt[3].destroy()
                entry_rows.remove(rt)
                _renumber()

            row_tuple = (sv, ev, scv, rf)
            del_btn = tk.Button(rf, text="✕",
                                command=lambda rt=row_tuple: _remove_row(rt),
                                font=FONT_SMALL,
                                bg=C_SURFACE, fg=C_MUTED,
                                activebackground=C_DANGER, activeforeground=C_TEXT,
                                relief="flat", bd=0, cursor="hand2")
            del_btn.pack(side=tk.LEFT, padx=4)

            entry_rows.append(row_tuple)

        def _renumber():
            for i, (sv, ev, scv, rf) in enumerate(entry_rows):
                widgets_in_row = rf.winfo_children()
                if widgets_in_row:
                    widgets_in_row[0].config(text=str(i + 1))

        for outage in default_outages:
            if len(outage) >= 3:
                add_row(outage[0], outage[1], outage[2])
            else:
                add_row(outage[0], outage[1], 0)

        ctrl = tk.Frame(body, bg=C_BG)
        ctrl.pack(fill=tk.X, pady=(0, 8))
        self._flat_btn(ctrl, "+  Add Row", lambda: add_row(),
                    bg=C_BADGE_BG, hover=C_BORDER).pack(side=tk.LEFT)

        result = {"outages": None, "gnss_intend_no_meas": gnss_intend_no_meas}

        def on_apply():
            new_outages = []

            start_limit = None if old_time_value == 'auto' else float(old_time_value)
            end_limit = None if end_time_value == 'auto' else float(end_time_value)

            for i, (sv, ev, scv, rf) in enumerate(entry_rows):
                s_str = sv.get().strip()
                e_str = ev.get().strip()
                sc_str = scv.get().strip()

                if not s_str and not e_str:
                    continue

                try:
                    s = float(s_str)
                    e = float(e_str)
                except ValueError:
                    messagebox.showerror(
                        "Invalid Input",
                        f"Row {i+1}: start and end must be numbers.",
                        parent=dialog)
                    return

                if start_limit is not None and s < start_limit:
                    messagebox.showerror(
                        "Invalid Input",
                        f"Row {i+1}: outage start ({s}) is before simulation start ({start_limit}).",
                        parent=dialog)
                    return

                if end_limit is not None and e > end_limit:
                    messagebox.showerror(
                        "Invalid Input",
                        f"Row {i+1}: outage end ({e}) is after simulation stop ({end_limit}).",
                        parent=dialog)
                    return

                if s >= e:
                    messagebox.showerror(
                        "Invalid Input",
                        f"Row {i+1}: start ({s}) must be less than end ({e}).",
                        parent=dialog)
                    return

                duration = e - s
                if duration > 20.0:
                    messagebox.showerror(
                        "Invalid Input",
                        f"Row {i+1}: outage duration ({duration:.1f} s) exceeds maximum allowed (20.0 s).",
                        parent=dialog)
                    return

                new_outages.append((s, e))

            if include_sat_count:
                gnss_val = gnss_intend_no_meas_var.get().strip()
                try:
                    gnss_intend = int(gnss_val)
                    if gnss_intend < 3 or gnss_intend > 40:
                        raise ValueError
                except ValueError:
                    messagebox.showerror(
                        "Invalid Input",
                        "Max GNSS sats for TCA must be an integer between 3 and 40.",
                        parent=dialog)
                    return
                result["gnss_intend_no_meas"] = gnss_intend

            result["outages"] = new_outages
            dialog.destroy()

        def on_cancel():
            dialog.destroy()

        sep = tk.Frame(body, height=1, bg=C_BORDER)
        sep.pack(fill=tk.X, pady=(8, 12))

        btn_row = tk.Frame(body, bg=C_BG)
        btn_row.pack(fill=tk.X)
        self._flat_btn(btn_row, "✔  Continue",
                    on_apply, bg=C_ACCENT, hover=C_ACCENT_H).pack(
                    side=tk.RIGHT, padx=(8, 0))
        self._flat_btn(btn_row, "✕  Cancel",
                    on_cancel, bg=C_BADGE_BG, hover=C_BORDER).pack(
                    side=tk.RIGHT)

        dialog.update_idletasks()
        pw = self.root.winfo_x() + self.root.winfo_width() // 2
        ph = self.root.winfo_y() + self.root.winfo_height() // 2
        dw, dh = dialog.winfo_width(), dialog.winfo_height()
        dialog.geometry(f"+{pw - dw//2}+{ph - dh//2}")

        self.root.wait_window(dialog)
        return result

    # ─── Dataset preview window (FIXED) ──────────────────────────────────────────────
    def show_dataset_preview(self, config_file, config, on_set_outage=None, on_close=None):
        """
        Non-blocking Toplevel with editable comments.
        Left: GNSS reference trajectory.
        Right: Editable dataset comments with Save button.
        """
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
        from matplotlib.figure import Figure
        from matplotlib.lines import Line2D

        win = tk.Toplevel(self.root)
        dataset_name = config.get('dataset_name', '') or os.path.basename(config_file)
        win.title(f"Reference Trajectory")
        win.configure(bg=C_BG)
        win.geometry("1200x700")
        win.resizable(True, True)

        # Header
        hdr = tk.Frame(win, bg=C_BG)
        hdr.pack(fill=tk.X)
        tk.Label(hdr, text=f"{dataset_name}",
                font=FONT_HEAD, bg=C_BG, fg=C_TEXT,
                padx=20, pady=10).pack(side=tk.LEFT)

        tk.Frame(win, height=2, bg=C_HIGHLIGHT).pack(fill=tk.X)

        # Main container with paned window
        main_pane = tk.PanedWindow(win, bg=C_BG, sashrelief="raised", sashwidth=6)
        main_pane.pack(fill=tk.BOTH, expand=True, padx=16, pady=12)

        # ── LEFT PANEL: Map ────────────────────────────────────────────────────
        left_frame = tk.Frame(main_pane, bg=C_BG)
        main_pane.add(left_frame, width=750, minsize=400)

        map_outer = tk.Frame(left_frame, bg=C_BORDER, bd=0)
        map_outer.pack(fill=tk.BOTH, expand=True)
        map_inner = tk.Frame(map_outer, bg=C_SURFACE, bd=0)
        map_inner.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

        fig = Figure(figsize=(8, 6), facecolor="white", dpi=100)
        fig.subplots_adjust(left=0.08, right=0.95, top=0.92, bottom=0.08)
        ax = fig.add_subplot(111)
        ax.set_facecolor('#fafafa')

        gnss_path = self._resolve_config_relative_path(
            config_file, config.get('gnss_file', ''))
        preview_ok = False

        def _clean_gnss_trajectory(lats_raw, lons_raw, times_raw, max_speed_kms=0.5, iqr_scale=1.5):
            import pandas as _pd
            import math
            s_lat = _pd.Series(lats_raw)
            s_lon = _pd.Series(lons_raw)
            s_time = _pd.Series(times_raw)
            dt = s_time.diff()
            dlat = s_lat.diff()
            dlon = s_lon.diff()
            lat_avg = (s_lat + s_lat.shift(1)) / 2
            dlat_m = dlat * 111000
            dlon_m = dlon * 111000 * _pd.Series([math.cos(math.radians(lat)) for lat in lat_avg])
            dist_m = (dlat_m**2 + dlon_m**2)**0.5
            speed_ms = dist_m / dt
            max_speed_ms = max_speed_kms * 1000
            keep_mask = (speed_ms <= max_speed_ms) | speed_ms.isna()
            s_lat_c = s_lat[keep_mask].reset_index(drop=True)
            s_lon_c = s_lon[keep_mask].reset_index(drop=True)
            s_time_c = s_time[keep_mask].reset_index(drop=True)
            dlat_c = s_lat_c.diff().abs()
            dlon_c = s_lon_c.diff().abs()
            disp_c = (dlat_c**2 + dlon_c**2)**0.5
            q1, q3 = disp_c.quantile(0.25), disp_c.quantile(0.75)
            iqr = q3 - q1
            thresh = q3 + iqr_scale * iqr
            keep_mask_iqr = (disp_c <= thresh) | disp_c.isna()
            s_lat_c2 = s_lat_c[keep_mask_iqr].reset_index(drop=True)
            s_lon_c2 = s_lon_c[keep_mask_iqr].reset_index(drop=True)
            roll_win = 15
            half = roll_win // 2
            s_lat_s = s_lat_c2.rolling(roll_win, center=True, min_periods=half).median()
            s_lon_s = s_lon_c2.rolling(roll_win, center=True, min_periods=half).median()
            s_lat_s = s_lat_s.fillna(s_lat_c2)
            s_lon_s = s_lon_s.fillna(s_lon_c2)
            return s_lat_s.values, s_lon_s.values, s_lat_c2.values, s_lon_c2.values

        try:
            gdf = pd.read_csv(gnss_path, header=None)
            col_lat = int(config.get('gnss_col_lat', 2))
            col_lon = int(config.get('gnss_col_lon', 3))
            col_time = int(config.get('gnss_col_time', 1))
            lats_raw = gdf.iloc[:, col_lat].astype(float).values
            lons_raw = gdf.iloc[:, col_lon].astype(float).values
            times_raw = gdf.iloc[:, col_time].astype(float).values

            if len(lats_raw) > 1:
                lats_s, lons_s, lats_c, lons_c = _clean_gnss_trajectory(
                    lats_raw, lons_raw, times_raw)

                ax.clear()
                ax.set_facecolor('#fafafa')
                ax.plot(lons_s, lats_s,
                        color='#0d6efd', linewidth=2, alpha=0.9, zorder=2,
                        label='Cleaned trajectory')
                ax.scatter(lons_s[0], lats_s[0], s=180, marker='^',
                        color='#198754', zorder=5,
                        edgecolors='white', linewidths=1.5, label='Start')
                ax.scatter(lons_s[-1], lats_s[-1], s=180, marker='s',
                        color='#dc3545', zorder=5,
                        edgecolors='white', linewidths=1.5, label='End')

                span_lat = (lats_s.max() - lats_s.min()) * 0.02 or 0.0005
                span_lon = (lons_s.max() - lons_s.min()) * 0.02 or 0.0005
                ax.annotate('START', xy=(lons_s[0], lats_s[0]),
                            xytext=(lons_s[0] + span_lon, lats_s[0] + span_lat),
                            fontsize=8, color='#198754', fontweight='bold',
                            arrowprops=dict(arrowstyle='->', color='#198754', lw=0.8))
                ax.annotate('END', xy=(lons_s[-1], lats_s[-1]),
                            xytext=(lons_s[-1] + span_lon, lats_s[-1] - span_lat),
                            fontsize=8, color='#dc3545', fontweight='bold',
                            arrowprops=dict(arrowstyle='->', color='#dc3545', lw=0.8))

                ax.set_title('Reference Trajectory', fontsize=11, fontweight='bold', pad=12)
                ax.set_xlabel('Longitude (°)', fontsize=10, fontweight='semibold')
                ax.set_ylabel('Latitude (°)', fontsize=10, fontweight='semibold')
                ax.tick_params(labelsize=9)
                ax.grid(True, linestyle='--', alpha=0.5, color='#cccccc')
                ax.set_aspect('equal', adjustable='box')

                min_lon, max_lon = lons_s.min(), lons_s.max()
                min_lat, max_lat = lats_s.min(), lats_s.max()
                dlon = max_lon - min_lon or 0.001
                dlat = max_lat - min_lat or 0.001
                lon_pad = dlon * 0.08
                lat_pad = dlat * 0.08
                ax.set_xlim(min_lon - lon_pad, max_lon + lon_pad)
                ax.set_ylim(min_lat - lat_pad, max_lat + lat_pad)

                legend_elements = [
                    Line2D([0], [0], color='#0d6efd', lw=2, label='Trajectory'),
                    Line2D([0], [0], marker='^', color='#198754', linestyle='None', markersize=10, label='Start'),
                    Line2D([0], [0], marker='s', color='#dc3545', linestyle='None', markersize=10, label='End'),
                ]
                ax.legend(handles=legend_elements, fontsize=9, frameon=True,
                        fancybox=False, edgecolor=C_BORDER, loc='best')
                
                # Add basemap using contextily (if available)
                try:
                    ctx.add_basemap(ax, crs='EPSG:4326', source=ctx.providers.OpenStreetMap.Mapnik)
                except Exception as e:
                    print(f"Could not add basemap: {e}")
                
                preview_ok = True

        except Exception as exc:
            print(f"Dataset preview: could not load GNSS file: {exc}")

        if not preview_ok:
            ax.clear()
            ax.text(0.5, 0.5,
                    "GNSS reference file unavailable\n"
                    f"({os.path.basename(gnss_path) if gnss_path else 'not configured'})",
                    ha='center', va='center', fontsize=10,
                    color=C_MUTED, transform=ax.transAxes)
            ax.set_axis_off()
            ax.set_title('GNSS Reference Trajectory', fontsize=11, fontweight='bold')

        canvas = FigureCanvasTkAgg(fig, master=map_inner)
        canvas.draw()
        toolbar_frame = tk.Frame(map_inner, bg=C_BG)
        toolbar_frame.pack(side=tk.TOP, fill=tk.X)
        toolbar = NavigationToolbar2Tk(canvas, toolbar_frame)
        toolbar.update()
        canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        # ── RIGHT PANEL: Comments (read-only by default, editable on demand) ───
        right_frame = tk.Frame(main_pane, bg=C_BG, width=350)
        main_pane.add(right_frame, width=350, minsize=250)

        # Header row: label + Edit button
        hdr_row = tk.Frame(right_frame, bg=C_BG)
        hdr_row.pack(fill=tk.X, pady=(0, 8))
        tk.Label(hdr_row, text="DATASET-HISTORY",
                font=("Segoe UI", 9, "bold"),
                bg=C_BG, fg=C_MUTED).pack(side=tk.LEFT)

        txt_outer = tk.Frame(right_frame, bg=C_BORDER)
        txt_outer.pack(fill=tk.BOTH, expand=True)
        txt_inner = tk.Frame(txt_outer, bg=C_SURFACE)
        txt_inner.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

        text_frame = tk.Frame(txt_inner, bg=C_SURFACE)
        text_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        # Scrollbar packed first so it never overlaps the text widget
        vsb = tk.Scrollbar(text_frame)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        # Text widget – starts DISABLED (read-only); enabled only during editing
        txt = tk.Text(text_frame,
                    font=FONT_LABEL, bg=C_SURFACE, fg=C_TEXT,
                    insertbackground=C_TEXT, relief="flat", bd=0,
                    wrap=tk.WORD, highlightthickness=1,
                    highlightcolor=C_HIGHLIGHT,
                    highlightbackground=C_BORDER,
                    cursor="arrow",
                    state=tk.DISABLED)
        txt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.config(command=txt.yview)
        txt.configure(yscrollcommand=vsb.set)

        # Load existing comment into the widget
        _initial_comment = config.get('comment', '').strip()
        txt.config(state=tk.NORMAL)
        if _initial_comment:
            txt.insert(tk.END, _initial_comment)
        txt.config(state=tk.DISABLED)

        # ── Button row below the text box ────────────────────────────────────
        btn_row = tk.Frame(right_frame, bg=C_BG)
        btn_row.pack(fill=tk.X, pady=(8, 0))

        # We keep references so we can show/hide them
        edit_btn_ref  = [None]
        save_btn_ref  = [None]
        cancel_btn_ref = [None]

        def enter_edit_mode():
            """Switch the text widget to editable and swap buttons."""
            txt.config(state=tk.NORMAL, cursor="xterm",
                       bg="#fffff8",          # subtle tint to signal edit mode
                       highlightbackground=C_HIGHLIGHT)
            txt.focus_set()
            edit_btn_ref[0].pack_forget()
            save_btn_ref[0].pack(side=tk.LEFT, padx=(0, 6))
            cancel_btn_ref[0].pack(side=tk.LEFT)

        def save_comment():
            """Write the edited text back to the config file, then go read-only."""
            new_comment = txt.get("1.0", tk.END).rstrip()
            try:
                self.save_config_comment(config_file, new_comment)
                config['comment'] = new_comment
                self.config = config
                self._set_status("Comment saved successfully.", "ok")
                leave_edit_mode(new_comment)
                # messagebox.showinfo("Saved", "Comment saved", parent=win)
            except Exception as exc:
                messagebox.showerror("Save Error",
                                     f"Could not save comment:\n{exc}", parent=win)
                self._set_status("Failed to save comment.", "error")

        def cancel_edit():
            """Discard edits and restore original content."""
            current_saved = config.get('comment', '').strip()
            txt.config(state=tk.NORMAL)
            txt.delete("1.0", tk.END)
            if current_saved:
                txt.insert(tk.END, current_saved)
            leave_edit_mode(current_saved)

        def leave_edit_mode(comment_text):
            """Switch back to read-only mode."""
            txt.config(state=tk.DISABLED, cursor="arrow",
                       bg=C_SURFACE, highlightbackground=C_BORDER)
            save_btn_ref[0].pack_forget()
            cancel_btn_ref[0].pack_forget()
            edit_btn_ref[0].pack(side=tk.LEFT)

        edit_btn  = self._flat_btn(btn_row, "✏  Edit Comment",  enter_edit_mode,
                                   bg=C_ACCENT, hover=C_ACCENT_H)
        save_btn  = self._flat_btn(btn_row, "💾  Save",          save_comment,
                                   bg=C_ACCENT,   hover=C_ACCENT_H)
        cancel_btn = self._flat_btn(btn_row, "✕  Close",        cancel_edit,
                                   bg=C_DANGER, hover=C_DANGER_H)
        set_outage_btn = None
        if on_set_outage is not None:
            set_outage_btn = self._flat_btn(
                btn_row, "⚙  Set Outage", on_set_outage,
                bg=C_HIGHLIGHT, hover=C_ACCENT_H
            )

        edit_btn_ref[0]   = edit_btn
        save_btn_ref[0]   = save_btn
        cancel_btn_ref[0] = cancel_btn

        # Start with only the Edit button visible
        edit_btn.pack(side=tk.LEFT)
        if set_outage_btn is not None:
            set_outage_btn.pack(side=tk.LEFT, padx=(8, 0))

        if on_close is not None:
            def _on_preview_close():
                try:
                    on_close()
                finally:
                    win.destroy()
            win.protocol("WM_DELETE_WINDOW", _on_preview_close)

        win.lift()
        win.focus_force()
        return win

    # ─── Run simulation ───────────────────────────────────────────────────────
   
    def run_simulation(self):
        selected_idx = None
        for i, var in enumerate(self.dataset_vars):
            if var.get() == 1:
                selected_idx = i
                break

        if selected_idx is None:
            messagebox.showerror("No Dataset Selected",
                                "Please select a dataset before running.")
            return

        selected_algo = self.sim_mode.get()
        paths_dict    = self.dataset_paths[selected_idx]

        # Pick the config file for the chosen algorithm; fall back with warning
        config_file = paths_dict.get(selected_algo)
        if config_file is None:
            fallback = "TCA" if selected_algo == "LCA" else "LCA"
            config_file = paths_dict.get(fallback)
            if config_file:
                messagebox.showwarning(
                    "Config File Missing",
                    f"No {selected_algo} config file found for this dataset.\n"
                    f"Falling back to the {fallback} config:\n"
                    f"{os.path.basename(config_file)}\n\n"
                    f"Results may be incorrect."
                )
            else:
                messagebox.showerror("Config File Missing",
                                     "No config file found for this dataset.")
                self._set_status("Config file missing.", "error")
                return

        # Parse config
        try:
            self.config = self.parse_config(config_file)
            print(f"Loaded config: {self.config}")
        except Exception as e:
            print(f"Error parsing config: {e}")
            self.config = {
                'outages': [],
                'imu_file': '',
                'gnss_file': '',
                'rawgnss_file': '',
                'dataset_name': 'Unknown',
                'old_time': 'auto',
                'gnss_intend_no_meas': 40
            }

        display_old_time, display_end_time = self.compute_display_time_bounds(
            config_file,
            self.config
        )

        # Open dataset preview first. Outage editor opens only when user clicks "Set Outage".
        flow_state = tk.StringVar(value="pending")
        outage_result = {"value": None}
        preview_ref = {"win": None}

        def open_outage_editor():
            if selected_algo == "LCA":
                result = self.ask_outage_changes(
                    config_file,
                    self.config.get('outages', []),
                    old_time_value=display_old_time,
                    end_time_value=display_end_time,
                    include_sat_count=False
                )
            else:
                result = self.ask_outage_changes(
                    config_file,
                    self.config.get('outages', []),
                    old_time_value=display_old_time,
                    end_time_value=display_end_time,
                    include_sat_count=True,
                    gnss_intend_no_meas=self.config.get('gnss_intend_no_meas', 40)
                )

            if result is not None and result.get('outages') is not None:
                outage_result["value"] = result
                flow_state.set("ready")
                preview_win = preview_ref.get("win")
                if preview_win is not None and preview_win.winfo_exists():
                    preview_win.destroy()

        def on_preview_close():
            if flow_state.get() == "pending":
                flow_state.set("cancelled")

        preview_win = self.show_dataset_preview(
            config_file,
            self.config,
            on_set_outage=open_outage_editor,
            on_close=on_preview_close
        )
        preview_ref["win"] = preview_win
        self.root.wait_variable(flow_state)

        result = outage_result["value"]
        if flow_state.get() != "ready" or result is None:
            self._set_status("Simulation cancelled.", "idle")
            return

        self.config['outages'] = result['outages']
        if selected_algo == "TCA":
            self.config['gnss_intend_no_meas'] = result.get('gnss_intend_no_meas',
                                                           self.config.get('gnss_intend_no_meas', 40))

        runtime_config_file = self.create_runtime_config(
            config_file,
            self.config['outages'],
            selected_algo,
            gnss_intend_no_meas=self.config.get('gnss_intend_no_meas')
        )

        # -------- ADD THIS BLOCK HERE --------
        if selected_algo == "LCA":
            exe_name = "./lca_sim"
        else:
            exe_name = "tca_app"

        exe_path = os.path.join(self.app_dir, exe_name)

        print("Executable path:", exe_path)
        print("Runtime config file:", runtime_config_file)
        print("App dir:", self.app_dir)
        print("Current working dir:", os.getcwd())

        # Check if executable exists
        if not os.path.isfile(exe_path):
            messagebox.showerror(
                "Executable Not Found",
                f"Cannot find executable:\n{exe_path}"
            )
            self._set_status("Executable not found.", "error")
            return

        # Check execute permission
        if not os.access(exe_path, os.X_OK):
            messagebox.showerror(
                "Permission Error",
                f"File exists but is not executable:\n{exe_path}\n\n"
                f"Run this in terminal:\nchmod +x '{exe_path}'"
            )
            self._set_status("Executable is not executable.", "error")
            return
        # -------- END OF BLOCK --------

        self._set_status(f"Running {selected_algo} simulation…", "busy")

        try:
            result = subprocess.run(
                [exe_path, runtime_config_file],
                capture_output=True,
                text=True,
                timeout=3600,
                cwd=self.app_dir
            )

            if result.stdout:
                print("STDOUT (first 500 chars):", result.stdout[:500])
            if result.stderr:
                print("STDERR:", result.stderr)

            if result.returncode != 0:
                messagebox.showerror(
                    "Simulation Error",
                    f"Executable failed with code {result.returncode}:\n{result.stderr}"
                )
                self._set_status("Simulation failed.", "error")
                return

            self._set_status("Simulation complete. Parsing output…", "busy")

        except subprocess.TimeoutExpired:
            messagebox.showerror("Timeout",
                                "Simulation exceeded 60-minute limit.")
            self._set_status("Simulation timed out.", "error")
            return

        except FileNotFoundError as e:
            messagebox.showerror(
                "Error",
                f"Could not launch executable.\n\n"
                f"Executable path:\n{exe_path}\n\n"
                f"Details:\n{e}"
            )
            self._set_status("Executable launch failed.", "error")
            return

        except Exception as exc:
            messagebox.showerror("Error",
                                f"Failed to launch executable:\n{exc}")
            self._set_status("Error launching executable.", "error")
            return

        errors_df, traj_df, gnss_ref_df, prn_df, outage_info, outage_points = self.parse_simulation_output(
            result.stdout
        )

        if errors_df is None or errors_df.empty:
            messagebox.showerror("Parse Error",
                                "Could not parse simulation output or no data available.")
            self._set_status("Output parse error.", "error")
            return

        self.errors_df = errors_df
        self.traj_df = traj_df
        self.gnss_ref_df = gnss_ref_df
        self.prn_df = prn_df
        self.outage_info = outage_info
        self.outage_points = outage_points

        if outage_info:
            print("\n=== AUTOMATICALLY CALCULATED OUTAGES ===")
            for i, (start, end) in enumerate(outage_info):
                print(f"Outage {i+1}: {start:.2f} - {end:.2f} seconds (Duration: {end-start:.2f} s)")
        else:
            print("\nNo outages were automatically calculated by the simulation")

        self._set_status("Rendering plots…", "busy")
        self.show_plots()
        self._set_status("Done — plots displayed.", "ok")
    
    # ─── Parse helpers ────────────────────────────────────────────────────────
    def parse_simulation_output(self, output):
        """Parse the delimited output from the simulation executable"""
        in_errors = in_traj = in_gnss = in_prn = in_outage_info = in_outage_points = False
        errors_lines, traj_lines, gnss_lines, prn_lines = [], [], [], []
        outage_info = []
        outage_points = []
        
        for line in output.splitlines():
            line = line.strip()
            if line == "BEGIN_ERRORS":
                in_errors = True
                continue
            elif line == "END_ERRORS":
                in_errors = False
                continue
            elif line == "BEGIN_TRAJ":
                in_traj = True
                continue
            elif line == "END_TRAJ":
                in_traj = False
                continue
            elif line == "BEGIN_GNSS_REF":
                in_gnss = True
                continue
            elif line == "END_GNSS_REF":
                in_gnss = False
                continue
            elif line == "BEGIN_OUTAGE_INFO":
                in_outage_info = True
                continue
            elif line == "END_OUTAGE_INFO":
                in_outage_info = False
                continue
            elif line == "BEGIN_OUTAGE_POINTS":
                in_outage_points = True
                continue
            elif line == "END_OUTAGE_POINTS":
                in_outage_points = False
                continue
            elif line == "BEGIN_PRN_AVAIL":
                in_prn = True
                continue
            elif line == "END_PRN_AVAIL":
                in_prn = False
                continue

            if in_errors and line:
                errors_lines.append(line)
            if in_traj and line:
                traj_lines.append(line)
            if in_gnss and line:
                gnss_lines.append(line)
            if in_prn and line:
                prn_lines.append(line)
            if in_outage_info and line and not line.startswith('outage_count'):
                parts = line.split(',')
                if len(parts) >= 3:
                    try:
                        outage_info.append((float(parts[1]), float(parts[2])))
                    except:
                        pass
            if in_outage_points and line and not line.startswith('time'):
                parts = line.split(',')
                if len(parts) >= 3:
                    try:
                        outage_points.append((float(parts[0]), float(parts[1]), float(parts[2])))
                    except:
                        pass

        try:
            errors_df = pd.read_csv(io.StringIO("\n".join(errors_lines))) if errors_lines else None
            traj_df = pd.read_csv(io.StringIO("\n".join(traj_lines))) if traj_lines else None
            gnss_ref_df = pd.read_csv(io.StringIO("\n".join(gnss_lines))) if gnss_lines else None
            prn_df = pd.read_csv(io.StringIO("\n".join(prn_lines))) if prn_lines else None

            # Normalize column names
            for df in (errors_df, traj_df, gnss_ref_df, prn_df):
                if df is not None:
                    df.columns = df.columns.str.strip()

            # Unify alternate time column names for trajectory and reference data
            if traj_df is not None:
                traj_df.rename(columns={
                    'GPStime': 'time',
                    'gps_time': 'time',
                    't': 'time'
                }, inplace=True)

            if gnss_ref_df is not None:
                gnss_ref_df.rename(columns={
                    'GPStime': 'time',
                    'gps_time': 'time',
                    't': 'time'
                }, inplace=True)
            if traj_df is not None:
                required_traj_cols = {'time', 'lat_deg', 'lon_deg'}
                missing = required_traj_cols - set(traj_df.columns)
                if missing:
                    raise ValueError(
                        f"Trajectory output missing columns: {sorted(missing)}. "
                        f"Found: {traj_df.columns.tolist()}"
                    )

            if gnss_ref_df is not None:
                required_ref_cols = {'lat_deg', 'lon_deg'}
                missing = required_ref_cols - set(gnss_ref_df.columns)
                if missing:
                    raise ValueError(
                        f"GNSS reference output missing columns: {sorted(missing)}. "
                        f"Found: {gnss_ref_df.columns.tolist()}"
                    )


            # Print data shapes for debugging
            if errors_df is not None:
                print(f"Errors data shape: {errors_df.shape}")
            if traj_df is not None:
                print(f"Trajectory data shape: {traj_df.shape}")
            if gnss_ref_df is not None:
                print(f"GNSS ref data shape: {gnss_ref_df.shape}")
            print(f"Outage intervals: {len(outage_info)}")
            print(f"Outage points: {len(outage_points)}")
            if prn_df is not None:
                print(f"PRN data shape: {prn_df.shape}")
            else:
                print("PRN data: not provided (expected for LCA)")

            return errors_df, traj_df, gnss_ref_df, prn_df, outage_info, outage_points
        except Exception as e:
            print(f"Error parsing CSV data: {e}")
            return None, None, None, None, None, None

    def parse_config(self, filename):
        """Parse config file with support for LCA/TCA fields and optional outage sat_count."""
        with open(filename, 'r') as f:
            lines = f.readlines()

        config = {
            'outages': [],
            'imu_file': '',
            'rawgnss_file': '',
            'gnss_file': '',
            'dataset_name': '',
            'old_time': 'auto',
            'end_time': 'auto',
            'est_clock_bias_m': 0.0,
            'est_clock_drift_mps': 0.0,
            'gnss_intend_no_meas': 40,
            # GNSS CSV column layout (0-based); overridden by config values
            'gnss_col_time': 1,
            'gnss_col_lat':  2,
            'gnss_col_lon':  3,
            'gnss_col_h':    4,
            'gnss_col_vn':   5,
            'gnss_col_ve':   6,
            'comment':       '',
        }

        comment_block = False
        comment_block_quote = None
        comment_block_lines = []

        for line in lines:
            stripped = line.strip()
            if comment_block:
                if stripped.endswith(comment_block_quote):
                    comment_block_lines.append(line.rstrip("\n")[:-len(comment_block_quote)])
                    if config['comment']:
                        config['comment'] += "\n"
                    config['comment'] += "\n".join(comment_block_lines)
                    comment_block = False
                    comment_block_quote = None
                    comment_block_lines = []
                else:
                    comment_block_lines.append(line.rstrip("\n"))
                continue

            if not stripped or stripped.startswith('#') or '=' not in stripped:
                continue

            key, value = stripped.split('=', 1)
            key, value = key.strip(), value.strip()

            if key == 'dataset_name':
                config['dataset_name'] = value

            elif key == 'imu_file':
                config['imu_file'] = value

            elif key in ('rawgnss', 'rawgnss_file'):
                config['rawgnss_file'] = value

            elif key in ('gnss', 'gnss_file', 'ref_file'):
                config['gnss_file'] = value

            elif key in ('gnss_col_time', 'gnss_col_lat', 'gnss_col_lon',
                         'gnss_col_h', 'gnss_col_vn', 'gnss_col_ve'):
                try:
                    config[key] = int(value)
                except ValueError:
                    print(f"Warning: invalid {key}: {value}")

            elif key == 'est_clock_bias_m':
                try:
                    config['est_clock_bias_m'] = float(value)
                except ValueError:
                    print(f"Warning: invalid est_clock_bias_m: {value}")

            elif key == 'est_clock_drift_mps':
                try:
                    config['est_clock_drift_mps'] = float(value)
                except ValueError:
                    print(f"Warning: invalid est_clock_drift_mps: {value}")

            elif key == 'old_time':
                if value.lower() == 'auto':
                    config['old_time'] = 'auto'
                else:
                    try:
                        config['old_time'] = float(value)
                    except ValueError:
                        print(f"Warning: invalid old_time: {value}")
                        config['old_time'] = 'auto'

            elif key == 'end_time':
                if value.lower() == 'auto':
                    config['end_time'] = 'auto'
                else:
                    try:
                        config['end_time'] = float(value)
                    except ValueError:
                        print(f"Warning: invalid end_time: {value}")
                        config['end_time'] = 'auto'

            elif key == 'gnss_intend_no_meas':
                try:
                    config['gnss_intend_no_meas'] = int(value)
                except ValueError:
                    print(f"Warning: invalid gnss_intend_no_meas: {value}")

            elif key == 'comment':
                if value.startswith('"""') or value.startswith("'''"):
                    quote = value[:3]
                    if value.endswith(quote) and len(value) >= 6:
                        comment_value = value[3:-3]
                        comment_value = comment_value.replace('\\n', '\n')
                        if config['comment']:
                            config['comment'] += "\n"
                        config['comment'] += comment_value
                    else:
                        comment_block = True
                        comment_block_quote = quote
                        comment_fragment = value[3:]
                        if comment_fragment:
                            comment_block_lines.append(comment_fragment)
                else:
                    if value.startswith('"') and value.endswith('"') and len(value) >= 2:
                        comment_value = value[1:-1]
                    elif value.startswith("'") and value.endswith("'") and len(value) >= 2:
                        comment_value = value[1:-1]
                    else:
                        comment_value = value
                    comment_value = comment_value.replace('\\n', '\n')
                    if config['comment']:
                        config['comment'] += "\n"
                    config['comment'] += comment_value

            elif key.startswith('outage_') and key != 'outage_intervals_count':
                parts = [p.strip() for p in value.split(',')]

                if len(parts) >= 2:
                    try:
                        start = float(parts[0])
                        end = float(parts[1])
                        sat_count = float(parts[2]) if len(parts) >= 3 and parts[2] != '' else 0.0
                        config['outages'].append((start, end, sat_count))
                    except ValueError:
                        print(f"Warning: Could not parse outage: {key}={value}")

        return config

    # ─── Statistics and plotting methods ─────────────────────────────────────
    def compute_statistics_with_outages(self, outages_to_use):
        """Compute statistics using the provided outage intervals"""
        if self.errors_df is None:
            return None, None, None

        non_outage_mask = pd.Series([True] * len(self.errors_df))
        for start, end in outages_to_use:
            non_outage_mask &= ~((self.errors_df['time'] >= start) &
                                 (self.errors_df['time'] <= end))

        non_outage = self.errors_df[non_outage_mask]
        if len(non_outage) == 0:
            return non_outage, (0,)*4, (0,)*4

        hrms     = np.sqrt(np.mean(non_outage['horz_error_m']**2))
        hmax     = non_outage['horz_error_m'].max()
        vrms     = np.sqrt(np.mean(non_outage['vert_error_m']**2))
        vmax_mag = np.abs(non_outage['vert_error_m']).max()

        eo_errors = []
        for start, end in outages_to_use:
            target   = start + 19.8
            mask     = (self.errors_df['time'] >= start) & (self.errors_df['time'] <= end)
            out_df   = self.errors_df[mask]
            if not out_df.empty:
                after = out_df[out_df['time'] >= target]
                row   = after.iloc[0] if not after.empty else out_df.iloc[-1]
                eo_errors.append([row['time'],
                                  row['horz_error_m'],
                                  row['vert_error_m']])

        if eo_errors:
            eo = pd.DataFrame(eo_errors,
                              columns=['time', 'horz_error_m', 'vert_error_m'])
            eohrms     = np.sqrt(np.mean(eo['horz_error_m']**2))
            eohmax     = eo['horz_error_m'].max()
            eovrms     = np.sqrt(np.mean(eo['vert_error_m']**2))
            eovmax_mag = np.abs(eo['vert_error_m']).max()
        else:
            eohrms = eohmax = eovrms = eovmax_mag = 0.0

        return (non_outage,
                (hrms, hmax, vrms, vmax_mag),
                (eohrms, eohmax, eovrms, eovmax_mag))

    # ─── Plots with Patches (improved styling) ─────────────────────────────────
    def show_plots(self):
        if self.errors_df is None:
            messagebox.showerror("Error", "No data loaded.")
            return

        # Render all plots inside a single tabbed Tk window.
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
        from matplotlib.gridspec import GridSpec

        # Use outage_info from C++ if available (these are the automatically calculated ones)
        # If not available, fall back to config
        outages_to_use = getattr(self, 'outage_info', [])
        if not outages_to_use:
            outages_to_use = self.config.get('outages', [])
            print(f"Using outages from config: {len(outages_to_use)} outages")
        else:
            print(f"Using outages from C++ simulation: {len(outages_to_use)} outages")
            # Print the outage intervals for debugging
            for i, (start, end) in enumerate(outages_to_use):
                print(f"  Outage {i+1}: {start:.2f} - {end:.2f} s")
        
        outage_points_to_use = getattr(self, 'outage_points', [])
        print(f"End-of-outage points received: {len(outage_points_to_use)}")

        # Compute statistics using the outages
        non_outage, \
            (hrms, hmax, vrms, vmax_mag), \
            (eohrms, eohmax, eovrms, eovmax_mag) = \
            self.compute_statistics_with_outages(outages_to_use)

        # Prepare end-of-outage points and outage details
        end_outage_points = []
        outage_details = []
        
        # First, use points from C++ output
        for point in outage_points_to_use:
            if len(point) >= 3:
                end_outage_points.append((point[0], point[1], point[2]))
                print(f"  Using C++ outage point: time={point[0]:.2f}, horz={point[1]:.2f}, vert={point[2]:.2f}")
        
        # If points from C++ don't match number of outages, compute missing ones
        if len(end_outage_points) < len(outages_to_use):
            print(f"Missing {len(outages_to_use) - len(end_outage_points)} outage points, computing from data...")
            for i, (start, end) in enumerate(outages_to_use):
                if i >= len(end_outage_points):
                    # Try to find the point near the end of outage
                    target = end - 0.1  # Look at the very end of the outage
                    # Find the closest time to the end of outage
                    time_diff = np.abs(self.errors_df['time'] - end)
                    closest_idx = time_diff.idxmin()
                    closest_time = self.errors_df.loc[closest_idx, 'time']
                    
                    if closest_time <= end + 0.5 and closest_time >= start:
                        # Valid point within the outage
                        end_outage_points.append((
                            closest_time,
                            self.errors_df.loc[closest_idx, 'horz_error_m'],
                            self.errors_df.loc[closest_idx, 'vert_error_m']
                        ))
                        print(f"  Computed outage point {i+1}: time={closest_time:.2f}, horz={end_outage_points[-1][1]:.2f}, vert={end_outage_points[-1][2]:.2f}")
                    else:
                        # No valid point found
                        end_outage_points.append((end, 0.0, 0.0))
                        print(f"  No valid point for outage {i+1}, using end time with zero error")
        
                # Create outage details for the table (duration and errors)
        for i, (start, end) in enumerate(outages_to_use):
            duration = end - start
            if i < len(end_outage_points):
                h_err = end_outage_points[i][1]
                v_err = end_outage_points[i][2]
                outage_details.append((duration, h_err, v_err))
            else:
                outage_details.append((duration, 0.0, 0.0))

        # Prepare outage rows for the table
        outage_rows = []
        for i, (start, end) in enumerate(outages_to_use):
            duration = end - start
            if i < len(outage_details):
                h_err = outage_details[i][1]
                v_err = outage_details[i][2]
                outage_rows.append([
                    f"{start:.1f} - {end:.1f} s",
                    f"{duration:.1f} s",
                    f"{h_err:.2f} m" if h_err != 0.0 else "N/A",
                    f"{v_err:.2f} m" if v_err != 0.0 else "N/A"
                ])
            else:
                outage_rows.append([
                    f"{start:.1f} - {end:.1f} s",
                    f"{duration:.1f} s",
                    "N/A",
                    "N/A"
                ])

        if not outage_rows:
            outage_rows = [["No outages defined", "", "", ""]]

        # Reuse/replace previous results window
        old_win = getattr(self, "results_win", None)
        if old_win is not None and old_win.winfo_exists():
            old_win.destroy()

        results_win = tk.Toplevel(self.root)
        results_win.title("Simulation Results")
        results_win.configure(bg=C_BG)
        results_win.geometry("1300x900")
        results_win.resizable(True, True)
        self.results_win = results_win

        notebook = ttk.Notebook(results_win)
        notebook.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        def _add_figure_tab(tab_title, fig):
            tab_frame = tk.Frame(notebook, bg=C_BG)
            notebook.add(tab_frame, text=tab_title)
            toolbar_frame = tk.Frame(tab_frame, bg=C_BG)
            toolbar_frame.pack(side=tk.TOP, fill=tk.X)
            canvas = FigureCanvasTkAgg(fig, master=tab_frame)
            canvas.draw()
            toolbar = NavigationToolbar2Tk(canvas, toolbar_frame)
            toolbar.update()
            canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        # ── Figure 1: Statistics only ─────────────────────────────────────
        fig_stats = plt.Figure(figsize=(14, 10), facecolor='white')
        gs_stats = GridSpec(
            3, 1,
            figure=fig_stats,
            height_ratios=[1.15, 1.15, 1.5],
            hspace=0.42
        )

        ax_tab1 = fig_stats.add_subplot(gs_stats[0, 0])
        ax_tab2 = fig_stats.add_subplot(gs_stats[1, 0])
        ax_tab3 = fig_stats.add_subplot(gs_stats[2, 0])

        for ax in (ax_tab1, ax_tab2, ax_tab3):
            ax.axis('off')


        def make_table(ax, rows, title, col_labels, col_widths=None,
                    font_size=11, header_height=0.10, row_height=0.085):
            if col_widths is None:
                col_widths = [0.62, 0.38]

            tbl = ax.table(
                cellText=rows,
                colLabels=col_labels,
                loc='center',
                cellLoc='left',
                colWidths=col_widths,
                bbox=[0.02, 0.02, 0.96, 0.78]
            )

            tbl.auto_set_font_size(False)
            tbl.set_fontsize(font_size)

            for (row, col), cell in tbl.get_celld().items():
                cell.set_edgecolor("black")
                cell.set_linewidth(0.8)

                if row == 0:
                    cell.set_facecolor(C_ACCENT)
                    cell.set_text_props(weight='bold', color='white',
                                        ha='center', va='center')
                    cell.set_height(header_height)
                else:
                    cell.set_facecolor(C_SURFACE if row % 2 == 0 else C_BADGE_BG)
                    if col == 0:
                        cell.set_text_props(color=C_TEXT, ha='left', va='center')
                    else:
                        cell.set_text_props(color=C_TEXT, ha='center', va='center')
                    cell.set_height(row_height)

            ax.set_title(title, fontsize=15, pad=10, fontweight='bold')


        make_table(
            ax_tab1,
            [["Horizontal RMS (m)",         f"{hrms:.2f}"],
            ["Horizontal Max (m)",         f"{hmax:.2f}"],
            ["Vertical RMS (m)",           f"{vrms:.2f}"],
            ["Vertical Max (m)", f"{vmax_mag:.2f}"]],
            "Non-outage periods",
            ["Metric", "Value"],
            [0.64, 0.36],
            font_size=11,
            header_height=0.10,
            row_height=0.085
        )

        make_table(
            ax_tab2,
            [["Horizontal RMS (m)",         f"{eohrms:.2f}"],
            ["Horizontal Max (m)",         f"{eohmax:.2f}"],
            ["Vertical RMS (m)",           f"{eovrms:.2f}"],
            ["Vertical Max (m)", f"{eovmax_mag:.2f}"]],
            "End-of-outage drift",
            ["Metric", "Value"],
            [0.64, 0.36],
            font_size=11,
            header_height=0.10,
            row_height=0.085
        )

        tbl3 = ax_tab3.table(
            cellText=outage_rows,
            colLabels=["Outage Interval", "Duration", "H Error", "V Error"],
            loc='center',
            cellLoc='left',
            colWidths=[0.34, 0.18, 0.24, 0.24],
            bbox=[0.02, 0.02, 0.96, 0.82]
        )
        tbl3.auto_set_font_size(False)
        tbl3.set_fontsize(10.5)

        for (row, col), cell in tbl3.get_celld().items():
            cell.set_edgecolor("black")
            cell.set_linewidth(0.8)

            if row == 0:
                cell.set_facecolor(C_ACCENT)
                cell.set_text_props(weight='bold', color='white',
                                    ha='center', va='center')
                cell.set_height(0.095)
            else:
                cell.set_facecolor(C_SURFACE if row % 2 == 0 else C_BADGE_BG)
                if col == 0:
                    cell.set_text_props(color=C_TEXT, ha='left', va='center')
                else:
                    cell.set_text_props(color=C_TEXT, ha='center', va='center')
                cell.set_height(0.078)

        ax_tab3.set_title("Individual Outage Details", fontsize=15, pad=10, fontweight='bold')

        fig_stats.subplots_adjust(left=0.05, right=0.95, top=0.90, bottom=0.04)
        # ── Figure 2: Error plots (+ PRN for TCA) ─────────────────────────
        has_prn = (
            self.sim_mode.get() == "TCA" and
            self.prn_df is not None and
            not self.prn_df.empty
        )

        if has_prn:
            fig_plots = plt.Figure(figsize=(14, 10), facecolor='white')
            gs_plots = fig_plots.add_gridspec(3, 1, height_ratios=[1, 1, 0.8])
            ax_horz = fig_plots.add_subplot(gs_plots[0, 0])
            ax_vert = fig_plots.add_subplot(gs_plots[1, 0], sharex=ax_horz)
            ax_prn = fig_plots.add_subplot(gs_plots[2, 0], sharex=ax_horz)
        else:
            fig_plots = plt.Figure(figsize=(14, 8), facecolor='white')
            gs_plots = fig_plots.add_gridspec(2, 1)
            ax_horz = fig_plots.add_subplot(gs_plots[0, 0])
            ax_vert = fig_plots.add_subplot(gs_plots[1, 0], sharex=ax_horz)
            ax_prn = None

        x_min = self.errors_df['time'].min()
        x_max = self.errors_df['time'].max()
        x_range = x_max - x_min
        x_padding = x_range * 0.02 if x_range > 0 else 1.0
        x_limits = (x_min - x_padding, x_max + x_padding)

        # Robust y-limits like original LCA GUI
        mask95 = (
            self.errors_df['horz_error_m'].abs().le(500) &
            self.errors_df['vert_error_m'].abs().le(500)
        )
        filtered = self.errors_df[mask95]

        if not filtered.empty:
            y_limits_h = tuple(np.percentile(filtered['horz_error_m'], [0.5, 99.5]))
            y_limits_v = tuple(np.percentile(filtered['vert_error_m'], [0.5, 99.5]))
        else:
            y_min_h = self.errors_df['horz_error_m'].min()
            y_max_h = self.errors_df['horz_error_m'].max()
            y_range_h = y_max_h - y_min_h if y_max_h != y_min_h else 1.0
            y_limits_h = (y_min_h - 0.05 * y_range_h, y_max_h + 0.05 * y_range_h)

            y_min_v = self.errors_df['vert_error_m'].min()
            y_max_v = self.errors_df['vert_error_m'].max()
            y_range_v = y_max_v - y_min_v if y_max_v != y_min_v else 1.0
            y_limits_v = (y_min_v - 0.05 * y_range_v, y_max_v + 0.05 * y_range_v)

        valid_end_points = [p for p in end_outage_points if p[1] != 0.0 or p[2] != 0.0]

        # Horizontal plot
        for start, end in outages_to_use:
            ax_horz.axvspan(start, end, facecolor='#ffcccc', edgecolor='red', alpha=0.35)

        ax_horz.scatter(
            self.errors_df['time'], self.errors_df['horz_error_m'],
            c='#1f77b4', marker='.', s=2, alpha=0.6, zorder=2
        )

        if valid_end_points:
            ax_horz.scatter(
                [p[0] for p in valid_end_points],
                [p[1] for p in valid_end_points],
                edgecolors='#d62728', facecolors='yellow',
                marker='o', s=50, zorder=3, linewidth=1.5
            )

        ax_horz.set_ylabel('Horizontal Error (m)', fontsize=10)
        ax_horz.set_title('Horizontal Error', fontsize=11, fontweight='bold')
        ax_horz.grid(True, linestyle='--', alpha=0.7)
        ax_horz.set_xlim(x_limits)
        ax_horz.set_ylim(y_limits_h)

        # Vertical plot
        for start, end in outages_to_use:
            ax_vert.axvspan(start, end, facecolor='#ffcccc', edgecolor='red', alpha=0.35)

        ax_vert.scatter(
            self.errors_df['time'], self.errors_df['vert_error_m'],
            c='#2ca02c', marker='.', s=2, alpha=0.6, zorder=2
        )

        if valid_end_points:
            ax_vert.scatter(
                [p[0] for p in valid_end_points],
                [p[2] for p in valid_end_points],
                edgecolors='#d62728', facecolors='yellow',
                marker='o', s=50, zorder=3, linewidth=1.5
            )

        ax_vert.set_ylabel('Vertical Error (m)', fontsize=10)
        ax_vert.set_title('Vertical Error', fontsize=11, fontweight='bold')
        ax_vert.grid(True, linestyle='--', alpha=0.7)
        ax_vert.set_xlim(x_limits)
        ax_vert.set_ylim(y_limits_v)

        # PRN plot for TCA only
        if has_prn and ax_prn is not None:
            prn_df = self.prn_df.copy()
            prn_df = prn_df[~((prn_df["gnss_time"] == 0) & (prn_df["sat_count"] == 0))]

            if not prn_df.empty:
                y_max_prn = prn_df["sat_count"].max()
                if y_max_prn <= 0:
                    y_max_prn = 1

                for start, end in outages_to_use:
                    ax_prn.add_patch(Rectangle(
                        (start, 0), end - start, y_max_prn + 1,
                        facecolor='#ffcccc', edgecolor='red',
                        alpha=0.35, linewidth=1, zorder=1
                    ))

                ax_prn.bar(
                    prn_df["gnss_time"], prn_df["sat_count"],
                    width=5.0, color='g', alpha=0.8, zorder=2
                )

                ax_prn.set_ylabel('Satellite count', fontsize=10)
                ax_prn.set_title('Number of available satellites', fontsize=11, fontweight='bold')
                ax_prn.grid(True, linestyle='--', alpha=0.7)
                ax_prn.set_ylim(0, y_max_prn + 1)
                ax_prn.set_xlim(x_limits)

        # Common x label only on bottom axis
        if ax_prn is not None:
            ax_prn.set_xlabel('GPS Time (s)', fontsize=10)
        else:
            ax_vert.set_xlabel('GPS Time (s)', fontsize=10)

        # Shared legend on top plot
        from matplotlib.patches import Patch
        legend_handles = [
            plt.Line2D([0], [0], marker='.', color='#1f77b4', linestyle='None',
                       markersize=6, label='Horizontal error'),
            plt.Line2D([0], [0], marker='.', color='#2ca02c', linestyle='None',
                       markersize=6, label='Vertical error')
        ]
        if outages_to_use:
            legend_handles.append(Patch(facecolor='#ffcccc', edgecolor='red',
                                        alpha=0.35, label='Outage'))
        if valid_end_points:
            legend_handles.append(plt.Line2D([0], [0], marker='o', color='#d62728',
                                             markerfacecolor='yellow', markersize=6,
                                             linestyle='None', label='End of outage'))
        if has_prn:
            legend_handles.append(Patch(facecolor='g', label='Satellite count'))

        ax_horz.legend(handles=legend_handles, frameon=True, fancybox=False,
                       loc='upper right', fontsize=8)

        fig_plots.tight_layout()

        # ── INS/GNSS trajectory:  statistics with outage filtering + Basemap ──────────────────────
        if self.traj_df is not None and self.gnss_ref_df is not None and not self.traj_df.empty and not self.gnss_ref_df.empty:
            fig_map = plt.Figure(figsize=(12, 8), facecolor='white')
            ax_map = fig_map.add_subplot(111, aspect='equal')
            
            # Get outage intervals
            outages_to_use_map = getattr(self, 'outage_info', [])
            if not outages_to_use_map:
                outages_to_use_map = self.config.get('outages', [])
            
            print(f"\n=== TRAJECTORY MAP DATA ===")
            print(f"GNSS Reference points total: {len(self.gnss_ref_df)}")
            print(f"Outage intervals: {len(outages_to_use_map)}")
            
            # Plot the full INS/GNSS estimated trajectory (shows during outages as well)
            ax_map.plot(self.traj_df['lon_deg'], self.traj_df['lat_deg'],
                       color='#1f77b4', linewidth=1.5, alpha=0.8, 
                       label='INS/GNSS Estimated', zorder=1)
            
            # Plot ALL GNSS reference points as small circles (not a line)
            ax_map.scatter(self.gnss_ref_df['lon_deg'],
                        self.gnss_ref_df['lat_deg'],
                        c="#0eff5a", s=8, marker='o', alpha=0.6,
                        label='GNSS Reference', zorder=2, 
                        edgecolors='white', linewidth=0.3)
            
            # Highlight outage periods on the trajectory with different color
            for start, end in outages_to_use_map:
                # Find trajectory points within this outage interval
                mask = (self.traj_df['time'] >= start) & (self.traj_df['time'] <= end)
                outage_traj = self.traj_df[mask]
                
                if not outage_traj.empty:
                    # Plot outage segments in red
                    ax_map.plot(outage_traj['lon_deg'], outage_traj['lat_deg'],
                               color='red', linewidth=2.5, alpha=0.9, zorder=3)
            
            # ── Start / End markers on the estimated trajectory ──────────────
            _traj_lons = self.traj_df['lon_deg'].values
            _traj_lats = self.traj_df['lat_deg'].values
            start_pt = ax_map.scatter(
                _traj_lons[0], _traj_lats[0],
                s=180, marker='^', color='#198754',
                zorder=6, edgecolors='white', linewidths=1.0,
                label='Start')
            end_pt = ax_map.scatter(
                _traj_lons[-1], _traj_lats[-1],
                s=180, marker='s', color='#dc3545',
                zorder=6, edgecolors='white', linewidths=1.0,
                label='End')

            # Get map bounds with padding
            all_lats = list(self.traj_df['lat_deg'].values)
            all_lats.extend(self.gnss_ref_df['lat_deg'].values)
            all_lons = list(self.traj_df['lon_deg'].values)
            all_lons.extend(self.gnss_ref_df['lon_deg'].values)
            
            min_lat = min(all_lats)
            max_lat = max(all_lats)
            min_lon = min(all_lons)
            max_lon = max(all_lons)
            
            dlat = (max_lat - min_lat) or 0.001
            dlon = (max_lon - min_lon) or 0.001
            lat_padding = dlat * 0.05
            lon_padding = dlon * 0.05
            
            bounds = (min_lon - lon_padding, min_lat - lat_padding,
                      max_lon + lon_padding, max_lat + lat_padding)
            
            ax_map.set_xlim(bounds[0], bounds[2])
            ax_map.set_ylim(bounds[1], bounds[3])
            
            # ----- ADD BASEMAP USING CONTEXTILY -----
            # The data is in WGS84 (EPSG:4326). contextily can add tiles in that CRS.
            try:
                ctx.add_basemap(ax_map, crs='EPSG:4326', source=ctx.providers.OpenStreetMap.Mapnik)
            except Exception as e:
                print(f"Could not add basemap to trajectory map: {e}")
            # -----------------------------------------
            
            ax_map.set_xlabel('Longitude (°)', fontsize=9)
            ax_map.set_ylabel('Latitude (°)', fontsize=9)
            ax_map.set_title('INS/GNSS trajectory', fontsize=11, fontweight='bold')
            ax_map.grid(True, linestyle='--', alpha=0.5)
            
            # Create legend
            from matplotlib.lines import Line2D
            legend_elements = [
                Line2D([0], [0], color='#1f77b4', linewidth=1.5, label='INS/GNSS Estimated'),
                Line2D([0], [0], color='red', linewidth=2.5, label='Outage Periods'),
                Line2D([0], [0], color="#4eb41f", linewidth=1.5, label='GNSS Reference'),
                Line2D([0], [0], marker='^', color='#198754', linestyle='None',
                       markersize=9, label='Start'),
                Line2D([0], [0], marker='s', color='#dc3545', linestyle='None',
                       markersize=9, label='End'),
            ]
            
            ax_map.legend(handles=legend_elements, frameon=True, fancybox=False, 
                         edgecolor=C_BORDER, loc='upper right', fontsize=8)
            
            # Add checkboxes for layer toggling
            ax_check = fig_map.add_axes([0.02, 0.02, 0.20, 0.15])
            chk = widgets.CheckButtons(
                ax_check,
                ['INS/GNSS Estimated', 'Outage Periods', 'GNSS Reference',
                 'Start / End Points'],
                [True, True, True, True])

            # Store references for toggle
            traj_line    = None
            outage_lines = []
            gnss_scatter = None

            for line in ax_map.lines:
                if line.get_color() == '#1f77b4':
                    traj_line = line
                elif line.get_color() == 'red' and line not in outage_lines:
                    outage_lines.append(line)
            for coll in ax_map.collections:
                if isinstance(coll, plt.matplotlib.collections.PathCollection):
                    if coll.get_label() == 'GNSS Reference':
                        gnss_scatter = coll

            def toggle_map(label):
                if label == 'INS/GNSS Estimated' and traj_line:
                    traj_line.set_visible(not traj_line.get_visible())
                elif label == 'Outage Periods':
                    for line in outage_lines:
                        line.set_visible(not line.get_visible())
                elif label == 'GNSS Reference' and gnss_scatter:
                    gnss_scatter.set_visible(not gnss_scatter.get_visible())
                elif label == 'Start / End Points':
                    start_pt.set_visible(not start_pt.get_visible())
                    end_pt.set_visible(not end_pt.get_visible())
                fig_map.canvas.draw_idle()
            
            chk.on_clicked(toggle_map)
            
            fig_map.subplots_adjust(left=0.1, right=0.95, top=0.95, bottom=0.05)
            _add_figure_tab("Trajectory map", fig_map)

        _add_figure_tab("Statistics", fig_stats)
        _add_figure_tab("Error and satellite count", fig_plots)

        notebook.select(0)
        results_win.lift()
        results_win.focus_force()

# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    root = tk.Tk()
    app  = INS_GUI(root)
    root.mainloop()