#!/usr/bin/env python3
"""T-094：门前出表 + 多例对照报告（不 apply）。"""

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
    whitelist_effective_hp_for_model,
)
from enemy_world_progression import (  # noqa: E402
    asymmetric_layer_lift_mult,
    load_map_regions,
    load_region_progression,
    map_layer_lift_mult,
    nominal_journey_atk_mult,
    nominal_journey_hp_mult,
    nominal_map_hp_mult,
    resolve_bracket_cap_mult,
    resolve_map_mult_t093,
    resolve_map_tier_t093,
    t094_config,
)
from paths import OUTPUT_REPORTS  # noqa: E402

SEED = 94094001
GATE = "m60_42_36_00"
ABYSS = "m61_46_38_00"
ALTUS = "m60_43_30_00"
OUT_DIR = SCRIPT_DIR / "output" / "runtime" / "_t094_report"
OUT_MD = OUTPUT_REPORTS / "T-094_出表示例报告.md"

# 白名单血量档例子
EXAMPLES = [
    ("几百血", "c2041", 20410050),
    ("约2000", "c5330", 53300087),
    ("约5000", "c3805", 38050050),
    ("中位Boss", "c5820", 58200095),
    ("约2万", "c3050", 30500051),
    ("最高Boss", "c4760", 47601050),
]


def _stub(npc: int, hp: str = "1000") -> dict[str, str]:
    return {
        "ID": str(npc),
        "hp": str(hp),
        "defFlickPower": "40",
        "spEffectID0": "0",
        "spEffectID1": "0",
        "spEffectID2": "0",
    }


def _target(
    model: str,
    npc: int,
    map_id: str,
    journey: int,
    *,
    user_mult: float = 1.0,
    night: bool = False,
    cfg: dict,
) -> dict:
    wl = whitelist_effective_hp_for_model(model) or 1000
    row = {
        "map_id": map_id,
        "model": model,
        "npc": npc,
        "tgt_cat": "night" if night else "trash",
        "src_cat": "trash",
    }
    donor = _stub(npc, str(wl))
    npc_by_id = {npc: donor}
    difficulty = {
        "enabled": True,
        "user_mult": user_mult,
        "journey_tier": journey,
    }
    hp = resolve_t093_target_effective_hp(
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
    stat = compute_t093_stat_lift_mult(
        row, donor, difficulty=difficulty, npc_by_id=npc_by_id, difficulty_cfg=cfg
    )
    tier = resolve_map_tier_t093(map_id)
    return {
        "wl": wl,
        "hp": hp,
        "table_hp": patch.get("hp"),
        "poise": patch.get("defFlickPower"),
        "stat_m": stat,
        "tier": tier,
        "map_nom": nominal_map_hp_mult(tier, difficulty_cfg=cfg),
        "j_nom": nominal_journey_hp_mult(journey, difficulty_cfg=cfg),
        "cap": int(wl * resolve_bracket_cap_mult(wl, kind="hp", difficulty_cfg=cfg)),
    }


def _pick_spawn_rows(spawn_map: Path, limit: int = 5) -> list[dict]:
    rows: list[dict] = []
    seen: set[str] = set()
    for line in spawn_map.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line or line.startswith("#") or "=" in line[:20]:
            continue
        parts = line.split("\t")
        if len(parts) < 7:
            continue
        model = parts[5].strip()
        tgt = parts[3].strip()
        try:
            npc = int(parts[6].strip())
        except ValueError:
            continue
        if not model or model in seen or npc <= 0:
            continue
        if "suppress" in parts[4]:
            continue
        seen.add(model)
        rows.append(
            {
                "label": f"门前真换 {model}（{tgt}）",
                "model": model,
                "npc": npc,
                "tgt": tgt,
            }
        )
        if len(rows) >= limit:
            break
    return rows


def main() -> int:
    load_map_regions.cache_clear()
    load_region_progression.cache_clear()
    load_whitelist_effective_hp_index.cache_clear()
    cfg = load_difficulty_cfg()
    t094 = t094_config(cfg)
    assert t094.get("enabled"), "t094_caps must be enabled"

    print(f"generate seed={SEED} map={GATE}")
    conf = json.loads((SCRIPT_DIR / "config.json").read_text(encoding="utf-8"))
    conf = dict(conf)
    diff = dict(conf.get("enemy_difficulty") or {})
    diff["enabled"] = True
    diff["user_mult"] = 1.0
    conf["enemy_difficulty"] = diff
    result = run_enemy_randomize(
        conf, seed=SEED, map_filter=GATE, out_dir=OUT_DIR
    )
    print(
        f"ok replaced={result.slots_replaced} skipped={result.slots_skipped} "
        f"-> {result.spawn_map_path}"
    )

    lines: list[str] = [
        "# T-094 出表示例报告（不 apply）",
        "",
        f"**生成**：{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"**种子**：`{SEED}` · 门前图 `{GATE}` · 换了 **{result.slots_replaced}** 个槽",
        f"**出表目录**：`cnv_randomizer/output/runtime/_t094_report/`",
        "",
        "## 怎么读",
        "",
        "- 最终血：白名单 → 地图层lift(T-095) → 夜 → 周目层lift → **分层硬帽** → 全局滑条lift",
        "- 弱怪几百血深渊周1约 **4000**；强怪最难 **接近×3**（上界不强制顶满）",
        "- 周目攻最高 **1.45**（不跟地图）",
        "",
        "## 名义抽检",
        "",
        f"| 项 | 值 |",
        f"|---|---|",
        f"| 地图档1 / 25 | {nominal_map_hp_mult(1, difficulty_cfg=cfg)} / {nominal_map_hp_mult(25, difficulty_cfg=cfg)} |",
        f"| 周目1 / 8 / 9 | {nominal_journey_hp_mult(1, difficulty_cfg=cfg)} / {nominal_journey_hp_mult(8, difficulty_cfg=cfg)} / {nominal_journey_hp_mult(9, difficulty_cfg=cfg)} |",
        f"| 周目攻9 | {nominal_journey_atk_mult(9, difficulty_cfg=cfg)} |",
        f"| 门前 map_mult | {resolve_map_mult_t093(GATE)}（档{resolve_map_tier_t093(GATE)}） |",
        f"| 深渊 map_mult | {resolve_map_mult_t093(ABYSS)}（档{resolve_map_tier_t093(ABYSS)}） |",
        f"| 亚坛 map_mult | {resolve_map_mult_t093(ALTUS)}（档{resolve_map_tier_t093(ALTUS)}） |",
        "",
        "## 层 lift（深渊地图×1.5 · T-095 map_layer）",
        "",
        "| 进入层前血 h | 层eff | 说明 |",
        "|---:|---:|---|",
    ]
    for h, note in (
        (600, "低血：高于名义"),
        (2500, "参考血附近：≈名义"),
        (30000, "高血：等于名义 1.5"),
    ):
        eff = map_layer_lift_mult(h, 1.5, difficulty_cfg=cfg)
        lines.append(f"| {h} | {eff:.4f} | {note} |")

    lines += [
        "",
        "## 白名单例子：宁姆一周目 vs 深渊最难（滑条=1）",
        "",
        "| 档 | 模型 | 白名单 | 宁姆·周1 | 亚坛8·周1 | 深渊25·周1 | **深渊25·周9** | 分层血帽 |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for label, model, npc in EXAMPLES:
        a = _target(model, npc, GATE, 1, cfg=cfg)
        b = _target(model, npc, ALTUS, 1, cfg=cfg)
        c = _target(model, npc, ABYSS, 1, cfg=cfg)
        d = _target(model, npc, ABYSS, 9, cfg=cfg)
        lines.append(
            f"| {label} | `{model}` | {a['wl']} | {a['hp']} | {b['hp']} | {c['hp']} | **{d['hp']}** | {d['cap']} |"
        )

    lines += [
        "",
        "## 同皮参数对照（深渊·周目9·滑条=1）",
        "",
        "| 档 | 模型 | 有效血 | 表hp | 韧 | 视嗅攻× |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for label, model, npc in EXAMPLES:
        d = _target(model, npc, ABYSS, 9, cfg=cfg)
        lines.append(
            f"| {label} | `{model}` | {d['hp']} | {d['table_hp']} | {d['poise']} | {d['stat_m']:.4f} |"
        )

    lines += [
        "",
        "## 滑条抽样（深渊·周目1 · 火焰巨人）",
        "",
        "| 滑条 | 有效血 | 相对白名单 |",
        "|---:|---:|---:|",
    ]
    wl_g = whitelist_effective_hp_for_model("c4760") or 71454
    for s in (0.5, 1.0, 1.5, 2.0):
        t = _target("c4760", 47601050, ABYSS, 1, user_mult=s, cfg=cfg)
        lines.append(f"| {s:g} | {t['hp']} | ×{t['hp'] / wl_g:.3f} |")

    lines += [
        "",
        "## 红灵夜 vs 硬帽（深渊·周目9）",
        "",
        "| 皮 | 非夜 | 红灵夜 | 硬帽 |",
        "|---|---:|---:|---:|",
    ]
    for label, model, npc in (("小怪", "c2041", 20410050), ("巨人", "c4760", 47601050)):
        n0 = _target(model, npc, ABYSS, 9, night=False, cfg=cfg)
        n1 = _target(model, npc, ABYSS, 9, night=True, cfg=cfg)
        lines.append(f"| {label} `{model}` | {n0['hp']} | {n1['hp']} | {n0['cap']} |")

    live = _pick_spawn_rows(Path(result.spawn_map_path), limit=5)
    if live:
        lines += [
            "",
            "## 门前本次真换出来的皮（再算深渊·周9）",
            "",
            "| 分配 | 模型 | 白名单 | 门前周1 | 深渊周9 | 硬帽 |",
            "|---|---|---:|---:|---:|---:|",
        ]
        for g in live:
            model = g["model"]
            npc = int(g["npc"])
            wl = whitelist_effective_hp_for_model(model)
            if not wl:
                continue
            a = _target(model, npc, GATE, 1, cfg=cfg)
            d = _target(model, npc, ABYSS, 9, cfg=cfg)
            lines.append(
                f"| {g['label']} | `{model}` | {a['wl']} | {a['hp']} | {d['hp']} | {d['cap']} |"
            )

    lines += [
        "",
        "## 一眼结论",
        "",
        "- 宁姆一周目：约等于白名单血（地图×1、周目×1）",
        "- 深渊周1：弱怪几百血约 **4000**（对齐原版 trash）；周9 弱怪顶分层血帽（605→4235，×7）",
        "- 强怪最难 **接近×3** 为上限，不强制顶满；火焰巨人 J9 仍≈×3",
        "- 红灵夜在已顶满分层帽时不再额外涨破",
        "- 滑条>1 仍可超过分层帽（全局滑条单独算）",
        "- **本报告只出表，不写进游戏**",
        "",
    ]
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {OUT_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
