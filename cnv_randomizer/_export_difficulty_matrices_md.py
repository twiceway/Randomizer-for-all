"""Export map×NG difficulty matrices → reports/敌人难度成长审计.md §6.

只导出两个示例：混种小怪（trash）· 接肢葛瑞克（major_boss）。
每个参数单独一张表，方便对照。
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from boss_npc_detect import load_npc_rows
from enemy_difficulty import (
    REGION_HP_MULT,
    assignment_effective_hp_at_ng,
    compute_assignment_patch,
    compute_row_adaptive_lift,
    load_difficulty_cfg,
    normalize_difficulty_settings,
    resolve_adaptive_hp_out,
    resolve_adaptive_poise_out,
    resolve_assignment_hp_out,
    resolve_target_curve_poise_out,
    rune_category_uses_hp_balance,
    scale_rune_by_assignment_hp,
    scale_rune_by_slot_tier,
    scale_rune_by_target_curve,
    target_progression_enabled,
    tier_to_ng_region_sp_effect,
    tier_to_region_sp_effect,
)
from enemy_think_difficulty import think_anchor_targets
from paths import OUTPUT_REPORTS, resolve_game_dir

AUDIT_REPORT = OUTPUT_REPORTS / "敌人难度成长审计.md"
MATRIX_MARKER = "## 6. 地图×周目参数矩阵"

TIER_MAPS = {
    1: "m10_01_00_00",
    2: "m11_05_00_00",
    3: "m12_01_00_00",
    4: "m10_00_00_00",
    5: "m30_17_00_00",
    6: "m31_00_00_00",
    7: "m32_00_00_00",
    8: "m60_08_10_02",
    9: "m31_81_00_00",
}

# 两个对照样本：路边小怪 vs 主线大 Boss
EXAMPLES = [
    {
        "key": "trash",
        "zh": "混种小怪",
        "model": "c3451",
        "npc": 34510030,
        "tgt_cat": "trash",
        "pool": "路边小怪",
        "soul_override": None,  # 用 NpcParam.getSoul
    },
    {
        "key": "godrick",
        "zh": "接肢葛瑞克",
        "model": "c4750",
        "npc": 47500014,
        "tgt_cat": "major_boss",
        "pool": "主线大 Boss",
        "soul_override": 20000,  # Boss 卢恩在 GameArea（NpcParam.getSoul=0）
    },
]

NG_HEADERS = ["一周目", "NG+1", "NG+2", "NG+3", "NG+4", "NG+5", "NG+6", "NG+7"]


def load_clearcount(csv_dir: Path) -> tuple[dict[int, float], dict[int, float]]:
    path = csv_dir / "ClearCountCorrectParam.csv"
    hp: dict[int, float] = {0: 1.0}
    atk: dict[int, float] = {0: 1.0}
    if not path.is_file():
        return hp, atk
    with path.open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            try:
                rid = int(row["ID"])
            except (KeyError, TypeError, ValueError):
                continue
            if rid > 7:
                continue
            hp[rid] = float(row.get("MaxHpRate") or row.get("maxHpRate") or 1)
            atk[rid] = float(row.get("PhysicsAttackRate") or row.get("physicsAttackRate") or 1)
    # 一周目 ClearCount ID=0 表值为 0（占位）；引擎实际按 1.0
    if hp.get(0, 1.0) == 0:
        hp[0] = 1.0
    if atk.get(0, 1.0) == 0:
        atk[0] = 1.0
    return hp, atk


def load_attack_sp_rates(csv_dir: Path) -> dict[int, float]:
    path = csv_dir / "SpEffectParam.csv"
    out: dict[int, float] = {}
    if not path.is_file():
        return out
    with path.open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            try:
                sid = int(row["ID"])
            except (KeyError, ValueError):
                continue
            try:
                out[sid] = float(row.get("physicsAttackPowerRate") or 1)
            except (TypeError, ValueError):
                out[sid] = 1.0
    return out


def effective_hp_ng(
    table_hp: int,
    slot_tier: int,
    ng_cycle: int,
    cc_hp: dict[int, float],
    difficulty_cfg: dict[str, Any],
) -> int:
    if table_hp <= 0:
        return 0
    if target_progression_enabled(difficulty_cfg):
        return assignment_effective_hp_at_ng(
            table_hp, slot_tier, ng_cycle, difficulty_cfg=difficulty_cfg
        )
    j1_id = tier_to_region_sp_effect(slot_tier, difficulty_cfg)
    j1 = REGION_HP_MULT.get(j1_id, 1.0)
    if ng_cycle <= 0:
        return max(1, int(round(table_hp * j1)))
    ng_id = tier_to_ng_region_sp_effect(slot_tier, difficulty_cfg)
    ng = REGION_HP_MULT.get(ng_id, 1.0)
    cc = cc_hp.get(ng_cycle, 1.0)
    return max(1, int(round(table_hp * j1 * ng * cc)))


def matrix_table(rows: list[tuple[str, list[Any]]]) -> str:
    header = "| 地图档 | " + " | ".join(NG_HEADERS) + " |"
    sep = "|--------|" + "|".join(["--------:"] * len(NG_HEADERS)) + "|"
    body_lines = []
    for label, vals in rows:
        cells = " | ".join(str(v) for v in vals)
        body_lines.append(f"| **{label}** | {cells} |")
    return "\n".join([header, sep, *body_lines])


def tier_col_as_matrix(by_tier: dict[int, Any]) -> str:
    """仅随地图档变的参数：仍画成矩阵，周目列同值（一眼看懂「周目不涨」）。"""
    rows = []
    for t in range(1, 10):
        label = f"T{t}" + ("（=T8）" if t == 9 else "")
        v = by_tier[t]
        rows.append((label, [v] * 8))
    return matrix_table(rows)


def make_row(
    ex: dict[str, Any],
    donor_row: dict[str, str],
    *,
    difficulty: dict[str, Any],
    npc_by_id: dict[int, dict[str, str]],
    difficulty_cfg: dict[str, Any],
    cc_hp: dict[int, float],
    cc_atk: dict[int, float],
    atk_rates: dict[int, float],
) -> dict[str, Any]:
    npc = int(ex["npc"])
    base_hp = int(donor_row.get("hp") or 0)
    base_poise = int(donor_row.get("defFlickPower") or 0)
    if ex.get("soul_override") is not None:
        base_soul = int(ex["soul_override"])
    else:
        base_soul = int(donor_row.get("getSoul") or 0)

    hp_table: dict[int, int] = {}
    hp_eff: dict[int, dict[int, int]] = {}
    poise: dict[int, int] = {}
    lift: dict[int, float] = {}
    attack_label: dict[int, str] = {}
    attack_mult: dict[int, dict[int, float]] = {}
    rune: dict[int, int] = {}
    think_eye: dict[int, str] = {}

    use_curve = target_progression_enabled(difficulty_cfg)

    for tier, map_id in TIER_MAPS.items():
        row = {
            "map_id": map_id,
            "model": ex["model"],
            "npc": npc,
            "tgt_cat": ex["tgt_cat"],
            "src_cat": ex["tgt_cat"],
            "src_npc": 0,
        }
        adaptive = compute_row_adaptive_lift(
            row,
            donor_row,
            difficulty=difficulty,
            npc_by_id=npc_by_id,
            difficulty_cfg=difficulty_cfg,
        )
        lift_v = float(adaptive.get("lift") or 0.0)
        lift[tier] = round(lift_v, 3)

        if use_curve:
            hp_out = resolve_assignment_hp_out(
                row,
                donor_row,
                difficulty=difficulty,
                npc_by_id=npc_by_id,
                difficulty_cfg=difficulty_cfg,
            )
            poise[tier] = resolve_target_curve_poise_out(
                donor_row,
                row=row,
                difficulty=difficulty,
                difficulty_cfg=difficulty_cfg,
            )
        else:
            hp_out = resolve_adaptive_hp_out(
                row,
                donor_row,
                difficulty=difficulty,
                npc_by_id=npc_by_id,
                difficulty_cfg=difficulty_cfg,
                lift=lift_v,
                donor_eff_hp=int(adaptive.get("donor_eff_hp") or 0),
                anchor_eff_hp=int(adaptive.get("anchor_eff_hp") or 0),
            )
            poise[tier] = resolve_adaptive_poise_out(
                donor_row,
                row=row,
                difficulty=difficulty,
                difficulty_cfg=difficulty_cfg,
                lift=lift_v,
            )
        hp_table[tier] = hp_out

        patch = (
            compute_assignment_patch(
                row,
                donor_row,
                soul_out=base_soul,
                difficulty=difficulty,
                npc_by_id=npc_by_id,
                difficulty_cfg=difficulty_cfg,
            )
            or {}
        )
        atk = patch.get("attack_sp")
        mod_atk = 1.0
        if atk:
            sp_id = int(atk.get("id") or 0)
            mod_atk = float(atk_rates.get(sp_id, 1.0))
            attack_label[tier] = f"sp{sp_id}×{mod_atk:.2f}"
        else:
            attack_label[tier] = "无加攻sp"

        attack_mult[tier] = {}
        for ng in range(8):
            eng = float(cc_atk.get(ng, 1.0) if ng > 0 else 1.0)
            attack_mult[tier][ng] = round(mod_atk * eng, 3)

        if use_curve:
            soul_scaled = scale_rune_by_target_curve(
                base_soul,
                row,
                difficulty=difficulty,
                difficulty_cfg=difficulty_cfg,
            )
        elif rune_category_uses_hp_balance(ex["tgt_cat"], difficulty_cfg):
            soul_scaled = scale_rune_by_assignment_hp(
                base_soul,
                row,
                donor_row,
                difficulty=difficulty,
                npc_by_id=npc_by_id,
                difficulty_cfg=difficulty_cfg,
            )
        else:
            # major_boss / night：走地图档卢恩（不走 T-058 血量对称）
            soul_scaled = scale_rune_by_slot_tier(
                base_soul,
                map_id,
                difficulty_cfg=difficulty_cfg,
            )
        if patch.get("get_soul") and (
            use_curve or rune_category_uses_hp_balance(ex["tgt_cat"], difficulty_cfg)
        ):
            soul_scaled = int(patch["get_soul"])
            soul_scaled = int(patch["get_soul"])
        rune[tier] = int(soul_scaled)

        hp_eff[tier] = {
            ng: effective_hp_ng(hp_out, tier, ng, cc_hp, difficulty_cfg) for ng in range(8)
        }

        if lift_v > 0:
            tgt = think_anchor_targets(tier, ex["tgt_cat"], difficulty_cfg=difficulty_cfg)
            eye_tgt = int(round(float(tgt.get("eye_dist", 0))))
            think_eye[tier] = str(eye_tgt)
        else:
            think_eye[tier] = "不改"

    return {
        "base_hp": base_hp,
        "base_poise": base_poise,
        "base_soul": base_soul,
        "hp_table": hp_table,
        "hp_eff": hp_eff,
        "poise": poise,
        "lift": lift,
        "attack_label": attack_label,
        "attack_mult": attack_mult,
        "rune": rune,
        "think_eye": think_eye,
    }


def render_example(ex: dict[str, Any], data: dict[str, Any], *, use_curve: bool = False) -> str:
    zh = ex["zh"]
    lines = [
        f"## A/B · {zh}",
        "",
        f"**是谁**：`{ex['model']}` / npc `{ex['npc']}` · 池 **{ex['pool']}**（`{ex['tgt_cat']}`）  ",
        f"**原版表**：基血 {data['base_hp']} · 基韧 {data['base_poise']} · 基卢恩 {data['base_soul']}  ",
        f"**怎么读**：行=地图档 T1~T9；列=一周目~NG+7。数字相同的列 = **周目不涨这个参数**。",
        "",
        f"### {zh} · 表1 · 有效血（打的时候看到的血）",
        "",
        "公式：表血 × 区域血倍 ×（NG 时再 × NG区域倍 × ClearCount血倍）",
        "",
        matrix_table(
            [
                (
                    f"T{t}" + ("（=T8）" if t == 9 else ""),
                    [data["hp_eff"][t][ng] for ng in range(8)],
                )
                for t in range(1, 10)
            ]
        ),
        "",
        f"### {zh} · 表2 · 表血（写进 NpcParam 的 hp，还没乘区域）",
        "",
        (
            "仅 baseline×1.05（T-065 关 lift；档差靠区域 sp）。**周目列相同**。"
            if use_curve
            else "含 baseline×1.05 + T-062 lift；**周目列相同**。"
        ),
        "",
        tier_col_as_matrix(data["hp_table"]),
        "",
        f"### {zh} · 表3 · T-062 弱皮补强 lift（0~1）",
        "",
        "越高 = 相对该图锚点越弱、补得越多。血/韧/加攻/Think 共用这一格。",
        "",
        tier_col_as_matrix({t: f"{data['lift'][t]:.3f}" for t in range(1, 10)}),
        "",
        f"### {zh} · 表4 · 韧性（defFlickPower 复制行）",
        "",
        "基韧为 0 时整表为 0（靠内含超韧，不是 bug）。**周目列相同**。",
        "",
        tier_col_as_matrix(data["poise"]),
        "",
        f"### {zh} · 表5 · 攻击总倍率（mod加攻sp × 引擎周目攻）",
        "",
        "小怪高图可能挂加攻 sp；主线大 Boss 默认**不加**攻击 sp（配置 skip）。"
        "周目变猛主要靠引擎 ClearCount。",
        "",
        "加攻 sp 标签：",
        "",
        tier_col_as_matrix(data["attack_label"]),
        "",
        "总攻击倍率（mod×引擎）：",
        "",
        matrix_table(
            [
                (
                    f"T{t}" + ("（=T8）" if t == 9 else ""),
                    [data["attack_mult"][t][ng] for ng in range(8)],
                )
                for t in range(1, 10)
            ]
        ),
        "",
        f"### {zh} · 表6 · Think 警戒距离锚点（eye_dist）",
        "",
        "lift>0 才向锚点靠拢；「不改」= 保持捐皮原 Think。**周目列相同**。",
        "",
        tier_col_as_matrix(data["think_eye"]),
        "",
        f"### {zh} · 表7 · 击杀卢恩（写进复制行）",
        "",
        (
            "小怪：按有效血对称缩放（T-058）。"
            if ex["tgt_cat"] == "trash"
            else "大 Boss：按地图档缩放（不走 T-058 血量对称）。"
        )
        + " **周目列相同**（引擎另有 SoulRate，本表不含）。",
        "",
        tier_col_as_matrix(data["rune"]),
        "",
    ]
    # 把第一个标题改成编号 A/B
    if ex["key"] == "trash":
        lines[0] = f"## A. {zh}（路边小怪）"
    else:
        lines[0] = f"## B. {zh}（主线大 Boss）"
    return "\n".join(lines)


def render_region_sp(difficulty_cfg: dict[str, Any]) -> str:
    rows = []
    for t in range(1, 10):
        j1 = tier_to_region_sp_effect(t, difficulty_cfg)
        ng = tier_to_ng_region_sp_effect(t, difficulty_cfg)
        rows.append(
            f"| T{t} | {j1} | ×{REGION_HP_MULT.get(j1, 1):.3f} | {ng} | ×{REGION_HP_MULT.get(ng, 1):.3f} |"
        )
    return "\n".join(
        [
            "| 地图档 | 一周目区域sp | 血倍 | NG区域sp | NG血倍 |",
            "|--------|-------------|-----|----------|--------|",
            *rows,
        ]
    )


def build_markdown() -> str:
    game_csv = resolve_game_dir() / "csv"
    npc_by_id = load_npc_rows(game_csv)
    difficulty_cfg = load_difficulty_cfg()
    difficulty = normalize_difficulty_settings({})
    use_curve = target_progression_enabled(difficulty_cfg)
    cc_hp, cc_atk = load_clearcount(game_csv)
    atk_rates = load_attack_sp_rates(game_csv)

    parts = [
        MATRIX_MARKER,
        "",
        "**生成**：`python cnv_randomizer/_export_difficulty_matrices_md.py`  ",
        "**日期**：2026-08-08  ",
        "**样本**：只保留两个对照 —— **混种小怪**（弱）vs **接肢葛瑞克**（强 Boss）",
        "",
        "### 怎么读（先看这 4 句）",
        "",
        "1. **行** = 地图难度档 T1（宁姆）→ T9（终盘）；**列** = 一周目 → NG+7。",
        "2. **表1 有效血** 才会随周目变厚；其它表若整列数字一样 = 周目不涨。",
        "3. "
        + (
            "**T-065**：全局重绑地图档/周目区域 sp（0.35 档 + 0.65 周目）；关 lift；表血仅 baseline×user_mult；葛瑞克只是验收样例。"
            if use_curve
            else "**小怪**高图常吃 T-062；**葛瑞克**相对「主线 Boss 锚点血」仍偏弱，也会吃 lift（表3），所以有效血会明显高于「只乘区域」。"
        ),
        "4. 全局还乘 `baseline 1.05 × user_mult`（默认 1.0），已含在表血里。",
        "",
        "### 共用 · 区域血倍（引擎 sp）",
        "",
        render_region_sp(difficulty_cfg),
        "",
        "### 共用 · 引擎周目攻击倍（全体敌人一样）",
        "",
        matrix_table(
            [
                (
                    "全体",
                    [round(cc_atk.get(ng, 1.0) if ng > 0 else 1.0, 3) for ng in range(8)],
                )
            ]
        ),
        "",
    ]

    for ex in EXAMPLES:
        donor = npc_by_id.get(int(ex["npc"]))
        if not donor:
            parts.append(f"## {ex['zh']}\n\n*NpcParam 未找到 {ex['npc']}*\n")
            continue
        data = make_row(
            ex,
            donor,
            difficulty=difficulty,
            npc_by_id=npc_by_id,
            difficulty_cfg=difficulty_cfg,
            cc_hp=cc_hp,
            cc_atk=cc_atk,
            atk_rates=atk_rates,
        )
        parts.append(render_example(ex, data, use_curve=use_curve))

    parts.append(
        "---\n\n"
        "*数据：`Game/csv` + `enemy_difficulty.json`；葛瑞克基卢恩取 GameArea **20000**"
        "（NpcParam.getSoul=0）。*"
    )
    return "\n".join(parts)


def main() -> None:
    md_path = AUDIT_REPORT
    text = md_path.read_text(encoding="utf-8")
    new_section = build_markdown()
    if MATRIX_MARKER in text:
        head = text.split(MATRIX_MARKER, 1)[0].rstrip()
        if head.endswith("---"):
            head = head.rsplit("---", 1)[0].rstrip()
        out = head + "\n\n" + new_section + "\n"
    else:
        head = text.rstrip()
        if head.endswith("---"):
            head = head.rsplit("---", 1)[0].rstrip()
        out = head + "\n\n" + new_section + "\n"
    md_path.write_text(out, encoding="utf-8")
    print(f"Wrote matrices to {md_path}")


if __name__ == "__main__":
    main()
