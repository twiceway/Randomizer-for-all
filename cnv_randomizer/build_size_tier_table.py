"""Build enemy_size_tiers.json from NpcParam.csv + optional enemy_index placement stats.

Run:
  python build_size_tier_table.py
  python build_size_tier_table.py --sync-categories
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from paths import SCRIPT_DIR  # frozen-safe
DEFAULT_CSV = Path(r"V:\games\Elden Ring\Game\csv\NpcParam.csv")
DEFAULT_INDEX = SCRIPT_DIR / "cache" / "enemy_index.json"
OUT_JSON = SCRIPT_DIR / "enemy_size_tiers.json"
from paths import OUTPUT_REPORTS  # noqa: E402

OUT_MD = OUTPUT_REPORTS / "怪物体型表.md"
CATEGORIES_PATH = SCRIPT_DIR / "enemy_categories.json"

# User-confirmed hard overrides (CSV hitbox unreliable for these).
MANUAL_TIER: dict[str, str] = {
    "c5270": "large",
    "c5120": "large",
    "c2200": "colossal",
    "c4750": "boss",
    "c4760": "boss",
    "c4670": "boss",
    "c2030": "boss",
    "c2110": "boss",
    "c5300": "boss",
    "c5130": "boss",
    "c5220": "boss",
    "c5030": "boss",
    "c5050": "boss",
    "c8100": "boss",
    "c8101": "boss",
    "c8110": "boss",
}

FLYING_PREFIXES = frozenset(
    f"c450{i}" for i in range(10)
) | frozenset(f"c451{i}" for i in range(10)) | frozenset(
    {"c4520", "c4521", "c4522", "c4530", "c4510"}
)

TIER_META: dict[str, dict[str, Any]] = {
    "tiny": {
        "rank": 0,
        "label_zh": "微型",
        "donor_zone": "any",
        "slot_zone": "any",
        "pool_exclude": False,
        "note": "蟹/鼠等；chrHitRadius≤0.35",
    },
    "small": {
        "rank": 0,
        "label_zh": "小型",
        "donor_zone": "any",
        "slot_zone": "any",
        "pool_exclude": False,
        "note": "小狗/乌鸦等；0.35<chrHitRadius≤0.55",
    },
    "humanoid": {
        "rank": 1,
        "label_zh": "人形",
        "donor_zone": "any",
        "slot_zone": "any",
        "pool_exclude": False,
        "note": "士兵/骑士默认档",
    },
    "mounted": {
        "rank": 2,
        "label_zh": "骑乘",
        "donor_zone": "any",
        "slot_zone": "any",
        "narrow_donor_block": True,
        "pool_exclude": False,
        "note": "大树守卫/黑夜骑兵；狭窄地图禁捐皮，池不变",
    },
    "medium": {
        "rank": 3,
        "label_zh": "中型",
        "donor_zone": "any",
        "slot_zone": "any",
        "narrow_donor_block": True,
        "pool_exclude": False,
        "note": "次要Boss；地下城/小型槽禁过大捐皮",
    },
    "tall": {
        "rank": 3,
        "label_zh": "高型",
        "donor_zone": "any",
        "slot_zone": "any",
        "narrow_donor_block": True,
        "pool_exclude": False,
        "note": "坠星兽/碎星等；狭窄地图禁捐皮",
    },
    "large": {
        "rank": 4,
        "label_zh": "大型",
        "donor_zone": "overworld",
        "slot_zone": "never",
        "narrow_donor_block": True,
        "pool_exclude": False,
        "note": "T-097：野外可捐；地下/洞窟/墓穴/城内/城寨拒；槽位原位",
    },
    "colossal": {
        "rank": 4,
        "label_zh": "超巨",
        "donor_zone": "overworld",
        "slot_zone": "never",
        "narrow_donor_block": True,
        "pool_exclude": False,
        "note": "T-097：野外可捐；狭窄/室内一律拒；槽位原位",
    },
    "flying": {
        "rank": 4,
        "label_zh": "飞龙/古龙",
        "donor_zone": "never",
        "slot_zone": "never",
        "pool_exclude": True,
        "note": "飞龙+古龙（勿称泛飞行）；never_donor + 狭窄全禁",
    },
    "boss": {
        "rank": 5,
        "label_zh": "主线Boss",
        "donor_zone": "overworld",
        "slot_zone": "never",
        "narrow_donor_block": True,
        "pool_exclude": False,
        "note": "T-097：可捐（满月除外）；野外可、禁区拒；闸门=体型+历史状态",
    },
}


def model_prefix(npc_id: int) -> str:
    s = str(npc_id)
    if len(s) < 5:
        return f"c{s}"
    return f"c{s[0:4]}"


def load_categories() -> dict[str, Any]:
    return json.loads(CATEGORIES_PATH.read_text(encoding="utf-8-sig"))


def mounted_rider_prefixes(categories: dict[str, Any]) -> set[str]:
    out: set[str] = {"c3251"}
    for kind in categories.get("mount_pair_kinds") or []:
        for p in kind.get("rider_prefixes") or []:
            out.add(str(p).lower())
    return out


def aggregate_npcparam(path: Path) -> dict[str, dict[str, Any]]:
    agg: dict[str, dict[str, Any]] = {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            try:
                nid = int(row["ID"])
            except (TypeError, ValueError):
                continue
            mp = model_prefix(nid)
            d = agg.setdefault(
                mp,
                {
                    "prefix": mp,
                    "npc_count": 0,
                    "sample_npc_ids": [],
                    "chr_hit_r": [],
                    "chr_hit_h": [],
                    "sfx_size": [],
                    "move_type": [],
                    "lock_dist": [],
                    "hp": [],
                    "boss_rows": 0,
                },
            )
            d["npc_count"] += 1
            if len(d["sample_npc_ids"]) < 3:
                d["sample_npc_ids"].append(nid)
            for key, col in (
                ("chr_hit_r", "chrHitRadius"),
                ("chr_hit_h", "chrHitHeight"),
                ("sfx_size", "sfxSize"),
                ("move_type", "moveType"),
                ("lock_dist", "lockDist"),
                ("hp", "hp"),
            ):
                try:
                    d[key].append(float(row.get(col) or 0))
                except (TypeError, ValueError):
                    pass
            try:
                if int(row.get("isSoulGetByBoss") or 0) == 1:
                    d["boss_rows"] += 1
            except (TypeError, ValueError):
                pass
    return agg


def _max(vals: list[float]) -> float:
    return max(vals) if vals else 0.0


def classify_prefix(
    mp: str,
    stats: dict[str, Any],
    *,
    mounted_riders: set[str],
    old_map: dict[str, str],
    force_trash: set[str],
) -> tuple[str, str]:
    if mp in MANUAL_TIER:
        return MANUAL_TIER[mp], "manual"
    if mp in FLYING_PREFIXES:
        return "flying", "flying_prefix"
    chr_r = _max(stats["chr_hit_r"])
    chr_h = _max(stats["chr_hit_h"])
    sfx = _max(stats["sfx_size"])
    if mp in force_trash:
        if chr_r <= 0.35:
            return "tiny", "force_trash"
        return "small", "force_trash"
    if chr_r >= 7.0:
        return "colossal", f"chrHitR>={chr_r}"
    if mp in mounted_riders or mp == "c3250":
        return "mounted", "mount_pair"
    if chr_h >= 6.0 and chr_r < 3.0:
        return "tall", f"chrHitH>={chr_h}"
    if chr_r >= 1.2 or sfx >= 2.0 or chr_h >= 4.5:
        return "medium", f"chrHitR={chr_r},sfx={sfx},chrH={chr_h}"
    if chr_r <= 0.35:
        return "tiny", f"chrHitR<={chr_r}"
    if chr_r <= 0.55:
        return "small", f"chrHitR<={chr_r}"
    if mp in old_map and old_map[mp] in TIER_META:
        return old_map[mp], "legacy_map"
    return "humanoid", "default"


def placement_stats(index_path: Path, prefix_tiers: dict[str, str]) -> dict[str, Any]:
    if not index_path.is_file():
        return {"available": False}
    raw = json.loads(index_path.read_text(encoding="utf-8-sig"))
    by_tier_map: Counter[str] = Counter()
    by_tier_zone: Counter[tuple[str, str]] = Counter()
    for slot in raw.get("slots", []):
        try:
            nid = int(slot.get("npc") or 0)
        except (TypeError, ValueError):
            continue
        mp = model_prefix(nid)
        tier = prefix_tiers.get(mp, "humanoid")
        map_id = str(slot.get("map_id", ""))
        zone = "overworld" if map_id.rsplit("_", 1)[-1] == "00" else "dungeon"
        by_tier_map[tier] += 1
        by_tier_zone[(tier, zone)] += 1
    return {
        "available": True,
        "slots_by_tier": dict(by_tier_map),
        "slots_by_tier_zone": {
            f"{t}|{z}": c for (t, z), c in sorted(by_tier_zone.items())
        },
    }


def build_table(csv_path: Path, index_path: Path) -> dict[str, Any]:
    categories = load_categories()
    old_map = {
        str(k).lower(): str(v)
        for k, v in (categories.get("size_tier_by_model_prefix") or {}).items()
    }
    mounted_riders = mounted_rider_prefixes(categories)
    force_trash = {
        str(p).lower()
        for p in categories.get("force_trash_model_prefixes") or []
    }
    agg = aggregate_npcparam(csv_path)

  # All prefixes seen in NpcParam + existing map keys
    all_prefixes = sorted(set(agg.keys()) | set(old_map.keys()))
    models: list[dict[str, Any]] = []
    prefix_tiers: dict[str, str] = {}
    for mp in all_prefixes:
        stats = agg.get(mp)
        if stats is None:
            tier = old_map.get(mp, "humanoid")
            reason = "npcparam_missing"
            metrics = {}
        else:
            tier, reason = classify_prefix(
                mp,
                stats,
                mounted_riders=mounted_riders,
                old_map=old_map,
                force_trash=force_trash,
            )
            metrics = {
                "chr_hit_radius_max": round(_max(stats["chr_hit_r"]), 2),
                "chr_hit_height_max": round(_max(stats["chr_hit_h"]), 2),
                "sfx_size_max": int(_max(stats["sfx_size"])),
                "move_type_max": int(_max(stats["move_type"])),
                "lock_dist_max": round(_max(stats["lock_dist"]), 1),
                "hp_max": int(_max(stats["hp"])),
                "npc_rows": stats["npc_count"],
                "boss_rows": stats["boss_rows"],
            }
        prefix_tiers[mp] = tier
        meta = TIER_META[tier]
        models.append(
            {
                "prefix": mp,
                "tier": tier,
                "label_zh": meta["label_zh"],
                "donor_zone": meta["donor_zone"],
                "slot_zone": meta["slot_zone"],
                "pool_exclude": meta["pool_exclude"],
                "reason": reason,
                "metrics": metrics,
            }
        )

    tier_counts = Counter(m["tier"] for m in models)
    placement = placement_stats(index_path, prefix_tiers)

    return {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_csv": str(csv_path),
        "tier_meta": TIER_META,
        "classification_notes": [
            "NpcParam 按 npc ID 前4位聚合为 model 前缀 cXXXX",
            "chrHitRadius/Height 取同前缀多行 max；火焰巨人等用手动覆盖",
            "体型表辅助七类池：不改池归属，仅 narrow_placement 过滤捐皮",
            "placement 统计依赖 cache/enemy_index.json（可选）",
        ],
        "tier_counts": dict(sorted(tier_counts.items())),
        "models": models,
        "prefix_to_tier": prefix_tiers,
        "placement": placement,
    }


def write_markdown(table: dict[str, Any], path: Path) -> None:
    lines = [
        "# 怪物体型表",
        "",
        f"生成时间：{table['generated_at']}",
        f"数据源：`{table['source_csv']}`",
        "",
        "## 档位说明",
        "",
        "| 档位 | 中文 | rank | 捐皮范围 | 槽位范围 | 进池 | 说明 |",
        "|------|------|------|----------|----------|------|------|",
    ]
    for tid, meta in table["tier_meta"].items():
        pool = "否" if meta["pool_exclude"] else "是"
        lines.append(
            f"| `{tid}` | {meta['label_zh']} | {meta['rank']} | "
            f"{meta['donor_zone']} | {meta['slot_zone']} | {pool} | {meta['note']} |"
        )

    lines.extend(["", "## 各档 model 数量", ""])
    for tier, count in table.get("tier_counts", {}).items():
        label = table["tier_meta"][tier]["label_zh"]
        lines.append(f"- **{label}** (`{tier}`): {count} 个前缀")

    if table.get("placement", {}).get("available"):
        lines.extend(["", "## 槽位放置统计（index）", ""])
        for key, count in sorted(table["placement"]["slots_by_tier_zone"].items()):
            tier, zone = key.split("|", 1)
            label = table["tier_meta"][tier]["label_zh"]
            zl = "野外" if zone == "overworld" else "地下城"
            lines.append(f"- {label} / {zl}: **{count}** 槽")

    lines.extend(["", "## 重点模型", ""])
    watch = [
        "c3251", "c3250", "c5270", "c5120", "c2200", "c4500", "c4600",
        "c4810", "c4730", "c1000", "c2270", "c4352",
    ]
    by_prefix = {m["prefix"]: m for m in table["models"]}
    lines.append("| model | 档 | 中文 | chrR | chrH | sfx | 规则 |")
    lines.append("|-------|-----|------|------|------|-----|------|")
    for mp in watch:
        m = by_prefix.get(mp)
        if not m:
            continue
        met = m.get("metrics") or {}
        lines.append(
            f"| `{mp}` | `{m['tier']}` | {m['label_zh']} | "
            f"{met.get('chr_hit_radius_max', '-')} | {met.get('chr_hit_height_max', '-')} | "
            f"{met.get('sfx_size_max', '-')} | {m['reason']} |"
        )

    lines.extend(
        [
            "",
            "## 放置规则（生成器 · 辅助七类池）",
            "",
            "- **不改** trash/minor_boss/…/cnv_special 七类池归属",
            "- 地下城：捐皮 rank **高于** 槽位 → 剔除",
            "- 小型/人形槽：禁骑乘/中型/高型捐皮",
            "- `pool_exclude` 档（现仅飞龙/古龙）：永不进捐皮池",
            "- 大型/超巨/主线Boss（T-097）：野外可捐、狭窄/室内拒；槽位仍原位（`slot_zone=never`）",
            "- `mounted`：仍走 `mount_pair_kinds` 成套逻辑",
            "",
            "重生成：`python build_size_tier_table.py --sync-categories`",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def sync_categories(prefix_to_tier: dict[str, str]) -> None:
    data = load_categories()
    data["size_tier_by_model_prefix"] = dict(
        sorted(prefix_to_tier.items(), key=lambda kv: kv[0])
    )
    data["size_tier_definitions"] = (
        "真源 enemy_size_tiers.json；辅助七类池放置，不改池归属 | "
        "narrow_block=骑乘/中型/高型/大型/超巨/主线Boss 禁贴狭窄或小型槽 | "
        "pool_exclude=仅飞龙/古龙 | T-097 大型/超巨/主线Boss 野外可捐"
    )
    # 捐皮禁档 vs 槽位原位档分离（T-097：大档可捐但仍不随机其本体槽）
    data["exclude_donor_size_tiers"] = [
        t for t, m in TIER_META.items() if m.get("pool_exclude")
    ]
    data["exclude_slot_size_tiers"] = [
        t for t, m in TIER_META.items() if m.get("slot_zone") == "never"
    ]
    narrow_block = [
        t for t, m in TIER_META.items() if m.get("narrow_donor_block")
    ]
    prev_aux = data.get("size_tier_placement_aux")
    if not isinstance(prev_aux, dict):
        prev_aux = {}
    data["size_tier_placement_aux"] = {
        **prev_aux,
        "definition": (
            "不改动七类池。狭窄环境：≤中型可捐；大型/超巨/主线Boss/飞龙古龙一律不捐"
            "（含室内 Boss 位 · T-097）；小型槽禁骑乘/高型/大型等"
        ),
        "narrow_map_kinds": prev_aux.get("narrow_map_kinds") or ["dungeon"],
        "compact_slot_tiers": prev_aux.get("compact_slot_tiers")
        or ["tiny", "small", "humanoid"],
        "compact_slot_donor_block_tiers": narrow_block,
    }
    data.pop("overworld_only_donor_size_tiers", None)
    data.pop("overworld_only_slot_size_tiers", None)
    data.pop("medium_donor_overworld_only", None)
    CATEGORIES_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--sync-categories", action="store_true")
    args = parser.parse_args()

    if not args.csv.is_file():
        raise SystemExit(f"NpcParam not found: {args.csv}")

    table = build_table(args.csv, args.index)
    OUT_JSON.write_text(
        json.dumps(table, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_markdown(table, OUT_MD)
    print(f"Wrote {OUT_JSON} ({len(table['models'])} prefixes)")
    print(f"Wrote {OUT_MD}")
    print("tier_counts:", table["tier_counts"])
    if args.sync_categories:
        sync_categories(table["prefix_to_tier"])
        print(f"Synced {CATEGORIES_PATH}")


if __name__ == "__main__":
    main()
