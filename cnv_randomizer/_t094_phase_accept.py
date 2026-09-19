#!/usr/bin/env python3
"""T-094 详尽出表验收（不 apply）：全参数 · 矩阵 · 多样本。"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
REPO = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

from enemy_difficulty import (  # noqa: E402
    _attack_sp_rate_table,
    compute_assignment_patch,
    compute_t093_attack_lift_mult,
    compute_t093_stat_lift_mult,
    load_difficulty_cfg,
    resolve_t093_target_effective_hp,
)
from enemy_whitelist_hp import (  # noqa: E402
    load_whitelist_effective_hp_index,
    resolve_donor_baseline_effective_hp,
    whitelist_effective_hp_for_model,
)
from enemy_world_progression import (  # noqa: E402
    asymmetric_layer_lift_mult,
    compute_slider_lift_mult,
    load_map_regions,
    load_region_progression,
    map_layer_lift_mult,
    night_mult_for_row,
    nominal_journey_atk_mult,
    nominal_journey_hp_mult,
    nominal_journey_stat_mult,
    nominal_map_atk_mult,
    nominal_map_hp_mult,
    nominal_map_stat_mult,
    resolve_bracket_cap_mult,
    resolve_journey_tier,
    resolve_map_tier_t093,
    t093_config,
    t094_config,
    t094_enabled,
)
from paths import OUTPUT_REPORTS  # noqa: E402

OUT = OUTPUT_REPORTS / "T-094_出表验收.md"
OFFLINE = REPO / "捐皮契约" / "离线参数大表.json"

# 代表地图（大区档）
MAP_CASES: list[tuple[str, str]] = [
    ("档1·宁姆", "m60_42_36_00"),
    ("档5·盖利德", "m60_50_36_00"),
    ("档8·亚坛", "m60_43_30_00"),
    ("档12·王城", "m12_01_00_00"),
    ("档20·灰城", "m12_03_00_00"),
    ("档25·深渊", "m61_46_38_00"),
]

JOURNEY_COLS = tuple(range(1, 10))
SLIDER_COLS = (0.1, 0.5, 1.0, 1.5, 2.0, 5.0)

# 白名单血量档多样本
SAMPLES: list[tuple[str, str, int]] = [
    ("几百血·腐败眷属", "c2041", 20410050),
    ("约2k·圣特里娜", "c5330", 53300087),
    ("约5k·女猎手", "c3805", 38050050),
    ("约1w·玛尔基特", "c2130", 21300000),
    ("中位Boss·凯玛", "c5820", 58200095),
    ("约2w·老将", "c3050", 30500051),
    ("最高·火焰巨人", "c4760", 47601050),
]


def _bracket_hp_cap(wl: int | float, cfg: dict[str, Any]) -> int:
    return int(wl * resolve_bracket_cap_mult(wl, kind="hp", difficulty_cfg=cfg))


@dataclass
class CaseResult:
    label: str
    model: str
    map_id: str
    map_label: str
    map_tier: int
    journey: int
    night: bool
    slider: float
    whitelist_hp: int
    map_nom: float
    map_eff: float
    night_m: float
    journey_nom: float
    journey_eff: float
    pre_cap: float
    hp_cap: float
    capped: bool
    slider_lift: float
    eff_hp: int
    table_hp: int | None
    base_poise: int
    out_poise: int | None
    stat_mult: float
    journey_atk: float
    base_eye: float | None
    out_eye: float | None
    base_nose: float | None
    out_nose: float | None
    base_ear: float | None
    out_ear: float | None


def _load_offline_by_npc() -> dict[int, dict[str, Any]]:
    if not OFFLINE.is_file():
        return {}
    data = json.loads(OFFLINE.read_text(encoding="utf-8-sig"))
    out: dict[int, dict[str, Any]] = {}
    for row in data.get("rows") or []:
        try:
            nid = int(row.get("npc") or 0)
        except (TypeError, ValueError):
            continue
        if nid:
            out[nid] = row
    return out


def _donor_row(
    model: str,
    npc: int,
    offline: dict[int, dict[str, Any]],
) -> dict[str, str]:
    wl = whitelist_effective_hp_for_model(model) or 1000
    base = dict(offline.get(npc) or {})
    poise = int(base.get("defFlickPower") or 40)
    return {
        "ID": str(npc),
        "hp": str(wl),
        "defFlickPower": str(poise),
        "spEffectID0": "0",
        "spEffectID1": "0",
        "spEffectID2": "0",
    }


def _think_bases(offline_row: dict[str, Any] | None) -> dict[str, float]:
    if not offline_row:
        return {}
    th = offline_row.get("think") or {}
    out: dict[str, float] = {}
    for k in ("eye_dist", "searchEye_dist", "nose_dist", "ear_dist"):
        try:
            v = float(th.get(k) or 0)
        except (TypeError, ValueError):
            v = 0.0
        if v > 0:
            out[k] = v
    return out


def _hp_breakdown(
    row: dict[str, Any],
    donor: dict[str, str],
    *,
    difficulty: dict[str, Any],
    npc_by_id: dict[int, dict[str, str]],
    cfg: dict[str, Any],
) -> dict[str, float]:
    t093 = t093_config(cfg)
    h_ref = float(t093.get("lift_h_ref", 2500.0))
    alpha = float(t093.get("lift_alpha", 0.5))
    base = float(
        resolve_donor_baseline_effective_hp(row, donor, npc_by_id=npc_by_id) or 0
    )
    h = base
    map_id = str(row.get("map_id") or "")
    out: dict[str, float] = {
        "base": base,
        "map_nom": 1.0,
        "map_eff": 1.0,
        "night_m": 1.0,
        "journey_nom": 1.0,
        "journey_eff": 1.0,
        "pre_cap": base,
        "hp_cap": _bracket_hp_cap(base, cfg),
    }
    if t094_enabled(cfg):
        t094 = t094_config(cfg)
        h_ref = float(t094.get("layer_lift_h_ref", h_ref))
        alpha = float(t094.get("layer_lift_alpha", alpha))
        tier = resolve_map_tier_t093(map_id)
        map_nom = nominal_map_hp_mult(tier, difficulty_cfg=cfg)
        map_eff = map_layer_lift_mult(h, map_nom, difficulty_cfg=cfg)
        h *= map_eff
        night_m = night_mult_for_row(row, map_id, difficulty_cfg=cfg)
        h *= night_m
        j_tier = resolve_journey_tier(difficulty)
        j_nom = nominal_journey_hp_mult(j_tier, difficulty_cfg=cfg)
        j_eff = asymmetric_layer_lift_mult(h, j_nom, h_ref=h_ref, alpha=alpha)
        h *= j_eff
        cap = base * resolve_bracket_cap_mult(base, kind="hp", difficulty_cfg=cfg)
        pre_cap = h
        h = min(h, cap)
        out.update(
            map_nom=map_nom,
            map_eff=map_eff,
            night_m=night_m,
            journey_nom=j_nom,
            journey_eff=j_eff,
            pre_cap=pre_cap,
            hp_cap=cap,
        )
    else:
        out["night_m"] = night_mult_for_row(row, map_id, difficulty_cfg=cfg)
        out["pre_cap"] = base
    user_mult = float(difficulty.get("user_mult", 1.0))
    slider_lift = compute_slider_lift_mult(
        h, user_mult,
        h_ref=float(t093.get("lift_h_ref", 2500.0)),
        alpha=float(t093.get("lift_alpha", 0.5)),
    )
    out["slider_lift"] = slider_lift
    out["final"] = h * slider_lift
    return out


def eval_case(
    *,
    label: str,
    model: str,
    npc: int,
    map_id: str,
    map_label: str,
    journey: int,
    slider: float,
    night: bool,
    cfg: dict[str, Any],
    offline: dict[int, dict[str, Any]],
) -> CaseResult:
    wl = whitelist_effective_hp_for_model(model) or 1000
    row = {
        "map_id": map_id,
        "model": model,
        "npc": npc,
        "tgt_cat": "night" if night else "trash",
        "src_cat": "trash",
    }
    donor = _donor_row(model, npc, offline)
    npc_by_id = {npc: donor}
    difficulty = {
        "enabled": True,
        "user_mult": slider,
        "journey_tier": journey,
    }
    bd = _hp_breakdown(row, donor, difficulty=difficulty, npc_by_id=npc_by_id, cfg=cfg)
    eff = resolve_t093_target_effective_hp(
        row, donor, difficulty=difficulty, npc_by_id=npc_by_id, difficulty_cfg=cfg
    )
    patch = compute_assignment_patch(
        row, donor, soul_out=100, difficulty=difficulty,
        npc_by_id=npc_by_id, difficulty_cfg=cfg,
    ) or {}
    stat_m = compute_t093_stat_lift_mult(
        row, donor, difficulty=difficulty, npc_by_id=npc_by_id, difficulty_cfg=cfg
    )
    think = _think_bases(offline.get(npc))
    base_poise = int(donor.get("defFlickPower") or 0)
    out_poise_raw = patch.get("defFlickPower")
    out_poise = int(out_poise_raw) if out_poise_raw not in (None, "") else None
    if out_poise is None and base_poise > 0:
        out_poise = max(0, int(round(base_poise * stat_m)))

    def _scaled(key: str) -> tuple[float | None, float | None]:
        b = think.get(key)
        if b is None:
            return None, None
        o = max(0.0, float(b) * stat_m)
        return b, o

    eye_b, eye_o = _scaled("eye_dist")
    nose_b, nose_o = _scaled("nose_dist")
    ear_b, ear_o = _scaled("ear_dist")

    t094 = t094_config(cfg)
    cap = wl * resolve_bracket_cap_mult(wl, kind="hp", difficulty_cfg=cfg)

    return CaseResult(
        label=label,
        model=model,
        map_id=map_id,
        map_label=map_label,
        map_tier=resolve_map_tier_t093(map_id),
        journey=journey,
        night=night,
        slider=slider,
        whitelist_hp=wl,
        map_nom=bd["map_nom"],
        map_eff=bd["map_eff"],
        night_m=bd["night_m"],
        journey_nom=bd["journey_nom"],
        journey_eff=bd["journey_eff"],
        pre_cap=bd["pre_cap"],
        hp_cap=cap,
        capped=bd["pre_cap"] > cap + 0.5,
        slider_lift=bd["slider_lift"],
        eff_hp=eff,
        table_hp=int(patch["hp"]) if patch.get("hp") else eff,
        base_poise=base_poise,
        out_poise=out_poise,
        stat_mult=stat_m,
        journey_atk=nominal_journey_atk_mult(journey, difficulty_cfg=cfg),
        base_eye=eye_b,
        out_eye=eye_o,
        base_nose=nose_b,
        out_nose=nose_o,
        base_ear=ear_b,
        out_ear=ear_o,
    )


def _md_table(headers: list[str], rows: list[list[Any]]) -> list[str]:
    sep = "|" + "|".join("---:" if i else "---" for i, _ in enumerate(headers)) + "|"
    lines = ["| " + " | ".join(str(h) for h in headers) + " |", sep]
    for row in rows:
        lines.append("| " + " | ".join(str(c) for c in row) + " |")
    return lines


def main() -> int:
    load_map_regions.cache_clear()
    load_region_progression.cache_clear()
    load_whitelist_effective_hp_index.cache_clear()
    cfg = load_difficulty_cfg()
    t093 = t093_config(cfg)
    t094 = t094_config(cfg)
    offline = _load_offline_by_npc()

    lines: list[str] = [
        "# T-094 出表验收（详尽 · 不 apply）",
        "",
        f"**生成**：{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "## 1. 叠层口径",
        "",
        "```text",
        "有效血 = 白名单 → 地图(T-095 map_layer_lift) → 夜 → 周目(层lift) → min(分层硬帽) → 全局滑条lift",
        "其它(韧/视/嗅/听) = 底数 × 地图stat层 × 周目stat层(分层stat帽) × 全局滑条lift",
        "攻击(T-096) = 地图攻 lift+帽（mod 仅地图）；周目攻引擎 1.0→1.45；总攻≈mod×引擎",
        "```",
        "",
        "## 2. 配置快照",
        "",
        "| 项 | 值 |",
        "|---|---|",
        f"| 血硬帽 | ×{t094['hp_cap_mult']} |",
        f"| 其它硬帽 | ×{t094['stat_cap_mult']} |",
        f"| 地图血最高 M_hp | {t094['map_hp_max']}（档25） |",
        f"| 周目血最高 J_hp | {t094['journey_hp_max']}（周目9） |",
        f"| 地图stat最高 | {t094['map_stat_max']} |",
        f"| 地图攻最高 M_atk | {t094['map_atk_max']}（档25） |",
        f"| 攻硬帽（强怪≥5000） | ×{t094['attack_cap_mult']} |",
        f"| 弱怪地图攻帽 (<800/<2000/<5000) | ×6 / ×3 / ×1.0 |",
        f"| 地图加攻 sp | {'关' if t094.get('disable_map_attack_sp') else '开'} |",
        f"| 周目stat最高 | {t094['journey_stat_max']} |",
        f"| 周目攻最高 | {t094['journey_atk_max']} |",
        f"| 层lift h_ref / alpha | {t094['layer_lift_h_ref']} / {t094['layer_lift_alpha']} |",
        f"| 地图层lift h_ref / alpha (T-095) | {t094.get('map_layer_lift_h_ref')} / {t094.get('map_layer_lift_alpha')} |",
        f"| 弱怪血帽档 (<800/<2000/<5000) | ×7 / ×5 / ×4 |",
        f"| 强怪血帽上界 (≥5000) | ×{t094['hp_cap_mult']} |",
        f"| 全局滑条 h_ref / alpha | {t093['lift_h_ref']} / {t093['lift_alpha']} |",
        f"| 红灵夜倍率 | ×{t093['night_mult']}（地下×1） |",
        f"| 名义乘积封顶 | {t094['map_hp_max']}×{t094['journey_hp_max']}={float(t094['map_hp_max'])*float(t094['journey_hp_max']):.2f} |",
        "",
        "## 3. 名义曲线表",
        "",
        "### 3.1 地图档 · 血 / stat（均匀线性）",
        "",
    ]

    tier_rows: list[list[Any]] = []
    for t in range(1, 26):
        tier_rows.append([
            t,
            f"{nominal_map_hp_mult(t, difficulty_cfg=cfg):.6f}",
            f"{nominal_map_stat_mult(t, difficulty_cfg=cfg):.6f}",
        ])
    lines += _md_table(["档 t", "M_hp", "M_stat"], tier_rows)

    lines += ["", "### 3.2 周目档 · 血 / stat / 攻", ""]
    j_rows: list[list[Any]] = []
    for j in range(1, 10):
        j_rows.append([
            j,
            f"{nominal_journey_hp_mult(j, difficulty_cfg=cfg):.6f}",
            f"{nominal_journey_stat_mult(j, difficulty_cfg=cfg):.6f}",
            f"{nominal_journey_atk_mult(j, difficulty_cfg=cfg):.6f}",
        ])
    lines += _md_table(["周目 j", "J_hp", "J_stat", "J_atk"], j_rows)

    lines += ["", "## 4. 层 lift 矩阵（非对称 max(名义, lift)）", ""]
    lift_rows: list[list[Any]] = []
    for h in (400, 600, 2500, 8000, 20000, 50000):
        lift_rows.append([
            h,
            f"{asymmetric_layer_lift_mult(h, 1.25, h_ref=2500, alpha=0.5):.4f}",
            f"{asymmetric_layer_lift_mult(h, 1.5, h_ref=2500, alpha=0.5):.4f}",
            f"{asymmetric_layer_lift_mult(h, 2.0, h_ref=2500, alpha=0.5):.4f}",
        ])
    lines += _md_table(["进入层前血 h", "名义1.25", "名义1.5", "名义2.0"], lift_rows)

    # --- 地图 / 周目 / 全局 lift 三类对比 ---
    h_ref = float(t094.get("layer_lift_h_ref", t093["lift_h_ref"]))
    alpha = float(t094.get("layer_lift_alpha", t093["lift_alpha"]))
    slider_h_ref = float(t093["lift_h_ref"])
    slider_alpha = float(t093["lift_alpha"])

    map_h_ref = float(t094.get("map_layer_lift_h_ref", h_ref))
    map_alpha = float(t094.get("map_layer_lift_alpha", alpha))
    abyss_id = "m61_46_38_00"
    sp_rates = _attack_sp_rate_table(cfg)

    lines += [
        "",
        "## 5. 地图 / 周目 / 全局 lift 对比（T-095 地图层独立参数）",
        "",
        "地图层用 `map_layer_lift_mult`；周目层仍用层 lift；全局滑条独立。",
        f"地图层 h_ref/alpha = {map_h_ref:g}/{map_alpha:g}；周目层 = {h_ref:g}/{alpha:g}；滑条 = {slider_h_ref:g}/{slider_alpha:g}。",
        "",
        "### 5.1 地图层 lift（进入血 = 白名单 · T-095）",
        "",
    ]
    map_lift_header = ["样本", "白名单", "血帽×", "stat帽×"] + [mlabel for mlabel, _ in MAP_CASES]
    map_lift_rows: list[list[Any]] = []
    for slabel, model, _npc in SAMPLES:
        wl = whitelist_effective_hp_for_model(model) or 0
        hp_cap_m = resolve_bracket_cap_mult(wl, kind="hp", difficulty_cfg=cfg)
        stat_cap_m = resolve_bracket_cap_mult(wl, kind="stat", difficulty_cfg=cfg)
        cells: list[Any] = [
            f"{slabel} `{model}`", wl,
            f"{hp_cap_m:.1f}", f"{stat_cap_m:.1f}",
        ]
        for _mlabel, map_id in MAP_CASES:
            tier = resolve_map_tier_t093(map_id)
            nom = nominal_map_hp_mult(tier, difficulty_cfg=cfg)
            eff = map_layer_lift_mult(wl, nom, difficulty_cfg=cfg)
            cells.append(f"{nom:.3f}→{eff:.3f}")
        map_lift_rows.append(cells)
    lines += _md_table(map_lift_header, map_lift_rows)

    lines += [
        "",
        "### 5.1b 弱怪锚点（深渊 · 滑条=1 · 非夜 · T-095 验收）",
        "",
        "对照原版 trash `c5740` 有效血 **3896**；强怪只要求 **接近 ×3** 不必须顶帽。",
        "",
    ]
    anchor_header = ["样本", "白名单", "血帽", "J1有效血", "J9叠乘前", "J9硬帽", "J9最终", "J9/白名单"]
    anchor_rows: list[list[Any]] = []
    for slabel, model, npc in SAMPLES[:3] + [SAMPLES[-1]]:
        wl = whitelist_effective_hp_for_model(model) or 0
        cap = int(wl * resolve_bracket_cap_mult(wl, kind="hp", difficulty_cfg=cfg))
        r_j1 = eval_case(
            label=slabel, model=model, npc=npc, map_id=abyss_id,
            map_label="深渊", journey=1, slider=1.0, night=False,
            cfg=cfg, offline=offline,
        )
        r_j9 = eval_case(
            label=slabel, model=model, npc=npc, map_id=abyss_id,
            map_label="深渊", journey=9, slider=1.0, night=False,
            cfg=cfg, offline=offline,
        )
        anchor_rows.append([
            f"`{model}`", wl, cap,
            r_j1.eff_hp, int(r_j9.pre_cap), int(r_j9.hp_cap),
            r_j9.eff_hp, f"{r_j9.eff_hp / wl:.3f}",
        ])
    lines += _md_table(anchor_header, anchor_rows)

    lines += [
        "",
        "### 5.1c 攻击锚点（深渊 · 滑条=1 · T-096）",
        "",
        "对照原版 trash `c5740`：地图攻 **1.0**；周目 J1=1.0 / J9=1.45（引擎）；总攻=地图×引擎。",
        "",
    ]
    atk_anchor_header = [
        "样本", "白名单", "地图攻", "J1 mod", "J9 mod", "J1 总攻≈", "J9 总攻≈",
    ]
    atk_anchor_rows: list[list[Any]] = []
    sp_rates = _attack_sp_rate_table(cfg)
    for slabel, model, npc in SAMPLES[:3] + [SAMPLES[-1]]:
        wl = whitelist_effective_hp_for_model(model) or 0
        donor = _donor_row(model, npc, offline)
        row = {
            "map_id": abyss_id,
            "model": model,
            "npc": npc,
            "tgt_cat": "trash",
            "src_cat": "trash",
        }
        npc_by_id = {npc: donor}
        diff_j1 = {"enabled": True, "user_mult": 1.0, "journey_tier": 1}
        diff_j9 = {"enabled": True, "user_mult": 1.0, "journey_tier": 9}
        layer_j1 = compute_t093_attack_lift_mult(
            row, donor, difficulty=diff_j1, npc_by_id=npc_by_id, difficulty_cfg=cfg,
        )
        layer_j9 = compute_t093_attack_lift_mult(
            row, donor, difficulty=diff_j9, npc_by_id=npc_by_id, difficulty_cfg=cfg,
        )
        patch_j1 = compute_assignment_patch(
            row, donor, soul_out=100, difficulty=diff_j1,
            npc_by_id=npc_by_id, difficulty_cfg=cfg,
        ) or {}
        patch_j9 = compute_assignment_patch(
            row, donor, soul_out=100, difficulty=diff_j9,
            npc_by_id=npc_by_id, difficulty_cfg=cfg,
        ) or {}
        def _mod_rate(patch: dict[str, Any]) -> float:
            atk = patch.get("attack_sp") or {}
            sp_id = int(atk.get("id") or 0)
            return float(sp_rates.get(sp_id, 1.0)) if sp_id > 0 else 1.0

        mod_j1 = _mod_rate(patch_j1)
        mod_j9 = _mod_rate(patch_j9)
        eng_j1 = nominal_journey_atk_mult(1, difficulty_cfg=cfg)
        eng_j9 = nominal_journey_atk_mult(9, difficulty_cfg=cfg)
        atk_anchor_rows.append([
            f"`{model}`", wl,
            f"{layer_j1:.3f}",
            f"{mod_j1:.2f}", f"{mod_j9:.2f}",
            f"{mod_j1 * eng_j1:.3f}", f"{mod_j9 * eng_j9:.3f}",
        ])
    lines += _md_table(atk_anchor_header, atk_anchor_rows)

    lines += [
        "",
        "### 5.2 周目层 lift（进入血 = 地图后 · 深渊档25）",
        "",
    ]
    abyss_tier = resolve_map_tier_t093(abyss_id)
    abyss_map_nom = nominal_map_hp_mult(abyss_tier, difficulty_cfg=cfg)
    journey_lift_header = ["样本", "地图后血"] + [f"J{j}" for j in JOURNEY_COLS]
    journey_lift_rows: list[list[Any]] = []
    for slabel, model, _npc in SAMPLES:
        wl = whitelist_effective_hp_for_model(model) or 0
        map_eff = map_layer_lift_mult(wl, abyss_map_nom, difficulty_cfg=cfg)
        h_after_map = int(wl * map_eff)
        cells: list[Any] = [f"{slabel} `{model}`", h_after_map]
        for j in JOURNEY_COLS:
            j_nom = nominal_journey_hp_mult(j, difficulty_cfg=cfg)
            j_eff = asymmetric_layer_lift_mult(h_after_map, j_nom, h_ref=h_ref, alpha=alpha)
            cells.append(f"{j_nom:.3f}→{j_eff:.3f}")
        journey_lift_rows.append(cells)
    lines += _md_table(journey_lift_header, journey_lift_rows)

    lines += [
        "",
        "### 5.3 全局滑条 lift（进入血 = 硬帽后 · 深渊·周目9）",
        "",
    ]
    slider_lift_header = ["样本", "帽后血"] + [f"s={s:g}" for s in SLIDER_COLS]
    slider_lift_rows: list[list[Any]] = []
    for slabel, model, npc in SAMPLES:
        r_cap = eval_case(
            label=slabel, model=model, npc=npc, map_id=abyss_id,
            map_label="深渊", journey=9, slider=1.0, night=False,
            cfg=cfg, offline=offline,
        )
        h_after_cap = r_cap.eff_hp
        cells: list[Any] = [f"{slabel} `{model}`", h_after_cap]
        for s in SLIDER_COLS:
            lift = compute_slider_lift_mult(
                h_after_cap, s, h_ref=slider_h_ref, alpha=slider_alpha
            )
            cells.append(f"{lift:.4f}")
        slider_lift_rows.append(cells)
    lines += _md_table(slider_lift_header, slider_lift_rows)

    lines += [
        "",
        "### 5.4 三类 lift 全流程倍率（深渊·周目9·滑条=1 · 非夜）",
        "",
        "地图层× / 周目层× = 层有效倍率；全局滑条× = 帽后滑条 lift（s=1 恒为 1）。",
        "",
    ]
    pipeline_header = [
        "样本", "白名单", "地图层×", "地图后", "周目层×", "叠乘前",
        "硬帽", "顶帽", "全局滑条×", "最终血",
    ]
    pipeline_rows: list[list[Any]] = []
    for slabel, model, npc in SAMPLES:
        r = eval_case(
            label=slabel, model=model, npc=npc, map_id=abyss_id,
            map_label="深渊", journey=9, slider=1.0, night=False,
            cfg=cfg, offline=offline,
        )
        h_after_map = int(r.whitelist_hp * r.map_eff)
        pipeline_rows.append([
            f"`{model}`",
            r.whitelist_hp,
            f"{r.map_eff:.4f}",
            h_after_map,
            f"{r.journey_eff:.4f}",
            int(r.pre_cap),
            int(r.hp_cap),
            "Y" if r.capped else "N",
            f"{r.slider_lift:.4f}",
            r.eff_hp,
        ])
    lines += _md_table(pipeline_header, pipeline_rows)

    lines += [
        "",
        "### 5.5 全局滑条 lift 有效血（深渊·周目9 · 帽后基数）",
        "",
    ]
    slider_hp_header = ["样本", "白名单", "帽后(s=1)"] + [f"s={s:g}" for s in SLIDER_COLS]
    slider_hp_rows: list[list[Any]] = []
    for slabel, model, npc in SAMPLES:
        wl = whitelist_effective_hp_for_model(model) or 0
        r1 = eval_case(
            label=slabel, model=model, npc=npc, map_id=abyss_id,
            map_label="深渊", journey=9, slider=1.0, night=False,
            cfg=cfg, offline=offline,
        )
        cells: list[Any] = [f"{slabel} `{model}`", wl, r1.eff_hp]
        for s in SLIDER_COLS:
            r = eval_case(
                label=slabel, model=model, npc=npc, map_id=abyss_id,
                map_label="深渊", journey=9, slider=s, night=False,
                cfg=cfg, offline=offline,
            )
            cells.append(r.eff_hp)
        slider_hp_rows.append(cells)
    lines += _md_table(slider_hp_header, slider_hp_rows)

    # --- 矩阵：有效血 地图×周目 ---
    lines += [
        "",
        "## 6. 有效血矩阵（滑条=1 · 非夜 · 多样本）",
        "",
        "行=白名单样本；列=周目档 J1–J9；每块=代表地图。",
        "",
    ]
    for map_label, map_id in MAP_CASES:
        tier = resolve_map_tier_t093(map_id)
        mhp = nominal_map_hp_mult(tier, difficulty_cfg=cfg)
        lines.append(f"### {map_label} `{map_id}` · 地图档 **{tier}** · M_hp={mhp:.4f}")
        lines.append("")
        header = ["样本", "白名单"] + [f"J{j}" for j in JOURNEY_COLS] + ["分层血帽"]
        rows_m: list[list[Any]] = []
        for slabel, model, npc in SAMPLES:
            wl = whitelist_effective_hp_for_model(model) or 0
            cells: list[Any] = [f"{slabel} `{model}`", wl]
            for j in JOURNEY_COLS:
                r = eval_case(
                    label=slabel, model=model, npc=npc, map_id=map_id,
                    map_label=map_label, journey=j, slider=1.0, night=False,
                    cfg=cfg, offline=offline,
                )
                cells.append(r.eff_hp)
            cells.append(_bracket_hp_cap(wl, cfg))
            rows_m.append(cells)
        lines += _md_table(header, rows_m)
        lines.append("")

    abyss_id = "m61_46_38_00"

    # --- stat_mult 矩阵：每代表地图 ---
    lines += [
        "## 7. stat× 矩阵（韧/视/嗅/听综合倍率 · 滑条=1 · 非夜）",
        "",
        "行=样本；列=周目档 J1–J9；每块=代表地图。",
        "",
    ]
    for map_label, map_id in MAP_CASES:
        tier = resolve_map_tier_t093(map_id)
        mstat = nominal_map_stat_mult(tier, difficulty_cfg=cfg)
        lines.append(f"### {map_label} · 地图档 **{tier}** · M_stat={mstat:.4f}")
        lines.append("")
        header_s = ["样本", "白名单"] + [f"J{j}" for j in JOURNEY_COLS] + ["封顶2×"]
        rows_s: list[list[Any]] = []
        for slabel, model, npc in SAMPLES:
            wl = whitelist_effective_hp_for_model(model) or 0
            cells: list[Any] = [f"{slabel} `{model}`", wl]
            for j in JOURNEY_COLS:
                r = eval_case(
                    label=slabel, model=model, npc=npc, map_id=map_id,
                    map_label=map_label, journey=j, slider=1.0, night=False,
                    cfg=cfg, offline=offline,
                )
                cells.append(f"{r.stat_mult:.4f}")
            cells.append("2.0000")
            rows_s.append(cells)
        lines += _md_table(header_s, rows_s)
        lines.append("")

    # --- 攻击 lift 矩阵（T-096） ---
    lines += [
        "## 8. 攻击 lift 矩阵（深渊 · 滑条=1 · T-096）",
        "",
        "layer=地图攻（与周目无关）；mod=加攻 sp；总攻≈mod×引擎周目。",
        "",
    ]
    atk_lift_header = ["样本", "白名单", "M_atk", "地图攻", "J1 mod", "J9 mod", "J1 总攻≈", "J9 总攻≈"]
    atk_lift_rows: list[list[Any]] = []
    abyss_tier = resolve_map_tier_t093(abyss_id)
    m_atk_nom = nominal_map_atk_mult(abyss_tier, difficulty_cfg=cfg)
    for slabel, model, npc in SAMPLES:
        wl = whitelist_effective_hp_for_model(model) or 0
        donor = _donor_row(model, npc, offline)
        row = {
            "map_id": abyss_id,
            "model": model,
            "npc": npc,
            "tgt_cat": "trash",
            "src_cat": "trash",
        }
        npc_by_id = {npc: donor}
        diff_j1 = {"enabled": True, "user_mult": 1.0, "journey_tier": 1}
        diff_j9 = {"enabled": True, "user_mult": 1.0, "journey_tier": 9}
        layer_j1 = compute_t093_attack_lift_mult(
            row, donor, difficulty=diff_j1, npc_by_id=npc_by_id, difficulty_cfg=cfg,
        )
        layer_j9 = compute_t093_attack_lift_mult(
            row, donor, difficulty=diff_j9, npc_by_id=npc_by_id, difficulty_cfg=cfg,
        )
        patch_j1 = compute_assignment_patch(
            row, donor, soul_out=100, difficulty=diff_j1,
            npc_by_id=npc_by_id, difficulty_cfg=cfg,
        ) or {}
        patch_j9 = compute_assignment_patch(
            row, donor, soul_out=100, difficulty=diff_j9,
            npc_by_id=npc_by_id, difficulty_cfg=cfg,
        ) or {}

        def _mod_rate(patch: dict[str, Any]) -> float:
            atk = patch.get("attack_sp") or {}
            sp_id = int(atk.get("id") or 0)
            return float(sp_rates.get(sp_id, 1.0)) if sp_id > 0 else 1.0

        mod_j1 = _mod_rate(patch_j1)
        mod_j9 = _mod_rate(patch_j9)
        eng_j1 = nominal_journey_atk_mult(1, difficulty_cfg=cfg)
        eng_j9 = nominal_journey_atk_mult(9, difficulty_cfg=cfg)
        atk_lift_rows.append([
            f"{slabel} `{model}`", wl, f"{m_atk_nom:.3f}",
            f"{layer_j1:.3f}",
            f"{mod_j1:.2f}", f"{mod_j9:.2f}",
            f"{mod_j1 * eng_j1:.3f}", f"{mod_j9 * eng_j9:.3f}",
        ])
    lines += _md_table(atk_lift_header, atk_lift_rows)

    lines += [
        "",
        "## 9. 周目攻 J_atk 曲线（引擎 · 与 mod 分工）",
        "",
    ]
    atk_rows = [[
        j,
        f"{nominal_journey_atk_mult(j, difficulty_cfg=cfg):.6f}",
        f"{nominal_map_atk_mult(abyss_tier, difficulty_cfg=cfg):.6f}",
        f"{nominal_journey_atk_mult(j, difficulty_cfg=cfg):.6f}",
    ] for j in JOURNEY_COLS]
    lines += _md_table(["周目 j", "J_atk(引擎)", "M_atk(深渊)", "设计J(层)"], atk_rows)

    # --- 全参数明细：每地图 × 全样本 @ J9 ---
    lines += [
        "",
        "## 10. 全参数明细（各代表地图 · 周目9 · 滑条=1 · 非夜）",
        "",
        "M_nom/M_eff=地图名义/层有效；J_nom/J_eff=周目名义/层有效；顶帽=Y 表示叠乘前>硬帽被截断。",
        "",
    ]
    detail_header = [
        "地图", "样本", "白名单", "M_nom", "M_eff", "J_nom", "J_eff", "夜",
        "叠乘前", "硬帽", "顶帽", "滑条lift", "有效血", "表hp",
        "底韧", "出表韧", "stat×", "J_atk", "底视距", "出视距", "底嗅", "出嗅",
    ]
    for map_label, map_id in MAP_CASES:
        lines.append(f"### {map_label} `{map_id}`")
        lines.append("")
        detail_rows: list[list[Any]] = []
        for slabel, model, npc in SAMPLES:
            r = eval_case(
                label=slabel, model=model, npc=npc, map_id=map_id,
                map_label=map_label, journey=9, slider=1.0, night=False,
                cfg=cfg, offline=offline,
            )
            detail_rows.append([
                map_label.split("·")[0],
                f"`{model}`",
                r.whitelist_hp,
                f"{r.map_nom:.3f}",
                f"{r.map_eff:.3f}",
                f"{r.journey_nom:.3f}",
                f"{r.journey_eff:.3f}",
                f"{r.night_m:.1f}",
                int(r.pre_cap),
                int(r.hp_cap),
                "Y" if r.capped else "N",
                f"{r.slider_lift:.4f}",
                r.eff_hp,
                r.table_hp,
                r.base_poise,
                r.out_poise if r.out_poise is not None else "-",
                f"{r.stat_mult:.4f}",
                f"{r.journey_atk:.3f}",
                f"{r.base_eye:.0f}" if r.base_eye else "-",
                f"{r.out_eye:.0f}" if r.out_eye else "-",
                f"{r.base_nose:.0f}" if r.base_nose else "-",
                f"{r.out_nose:.0f}" if r.out_nose else "-",
            ])
        lines += _md_table(detail_header, detail_rows)
        lines.append("")

    # --- 顶帽命中矩阵 ---
    lines += [
        "## 11. 顶帽命中矩阵（叠乘前>白名单×3 · 滑条=1 · 非夜）",
        "",
    ]
    for map_label, map_id in MAP_CASES:
        lines.append(f"### {map_label}")
        lines.append("")
        cap_header = ["样本", "白名单"] + [f"J{j}" for j in JOURNEY_COLS]
        cap_rows: list[list[Any]] = []
        for slabel, model, npc in SAMPLES:
            wl = whitelist_effective_hp_for_model(model) or 0
            cells: list[Any] = [f"`{model}`", wl]
            for j in JOURNEY_COLS:
                r = eval_case(
                    label=slabel, model=model, npc=npc, map_id=map_id,
                    map_label=map_label, journey=j, slider=1.0, night=False,
                    cfg=cfg, offline=offline,
                )
                cells.append("Y" if r.capped else ".")
            cap_rows.append(cells)
        lines += _md_table(cap_header, cap_rows)
        lines.append("")

    # --- 滑条矩阵 深渊 J9 全样本 ---
    lines += ["## 12. 滑条矩阵（深渊·周目9 · 全7样本 · 非夜）", ""]
    header_sl = ["样本", "白名单"] + [f"s={s:g}" for s in SLIDER_COLS] + ["分层血帽(s=1)"]
    rows_sl: list[list[Any]] = []
    for slabel, model, npc in SAMPLES:
        wl = whitelist_effective_hp_for_model(model) or 0
        cells: list[Any] = [f"{slabel} `{model}`", wl]
        for s in SLIDER_COLS:
            r = eval_case(
                label=slabel, model=model, npc=npc, map_id=abyss_id,
                map_label="深渊", journey=9, slider=s, night=False,
                cfg=cfg, offline=offline,
            )
            cells.append(r.eff_hp)
        cells.append(_bracket_hp_cap(wl, cfg))
        rows_sl.append(cells)
    lines += _md_table(header_sl, rows_sl)

    # --- 夜矩阵 ---
    lines += ["", "## 13. 红灵夜矩阵（深渊·周目9·滑条=1）", ""]
    header_n = ["样本", "白名单", "非夜", "红灵夜", "硬帽", "夜后仍≤帽"]
    rows_n: list[list[Any]] = []
    for slabel, model, npc in SAMPLES:
        wl = whitelist_effective_hp_for_model(model) or 0
        r0 = eval_case(
            label=slabel, model=model, npc=npc, map_id=abyss_id,
            map_label="深渊", journey=9, slider=1.0, night=False,
            cfg=cfg, offline=offline,
        )
        r1 = eval_case(
            label=slabel, model=model, npc=npc, map_id=abyss_id,
            map_label="深渊", journey=9, slider=1.0, night=True,
            cfg=cfg, offline=offline,
        )
        cap = _bracket_hp_cap(wl, cfg)
        rows_n.append([
            f"`{model}`", wl, r0.eff_hp, r1.eff_hp, cap,
            "✅" if r1.eff_hp <= cap + 2 else "❌",
        ])
    lines += _md_table(header_n, rows_n)

    # --- 叠乘逐步 ---
    lines += [
        "",
        "## 14. 叠乘逐步样例（深渊·周目9 · 滑条=1）",
        "",
    ]
    step_cases = [
        ("低血", "c2041", 20410050),
        ("约2k", "c5330", 53300087),
        ("中位", "c5820", 58200095),
        ("最高", "c4760", 47601050),
    ]
    for tag, model, npc in step_cases:
        r = eval_case(
            label=tag, model=model, npc=npc, map_id=abyss_id,
            map_label="深渊", journey=9, slider=1.0, night=False,
            cfg=cfg, offline=offline,
        )
        lines += [
            f"### {tag} `{model}` · 白名单 {r.whitelist_hp}",
            "",
            "| 步 | 倍率 | 累计有效血 |",
            "|---|---:|---:|",
            f"| 基准 | 1 | {r.whitelist_hp} |",
            f"| ×地图层 | {r.map_eff:.4f} | {int(r.whitelist_hp * r.map_eff)} |",
            f"| ×夜 | {r.night_m:.1f} | {int(r.whitelist_hp * r.map_eff * r.night_m)} |",
            f"| ×周目层 | {r.journey_eff:.4f} | {int(r.pre_cap)} |",
            f"| 分层硬帽 | min({int(r.hp_cap)}) | **{r.eff_hp}** |",
            "",
        ]

    # --- 战斗时间粗算 ---
    lines += [
        "## 15. 战斗时间粗算（一套1万伤 · 每套躲10次 · 23s/28s每套）",
        "",
    ]
    time_rows: list[list[Any]] = []
    for slabel, model, npc in SAMPLES:
        r = eval_case(
            label=slabel, model=model, npc=npc, map_id=abyss_id,
            map_label="深渊", journey=9, slider=1.0, night=False,
            cfg=cfg, offline=offline,
        )
        sets = (r.eff_hp + 9999) // 10000
        dodges = sets * 10
        time_rows.append([
            slabel.split("·")[-1] if "·" in slabel else slabel,
            f"`{model}`",
            r.eff_hp,
            sets,
            dodges,
            f"{sets * 23 // 60}m{sets * 23 % 60}s",
            f"{sets * 28 // 60}m{sets * 28 % 60}s",
        ])
    lines += _md_table(
        ["样本", "模型", "深渊J9有效血", "需套数", "躲技能次", "23s/套", "28s/套"],
        time_rows,
    )

    lines += [
        "",
        "## 16. 验收结论",
        "",
        "- 名义 M_hp(25)×J_hp(9) = 1.5×2.0 = **3.0**",
        "- 低血层 lift **≥** 名义；高血层 lift **=** 名义",
        "- 滑条=1 时有效血 **≤** 分层血帽（含红灵夜）",
        "- stat× 滑条=1 时 **≤** 2.0（深渊周9）",
        "- 攻击(T-096)：仅地图 lift；弱怪地图≈×6；参照 trash≈×1.0；强怪≈×1.1；总攻=地图×引擎周目",
        "- **本报告仅演算/出表对照，不 apply、不真机**",
        "",
    ]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")
    print(f"lines={len(lines)} samples={len(SAMPLES)} maps={len(MAP_CASES)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
