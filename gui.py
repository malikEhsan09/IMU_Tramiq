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
import contextily as ctx

# ─────────────────────────────────────────────────────────────────────────────
#  Color palette & font constants – Light theme
# ─────────────────────────────────────────────────────────────────────────────
C_BG        = "#f8f9fa"
C_SURFACE   = "#ffffff"
C_BORDER    = "#dee2e6"
C_ACCENT    = "#0d6efd"
C_ACCENT_H  = "#0b5ed7"
C_DANGER    = "#dc3545"
C_DANGER_H  = "#bb2d3b"
C_TEXT      = "#212529"
C_MUTED     = "#6c757d"
C_HIGHLIGHT = "#0d6efd"
C_BADGE_BG  = "#e9ecef"
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
        self.high_freq_traj_df = None
        self.outages         = []
        self.outage_info     = []
        self.outage_points   = []
        self.non_outage_rms_h = 0.0
        self.non_outage_rms_v = 0.0
        self.config_dir      = ""
        self.sim_mode        = tk.StringVar(value="LCA")

        self.app_dir = os.path.dirname(os.path.abspath(__file__))

        self._apply_style()
        self.create_widgets()
    
    def _resolve_config_relative_path(self, config_file, path_value):
        if not path_value:
            return ""
        if os.path.isabs(path_value):
            return path_value
        return os.path.normpath(os.path.join(os.path.dirname(config_file), path_value))

    def compute_display_time_bounds(self, config_file, config):
        old_time_value = config.get('old_time', 'auto')
        end_time_value = config.get('end_time', 'auto')
        if old_time_value != 'auto' and end_time_value != 'auto':
            return old_time_value, end_time_value

        imu_path = self._resolve_config_relative_path(config_file, config.get('imu_file', ''))
        gnss_ref_path = self._resolve_config_relative_path(config_file, config.get('gnss_file', ''))

        try:
            imu_df = pd.read_csv(imu_path, header=None)
            gnss_df = pd.read_csv(gnss_ref_path, header=None)
            if old_time_value == 'auto':
                if len(imu_df) > 99 and len(gnss_df) > 9 and imu_df.shape[1] > 0 and gnss_df.shape[1] > 1:
                    old_time_value = max(float(imu_df.iloc[99, 0]), float(gnss_df.iloc[9, 1]))
            if end_time_value == 'auto':
                if not imu_df.empty and not gnss_df.empty and imu_df.shape[1] > 0 and gnss_df.shape[1] > 1:
                    end_time_value = min(float(imu_df.iloc[-1, 0]), float(gnss_df.iloc[-1, 1]))
        except Exception as e:
            print(f"Warning: could not compute auto time bounds from files: {e}")

        return old_time_value, end_time_value
    
    def create_runtime_config(self, original_config_file, updated_outages, selected_algo, gnss_intend_no_meas=None):
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
        runtime_config_file = os.path.join(os.path.dirname(original_config_file), "_runtime_config.txt")
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
        body = tk.Frame(dialog, bg=C_BG)
        body.pack(fill=tk.BOTH, expand=True, padx=16, pady=16)
        tk.Label(body, text="Edit dataset comment:",
                 font=FONT_LABEL, bg=C_BG, fg=C_TEXT).pack(anchor=tk.W, pady=(0, 8))
        text_frame = tk.Frame(body, bg=C_SURFACE)
        text_frame.pack(fill=tk.BOTH, expand=True)
        txt = tk.Text(text_frame, font=FONT_LABEL, bg=C_SURFACE, fg=C_TEXT,
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
                messagebox.showerror("Save Error", f"Could not save comment:\n{exc}", parent=dialog)
        def on_cancel():
            dialog.destroy()
        btn_row = tk.Frame(body, bg=C_BG)
        btn_row.pack(fill=tk.X, pady=(12, 0))
        self._flat_btn(btn_row, "✔  Save", on_save, bg=C_ACCENT, hover=C_ACCENT_H).pack(side=tk.RIGHT)
        self._flat_btn(btn_row, "✕  Close", on_cancel, bg=C_DANGER, hover=C_DANGER_H).pack(side=tk.RIGHT, padx=(8, 0))
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

    def _apply_style(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(".", background=C_BG, foreground=C_TEXT, font=FONT_LABEL, borderwidth=0)
        style.configure("TFrame", background=C_BG)
        style.configure("Card.TFrame", background=C_SURFACE, relief="flat", borderwidth=1)
        style.configure("TLabel", background=C_BG, foreground=C_TEXT)
        style.configure("Muted.TLabel", foreground=C_MUTED, background=C_BG)
        style.configure("TRadiobutton", background=C_SURFACE, foreground=C_TEXT,
                        selectcolor=C_HIGHLIGHT, indicatorcolor=C_HIGHLIGHT, font=FONT_LABEL)
        style.map("TRadiobutton", background=[("active", C_SURFACE)], foreground=[("active", C_TEXT)])

    def create_widgets(self):
        header = tk.Frame(self.root, bg=C_BG, height=64)
        header.pack(fill=tk.X)
        header.pack_propagate(False)
        dot = tk.Canvas(header, width=10, height=10, bg=C_BG, highlightthickness=0)
        dot.pack(side=tk.LEFT, padx=(20, 6), pady=22)
        dot.create_oval(0, 0, 10, 10, fill=C_ACCENT, outline="")
        tk.Label(header, text="INS/GNSS  Loosely & Tightly Coupled Algorithms",
                 font=FONT_HEAD, bg=C_BG, fg=C_TEXT).pack(side=tk.LEFT)
        tk.Label(header, text="Visualization & Analysis Tool",
                 font=FONT_SMALL, bg=C_BG, fg=C_MUTED).pack(side=tk.LEFT, padx=(12, 0), pady=(8, 0))
        tk.Frame(self.root, height=2, bg=C_HIGHLIGHT).pack(fill=tk.X)
        outer = tk.Frame(self.root, bg=C_BG)
        outer.pack(fill=tk.BOTH, expand=True, padx=24, pady=16)

        self._section_label(outer, "SELECT ALGORITHM")
        algo_card = self._card(outer)
        self.radio_vars = {}
        self.algo_buttons = {}
        modes = [("LCA – Loosely Coupled Algorithm", "LCA"), ("TCA – Tightly Coupled Algorithm", "TCA")]
        for text, val in modes:
            var = tk.IntVar(value=1 if val == "LCA" else 0)
            self.radio_vars[val] = var
            btn = tk.Checkbutton(algo_card, text=text, variable=var, onvalue=1, offvalue=0,
                                 command=lambda v=val: self._exclusive_radio(v),
                                 bg=C_SURFACE, fg=C_TEXT, activebackground=C_SURFACE,
                                 activeforeground=C_ACCENT, selectcolor=C_HIGHLIGHT,
                                 font=FONT_LABEL, cursor="hand2", indicatoron=0,
                                 relief="raised", bd=1, padx=10, pady=5, highlightthickness=0)
            btn.pack(anchor=tk.W, padx=14, pady=4)
            self.algo_buttons[val] = btn
            if val == "LCA":
                var.set(1)
        self._update_algo_button_colors()

        self._section_label(outer, "DATASET")
        ds_card = self._card(outer)
        script_dir = os.path.dirname(os.path.abspath(__file__))
        import re
        _pat = re.compile(r"(LCA|TCA)_PreRec(\d+)_config\.txt$", re.IGNORECASE)
        _dataset_map = {}
        for p in sorted(glob.glob(os.path.join(script_dir, "LCA_PreRec*_config.txt")) +
                        glob.glob(os.path.join(script_dir, "TCA_PreRec*_config.txt"))):
            m = _pat.search(os.path.basename(p))
            if m:
                algo = m.group(1).upper()
                key = int(m.group(2))
                if key not in _dataset_map:
                    _dataset_map[key] = {'LCA': None, 'TCA': None}
                _dataset_map[key][algo] = p
        self.dataset_vars = []
        self.dataset_paths = []
        if _dataset_map:
            for prerec_num in sorted(_dataset_map):
                paths = _dataset_map[prerec_num]
                var = tk.IntVar()
                row_frame = tk.Frame(ds_card, bg=C_SURFACE)
                row_frame.pack(fill=tk.X, padx=14, pady=2)
                cb = tk.Checkbutton(row_frame, text=f"Prerecorded Dataset {prerec_num}", variable=var,
                                    command=lambda v=var: self._only_one_selected(v),
                                    bg=C_SURFACE, fg=C_TEXT, activebackground=C_SURFACE,
                                    activeforeground=C_ACCENT, selectcolor=C_BADGE_BG,
                                    font=FONT_LABEL, cursor="hand2", relief="flat", bd=0, highlightthickness=0)
                cb.pack(side=tk.LEFT)
                for algo in ("LCA", "TCA"):
                    if paths[algo]:
                        tk.Label(row_frame, text=algo, font=FONT_SMALL, bg=C_BADGE_BG, fg=C_MUTED,
                                 padx=5, pady=1, relief="flat").pack(side=tk.RIGHT, padx=2)
                self.dataset_vars.append(var)
                self.dataset_paths.append(paths)
            tk.Frame(ds_card, bg=C_SURFACE, height=6).pack()
        else:
            tk.Label(ds_card, text="⚠  No LCA/TCA_PreRec*_config.txt files found in script directory.",
                     bg=C_SURFACE, fg="#e3b341", font=FONT_LABEL).pack(padx=14, pady=10)

        self._section_label(outer, "ACTIONS")
        btn_card = self._card(outer)
        btn_row = tk.Frame(btn_card, bg=C_SURFACE)
        btn_row.pack(padx=14, pady=12)
        self._flat_btn(btn_row, "▶  Run Algorithm", self.run_simulation, bg=C_ACCENT, hover=C_ACCENT_H).pack(side=tk.LEFT, padx=(0, 10))
        self._flat_btn(btn_row, "✕  Exit", self.root.quit, bg=C_DANGER, hover=C_DANGER_H).pack(side=tk.LEFT)

        status_bar = tk.Frame(self.root, bg=C_BG, height=28)
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)
        status_bar.pack_propagate(False)
        self._status_dot = tk.Canvas(status_bar, width=8, height=8, bg=C_BG, highlightthickness=0)
        self._status_dot.pack(side=tk.LEFT, padx=(12, 4), pady=10)
        self._status_dot_id = self._status_dot.create_oval(0, 0, 8, 8, fill=C_MUTED, outline="")
        self.status = tk.Label(status_bar, text="Ready — select a dataset and algorithm to begin.",
                               font=FONT_SMALL, bg=C_BG, fg=C_MUTED, anchor=tk.W)
        self.status.pack(side=tk.LEFT, fill=tk.X)

    def _section_label(self, parent, text):
        row = tk.Frame(parent, bg=C_BG)
        row.pack(fill=tk.X, pady=(12, 4))
        tk.Label(row, text=text, font=("Segoe UI", 8, "bold"), bg=C_BG, fg=C_MUTED).pack(side=tk.LEFT)
        tk.Frame(row, height=1, bg=C_BORDER).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 0), pady=6)

    def _card(self, parent):
        outer = tk.Frame(parent, bg=C_BORDER, bd=0)
        outer.pack(fill=tk.X, pady=(0, 4))
        inner = tk.Frame(outer, bg=C_SURFACE, bd=0)
        inner.pack(fill=tk.X, padx=1, pady=1)
        return inner

    def _flat_btn(self, parent, text, cmd, bg, hover):
        text_color = 'white' if bg in (C_ACCENT, C_ACCENT_H, C_DANGER, C_DANGER_H, C_HIGHLIGHT) else C_TEXT
        btn = tk.Button(parent, text=text, command=cmd, font=FONT_BTN, bg=bg, fg=text_color,
                        activebackground=hover, activeforeground=text_color, relief="flat", bd=0,
                        cursor="hand2", padx=20, pady=8, highlightthickness=0)
        btn.bind("<Enter>", lambda e, b=btn, h=hover: b.config(bg=h))
        btn.bind("<Leave>", lambda e, b=btn, n=bg: b.config(bg=n))
        return btn

    def _set_status(self, msg, state="idle"):
        colour = {"idle": C_MUTED, "busy": "#fd7e14", "ok": C_STATUS_OK, "error": C_STATUS_ERR}.get(state, C_MUTED)
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

    def ask_outage_changes(self, config_file, default_outages,
                           old_time_value='auto', end_time_value='auto',
                           include_sat_count=False, gnss_intend_no_meas=40):
        dialog = tk.Toplevel(self.root)
        dialog.title("Outage Intervals")
        dialog.configure(bg=C_BG)
        dialog.resizable(False, False)
        hdr = tk.Frame(dialog, bg=C_BG)
        hdr.pack(fill=tk.X)
        tk.Label(hdr, text="Outage Intervals", font=FONT_HEAD, bg=C_BG, fg=C_TEXT,
                 padx=20, pady=14).pack(side=tk.LEFT)
        tk.Frame(dialog, height=2, bg=C_HIGHLIGHT).pack(fill=tk.X)
        body = tk.Frame(dialog, bg=C_BG, padx=20, pady=14)
        body.pack(fill=tk.BOTH, expand=True)
        tk.Label(body, text=f"Config file:  {os.path.basename(config_file)}",
                 font=FONT_MONO, bg=C_BG, fg=C_MUTED).pack(anchor=tk.W, pady=(0, 10))
        boundary_text = f"Allowed outage boundary  →  start: {old_time_value} s   |   stop: {end_time_value} s"
        tk.Label(body, text=boundary_text, font=FONT_MONO, bg=C_BG, fg=C_ACCENT, justify=tk.LEFT).pack(anchor=tk.W, pady=(0, 8))
        info_text = ("Edit start / end times (seconds) below.\n"
                     "Add or remove rows as needed, then click Apply & Continue.\n"
                     "NOTE: Maximum outage duration is 20 seconds. Changes are used only for this run.")
        if include_sat_count:
            info_text = ("Edit start / end times and max satellite count during outage below.\n"
                         "For TCA, max allowable GNSS sats in normal condition (without outage).\n"
                         "NOTE: Maximum outage duration is 20 seconds.")
        tk.Label(body, text=info_text, font=FONT_LABEL, bg=C_BG, fg=C_TEXT, justify=tk.LEFT).pack(anchor=tk.W, pady=(0, 12))
        gnss_intend_no_meas_var = tk.StringVar(value=str(gnss_intend_no_meas))
        if include_sat_count:
            param_row = tk.Frame(body, bg=C_BG)
            param_row.pack(fill=tk.X, pady=(0, 10))
            tk.Label(param_row, text="Max GNSS sats for TCA:", font=FONT_LABEL, bg=C_BG, fg=C_TEXT).pack(side=tk.LEFT)
            tk.Entry(param_row, textvariable=gnss_intend_no_meas_var, font=FONT_MONO, width=6,
                     bg=C_BADGE_BG, fg=C_TEXT, insertbackground=C_TEXT, relief="flat", bd=4,
                     highlightthickness=1, highlightcolor=C_HIGHLIGHT, highlightbackground=C_BORDER).pack(side=tk.LEFT, padx=(8, 0))
            tk.Label(param_row, text="(3–40)", font=FONT_SMALL, bg=C_BG, fg=C_MUTED).pack(side=tk.LEFT, padx=(8, 0))
        col_hdr = tk.Frame(body, bg=C_BG)
        col_hdr.pack(fill=tk.X)
        columns = [("#", 3), ("Start (s)", 12), ("End (s)", 12)]
        if include_sat_count:
            columns.append(("Max Sat Count", 12))
        for col_text, w in columns:
            tk.Label(col_hdr, text=col_text, font=("Segoe UI", 9, "bold"), bg=C_BG, fg=C_MUTED,
                     width=w, anchor=tk.W).pack(side=tk.LEFT, padx=4)
        list_outer = tk.Frame(body, bg=C_BORDER)
        list_outer.pack(fill=tk.X, pady=(4, 12))
        list_inner = tk.Frame(list_outer, bg=C_SURFACE)
        list_inner.pack(fill=tk.X, padx=1, pady=1)
        entry_rows = []
        def _make_entry(parent, textvariable, w=12):
            return tk.Entry(parent, textvariable=textvariable, font=FONT_MONO, width=w,
                            bg=C_BADGE_BG, fg=C_TEXT, insertbackground=C_TEXT, relief="flat", bd=4,
                            highlightthickness=1, highlightcolor=C_HIGHLIGHT, highlightbackground=C_BORDER)
        def add_row(start_val="", end_val="", sat_count_val="0"):
            idx = len(entry_rows) + 1
            rf = tk.Frame(list_inner, bg=C_SURFACE)
            rf.pack(fill=tk.X, pady=2, padx=6)
            tk.Label(rf, text=str(idx), width=3, font=FONT_MONO, bg=C_SURFACE, fg=C_MUTED, anchor=tk.W).pack(side=tk.LEFT, padx=4)
            sv = tk.StringVar(value=str(start_val))
            ev = tk.StringVar(value=str(end_val))
            scv = tk.StringVar(value=str(sat_count_val))
            _make_entry(rf, sv).pack(side=tk.LEFT, padx=4)
            _make_entry(rf, ev).pack(side=tk.LEFT, padx=4)
            if include_sat_count:
                sc_combo = ttk.Combobox(rf, textvariable=scv, values=["0", "3"], state="readonly", width=10)
                sc_combo.pack(side=tk.LEFT, padx=4)
            def _remove_row(rt):
                rt[3].destroy()
                entry_rows.remove(rt)
                _renumber()
            row_tuple = (sv, ev, scv, rf)
            del_btn = tk.Button(rf, text="✕", command=lambda rt=row_tuple: _remove_row(rt), font=FONT_SMALL,
                                bg=C_SURFACE, fg=C_MUTED, activebackground=C_DANGER, activeforeground=C_TEXT,
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
                add_row(outage[0], outage[1], str(int(outage[2])))
            else:
                add_row(outage[0], outage[1], "0")
        ctrl = tk.Frame(body, bg=C_BG)
        ctrl.pack(fill=tk.X, pady=(0, 8))
        self._flat_btn(ctrl, "+  Add Row", lambda: add_row(), bg=C_BADGE_BG, hover=C_BORDER).pack(side=tk.LEFT)
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
                    if include_sat_count:
                        sc = float(sc_str)
                        if sc not in [0, 3]:
                            messagebox.showerror("Invalid Input", f"Row {i+1}: max sat count must be 0 or 3.", parent=dialog)
                            return
                except ValueError:
                    messagebox.showerror("Invalid Input", f"Row {i+1}: start, end, and max sat count must be numbers.", parent=dialog)
                    return
                if start_limit is not None and s < start_limit:
                    messagebox.showerror("Invalid Input", f"Row {i+1}: outage start ({s}) is before simulation start ({start_limit}).", parent=dialog)
                    return
                if end_limit is not None and e > end_limit:
                    messagebox.showerror("Invalid Input", f"Row {i+1}: outage end ({e}) is after simulation stop ({end_limit}).", parent=dialog)
                    return
                if s >= e:
                    messagebox.showerror("Invalid Input", f"Row {i+1}: start ({s}) must be less than end ({e}).", parent=dialog)
                    return
                duration = e - s
                if duration > 20.0:
                    messagebox.showerror("Invalid Input", f"Row {i+1}: outage duration ({duration:.1f} s) exceeds maximum allowed (20.0 s).", parent=dialog)
                    return
                if include_sat_count:
                    new_outages.append((s, e, sc))
                else:
                    new_outages.append((s, e))
            if include_sat_count:
                gnss_val = gnss_intend_no_meas_var.get().strip()
                try:
                    gnss_intend = int(gnss_val)
                    if gnss_intend < 3 or gnss_intend > 40:
                        raise ValueError
                except ValueError:
                    messagebox.showerror("Invalid Input", "Max GNSS sats for TCA must be an integer between 3 and 40.", parent=dialog)
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
        self._flat_btn(btn_row, "✔  Continue", on_apply, bg=C_ACCENT, hover=C_ACCENT_H).pack(side=tk.RIGHT, padx=(8, 0))
        self._flat_btn(btn_row, "✕  Cancel", on_cancel, bg=C_BADGE_BG, hover=C_BORDER).pack(side=tk.RIGHT)
        dialog.update_idletasks()
        pw = self.root.winfo_x() + self.root.winfo_width() // 2
        ph = self.root.winfo_y() + self.root.winfo_height() // 2
        dw, dh = dialog.winfo_width(), dialog.winfo_height()
        dialog.geometry(f"+{pw - dw//2}+{ph - dh//2}")
        self.root.wait_window(dialog)
        return result

    def show_dataset_preview(self, config_file, config, on_set_outage=None, on_close=None):
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
        from matplotlib.figure import Figure
        from matplotlib.lines import Line2D
        win = tk.Toplevel(self.root)
        dataset_name = config.get('dataset_name', '') or os.path.basename(config_file)
        win.title(f"Reference Trajectory")
        win.configure(bg=C_BG)
        win.geometry("1200x700")
        win.resizable(True, True)
        hdr = tk.Frame(win, bg=C_BG)
        hdr.pack(fill=tk.X)
        tk.Label(hdr, text=f"{dataset_name}", font=FONT_HEAD, bg=C_BG, fg=C_TEXT, padx=20, pady=10).pack(side=tk.LEFT)
        tk.Frame(win, height=2, bg=C_HIGHLIGHT).pack(fill=tk.X)
        main_pane = tk.PanedWindow(win, bg=C_BG, sashrelief="raised", sashwidth=6)
        main_pane.pack(fill=tk.BOTH, expand=True, padx=16, pady=12)
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
        gnss_path = self._resolve_config_relative_path(config_file, config.get('gnss_file', ''))
        preview_ok = False
        def _clean_gnss_trajectory(lats_raw, lons_raw, times_raw, max_speed_kms=0.5, iqr_scale=1.5):
            import pandas as _pd, math
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
                lats_s, lons_s, lats_c, lons_c = _clean_gnss_trajectory(lats_raw, lons_raw, times_raw)
                ax.clear()
                ax.set_facecolor('#fafafa')
                ax.plot(lons_s, lats_s, color='#0d6efd', linewidth=2, alpha=0.9, zorder=2, label='Cleaned trajectory')
                ax.scatter(lons_s[0], lats_s[0], s=180, marker='^', color='#198754', zorder=5, edgecolors='white', linewidths=1.5, label='Start')
                ax.scatter(lons_s[-1], lats_s[-1], s=180, marker='s', color='#dc3545', zorder=5, edgecolors='white', linewidths=1.5, label='End')
                span_lat = (lats_s.max() - lats_s.min()) * 0.02 or 0.0005
                span_lon = (lons_s.max() - lons_s.min()) * 0.02 or 0.0005
                ax.annotate('START', xy=(lons_s[0], lats_s[0]), xytext=(lons_s[0] + span_lon, lats_s[0] + span_lat),
                            fontsize=8, color='#198754', fontweight='bold', arrowprops=dict(arrowstyle='->', color='#198754', lw=0.8))
                ax.annotate('END', xy=(lons_s[-1], lats_s[-1]), xytext=(lons_s[-1] + span_lon, lats_s[-1] - span_lat),
                            fontsize=8, color='#dc3545', fontweight='bold', arrowprops=dict(arrowstyle='->', color='#dc3545', lw=0.8))
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
                ax.legend(handles=legend_elements, fontsize=9, frameon=True, fancybox=False, edgecolor=C_BORDER, loc='best')
                try:
                    ctx.add_basemap(ax, crs='EPSG:4326', source=ctx.providers.OpenStreetMap.Mapnik)
                except Exception as e:
                    print(f"Could not add basemap: {e}")
                preview_ok = True
        except Exception as exc:
            print(f"Dataset preview: could not load GNSS file: {exc}")
        if not preview_ok:
            ax.clear()
            ax.text(0.5, 0.5, f"GNSS reference file unavailable\n({os.path.basename(gnss_path) if gnss_path else 'not configured'})",
                    ha='center', va='center', fontsize=10, color=C_MUTED, transform=ax.transAxes)
            ax.set_axis_off()
            ax.set_title('GNSS Reference Trajectory', fontsize=11, fontweight='bold')
        canvas = FigureCanvasTkAgg(fig, master=map_inner)
        canvas.draw()
        toolbar_frame = tk.Frame(map_inner, bg=C_BG)
        toolbar_frame.pack(side=tk.TOP, fill=tk.X)
        toolbar = NavigationToolbar2Tk(canvas, toolbar_frame)
        toolbar.update()
        canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        right_frame = tk.Frame(main_pane, bg=C_BG, width=350)
        main_pane.add(right_frame, width=350, minsize=250)
        hdr_row = tk.Frame(right_frame, bg=C_BG)
        hdr_row.pack(fill=tk.X, pady=(0, 8))
        tk.Label(hdr_row, text="DATASET-HISTORY", font=("Segoe UI", 9, "bold"), bg=C_BG, fg=C_MUTED).pack(side=tk.LEFT)
        txt_outer = tk.Frame(right_frame, bg=C_BORDER)
        txt_outer.pack(fill=tk.BOTH, expand=True)
        txt_inner = tk.Frame(txt_outer, bg=C_SURFACE)
        txt_inner.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)
        text_frame = tk.Frame(txt_inner, bg=C_SURFACE)
        text_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        vsb = tk.Scrollbar(text_frame)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        txt = tk.Text(text_frame, font=FONT_LABEL, bg=C_SURFACE, fg=C_TEXT, insertbackground=C_TEXT,
                      relief="flat", bd=0, wrap=tk.WORD, highlightthickness=1,
                      highlightcolor=C_HIGHLIGHT, highlightbackground=C_BORDER, cursor="arrow", state=tk.DISABLED)
        txt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.config(command=txt.yview)
        txt.configure(yscrollcommand=vsb.set)
        _initial_comment = config.get('comment', '').strip()
        txt.config(state=tk.NORMAL)
        if _initial_comment:
            txt.insert(tk.END, _initial_comment)
        txt.config(state=tk.DISABLED)
        btn_row = tk.Frame(right_frame, bg=C_BG)
        btn_row.pack(fill=tk.X, pady=(8, 0))
        edit_btn_ref = [None]
        save_btn_ref = [None]
        cancel_btn_ref = [None]
        def enter_edit_mode():
            txt.config(state=tk.NORMAL, cursor="xterm", bg="#fffff8", highlightbackground=C_HIGHLIGHT)
            txt.focus_set()
            edit_btn_ref[0].pack_forget()
            save_btn_ref[0].pack(side=tk.LEFT, padx=(0, 6))
            cancel_btn_ref[0].pack(side=tk.LEFT)
        def save_comment():
            new_comment = txt.get("1.0", tk.END).rstrip()
            try:
                self.save_config_comment(config_file, new_comment)
                config['comment'] = new_comment
                self.config = config
                self._set_status("Comment saved successfully.", "ok")
                leave_edit_mode(new_comment)
            except Exception as exc:
                messagebox.showerror("Save Error", f"Could not save comment:\n{exc}", parent=win)
                self._set_status("Failed to save comment.", "error")
        def cancel_edit():
            current_saved = config.get('comment', '').strip()
            txt.config(state=tk.NORMAL)
            txt.delete("1.0", tk.END)
            if current_saved:
                txt.insert(tk.END, current_saved)
            leave_edit_mode(current_saved)
        def leave_edit_mode(comment_text):
            txt.config(state=tk.DISABLED, cursor="arrow", bg=C_SURFACE, highlightbackground=C_BORDER)
            save_btn_ref[0].pack_forget()
            cancel_btn_ref[0].pack_forget()
            edit_btn_ref[0].pack(side=tk.LEFT)
        edit_btn = self._flat_btn(btn_row, "✏  Edit Comment", enter_edit_mode, bg=C_ACCENT, hover=C_ACCENT_H)
        save_btn = self._flat_btn(btn_row, "💾  Save", save_comment, bg=C_ACCENT, hover=C_ACCENT_H)
        cancel_btn = self._flat_btn(btn_row, "✕  Close", cancel_edit, bg=C_DANGER, hover=C_DANGER_H)
        set_outage_btn = None
        if on_set_outage is not None:
            set_outage_btn = self._flat_btn(btn_row, "⚙  Set Outage", on_set_outage, bg=C_HIGHLIGHT, hover=C_ACCENT_H)
        edit_btn_ref[0] = edit_btn
        save_btn_ref[0] = save_btn
        cancel_btn_ref[0] = cancel_btn
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

    def _run_executable(self, algo, config_file):
        exe_name = "./lca_sim" if algo == "LCA" else "tca_app"
        exe_path = os.path.join(self.app_dir, exe_name)
        if not os.path.isfile(exe_path):
            messagebox.showerror("Executable Not Found", f"Cannot find:\n{exe_path}")
            self._set_status("Executable not found.", "error")
            return None
        if not os.access(exe_path, os.X_OK):
            messagebox.showerror("Permission Error", f"File exists but is not executable:\n{exe_path}\n\nRun: chmod +x '{exe_path}'")
            self._set_status("Executable is not executable.", "error")
            return None
        try:
            result = subprocess.run([exe_path, config_file], capture_output=True, text=True, timeout=3600, cwd=self.app_dir)
            if result.returncode != 0:
                messagebox.showerror("Simulation Error", f"Executable failed with code {result.returncode}:\n{result.stderr}")
                self._set_status("Simulation failed.", "error")
                return None
            return result.stdout
        except subprocess.TimeoutExpired:
            messagebox.showerror("Timeout", "Simulation exceeded 60-minute limit.")
            self._set_status("Simulation timed out.", "error")
            return None
        except Exception as exc:
            messagebox.showerror("Error", f"Failed to launch executable:\n{exc}")
            self._set_status("Error launching executable.", "error")
            return None

    def run_simulation(self):
        selected_idx = None
        for i, var in enumerate(self.dataset_vars):
            if var.get() == 1:
                selected_idx = i
                break
        if selected_idx is None:
            messagebox.showerror("No Dataset Selected", "Please select a dataset before running.")
            return
        selected_algo = self.sim_mode.get()
        paths_dict = self.dataset_paths[selected_idx]
        config_file = paths_dict.get(selected_algo)
        if config_file is None:
            fallback = "TCA" if selected_algo == "LCA" else "LCA"
            config_file = paths_dict.get(fallback)
            if config_file:
                messagebox.showwarning("Config File Missing", f"No {selected_algo} config file found for this dataset.\nFalling back to the {fallback} config:\n{os.path.basename(config_file)}\n\nResults may be incorrect.")
            else:
                messagebox.showerror("Config File Missing", "No config file found for this dataset.")
                self._set_status("Config file missing.", "error")
                return
        try:
            self.config = self.parse_config(config_file)
            print(f"Loaded config: {self.config}")
        except Exception as e:
            print(f"Error parsing config: {e}")
            self.config = {'outages': [], 'imu_file': '', 'gnss_file': '', 'rawgnss_file': '', 'dataset_name': 'Unknown', 'old_time': 'auto', 'gnss_intend_no_meas': 40}
        display_old_time, display_end_time = self.compute_display_time_bounds(config_file, self.config)
        flow_state = tk.StringVar(value="pending")
        outage_result = {"value": None}
        preview_ref = {"win": None}
        def open_outage_editor():
            if selected_algo == "LCA":
                result = self.ask_outage_changes(config_file, self.config.get('outages', []),
                                                 old_time_value=display_old_time, end_time_value=display_end_time, include_sat_count=False)
            else:
                result = self.ask_outage_changes(config_file, self.config.get('outages', []),
                                                 old_time_value=display_old_time, end_time_value=display_end_time,
                                                 include_sat_count=True, gnss_intend_no_meas=self.config.get('gnss_intend_no_meas', 40))
            if result is not None and result.get('outages') is not None:
                outage_result["value"] = result
                flow_state.set("ready")
                preview_win = preview_ref.get("win")
                if preview_win is not None and preview_win.winfo_exists():
                    preview_win.destroy()
        def on_preview_close():
            if flow_state.get() == "pending":
                flow_state.set("cancelled")
        preview_win = self.show_dataset_preview(config_file, self.config, on_set_outage=open_outage_editor, on_close=on_preview_close)
        preview_ref["win"] = preview_win
        self.root.wait_variable(flow_state)
        result = outage_result["value"]
        if flow_state.get() != "ready" or result is None:
            self._set_status("Simulation cancelled.", "idle")
            return
        self.config['outages'] = result['outages']
        if selected_algo == "TCA":
            self.config['gnss_intend_no_meas'] = result.get('gnss_intend_no_meas', self.config.get('gnss_intend_no_meas', 40))

        # First run: no outages (baseline RMS)
        self._set_status("Running simulation without outages (baseline)…", "busy")
        baseline_config = self.config.copy()
        baseline_config['outages'] = []
        baseline_runtime = self.create_runtime_config(config_file, baseline_config['outages'], selected_algo,
                                                      gnss_intend_no_meas=baseline_config.get('gnss_intend_no_meas'))
        baseline_stdout = self._run_executable(selected_algo, baseline_runtime)
        if baseline_stdout is None:
            return
        baseline_errors_df, _, _, _, _, _ = self.parse_simulation_output(baseline_stdout)
        if baseline_errors_df is None or baseline_errors_df.empty:
            messagebox.showerror("Baseline Error", "Could not compute non‑outage statistics.")
            return
        self.non_outage_rms_h = np.sqrt((baseline_errors_df['horz_error_m'] ** 2).mean())
        self.non_outage_rms_v = np.sqrt((baseline_errors_df['vert_error_m'] ** 2).mean())
        print(f"Non‑outage RMS - Horizontal: {self.non_outage_rms_h:.2f} m, Vertical: {self.non_outage_rms_v:.2f} m")

        # Second run: with user‑defined outages
        self._set_status(f"Running {selected_algo} simulation with outages…", "busy")
        runtime_config_file = self.create_runtime_config(config_file, self.config['outages'], selected_algo,
                                                         gnss_intend_no_meas=self.config.get('gnss_intend_no_meas'))
        stdout = self._run_executable(selected_algo, runtime_config_file)
        if stdout is None:
            return
        errors_df, traj_df, gnss_ref_df, prn_df, outage_info, outage_points = self.parse_simulation_output(stdout)
        high_freq_df = self._extract_high_freq_traj(stdout)
        if errors_df is None or errors_df.empty:
            messagebox.showerror("Parse Error", "Could not parse simulation output or no data available.")
            self._set_status("Output parse error.", "error")
            return
        self.errors_df = errors_df
        self.traj_df = traj_df
        self.gnss_ref_df = gnss_ref_df
        self.prn_df = prn_df
        self.high_freq_traj_df = high_freq_df
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

    def _extract_high_freq_traj(self, output):
        in_high = False
        lines = []
        for line in output.splitlines():
            line = line.strip()
            if line == "BEGIN_TRAJ_HIGHFREQ":
                in_high = True
                continue
            elif line == "END_TRAJ_HIGHFREQ":
                in_high = False
                continue
            if in_high and line and not line.startswith('time'):
                lines.append(line)
        if lines:
            df = pd.read_csv(io.StringIO("\n".join(lines)))
            df.columns = df.columns.str.strip()
            required = {'time', 'lat_deg', 'lon_deg'}
            if required.issubset(df.columns):
                return df
            else:
                print("High‑frequency trajectory missing required columns.")
                return None
        return None

    def parse_simulation_output(self, output):
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
            for df in (errors_df, traj_df, gnss_ref_df, prn_df):
                if df is not None:
                    df.columns = df.columns.str.strip()
            if traj_df is not None:
                traj_df.rename(columns={'GPStime': 'time', 'gps_time': 'time', 't': 'time'}, inplace=True)
            if gnss_ref_df is not None:
                gnss_ref_df.rename(columns={'GPStime': 'time', 'gps_time': 'time', 't': 'time'}, inplace=True)
            if traj_df is not None:
                required_traj_cols = {'time', 'lat_deg', 'lon_deg'}
                missing = required_traj_cols - set(traj_df.columns)
                if missing:
                    raise ValueError(f"Trajectory output missing columns: {sorted(missing)}. Found: {traj_df.columns.tolist()}")
            if gnss_ref_df is not None:
                required_ref_cols = {'lat_deg', 'lon_deg'}
                missing = required_ref_cols - set(gnss_ref_df.columns)
                if missing:
                    raise ValueError(f"GNSS reference output missing columns: {sorted(missing)}. Found: {gnss_ref_df.columns.tolist()}")
            print(f"Errors data shape: {errors_df.shape if errors_df is not None else 'None'}")
            print(f"Trajectory data shape: {traj_df.shape if traj_df is not None else 'None'}")
            print(f"GNSS ref data shape: {gnss_ref_df.shape if gnss_ref_df is not None else 'None'}")
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
        with open(filename, 'r') as f:
            lines = f.readlines()
        config = {'outages': [], 'imu_file': '', 'rawgnss_file': '', 'gnss_file': '', 'dataset_name': '',
                  'old_time': 'auto', 'end_time': 'auto', 'est_clock_bias_m': 0.0, 'est_clock_drift_mps': 0.0,
                  'gnss_intend_no_meas': 40, 'gnss_col_time': 1, 'gnss_col_lat': 2, 'gnss_col_lon': 3,
                  'gnss_col_h': 4, 'gnss_col_vn': 5, 'gnss_col_ve': 6, 'comment': ''}
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
            elif key in ('gnss_col_time', 'gnss_col_lat', 'gnss_col_lon', 'gnss_col_h', 'gnss_col_vn', 'gnss_col_ve'):
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
                        comment_value = value[3:-3].replace('\\n', '\n')
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

    def compute_statistics_with_outages(self, outages_to_use):
        if self.errors_df is None:
            return None, None, None
        non_outage_mask = pd.Series([True] * len(self.errors_df))
        for start, end in outages_to_use:
            non_outage_mask &= ~((self.errors_df['time'] >= start) & (self.errors_df['time'] <= end))
        non_outage = self.errors_df[non_outage_mask]
        if len(non_outage) == 0:
            return non_outage, (0, 0, 0, 0, None), (0,)*5
        hrms = np.sqrt(np.mean(non_outage['horz_error_m']**2))
        hmax = non_outage['horz_error_m'].max()
        vrms = np.sqrt(np.mean(non_outage['vert_error_m']**2))
        vmax_mag = np.abs(non_outage['vert_error_m']).max()
        avg_sat_count = None
        if self.prn_df is not None:
            prn_df = self.prn_df
            if 'gnss_time' in prn_df.columns and 'sat_count' in prn_df.columns:
                prn_mask = pd.Series([True] * len(prn_df))
                for start, end in outages_to_use:
                    prn_mask &= ~((prn_df['gnss_time'] >= start) & (prn_df['gnss_time'] <= end))
                non_outage_prn = prn_df[prn_mask]
                if len(non_outage_prn) > 0:
                    avg_value = non_outage_prn['sat_count'].mean()
                    if np.isfinite(avg_value):
                        avg_sat_count = int(round(avg_value))
        eo_errors = []
        for start, end in outages_to_use:
            target = start + 19.8
            mask = (self.errors_df['time'] >= start) & (self.errors_df['time'] <= end)
            out_df = self.errors_df[mask]
            if not out_df.empty:
                after = out_df[out_df['time'] >= target]
                row = after.iloc[0] if not after.empty else out_df.iloc[-1]
                eo_errors.append([row['time'], row['horz_error_m'], row['vert_error_m']])
        if eo_errors:
            eo = pd.DataFrame(eo_errors, columns=['time', 'horz_error_m', 'vert_error_m'])
            eohrms = np.sqrt(np.mean(eo['horz_error_m']**2))
            eohmax = eo['horz_error_m'].max()
            eovrms = np.sqrt(np.mean(eo['vert_error_m']**2))
            eovmax_mag = np.abs(eo['vert_error_m']).max()
        else:
            eohrms = eohmax = eovrms = eovmax_mag = 0.0
        avg_sat_count_outage = None
        if self.prn_df is not None:
            prn_df = self.prn_df
            if 'gnss_time' in prn_df.columns and 'sat_count' in prn_df.columns:
                outage_prn_list = []
                for start, end in outages_to_use:
                    prn_mask = (prn_df['gnss_time'] >= start) & (prn_df['gnss_time'] <= end)
                    outage_prn = prn_df[prn_mask]
                    if len(outage_prn) > 0:
                        outage_prn_list.extend(outage_prn['sat_count'].values)
                if outage_prn_list:
                    avg_value = np.mean(outage_prn_list)
                    if np.isfinite(avg_value):
                        avg_sat_count_outage = int(round(avg_value))
        return non_outage, (hrms, hmax, vrms, vmax_mag, avg_sat_count), (eohrms, eohmax, eovrms, eovmax_mag, avg_sat_count_outage)

    # -------------------------------------------------------------------------
    # show_plots – FIXED: RMS annotation, no connecting lines, high‑freq for all
    # -------------------------------------------------------------------------
    def show_plots(self):
        if self.errors_df is None:
            messagebox.showerror("Error", "No data loaded.")
            return

        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
        from matplotlib.gridspec import GridSpec
        from matplotlib.patches import Patch, Rectangle
        from matplotlib.lines import Line2D

        # ── Original outage handling (kept unchanged) ──
        outages_to_use = getattr(self, 'outage_info', [])
        if not outages_to_use:
            outages_to_use = self.config.get('outages', [])
            print(f"Using outages from config: {len(outages_to_use)} outages")
        else:
            print(f"Using outages from C++ simulation: {len(outages_to_use)} outages")
            for i, (start, end) in enumerate(outages_to_use):
                print(f"  Outage {i+1}: {start:.2f} - {end:.2f} s")

        outage_points_to_use = getattr(self, 'outage_points', [])
        print(f"End-of-outage points received: {len(outage_points_to_use)}")

        non_outage, (hrms, hmax, vrms, vmax_mag, avg_sat_count), (eohrms, eohmax, eovrms, eovmax_mag, avg_sat_count_outage) = \
            self.compute_statistics_with_outages(outages_to_use)

        # Prepare end-of-outage points (original logic kept)
        end_outage_points = []
        for point in outage_points_to_use:
            if len(point) >= 3:
                end_outage_points.append((point[0], point[1], point[2]))
                print(f"  Using C++ outage point: time={point[0]:.2f}, horz={point[1]:.2f}, vert={point[2]:.2f}")

        if len(end_outage_points) < len(outages_to_use):
            print(f"Missing {len(outages_to_use) - len(end_outage_points)} outage points, computing from data...")
            for i, (start, end) in enumerate(outages_to_use):
                if i >= len(end_outage_points):
                    time_diff = np.abs(self.errors_df['time'] - end)
                    closest_idx = time_diff.idxmin()
                    closest_time = self.errors_df.loc[closest_idx, 'time']
                    if closest_time <= end + 0.5 and closest_time >= start:
                        end_outage_points.append((closest_time,
                                                self.errors_df.loc[closest_idx, 'horz_error_m'],
                                                self.errors_df.loc[closest_idx, 'vert_error_m']))
                        print(f"  Computed outage point {i+1}: time={closest_time:.2f}, horz={end_outage_points[-1][1]:.2f}, vert={end_outage_points[-1][2]:.2f}")
                    else:
                        end_outage_points.append((end, 0.0, 0.0))
                        print(f"  No valid point for outage {i+1}, using end time with zero error")

        # Build outage_rows for statistics table (original logic)
        outage_rows = []
        for i, (start, end) in enumerate(outages_to_use):
            duration = end - start
            h_err = end_outage_points[i][1] if i < len(end_outage_points) else 0.0
            v_err = end_outage_points[i][2] if i < len(end_outage_points) else 0.0
            outage_rows.append([f"{start:.1f} - {end:.1f} s", f"{duration:.1f} s",
                                f"{h_err:.2f} m" if h_err != 0.0 else "N/A",
                                f"{v_err:.2f} m" if v_err != 0.0 else "N/A"])
        if not outage_rows:
            outage_rows = [["No outages defined", "", "", ""]]

        # Close old window if exists
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

        # ==================== FIGURE 1: STATISTICS ====================
        fig_stats = plt.Figure(figsize=(14, 10), facecolor='white')
        gs_stats = GridSpec(3, 1, figure=fig_stats, height_ratios=[1.15, 1.15, 1.5], hspace=0.42)
        ax_tab1 = fig_stats.add_subplot(gs_stats[0, 0])
        ax_tab2 = fig_stats.add_subplot(gs_stats[1, 0])
        ax_tab3 = fig_stats.add_subplot(gs_stats[2, 0])
        for ax in (ax_tab1, ax_tab2, ax_tab3):
            ax.axis('off')

        def make_table(ax, rows, title, col_labels, col_widths=None, font_size=11, header_height=0.10, row_height=0.085):
            if col_widths is None:
                col_widths = [0.62, 0.38]
            tbl = ax.table(cellText=rows, colLabels=col_labels, loc='center', cellLoc='left',
                        colWidths=col_widths, bbox=[0.02, 0.02, 0.96, 0.78])
            tbl.auto_set_font_size(False)
            tbl.set_fontsize(font_size)
            for (row, col), cell in tbl.get_celld().items():
                cell.set_edgecolor("black")
                cell.set_linewidth(0.8)
                if row == 0:
                    cell.set_facecolor(C_ACCENT)
                    cell.set_text_props(weight='bold', color='white', ha='center', va='center')
                    cell.set_height(header_height)
                else:
                    cell.set_facecolor(C_SURFACE if row % 2 == 0 else C_BADGE_BG)
                    if col == 0:
                        cell.set_text_props(color=C_TEXT, ha='left', va='center')
                    else:
                        cell.set_text_props(color=C_TEXT, ha='center', va='center')
                    cell.set_height(row_height)
            ax.set_title(title, fontsize=15, pad=10, fontweight='bold')

        make_table(ax_tab1,
                [["Horizontal RMS (m)", f"{self.non_outage_rms_h:.2f}"],
                    ["Horizontal Max (m)", f"{hmax:.2f}"],
                    ["Vertical RMS (m)", f"{self.non_outage_rms_v:.2f}"],
                    ["Vertical Max (m)", f"{vmax_mag:.2f}"],
                    ["Satellite count", f"{avg_sat_count or 0:d}"]],
                "Error - GNSS vs Fused Position (Non‑outage Periods)",
                ["Metric", "Value"], [0.64, 0.36])

        tbl2 = ax_tab2.table(cellText=outage_rows, colLabels=["Outage Interval", "Duration", "H Error", "V Error"],
                            loc='center', cellLoc='left', colWidths=[0.34, 0.18, 0.24, 0.24],
                            bbox=[0.02, 0.02, 0.96, 0.82])
        tbl2.auto_set_font_size(False)
        tbl2.set_fontsize(10.5)
        for (row, col), cell in tbl2.get_celld().items():
            cell.set_edgecolor("black")
            cell.set_linewidth(0.8)
            if row == 0:
                cell.set_facecolor(C_ACCENT)
                cell.set_text_props(weight='bold', color='white', ha='center', va='center')
                cell.set_height(0.095)
            else:
                cell.set_facecolor(C_SURFACE if row % 2 == 0 else C_BADGE_BG)
                if col == 0:
                    cell.set_text_props(color=C_TEXT, ha='left', va='center')
                else:
                    cell.set_text_props(color=C_TEXT, ha='center', va='center')
                cell.set_height(0.078)
        ax_tab2.set_title("Outages Error - GNSS vs INS position", fontsize=15, pad=10, fontweight='bold')

        make_table(ax_tab3,
                [["Horizontal RMS (m)", f"{eohrms:.2f}"],
                    ["Horizontal Max (m)", f"{eohmax:.2f}"],
                    ["Vertical RMS (m)", f"{eovrms:.2f}"],
                    ["Vertical Max (m)", f"{eovmax_mag:.2f}"],
                    ["Satellite count", f"{avg_sat_count_outage or 0:d}"]],
                "Outage Error Summary", ["Metric", "Value"], [0.64, 0.36])

        fig_stats.subplots_adjust(left=0.05, right=0.95, top=0.90, bottom=0.04)

        # ==================== FIGURE 2: ERROR PLOTS ====================
        has_prn = (self.sim_mode.get() == "TCA" and self.prn_df is not None and not self.prn_df.empty)
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

        # ----- Y limits: always use full data range with 5% padding (percentile removed) -----
        y_min_h = self.errors_df['horz_error_m'].min()
        y_max_h = self.errors_df['horz_error_m'].max()
        y_range_h = y_max_h - y_min_h if y_max_h != y_min_h else 1.0
        y_limits_h = (y_min_h - 0.05 * y_range_h, y_max_h + 0.05 * y_range_h)

        y_min_v = self.errors_df['vert_error_m'].min()
        y_max_v = self.errors_df['vert_error_m'].max()
        y_range_v = y_max_v - y_min_v if y_max_v != y_min_v else 1.0
        y_limits_v = (y_min_v - 0.05 * y_range_v, y_max_v + 0.05 * y_range_v)

        valid_end_points = [p for p in end_outage_points if p[1] != 0.0 or p[2] != 0.0]

        # Horizontal error plot
        for start, end in outages_to_use:
            ax_horz.axvspan(start, end, facecolor='#ffcccc', edgecolor='red', alpha=0.35)
        ax_horz.scatter(self.errors_df['time'], self.errors_df['horz_error_m'],
                        c='#1f77b4', marker='.', s=2, alpha=0.6, zorder=2)
        if valid_end_points:
            ax_horz.scatter([p[0] for p in valid_end_points], [p[1] for p in valid_end_points],
                            edgecolors='#d62728', facecolors='yellow', marker='o', s=50, zorder=3, linewidth=1.5)
            # --- Annotate horizontal errors ---
            for time, h_err, v_err in valid_end_points:
                ax_horz.annotate(f'{h_err:.1f} m', xy=(time, h_err),
                                xytext=(5, 5), textcoords='offset points',
                                fontsize=7, color='#d62728',
                                bbox=dict(boxstyle='round,pad=0.2', facecolor='white', alpha=0.7))

        # RMS line - changed to blue to match horizontal error points
        ax_horz.axhline(y=self.non_outage_rms_h, color='#1f77b4', linestyle='--', linewidth=1.5)
        x_pos = x_limits[1] - (x_limits[1] - x_limits[0]) * 0.02
        ax_horz.text(x_pos, self.non_outage_rms_h, f'RMS = {self.non_outage_rms_h:.2f} m',
                    color='#1f77b4', fontsize=9, va='bottom', ha='right', backgroundcolor='white')

        ax_horz.set_ylabel('Horizontal Error (m)', fontsize=10)
        ax_horz.set_title('Horizontal Error', fontsize=11, fontweight='bold')
        ax_horz.grid(True, linestyle='--', alpha=0.7)
        ax_horz.set_xlim(x_limits)
        ax_horz.set_ylim(y_limits_h)

        # Vertical error plot
        for start, end in outages_to_use:
            ax_vert.axvspan(start, end, facecolor='#ffcccc', edgecolor='red', alpha=0.35)
        ax_vert.scatter(self.errors_df['time'], self.errors_df['vert_error_m'],
                        c='#2ca02c', marker='.', s=2, alpha=0.6, zorder=2)
        if valid_end_points:
            ax_vert.scatter([p[0] for p in valid_end_points], [p[2] for p in valid_end_points],
                            edgecolors='#d62728', facecolors='yellow', marker='o', s=50, zorder=3, linewidth=1.5)
            # --- Annotate vertical errors ---
            for time, h_err, v_err in valid_end_points:
                ax_vert.annotate(f'{v_err:.1f} m', xy=(time, v_err),
                                xytext=(5, 5), textcoords='offset points',
                                fontsize=7, color='#d62728',
                                bbox=dict(boxstyle='round,pad=0.2', facecolor='white', alpha=0.7))

        # RMS line - changed to green to match vertical error points
        ax_vert.axhline(y=self.non_outage_rms_v, color='#2ca02c', linestyle='--', linewidth=1.5)
        ax_vert.text(x_pos, self.non_outage_rms_v, f'RMS = {self.non_outage_rms_v:.2f} m',
                    color='#2ca02c', fontsize=9, va='bottom', ha='right', backgroundcolor='white')

        ax_vert.set_ylabel('Vertical Error (m)', fontsize=10)
        ax_vert.set_title('Vertical Error', fontsize=11, fontweight='bold')
        ax_vert.grid(True, linestyle='--', alpha=0.7)
        ax_vert.set_xlim(x_limits)
        ax_vert.set_ylim(y_limits_v)

        if has_prn and ax_prn is not None:
            prn_df = self.prn_df.copy()
            prn_df = prn_df[~((prn_df["gnss_time"] == 0) & (prn_df["sat_count"] == 0))]
            if not prn_df.empty:
                y_max_prn = prn_df["sat_count"].max() or 1
                for start, end in outages_to_use:
                    ax_prn.add_patch(Rectangle((start, 0), end - start, y_max_prn + 1,
                                            facecolor='#ffcccc', edgecolor='red', alpha=0.35, linewidth=1, zorder=1))
                ax_prn.bar(prn_df["gnss_time"], prn_df["sat_count"], width=5.0, color='g', alpha=0.8, zorder=2)
                ax_prn.set_ylabel('Satellite count', fontsize=10)
                ax_prn.set_title('Number of available satellites', fontsize=11, fontweight='bold')
                ax_prn.grid(True, linestyle='--', alpha=0.7)
                ax_prn.set_ylim(0, y_max_prn + 1)
                ax_prn.set_xlim(x_limits)

        if ax_prn is not None:
            ax_prn.set_xlabel('GPS Time (s)', fontsize=10)
        else:
            ax_vert.set_xlabel('GPS Time (s)', fontsize=10)

        # Legend (original + improved)
        legend_handles = [
            plt.Line2D([0], [0], marker='.', color='#1f77b4', linestyle='None', markersize=6, label='Horizontal error'),
            plt.Line2D([0], [0], marker='.', color='#2ca02c', linestyle='None', markersize=6, label='Vertical error')
        ]
        if outages_to_use:
            legend_handles.append(Patch(facecolor='#ffcccc', edgecolor='red', alpha=0.35, label='Outage'))
        if valid_end_points:
            legend_handles.append(plt.Line2D([0], [0], marker='o', color='#d62728', markerfacecolor='yellow',
                                            markersize=6, linestyle='None', label='End of outage'))
        if has_prn:
            legend_handles.append(Patch(facecolor='g', label='Satellite count'))
        ax_horz.legend(handles=legend_handles, frameon=True, fancybox=False, loc='upper right', fontsize=8)

        fig_plots.tight_layout()

        # ==================== FIGURE 3: TRAJECTORY MAP ====================
        if self.gnss_ref_df is not None and not self.gnss_ref_df.empty:
            fig_map = plt.Figure(figsize=(12, 8), facecolor='white')
            ax_map = fig_map.add_subplot(111, aspect='equal')

            outages_to_use_map = getattr(self, 'outage_info', []) or self.config.get('outages', [])

            # High-frequency trajectory preferred
            if self.high_freq_traj_df is not None and not self.high_freq_traj_df.empty:
                hf = self.high_freq_traj_df
                traj_scatter = ax_map.scatter(hf['lon_deg'], hf['lat_deg'],
                                            c='#1f77b4', s=0.5, alpha=0.6,
                                            label='INS/GNSS Estimated (200 Hz)', zorder=1)

                outage_mask = pd.Series([False] * len(hf))
                for start, end in outages_to_use_map:
                    outage_mask |= ((hf['time'] >= start) & (hf['time'] <= end))
                outage_points_df = hf[outage_mask]
                if not outage_points_df.empty:
                    outage_scatter = ax_map.scatter(outage_points_df['lon_deg'], outage_points_df['lat_deg'],
                                                    c='red', s=0.8, alpha=0.8, label='Outage periods', zorder=2)
                    outage_artists = [outage_scatter]
                else:
                    outage_scatter = None
                    outage_artists = []
                # For start/end points later
                traj_lons = hf['lon_deg'].values
                traj_lats = hf['lat_deg'].values
            else:
                # Fallback
                traj_lons = self.traj_df['lon_deg'].values
                traj_lats = self.traj_df['lat_deg'].values
                traj_scatter = ax_map.scatter(traj_lons, traj_lats,
                                            c='#1f77b4', s=2, alpha=0.6,
                                            label='INS/GNSS Estimated', zorder=1)
                outage_artists = []
                for start, end in outages_to_use_map:
                    mask = (self.traj_df['time'] >= start) & (self.traj_df['time'] <= end)
                    outage_traj = self.traj_df[mask]
                    if not outage_traj.empty:
                        artist = ax_map.scatter(outage_traj['lon_deg'], outage_traj['lat_deg'],
                                                c='red', s=3, alpha=0.8, label='Outage periods', zorder=2)
                        outage_artists.append(artist)

            # GNSS reference
            gnss_scatter = ax_map.scatter(self.gnss_ref_df['lon_deg'], self.gnss_ref_df['lat_deg'],
                                        c="#0eff5a", s=8, marker='o', alpha=0.6,
                                        label='GNSS Reference', zorder=3,
                                        edgecolors='white', linewidth=0.3)

            # Start and End points
            start_pt = ax_map.scatter(traj_lons[0], traj_lats[0],
                                    s=180, marker='^', color='#198754',
                                    zorder=6, edgecolors='white', linewidths=1.0, label='Start')
            end_pt = ax_map.scatter(traj_lons[-1], traj_lats[-1],
                                    s=180, marker='s', color='#dc3545',
                                    zorder=6, edgecolors='white', linewidths=1.0, label='End')

            # Bounds and basemap (original)
            all_lats = list(traj_lats) + list(self.gnss_ref_df['lat_deg'].values)
            all_lons = list(traj_lons) + list(self.gnss_ref_df['lon_deg'].values)
            min_lat, max_lat = min(all_lats), max(all_lats)
            min_lon, max_lon = min(all_lons), max(all_lons)
            dlat = (max_lat - min_lat) or 0.001
            dlon = (max_lon - min_lon) or 0.001
            ax_map.set_xlim(min_lon - dlon*0.05, max_lon + dlon*0.05)
            ax_map.set_ylim(min_lat - dlat*0.05, max_lat + dlat*0.05)

            try:
                ctx.add_basemap(ax_map, crs='EPSG:4326', source=ctx.providers.OpenStreetMap.Mapnik)
            except Exception as e:
                print(f"Could not add basemap: {e}")

            ax_map.set_xlabel('Longitude (°)', fontsize=9)
            ax_map.set_ylabel('Latitude (°)', fontsize=9)
            ax_map.set_title('INS/GNSS trajectory', fontsize=11, fontweight='bold')
            ax_map.grid(True, linestyle='--', alpha=0.5)

            # Improved legend
            legend_elements = [
                Line2D([0], [0], marker='^', color='#198754', linestyle='None', markersize=10, label='Start'),
                Line2D([0], [0], marker='s', color='#dc3545', linestyle='None', markersize=10, label='End'),
                Line2D([0], [0], color="#0eff5a", lw=0, marker='o', markersize=6, label='GNSS Reference'),
                Line2D([0], [0], color='#1f77b4', lw=0, marker='o', markersize=4, label='INS/GNSS Estimated'),
                Line2D([0], [0], color='red', lw=0, marker='o', markersize=4, label='Outage Periods'),
            ]
            ax_map.legend(handles=legend_elements, frameon=True, fancybox=False,
                        edgecolor=C_BORDER, loc='upper right', fontsize=8)

            fig_map.subplots_adjust(left=0.05, right=0.95, top=0.95, bottom=0.05)

            # --- Toggle logic with improved appearance and order matching legend ---
            canvas_ref = [None]
            # Store artists for each layer (note: Start & End are combined)
            visibility_state = {
                'Start / End Points': [True, [start_pt, end_pt]],
                'GNSS Reference': [True, gnss_scatter],
                'INS/GNSS Estimated': [True, traj_scatter],
                'Outage Periods': [True, outage_artists],
            }

            # Add map tab
            tab_frame = tk.Frame(notebook, bg=C_BG)
            notebook.add(tab_frame, text="Trajectory map")

            # Toolbar first
            toolbar_frame = tk.Frame(tab_frame, bg=C_BG)
            toolbar_frame.pack(side=tk.TOP, fill=tk.X)
            map_canvas = FigureCanvasTkAgg(fig_map, master=tab_frame)
            canvas_ref[0] = map_canvas
            map_canvas.draw()
            toolbar = NavigationToolbar2Tk(map_canvas, toolbar_frame)
            toolbar.update()
            map_canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

            # ==================== IMPROVED TOGGLE BUTTONS ====================
            # Create a frame to hold the toggle controls
            control_frame = ttk.LabelFrame(tab_frame, text="Layer Visibility", padding=(10, 5))
            control_frame.pack(side=tk.TOP, fill=tk.X, padx=5, pady=5)

            # Define button styles for ON/OFF states
            style = ttk.Style()
            # Make sure colors are defined; if not, provide fallbacks
            accent_color = getattr(self, 'C_ACCENT', '#0078D4')
            accent_hover = getattr(self, 'C_ACCENT_HOVER', '#005a9e')
            surface_color = getattr(self, 'C_SURFACE', '#f0f0f0')
            text_color = getattr(self, 'C_TEXT', '#333333')
            badge_bg = getattr(self, 'C_BADGE_BG', '#e9ecef')
            
            style.configure("ToggleOn.TButton",
                            background=accent_color,
                            foreground="white",
                            font=("Segoe UI", 9, "bold"),
                            padding=6,
                            relief="raised")
            style.map("ToggleOn.TButton",
                    background=[("active", accent_hover)])

            style.configure("ToggleOff.TButton",
                            background=surface_color,
                            foreground=text_color,
                            font=("Segoe UI", 9),
                            padding=6,
                            relief="flat")
            style.map("ToggleOff.TButton",
                    background=[("active", badge_bg)])

            def make_toggle_button(parent, label, key, initial_visible=True):
                """Create a toggle button that changes appearance when clicked."""
                var = tk.BooleanVar(value=initial_visible)
                
                def toggle():
                    # Flip state
                    new_state = not var.get()
                    var.set(new_state)
                    # Update button appearance
                    if new_state:
                        btn.configure(style="ToggleOn.TButton", text=f"✓ {label}")
                    else:
                        btn.configure(style="ToggleOff.TButton", text=f"○ {label}")
                    # Toggle layer visibility
                    state = visibility_state[key]
                    state[0] = new_state
                    artists = state[1]
                    if isinstance(artists, list):
                        for a in artists:
                            if a is not None:
                                a.set_visible(new_state)
                    elif artists is not None:
                        artists.set_visible(new_state)
                    if canvas_ref[0] is not None:
                        canvas_ref[0].draw()
                
                # Initial button text with indicator
                initial_text = f"✓ {label}" if initial_visible else f"○ {label}"
                btn = ttk.Button(parent, text=initial_text, command=toggle,
                                style="ToggleOn.TButton" if initial_visible else "ToggleOff.TButton")
                btn.pack(side=tk.LEFT, padx=4, pady=2)
                return var

            # Create buttons in desired order (matches legend order)
            order = ['Start / End Points', 'GNSS Reference', 'INS/GNSS Estimated', 'Outage Periods']
            for key in order:
                make_toggle_button(control_frame, key, key, initial_visible=True)

            # Optional: add a small hint label
            hint_label = ttk.Label(control_frame, text="(click to toggle layer visibility)",
                                font=("Segoe UI", 8, "italic"), foreground="#6c757d")
            hint_label.pack(side=tk.LEFT, padx=(15, 5))

        # Add tabs (original order)
        _add_figure_tab("Statistics", fig_stats)
        _add_figure_tab("Error and satellite count", fig_plots)
        notebook.select(0)
        results_win.lift()
        results_win.focus_force()

# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    root = tk.Tk()
    app = INS_GUI(root)
    root.mainloop()