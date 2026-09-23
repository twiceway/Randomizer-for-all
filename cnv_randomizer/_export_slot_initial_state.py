"""Export MSB enemy slot initial-state catalog from enemy_index.json."""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
INDEX_PATH = SCRIPT_DIR / "cache" / "enemy_index.json"
OUT_MD = SCRIPT_DIR.parent / "reports" / "MSB槽位初始状态全表.md"
OUT_JSON = SCRIPT_DIR.parent / "reports" / "MSB槽位初始状态全表.json"

AERIAL_PREFIXES = (
    "c6001", "c4560", "c4561", "c4562", "c4563",
    "c4500", "c4501", "c4502", "c4503", "c4504", "c4505",
    "c4510", "c4511", "c4520",
)
SCRIPTED_FLYER_PREFIXES = ("c4980", "c6260", "c6270")
PERCH_PREFIXES = ("c4210", "c3000")
DECORATIVE_CORPSE_PREFIXES = ("c3661", "c3662", "c4711")

MSB_PARAM_KEYS = (
    "map_id", "name", "model", "npc", "think", "chara", "entity_id",
    "walk_route", "backup_anim", "talk_id", "chr_activate", "collision_part",
    "pos_x", "pos_y", "pos_z",
)


def _pref(model: str, prefixes: tuple[str, ...]) -> bool:
    m = (model or "").lower()
    return any(m.startswith(p) for p in prefixes)


def is_patrol(slot: dict) -> bool:
    return bool(str(slot.get("walk_route") or "").strip())


def placement_kind(slot: dict) -> str:
    """enemy_randomizer_core._slot_placement_kind"""
    model = str(slot.get("model", ""))
    backup = int(slot.get("backup_anim", -1) or -1)
    walk = str(slot.get("walk_route") or "").strip()
    collision = str(slot.get("collision_part") or "").strip()
    if _pref(model, AERIAL_PREFIXES):
        return "aerial_model"
    if backup > 0 and not walk:
        return "perch_or_squat"
    if collision and not walk:
        return "collision_anchor"
    if walk:
        return "patrol"
    return "ground"


def is_standing_slot(slot: dict) -> bool:
    """MsbEnemyPoc.IsStandingSlot (换模前判定)"""
    if is_patrol(slot):
        return False
    model = str(slot.get("model", ""))
    if _pref(model, SCRIPTED_FLYER_PREFIXES) or _pref(model, AERIAL_PREFIXES):
        return False
    if int(slot.get("backup_anim", -1) or -1) > 0:
        return False
    if int(slot.get("chr_activate", 0) or 0) != 0:
        return False
    collision = str(slot.get("collision_part") or "").strip()
    if collision and not _pref(model, PERCH_PREFIXES) and not _pref(model, DECORATIVE_CORPSE_PREFIXES):
        return False
    return True


def apply_slot_class(slot: dict) -> str:
    """MSB apply 三分（契约 §MSB apply 捐皮出场）"""
    if is_patrol(slot):
        return "patrol_keep_initial"
    if is_standing_slot(slot):
        return "standing_keep_initial"
    return "other_use_donor_behavior"


def pose_label(slot: dict) -> str:
    backup = int(slot.get("backup_anim", -1) or -1)
    walk = str(slot.get("walk_route") or "").strip()
    model = str(slot.get("model", ""))
    collision = str(slot.get("collision_part") or "").strip()
    chr_act = int(slot.get("chr_activate", 0) or 0)

    if walk:
        return "patrol"
    if _pref(model, AERIAL_PREFIXES):
        return "aerial_model"
    if _pref(model, SCRIPTED_FLYER_PREFIXES):
        return "scripted_flyer"
    if _pref(model, DECORATIVE_CORPSE_PREFIXES):
        return "decorative_corpse"
    if _pref(model, PERCH_PREFIXES) and collision:
        return "perch_collision"
    if backup > 0:
        return f"sit_squat_backup_{backup}"
    if collision:
        return "collision_anchor_no_backup"
    if chr_act != 0:
        return f"chr_activate_{chr_act}"
    return "ground_stand"


def slot_row(slot: dict) -> dict:
    row = {k: slot.get(k) for k in MSB_PARAM_KEYS}
    if slot.get("src_cat"):
        row["src_cat"] = slot.get("src_cat")
    tags = slot.get("slot_tags") or {}
    if tags:
        row["map_kind"] = tags.get("map_kind")
    row["placement_kind"] = placement_kind(slot)
    row["apply_slot_class"] = apply_slot_class(slot)
    row["pose_label"] = pose_label(slot)
    return row


def main() -> None:
    raw = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    slots = raw.get("slots") or []
    enriched = [slot_row(s) for s in slots]

    apply_ctr = Counter(r["apply_slot_class"] for r in enriched)
    placement_ctr = Counter(r["placement_kind"] for r in enriched)
    pose_ctr = Counter(r["pose_label"] for r in enriched)
    backup_ctr = Counter(int(s.get("backup_anim", -1) or -1) for s in slots)

    by_backup: dict[int, list[dict]] = defaultdict(list)
    for r in enriched:
        b = int(r.get("backup_anim", -1) or -1)
        if len(by_backup[b]) < 5:
            by_backup[b].append(r)

    maps = sorted({r["map_id"] for r in enriched})

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "source": str(INDEX_PATH),
                "index_generated_at": raw.get("generated_at"),
                "maps_scanned": raw.get("maps_scanned"),
                "slot_count": len(enriched),
                "summary": {
                    "apply_slot_class": dict(apply_ctr),
                    "placement_kind": dict(placement_ctr),
                    "pose_label": dict(pose_ctr.most_common(50)),
                    "backup_anim_counts": dict(sorted(backup_ctr.items())),
                },
                "slots": enriched,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    lines = [
        "# MSB 敌人槽位初始状态全表",
        "",
        f"**生成**：`cnv_randomizer/_export_slot_initial_state.py` · {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
        f"**数据源**：`enemy_index.json`（`maps_scanned={raw.get('maps_scanned')}` · 槽 `{len(enriched)}`）",
        f"**全量 JSON**：[`MSB槽位初始状态全表.json`](./MSB槽位初始状态全表.json)",
        "",
        "## MSB 参数字段（每槽一行）",
        "",
        "| 字段 | MSB 含义 |",
        "|------|----------|",
        "| `walk_route` | 巡逻路名；非空 → 巡逻槽 |",
        "| `backup_anim` | BackupEventAnimID；>0 且无巡逻 → 坐/蹲/躺等预设姿态 |",
        "| `collision_part` | 碰撞挂靠部件名（檐、地面片等） |",
        "| `chr_activate` | ChrActivateCondParamID；脚本出场条件 |",
        "| `talk_id` | 对话 ID |",
        "| `entity_id` / xyz | 实体与坐标（apply 保留） |",
        "",
        "## apply 三分类（换模前 · 与 `MsbEnemyPoc` 一致）",
        "",
        "| apply_slot_class | 含义 | 数量 |",
        "|------------------|------|-----:|",
    ]
    apply_zh = {
        "patrol_keep_initial": "A 巡逻 — 保留槽 WalkRoute/Backup/Collision/ChrActivate",
        "standing_keep_initial": "B 站立 — 地面站立无脚本；保留槽初态",
        "other_use_donor_behavior": "C 其他 — 坐/躺/挂靠/飞鸟/脚本激活；用捐皮 MSB 行为",
    }
    for key in ("patrol_keep_initial", "standing_keep_initial", "other_use_donor_behavior"):
        lines.append(f"| `{key}` | {apply_zh[key]} | {apply_ctr[key]:,} |")

    lines += [
        "",
        "## placement_kind（生成侧 `_slot_placement_kind`）",
        "",
        "| placement_kind | 数量 |",
        "|----------------|-----:|",
    ]
    for k, v in placement_ctr.most_common():
        lines.append(f"| `{k}` | {v:,} |")

    lines += [
        "",
        "## pose_label 分布（姿态/出场语义）",
        "",
        "| pose_label | 数量 |",
        "|------------|-----:|",
    ]
    for k, v in pose_ctr.most_common(40):
        lines.append(f"| `{k}` | {v:,} |")
    if len(pose_ctr) > 40:
        lines.append(f"| … 另有 {len(pose_ctr) - 40} 种 | |")

    lines += [
        "",
        "## backup_anim 取值统计（BackupEventAnimID）",
        "",
        "| backup_anim | 槽数 | 示例 map:entity |",
        "|-------------|-----:|-----------------|",
    ]
    for b in sorted(backup_ctr.keys()):
        if b == -1:
            continue
        sample = by_backup.get(b, [])
        ex = f"{sample[0]['map_id']}:{sample[0]['name']}" if sample else ""
        lines.append(f"| `{b}` | {backup_ctr[b]:,} | `{ex}` |")
    lines.append(f"| `-1`（无 backup） | {backup_ctr[-1]:,} | |")

    lines += [
        "",
        "## 地图覆盖",
        "",
        f"共 **{len(maps)}** 张图有敌人槽（索引内 `map_id` 去重）。",
        "",
        "## 讨论用要点",
        "",
        "1. **站立保留初态** 仅覆盖 `standing_keep_initial`；坐/躺/挂靠 Boss 多在 **C 其他**。",
        "2. `backup_anim` 是姿态主信号，但 **同一数值可对应不同语义**（需结合 model/collision）。",
        "3. 塔兰类终点 Boss：`backup_anim>0` + `collision_part` → apply 走 C，换 incompatible 捐皮易隐形。",
        "",
    ]

    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {OUT_MD}")
    print(f"Wrote {OUT_JSON}")
    print("apply:", dict(apply_ctr))
    print("placement:", dict(placement_ctr))


if __name__ == "__main__":
    main()
