#!/usr/bin/env python3
"""T-093 Phase4：出表验收（不 apply）。"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from enemy_difficulty import (  # noqa: E402
    compute_assignment_patch,
    load_difficulty_cfg,
    resolve_t093_target_effective_hp,
)
from enemy_whitelist_hp import (  # noqa: E402
    load_whitelist_effective_hp_index,
    whitelist_effective_hp_for_model,
)
from enemy_world_progression import (  # noqa: E402
    compute_slider_lift_mult,
    is_underground_map,
    load_map_regions,
    night_mult_for_row,
    resolve_map_mult_t093,
    resolve_map_tier_t093,
    t093_config,
)
from paths import OUTPUT_REPORTS  # noqa: E402

GATEFRONT = "m60_42_36_00"
OUT_MD = OUTPUT_REPORTS / "T-093_出表验收.md"


def _stub_donor(npc: int = 30600000) -> dict[str, str]:
    return {
        "ID": str(npc),
        "hp": "705",
        "defFlickPower": "30",
        "spEffectID0": "7010",
        "spEffectID1": "0",
        "spEffectID2": "0",
    }


def main() -> int:
    load_map_regions.cache_clear()
    load_whitelist_effective_hp_index.cache_clear()
    cfg = load_difficulty_cfg()
    t093 = t093_config(cfg)
    assert t093.get("enabled"), "t093_progression must be enabled"

    lines: list[str] = [
        "# T-093 出表验收（不 apply）",
        "",
        f"**生成**：{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"**门前图**：`{GATEFRONT}` tier={resolve_map_tier_t093(GATEFRONT)} "
        f"map_mult={resolve_map_mult_t093(GATEFRONT)}",
        "",
        "## 1. 宁姆 map_mult=1 · c3060 ≈ 白名单",
        "",
    ]

    wl_c3060 = whitelist_effective_hp_for_model("c3060")
    row = {
        "map_id": GATEFRONT,
        "model": "c3060",
        "npc": 30600000,
        "tgt_cat": "trash",
        "src_cat": "trash",
    }
    donor = _stub_donor()
    target = resolve_t093_target_effective_hp(
        row,
        donor,
        difficulty={"enabled": True, "user_mult": 1.0},
        npc_by_id={30600000: donor},
        difficulty_cfg=cfg,
    )
    patch = compute_assignment_patch(
        row,
        donor,
        soul_out=100,
        difficulty={"enabled": True, "user_mult": 1.0},
        npc_by_id={30600000: donor},
        difficulty_cfg=cfg,
    )
    ok_c3060 = (
        wl_c3060 is not None
        and abs(target - wl_c3060) / max(wl_c3060, 1) < 0.05
        and target < 5000
        and resolve_map_mult_t093(GATEFRONT) == 1.0
    )
    lines += [
        f"| 项 | 值 |",
        f"|---|---|",
        f"| 白名单有效血 | {wl_c3060} |",
        f"| T-093 目标有效血 (s=1) | {target} |",
        f"| 表 hp (patch) | {(patch or {}).get('hp')} |",
        f"| 禁止出现 ≈705×3.34 | {'✅' if ok_c3060 else '❌'} |",
        "",
    ]

    lines += ["## 2. 滑条 lift 形态（h_ref / alpha 来自配置）", ""]
    h_ref = float(t093.get("lift_h_ref", 2500))
    alpha = float(t093.get("lift_alpha", 0.5))
    lines.append("| h | s=0.5 | s=1 | s=2 |")
    lines.append("|---:|---:|---:|---:|")
    for h in (800, 2500, 8000):
        m05 = compute_slider_lift_mult(h, 0.5, h_ref=h_ref, alpha=alpha)
        m10 = compute_slider_lift_mult(h, 1.0, h_ref=h_ref, alpha=alpha)
        m20 = compute_slider_lift_mult(h, 2.0, h_ref=h_ref, alpha=alpha)
        lines.append(
            f"| {h} | {h * m05:.0f} (×{m05:.3f}) | {h * m10:.0f} | {h * m20:.0f} (×{m20:.3f}) |"
        )
    lo2 = compute_slider_lift_mult(800, 2.0, h_ref=h_ref, alpha=alpha)
    hi2 = compute_slider_lift_mult(8000, 2.0, h_ref=h_ref, alpha=alpha)
    lo05 = compute_slider_lift_mult(800, 0.5, h_ref=h_ref, alpha=alpha)
    hi05 = compute_slider_lift_mult(8000, 0.5, h_ref=h_ref, alpha=alpha)
    lines += [
        "",
        f"- s>1 低血加得多：{lo2:.3f} > {hi2:.3f} → {'✅' if lo2 > hi2 else '❌'}",
        f"- s<1 高血降得多：{lo05:.3f} > {hi05:.3f} → {'✅' if lo05 > hi05 else '❌'}",
        "",
    ]

    lines += ["## 3. 夜晚 ×1.5 · 地下不乘", ""]
    night_row = {**row, "tgt_cat": "night"}
    n_over = night_mult_for_row(night_row, GATEFRONT, difficulty_cfg=cfg)
    # Siofra / Mohgwyn sample underground
    under_map = "m32_00_00_00"
    n_under = night_mult_for_row(night_row, under_map, difficulty_cfg=cfg)
    lines += [
        f"| 落点 | underground | night_mult |",
        f"|---|---|---:|",
        f"| `{GATEFRONT}` | {is_underground_map(GATEFRONT)} | {n_over} |",
        f"| `{under_map}` | {is_underground_map(under_map)} | {n_under} |",
        "",
        f"- 野外红灵 ×1.5：{'✅' if n_over == 1.5 else '❌'}",
        f"- 地下红灵 ×1：{'✅' if n_under == 1.0 else '❌'}",
        "",
    ]

    # Sample whitelist models × limgrave at s=1
    lines += ["## 4. 宁姆白名单抽样（s=1 应贴有效血）", ""]
    idx = load_whitelist_effective_hp_index()
    samples = sorted(idx.items(), key=lambda kv: kv[1])[:: max(1, len(idx) // 12)][:12]
    lines.append("| model | 白名单 | T-093(s=1) | 偏差% |")
    lines.append("|---|---:|---:|---:|")
    max_pct = 0.0
    for model, wl in samples:
        r = {
            "map_id": GATEFRONT,
            "model": model,
            "npc": 0,
            "tgt_cat": "trash",
            "src_cat": "trash",
        }
        t = resolve_t093_target_effective_hp(
            r,
            donor,
            difficulty={"enabled": True, "user_mult": 1.0},
            npc_by_id={},
            difficulty_cfg=cfg,
        )
        pct = abs(t - wl) / max(wl, 1) * 100
        max_pct = max(max_pct, pct)
        lines.append(f"| `{model}` | {wl} | {t} | {pct:.1f} |")
    lines += ["", f"最大偏差 {max_pct:.1f}%（期望 <5%）→ {'✅' if max_pct < 5 else '❌'}", ""]

    # Optional: single-map generate audit if spawn exists or we run generate
    out_dir = SCRIPT_DIR / "output" / "runtime" / "_t093_accept"
    lines += ["## 5. 单图 generate（门前 · 不 apply）", ""]
    try:
        from enemy_randomizer_core import run_enemy_generate  # type: ignore

        # Prefer thin generate API if present
        gen = getattr(sys.modules.get("enemy_randomizer_core"), "run_enemy_generate", None)
    except Exception:
        gen = None

    # Call CLI-compatible path
    import subprocess

    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        "enemy_randomizer_core.py",
        "generate",
        "--map-filter",
        GATEFRONT,
        "--out-dir",
        str(out_dir),
        "--seed",
        "93093001",
    ]
    proc = subprocess.run(cmd, cwd=str(SCRIPT_DIR), capture_output=True, text=True)
    lines.append(f"```")
    lines.append(f"$ {' '.join(cmd)}")
    lines.append((proc.stdout or "")[-800:])
    if proc.returncode != 0:
        lines.append((proc.stderr or "")[-800:])
    lines.append("```")
    lines.append("")

    copies = out_dir / "cnv_npc_soul_copies.json"
    spawn = out_dir / "cnv_enemy_spawn_map.txt"
    if copies.is_file():
        data = json.loads(copies.read_text(encoding="utf-8-sig"))
        specs = data.get("copies") or data.get("rows") or []
        if isinstance(data, dict) and not specs:
            # v2 shape
            specs = list((data.get("by_id") or {}).values()) or data.get("entries") or []
        hp_vals = []
        c3060_hits = []
        for spec in specs if isinstance(specs, list) else []:
            if not isinstance(spec, dict):
                continue
            hp = spec.get("hp")
            if hp is not None:
                try:
                    hp_vals.append(int(hp))
                except (TypeError, ValueError):
                    pass
            model = str(spec.get("model") or spec.get("base_model") or "")
            if "3060" in model or str(spec.get("base_npc") or "").startswith("3060"):
                c3060_hits.append(spec)
        lines += [
            f"- soul copies 文件：`{copies.name}`",
            f"- 写出 hp 条数：{len(hp_vals)}",
            f"- hp 中位数：{(sorted(hp_vals)[len(hp_vals)//2] if hp_vals else 'n/a')}",
            f"- c3060 相关条：{len(c3060_hits)}",
            "",
        ]
        # Flag any table hp that looks like old 705*3.34 baked wrong for limgrave trash
        suspect = [h for h in hp_vals if 2200 <= h <= 2500]
        lines.append(
            f"- 可疑「≈2350=705×3.34」条数：{len(suspect)} → "
            f"{'⚠️ 需人工看' if suspect else '✅ 未见'}"
        )
    else:
        lines.append(f"- 未写出 `{copies.name}`（exit={proc.returncode}）")

    if spawn.is_file():
        n_lines = sum(1 for _ in spawn.open(encoding="utf-8", errors="ignore"))
        lines.append(f"- spawn 行数：{n_lines}")

    lines += [
        "",
        "## 结论",
        "",
        f"- 宁姆×1 / c3060≈白名单：{'✅' if ok_c3060 else '❌'}",
        f"- lift 形态：{'✅' if lo2 > hi2 and lo05 > hi05 else '❌'}",
        f"- 夜/地下：{'✅' if n_over == 1.5 and n_under == 1.0 else '❌'}",
        "",
        "**本阶段不 apply、不真机。**",
        "",
    ]

    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {OUT_MD}")
    return 0 if ok_c3060 and lo2 > hi2 and n_over == 1.5 else 1


if __name__ == "__main__":
    raise SystemExit(main())
