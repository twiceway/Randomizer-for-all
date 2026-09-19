"""生成槽位分类底表（工程真源）— 与 skip 规则同源 describe_slot_policy()。

用法:
  python build_slot_baseline_table.py
  python build_slot_baseline_table.py --map m10_00_00_00

输出:
  reports/槽位分类底表.json
  reports/槽位分类底表.md
  reports/槽位分类底表_<map_id>.md  （--map 时）
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from paths import SCRIPT_DIR  # frozen-safe
sys.path.insert(0, str(SCRIPT_DIR))

import enemy_randomizer_core as core  # noqa: E402
from paths import OUTPUT_REPORTS  # noqa: E402

DEFAULT_INDEX = SCRIPT_DIR / "cache" / "enemy_index.json"
DEFAULT_PREP_GZ = SCRIPT_DIR / "cache" / "enemy_slot_prep.json.gz"
DEFAULT_CATEGORIES = SCRIPT_DIR / "enemy_categories.json"
DEFAULT_SPAWN = SCRIPT_DIR / "output" / "runtime" / "cnv_enemy_spawn_map.txt"

ROLE_ZH = {
    "story_talk": "剧情对话NPC",
    "story_event": "剧情事件槽(门卫/事件think)",
    "ambient_animal": "被动动物",
    "keep_original": "原位保留(圣甲虫等)",
    "hub": "大赐福/木桩",
    "skip_other": "其它跳过",
    "combat_ground": "战斗·地面",
    "combat_patrol": "战斗·巡逻",
    "combat_ledge": "战斗·城垛/碰撞锚点",
    "combat_perch": "战斗·栖枝/蹲姿(可随机,留碰撞)",
    "combat_aerial": "战斗·空中模型",
}


def _load_prep_rows() -> dict[tuple[str, str], dict[str, Any]]:
    if not DEFAULT_PREP_GZ.is_file():
        return {}
    with gzip.open(DEFAULT_PREP_GZ, "rt", encoding="utf-8") as fh:
        prep = json.load(fh)
    return {(str(r["m"]), str(r["n"])): r for r in prep.get("slots", [])}


def _load_spawn_keys() -> set[tuple[str, str]]:
    if not DEFAULT_SPAWN.is_file():
        return set()
    out: set[tuple[str, str]] = set()
    for line in DEFAULT_SPAWN.read_text(encoding="utf-8").splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and not parts[0].startswith("#"):
            out.add((parts[0], parts[1]))
    return out


def _md_table(rows: list[dict[str, Any]], columns: list[tuple[str, str]]) -> list[str]:
    header = "| " + " | ".join(h for _, h in columns) + " |"
    sep = "| " + " | ".join("---" for _ in columns) + " |"
    lines = [header, sep]
    for row in rows:
        cells = []
        for key, _ in columns:
            val = row.get(key, "")
            if isinstance(val, list):
                val = ",".join(val) if val else "—"
            cells.append(str(val).replace("|", "\\|") if val != "" else "—")
        lines.append("| " + " | ".join(cells) + " |")
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description="Build slot baseline policy table")
    parser.add_argument("--map", dest="map_filter", help="Extra detail MD for one map")
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--out-dir", type=Path, default=OUTPUT_REPORTS)
    args = parser.parse_args()

    categories_cfg = core._load_json(DEFAULT_CATEGORIES)
    npc_csv_dir = core.GAME_DIR / "csv"
    index = json.loads(args.index.read_text(encoding="utf-8"))
    prep_by_key = _load_prep_rows()
    spawn_keys = _load_spawn_keys()

    all_rows: list[dict[str, Any]] = []
    for slot in index.get("slots", []):
        key = (str(slot.get("map_id", "")), str(slot.get("name", "")))
        row = core.describe_slot_policy(
            slot,
            categories_cfg,
            npc_csv_dir=npc_csv_dir,
            prep_row=prep_by_key.get(key),
            spawn_keys=spawn_keys,
        )
        row["slot_role_zh"] = ROLE_ZH.get(row["slot_role"], row["slot_role"])
        all_rows.append(row)

    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    payload = {
        "generated_at": generated,
        "schema": "slot_policy_v2",
        "generator": "describe_slot_policy() in enemy_randomizer_core.py",
        "slot_count": len(all_rows),
        "slots": all_rows,
    }

    args.out_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.out_dir / "槽位分类底表.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    by_role = Counter(r["slot_role_zh"] for r in all_rows)
    by_policy = Counter(r["policy"] for r in all_rows)

    md: list[str] = [
        "# 槽位分类底表（工程真源）",
        "",
        f"**生成**：{generated}  ",
        "**维护**：改 `describe_slot_policy()` / skip 规则后 **必须**重跑本脚本；契约见 `.ai/docs/槽位分类契约.md`",
        "",
        f"JSON：`reports/槽位分类底表.json`（{len(all_rows)} 槽）",
        "",
        "## 统计",
        "",
        "### policy",
        "",
    ]
    for k, v in by_policy.most_common():
        md.append(f"- {k}: **{v}**")
    md.extend(["", "### slot_role", ""])
    for k, v in by_role.most_common():
        md.append(f"- {k}: **{v}**")

    cols = [
        ("entity", "实体"),
        ("model", "模型"),
        ("src_pool", "原池"),
        ("policy", "policy"),
        ("slot_role_zh", "角色"),
        ("rule_ids", "规则"),
        ("placement", "放置"),
        ("apply_collision", "apply碰撞"),
        ("npc_soul", "soul"),
        ("think", "think"),
        ("in_last_spawn_map", "spawn"),
    ]
    for map_id in ["m10_00_00_00", "m12_01_00_00", "m12_02_00_00"]:
        map_rows = sorted(
            [r for r in all_rows if r["map_id"] == map_id],
            key=lambda r: r["entity"],
        )
        if not map_rows:
            continue
        md.extend(["", f"## {map_id}（{len(map_rows)}）", ""])
        md.extend(_md_table(map_rows, cols))

    md_path = args.out_dir / "槽位分类底表.md"
    md_path.write_text("\n".join(md) + "\n", encoding="utf-8")

    if args.map_filter:
        detail_rows = sorted(
            [r for r in all_rows if r["map_id"] == args.map_filter],
            key=lambda r: r["entity"],
        )
        detail_md = [
            f"# 槽位分类底表 — {args.map_filter}",
            "",
            f"生成：{generated}",
            "",
        ]
        detail_md.extend(_md_table(detail_rows, cols))
        detail_path = args.out_dir / f"槽位分类底表_{args.map_filter}.md"
        detail_path.write_text("\n".join(detail_md) + "\n", encoding="utf-8")
        print(f"wrote {detail_path}")

    print(f"wrote {json_path}")
    print(f"wrote {md_path}")
    print(
        f"slots={len(all_rows)} participate={by_policy.get('participate', 0)} "
        f"skip={by_policy.get('skip', 0)}"
    )


if __name__ == "__main__":
    main()
