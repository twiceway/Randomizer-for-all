#!/usr/bin/env python3
"""GUI mixin: install mod wiring into user-selected Game folder."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import mod_install as mi
from gui_i18n import t


class InstallTabMixin:
    def _build_install_tab(self) -> None:
        pad = {"padx": 8, "pady": 4}
        parent = self.tab_install
        req_pad = {"padx": 8, "pady": (10, 2)}
        req_font = ("Microsoft YaHei UI", 12, "bold")

        req_frame = ttk.Frame(parent)
        req_frame.pack(fill="x")

        from mod_install import CNV_REQUIRED_LABEL, ER_REQUIRED_APP_LABEL

        self._install_req_er_lbl = tk.Label(
            req_frame,
            text=t("install_req_er", ver=ER_REQUIRED_APP_LABEL),
            font=req_font,
            anchor="w",
            justify="left",
        )
        self._install_req_er_lbl.pack(fill="x", **req_pad)
        self._install_req_cnv_lbl = tk.Label(
            req_frame,
            text=t("install_req_cnv", ver=CNV_REQUIRED_LABEL),
            font=req_font,
            anchor="w",
            justify="left",
        )
        self._install_req_cnv_lbl.pack(fill="x", padx=8, pady=(0, 6))

        self._install_intro_lbl = ttk.Label(
            parent,
            text=t("install_intro"),
            wraplength=1000,
            justify="left",
        )
        self._install_intro_lbl.pack(fill="x", **pad)

        path_row = ttk.Frame(parent)
        path_row.pack(fill="x", **pad)
        self._install_dir_lbl = ttk.Label(path_row, text=t("install_game_dir"))
        self._install_dir_lbl.pack(side="left")
        saved = mi.load_saved_game_dir()
        if not hasattr(self, "install_game_dir_var"):
            self.install_game_dir_var = tk.StringVar(value=str(saved) if saved else "")
        elif saved and not self.install_game_dir_var.get().strip():
            self.install_game_dir_var.set(str(saved))
        ttk.Entry(path_row, textvariable=self.install_game_dir_var, width=70).pack(
            side="left", padx=6, fill="x", expand=True
        )
        ttk.Button(path_row, text=t("browse"), command=self._install_browse_game).pack(
            side="left", padx=2
        )

        if not hasattr(self, "install_force_var"):
            self.install_force_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            parent,
            text=t("install_force"),
            variable=self.install_force_var,
        ).pack(anchor="w", **pad)

        btn_row = ttk.Frame(parent)
        btn_row.pack(fill="x", **pad)
        ttk.Button(btn_row, text=t("install_detect"), command=self._install_detect).pack(
            side="left", padx=2
        )
        ttk.Button(
            btn_row,
            text=t("install_run"),
            command=self._install_run,
        ).pack(side="left", padx=8)
        ttk.Button(
            btn_row,
            text=t("install_uninstall"),
            command=self._install_uninstall,
        ).pack(side="left", padx=2)
        ttk.Button(
            btn_row,
            text=t("install_open"),
            command=self._install_open_game,
        ).pack(side="left", padx=8)

        if not hasattr(self, "install_status_var"):
            self.install_status_var = tk.StringVar(value="")
        ttk.Label(
            parent,
            textvariable=self.install_status_var,
            wraplength=1000,
            justify="left",
            foreground="#333333",
        ).pack(fill="x", **pad)

        ttk.Label(parent, text=t("install_log_title")).pack(anchor="w", padx=8)
        self.install_log = tk.Text(parent, height=12, wrap="word", font=("Consolas", 9))
        self.install_log.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        self._install_refresh_status()

    def _install_append(self, text: str) -> None:
        self.install_log.insert("end", text.rstrip() + "\n")
        self.install_log.see("end")

    def _install_clear_log(self) -> None:
        self.install_log.delete("1.0", "end")

    def _install_game_path(self) -> Path | None:
        raw = self.install_game_dir_var.get().strip().strip('"')
        if not raw:
            return None
        return Path(raw)

    def _install_browse_game(self) -> None:
        initial = self._install_game_path()
        path = filedialog.askdirectory(
            title=t("install_pick_title"),
            initialdir=str(initial) if initial and initial.is_dir() else None,
        )
        if path:
            self.install_game_dir_var.set(path)
            p = Path(path)
            if p.is_dir() and (p / "eldenring.exe").is_file():
                mi.save_game_dir(p)
            self._install_detect()

    def _install_refresh_status(self) -> None:
        game = self._install_game_path()
        if game and mi.is_mod_installed(game):
            self.install_status_var.set(t("install_status_ok"))
        elif game:
            self.install_status_var.set(t("install_status_need"))
        else:
            saved = mi.load_saved_game_dir()
            if saved and mi.is_mod_installed(saved):
                self.install_status_var.set(t("install_status_ok_saved", path=saved))
                if not self.install_game_dir_var.get().strip():
                    self.install_game_dir_var.set(str(saved))
            else:
                self.install_status_var.set(t("install_status_none"))

    def _install_detect(self) -> None:
        self._install_clear_log()
        game = self._install_game_path()
        if not game or not game.is_dir():
            messagebox.showwarning(t("notice"), t("install_need_dir"))
            return
        report = mi.detect_all(game)
        self._install_append(t("install_log_dir", path=report.game_dir))
        self._install_append(t("install_log_er", detail=report.er.detail))
        self._install_append(t("install_log_cnv", detail=report.cnv.detail))
        if report.cnv.signals:
            self._install_append(
                t("install_log_signals", signals="；".join(report.cnv.signals))
            )
        if report.process_running:
            self._install_append(report.process_detail)
        else:
            self._install_append(t("install_log_proc_none"))
        self._install_append(t("install_log_preview"))
        for item in mi.build_preview(game):
            self._install_append(f"[{item.action}] {item.path}  {item.note}")
        installed = mi.is_mod_installed(game)
        self._install_append(
            t(
                "install_log_installed",
                yes=t("yes") if installed else t("no"),
            )
        )
        self._install_refresh_status()

    def _install_run(self) -> None:
        game = self._install_game_path()
        if not game or not game.is_dir():
            messagebox.showwarning(t("notice"), t("install_need_dir"))
            return
        report = mi.detect_all(game)
        force = bool(self.install_force_var.get())
        warnings: list[str] = []
        if not report.er.ok:
            warnings.append(report.er.detail)
        if not report.cnv.likely_ok:
            warnings.append(report.cnv.detail)
        if report.process_running:
            messagebox.showerror(t("install_blocked"), report.process_detail)
            return
        if warnings and not force:
            messagebox.showwarning(
                t("install_ver_warn"),
                "\n".join(warnings) + t("install_ver_force_hint"),
            )
            self._install_detect()
            return

        preview_lines = [
            f"[{i.action}] {i.path}" + (f" — {i.note}" if i.note else "")
            for i in mi.build_preview(game)
        ]
        msg = t("install_confirm_body", preview="\n".join(preview_lines))
        if warnings and force:
            msg = t("install_force_prefix", warnings="\n".join(warnings)) + msg
        if not messagebox.askokcancel(t("install_confirm_title"), msg):
            return

        result = mi.install_mod(game, force=force, dry_run=False)
        self._install_clear_log()
        for line in result.messages:
            self._install_append(line)
        self._install_refresh_status()
        if result.ok:
            self._install_append(t("install_launch_hint"))
            messagebox.showinfo(t("install_done_title"), t("install_done_body"))
        else:
            messagebox.showerror(t("install_fail_title"), "\n".join(result.messages))

    def _install_uninstall(self) -> None:
        game = self._install_game_path()
        if not game or not game.is_dir():
            messagebox.showwarning(t("notice"), t("install_need_dir"))
            return
        if not messagebox.askyesno(t("uninstall_title"), t("uninstall_body")):
            return
        result = mi.uninstall_mod(game, remove_dll=True)
        self._install_clear_log()
        for line in result.messages:
            self._install_append(line)
        self._install_refresh_status()
        if result.ok:
            messagebox.showinfo(t("uninstall_ok"), "\n".join(result.messages))
        else:
            messagebox.showerror(t("uninstall_fail"), "\n".join(result.messages))

    def _install_open_game(self) -> None:
        game = self._install_game_path()
        if not game or not game.is_dir():
            messagebox.showwarning(t("notice"), t("install_need_dir"))
            return
        import os

        os.startfile(str(game))  # noqa: S606

    def _require_mod_installed_for_generate(self) -> bool:
        """Hard gate: generate blocked until mod wiring is present."""
        game = self._install_game_path() if hasattr(self, "install_game_dir_var") else None
        if game and game.is_dir() and mi.is_mod_installed(game):
            # Persist so resolve_game_dir / deploy see the same Game path
            mi.save_game_dir(game)
            return True
        saved = mi.load_saved_game_dir()
        if saved is not None and mi.is_mod_installed(saved):
            if hasattr(self, "install_game_dir_var") and not self.install_game_dir_var.get().strip():
                self.install_game_dir_var.set(str(saved))
            return True
        if mi.is_mod_installed(None):
            return True
        messagebox.showerror(t("install_gate_title"), t("install_gate_body"))
        try:
            self.notebook.select(self.tab_install)
        except Exception:
            pass
        return False
