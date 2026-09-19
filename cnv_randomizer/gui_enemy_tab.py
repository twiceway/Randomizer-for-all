#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from paths import GAME_DIR
from enemy_randomizer_core import (
    DEFAULT_CATEGORIES_PATH,
    DEFAULT_INDEX_PATH,
    _ENEMY_CALC_PHASE_SPAN,
    _load_json,
    deploy_enemy_spawn_map,
    run_enemy_apply,
    run_enemy_randomize,
    run_index_export,
)
from gui_maintainer import deploy_enemy_debug_slot_index
from gui_session_log import append_enemy_result_diagnostics

from donor_pool_review_allowlist import migrate_category_weights
from gui_common import (
    ENEMY_CATEGORY_LABELS,
    ENEMY_CATEGORY_NUM,
    ENEMY_CATEGORY_ORDER,
    ENEMY_DLC_POOL_MODE,
    ENEMY_NUM_LEGEND,
    ENEMY_SPAWN_MAP_PATH,
    SCRIPT_DIR,
    _decode_subprocess_bytes,
    _format_weight,
    _read_spawn_map_seed,
    adjust_enemy_row_weights_on_max,
    diagonal_enemy_category_weights,
    load_enemy_category_weights,
    load_enemy_difficulty_settings,
    normalize_enemy_row_weights,
)
from gui_i18n import t

class EnemyTabMixin:
    def _build_enemies_tab(self) -> None:
        pad = {"padx": 8, "pady": 4}
        parent = self.tab_enemies
        parent.columnconfigure(0, weight=1)

        enemy_cfg = self.cfg.get("enemy_gui", {})
        saved_weights = load_enemy_category_weights(enemy_cfg)

        toolbar = ttk.Frame(parent)
        toolbar.grid(row=0, column=0, sticky="ew", **pad)
        toolbar.columnconfigure(0, weight=1)
        btn_row = ttk.Frame(toolbar)
        btn_row.pack(fill="x")

        self.enemy_scan_btn = ttk.Button(
            btn_row,
            text=t("enemy_scan"),
            command=self._enemy_scan_maps,
        )
        self.enemy_scan_btn.pack(side="left", padx=(0, 4))
        self._maintainer_widgets.append(self.enemy_scan_btn)

        maint_sep = ttk.Separator(btn_row, orient="vertical")
        maint_sep.pack(side="left", fill="y", padx=(8, 8), pady=2)
        self._maintainer_widgets.append(maint_sep)

        self.maintainer_test_lab_btn = ttk.Button(
            btn_row,
            text=t("maint_lab"),
            command=self._open_gatefront_test_lab,
        )
        self.maintainer_test_lab_btn.pack(side="left", padx=(0, 4))
        self._maintainer_widgets.append(self.maintainer_test_lab_btn)

        self.maintainer_offline_table_btn = ttk.Button(
            btn_row,
            text=t("maint_offline"),
            command=self._offline_slot_table_ingest,
        )
        self.maintainer_offline_table_btn.pack(side="left", padx=(0, 4))
        self._maintainer_widgets.append(self.maintainer_offline_table_btn)

        self.maintainer_f6f7_btn = ttk.Button(
            btn_row,
            text=t("maint_f6f7"),
            command=self._deploy_f6f7_slot_index,
        )
        self.maintainer_f6f7_btn.pack(side="left", padx=(0, 4))
        self._maintainer_widgets.append(self.maintainer_f6f7_btn)

        self.maintainer_reexport_donor_btn = ttk.Button(
            btn_row,
            text=t("maint_reexport"),
            command=self._reexport_donor_bundle,
        )
        self.maintainer_reexport_donor_btn.pack(side="left", padx=(0, 4))
        self._maintainer_widgets.append(self.maintainer_reexport_donor_btn)

        ttk.Button(
            btn_row,
            text=t("enemy_restore"),
            command=self._restore_enemy_overlay,
        ).pack(side="left", padx=4)
        self.enemy_spoiler_btn = ttk.Button(
            btn_row,
            text=t("enemy_spoiler"),
            command=self._open_enemy_spoiler,
        )
        self.enemy_spoiler_btn.pack(side="left", padx=4)
        self._maintainer_widgets.append(self.enemy_spoiler_btn)
        self.enemy_stats_label = ttk.Label(
            toolbar,
            text=t("enemy_stats"),
            justify="left",
            foreground="#444444",
            wraplength=1100,
        )
        self.enemy_stats_label.pack(fill="x", anchor="w", pady=(4, 0))

        cats = ttk.LabelFrame(parent, text=t("enemy_weights_frame"))
        cats.grid(row=1, column=0, sticky="ew", **pad)
        cats.columnconfigure(0, weight=1)

        btn_row = ttk.Frame(cats)
        btn_row.grid(row=0, column=0, sticky="ew", padx=8, pady=(6, 0))
        ttk.Button(btn_row, text=t("enemy_preset_same"), command=self._enemy_preset_same).pack(
            side="left", padx=4
        )
        ttk.Button(btn_row, text=t("enemy_preset_avg"), command=self._enemy_preset_all).pack(
            side="left", padx=4
        )
        ttk.Button(btn_row, text=t("enemy_preset_weak"), command=self._enemy_preset_weak_to_boss).pack(
            side="left", padx=4
        )
        ttk.Button(btn_row, text=t("enemy_preset_smooth"), command=self._enemy_preset_smooth).pack(
            side="left", padx=4
        )
        ttk.Button(btn_row, text=t("enemy_preset_fill"), command=self._enemy_normalize_all_rows).pack(
            side="left", padx=4
        )
        ttk.Button(btn_row, text=t("enemy_preset_clear"), command=self._enemy_preset_clear).pack(
            side="left", padx=4
        )
        ttk.Label(
            cats,
            text=t("enemy_weights_hint") + ENEMY_NUM_LEGEND,
            foreground="#666",
            wraplength=1100,
            justify="left",
        ).grid(row=1, column=0, sticky="w", padx=12, pady=(2, 2))

        table_outer = ttk.Frame(cats)
        table_outer.grid(row=2, column=0, sticky="ew", padx=8, pady=(0, 6))
        table_outer.columnconfigure(0, weight=1)

        table_canvas = tk.Canvas(table_outer, highlightthickness=0, borderwidth=0)
        table = ttk.Frame(table_canvas)
        table_window = table_canvas.create_window((0, 0), window=table, anchor="nw")

        def on_table_configure(_event: tk.Event | None = None) -> None:
            table_canvas.configure(scrollregion=table_canvas.bbox("all"))
            width = table_canvas.winfo_width()
            if width > 1:
                table_canvas.itemconfigure(table_window, width=width)
            bbox = table_canvas.bbox("all")
            if bbox:
                content_h = bbox[3] - bbox[1]
                table_canvas.configure(height=content_h)

        table.bind("<Configure>", on_table_configure)
        table_canvas.bind("<Configure>", on_table_configure)
        table_canvas.grid(row=0, column=0, sticky="ew")

        ttk.Label(table, text=t("enemy_col_from"), font=("", 9, "bold")).grid(
            row=0, column=0, sticky="w", padx=(0, 8), pady=(0, 4)
        )
        ttk.Label(table, text=t("enemy_col_to"), font=("", 9, "bold")).grid(
            row=0,
            column=1,
            columnspan=len(ENEMY_CATEGORY_ORDER),
            sticky="w",
            pady=(0, 4),
        )
        ttk.Label(table, text=t("enemy_col_sum"), font=("", 8, "bold")).grid(
            row=0, column=1 + len(ENEMY_CATEGORY_ORDER), sticky="w", padx=(6, 0)
        )

        # 列宽与下方 Entry(width=5) 对齐，避免 1234567 与矩阵错位
        cell_w = 5
        for col_i, tgt_id in enumerate(ENEMY_CATEGORY_ORDER, start=1):
            table.columnconfigure(col_i, minsize=42, weight=0)
            ttk.Label(
                table,
                text=str(ENEMY_CATEGORY_NUM[tgt_id]),
                width=cell_w,
                anchor="center",
                font=("", 9, "bold"),
            ).grid(row=1, column=col_i, padx=1, sticky="ew")
            short = ENEMY_CATEGORY_LABELS[tgt_id].replace(" Boss", "").replace("/", "")
            if len(short) > 4:
                short = short[:4]
            ttk.Label(
                table,
                text=short,
                width=cell_w,
                anchor="center",
                font=("", 7),
                foreground="#666666",
            ).grid(row=2, column=col_i, padx=1, sticky="ew")

        self.enemy_weight_vars.clear()
        self.enemy_row_sum_labels.clear()
        for row_idx, src_id in enumerate(ENEMY_CATEGORY_ORDER, start=3):
            src_num = ENEMY_CATEGORY_NUM[src_id]
            src_label = ENEMY_CATEGORY_LABELS[src_id]
            ttk.Label(
                table,
                text=f"{src_num}  {src_label}",
                width=20,
            ).grid(row=row_idx, column=0, sticky="w", padx=(0, 8), pady=2)

            saved_row = saved_weights.get(src_id, {})
            self.enemy_weight_vars[src_id] = {}
            for col_i, tgt_id in enumerate(ENEMY_CATEGORY_ORDER, start=1):
                w = saved_row.get(tgt_id, 0.0)
                var = tk.StringVar(value=_format_weight(w))
                self.enemy_weight_vars[src_id][tgt_id] = var
                entry = ttk.Entry(
                    table,
                    textvariable=var,
                    width=cell_w,
                    justify="center",
                )
                entry.grid(row=row_idx, column=col_i, padx=1, pady=2, sticky="ew")
                entry.bind(
                    "<FocusOut>",
                    lambda _e, s=src_id, t=tgt_id: self._on_enemy_weight_edit(s, t),
                )
                entry.bind(
                    "<Return>",
                    lambda _e, s=src_id, t=tgt_id: self._on_enemy_weight_edit(s, t),
                )

            sum_label = ttk.Label(table, text="", width=8, foreground="#555555")
            sum_label.grid(
                row=row_idx,
                column=1 + len(ENEMY_CATEGORY_ORDER),
                sticky="w",
                padx=(6, 0),
            )
            self.enemy_row_sum_labels[src_id] = sum_label
            self._refresh_enemy_row_sum(src_id)

        ttk.Label(
            table,
            text=t("enemy_edit_hint"),
            foreground="#666666",
        ).grid(
            row=3 + len(ENEMY_CATEGORY_ORDER),
            column=0,
            columnspan=2 + len(ENEMY_CATEGORY_ORDER),
            sticky="w",
            pady=(8, 0),
        )

        options = ttk.LabelFrame(parent, text=t("enemy_options"))
        options.grid(row=2, column=0, sticky="ew", padx=8, pady=(0, 2))
        options.columnconfigure(0, weight=1)

        # Kill runes: fixed donor_default (no UI choice)
        self.enemy_mob_drop_mode_var = tk.StringVar(value="donor_default")

        diff_col = ttk.Frame(options)
        diff_col.grid(row=0, column=0, sticky="nw", padx=10, pady=6)
        diff_settings = load_enemy_difficulty_settings(enemy_cfg)
        self.enemy_difficulty_enabled_var = tk.BooleanVar(
            value=bool(diff_settings.get("enabled", True))
        )
        self.enemy_difficulty_mult_var = tk.DoubleVar(
            value=float(diff_settings.get("user_mult", 1.0))
        )
        ttk.Label(diff_col, text=t("enemy_diff_title"), font=("", 9, "bold")).pack(anchor="w")
        ttk.Checkbutton(
            diff_col,
            text=t("enemy_diff_auto"),
            variable=self.enemy_difficulty_enabled_var,
            command=self._on_enemy_category_change,
        ).pack(anchor="w", pady=1)
        mult_row = ttk.Frame(diff_col)
        mult_row.pack(anchor="w", pady=(2, 0))
        ttk.Label(mult_row, text=t("enemy_diff_mult")).pack(side="left")
        ttk.Spinbox(
            mult_row,
            from_=0.25,
            to=2.0,
            increment=0.05,
            width=6,
            textvariable=self.enemy_difficulty_mult_var,
            command=self._on_enemy_diff_mult_change,
        ).pack(side="left", padx=(4, 0))
        self.enemy_diff_band_label = ttk.Label(
            mult_row,
            text="",
            foreground="#333333",
            font=("", 9, "bold"),
        )
        self.enemy_diff_band_label.pack(side="left", padx=(8, 0))
        ttk.Label(
            mult_row,
            text=t("enemy_diff_mult_hint"),
            foreground="#666666",
        ).pack(side="left", padx=(6, 0))
        ttk.Label(
            diff_col,
            text=t("enemy_diff_guide"),
            foreground="#666666",
            wraplength=900,
            justify="left",
        ).pack(anchor="w", pady=(4, 0))
        self.enemy_difficulty_mult_var.trace_add(
            "write", lambda *_a: self._on_enemy_diff_mult_change()
        )
        self._refresh_enemy_diff_band()

        # Map filter: maintainer-only
        test_row = ttk.Frame(options)
        self.enemy_map_filter_var = tk.StringVar(
            value=str(enemy_cfg.get("map_filter") or "").strip()
        )
        ttk.Label(test_row, text=t("enemy_map_filter")).pack(anchor="w")
        map_filter_row = ttk.Frame(test_row)
        map_filter_row.pack(anchor="w", pady=(2, 0))
        ttk.Entry(
            map_filter_row,
            textvariable=self.enemy_map_filter_var,
            width=28,
        ).pack(side="left")
        ttk.Label(
            map_filter_row,
            text=t("enemy_map_filter_hint"),
            foreground="#666666",
        ).pack(side="left")
        self.enemy_map_filter_var.trace_add(
            "write", lambda *_a: self._on_enemy_category_change()
        )
        test_row.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 8))
        self._maintainer_widgets.append(test_row)


    def _diff_band_key(self, mult: float) -> str:
        if mult < 0.375:
            return "enemy_diff_band_novice"
        if mult < 0.625:
            return "enemy_diff_band_normal"
        if mult < 0.875:
            return "enemy_diff_band_hard"
        return "enemy_diff_band_hell"

    def _refresh_enemy_diff_band(self) -> None:
        if not hasattr(self, "enemy_diff_band_label"):
            return
        try:
            mult = float(self.enemy_difficulty_mult_var.get())
        except (TypeError, ValueError, tk.TclError):
            mult = 1.0
        self.enemy_diff_band_label.configure(text=t(self._diff_band_key(mult)))

    def _on_enemy_diff_mult_change(self, *_args) -> None:
        self._refresh_enemy_diff_band()
        self._on_enemy_category_change()

    def _apply_maintainer_visibility(self) -> None:
        if self._maintainer_enabled:
            self.generate_hint_label.configure(text=self._generate_hint_maintainer)
            return
        for widget in self._maintainer_widgets:
            try:
                widget.pack_forget()
            except tk.TclError:
                pass
            try:
                widget.grid_remove()
            except tk.TclError:
                pass
        self.generate_hint_label.configure(text=self._generate_hint_release)


    def _open_gatefront_test_lab(self) -> None:
        script = SCRIPT_DIR / "gatefront_test_lab_gui.py"
        if not script.is_file():
            messagebox.showerror("试验台", f"缺少脚本：\n{script}")
            return
        try:
            subprocess.Popen(
                [sys.executable, str(script)],
                cwd=str(SCRIPT_DIR),
            )
            self._log("已打开门前试验台（14 写盘位 + 3 蝙蝠槽）")
        except OSError as exc:
            messagebox.showerror("试验台", str(exc))


    def _offline_slot_table_ingest(self) -> None:
        if getattr(self, "_offline_table_thread", None) and self._offline_table_thread.is_alive():
            messagebox.showwarning("提示", "离线槽位入库进行中，请稍候…")
            return
        raw_path = SCRIPT_DIR / "cache" / "offline" / "enemy_index.raw.json"
        rescan = not raw_path.is_file()
        if rescan:
            if not messagebox.askyesno(
                "离线槽位入库",
                "将全图扫描 MSB 并写入 cache/offline/enemy_slot_table.json\n"
                "（筛掉小动物、NPC、装饰等跳过槽）\n\n"
                "首次约数分钟，是否继续？",
            ):
                return
        else:
            if not messagebox.askyesno(
                "离线槽位入库",
                "已有 offline 扫描快照，将快速重建离线表（--no-rescan）。\n\n"
                "若刚改过 MSB 或索引，请先点「扫描游戏地图」或删 offline 快照后重扫。\n\n"
                "是否继续？",
            ):
                return
        self.maintainer_offline_table_btn.configure(state="disabled")
        self._offline_table_thread = threading.Thread(
            target=self._offline_slot_table_worker,
            args=(rescan,),
            daemon=True,
        )
        self._offline_table_thread.start()


    def _offline_slot_table_worker(self, rescan: bool) -> None:
        self._log_threadsafe("—— 离线槽位入库（T-077）——")
        try:
            from enemy_slot_table import build_offline_enemy_slot_table

            result = build_offline_enemy_slot_table(rescan=rescan)
            meta_path = result["paths"]["meta"]
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            excluded = meta.get("excluded_slot_counts") or {}
            msg = (
                f"离线表 {result.get('table_rows')} 参战槽 · "
                f"扫描 {result.get('slot_count')} 槽 · "
                f"剔动物 {excluded.get('animal', 0)} · "
                f"剔 NPC {excluded.get('npc', 0)} · "
                f"剔装饰 {excluded.get('decorative', 0)} · "
                f"剔其他 {excluded.get('other_skip', 0)}"
            )
            self._log_threadsafe(msg)
            self._log_threadsafe(f"主表: {result['paths']['json']}")
            self.after(
                0,
                lambda: messagebox.showinfo("离线槽位入库", msg + "\n\n" + str(result["paths"]["json"])),
            )
        except Exception as exc:
            self._log_threadsafe(f"离线槽位入库失败: {exc}")
            self.after(0, lambda: messagebox.showerror("离线槽位入库", str(exc)))
        finally:
            self.after(
                0,
                lambda: self.maintainer_offline_table_btn.configure(state="normal"),
            )


    def _deploy_f6f7_slot_index(self) -> None:
        self._log("—— F6/F7 槽位索引 ——")
        try:
            dest, slot_count = deploy_enemy_debug_slot_index(game_dir=GAME_DIR)
        except Exception as exc:
            messagebox.showerror("F6/F7", str(exc))
            self._log(f"F6/F7 槽位索引失败: {exc}")
            return
        self._log(f"已导出 {slot_count} 槽 → {dest}")
        messagebox.showinfo(
            "F6/F7 槽位索引",
            f"已写入 {slot_count} 槽\n{dest}\n\n"
            "请完全退出游戏后重进；F6 标槽 / F7 锁敌需 hook 已加载。",
        )


    def _parse_enemy_weight(self, raw: str) -> float:
        text = raw.strip().replace("%", "")
        if not text:
            return 0.0
        try:
            return max(0.0, float(text))
        except ValueError:
            return 0.0


    def _enemy_get_category_weights(self) -> dict[str, dict[str, float]]:
        out: dict[str, dict[str, float]] = {}
        for src_id, targets in self.enemy_weight_vars.items():
            row: dict[str, float] = {}
            for tgt_id, var in targets.items():
                w = self._parse_enemy_weight(var.get())
                if w > 0:
                    row[tgt_id] = round(w, 2)
            if row:
                out[src_id] = row
        return out


    def _enemy_set_category_weights(
        self, mapping: dict[str, dict[str, float]]
    ) -> None:
        for src_id, targets in self.enemy_weight_vars.items():
            row = mapping.get(src_id, {})
            for tgt_id, var in targets.items():
                var.set(_format_weight(float(row.get(tgt_id, 0.0))))
            self._refresh_enemy_row_sum(src_id)


    def _refresh_enemy_row_sum(self, src_id: str) -> None:
        label = self.enemy_row_sum_labels.get(src_id)
        if label is None:
            return
        row = self._enemy_get_category_weights().get(src_id, {})
        total = sum(row.values())
        if total <= 0:
            label.configure(text="—", foreground="#999999")
            return
        text = _format_weight(total)
        if abs(total - 100.0) < 0.05:
            label.configure(text=f"{text}%", foreground="#2a7a2a")
        elif total > 100.05:
            label.configure(text=f"{text}%", foreground="#c0392b")
        else:
            label.configure(text=f"{text}%", foreground="#a65c00")


    def _on_enemy_weight_edit(self, src_id: str, edited_tgt_id: str) -> None:
        row: dict[str, float] = {}
        for tgt_id, var in self.enemy_weight_vars.get(src_id, {}).items():
            row[tgt_id] = self._parse_enemy_weight(var.get())
        adjusted = adjust_enemy_row_weights_on_max(row, edited_key=edited_tgt_id)
        for tgt_id, var in self.enemy_weight_vars.get(src_id, {}).items():
            var.set(_format_weight(adjusted.get(tgt_id, 0.0)))
        self._refresh_enemy_row_sum(src_id)
        self._on_enemy_category_change()


    def _enemy_normalize_all_rows(self) -> None:
        current = self._enemy_get_category_weights()
        normalized: dict[str, dict[str, float]] = {}
        for src_id in ENEMY_CATEGORY_ORDER:
            row = adjust_enemy_row_weights_on_max(current.get(src_id, {}))
            if row:
                normalized[src_id] = row
        self._enemy_set_category_weights(normalized)
        self._on_enemy_category_change()


    def _on_enemy_category_change(self) -> None:
        self._schedule_session_save()


    def _enemy_preset_same(self) -> None:
        self._enemy_set_category_weights(diagonal_enemy_category_weights())
        self._on_enemy_category_change()


    def _enemy_preset_all(self) -> None:
        share = round(100.0 / len(ENEMY_CATEGORY_ORDER), 1)
        base = {tgt: share for tgt in ENEMY_CATEGORY_ORDER}
        row = adjust_enemy_row_weights_on_max(base, edited_key=ENEMY_CATEGORY_ORDER[-1])
        mapping = {src: dict(row) for src in ENEMY_CATEGORY_ORDER}
        self._enemy_set_category_weights(mapping)
        self._on_enemy_category_change()


    def _enemy_preset_weak_to_boss(self) -> None:
        boss_pool = ["elite", "evergaol", "minor_boss", "major_boss"]
        boss_share = round(100.0 / len(boss_pool), 2)
        mapping: dict[str, dict[str, float]] = {
            "trash": {t: boss_share for t in boss_pool},
            "elite": {"elite": 100.0},
            "night": {"major_boss": 100.0},
            "evergaol": {t: round(100.0 / len(ENEMY_CATEGORY_ORDER), 2) for t in ENEMY_CATEGORY_ORDER},
            "minor_boss": {t: round(100.0 / len(ENEMY_CATEGORY_ORDER), 2) for t in ENEMY_CATEGORY_ORDER},
            "major_boss": {"major_boss": 100.0},
        }
        self._enemy_set_category_weights(migrate_category_weights(mapping))
        self._on_enemy_category_change()


    def _enemy_preset_smooth(self) -> None:
        """Lightweight preset: humanoid donors only; low boss roll rate."""
        mapping: dict[str, dict[str, float]] = {
            "trash": {
                "trash": 55.0,
                "night": 10.0,
                "evergaol": 15.0,
                "minor_boss": 20.0,
            },
            "night": {"night": 60.0, "evergaol": 20.0, "minor_boss": 20.0},
            "evergaol": {"evergaol": 70.0, "minor_boss": 30.0},
            "minor_boss": {"minor_boss": 70.0, "evergaol": 30.0},
            "major_boss": {"major_boss": 100.0},
            "elite": {"elite": 100.0},
        }
        self._enemy_set_category_weights(migrate_category_weights(mapping))
        self._on_enemy_category_change()


    def _enemy_preset_clear(self) -> None:
        self._enemy_set_category_weights({})
        self._on_enemy_category_change()


    def _enemy_calc_progress_pct(
        self,
        progress_start: float,
        progress_calc_end: float,
        phase: str,
        done: int,
        total: int,
    ) -> float:
        base, span = _ENEMY_CALC_PHASE_SPAN.get(phase, (0.0, 1.0))
        frac = (done / total) if total > 0 else 1.0
        inner = base + span * frac
        calc_span = max(0.0, progress_calc_end - progress_start)
        return progress_start + calc_span * inner


    def _generate_enemies(
        self,
        *,
        progress_start: float = 0.0,
        progress_calc_end: float = 5.0,
        progress_end: float = 100.0,
        apply_msb: bool = True,
        seed: int | None = None,
    ) -> bool:
        weights = self._enemy_get_category_weights()
        if not weights:
            self._show_message("warning", t("notice"), t("enemy_need_weights"))
            return False

        if not DEFAULT_INDEX_PATH.is_file():
            self._log("未找到地图索引，正在自动扫描…")
            if not self._enemy_scan_maps() or not DEFAULT_INDEX_PATH.is_file():
                self._show_message(
                    "warning",
                    t("notice"),
                    t("enemy_need_scan"),
                )
                return False

        from enemy_slot_density import density_fingerprint_ok

        dens_ok, dens_msg = density_fingerprint_ok()
        if dens_ok:
            self._log(f"密集槽库: {dens_msg}")
        else:
            self._log(f"⚠ 密集槽库: {dens_msg}（仍可生成；密集规则可能未生效）")

        mob_drop_mode = "donor_default"
        self.enemy_mob_drop_mode_var.set(mob_drop_mode)
        self._log("—— 敌人 ——")
        if seed is None:
            try:
                seed = int(self.seed_var.get().strip())
            except ValueError:
                self._show_message("error", t("error"), t("enemy_bad_seed"))
                return False

        self._log(f"种子: {seed}")
        last_seed = _read_spawn_map_seed(ENEMY_SPAWN_MAP_PATH)
        if last_seed is not None and last_seed == seed:
            self._log(
                "⚠ 种子与上次 spawn_map 相同 → 敌人替换表将完全一样。"
                "请勾选「每次生成换新种子」或点「随机种子」。"
            )
        self._log(
            "真机：须完全退出游戏重进；已击杀的怪不会刷新，建议新档/NG 再看门前士兵。"
        )
        self._log("DLC 怪物：本体与 DLC 全图混刷（固定）")
        self._log("Boss 战利品：保持原 Boss 位（或沿用物品随机地上奖）")
        if self.page_items_var.get():
            self._log("  └ 物品随机已开启：地上拾取类奖励会随机")
        self._log(
            "击杀卢恩："
            + (
                "原槽（soul=0→难度分档）"
                if mob_drop_mode == "keep_original"
                else "按新怪 NpcParam 默认卢恩"
            )
            + "（写入 spawn_map + 部署卢恩 hook 表）"
        )

        for src_id in ENEMY_CATEGORY_ORDER:
            row = weights.get(src_id)
            if not row:
                self._log(
                    f"  {ENEMY_CATEGORY_NUM[src_id]} {ENEMY_CATEGORY_LABELS[src_id]} → （不随机）"
                )
                continue
            norm = normalize_enemy_row_weights(row)
            total = sum(row.values())
            parts = []
            for tgt_id in ENEMY_CATEGORY_ORDER:
                if tgt_id not in norm:
                    continue
                raw_w = row[tgt_id]
                eff = norm[tgt_id]
                parts.append(
                    f"{ENEMY_CATEGORY_NUM[tgt_id]}:{raw_w:g}%→{eff:.1f}%"
                )
            self._log(
                f"  {ENEMY_CATEGORY_NUM[src_id]} {ENEMY_CATEGORY_LABELS[src_id]} "
                f"(行Σ{total:g}%) → " + " ".join(parts)
            )

        try:
            self._sync_config(require_item_cats=False)
            cfg = dict(self.cfg)
            enemy_gui = dict(cfg.get("enemy_gui", {}))
            enemy_gui["category_weights"] = weights
            cfg["enemy_gui"] = enemy_gui
            map_filter = str(self.enemy_map_filter_var.get() or "").strip() or None
            if map_filter:
                self._log_threadsafe(
                    f"测试地图：仅计算并写入 {map_filter}（不处理其它地图 MSB）"
                )
            else:
                self._log_threadsafe(
                    "正在计算敌人替换表（全图约 1 万槽，预计 10 分钟左右）…"
                )
                self._log_threadsafe(
                    "进度：有缓存则秒级载入；指纹变更则自动重建槽位缓存"
                    "（①筛选捐皮模板约 5～8 分钟，非 MSB 扫描）。"
                )

            def on_enemy_calc(phase: str, done: int, total: int, msg: str) -> None:
                pct = self._enemy_calc_progress_pct(
                    progress_start, progress_calc_end, phase, done, total
                )
                self._set_progress(pct, msg)
                sess = self._session_log
                if sess is not None:
                    file_every = 50 if phase == "scan" else 100 if phase == "pick" else 1
                    sess.log_progress(phase, done, total, msg, file_every=file_every)
                if phase in ("prep_cache", "scan", "pick") and total > 0:
                    scan_step = 50 if phase == "scan" else 200
                    if done in (0, total) or done % scan_step == 0:
                        self._log_threadsafe(msg)
                    elif phase == "prep_cache" and "仍在运行" in msg:
                        self._log_threadsafe(msg)
                elif done in (0, total):
                    self._log_threadsafe(msg)

            self._set_progress(
                max(progress_start + 0.5, 1.0), "敌人：准备计算…"
            )
            if self._session_log is not None:
                self._session_log.log_config_snapshot(cfg)
            result = run_enemy_randomize(
                cfg,
                seed=seed,
                map_filter=map_filter,
                on_progress=on_enemy_calc,
            )
            self._set_progress(progress_calc_end, "敌人表完成")
        except Exception as exc:
            self._show_message("error", "敌人生成失败", str(exc))
            self._log(f"敌人生成失败: {exc}")
            if self._session_log:
                self._session_log.line(f"ERROR {exc}")
            return False

        if self._session_log is not None:
            append_enemy_result_diagnostics(self._session_log, result)

        self.last_enemy_map = result.spawn_map_path
        try:
            unique_models = list(result.spawn_model_names)
            dlc_models = list(result.gatefront_dlc_models)
            self._log(
                f"本次门前：原型 {result.archetypes_hit} 类 · model {result.models_hit} 种"
                f"（{result.slots_replaced} 槽）"
                + (f"，含 DLC 小怪: {', '.join(dlc_models)}" if dlc_models else "")
            )
            for w in result.warnings or []:
                if str(w).startswith("dense_keep=") or str(w).startswith(
                    "density_fingerprint"
                ):
                    self._log(str(w))
            if getattr(result, "slots_skipped_dense_keep", 0):
                self._log(
                    f"密集约束：原位保留 {result.slots_skipped_dense_keep} 槽"
                )
            if len(unique_models) <= 24:
                self._log(f"  模型列表: {', '.join(unique_models)}")
        except OSError:
            pass
        skip_bits: list[str] = []
        if result.slots_skipped_large:
            skip_bits.append(f"大体型原位 {result.slots_skipped_large}")
        if result.slots_skipped_passive_animal:
            skip_bits.append(f"被动动物原位 {result.slots_skipped_passive_animal}")
        if result.slots_skipped_npc_slot:
            skip_bits.append(f"NPC 槽原位 {result.slots_skipped_npc_slot}")
        if result.slots_skipped_scarab:
            skip_bits.append(f"圣甲虫原位 {result.slots_skipped_scarab}")
        skip_detail = f"（{'，'.join(skip_bits)}）" if skip_bits else ""
        self._log(
            f"槽位：替换 {result.slots_replaced} / {result.slots_total}，"
            f"跳过 {result.slots_skipped}{skip_detail}"
        )
        self._log(f"spawn_map: {result.spawn_map_path}")
        try:
            import time

            from _audit_freeze_pipeline import freeze_gate_detail

            gate_t0 = time.perf_counter()
            gate, gate_total, gate_samples = freeze_gate_detail(result.spawn_map_path)
            gate_elapsed = round(time.perf_counter() - gate_t0, 2)
            if self._session_log is not None:
                self._session_log.log_timing("freeze_gate_timing", gate_elapsed)
            if gate_total > 0:
                parts = [f"{k}={v}" for k, v in gate.items() if v]
                detail = "，".join(parts)
                self._log(f"⚠ 冻怪门禁未通过：{detail}")
                for key, lines in gate_samples.items():
                    for line in lines:
                        self._log(f"  门禁样例 {key}: {line}")
                sample_hint = ""
                first_key = next((k for k, v in gate.items() if v), "")
                first_lines = gate_samples.get(first_key) or []
                if first_lines:
                    sample_hint = f"\n样例：{first_lines[0]}"
                self._show_message(
                    "error",
                    "冻怪门禁未通过",
                    "生成表仍含易冻怪模式（链路 bug），已阻止部署与 MSB 安装。\n"
                    f"详情：{detail}{sample_hint}\n\n"
                    "请完全关闭本窗口后重新打开再生成；不要手改 spawn 表。",
                )
                return False
            self._log("冻怪门禁：通过（高危冻怪模式 0）")
        except OSError as exc:
            self._log(f"冻怪门禁跳过（读表失败）：{exc}")
        except Exception as exc:
            self._log(f"冻怪门禁跳过：{exc}")
        apply_spawn_path = result.apply_spawn_path or result.spawn_map_path
        if result.apply_spawn_path:
            self._log(f"MSB 安装源：{apply_spawn_path.name}（写表后隔离副本）")
        try:
            deploy_dest = deploy_enemy_spawn_map(apply_spawn_path)
            self._log(
                f"已部署卢恩表 → {deploy_dest}（已与生成表校验 seed/slots/大小）"
            )
        except OSError as exc:
            self._show_message(
                "error",
                "卢恩表部署失败",
                f"{exc}\n\n"
                "F6 标记会读游戏 mod 里的旧表，真机怪也可能仍是旧 MSB。\n"
                "请先完全退出游戏，再点「生成随机」重试。",
            )
            self._log(f"spawn_map 部署失败: {exc}")
            return False
        if result.spoiler_zh_path and result.spoiler_zh_path.is_file():
            self._log(f"中文对照表: {result.spoiler_zh_path}")
        self._log(f"spoiler: {result.spoiler_path}")
        if result.risk_report_path and result.risk_report_path.is_file():
            self._log(f"risk_report: {result.risk_report_path}")
        self._log(f"DLC 幽影捐皮：{result.dlc_donor_hits} 槽")
        if result.warnings:
            self._log(f"警告 {len(result.warnings)} 条（见 spoiler 末尾）")

        if result.slots_replaced <= 0:
            self._show_message(
                "warning",
                "无替换槽位",
                "概率表未匹配到任何怪物槽位（生成 0 条）。\n"
                "请检查：① 是否已扫描地图 ② 左侧「原怪物类别」行是否填了概率。\n"
                "未写入游戏 MSB。",
            )
            self._log("生成 0 槽 — 跳过 MSB 安装")
            return False

        if not apply_msb:
            self._set_progress(progress_end, "敌人表完成（未安装 MSB）")
            elapsed_note = ""
            if self._session_log is not None:
                elapsed_note = f"（用时 {self._session_log.elapsed():.1f} 秒）"
            self._log(f"—— 测试生成完成{elapsed_note} ——")
            self._log("未写入游戏 MSB；请打开 output 目录查看 txt。")
            if result.spoiler_zh_path and result.spoiler_zh_path.is_file():
                self._log(f"推荐阅读: {result.spoiler_zh_path.name}")
            self.enemy_stats_label.configure(
                text=(
                    f"已设置类别：{sum(1 for s in ENEMY_CATEGORY_ORDER if weights.get(s))}"
                    f"/{len(ENEMY_CATEGORY_ORDER)}    "
                    f"上次测试：{result.slots_replaced} 槽（仅 txt）    "
                    f"索引：{DEFAULT_INDEX_PATH.name}"
                )
            )
            self._last_enemy_summary = (
                f"敌人：种子 {seed}，{result.slots_replaced} 槽已写入 output/*.txt（未安装 MSB）"
            )
            return True

        self._log_threadsafe(
            f"正在写入游戏 MSB（{result.slots_replaced} 槽"
            + (f"，仅 {map_filter}" if map_filter else "，全图")
            + "）…"
        )
        apply_span = max(1.0, progress_end - progress_calc_end)

        def on_apply(done: int, total: int, msg: str) -> None:
            if total <= 0:
                pct = progress_calc_end
            else:
                pct = progress_calc_end + apply_span * (done / total)
            self._set_progress(pct, msg)
            sess = self._session_log
            if sess is not None and msg:
                # apply 阶段进度很密；file_every 过大易堵 stdout 管道拖慢 MsbEnemyPoc
                if "仍在进行" in msg:
                    sess.log_progress(
                        "apply", done, max(total, 1), msg, file_every=300
                    )
                else:
                    sess.log_progress(
                        "apply", done, max(total, 1), msg, file_every=200
                    )
            if msg and (
                "模型表" in msg
                or "写入 MSB" in msg
                or "扫描模型" in msg
                or "预读" in msg
            ):
                step = 25 if "仍在进行" in msg else 5
                if done in (0, total) or done % step == 0 or "缓存" in msg or "模型表" in msg:
                    self._log_threadsafe(msg)

        import time

        apply_t0 = time.perf_counter()
        try:
            apply_result = run_enemy_apply(
                apply_spawn_path,
                on_progress=on_apply,
            )
        except Exception as exc:
            self._show_message("error", "敌人安装失败", str(exc))
            self._log(f"敌人 MSB apply 失败: {exc}")
            return False

        self._set_progress(progress_end, "敌人 MSB 写入完成")
        apply_elapsed = time.perf_counter() - apply_t0
        elapsed_note = ""
        if self._session_log is not None:
            elapsed_note = f"（用时 {self._session_log.elapsed():.1f} 秒）"
        if self._session_log is not None:
            self._session_log.log_timing("apply_timing", apply_elapsed)
            self._session_log.section("apply_result")
            self._session_log.line(
                f"maps_written={apply_result.maps_written} "
                f"slots_patched={apply_result.slots_patched} "
                f"missing_slots={apply_result.missing_slots} "
                f"missing_maps={apply_result.missing_maps} "
                f"write_failed={apply_result.maps_write_failed}"
            )
            self._session_log.line(f"overlay_dir={apply_result.overlay_dir}")
        self._log(f"—— 敌人完成{elapsed_note} ——")
        self._log(
            f"已安装 MSB：{apply_result.maps_written} 张地图，"
            f"{apply_result.slots_patched} 槽"
        )
        self._log(f"叠加目录: {apply_result.overlay_dir}")
        if apply_result.missing_slots or apply_result.missing_maps:
            self._log(
                f"跳过：缺槽 {apply_result.missing_slots} · 缺图 {apply_result.missing_maps}"
            )
        if apply_result.maps_write_failed:
            self._log(
                f"写盘失败：{apply_result.maps_write_failed} 张图（见 apply_last_run.txt 的 FAIL 行）"
            )
            for line in apply_result.apply_fail_samples[:5]:
                self._log(line)
        if apply_result.hub_maps_restored:
            self._log(
                f"大赐福安全区已恢复原版 MSB：{len(apply_result.hub_maps_restored)} 张"
            )
        self._log("重启游戏前请确认 me3/convergence.me3 已含 cnv-enemy-poc 包")

        self.enemy_stats_label.configure(
            text=(
                f"已设置类别：{sum(1 for s in ENEMY_CATEGORY_ORDER if weights.get(s))}"
                f"/{len(ENEMY_CATEGORY_ORDER)}    "
                f"上次生成：{apply_result.slots_patched} 槽 / {apply_result.maps_written} 图    "
                f"索引：{DEFAULT_INDEX_PATH.name}"
            )
        )
        extra = ""
        if apply_result.missing_slots or apply_result.missing_maps:
            extra = (
                f"（跳过 {apply_result.missing_slots} 槽"
                f"{f' / {apply_result.missing_maps} 图' if apply_result.missing_maps else ''}）"
            )
        elif apply_result.maps_write_failed:
            sample = ""
            if apply_result.apply_fail_samples:
                sample = f" · {apply_result.apply_fail_samples[0][:120]}"
            extra = (
                f"（⚠ {apply_result.maps_write_failed} 张图写盘失败"
                f"{sample}）"
            )
        elif apply_result.slots_patched < result.slots_replaced * 0.9:
            extra = (
                f"（⚠ 表 {result.slots_replaced} 槽但 MSB 只写入 "
                f"{apply_result.slots_patched} 槽 / {apply_result.maps_written} 图）"
            )
        self._last_enemy_summary = t(
            "enemy_summary",
            seed=seed,
            slots=result.slots_replaced,
            patched=apply_result.slots_patched,
            maps=apply_result.maps_written,
        ) + (extra or "")
        return True


    def _enemy_scan_maps(self) -> bool:
        self._log("—— 扫描地图（敌人索引）——")
        self._log("正在读取 CNV mod MSB，首次全图扫描可能需数分钟…")
        try:
            self.enemy_scan_btn.configure(state="disabled")
        except tk.TclError:
            pass
        self.update_idletasks()
        try:
            index_path = run_index_export()
        except Exception as exc:
            messagebox.showerror(t("enemy_scan_fail"), str(exc))
            self._log(f"扫描失败: {exc}")
            return False
        finally:
            try:
                self.enemy_scan_btn.configure(state="normal")
            except tk.TclError:
                pass

        data = json.loads(index_path.read_text(encoding="utf-8"))
        maps = int(data.get("maps_scanned", 0))
        slots = len(data.get("slots", []))
        templates = len(data.get("templates", []))
        self._log(f"索引已写入: {index_path}")
        self._log(f"地图 {maps} 张 · 槽位 {slots} · 模板 {templates}")
        meta_cat = SCRIPT_DIR / "cache" / "enemy_slot_catalog.meta.json"
        if meta_cat.is_file():
            try:
                cat_meta = json.loads(meta_cat.read_text(encoding="utf-8"))
                self._log(f"槽位全量表: {cat_meta.get('catalog_csv')}")
                summ = cat_meta.get("summary") or {}
                self._log(
                    f"全量表 {summ.get('total')} 行 · 参与随机 {summ.get('participate')} · "
                    f"巡逻 {summ.get('by_placement_kind', {}).get('patrol', 0)}"
                )
            except (OSError, json.JSONDecodeError):
                pass

        build_script = SCRIPT_DIR / "build_enemy_slot_density.py"
        if build_script.is_file():
            self._log("—— 密集槽聚类（离线入库）——")
            try:
                proc = subprocess.run(
                    [sys.executable, str(build_script)],
                    cwd=str(SCRIPT_DIR),
                    capture_output=True,
                )
                out = _decode_subprocess_bytes(proc.stdout).strip()
                err = _decode_subprocess_bytes(proc.stderr).strip()
                if proc.returncode != 0:
                    self._log(f"密集聚类失败 (exit {proc.returncode})")
                    if out:
                        self._log(out)
                    if err:
                        self._log(err)
                elif out:
                    self._log(out)
                meta_path = SCRIPT_DIR / "cache" / "enemy_slot_density.meta.json"
                if meta_path.is_file():
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    self._log(
                        f"密集簇 {meta.get('cluster_count', '?')} · "
                        f"约束槽 {meta.get('constrained_slot_count', '?')}"
                    )
                    try:
                        from enemy_slot_density import clear_density_cache

                        clear_density_cache()
                    except Exception:
                        pass
            except Exception as exc:
                self._log(f"密集聚类异常: {exc}")
        prep_path = SCRIPT_DIR / "cache" / "enemy_slot_prep.json"
        meta_path = SCRIPT_DIR / "cache" / "enemy_slot_prep.meta.json"
        gz_path = SCRIPT_DIR / "cache" / "enemy_slot_prep.json.gz"
        if meta_path.is_file() and gz_path.is_file():
            self._log(
                f"槽位缓存: 已入库（{gz_path.name}）；生成时直读或自动建 .pkl 快载"
            )
        elif prep_path.is_file():
            self._log(f"槽位缓存: 本地 {prep_path.name}（建议维护者 prep 后提交 .gz）")
        else:
            self._log(
                "尚无槽位缓存 — 首次生成将自动构建（约 5 分钟），或 git pull 拿 .gz"
            )
        self.enemy_stats_label.configure(
            text=(
                f"索引：{index_path.name}（{maps} 图 / {slots} 槽）    "
                "上次生成：—"
            )
        )
        return True


    def _reexport_donor_bundle(self) -> None:
        bat = SCRIPT_DIR / "REEXPORT_DONOR.bat"
        if not bat.is_file():
            messagebox.showerror("失败", f"找不到 {bat.name}")
            return
        if not messagebox.askyesno(
            "重建捐皮缓存",
            "将重导 Bundle 三表并重建 enemy_slot_prep（约 1～3 分钟）。\n是否继续？",
        ):
            return
        self.maintainer_reexport_donor_btn.configure(state="disabled")
        self._log("—— 重建捐皮 Bundle + prep ——")
        try:
            proc = subprocess.run(
                [str(bat)],
                cwd=str(SCRIPT_DIR),
                capture_output=True,
                shell=True,
            )
            out = _decode_subprocess_bytes(proc.stdout).strip()
            err = _decode_subprocess_bytes(proc.stderr).strip()
            if out:
                self._log(out)
            if err:
                self._log(err)
            if proc.returncode != 0:
                messagebox.showerror("失败", f"REEXPORT_DONOR 退出码 {proc.returncode}")
            else:
                try:
                    from enemy_slot_prep import clear_slot_prep_cache

                    clear_slot_prep_cache()
                except Exception:
                    pass
                self._log("捐皮 Bundle + prep 重建完成")
        except Exception as exc:
            messagebox.showerror("失败", str(exc))
            self._log(f"重建捐皮缓存异常: {exc}")
        finally:
            self.maintainer_reexport_donor_btn.configure(state="normal")


    def _restore_enemy_overlay(self) -> None:
        enemy_dir = GAME_DIR / "mod" / "cnv_enemy"
        if not enemy_dir.exists():
            messagebox.showinfo(t("notice"), t("enemy_restore_none"))
            return
        if not messagebox.askyesno(
            t("enemy_restore_ask_title"),
            t("enemy_restore_ask"),
        ):
            return
        import shutil

        shutil.rmtree(enemy_dir)
        self._log("已恢复原版怪物")


    def _open_enemy_spoiler(self) -> None:
        spoiler = self._output_dir() / "spoiler_enemies.txt"
        if not spoiler.exists():
            zh = self._output_dir() / "spoiler_enemies_zh.txt"
            if zh.exists():
                spoiler = zh
            else:
                messagebox.showinfo(t("notice"), t("enemy_spoiler_empty"))
                return
        subprocess.Popen(["notepad", str(spoiler)])

