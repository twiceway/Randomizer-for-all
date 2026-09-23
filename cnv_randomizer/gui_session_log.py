"""GUI 生成会话日志 — 写入 output/logs/，供排错时直接 Read，无需重跑全图生成。"""

from __future__ import annotations

import json
import threading
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from paths import OUTPUT_DIR, SCRIPT_DIR, ensure_output_dirs

LOG_DIR = OUTPUT_DIR / "logs"
LATEST_LOG = LOG_DIR / "gui_run_latest.log"


class GuiSessionLog:
    """线程安全；一次「生成随机」或「测试生成」对应一个带时间戳的 log 文件。"""

    def __init__(self, *, kind: str, seed: int) -> None:
        ensure_output_dirs()
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.path = LOG_DIR / f"gui_run_{stamp}.log"
        self.kind = kind
        self.seed = seed
        self._lock = threading.Lock()
        self._t0 = time.perf_counter()
        self._phase_t0 = self._t0
        self._last_phase = ""
        self._progress_last: dict[str, tuple[int, float]] = {}
        self._write_header()

    @property
    def latest_path(self) -> Path:
        return LATEST_LOG

    def _write_header(self) -> None:
        lines = [
            "# CNV GUI session log",
            f"started={datetime.now().isoformat(timespec='seconds')}",
            f"kind={self.kind}",
            f"seed={self.seed}",
            f"file={self.path}",
            "",
        ]
        text = "\n".join(lines) + "\n"
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(text, encoding="utf-8")
            LATEST_LOG.write_text(text, encoding="utf-8")

    def _append_lines(self, lines: list[str]) -> None:
        text = "\n".join(lines) + "\n"
        with self._lock:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(text)
            with LATEST_LOG.open("a", encoding="utf-8") as fh:
                fh.write(text)

    def elapsed(self) -> float:
        return time.perf_counter() - self._t0

    def _ts(self) -> str:
        return f"+{self.elapsed():6.1f}s"

    def line(self, text: str) -> None:
        self._append_lines([f"[{self._ts()}] {text.rstrip()}"])

    def section(self, title: str) -> None:
        self._append_lines(["", f"## {title}", ""])

    def mark_phase(self, phase: str, msg: str = "") -> None:
        now = time.perf_counter()
        if self._last_phase:
            self.line(
                f"phase_end {self._last_phase} "
                f"duration={now - self._phase_t0:.1f}s"
            )
        self._last_phase = phase
        self._phase_t0 = now
        if msg:
            self.line(f"phase_start {phase} | {msg}")
        else:
            self.line(f"phase_start {phase}")

    def log_progress(
        self,
        phase: str,
        done: int,
        total: int,
        msg: str,
        *,
        file_every: int = 250,
    ) -> None:
        """文件日志比窗口日志更密；scan/pick 按 file_every 记一条。"""
        if phase != self._last_phase:
            self.mark_phase(phase, msg)
        if total <= 0:
            self.line(msg)
            return
        if done in (0, total) or done % file_every == 0:
            prev_done, prev_t = self._progress_last.get(phase, (-1, self._t0))
            dt = time.perf_counter() - prev_t if done > prev_done else 0.0
            dd = done - prev_done if done > prev_done else done
            rate = f" {dd / dt:.0f}/s" if dt > 0.05 and dd > 0 else ""
            self.line(f"{msg} [{phase}]{rate}")
            self._progress_last[phase] = (done, time.perf_counter())

    def log_config_snapshot(self, cfg: dict[str, Any]) -> None:
        self.section("config_snapshot")
        enemy_gui = cfg.get("enemy_gui") or {}
        snap = {
            "seed": cfg.get("seed"),
            "shuffle_mode": cfg.get("shuffle_mode"),
            "enemy_gui": {
                k: enemy_gui.get(k)
                for k in (
                    "category_weights",
                    "mob_drop_mode",
                    "dlc_pool_mode",
                    "page_enemies_enabled",
                )
                if k in enemy_gui
            },
            "donor_archetype_weights": (cfg.get("enemy_categories") or {}).get(
                "donor_archetype_weights"
            ),
        }
        cats_path = SCRIPT_DIR / "enemy_categories.json"
        if cats_path.is_file():
            try:
                cats = json.loads(cats_path.read_text(encoding="utf-8-sig"))
                snap["donor_archetype_weights"] = cats.get("donor_archetype_weights")
                snap["dlc_trash_pick_multiplier"] = cats.get("dlc_trash_pick_multiplier")
            except (OSError, json.JSONDecodeError):
                pass
        self.line(json.dumps(snap, ensure_ascii=False, indent=2))

    def log_warnings(self, warnings: list[str], *, title: str = "warnings") -> None:
        if not warnings:
            return
        self.section(title)
        for w in warnings:
            self.line(f"WARN {w}")

    def log_timing(self, name: str, seconds: float) -> None:
        self.line(f"{name}={seconds:.1f}s")

    def finish(self, *, ok: bool, summary: str = "") -> Path:
        if self._last_phase:
            self.line(
                f"phase_end {self._last_phase} "
                f"duration={time.perf_counter() - self._phase_t0:.1f}s"
            )
        self.section("session_end")
        total = self.elapsed()
        self.line(f"ok={ok} total_elapsed={total:.1f}s")
        self.line(f"用时 {total:.1f} 秒")
        if summary:
            self.line(summary)
        self.line(f"latest_copy={LATEST_LOG}")
        return self.path


def summarize_enemy_spawn_map(spawn_map_path: Path) -> list[str]:
    """从已有 spawn_map 提取诊断行（不重跑 generate）。"""
    if not spawn_map_path.is_file():
        return [f"spawn_map missing: {spawn_map_path}"]

    from enemy_randomizer_core import DEFAULT_CATEGORIES_PATH, _load_json, load_archetype_index

    arch = load_archetype_index(_load_json(DEFAULT_CATEGORIES_PATH))
    tgt = Counter()
    models = Counter()
    arch_out = Counter()
    for line in spawn_map_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or "\t" not in line:
            continue
        parts = line.split("\t")
        if len(parts) < 6:
            continue
        tgt[parts[3]] += 1
        model = parts[5].lower()
        models[model] += 1
        a = arch.trash_archetype_for_model(model)
        if a:
            arch_out[a] += 1

    total = sum(models.values())
    if total == 0:
        return ["spawn_map empty"]

    lines = [
        f"spawn_map={spawn_map_path}",
        f"assignments={total}",
        f"tgt_cat={dict(tgt.most_common())}",
        f"archetype_output={dict(arch_out.most_common(12))}",
        f"top_models={models.most_common(15)}",
        f"soldier_archetype_pct={100 * arch_out.get('soldier', 0) / total:.1f}%",
    ]
    classic = sum(
        c
        for m, c in models.items()
        if m.startswith("c431") or m.startswith("c437") or m == "c4300"
    )
    lines.append(f"classic_soldier_model_pct={100 * classic / total:.1f}%")
    return lines


def append_enemy_result_diagnostics(log: GuiSessionLog, result: Any) -> None:
    log.section("enemy_result")
    log.line(f"slots_total={result.slots_total}")
    log.line(f"slots_replaced={result.slots_replaced}")
    log.line(f"slots_skipped={result.slots_skipped}")
    log.line(f"skipped_large={result.slots_skipped_large}")
    log.line(f"skipped_passive_animal={result.slots_skipped_passive_animal}")
    log.line(f"skipped_npc={result.slots_skipped_npc_slot}")
    log.line(f"skipped_scarab={result.slots_skipped_scarab}")
    log.line(
        f"skipped_dense_keep={getattr(result, 'slots_skipped_dense_keep', 0)}"
    )
    log.line(f"dlc_donor_hits={result.dlc_donor_hits}")
    log.line(f"archetypes_hit={result.archetypes_hit}")
    log.line(f"models_hit={result.models_hit}")
    log.line(f"spawn_map={result.spawn_map_path}")
    if result.risk_report_path:
        log.line(f"risk_report={result.risk_report_path}")
    log.log_warnings(list(result.warnings or []))
    log.section("spawn_map_diagnostics")
    for line in summarize_enemy_spawn_map(Path(result.spawn_map_path)):
        log.line(line)
