#!/usr/bin/env python3
"""T-093：单图 generate 出表 + 多滑条叠乘对比（不 apply）。"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from enemy_difficulty import (  # noqa: E402
    compute_assignment_patch,
    compute_t093_stat_lift_mult,
    load_difficulty_cfg,
    resolve_t093_target_effective_hp,
)
from enemy_randomizer_core import run_enemy_randomize  # noqa: E402
from enemy_whitelist_hp import (  # noqa: E402
    load_whitelist_effective_hp_index,
    resolve_donor_baseline_effective_hp,
    whitelist_effective_hp_for_model,
)
from enemy_world_progression import (  # noqa: E402
    compute_slider_lift_mult,
    load_map_regions,
    night_mult_for_row,
    resolve_map_mult_t093,
    resolve_map_region_id,
    resolve_map_tier_t093,
    t093_config,
)
from paths import OUTPUT_REPORTS  # noqa: E402

SLIDERS = (0.1, 0.5, 1.0, 1.5, 2.0, 5.0)
SEED = 93093011
GATEFRONT = "m60_42_36_00"
OUT_DIR = SCRIPT_DIR / "output" / "runtime" / "_t093_slider_compare"
OUT_MD = OUTPUT_REPORTS / "T-093_滑条多档对比.md"

# 代表性对照组：覆盖低/中/高血、不同大区档、红灵×夜、地下红灵不乘
COMPARE_GROUPS: list[dict] = [
    {
        "label": "宁姆杂兵 c3060（档1·地图×1）",
        "map_id": GATEFRONT,
        "model": "c3060",
        "npc": 30600000,
        "tgt_cat": "trash",
        "src_cat": "trash",
        "hp_stub": "705",
        "poise_stub": "30",
    },
    {
        "label": "宁姆红灵（档1·夜×1.5）",
        "map_id": GATEFRONT,
        "model": "c3060",
        "npc": 30600000,
        "tgt_cat": "night",
        "src_cat": "night",
        "hp_stub": "705",
        "poise_stub": "30",
    },
    {
        "label": "希夫拉地下红灵（地下·夜不乘）",
        "map_id": "m32_00_00_00",
        "model": "c3060",
        "npc": 30600000,
        "tgt_cat": "night",
        "src_cat": "night",
        "hp_stub": "705",
        "poise_stub": "30",
    },
    {
        "label": "亚坛中血样（档8·地图×1.46）",
        "map_id": "m60_43_30_00",
        "model": "c3100",
        "npc": 31000000,
        "tgt_cat": "trash",
        "src_cat": "trash",
        "hp_stub": "1200",
        "poise_stub": "40",
    },
    {
        "label": "王城高血样（档12·地图×1.80）",
        "map_id": "m12_01_00_00",
        "model": "c2000",
        "npc": 20000000,
        "tgt_cat": "trash",
        "src_cat": "trash",
        "hp_stub": "3000",
        "poise_stub": "80",
    },
    {
        "label": "DLC深渊高档（档25·地图×3.28）",
        "map_id": "m61_46_38_00",
        "model": "c2000",
        "npc": 20000000,
        "tgt_cat": "trash",
        "src_cat": "trash",
        "hp_stub": "3000",
        "poise_stub": "80",
    },
]


def _stub(npc: int, hp: str, poise: str) -> dict[str, str]:
    return {
        "ID": str(npc),
        "hp": str(hp),
        "defFlickPower": str(poise),
        "spEffectID0": "0",
        "spEffectID1": "0",
        "spEffectID2": "0",
    }


def _row_from_group(g: dict) -> dict:
    return {
        "map_id": g["map_id"],
        "model": g["model"],
        "npc": g["npc"],
        "tgt_cat": g["tgt_cat"],
        "src_cat": g["src_cat"],
    }


def _stack_line(
    row: dict,
    donor: dict[str, str],
    *,
    npc_by_id: dict[int, dict[str, str]],
    cfg: dict,
    s: float,
) -> dict:
    t093 = t093_config(cfg)
    map_id = str(row["map_id"])
    base = resolve_donor_baseline_effective_hp(row, donor, npc_by_id=npc_by_id)
    map_m = resolve_map_mult_t093(map_id)
    night_m = night_mult_for_row(row, map_id, difficulty_cfg=cfg)
    pre = float(base) * map_m * night_m
    lift_m = compute_slider_lift_mult(
        pre,
        s,
        h_ref=float(t093.get("lift_h_ref", 2500)),
        alpha=float(t093.get("lift_alpha", 0.5)),
    )
    difficulty = {"enabled": True, "user_mult": s}
    target = resolve_t093_target_effective_hp(
        row, donor, difficulty=difficulty, npc_by_id=npc_by_id, difficulty_cfg=cfg
    )
    patch = compute_assignment_patch(
        row,
        donor,
        soul_out=100,
        difficulty=difficulty,
        npc_by_id=npc_by_id,
        difficulty_cfg=cfg,
    ) or {}
    stat_m = compute_t093_stat_lift_mult(
        row, donor, difficulty=difficulty, npc_by_id=npc_by_id, difficulty_cfg=cfg
    )
    region_id, _ = resolve_map_region_id(map_id)
    return {
        "base": base,
        "map_m": map_m,
        "night_m": night_m,
        "pre": pre,
        "lift_m": lift_m,
        "target": target,
        "hp": patch.get("hp"),
        "poise": patch.get("defFlickPower") or patch.get("poise"),
        "stat_m": stat_m,
        "tier": resolve_map_tier_t093(map_id),
        "region_id": region_id,
        "formula": f"{base}×{map_m:.2f}×{night_m:.2f}×{lift_m:.4f}",
    }


def _pick_live_rows(spawn_map: Path, limit: int = 6) -> list[dict]:
    """从出表抽几条真分配（不同模型优先）。列：map src_cat tgt_cat template model npc ..."""
    text = spawn_map.read_text(encoding="utf-8", errors="replace")
    seen: set[str] = set()
    rows: list[dict] = []
    for line in text.splitlines():
        if not line or line.startswith("#") or "=" in line[:24]:
            continue
        parts = line.split("\t")
        if len(parts) < 7:
            continue
        map_id = parts[0].strip()
        src_cat = parts[2].strip()
        tgt_cat = parts[3].strip()
        model = parts[5].strip()
        try:
            npc = int(parts[6].strip())
        except ValueError:
            npc = 0
        if not model or model in seen or npc <= 0:
            continue
        if tgt_cat in ("decorative",) or "suppress" in parts[4]:
            continue
        seen.add(model)
        rows.append(
            {
                "label": f"门前真分配 {model}（{tgt_cat}）",
                "map_id": map_id or GATEFRONT,
                "model": model,
                "npc": npc,
                "tgt_cat": tgt_cat or "trash",
                "src_cat": src_cat or "trash",
                "from_spawn": True,
            }
        )
        if len(rows) >= limit:
            break
    return rows


def main() -> int:
    load_map_regions.cache_clear()
    load_whitelist_effective_hp_index.cache_clear()
    cfg = load_difficulty_cfg()
    assert t093_config(cfg).get("enabled"), "t093 must be enabled"

    print(f"generate seed={SEED} map={GATEFRONT} -> {OUT_DIR}")
    conf = json.loads((SCRIPT_DIR / "config.json").read_text(encoding="utf-8"))
    conf = dict(conf)
    diff = dict(conf.get("enemy_difficulty") or {})
    diff["enabled"] = True
    diff["user_mult"] = 1.0
    conf["enemy_difficulty"] = diff
    result = run_enemy_randomize(
        conf,
        seed=SEED,
        map_filter=GATEFRONT,
        out_dir=OUT_DIR,
    )
    print(
        f"ok replaced={result.slots_replaced} skipped={result.slots_skipped} "
        f"-> {result.spawn_map_path}"
    )

    # Try load NpcParam from generated CSV for live rows
    npc_by_id: dict[int, dict[str, str]] = {}
    csv_candidates = list(OUT_DIR.glob("NpcParam_*.csv"))
    if csv_candidates:
        import csv as _csv

        with csv_candidates[0].open(encoding="utf-8", newline="") as f:
            reader = _csv.DictReader(f)
            for r in reader:
                try:
                    nid = int(r.get("ID") or 0)
                except ValueError:
                    continue
                if nid:
                    npc_by_id[nid] = {k: str(v) for k, v in r.items() if v is not None}

    groups = list(COMPARE_GROUPS)
    live = _pick_live_rows(Path(result.spawn_map_path), limit=4)
    for g in live:
        npc = int(g.get("npc") or 0)
        if npc and npc not in npc_by_id:
            wl = whitelist_effective_hp_for_model(str(g["model"]))
            g["hp_stub"] = str(max(1, int(wl or 1000)))
            g["poise_stub"] = "40"
            npc_by_id[npc] = _stub(npc, g["hp_stub"], g["poise_stub"])
        elif npc in npc_by_id:
            g["hp_stub"] = str(npc_by_id[npc].get("hp") or "1000")
            g["poise_stub"] = str(npc_by_id[npc].get("defFlickPower") or "40")
        else:
            g["hp_stub"] = "1000"
            g["poise_stub"] = "40"
        groups.append(g)

    for g in COMPARE_GROUPS:
        npc = int(g["npc"])
        if npc not in npc_by_id:
            npc_by_id[npc] = _stub(npc, g["hp_stub"], g["poise_stub"])

    lines: list[str] = [
        "# T-093 滑条多档对比（只出表 · 不 apply）",
        "",
        f"**生成**：{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"**种子**：`{SEED}` · 门前图 `{GATEFRONT}` · replaced={result.slots_replaced}",
        f"**出表目录**：`cnv_randomizer/output/runtime/_t093_slider_compare/`",
        "",
        "## 叠乘公式（矩阵难度）",
        "",
        "`最终有效血 = 白名单有效血 × 地图倍率 × 夜晚(红灵×1.5，地下=1) × 周目(本表=1) × 滑条lift`",
        "",
        "滑条 lift：`s=1` 不变；`s>1` 低血加得多；`s<1` 高血降得多。韧性/视嗅攻同用 `stat_mult`。",
        "",
        f"滑条取样：{' / '.join(str(x) for x in SLIDERS)}",
        "",
    ]

    for g in groups:
        row = _row_from_group(g)
        donor = npc_by_id.get(int(g["npc"])) or _stub(
            int(g["npc"]), g.get("hp_stub", "1000"), g.get("poise_stub", "40")
        )
        npc_by_id[int(g["npc"])] = donor
        # prefer whitelist baseline display
        base = resolve_donor_baseline_effective_hp(row, donor, npc_by_id=npc_by_id)
        map_id = g["map_id"]
        tier = resolve_map_tier_t093(map_id)
        region_id, reason = resolve_map_region_id(map_id)
        map_m = resolve_map_mult_t093(map_id)
        night_m = night_mult_for_row(row, map_id, difficulty_cfg=cfg)

        lines += [
            f"## {g['label']}",
            "",
            f"- 图 `{map_id}` · 大区 `{region_id}` · 档 **{tier}** · 地图×**{map_m}** · 夜×**{night_m}**",
            f"- 白名单/基准有效血 **{base}** · 模型 `{g['model']}` npc `{g['npc']}`",
            f"- 叠乘前（周目=1）：`{base} × {map_m} × {night_m} = {base * map_m * night_m:.1f}`",
            "",
            "| 滑条s | 叠乘拆解 | lift× | 目标有效血 | 表hp | 韧 | 视嗅攻× |",
            "|---:|:---|---:|---:|---:|---:|---:|",
        ]
        for s in SLIDERS:
            st = _stack_line(row, donor, npc_by_id=npc_by_id, cfg=cfg, s=s)
            lines.append(
                f"| {s:g} | `{st['formula']}` | {st['lift_m']:.4f} | {st['target']} | "
                f"{st['hp']} | {st['poise']} | {st['stat_m']:.4f} |"
            )
        lines.append("")

    # 形态摘要：同图低血 vs 高血在 s=2 / s=0.1
    lines += [
        "## 形态抽检（同参考血）",
        "",
        "| 预滑条有效血 h | s=0.1 lift | s=0.5 | s=1 | s=1.5 | s=2 | s=5 |",
        "|---:|---:|---:|---:|---:|---:|---:|",
    ]
    t093 = t093_config(cfg)
    href = float(t093["lift_h_ref"])
    alpha = float(t093["lift_alpha"])
    for h in (800.0, 2500.0, 8000.0, 20000.0):
        cells = [f"{h:g}"]
        for s in SLIDERS:
            m = compute_slider_lift_mult(h, s, h_ref=href, alpha=alpha)
            cells.append(f"{m:.3f}→{h*m:.0f}")
        lines.append("| " + " | ".join(cells) + " |")
    lines += [
        "",
        "## 验收要点",
        "",
        "- 宁姆档1·s=1：有效血 ≈ 白名单，禁止再 ×3.34",
        "- 同 s>1：低血 lift 更大；同 s<1：高血 lift 更小（降得多）",
        "- 红灵地上 ×1.5；地下红灵夜倍率=1",
        "- 本报告不 apply、不真机",
        "",
    ]

    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {OUT_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
