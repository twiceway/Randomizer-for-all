# -*- coding: utf-8 -*-
"""分类开关分册 MD → 离线物品池 JSON（主程序只读）。

真源：reports/分类开关/
产物：捐皮契约/分类开关物品池_当前.json
契约：捐皮契约/分类开关物品池契约.md

同号说明：武器/护甲/道具/战灰表可共用数字 id（命名空间不同）。
JSON 以 (item_id, switch_key) 为行；建池时按开关取并集 id。
禁止「同一开关下同 id 两行冲突」以外的硬失败。

用法：
  cd V:\\1_mel\\Ringrandom\\cnv_randomizer
  python _sync_category_switch_pool.py
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
BOOK_DIR = REPO / "reports" / "分类开关"
OUT = REPO / "捐皮契约" / "分类开关物品池_当前.json"

BOOK_SWITCH: list[tuple[str, str, str]] = [
    ("装备_武器_", "weapon", "equip_cat"),
    ("装备_护甲_", "armor", "equip_cat"),
    ("装备_法术_", "magic", "equip_cat"),
    ("道具_任务_", "quest", "goods_group"),
    ("道具_重要道具_", "important", "goods_group"),
    ("道具_强化材料_", "upgrade", "goods_group"),
    ("道具_杂项_", "craft", "goods_group"),
]

SKIP_PREFIXES = ("装备_护符_",)
MAGIC_TAGS = frozenset({"法术卢恩", "骨灰", "战灰"})


def _switch_for_book(name: str) -> tuple[str, str] | None:
    for pref in SKIP_PREFIXES:
        if name.startswith(pref):
            return None
    for pref, key, kind in BOOK_SWITCH:
        if name.startswith(pref):
            return key, kind
    return None


def _parse_book(path: Path) -> list[tuple[int, str, int, str]]:
    rows: list[tuple[int, str, int, str]] = []
    for ln in path.read_text(encoding="utf-8").splitlines():
        if not ln.startswith("|"):
            continue
        parts = [p.strip() for p in ln.strip("|").split("|")]
        if len(parts) < 3 or not parts[0].isdigit() or not parts[1].isdigit():
            continue
        iid = int(parts[1])
        name = parts[2]
        slot_n = 0
        audit_tag = ""
        for p in parts[3:]:
            if p.isdigit():
                slot_n = int(p)
                break
        for p in parts[3:]:
            if p in MAGIC_TAGS:
                audit_tag = p
                break
        rows.append((iid, name, slot_n, audit_tag))
    return rows


def main() -> int:
    if not BOOK_DIR.is_dir():
        print(f"ERROR: missing book dir {BOOK_DIR}", file=sys.stderr)
        return 1

    # key = (item_id, switch_key, audit_tag) — 法术册同号可兼骨灰/战灰撞号
    by_key: dict[tuple[int, str, str], dict] = {}
    same_row_conflict: list[str] = []

    for path in sorted(BOOK_DIR.glob("*.md")):
        mapped = _switch_for_book(path.name)
        if mapped is None:
            continue
        switch_key, switch_kind = mapped
        for iid, name, slot_n, tag in _parse_book(path):
            key = (iid, switch_key, tag)
            if key in by_key:
                prev = by_key[key]
                if prev["name_zh"] != name and name and prev["name_zh"]:
                    same_row_conflict.append(
                        f"id={iid} switch={switch_key} tag={tag!r}: "
                        f"{prev['name_zh']!r}@{prev['book']} vs {name!r}@{path.name}"
                    )
                if slot_n > int(prev.get("world_slot_count") or 0):
                    prev["world_slot_count"] = slot_n
                continue
            by_key[key] = {
                "item_id": iid,
                "name_zh": name,
                "switch_key": switch_key,
                "switch_kind": switch_kind,
                "book": path.name,
                "world_slot_count": slot_n,
                "audit_tag": tag,
            }

    if same_row_conflict:
        print("ERROR: same id+switch+tag conflicting names:", file=sys.stderr)
        for line in same_row_conflict[:30]:
            print(" ", line, file=sys.stderr)
        return 2

    items = sorted(
        by_key.values(),
        key=lambda d: (str(d["switch_key"]), int(d["item_id"]), str(d["audit_tag"])),
    )
    by_switch = Counter(d["switch_key"] for d in items)
    unique_ids = {int(d["item_id"]) for d in items}
    id_multi = Counter(int(d["item_id"]) for d in items)
    cross_ns = sum(1 for _i, n in id_multi.items() if n > 1)

    payload = {
        "schema_version": 1,
        "updated": str(date.today()),
        "source": "reports/分类开关/",
        "purpose": "最终物品池：主程序只读；再过 GUI 分开开关",
        "notes": {
            "row_key": "(item_id, switch_key, audit_tag)",
            "id_namespace": "同数字 id 可跨开关或同法术册内骨灰/战灰撞号；建池按开关并集 id",
        },
        "stats": {
            "kinds_rows": len(items),
            "kinds_unique_ids": len(unique_ids),
            "ids_in_multiple_rows": cross_ns,
            "by_switch": {k: by_switch[k] for k in sorted(by_switch)},
            "world_slots_sum": sum(int(d["world_slot_count"]) for d in items),
        },
        "items": items,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print("wrote", OUT)
    print("kinds_rows", len(items), "unique_ids", len(unique_ids), "multi_row_ids", cross_ns)
    for k, n in sorted(by_switch.items()):
        print(f"  {k}", n)
    smith = next(
        (d for d in items if int(d["item_id"]) == 10101 and d["switch_key"] == "upgrade"),
        None,
    )
    if smith:
        print("smithing_stone_10101_slots", smith["world_slot_count"])
    else:
        print("WARN: 10101 upgrade not in pool")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
