#!/usr/bin/env python3
"""关卡前方 · F6 标定 14+3 槽试验台 GUI（默认：飞行皮 17 行写盘）。"""

from __future__ import annotations

import contextlib
import io
import subprocess
import sys
import threading
import traceback
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, scrolledtext, ttk

from paths import SCRIPT_DIR  # frozen-safe
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from gatefront_fly_catalog import (  # noqa: E402
    FLY_BATCH_SIZE,
    FLY_BATCHES_CACHE,
    FLY_TABLE_PATH,
    build_fly_lineup_batches,
)
from gatefront_test_lab import (  # noqa: E402
    BASELINE_DIR,
    DEFAULT_CONFIG,
    DEFAULT_SEED,
    OUT_DIR,
    cmd_fly_table,
    cmd_init,
    run_apply_fly,
)


class GatefrontQuadLabGui(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("关卡前方 · 14+3 槽试验台（飞行）")
        self.geometry("920x680")
        self.minsize(760, 520)

        self._worker: threading.Thread | None = None
        self._total_batches = 1
        self._total_flyers = 0
        self._batch_row_count = 0

        self.batch_var = tk.IntVar(value=1)
        self.seed_var = tk.StringVar(value=str(DEFAULT_SEED))
        self.skip_apply_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="就绪")

        self._build_ui()
        self._reload_batches()

    def _build_ui(self) -> None:
        top = ttk.Frame(self, padding=10)
        top.pack(fill=tk.X)

        ttk.Label(top, text="种子").grid(row=0, column=0, sticky=tk.W, padx=(0, 6))
        ttk.Entry(top, textvariable=self.seed_var, width=14).grid(
            row=0, column=1, sticky=tk.W
        )
        ttk.Label(top, text="（仅文件名用；全图固定原版士兵，不随机）", foreground="#666").grid(
            row=0, column=2, columnspan=4, sticky=tk.W, padx=(8, 0)
        )

        ttk.Label(top, text="组").grid(row=1, column=0, sticky=tk.W, pady=(8, 0))
        self.batch_spin = ttk.Spinbox(
            top,
            from_=1,
            to=1,
            textvariable=self.batch_var,
            width=6,
            command=self._on_batch_change,
        )
        self.batch_spin.grid(row=1, column=1, sticky=tk.W, pady=(8, 0))
        self.batch_hint = ttk.Label(top, text="/ 1 组")
        self.batch_hint.grid(row=1, column=2, columnspan=3, sticky=tk.W, padx=(4, 0), pady=(8, 0))
        ttk.Label(
            top,
            text=f"note2～15 + 3 蝙蝠巡逻 · 共 {FLY_BATCH_SIZE} 张白名单飞行皮",
            foreground="#666",
        ).grid(row=1, column=5, sticky=tk.W, padx=(8, 0), pady=(8, 0))

        btns = ttk.Frame(self, padding=(10, 0, 10, 6))
        btns.pack(fill=tk.X)

        self.btn_one_click = ttk.Button(
            btns,
            text="▶ 一键写盘并部署",
            command=self._on_one_click,
        )
        self.btn_one_click.pack(side=tk.LEFT, padx=(0, 16))

        ttk.Label(btns, text="分步：", foreground="#666").pack(side=tk.LEFT, padx=(0, 4))
        self.btn_init = ttk.Button(btns, text="① 士兵基线 (~3s)", command=self._on_init)
        self.btn_init.pack(side=tk.LEFT, padx=(0, 4))
        self.btn_table = ttk.Button(btns, text="② 飞行表", command=self._on_fly_table)
        self.btn_table.pack(side=tk.LEFT, padx=(0, 4))
        self.btn_apply = ttk.Button(
            btns,
            text="③ 写盘",
            command=self._on_apply,
        )
        self.btn_apply.pack(side=tk.LEFT, padx=(0, 12))
        ttk.Checkbutton(btns, text="只生成 txt（不写 MSB）", variable=self.skip_apply_var).pack(
            side=tk.LEFT
        )

        aux = ttk.Frame(self, padding=(10, 0, 10, 6))
        aux.pack(fill=tk.X)
        ttk.Button(aux, text="打开分批表", command=self._open_table).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(aux, text="打开对照单", command=self._open_legend).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(aux, text="打开输出目录", command=self._open_out_dir).pack(side=tk.LEFT)

        mid = ttk.LabelFrame(self, padding=8)
        mid.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 6))
        self.preview_frame = mid
        self._set_preview_title(0)

        cols = ("note", "write_slot", "npc", "english")
        self.tree = ttk.Treeview(mid, columns=cols, show="headings", height=18)
        self.tree.heading("note", text="note")
        self.tree.heading("write_slot", text="写盘槽")
        self.tree.heading("npc", text="npc")
        self.tree.heading("english", text="飞行皮")
        self.tree.column("note", width=48, anchor=tk.CENTER)
        self.tree.column("write_slot", width=120)
        self.tree.column("npc", width=90, anchor=tk.E)
        self.tree.column("english", width=280)
        scroll = ttk.Scrollbar(mid, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        log_frame = ttk.LabelFrame(self, text="日志", padding=8)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 6))
        self.log = scrolledtext.ScrolledText(
            log_frame, height=10, state=tk.DISABLED, font=("Consolas", 9)
        )
        self.log.pack(fill=tk.BOTH, expand=True)

        status = ttk.Frame(self, padding=(10, 0, 10, 8))
        status.pack(fill=tk.X)
        ttk.Label(status, textvariable=self.status_var).pack(side=tk.LEFT)

        self.batch_var.trace_add("write", lambda *_: self._on_batch_change())

    def _set_preview_title(self, row_count: int) -> None:
        self.preview_frame.configure(
            text=(
                f"本组预览（{row_count} 行 · note2～15 + 蝙蝠巡逻 · 满额 {FLY_BATCH_SIZE}）"
            )
        )

    def _log(self, text: str) -> None:
        self.log.configure(state=tk.NORMAL)
        self.log.insert(tk.END, text)
        if not text.endswith("\n"):
            self.log.insert(tk.END, "\n")
        self.log.see(tk.END)
        self.log.configure(state=tk.DISABLED)

    def _baseline_path(self, seed: int | None = None) -> Path:
        seed = seed if seed is not None else self._parse_seed()
        return BASELINE_DIR / ".apply_staging" / f"cnv_enemy_spawn_map_{seed}.txt"

    def _set_busy(self, busy: bool, status: str = "") -> None:
        state = tk.DISABLED if busy else tk.NORMAL
        for w in (self.btn_one_click, self.btn_init, self.btn_table, self.btn_apply):
            w.configure(state=state)
        if status:
            self.status_var.set(status)

    def _reload_batches(self) -> None:
        try:
            if FLY_BATCHES_CACHE.is_file():
                payload = build_fly_lineup_batches()
            else:
                payload = build_fly_lineup_batches(refresh=True)
            self._total_batches = max(1, int(payload.get("total_batches") or 1))
            self._total_flyers = int(payload.get("total_flying") or 0)
        except Exception as exc:
            self._total_batches = 1
            self._total_flyers = 0
            self._log(f"[warn] 无法加载飞行分批表: {exc}")
        self.batch_spin.configure(to=self._total_batches)
        fly_note = f"{self._total_flyers} 种飞行捐皮" if self._total_flyers else "飞行捐皮"
        self.batch_hint.configure(
            text=f"/ {self._total_batches} 组 · 共 {fly_note}（不足 {FLY_BATCH_SIZE} 则循环）"
        )
        self._refresh_preview()

    def _current_batch(self) -> int:
        try:
            batch = int(self.batch_var.get())
        except (tk.TclError, ValueError):
            batch = 1
        return max(1, min(batch, self._total_batches))

    def _on_batch_change(self) -> None:
        if threading.current_thread() is threading.main_thread():
            self._refresh_preview()
        else:
            self.after(0, self._refresh_preview)

    def _refresh_preview(self) -> None:
        batch = self._current_batch()
        for item in self.tree.get_children():
            self.tree.delete(item)
        if not FLY_BATCHES_CACHE.is_file():
            return
        try:
            payload = build_fly_lineup_batches()
            batch_data = next(
                (b for b in payload.get("batches") or [] if int(b.get("batch") or 0) == batch),
                None,
            )
            if not batch_data:
                self._batch_row_count = 0
                self._set_preview_title(0)
                return
            rows = list(batch_data.get("rows") or [])
            self._batch_row_count = len(rows)
            self._set_preview_title(self._batch_row_count)
            for row in rows:
                cycle = int(row.get("donor_cycle") or 0)
                name = str(row.get("english") or row.get("model") or "")
                if cycle:
                    name = f"{name} ×{cycle + 1}"
                self.tree.insert(
                    "",
                    tk.END,
                    values=(
                        row.get("note"),
                        row.get("mark_slot") or row.get("test_slot"),
                        row.get("npc"),
                        name,
                    ),
                )
        except Exception as exc:
            self._log(f"[warn] 预览刷新失败: {exc}")

    def _run_worker(self, title: str, fn, *, on_success=None) -> None:
        if self._worker and self._worker.is_alive():
            messagebox.showwarning("提示", "上一项任务还在跑，请稍候…")
            return

        def worker() -> None:
            buf = io.StringIO()
            code = 1
            try:
                with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                    code = int(fn())
            except Exception as exc:
                buf.write(f"\nERROR: {exc}\n")
                buf.write(traceback.format_exc())
            text = buf.getvalue()

            def done() -> None:
                self._set_busy(False, "就绪" if code == 0 else "失败")
                if text.strip():
                    self._log(text.rstrip())
                if code == 0:
                    self._log(f"===== {title} 完成 =====")
                    if on_success:
                        on_success()
                    self._refresh_preview()
                else:
                    self._log(f"===== {title} 失败 (exit={code}) =====")
                    messagebox.showerror("失败", f"{title} 未成功，请看日志。")

            self.after(0, done)

        self._set_busy(True, f"{title}…")
        self._log(f"===== {title} =====")
        self._worker = threading.Thread(target=worker, daemon=True)
        self._worker.start()

    def _parse_seed(self) -> int:
        try:
            return int(self.seed_var.get().strip())
        except ValueError:
            return DEFAULT_SEED

    def _on_init(self) -> None:
        if not messagebox.askyesno(
            "生成基线",
            f"将生成关卡前方单图基线（约 7 秒）\n种子 {self._parse_seed()}\n\n继续？",
        ):
            return
        seed = self._parse_seed()
        self._run_worker("生成基线", lambda: cmd_init(seed))

    def _on_fly_table(self) -> None:
        self._run_worker(
            "刷新飞行表",
            lambda: cmd_fly_table(refresh=True),
            on_success=self._reload_batches,
        )

    def _on_apply(self, *, confirm: bool = True) -> None:
        batch = self._current_batch()
        if not self._baseline_path().is_file():
            messagebox.showwarning(
                "缺少基线",
                "还没生成基线。\n请点「一键写盘」或「① 基线」。",
            )
            return
        skip = bool(self.skip_apply_var.get())
        action = "只生成 txt" if skip else "写盘并部署到游戏"
        if confirm and not messagebox.askyesno(
            "写盘",
            f"组 {batch}/{self._total_batches} · {self._batch_row_count} 条飞行皮 → 17 槽\n"
            f"{action}\n\n写盘后请完全退出游戏再重进。\n\n继续？",
        ):
            return
        seed = self._parse_seed()

        def job() -> int:
            return run_apply_fly(
                batch,
                seed=seed,
                config=DEFAULT_CONFIG,
                skip_apply=skip,
            )

        self._run_worker(f"写盘 组{batch}", job)

    def _on_one_click(self) -> None:
        batch = self._current_batch()
        seed = self._parse_seed()
        skip = bool(self.skip_apply_var.get())
        need_init = not self._baseline_path(seed).is_file()
        action = "只生成 txt" if skip else "写进游戏"
        steps = []
        if need_init:
            steps.append("① 生成士兵基线（约 3 秒）")
        steps.append("② 刷新飞行表")
        steps.append(f"③ 组 {batch} 写盘 17 飞行皮（{action}）")
        if not messagebox.askyesno(
            "一键写盘",
            "将自动执行：\n"
            + "\n".join(steps)
            + "\n\n写盘后请完全退出游戏再重进。\n\n继续？",
        ):
            return

        def pipeline() -> int:
            if need_init:
                rc = cmd_init(seed)
                if rc != 0:
                    return rc
            rc = cmd_fly_table(refresh=True)
            if rc != 0:
                return rc
            return run_apply_fly(
                batch,
                seed=seed,
                config=DEFAULT_CONFIG,
                skip_apply=skip,
            )

        self._run_worker(
            f"一键写盘 组{batch}",
            pipeline,
            on_success=self._reload_batches,
        )

    def _open_table(self) -> None:
        if not FLY_TABLE_PATH.is_file():
            messagebox.showinfo("提示", "分批表还不存在，请先点「刷新飞行表」。")
            return
        subprocess.Popen(["notepad", str(FLY_TABLE_PATH)])

    def _open_legend(self) -> None:
        batch = self._current_batch()
        path = OUT_DIR / f"gatefront_fly_legend_b{batch}.txt"
        if not path.is_file():
            messagebox.showinfo("提示", "对照单还不存在，请先写盘一次。")
            return
        subprocess.Popen(["notepad", str(path)])

    def _open_out_dir(self) -> None:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(["explorer", str(OUT_DIR)])


def main() -> int:
    app = GatefrontQuadLabGui()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
