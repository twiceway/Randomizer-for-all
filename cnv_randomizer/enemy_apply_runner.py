"""T-073R R3.3 — MSB apply runner (spawn bundle → MsbEnemyPoc apply-map)."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from enemy_spawn_bundle import (
    resolve_spawn_map_sidecar_paths,
    validate_spawn_bundle,
)
from paths import GAME_DIR, OUTPUT_RUNTIME, subprocess_no_window_kwargs


@dataclass
class EnemyApplyResult:
    spawn_map_path: Path
    maps_written: int
    slots_patched: int
    missing_slots: int
    missing_maps: int
    overlay_dir: Path
    maps_write_failed: int = 0
    manifest_path: Path | None = None
    hub_maps_restored: list[str] = field(default_factory=list)
    apply_fail_samples: list[str] = field(default_factory=list)


def _parse_apply_summary(stdout: str) -> tuple[int, int, int, int, int, list[str]]:
    maps_written = slots_patched = missing_slots = missing_maps = maps_write_failed = 0
    fail_samples: list[str] = []
    for line in stdout.splitlines():
        if line.strip().startswith("FAIL "):
            fail_samples.append(line.strip())
            continue
        if "apply-map done:" not in line:
            continue
        for token in line.split():
            if token.startswith("maps_written="):
                maps_written = int(token.split("=", 1)[1])
            elif token.startswith("slots_patched="):
                slots_patched = int(token.split("=", 1)[1])
            elif token.startswith("missing_slots="):
                missing_slots = int(token.split("=", 1)[1])
            elif token.startswith("missing_maps="):
                missing_maps = int(token.split("=", 1)[1])
            elif token.startswith("write_failed="):
                maps_write_failed = int(token.split("=", 1)[1])
    return maps_written, slots_patched, missing_slots, missing_maps, maps_write_failed, fail_samples


def _count_spawn_map_maps(spawn_map_path: Path, map_filter: str | None = None) -> int:
    if map_filter:
        return 1
    maps: set[str] = set()
    for line in spawn_map_path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        if line.startswith("seed=") or line.startswith("mob_drop") or line.startswith("slots="):
            continue
        parts = line.split("\t") if "\t" in line else line.split()
        if parts:
            maps.add(parts[0])
    return len(maps)


def prune_stale_overlay_msbs(
    *,
    map_filter: str | None = None,
) -> int:
    """全图 apply 前删除旧种子残留的 MSB 叠加（避免 npc 与 regulation 不一致 / 0 字节坏文件）。"""
    if map_filter:
        return 0
    overlay_dir = GAME_DIR / "mod" / "cnv_enemy" / "map" / "MapStudio"
    if not overlay_dir.is_dir():
        return 0
    removed = 0
    for pattern in ("*.msb.dcx", "*.msbe.dcx", "cnv_enemy_apply_slots_*.txt"):
        for path in overlay_dir.glob(pattern):
            try:
                path.unlink(missing_ok=True)
                removed += 1
            except OSError:
                continue
    return removed


def run_enemy_apply(
    spawn_map_path: Path | None = None,
    *,
    map_filter: str | None = None,
    on_progress: Any | None = None,
    parallel: int | None = None,
    quiet: bool = True,
) -> EnemyApplyResult:
    from enemy_randomizer_core import (
        DEFAULT_CATEGORIES_PATH,
        _ensure_msb_poc_built,
        _enemy_gui_perf,
        _load_json,
        resolve_enemy_apply_map_inflight,
        resolve_enemy_apply_max_parallel,
        resolve_enemy_apply_parallel,
        restore_hub_map_overlays,
    )

    spawn_map_path = Path(spawn_map_path or (OUTPUT_RUNTIME / "cnv_enemy_spawn_map.txt"))
    if not spawn_map_path.is_file():
        raise FileNotFoundError(f"缺少 spawn map：{spawn_map_path}")

    from enemy_randomizer_core import augment_spawn_map_path_with_decorative_suppress

    apply_spawn_map_path = augment_spawn_map_path_with_decorative_suppress(
        spawn_map_path,
        map_filter=map_filter,
    )

    validate_spawn_bundle(spawn_map_path)
    sidecars = resolve_spawn_map_sidecar_paths(spawn_map_path)
    copies_json = sidecars["copies"]
    if copies_json.is_file():
        from npc_soul_copies import (
            ensure_radahn_phase1_assets,
            patch_regulation_npc_copies,
            regulation_patch_unchanged,
        )

        ensure_radahn_phase1_assets()
        if regulation_patch_unchanged(copies_json):
            if on_progress:
                on_progress(0, 1, "T-052：regulation 已是最新，跳过重复写入…")
        else:
            if on_progress:
                on_progress(0, 1, "T-052：写入 NpcParam 复制行到 regulation…")
            patch_regulation_npc_copies(copies_json)
    else:
        from npc_soul_copies import ensure_radahn_phase1_assets

        ensure_radahn_phase1_assets()

    pruned = prune_stale_overlay_msbs(map_filter=map_filter)
    if pruned and on_progress:
        on_progress(0, 1, f"已清理旧 MSB 叠加 {pruned} 个文件…")

    exe = _ensure_msb_poc_built()
    perf = _enemy_gui_perf()
    if parallel is None:
        parallel = resolve_enemy_apply_parallel(
            perf.get("apply_parallel"),
            perf.get("apply_io_multiplier"),
        )
    parallel = max(1, parallel)
    max_parallel = resolve_enemy_apply_max_parallel(perf.get("apply_max_parallel"))
    map_inflight = resolve_enemy_apply_map_inflight(perf.get("apply_map_inflight"))
    dynamic_parallel = bool(perf.get("apply_dynamic_parallel", False))
    cmd = [
        str(exe),
        "apply-map",
        f"--spawn-map={apply_spawn_map_path}",
        f"--game={GAME_DIR}",
        f"--parallel={parallel}",
        f"--max-parallel={max_parallel}",
        f"--map-inflight={map_inflight}",
    ]
    if dynamic_parallel:
        cmd.append("--dynamic-parallel")
    if quiet:
        cmd.append("--quiet")
    if map_filter:
        cmd.append(f"--map-filter={map_filter}")

    est_maps = _count_spawn_map_maps(apply_spawn_map_path, map_filter)
    if on_progress:
        on_progress(0, est_maps, f"开始写入 MSB（共约 {est_maps} 张地图）…")

    reg_progress_re = re.compile(r"registry_progress (\d+)/(\d+)")
    map_progress_re = re.compile(r"map_progress (\d+)/(\d+)")
    prefetch_progress_re = re.compile(r"prefetch_progress (\d+)/(\d+)")
    dynamic_scale_re = re.compile(
        r"dynamic_scale workers=(\d+)->(\d+) cpu_util=([0-9.]+%) queue=(\d+)"
    )
    map_heartbeat_re = re.compile(r"map_heartbeat done=(\d+)/(\d+)")

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        **subprocess_no_window_kwargs(),
    )
    stdout_lines: list[str] = []
    maps_done = 0
    assert proc.stdout is not None
    for line in proc.stdout:
        stdout_lines.append(line)
        reg_match = reg_progress_re.search(line)
        if reg_match and on_progress:
            on_progress(
                0,
                est_maps,
                f"扫描模型表 {reg_match.group(1)}/{reg_match.group(2)}…",
            )
            continue
        prefetch_match = prefetch_progress_re.search(line)
        if prefetch_match and on_progress:
            on_progress(
                0,
                est_maps,
                f"预读地图 {prefetch_match.group(1)}/{prefetch_match.group(2)}…",
            )
            continue
        if "prefetch done ram_maps=" in line and on_progress:
            on_progress(0, est_maps, "预读完成，开始并行写入…")
        elif "cache_warm done" in line and on_progress:
            on_progress(0, est_maps, "缓存预热完成，开始并行写入…")
        map_match = map_progress_re.search(line)
        if map_match and on_progress:
            done_maps = int(map_match.group(1))
            on_progress(done_maps, est_maps, f"写入 MSB {done_maps}/{est_maps} 张地图…")
            continue
        hb_match = map_heartbeat_re.search(line)
        if hb_match and on_progress:
            done_maps = int(hb_match.group(1))
            on_progress(
                done_maps,
                est_maps,
                f"写入 MSB {done_maps}/{est_maps} 张地图（仍在进行）…",
            )
            continue
        dyn_match = dynamic_scale_re.search(line)
        if dyn_match and on_progress:
            on_progress(
                maps_done,
                est_maps,
                f"动态加线程 {dyn_match.group(1)}→{dyn_match.group(2)} "
                f"CPU {dyn_match.group(3)} 待写 {dyn_match.group(4)}",
            )
            continue
        if "model registry cache hit" in line and on_progress:
            on_progress(0, est_maps, "模型表缓存命中，开始写地图…")
        elif "model registry=" in line and on_progress:
            on_progress(0, est_maps, "模型表就绪，写入地图…")
        elif "msb_source_cache hits=" in line and on_progress:
            on_progress(maps_done, est_maps, line.strip())
        if ": patched " in line:
            maps_done += 1
            if on_progress:
                on_progress(maps_done, est_maps, f"写入 MSB {maps_done}/{est_maps} 张地图…")
    proc.wait()
    combined = "".join(stdout_lines)
    fail_log = OUTPUT_RUNTIME / "apply_last_run.txt"
    try:
        fail_log.write_text(combined, encoding="utf-8")
    except Exception:
        pass
    if proc.returncode != 0:
        tail = "\n".join(combined.strip().splitlines()[-40:])
        raise RuntimeError(
            "apply-map failed:\n"
            + tail
            + f"\n\n（完整日志已写入 {fail_log}）"
        )

    if on_progress:
        on_progress(est_maps, est_maps, "MSB 写入完成")

    overlay_dir = GAME_DIR / "mod" / "cnv_enemy" / "map" / "MapStudio"
    landing_manifest = overlay_dir / "cnv_radahn_landing.json"
    landing_records: list[dict[str, Any]] = []
    try:
        from radahn_landing_inject import (
            inject_radahn_landing_events,
            load_landing_manifest,
            summarize_injection,
        )

        if on_progress:
            on_progress(est_maps, est_maps, "碎星落地：写入事件脚本…")
        injected_paths = inject_radahn_landing_events(
            landing_manifest,
            map_filter=map_filter,
        )
        landing_records = load_landing_manifest(landing_manifest)
        if map_filter:
            landing_records = [
                r for r in landing_records if str(r.get("map_id")) == map_filter
            ]
        landing_summary = summarize_injection(injected_paths, landing_records)
        stdout_lines.append(landing_summary + "\n")
        if on_progress:
            on_progress(est_maps, est_maps, landing_summary)
    except Exception as exc:
        landing_summary = f"radahn_landing_inject: FAILED {exc}"
        stdout_lines.append(landing_summary + "\n")
        if on_progress:
            on_progress(est_maps, est_maps, landing_summary)

    combined = "".join(stdout_lines)
    try:
        fail_log.write_text(combined, encoding="utf-8")
    except Exception:
        pass

    (
        maps_written,
        slots_patched,
        missing_slots,
        missing_maps,
        maps_write_failed,
        apply_fail_samples,
    ) = _parse_apply_summary(combined)
    manifest = overlay_dir / "cnv_enemy_apply_manifest.txt"
    categories_cfg = _load_json(DEFAULT_CATEGORIES_PATH)
    hub_restored = restore_hub_map_overlays(categories_cfg)
    if hub_restored and on_progress:
        on_progress(
            est_maps,
            est_maps,
            f"已恢复安全区原版 MSB：{len(hub_restored)} 张",
        )
    return EnemyApplyResult(
        spawn_map_path=spawn_map_path,
        maps_written=maps_written,
        slots_patched=slots_patched,
        missing_slots=missing_slots,
        missing_maps=missing_maps,
        overlay_dir=overlay_dir,
        maps_write_failed=maps_write_failed,
        manifest_path=manifest if manifest.is_file() else None,
        hub_maps_restored=hub_restored,
        apply_fail_samples=apply_fail_samples,
    )
