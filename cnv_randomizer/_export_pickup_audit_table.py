# -*- coding: utf-8 -*-
"""Emit categorized pickup-slot audit report for user review."""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from cnv_randomizer_core import (
    CAT_GOODS,
    CAT_WEAPON,
    iter_slots,
    load_config,
    load_item_type_index,
    read_csv,
)
from goods_subcats import (
    GOODS_SUBCAT_LABELS,
    GOODS_SUBCAT_ORDER,
    classify_goods_subcat,
    is_spell_rune_item,
    is_spell_teach_book_item,
    load_accessory_rows,
    load_goods_rows,
    load_protector_rows,
    load_weapon_rows,
)
from pickup_pool import load_dlc_rules, resolve_item_category
from pickup_shuffle import (
    _indexed_lot_ids,
    collect_boss_reward_map_lots,
    collect_randomizable_slots,
)
from pickup_slot_index import load_pickup_slot_index

ROOT = Path(__file__).resolve().parent
OUT = ROOT.parent / "reports" / "物品槽扫描审计表_当前.md"

CAT_NAME = {
    0: "武器",
    1: "道具",
    2: "防具",
    3: "战灰",
    4: "护符",
    5: "魔法",
}
# MSB treasure.InChest：1=箱 · 2=地光 · 0=其余（多数为地图摆好的尸体，含少量桶/壶等）
# ≠ 打死怪才掉的尸体（敌人掉落表，不进本索引）
CHEST = {1: "箱子", 2: "地上光柱", 0: "非箱非光（多为地图尸体）"}


def main() -> None:
    cfg = load_config(ROOT / "config.json")
    cfg["goods_rows"] = load_goods_rows(cfg["csv_dir"])
    cfg["weapon_rows"] = load_weapon_rows(cfg["csv_dir"])
    cfg["accessory_rows"] = load_accessory_rows(cfg["csv_dir"])
    cfg["protector_rows"] = load_protector_rows(cfg["csv_dir"])
    cfg["dlc_rules"] = load_dlc_rules()
    cfg["dlc_ranges"] = cfg["dlc_rules"]["item_ranges"]
    type_index = load_item_type_index(cfg["csv_dir"])
    _, rows = read_csv(cfg["csv_dir"] / "ItemLotParam_map.csv")
    rows_by = {
        int(float(r["ID"])): r for r in rows if str(r.get("ID", "")).strip()
    }

    idx = load_pickup_slot_index() or {}
    placements = idx.get("placements") or []
    lot_chest: dict[int, int] = {}
    for p in placements:
        lid = int(p.get("lot_id") or 0)
        if lid and lid not in lot_chest:
            lot_chest[lid] = int(p.get("in_chest") or 0)

    indexed = _indexed_lot_ids(cfg)
    all_slots = collect_randomizable_slots(rows, cfg, type_index)
    boss_slots = collect_boss_reward_map_lots(rows, cfg, type_index, indexed)
    boss_lots = {l for l, _, _ in boss_slots}

    ch: Counter[str] = Counter()
    for lid, _s, _iid in all_slots:
        if lid in lot_chest:
            ch[CHEST.get(lot_chest[lid], "其他")] += 1
        else:
            ch["Boss注入"] += 1

    by_cat: Counter[str] = Counter()
    by_goods_sub: Counter[str] = Counter()
    spell_rune_slots: list[tuple] = []
    book_slots: list[tuple] = []
    weapon_slots: list[tuple] = []

    for lid, s, iid in all_slots:
        row = rows_by.get(lid)
        lot_cat = 0
        if row:
            for si, _idk, _ck, _item_id, lc in iter_slots(row):
                if si == s:
                    lot_cat = lc
                    break
        tc = resolve_item_category(iid, lot_cat, type_index)
        if tc is None:
            tc = type_index.get(iid)
        cname = CAT_NAME.get(tc if tc is not None else -1, "未知")
        by_cat[cname] += 1
        if tc == CAT_GOODS or type_index.get(iid) == CAT_GOODS:
            sub = classify_goods_subcat(iid, cfg["goods_rows"].get(iid))
            by_goods_sub[sub] += 1
            nm = (cfg["goods_rows"].get(iid) or {}).get("Name", "")
            if is_spell_rune_item(iid):
                spell_rune_slots.append((lid, s, iid, nm))
            if is_spell_teach_book_item(iid):
                book_slots.append((lid, s, iid, nm))
        if tc == CAT_WEAPON:
            wn = (cfg["weapon_rows"].get(iid) or {}).get("Name", "")
            weapon_slots.append(
                (lid, s, iid, wn, CHEST.get(lot_chest.get(lid, -1), "Boss注入"))
            )

    goods_band = sum(1 for i in range(8300, 8486) if i in cfg["goods_rows"])
    ic = Counter(int(p.get("in_chest") or 0) for p in placements)
    gs = [
        x
        for x in weapon_slots
        if "Greatsword" in (x[3] or "")
        or "greatsword" in (x[3] or "").lower()
        or x[2] == 4000000
    ]

    lines: list[str] = []
    lines.append("# 物品槽扫描审计表（当前）")
    lines.append("")
    lines.append(
        f"**用途**：给你按分类审计进池结果。"
        f"索引时间 `{idx.get('generated_at')}` · 扫描地图 `{idx.get('maps_scanned')}` · "
        f"treasure `{idx.get('treasure_events')}`。"
    )
    lines.append("")
    lines.append("## 1. 地图库（MSB 索引）分列")
    lines.append("")
    lines.append(
        "> **非箱非光（多为地图尸体）**：地图里本来就摆好的掉落点，"
        "既不是宝箱、也不是单独那种地上光柱；扫图标记为「其余」。"
        "里面**绝大多数是带拾取光的尸体**，另有少量桶/壶等。"
        "**不是**打死怪才出现的尸体掉落（那种走敌人掉落表，不进本表）。"
    )
    lines.append("")
    lines.append("| 类型 | placement 数 |")
    lines.append("|------|-------------|")
    for k, lab in [
        (1, "箱子"),
        (2, "地上光柱"),
        (0, "非箱非光（多为地图尸体）"),
    ]:
        lines.append(f"| {lab} | **{ic[k]}** |")
    lines.append(f"| **合计** | **{len(placements)}** |")
    lines.append("")
    lines.append("## 2. 进洗牌池（过闸后）按槽通道")
    lines.append("")
    lines.append("| 通道 | 可洗槽数 |")
    lines.append("|------|----------|")
    for lab in ["箱子", "地上光柱", "非箱非光（多为地图尸体）", "Boss注入"]:
        lines.append(f"| {lab} | **{ch[lab]}** |")
    lines.append(f"| **合计** | **{len(all_slots)}** |")
    lines.append("")
    lines.append("## 3. 进洗牌池按物品大类（源道具）")
    lines.append("")
    lines.append("| 大类 | 槽数 |")
    lines.append("|------|------|")
    for lab in ["武器", "道具", "防具", "护符", "战灰", "魔法", "未知"]:
        if by_cat[lab]:
            lines.append(f"| {lab} | **{by_cat[lab]}** |")
    lines.append("")
    lines.append("## 4. 进洗牌池 · 道具子类明细")
    lines.append("")
    lines.append(
        "> **读表注意**：下表槽数 = **过闸后进互洗袋的源槽**，不是道具表种类数。"
        "光荣商人能列全道具，靠整张道具表开店，不是扫地图。"
    )
    lines.append("")
    lines.append("| 子类代号 | 白话 | 进池槽数 |")
    lines.append("|----------|------|----------|")
    for sub in GOODS_SUBCAT_ORDER:
        n = by_goods_sub.get(sub, 0)
        if n:
            lines.append(
                f"| `{sub}` | {GOODS_SUBCAT_LABELS.get(sub, sub)} | **{n}** |"
            )
    for sub, n in sorted(by_goods_sub.items()):
        if sub not in GOODS_SUBCAT_ORDER and n:
            lines.append(
                f"| `{sub}` | {GOODS_SUBCAT_LABELS.get(sub, sub)} | **{n}** |"
            )
    lines.append("")
    lines.append("### 4.1 骨灰 / 追忆漏斗（进池很少时先看）")
    lines.append("")
    lines.append(
        "道具表种数 ≫ 地图 ton 槽 ≫ MSB 地上索引 ≫ 过闸进池。"
        "骨灰常被关掉标记挡；追忆常在排除名单；许多 ton 不在 MSB 宝箱/尸体事件里。"
        "要对齐「商店那种全有」需另开口径（放宽闸 / 洗整张 ton 表），先拍板再改码。"
    )
    lines.append("")
    lines.append("## 5. 法术卢恩（8300–8485）")
    lines.append("")
    lines.append("| 项 | 数 |")
    lines.append("|----|----|")
    lines.append(f"| 道具表条数 | **{goods_band}** |")
    lines.append(f"| 进池源槽（源=法术卢恩） | **{len(spell_rune_slots)}** |")
    lines.append("")
    lines.append("### 5.1 进池法术卢恩 ton 清单")
    lines.append("")
    lines.append("| ton | 槽 | 道具id | 表内名 | 通道 |")
    lines.append("|-----|----|--------|--------|------|")
    for lid, s, iid, nm in sorted(spell_rune_slots):
        chn = CHEST.get(lot_chest.get(lid, -1), "Boss注入")
        lines.append(f"| {lid} | {s} | {iid} | {nm} | {chn} |")
    lines.append("")
    lines.append("## 6. 真书法术书")
    lines.append("")
    lines.append(f"进池源槽：**{len(book_slots)}**")
    lines.append("")
    lines.append("| ton | 槽 | 道具id | 表内名 | 通道 |")
    lines.append("|-----|----|--------|--------|------|")
    if book_slots:
        for lid, s, iid, nm in sorted(book_slots):
            chn = CHEST.get(lot_chest.get(lid, -1), "Boss注入")
            lines.append(f"| {lid} | {s} | {iid} | {nm} | {chn} |")
    else:
        lines.append("| （当前过闸后无书作为源槽） | | | | |")
    lines.append("")
    lines.append("## 7. 武器进池 · 巨剑相关")
    lines.append("")
    lines.append(f"名称含 Greatsword 或 id=`4000000`：**{len(gs)}** 槽")
    lines.append("")
    lines.append("| ton | 槽 | 武器id | 名 | 通道 |")
    lines.append("|-----|----|--------|----|------|")
    for lid, s, iid, nm, chn in sorted(gs):
        lines.append(f"| {lid} | {s} | {iid} | {nm} | {chn} |")
    lines.append("")
    lines.append("## 8. Boss 注入")
    lines.append("")
    lines.append(
        f"注入 ton 唯一数：**{len(boss_lots)}** · 槽数：**{len(boss_slots)}**"
    )
    lines.append("")
    lines.append(
        "> 小怪击杀掉落表未参与。黄金卢恩柱 / E 键采集默认不洗。"
    )
    lines.append("")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {OUT}")
    print("channels", dict(ch))
    print("cats", dict(by_cat))
    print(
        "spell_rune",
        len(spell_rune_slots),
        "books",
        len(book_slots),
        "greatswordish",
        len(gs),
    )


if __name__ == "__main__":
    main()
