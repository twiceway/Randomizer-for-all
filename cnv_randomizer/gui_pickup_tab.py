#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from cnv_randomizer_core import (
    CAT_GOODS,
    NAME_TO_CAT,
    RegionPanelCache,
    build_region_panel_cache,
    build_unified_pool,
    compute_effective_pools,
    deploy_runtime_map,
    load_config,
    load_item_type_index,
    read_csv,
    run_randomize,
    save_config,
)
from goods_subcats import (
    GOODS_GROUP_ORDER,
    GOODS_GROUP_PRESET_PILLAR,
    GOODS_GROUP_PRESET_SAFE,
    expand_goods_groups,
    load_goods_rows,
    load_goods_subcat_index,
)
from region_tiers import region_display_label

from gui_common import (
    CATEGORY_LABELS,
    CONFIG_PATH,
    EQUIP_GUI_SWITCH_ORDER,
    STRICTNESS_REFRESH_MS,
    STRICTNESS_SAVE_MS,
)
from gui_i18n import t

class PickupTabMixin:
    def _cancel_strictness_timers(self) -> None:
        self._cancel_pending_timers()


    def _invalidate_panel_cache(self) -> None:
        self._panel_cache = None
        self._region_tree_ids = []
        self._region_total_id = None


    def _load_panel_cache(self) -> RegionPanelCache | None:
        try:
            csv_dir = Path(self.cfg["csv_dir"])
            src = csv_dir / f"{self.cfg['target_param']}.csv"
            _, rows = read_csv(src)
            type_index = load_item_type_index(csv_dir)
            snap = self._cfg_snapshot()
            snap["goods_rows"] = load_goods_rows(csv_dir)
            snap["goods_subcat_index"] = load_goods_subcat_index(csv_dir)
            pool = build_unified_pool(rows, snap, type_index)
            return build_region_panel_cache(rows, snap, type_index, pool)
        except OSError:
            return None


    def _render_region_tree(self, effective: dict[str, int]) -> None:
        for item in self.region_tree.get_children():
            self.region_tree.delete(item)

        self._region_tree_ids = []
        total_slots = 0
        total_local = 0
        pool_size = self._panel_cache.pool_size if self._panel_cache else 0

        if self._panel_cache:
            for key, n_slots, n_local in self._panel_cache.rows_data:
                total_slots += n_slots
                total_local += n_local
                label = region_display_label(key)
                if len(label) > 42:
                    label = label[:39] + "…"
                row_id = self.region_tree.insert(
                    "",
                    "end",
                    text=label,
                    values=(
                        str(n_slots),
                        str(n_local),
                        str(effective.get(key, 0)),
                    ),
                )
                self._region_tree_ids.append(row_id)

        strict = float(self.region_strictness_var.get())
        self._region_total_id = self.region_tree.insert(
            "",
            "end",
            text=t("items_total_row", strict=strict),
            values=(str(total_slots), str(total_local), str(pool_size)),
        )
        self.region_count_label.configure(
            text=t("items_region_count", n=len(self._region_tree_ids))
        )


    def _update_effective_column(self, effective: dict[str, int]) -> None:
        if not self._panel_cache or len(self._region_tree_ids) != len(
            self._panel_cache.rows_data
        ):
            self._render_region_tree(effective)
            return

        for row_id, (key, n_slots, n_local) in zip(
            self._region_tree_ids, self._panel_cache.rows_data, strict=True
        ):
            self.region_tree.item(
                row_id,
                values=(str(n_slots), str(n_local), str(effective.get(key, 0))),
            )

        strict = float(self.region_strictness_var.get())
        if self._region_total_id:
            total_slots = sum(slots for _k, slots, _l in self._panel_cache.rows_data)
            total_local = sum(local for _k, _s, local in self._panel_cache.rows_data)
            self.region_tree.item(
                self._region_total_id,
                text=t("items_total_row", strict=strict),
                values=(
                    str(total_slots),
                    str(total_local),
                    str(self._panel_cache.pool_size),
                ),
            )


    def _refresh_region_panel(self) -> None:
        self._cancel_strictness_timers()
        self._panel_cache = self._load_panel_cache()
        if self._panel_cache is None:
            self._invalidate_panel_cache()
            self._render_region_tree({})
            return

        snap = self._cfg_snapshot()
        effective = compute_effective_pools(self._panel_cache, snap)
        self._render_region_tree(effective)


    def _apply_strictness_refresh(self) -> None:
        self._strictness_refresh_after = None
        if self._panel_cache is None:
            self._refresh_region_panel()
            return
        snap = self._cfg_snapshot()
        effective = compute_effective_pools(self._panel_cache, snap)
        self._update_effective_column(effective)


    def _schedule_strictness_refresh(self, *, immediate: bool = False) -> None:
        if self._strictness_refresh_after is not None:
            self.after_cancel(self._strictness_refresh_after)
            self._strictness_refresh_after = None
        if immediate:
            self._apply_strictness_refresh()
        else:
            self._strictness_refresh_after = self.after(
                STRICTNESS_REFRESH_MS, self._apply_strictness_refresh
            )


    def _schedule_strictness_save(self) -> None:
        if self._strictness_save_after is not None:
            self.after_cancel(self._strictness_save_after)
        self._strictness_save_after = self.after(
            STRICTNESS_SAVE_MS, self._save_strictness_session
        )


    def _save_strictness_session(self) -> None:
        self._strictness_save_after = None
        self._schedule_session_save()


    def _bind_mousewheel(self, canvas: tk.Canvas) -> None:
        def on_wheel(event: tk.Event) -> None:
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        def on_enter(_event: tk.Event) -> None:
            canvas.bind_all("<MouseWheel>", on_wheel)

        def on_leave(_event: tk.Event) -> None:
            canvas.unbind_all("<MouseWheel>")

        canvas.bind("<Enter>", on_enter)
        canvas.bind("<Leave>", on_leave)


    def _build_items_tab(self) -> None:
        pad = {"padx": 8, "pady": 4}
        parent = self.tab_items

        strict_frame = ttk.LabelFrame(parent, text=t("items_strict_frame"))
        strict_frame.pack(fill="x", **pad)

        strict_row = ttk.Frame(strict_frame)
        strict_row.pack(fill="x", padx=8, pady=8)
        strict_row.columnconfigure(1, weight=1)
        ttk.Label(strict_row, text=t("items_strict_label")).grid(row=0, column=0, sticky="w")
        self.region_strictness_var = tk.DoubleVar(
            value=float(self.cfg.get("region_strictness", 1.0))
        )
        self.region_strictness_scale = tk.Scale(
            strict_row,
            from_=0.0,
            to=1.0,
            resolution=0.01,
            orient=tk.HORIZONTAL,
            variable=self.region_strictness_var,
            command=self._on_region_strictness_change,
            showvalue=0,
            highlightthickness=0,
            width=16,
            sliderlength=20,
            length=320,
        )
        self.region_strictness_scale.grid(row=0, column=1, sticky="ew", padx=(8, 8))
        self.region_strictness_label = ttk.Label(
            strict_row,
            text=f"{float(self.cfg.get('region_strictness', 1.0)):.2f}",
            width=5,
        )
        self.region_strictness_label.grid(row=0, column=2, sticky="e")
        self.region_strictness_scale.bind(
            "<ButtonRelease-1>", self._on_region_strictness_release
        )

        def on_strict_resize(event: tk.Event) -> None:
            length = max(160, event.width - 130)
            self.region_strictness_scale.configure(length=length)

        strict_row.bind("<Configure>", on_strict_resize)
        strict_hint = ttk.Frame(strict_frame)
        strict_hint.pack(fill="x", padx=8, pady=(0, 6))
        ttk.Label(strict_hint, text=t("items_strict_0")).pack(side="left")
        ttk.Label(strict_hint, text=t("items_strict_1")).pack(side="right")

        body = ttk.Frame(parent)
        body.pack(fill="x", **pad)
        body.columnconfigure(0, weight=3)
        body.columnconfigure(1, weight=2)
        body.rowconfigure(0, weight=1)

        left_outer = ttk.Frame(body)
        left_outer.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        left_outer.rowconfigure(0, weight=1)
        left_outer.columnconfigure(0, weight=1)

        left_canvas = tk.Canvas(left_outer, highlightthickness=0, borderwidth=0)
        left_scroll = ttk.Scrollbar(
            left_outer, orient="vertical", command=left_canvas.yview
        )
        left = ttk.Frame(left_canvas)
        left_window = left_canvas.create_window((0, 0), window=left, anchor="nw")

        def on_left_configure(_event: tk.Event | None = None) -> None:
            left_canvas.configure(scrollregion=left_canvas.bbox("all"))
            left_canvas.itemconfigure(left_window, width=left_canvas.winfo_width())

        left.bind("<Configure>", on_left_configure)
        left_canvas.bind("<Configure>", on_left_configure)
        left_canvas.configure(yscrollcommand=left_scroll.set)
        left_canvas.grid(row=0, column=0, sticky="nsew")
        left_scroll.grid(row=0, column=1, sticky="ns")
        self._bind_mousewheel(left_canvas)

        right = ttk.LabelFrame(body, text=t("items_region_frame"))
        right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)

        tier_wrap = ttk.Frame(right)
        tier_wrap.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        tier_wrap.rowconfigure(0, weight=1)
        tier_wrap.columnconfigure(0, weight=1)

        self.region_tree = ttk.Treeview(
            tier_wrap,
            columns=("slots", "local", "effective"),
            show="tree headings",
            height=14,
            selectmode="none",
        )
        self.region_tree.heading("#0", text=t("items_col_region"), anchor="w")
        self.region_tree.heading("slots", text=t("items_col_slots"))
        self.region_tree.heading("local", text=t("items_col_local"))
        self.region_tree.heading("effective", text=t("items_col_pool"))
        self.region_tree.column("#0", width=200, stretch=True)
        self.region_tree.column("slots", width=58, anchor="e", stretch=False)
        self.region_tree.column("local", width=62, anchor="e", stretch=False)
        self.region_tree.column("effective", width=62, anchor="e", stretch=False)
        region_scroll = ttk.Scrollbar(
            tier_wrap, orient="vertical", command=self.region_tree.yview
        )
        self.region_tree.configure(yscrollcommand=region_scroll.set)
        self.region_tree.grid(row=0, column=0, sticky="nsew")
        region_scroll.grid(row=0, column=1, sticky="ns")

        self.region_count_label = ttk.Label(right, text=t("items_region_count", n=0))
        self.region_count_label.grid(row=1, column=0, sticky="w", padx=8)
        ttk.Label(
            right,
            text=t("items_region_hint"),
            wraplength=320,
            justify="left",
        ).grid(row=2, column=0, sticky="w", padx=8, pady=(0, 8))

        ttk.Button(
            right, text=t("items_refresh"), command=self._refresh_region_panel
        ).grid(row=3, column=0, sticky="w", padx=8, pady=(0, 4))
        ttk.Button(
            right, text=t("items_spoiler"), command=self._open_items_spoiler
        ).grid(row=4, column=0, sticky="w", padx=8, pady=(0, 8))

        mix = ttk.LabelFrame(left, text=t("items_cats_frame"))
        mix.pack(fill="x")
        cats_frame = ttk.Frame(mix)
        cats_frame.pack(fill="x", padx=8, pady=8)

        enabled = self.cfg.get("enabled_cats", set())
        for name in EQUIP_GUI_SWITCH_ORDER:
            var = tk.BooleanVar(
                value=(NAME_TO_CAT[name] in enabled) if enabled else True
            )
            self.cat_vars[name] = var
            ttk.Checkbutton(
                cats_frame,
                text=CATEGORY_LABELS[name],
                variable=var,
                command=self._on_category_change,
            ).pack(anchor="w", pady=2)

        goods_frame = ttk.LabelFrame(
            left,
            text=t("items_goods_frame"),
        )
        goods_frame.pack(fill="x", pady=(8, 0))

        btn_row = ttk.Frame(goods_frame)
        btn_row.pack(fill="x", padx=8, pady=(8, 0))
        ttk.Button(btn_row, text=t("items_select_all"), command=self._goods_select_all).pack(
            side="left", padx=4
        )
        ttk.Button(btn_row, text=t("items_select_none"), command=self._goods_select_none).pack(
            side="left", padx=4
        )
        ttk.Button(btn_row, text=t("items_preset_pillar"), command=self._goods_preset_pillar).pack(
            side="left", padx=4
        )
        ttk.Button(
            btn_row, text=t("items_preset_safe"), command=self._goods_preset_safe
        ).pack(side="left", padx=4)

        groups_frame = ttk.Frame(goods_frame)
        groups_frame.pack(fill="x", padx=8, pady=8)

        enabled_groups = self.cfg.get("enabled_goods_groups", set())
        for group_id in GOODS_GROUP_ORDER:
            if enabled_groups:
                default = group_id in enabled_groups
            else:
                default = group_id in GOODS_GROUP_PRESET_PILLAR or group_id == "important"
            if group_id == "quest":
                default = False
            var = tk.BooleanVar(value=default)
            self.goods_group_vars[group_id] = var
            ttk.Checkbutton(
                groups_frame,
                text=t(f"goods_{group_id}"),
                variable=var,
                command=self._on_category_change,
            ).pack(anchor="w", pady=3)

        opts = ttk.LabelFrame(left, text=t("items_dlc_frame"))
        opts.pack(fill="x", pady=(8, 0))
        opts_row = ttk.Frame(opts)
        opts_row.pack(fill="x", padx=8, pady=8)
        self.include_dlc_var = tk.BooleanVar(value=self.cfg.get("include_dlc", True))
        ttk.Checkbutton(
            opts_row,
            text=t("items_dlc_check"),
            variable=self.include_dlc_var,
            command=self._on_category_change,
        ).pack(anchor="w")


    def _generate_items(self, *, seed: int | None = None) -> bool:
        import time

        try:
            if seed is not None:
                self.cfg["seed"] = seed
            self._sync_config()
            if self._session_log is not None:
                self._session_log.mark_phase("items", "物品随机")
            t0 = time.perf_counter()
            result = run_randomize(self.cfg, deploy=False)
            items_elapsed = time.perf_counter() - t0
        except Exception as exc:
            self._show_message("error", t("items_gen_fail"), str(exc))
            return False

        self._refresh_region_panel()
        self._log(t("log_items"))
        self._log(t("log_seed", seed=result.seed))
        self._log(t("log_lots", n=result.stats.get("lots", 0)))
        self._log(t("log_slots_kept", n=result.slots_kept))
        self._log(t("log_pool", n=result.pool_size))
        self._log(
            t(
                "log_unique",
                covered=result.unique_covered,
                pool=result.unique_pool_size,
            )
        )
        self._log(
            t("log_strict", strict=float(self.cfg.get("region_strictness", 1.0)))
        )
        self._log(t("log_map", path=result.runtime_map_path))
        self.last_runtime_map = Path(result.runtime_map_path)

        try:
            dest = deploy_runtime_map(self.last_runtime_map)
            self._log(t("log_deployed", path=dest))
        except Exception as exc:
            self._show_message("error", t("items_deploy_fail"), str(exc))
            return False
        lots = result.stats.get("lots", 0)
        self._last_items_summary = t(
            "items_summary", seed=result.seed, lots=lots
        )
        if self._session_log is not None:
            self._session_log.log_timing("items_timing", items_elapsed)
            self._session_log.section("items_result")
            self._session_log.line(f"seed={result.seed} lots={lots}")
            self._session_log.line(f"pool_size={result.pool_size}")
            self._session_log.line(f"runtime_map={result.runtime_map_path}")
        return True


    def _open_items_spoiler(self) -> None:
        out = self._output_dir()
        spoilers = sorted(out.glob("spoiler_*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not spoilers:
            messagebox.showinfo(t("notice"), t("items_spoiler_empty"))
            return
        subprocess.Popen(["notepad", str(spoilers[0])])


    def _on_category_change(self) -> None:
        self._invalidate_panel_cache()
        self._refresh_region_panel()
        self._save_session(silent=True)


    def _on_region_strictness_change(self, _value: str = "") -> None:
        raw = _value if _value != "" else self.region_strictness_var.get()
        value = max(0.0, min(1.0, float(raw)))
        self.region_strictness_label.configure(text=f"{value:.2f}")
        if self._region_total_id:
            self.region_tree.item(
                self._region_total_id,
                text=t("items_total_row", strict=value),
            )
        self._schedule_strictness_refresh()
        self._schedule_strictness_save()


    def _on_region_strictness_release(self, _event: tk.Event | None = None) -> None:
        self._schedule_strictness_refresh(immediate=True)
        if self._strictness_save_after is not None:
            self.after_cancel(self._strictness_save_after)
        self._save_strictness_session()


    def _goods_select_all(self) -> None:
        for var in self.goods_group_vars.values():
            var.set(True)
        self._on_category_change()


    def _goods_select_none(self) -> None:
        for var in self.goods_group_vars.values():
            var.set(False)
        self._on_category_change()


    def _goods_preset_pillar(self) -> None:
        for group_id, var in self.goods_group_vars.items():
            var.set(group_id in GOODS_GROUP_PRESET_PILLAR)
        self._on_category_change()


    def _goods_preset_safe(self) -> None:
        for group_id, var in self.goods_group_vars.items():
            var.set(group_id in GOODS_GROUP_PRESET_SAFE)
        self._on_category_change()


    def _generate(self) -> None:
        try:
            self._sync_config()
            result = run_randomize(self.cfg, deploy=False)
        except Exception as exc:
            messagebox.showerror(t("items_gen_fail"), str(exc))
            return

        self._refresh_region_panel()
        self._log(t("log_items"))
        self._log(t("log_seed", seed=result.seed))
        self._log(t("log_lots", n=result.stats.get("lots", 0)))
        self._log(t("log_slots_kept", n=result.slots_kept))
        self._log(t("log_pool", n=result.pool_size))
        self._log(
            t(
                "log_unique",
                covered=result.unique_covered,
                pool=result.unique_pool_size,
            )
        )
        if result.unique_coverage_gaps:
            self._log(
                f"hint: {result.unique_coverage_gaps} uniques not placed"
            )
        self._log(
            f"DLC: {t('yes') if self.cfg.get('include_dlc', True) else t('no')}"
        )
        self._log(
            t("log_strict", strict=float(self.cfg.get("region_strictness", 1.0)))
        )
        for label, n in sorted(result.stats.items()):
            if label == "lots" or not n:
                continue
            self._log(f"  [{label}]: {n}")
        self._log(f"runtime patches: {result.runtime_lot_patches}")
        self._log(t("log_map", path=result.runtime_map_path))
        self.last_runtime_map = result.runtime_map_path


    def _deploy(self) -> None:
        map_path = getattr(self, "last_runtime_map", None)
        if map_path is None or not Path(map_path).exists():
            out = self._output_dir() / "cnv_runtime_map.txt"
            if out.exists():
                map_path = out
            else:
                messagebox.showwarning(t("notice"), t("items_need_gen"))
                return
        try:
            dest = deploy_runtime_map(Path(map_path))
        except Exception as exc:
            messagebox.showerror(t("items_deploy_fail"), str(exc))
            return
        self._log(t("log_deployed", path=dest))
        messagebox.showinfo(
            t("items_deploy_done_title"),
            t("items_deploy_done", path=dest),
        )

