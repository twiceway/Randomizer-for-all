#!/usr/bin/env python3
"""CNV 3.0 randomizer GUI — items + enemies tabs (428-style), seed, generate, deploy."""

from __future__ import annotations

import random
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, scrolledtext, ttk

_boot_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(_boot_dir))
from paths import SCRIPT_DIR, ensure_output_dirs, resolve_output_dir  # noqa: E402

from cnv_randomizer_core import (
    CAT_ASH,
    CAT_GOODS,
    CAT_TALISMAN,
    NAME_TO_CAT,
    RegionPanelCache,
    deploy_runtime_map,
    load_config,
    save_config,
)
from goods_subcats import expand_goods_groups
from gui_maintainer import is_maintainer_gui
from gui_session_log import GuiSessionLog, LATEST_LOG

from gui_common import (
    CONFIG_PATH,
    ENEMY_DLC_POOL_MODE,
    SESSION_SAVE_MS,
    default_enemy_category_weights,
    diagonal_enemy_category_weights,
    get_ui_lang,
    load_enemy_category_weights,
    refresh_gui_label_maps,
    set_ui_lang,
    t,
)

from gui_enemy_tab import EnemyTabMixin
from gui_install_tab import InstallTabMixin
from gui_pickup_tab import PickupTabMixin

# Re-export for external importers
__all__ = [
    "main",
    "default_enemy_category_weights",
    "diagonal_enemy_category_weights",
    "load_enemy_category_weights",
    "RandomizerApp",
]

class RandomizerApp(InstallTabMixin, PickupTabMixin, EnemyTabMixin, tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.cfg = load_config(CONFIG_PATH)
        set_ui_lang(str(self.cfg.get("ui_lang", "zh")))
        refresh_gui_label_maps()
        self.title(t("app_title"))
        self.geometry("1200x880")
        self.minsize(1000, 700)

        self._maintainer_enabled = is_maintainer_gui(self.cfg)
        self._maintainer_widgets: list[tk.Widget] = []
        ensure_output_dirs()
        self.cat_vars: dict[str, tk.BooleanVar] = {}
        self.goods_group_vars: dict[str, tk.BooleanVar] = {}
        self.enemy_weight_vars: dict[str, dict[str, tk.StringVar]] = {}
        self.enemy_row_sum_labels: dict[str, ttk.Label] = {}
        self._panel_cache: RegionPanelCache | None = None
        self._region_tree_ids: list[str] = []
        self._region_total_id: str | None = None
        self._strictness_refresh_after: str | None = None
        self._strictness_save_after: str | None = None
        self._session_save_after: str | None = None
        self.last_runtime_map: Path | None = None
        self.last_enemy_map: Path | None = None
        self._last_items_summary: str | None = None
        self._last_enemy_summary: str | None = None
        self._session_log: GuiSessionLog | None = None
        self._build_ui()
        self._apply_maintainer_visibility()
        self._refresh_region_panel()
        self._refresh_tab_titles()
        self._start_background_warmup()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _start_background_warmup(self) -> None:
        try:
            from gui_warmup import start_background_warmup
            from paths import resolve_game_dir

            game_dir = resolve_game_dir()
        except Exception:
            game_dir = None

        def _warmup_log(msg: str) -> None:
            if self._session_log is not None:
                self._session_log.line(msg)
            elif self._maintainer_enabled:
                self._log(msg)

        start_background_warmup(
            game_dir=game_dir,
            cfg=self.cfg,
            log_fn=_warmup_log,
        )


    def _cancel_pending_timers(self) -> None:
        if self._strictness_refresh_after is not None:
            self.after_cancel(self._strictness_refresh_after)
            self._strictness_refresh_after = None
        if self._strictness_save_after is not None:
            self.after_cancel(self._strictness_save_after)
            self._strictness_save_after = None
        if self._session_save_after is not None:
            self.after_cancel(self._session_save_after)
            self._session_save_after = None


    def _refresh_tab_titles(self) -> None:
        # nbsp (\u00A0) is kept by ttk; normal/fullwidth spaces are often stripped,
        # which made overlay checkboxes cover the tab label (物品 disappeared).
        self.notebook.tab(self.tab_install, text=self._tab_label(t("tab_install"), chk=False))
        self.notebook.tab(self.tab_items, text=self._tab_label(t("tab_items"), chk=True))
        self.notebook.tab(self.tab_enemies, text=self._tab_label(t("tab_enemies"), chk=True))
        self.after_idle(self._position_tab_checkboxes)

    @staticmethod
    def _tab_label(name: str, *, chk: bool) -> str:
        """Widen tab title; leave left room when a checkbox will be overlaid."""
        nb = "\u00A0"
        em = "\u2003"  # wider than nbsp; ttk keeps both
        if chk:
            # larger checkbox glyph (~18px) + gap, then label
            return f"{em * 3}{nb}{name}{nb * 4}"
        return f"{nb * 2}{name}{nb * 2}"

    def _make_tab_enable_toggle(self, var: tk.BooleanVar) -> tk.Label:
        """Large ☐/☑ on tab header (ttk box can't grow; glyph scales with font)."""
        font = ("Segoe UI Symbol", 15)
        try:
            style = ttk.Style(self)
            bg = style.lookup("TNotebook", "background") or "SystemButtonFace"
        except tk.TclError:
            bg = "SystemButtonFace"

        lbl = tk.Label(
            self._nb_host,
            text="☑" if var.get() else "☐",
            font=font,
            bg=bg,
            fg="#222222",
            cursor="hand2",
            borderwidth=0,
            highlightthickness=0,
            padx=0,
            pady=0,
        )

        def _refresh(*_a: object) -> None:
            try:
                lbl.configure(text="☑" if var.get() else "☐")
            except tk.TclError:
                pass

        def _toggle(_event: object | None = None) -> None:
            var.set(not bool(var.get()))
            self._on_page_toggle()

        var.trace_add("write", _refresh)
        lbl.bind("<Button-1>", _toggle)
        return lbl

    def _notebook_tab_start_xs(self) -> dict[int, int]:
        """Map tab index → leftmost x of that tab header (via hit-test)."""
        nb = self.notebook
        # Hide overlays so they don't steal hit-tests on the tab strip
        for w in (getattr(self, "_chk_page_items", None), getattr(self, "_chk_page_enemies", None)):
            if w is not None:
                try:
                    w.place_forget()
                except tk.TclError:
                    pass
        try:
            nb.update_idletasks()
            width = max(int(nb.winfo_width()), 1)
            height = max(int(nb.winfo_height()), 1)
        except tk.TclError:
            return {}
        # Sample near top of tab strip (not content area)
        y = min(12, max(4, height // 20))
        starts: dict[int, int] = {}
        last: int | None = None
        step = 2
        for x in range(0, width, step):
            try:
                idx = int(nb.index(f"@{x},{y}"))
            except (tk.TclError, ValueError, TypeError):
                continue
            if idx != last:
                starts[idx] = x
                last = idx
        return starts

    def _position_tab_checkboxes(self, _event: object | None = None) -> None:
        """Overlay enable-checkboxes on Items / Enemies tab headers (428-style)."""
        if not hasattr(self, "notebook") or not hasattr(self, "_chk_page_items"):
            return
        if getattr(self, "_tab_chk_placing", False):
            return
        self._tab_chk_placing = True
        try:
            try:
                self.update_idletasks()
            except tk.TclError:
                return
            starts = self._notebook_tab_start_xs()
            if 1 not in starts or 2 not in starts:
                # Font fallback if hit-test failed
                from tkinter import font as tkfont

                try:
                    face = tkfont.nametofont("TkDefaultFont")
                except tk.TclError:
                    face = None

                def _tab_w(label: str) -> int:
                    chrome = 56
                    if face is not None:
                        return max(120, int(face.measure(label)) + chrome)
                    return max(120, len(label) * 14 + chrome)

                x0 = 6
                w0 = _tab_w(self._tab_label(t("tab_install"), chk=False))
                w1 = _tab_w(self._tab_label(t("tab_items"), chk=True))
                starts = {0: x0, 1: x0 + w0, 2: x0 + w0 + w1}

            # Place on host: notebook-relative coords + notebook origin
            try:
                ox = int(self.notebook.winfo_x())
                oy = int(self.notebook.winfo_y())
            except tk.TclError:
                ox, oy = 0, 0
            y = oy + 2
            # Sit near tab left edge; em gutter keeps gap before 汉字
            x_items = ox + int(starts.get(1, 140)) + 4
            x_enemies = ox + int(starts.get(2, 280)) + 4
            try:
                self._chk_page_items.place(in_=self._nb_host, x=x_items, y=y)
                self._chk_page_enemies.place(in_=self._nb_host, x=x_enemies, y=y)
                self._chk_page_items.lift()
                self._chk_page_enemies.lift()
            except tk.TclError:
                pass
        finally:
            self._tab_chk_placing = False

    def _on_ui_lang_change(self, *_args) -> None:
        lang = set_ui_lang(str(self.ui_lang_var.get()))
        self.cfg["ui_lang"] = lang
        refresh_gui_label_maps()
        self.title(t("app_title"))
        self._lbl_seed.configure(text=t("seed") + ":")
        self._btn_random_seed.configure(text=t("random_seed"))
        self._chk_auto_seed.configure(text=t("auto_new_seed"))
        self._lbl_lang.configure(text=t("lang_label") + ":")
        self._btn_save.configure(text=t("save_settings"))
        self.test_generate_btn.configure(text=t("test_generate"))
        self.generate_btn.configure(text=t("generate"))
        self._btn_open_output.configure(text=t("open_output"))
        self._generate_hint_maintainer = t("hint_maintainer")
        self._generate_hint_release = t("hint_release")
        self.generate_hint_label.configure(
            text=self._generate_hint_maintainer
            if self._maintainer_enabled
            else self._generate_hint_release
        )
        self.gen_progress_label.configure(text=t("ready"))

        self._maintainer_widgets.clear()
        for tab in (self.tab_install, self.tab_items, self.tab_enemies):
            for child in tab.winfo_children():
                child.destroy()
        self._build_install_tab()
        self._build_items_tab()
        self._build_enemies_tab()
        self._maintainer_widgets.append(self.test_generate_btn)
        self._apply_maintainer_visibility()
        self._refresh_tab_titles()
        self._update_generate_status()
        self._save_session(silent=True)


    def _on_page_toggle(self) -> None:
        self._refresh_tab_titles()
        self._update_generate_status()
        self._save_session(silent=True)


    def _build_ui(self) -> None:
        pad = {"padx": 8, "pady": 2}

        self.page_items_var = tk.BooleanVar(
            value=bool(self.cfg.get("enemy_gui", {}).get("page_items_enabled", True))
            if "enemy_gui" in self.cfg
            else True
        )
        self.page_enemies_var = tk.BooleanVar(
            value=bool(
                self.cfg.get("enemy_gui", {}).get("page_enemies_enabled", True)
            )
        )

        top = ttk.Frame(self)
        top.pack(fill="x", **pad)

        seed_row = ttk.Frame(top)
        seed_row.pack(fill="x")
        self._lbl_seed = ttk.Label(seed_row, text=t("seed") + ":")
        self._lbl_seed.pack(side="left")
        self.seed_var = tk.StringVar(value=str(self.cfg.get("seed", 42001)))
        self.seed_var.trace_add("write", lambda *_: self._schedule_session_save())
        ttk.Entry(seed_row, textvariable=self.seed_var, width=18).pack(side="left", padx=6)
        self._btn_random_seed = ttk.Button(
            seed_row, text=t("random_seed"), command=self._random_seed
        )
        self._btn_random_seed.pack(side="left", padx=4)
        enemy_cfg_boot = self.cfg.get("enemy_gui", {})
        self.auto_randomize_seed_var = tk.BooleanVar(
            value=bool(enemy_cfg_boot.get("auto_randomize_seed", True))
        )
        self._chk_auto_seed = ttk.Checkbutton(
            seed_row,
            text=t("auto_new_seed"),
            variable=self.auto_randomize_seed_var,
            command=self._on_enemy_category_change,
        )
        self._chk_auto_seed.pack(side="left", padx=(8, 0))

        lang_row = ttk.Frame(seed_row)
        lang_row.pack(side="right", padx=(8, 0))
        self._lbl_lang = ttk.Label(lang_row, text=t("lang_label") + ":")
        self._lbl_lang.pack(side="left")
        self.ui_lang_var = tk.StringVar(value=get_ui_lang())
        self._lang_combo = ttk.Combobox(
            lang_row,
            textvariable=self.ui_lang_var,
            values=("zh", "en"),
            width=5,
            state="readonly",
        )
        self._lang_combo.pack(side="left", padx=4)
        self._lang_combo.bind("<<ComboboxSelected>>", self._on_ui_lang_change)

        self._btn_save = ttk.Button(
            seed_row, text=t("save_settings"), command=self._save_settings_click
        )
        self._btn_save.pack(side="right", padx=4)

        self.test_generate_btn = ttk.Button(
            seed_row,
            text=t("test_generate"),
            command=self._generate_test_only,
        )
        self.test_generate_btn.pack(side="right", padx=4)
        self._maintainer_widgets.append(self.test_generate_btn)

        self.generate_btn = ttk.Button(
            seed_row,
            text=t("generate"),
            command=self._generate_all,
        )
        self.generate_btn.pack(side="right", padx=4)

        self._btn_open_output = ttk.Button(
            seed_row, text=t("open_output"), command=self._open_output
        )
        self._btn_open_output.pack(side="right", padx=4)

        self._generate_hint_maintainer = t("hint_maintainer")
        self._generate_hint_release = t("hint_release")
        self.generate_hint_label = ttk.Label(
            top,
            text=self._generate_hint_maintainer
            if self._maintainer_enabled
            else self._generate_hint_release,
            wraplength=900,
            justify="left",
        )
        self.generate_hint_label.pack(fill="x", pady=(2, 0))

        prog_row = ttk.Frame(top)
        prog_row.pack(fill="x", pady=(4, 0))
        self.gen_progress_var = tk.DoubleVar(value=0.0)
        self.gen_progress = ttk.Progressbar(
            prog_row, variable=self.gen_progress_var, maximum=100.0
        )
        self.gen_progress.pack(side="left", fill="x", expand=True)
        self.gen_progress_label = ttk.Label(
            prog_row, text=t("ready"), width=28, anchor="e"
        )
        self.gen_progress_label.pack(side="right", padx=(8, 0))
        self.generate_status_label = ttk.Label(
            prog_row,
            text="",
            foreground="#444444",
        )
        self.generate_status_label.pack(side="right", padx=(8, 0))

        # Notebook + 428-style checkboxes overlaid on item/enemy tab headers
        self._nb_host = ttk.Frame(self)
        self._nb_host.pack(fill="x", **pad)
        try:
            style = ttk.Style(self)
            # Larger tab title + room for big enable glyph
            tab_font = ("Microsoft YaHei UI", 12)
            try:
                style.configure(
                    "TNotebook.Tab",
                    padding=(28, 10),
                    font=tab_font,
                )
            except tk.TclError:
                style.configure("TNotebook.Tab", padding=(28, 10))
        except tk.TclError:
            pass
        self.notebook = ttk.Notebook(self._nb_host)
        self.notebook.pack(fill="x")

        self.tab_install = ttk.Frame(self.notebook)
        self.tab_items = ttk.Frame(self.notebook)
        self.tab_enemies = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_install, text="")
        self.notebook.add(self.tab_items, text="")
        self.notebook.add(self.tab_enemies, text="")
        self._refresh_tab_titles()

        self._chk_page_items = self._make_tab_enable_toggle(self.page_items_var)
        self._chk_page_enemies = self._make_tab_enable_toggle(self.page_enemies_var)
        self.notebook.bind("<Configure>", self._position_tab_checkboxes)
        self._nb_host.bind("<Configure>", self._position_tab_checkboxes)

        self._build_install_tab()
        self._build_items_tab()
        self._build_enemies_tab()
        self.after_idle(self._position_tab_checkboxes)
        self.after(100, self._position_tab_checkboxes)
        self.after(300, self._position_tab_checkboxes)

        self.log = scrolledtext.ScrolledText(
            self, height=5, wrap="word", font=("Consolas", 9)
        )
        self.log.pack(fill="x", padx=8, pady=(2, 8))

        self._log(t("boot_log"))
        if self._maintainer_enabled:
            self._log(t("maintainer_on"))
        self._update_generate_status()


    def _update_generate_status(self) -> None:
        parts: list[str] = []
        if self.page_items_var.get():
            parts.append(t("tab_items") + " ✓")
        if self.page_enemies_var.get():
            parts.append(t("tab_enemies") + " ✓")
        if parts:
            text = t("gen_will") + " · ".join(parts)
        else:
            text = t("gen_none")
        if hasattr(self, "generate_status_label"):
            self.generate_status_label.configure(text=text)


    def _cfg_snapshot(self) -> dict:
        snap = dict(self.cfg)
        snap["ui_lang"] = get_ui_lang()
        snap["enabled_cats"] = {
            NAME_TO_CAT[name]
            for name, var in self.cat_vars.items()
            if var.get()
        }
        # 战灰并入法术：magic 开则 CAT_ASH 开，关则关
        snap["enabled_cats"] = set(snap["enabled_cats"])
        if NAME_TO_CAT["magic"] in snap["enabled_cats"]:
            snap["enabled_cats"].add(CAT_ASH)
        else:
            snap["enabled_cats"].discard(CAT_ASH)
        snap["enabled_cats"].discard(CAT_TALISMAN)  # 遗物兑换不进池
        snap["enabled_goods_groups"] = {
            gid for gid, var in self.goods_group_vars.items() if var.get()
        }
        snap["enabled_goods_subcats"] = expand_goods_groups(snap["enabled_goods_groups"])
        if snap["enabled_goods_subcats"]:
            snap["enabled_cats"].add(CAT_GOODS)
        snap["include_dlc"] = self.include_dlc_var.get()
        snap["region_strictness"] = round(
            max(0.0, min(1.0, float(self.region_strictness_var.get()))), 2
        )
        mob_drop_mode = "donor_default"
        dlc_pool_mode = ENEMY_DLC_POOL_MODE
        map_filter = ""
        if hasattr(self, "enemy_map_filter_var"):
            map_filter = self.enemy_map_filter_var.get().strip()
        snap["enemy_gui"] = {
            "page_items_enabled": self.page_items_var.get(),
            "page_enemies_enabled": self.page_enemies_var.get(),
            "category_weights": self._enemy_get_category_weights(),
            "mob_drop_mode": mob_drop_mode,
            "drop_mode": mob_drop_mode,
            "keep_original_drops": False,
            "dlc_pool_mode": dlc_pool_mode,
            "map_filter": map_filter or None,
            "auto_randomize_seed": self.auto_randomize_seed_var.get(),
            "difficulty": {
                "enabled": bool(
                    getattr(self, "enemy_difficulty_enabled_var", tk.BooleanVar(value=True)).get()
                ),
                "user_mult": max(
                    0.25,
                    min(
                        2.0,
                        float(
                            getattr(self, "enemy_difficulty_mult_var", tk.DoubleVar(value=1.0)).get()
                            or 1.0
                        ),
                    ),
                ),
            },
        }
        return snap


    def _schedule_session_save(self) -> None:
        if self._session_save_after is not None:
            self.after_cancel(self._session_save_after)
        self._session_save_after = self.after(
            SESSION_SAVE_MS, self._run_debounced_session_save
        )


    def _run_debounced_session_save(self) -> None:
        self._session_save_after = None
        self._save_session(silent=True)


    def _save_settings_click(self) -> None:
        self._cancel_pending_timers()
        if self._save_session(silent=False):
            messagebox.showinfo(t("saved"), t("saved_to", path=CONFIG_PATH))


    def _set_generate_busy(self, busy: bool, status: str = "") -> None:
        state = "disabled" if busy else "normal"
        self.generate_btn.configure(state=state)
        self.test_generate_btn.configure(state=state)
        if status:
            self._log(status)
            self.update_idletasks()
        if not busy:
            self._set_progress(0, t("ready"))


    def _set_progress(self, pct: float, text: str = "") -> None:
        if threading.current_thread() is threading.main_thread():
            self._write_progress(pct, text)
        else:
            self.after(0, lambda p=pct, t=text: self._write_progress(p, t))


    def _write_progress(self, pct: float, text: str) -> None:
        self.gen_progress_var.set(max(0.0, min(100.0, float(pct))))
        if text:
            self.gen_progress_label.configure(text=text)


    def _generate_all(self) -> None:
        if not self._require_mod_installed_for_generate():
            return
        if not self.page_items_var.get() and not self.page_enemies_var.get():
            messagebox.showwarning("提示", "请至少勾选「参与随机：物品」或「参与随机：敌人」。")
            return
        if getattr(self, "_generate_thread", None) and self._generate_thread.is_alive():
            messagebox.showwarning("提示", "正在生成中，请稍候…")
            return

        if self.auto_randomize_seed_var.get():
            self._random_seed()
            self._log(f"已自动换新种子: {self.seed_var.get()}")

        self._set_generate_busy(True, "======== 开始生成（后台运行，窗口可滚动日志）========")
        self._last_items_summary = None
        self._last_enemy_summary = None
        do_items = bool(self.page_items_var.get())
        do_enemies = bool(self.page_enemies_var.get())
        try:
            seed = int(self.seed_var.get().strip())
        except ValueError:
            seed = int(self.cfg.get("seed", 42001))
        self._last_run_do_items = do_items
        self._last_run_do_enemies = do_enemies
        self._generate_thread = threading.Thread(
            target=self._generate_all_worker,
            args=(do_items, do_enemies, seed),
            daemon=True,
        )
        self._generate_thread.start()


    def _generate_test_only(self) -> None:
        if not self._require_mod_installed_for_generate():
            return
        if not self.page_enemies_var.get():
            messagebox.showwarning(
                "提示",
                "测试生成只写敌人 txt，请先勾选「参与随机：敌人」。",
            )
            return
        if getattr(self, "_generate_thread", None) and self._generate_thread.is_alive():
            messagebox.showwarning("提示", "正在生成中，请稍候…")
            return

        if self.auto_randomize_seed_var.get():
            self._random_seed()
            self._log(f"已自动换新种子: {self.seed_var.get()}")

        self._set_generate_busy(
            True, "======== 测试生成（仅 output txt，不写 MSB）========"
        )
        self._last_enemy_summary = None
        self._generate_thread = threading.Thread(
            target=self._generate_test_worker, daemon=True
        )
        self._generate_thread.start()


    def _generate_test_worker(self) -> None:
        enemy_ok = False
        try:
            seed = int(self.seed_var.get().strip())
        except ValueError:
            seed = int(self.cfg.get("seed", 42001))
        self._session_log_begin("test_enemy", seed, apply_msb=False)
        try:
            self._set_progress(2, "敌人：计算替换表…")
            enemy_ok = self._generate_enemies(
                progress_start=2.0,
                progress_calc_end=98.0,
                progress_end=100.0,
                apply_msb=False,
            )
        except Exception as exc:
            self.after(0, lambda: messagebox.showerror("测试生成失败", str(exc)))
            self._log_threadsafe(f"测试生成失败: {exc}")
            if self._session_log:
                self._session_log.line(f"ERROR {exc}")
        finally:
            self._session_log_finish(
                ok=enemy_ok,
                summary=self._last_enemy_summary or "",
            )
            self.after(0, self._generate_test_done, enemy_ok)


    def _generate_test_done(self, enemy_ok: bool) -> None:
        self._set_generate_busy(False)
        self._save_session(silent=True)
        if enemy_ok:
            elapsed = getattr(self, "_last_session_elapsed", None)
            suffix = (
                f"（用时 {elapsed:.1f} 秒）"
                if isinstance(elapsed, (int, float))
                else ""
            )
            self._log(f"======== 测试生成完成{suffix}（未安装 MSB）========")
            lines = ["测试生成已完成！", ""]
            if self._last_enemy_summary:
                lines.append(self._last_enemy_summary)
            if self.last_enemy_map:
                out_dir = self.last_enemy_map.parent
                lines.append(f"输出目录: {out_dir}")
                zh_path = out_dir / "spoiler_enemies_zh.txt"
                if zh_path.is_file():
                    lines.append(f"中文对照表: {zh_path.name}")
            lines.append("")
            lines.append("未写入游戏 MSB；确认表无误后再点「生成随机」安装。")
            messagebox.showinfo("测试生成完成", "\n".join(lines))
        else:
            self._log("======== 测试生成未完成（见上方错误）========")


    def _session_log_begin(self, kind: str, seed: int, **meta: object) -> None:
        self._session_log = GuiSessionLog(kind=kind, seed=seed)
        for key, value in meta.items():
            self._session_log.line(f"meta {key}={value}")
        self._log_threadsafe(f"详细日志 → {LATEST_LOG}")
        self._log_threadsafe(f"本次存档 → {self._session_log.path}")


    def _session_log_finish(self, *, ok: bool, summary: str = "") -> None:
        if self._session_log is None:
            return
        elapsed = self._session_log.elapsed()
        path = self._session_log.finish(ok=ok, summary=summary)
        self._last_session_elapsed = elapsed
        self._log_threadsafe(f"详细日志已写入 → {path}")
        self._log_threadsafe(f"用时 {elapsed:.1f} 秒")
        self._session_log = None


    def _generate_all_worker(
        self, do_items: bool, do_enemies: bool, seed: int
    ) -> None:
        items_ok = False
        enemy_ok = False
        if do_items and do_enemies:
            item_end, enemy_start, enemy_calc_end, progress_end = (
                12.0,
                12.0,
                52.0,
                100.0,
            )
        elif do_items:
            item_end, enemy_start, enemy_calc_end, progress_end = (
                100.0,
                100.0,
                100.0,
                100.0,
            )
        else:
            item_end, enemy_start, enemy_calc_end, progress_end = (
                0.0,
                0.0,
                50.0,
                100.0,
            )
        try:
            self._session_log_begin(
                "generate_all",
                seed,
                do_items=do_items,
                do_enemies=do_enemies,
            )
            if do_items:
                self._set_progress(2, "物品：计算替换表…")
                items_ok = self._generate_items(seed=seed)
                self._set_progress(item_end, "物品完成")
            else:
                self._log_threadsafe("物品页未勾选 — 跳过")

            if do_enemies:
                if self._session_log is not None and do_items:
                    self._session_log.mark_phase("enemies", "敌人生成")
                enemy_ok = self._generate_enemies(
                    progress_start=enemy_start,
                    progress_calc_end=enemy_calc_end,
                    progress_end=progress_end,
                    seed=seed,
                )
            else:
                self._log_threadsafe("敌人未勾选「参与随机：敌人」— 跳过")
        except Exception as exc:
            self.after(0, lambda: messagebox.showerror("生成失败", str(exc)))
            self._log_threadsafe(f"生成失败: {exc}")
            if self._session_log:
                self._session_log.line(f"ERROR {exc}")
        finally:
            ok = items_ok or enemy_ok
            parts: list[str] = []
            if self._last_items_summary:
                parts.append(self._last_items_summary)
            if self._last_enemy_summary:
                parts.append(self._last_enemy_summary)
            self._session_log_finish(ok=ok, summary=" | ".join(parts))
            self.after(
                0,
                self._generate_all_done,
                items_ok,
                enemy_ok,
                do_items,
                do_enemies,
            )


    def _generate_all_done(
        self,
        items_ok: bool,
        enemy_ok: bool,
        do_items: bool,
        do_enemies: bool,
    ) -> None:
        self._set_generate_busy(False)
        self._refresh_tab_titles()
        self._save_session(silent=True)

        if items_ok or enemy_ok:
            elapsed = getattr(self, "_last_session_elapsed", None)
            suffix = (
                f"（用时 {elapsed:.1f} 秒）"
                if isinstance(elapsed, (int, float))
                else ""
            )
            self._log(f"======== 生成完成{suffix} ========")
            self._show_generate_done_dialog(
                items_ok, enemy_ok, do_items=do_items, do_enemies=do_enemies
            )
        elif do_items or do_enemies:
            self._log("======== 生成未完成（见上方错误）========")


    def _show_generate_done_dialog(
        self,
        items_ok: bool,
        enemy_ok: bool,
        *,
        do_items: bool,
        do_enemies: bool,
    ) -> None:
        lines = ["生成随机已完成！"]
        if items_ok and self._last_items_summary:
            lines.append(self._last_items_summary)
        elif do_items and not items_ok:
            lines.append("物品：未完成（见下方日志）")
        if enemy_ok and self._last_enemy_summary:
            lines.append(self._last_enemy_summary)
        elif do_enemies and not enemy_ok:
            lines.append("敌人：未完成（见下方日志；常见：未扫图 / MSB 安装失败）")
        elif not do_enemies:
            lines.append("敌人：本次未勾选「参与随机：敌人」，已跳过")
        lines.append("")
        lines.append("请完全退出游戏后，用 Start_Convergence.bat 重新进入。")
        if enemy_ok:
            lines.append("敌人换怪建议新档或 NG（已杀过的怪不会刷新）。")
        messagebox.showinfo("生成随机完成", "\n".join(lines))


    def _output_dir(self) -> Path:
        return resolve_output_dir(self.cfg)


    def _save_session(self, *, silent: bool = True) -> bool:
        try:
            seed = int(self.seed_var.get().strip())
        except ValueError:
            seed = int(self.cfg.get("seed", 42001))
        self.cfg["seed"] = seed
        snap = self._cfg_snapshot()
        self.cfg.update(snap)
        if self._maintainer_enabled:
            self.cfg["maintainer_gui"] = True
        try:
            save_config(CONFIG_PATH, self.cfg)
            if not silent:
                self._log(f"已保存设置 -> {CONFIG_PATH}")
            return True
        except OSError as exc:
            if not silent:
                messagebox.showerror("保存失败", str(exc))
            return False


    def _on_close(self) -> None:
        self._cancel_pending_timers()
        self._save_session(silent=True)
        self.destroy()


    def _log(self, text: str) -> None:
        if threading.current_thread() is threading.main_thread():
            self._write_log(text)
        else:
            self.after(0, lambda t=text: self._write_log(t))


    def _write_log(self, text: str) -> None:
        self.log.insert("end", text.rstrip() + "\n")
        self.log.see("end")
        if self._session_log is not None:
            self._session_log.line(f"ui {text.rstrip()}")


    def _log_threadsafe(self, text: str) -> None:
        self._log(text)


    def _show_message(self, kind: str, title: str, message: str) -> None:
        def _show() -> None:
            if kind == "error":
                messagebox.showerror(title, message)
            elif kind == "warning":
                messagebox.showwarning(title, message)
            else:
                messagebox.showinfo(title, message)

        if threading.current_thread() is threading.main_thread():
            _show()
        else:
            self.after(0, _show)


    def _random_seed(self) -> None:
        self.seed_var.set(str(random.randint(1, 999_999_999)))
        self._schedule_session_save()


    def _sync_config(self, *, require_item_cats: bool = True) -> None:
        try:
            seed = int(self.seed_var.get().strip())
        except ValueError:
            raise ValueError("种子必须是整数") from None
        self.cfg["seed"] = seed
        snap = self._cfg_snapshot()
        self.cfg.update(snap)
        if self._maintainer_enabled:
            self.cfg["maintainer_gui"] = True
        if (
            require_item_cats
            and not self.cfg["enabled_cats"]
            and not self.cfg["enabled_goods_groups"]
        ):
            raise ValueError("请至少勾选一个装备类别或道具大类")
        save_config(CONFIG_PATH, self.cfg)
        self.cfg = load_config(CONFIG_PATH)


    def _open_output(self) -> None:
        out = self._output_dir()
        out.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(["explorer", str(out)])


def main() -> None:
    app = RandomizerApp()
    app.mainloop()


if __name__ == "__main__":
    import multiprocessing

    multiprocessing.freeze_support()
    main()
