#!/usr/bin/env python3
"""Patch a few known chest lots for in-game edit verification (no randomizer)."""

from __future__ import annotations

import csv
from pathlib import Path

GAME_CSV = Path(r"V:\games\Elden Ring\Game\csv\ItemLotParam_map.csv")
OUT_DIR = Path(__file__).resolve().parent / "output" / "runtime"

# CNV ItemLot categories (NOT vanilla): weapon=0, goods=1, armor=2, ...
CAT_WEAPON = 0
CAT_GOODS = 1

# lot_id -> (item_id, category, note)
PATCHES: dict[int, tuple[int, int, str]] = {
    # 失色锻造石 [1] / item 10160 / cat 1 — 2900 是错的，改它不会影响先锋出生点箱子
    20000710: (18080000, CAT_WEAPON, "先锋出生点箱子（失色石）→ 黄金戟"),
    942370060: (32290000, CAT_WEAPON, "关卡前哨马车 1 → 木制大盾（随机器验证过）"),
    942370070: (64510000, CAT_WEAPON, "关卡前哨马车 2 → 流纹圆刃刀（随机器验证过）"),
}


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    with GAME_CSV.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        assert fieldnames is not None
        rows = list(reader)

    by_id = {int(r["ID"]): r for r in rows}
    missing = [lot for lot in PATCHES if lot not in by_id]
    if missing:
        raise SystemExit(f"Lot IDs not found in CSV: {missing}")

    massedit_lines: list[str] = []
    patch_rows: list[dict[str, str]] = []

    for lot_id, (item_id, category, note) in PATCHES.items():
        row = by_id[lot_id]
        old_id = row["lotItemId01"]
        old_cat = row["lotItemCategory01"]
        row["lotItemId01"] = str(item_id)
        row["lotItemCategory01"] = str(category)
        patch_rows.append(row)
        massedit_lines.append(f"# {note}")
        massedit_lines.append(
            f"param ItemLotParam_map: id {lot_id}: lotItemId01: = {item_id};"
        )
        massedit_lines.append(
            f"param ItemLotParam_map: id {lot_id}: lotItemCategory01: = {category};"
        )
        print(f"lot {lot_id}: id {old_id} cat {old_cat} -> {item_id} cat {category}  ({note})")

    patch_csv = OUT_DIR / "TEST_CHESTS_ItemLotParam_map.csv"
    with patch_csv.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(patch_rows)

    massedit_path = OUT_DIR / "TEST_CHESTS.massedit"
    massedit_path.write_text("\n".join(massedit_lines) + "\n", encoding="utf-8")

    readme = OUT_DIR / "TEST_CHESTS_说明.txt"
    readme.write_text(
        """法魂 3.0 — 三个测试宝箱（修正版）
================================

上次为什么没生效？
------------------
1. 先锋出生点箱子：之前改的是 lot 2900，但实际给失色石的是 lot 20000710。
2. 马车白光无物：和提灯类似，CNV 地上拾取是「光柱 + 实际掉落」两套；
   光柱还在说明地图/event 侧还在，但 ItemLot 里物品 ID / category 对不上就会空捡。
3. 改 ItemLot 时必须同时改 lotItemId01 和 lotItemCategory01（失色石 cat=1，武器 cat=0）。

本次三个 lot（Smithbox 搜 ItemLotParam_map 的 ID）：

  20000710    先锋出生点箱子（原：失色锻造石 [1]）→ 黄金戟 18080000
  942370060   关卡前哨马车 1（原：31250000）→ 木制大盾 32290000
  942370070   关卡前哨马车 2（原：44010000）→ 流纹圆刃刀 64510000

若 20000710 改完仍失色石，再试 lot 998700（Material Node 全局模板，会影响所有同类节点）。

CNV 双处原理（参考提灯）
------------------------
提灯：武器 residentSpEffectId + SpEffectVfxParam 5400/5401 管发光。

地上光柱拾取（event 90005750 / 20000732）：
  - CreateAssetfollowingSFX(...)  →  白光柱（类似提灯光效）
  - AwardItemsIncludingClients(lot)  →  实际给的物品（读 ItemLotParam_map）

Material Node（失色石一类）还多一层：
  - ItemLotParam_map 998700  →  给什么
  - AssetEnvironmentGeometryParam 99870  →  光柱/几何绑定

普通 MSB 宝箱（马车）一般只绑 ItemLot，改 lot 就够；空捡多半是 category 错了或存档 flag 已领过。

操作
----
1. 完全退出游戏
2. Smithbox → Project = Game\\mod，Data = Game
3. Tools → Data Transfer → Import CSV
4. 选 TEST_CHESTS_ItemLotParam_map.csv（本目录）
5. ItemLotParam_map，All fields，导入后 Ctrl+S
6. 确认 mod\\regulation.bin = 2,364,448 字节
7. 在 Smithbox 里核对三行是否已变（尤其 20000710 不再是 10160）
8. Start_Convergence_ME3.bat → 新建档（不要用旧档，避免 pickup flag 干扰）

预期
----
  先锋箱 → 黄金戟（有中文名）
  马车 1 → 木制大盾
  马车 2 → 流纹圆刃刀

若马车仍白光空捡：在 Smithbox 把 942370060/070 先改回原值 31250000 / 44010000 测 bin 是否生效；
若原版能捡、换成测试武器不能捡，把 Smithbox 里看到的 category 发回来。

Mass Edit 备用：TEST_CHESTS.massedit
""",
        encoding="utf-8",
    )

    print(f"\nWrote {patch_csv}")
    print(f"Wrote {massedit_path}")
    print(f"Wrote {readme}")


if __name__ == "__main__":
    main()
