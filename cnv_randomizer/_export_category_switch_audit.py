# -*- coding: utf-8 -*-
"""导出「分类开关」物品清单（按 GUI 开关分册，给人审计）。

对齐界面：
  装备类：武器 / 护甲 / 法术（卢恩·骨灰·战灰） / 护符
  道具大类：任务 / 重要道具 / 强化材料 / 杂项

不接洗牌、不改允许表。只出 reports 分册。

用法：
  cd V:\\1_mel\\Ringrandom\\cnv_randomizer
  python _export_category_switch_audit.py
"""
from __future__ import annotations

import json
import shutil
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

import cnv_randomizer_core as core
from cnv_randomizer_core import (
    CAT_ARMOR,
    CAT_ASH,
    CAT_GOODS,
    CAT_MAGIC,
    CAT_TALISMAN,
    CAT_WEAPON,
    load_item_type_index,
    read_csv,
)
from goods_subcats import (
    GOODS_GROUP_HINTS,
    GOODS_GROUP_LABELS,
    GOODS_GROUP_ORDER,
    GOODS_SUBCAT_LABELS,
    SACRED_TEAR_IDS,
    classify_goods_subcat,
    is_flask_goods,
    is_pseudo_weapon_param_row,
    is_spirit_ash_base_tier,
    is_spirit_ash_goods_id,
    is_spell_rune_item,
    is_spell_teach_book_item,
    load_goods_rows,
    load_protector_rows,
    load_weapon_rows,
    subcat_to_goods_group,
)
from gui_common import CATEGORY_LABELS
from pickup_slot_index import DEFAULT_PICKUP_INDEX_PATH, load_pickup_slot_index

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
REPORTS = REPO / "reports"
OUT_DIR = REPORTS / "分类开关"
INDEX = REPORTS / "物品分类开关审计_索引_当前.md"
ZH_FMG = ROOT / "cache" / "item_names_zhocn_dlc02.json"
EN_FMG = ROOT / "cache" / "item_names_engus_dlc02.json"

# 与 gui_pickup_tab 勾选顺序一致
# 与 gui 勾选顺序一致（战灰已并入法术）
EQUIP_SWITCHES = [
    ("weapon", CAT_WEAPON),
    ("armor", CAT_ARMOR),
    ("magic", CAT_MAGIC),
]

MAX_ROWS = 450


def _load_zh() -> dict[str, dict[str, str]]:
    if not ZH_FMG.is_file():
        return {}
    return json.loads(ZH_FMG.read_text(encoding="utf-8"))


def _load_en() -> dict[str, dict[str, str]]:
    if not EN_FMG.is_file():
        return {}
    return json.loads(EN_FMG.read_text(encoding="utf-8"))


def _name(zh: dict, fmg_key: str, iid: int) -> str:
    block = zh.get(fmg_key) or {}
    return (block.get(str(iid)) or block.get(iid) or "").strip() or f"#{iid}"


def _goods_name(
    zh: dict,
    en: dict,
    iid: int,
    row: dict[str, str] | None = None,
) -> str:
    """道具中文名：主表+DLC；没有则英文名；再没有则 CSV Name；仍无则 #id。"""
    for pack in (zh, en):
        for fmg in (
            "GoodsName.fmg",
            "GoodsName_dlc01.fmg",
            "GoodsName_dlc02.fmg",
        ):
            n = _name(pack, fmg, iid)
            if n and not n.startswith("#"):
                return n
    if row:
        csv_name = str(row.get("Name") or row.get("name") or "").strip()
        if csv_name and csv_name not in {"-", "None"}:
            return csv_name
    return f"#{iid}"


def _cfg_on(cfg: dict, key: str, section: str) -> bool:
    if section == "cat":
        return bool((cfg.get("randomize_categories") or {}).get(key, False))
    return bool((cfg.get("randomize_goods_groups") or {}).get(key, False))


def _safe_stem(text: str) -> str:
    return (
        text.replace("/", "_")
        .replace("·", "_")
        .replace("（", "_")
        .replace("）", "")
        .replace(" ", "")
        .replace("～", "_")
    )


def _clear_out_dir() -> None:
    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    OUT_DIR.mkdir(parents=True, exist_ok=True)


def _is_ash_name(name: str) -> bool:
    s = (name or "").strip()
    return s.startswith("战灰：") or s.startswith("战灰:")


def _is_upgraded_spirit_ash(name: str, iid: int) -> bool:
    """强化档：名带＋/+，或末两位数 01～10。"""
    if "＋" in name or "+" in name:
        return True
    if is_spirit_ash_goods_id(iid) and not is_spirit_ash_base_tier(iid):
        return True
    rem = iid % 100
    sc = classify_goods_subcat(iid, None)
    if 1 <= rem <= 10 and sc in ("spirit_lesser", "spirit_greater"):
        return True
    return False


def _lot_looks_fixed_or_boss_map_reward(name: str, row: dict[str, str], cfg: dict) -> bool:
    """地图表 ton：Boss/精英固定奖 + 泪滴圣甲虫战灰 + 未索引遗物。

    不含全量敌人掉落表。与洗牌注入 `_lot_eligible_for_map_inject` 对齐。
    """
    from pickup_shuffle import (
        _lot_drops_relic_goods,
        _lot_has_spell_rune_or_teach_book,
        _lot_name_looks_boss_reward,
        _lot_name_looks_teardrop_scarab,
    )

    n = (name or "").strip()
    if not n or n.lower().startswith("tome #"):
        return False
    # CNV 固定奖 ton 名常为「[区域 - 敌人] …」或「[具名] …」
    if n.startswith("["):
        return True
    if _lot_name_looks_boss_reward(n):
        return True
    if _lot_name_looks_teardrop_scarab(n):
        return True
    if _lot_drops_relic_goods(row, cfg):
        return True
    if _lot_has_spell_rune_or_teach_book(row, cfg):
        return True
    return False


def _collect_world_slot_occ(csv_dir: Path, cfg: dict) -> Counter[int]:
    """洗槽原槽上的物品 id → 出现次数（箱/地光/尸体光 + 地图 Boss/固定奖）。

    **禁止**读 ItemLotParam_enemy（小怪随机掉落不算槽）。
    """
    occ: Counter[int] = Counter()
    map_fp = csv_dir / "ItemLotParam_map.csv"
    if not map_fp.is_file():
        return occ
    _, map_rows = core.read_csv(map_fp)
    idx = load_pickup_slot_index(
        Path(cfg.get("pickup_slot_index_path", DEFAULT_PICKUP_INDEX_PATH))
    ) or {}
    place_lots = {
        int(p.get("lot_id") or 0)
        for p in (idx.get("placements") or [])
        if int(p.get("lot_id") or 0)
    }

    def _absorb_row(row: dict[str, str]) -> None:
        for _i, _ik, _ck, iid, _cat in core.iter_slots(row):
            if iid > 0:
                occ[int(iid)] += 1

    for row in map_rows:
        lid = core.parse_int(row.get("ID"))
        if lid <= 0:
            continue
        name = str(row.get("Name") or row.get("name") or "")
        if lid in place_lots:
            _absorb_row(row)
            continue
        if _lot_looks_fixed_or_boss_map_reward(name, row, cfg):
            _absorb_row(row)
    return occ


def _collect_item_ids_on_world_slots(csv_dir: Path, cfg: dict) -> set[int]:
    """洗槽原槽上的物品 id 集合（有槽才进池）。"""
    return set(_collect_world_slot_occ(csv_dir, cfg))


def _is_letter_name(name: str) -> bool:
    """信件（不含制作笔记/祷告书/说明）。"""
    if not name or name.startswith("#"):
        return False
    if "制作笔记" in name or "祷告书" in name or name.startswith("说明"):
        return False
    return name.endswith("信") or "书信" in name or "介绍信" in name


def _is_great_rune_name(name: str) -> bool:
    """真·大卢恩（不含幻影、不含说明：大卢恩）。"""
    if not name or name.startswith("#"):
        return False
    if "大卢恩" not in name:
        return False
    if "幻影" in name or name.startswith("说明"):
        return False
    return True


def _is_spell_goods_row(row: dict[str, str] | None) -> bool:
    """CSV Name 带 [Sorcery]/[Incantation]：魔法/祷告商品行，不当杂项。"""
    if not row:
        return False
    raw = str(row.get("Name") or row.get("name") or "").strip()
    return raw.startswith("[Sorcery]") or raw.startswith("[Incantation]")


def _goods_never_pool_reason(name: str, row: dict[str, str] | None = None, iid: int | None = None) -> str | None:
    """审计踢出 / 永不进池·原槽不随机。返回原因代号，None=保留。"""
    from goods_subcats import goods_name_is_map_fragment

    if not name or name.startswith("#"):
        return "shell"
    if name.startswith("[ERROR]") or "[ERROR]" in name:
        return "error_name"
    # 调试占位
    if iid == 1 or name == "重新加载地图":
        return "debug"
    if _is_spell_goods_row(row):
        return "spell_goods"
    if goods_name_is_map_fragment(name):
        return "map_frag"
    if "哨笛" in name:
        return "whistle"
    if "制作笔记" in name:
        return "craft_note"
    # 说明：2026-09-19 进池 — 不再踢
    # 圣杯瓶（红/蓝露滴 + 灵药瓶本体 + NPC 专用瓶）
    if "圣杯瓶" in name or (iid is not None and is_flask_goods(iid)):
        return "flask"
    # 露滴：结晶露滴等仍踢；圣杯露滴（瓶升级 · id=10020）2026-09-18 进池
    if (iid is not None and iid in SACRED_TEAR_IDS) or name == "圣杯露滴" or name.startswith(
        "圣杯露滴"
    ):
        pass  # keep — do not treat as tear_dew
    elif "露滴" in name:
        return "tear_dew"
    # 祷告书 / 法术卷轴：法魂靠法术卢恩学法；地图几乎无拾取槽
    if iid is not None and is_spell_teach_book_item(iid):
        return "spell_book"
    raw = str((row or {}).get("Name") or (row or {}).get("name") or "")
    if "NPC Flask" in raw or name.startswith("NPC Flask"):
        return "npc_flask"
    # 「文件：…」含 [ERROR] 前缀误名
    if name.startswith("文件") or "文件：" in name or "文件:" in name:
        return "file"
    if "铃珠" in name:
        return "bell"
    if "砥石" in name and "刀" in name:
        return "whetblade"
    if name.startswith("绘画"):
        return "painting"
    if _is_letter_name(name):
        return "letter"
    return None


def _protector_name(zh: dict, iid: int) -> str:
    """护甲中文名：主表 + DLC；绝不回落到道具名。"""
    for fmg in (
        "ProtectorName.fmg",
        "ProtectorName_dlc01.fmg",
        "ProtectorName_dlc02.fmg",
    ):
        n = _name(zh, fmg, iid)
        if n and not n.startswith("#"):
            return n
    return ""


def _weapon_name(zh: dict, iid: int) -> str:
    """武器中文名：主表 + DLC；绝不回落到道具名。"""
    for fmg in (
        "WeaponName.fmg",
        "WeaponName_dlc01.fmg",
        "WeaponName_dlc02.fmg",
    ):
        n = _name(zh, fmg, iid)
        if n and not n.startswith("#"):
            return n
    return ""


# 占位空壳（整名恰好为部位字），「蘑菇头部」等成品不在此列
_ARMOR_PLACEHOLDER_NAMES = frozenset({"头部", "腿部", "身体", "腕部", "臂部"})


def _is_armor_keep_name(name: str) -> bool:
    s = (name or "").strip()
    if not s or s.startswith("#"):
        return False
    if s in _ARMOR_PLACEHOLDER_NAMES:
        return False
    return True


def _is_weapon_keep_name(name: str) -> bool:
    s = (name or "").strip()
    return bool(s) and not s.startswith("#")


def _collect_ash_by_name(zh: dict) -> list[tuple[int, str]]:
    """全库中文名以「战灰：」开头的战灰（GemName + DLC）。"""
    by: dict[int, str] = {}
    for fmg in ("GemName.fmg", "GemName_dlc01.fmg"):
        for k, v in (zh.get(fmg) or {}).items():
            if not isinstance(v, str):
                continue
            s = v.strip()
            if not _is_ash_name(s):
                continue
            try:
                by[int(k)] = s
            except ValueError:
                continue
    return sorted(by.items(), key=lambda t: t[0])


def _collect_spell_runes(
    zh: dict,
    en: dict,
    goods: dict[int, dict[str, str]],
) -> list[tuple[int, str]]:
    """真·法术卢恩（8300–8485 / is_spell_rune_item），非 Magic.csv 魔法祷告。"""
    out: list[tuple[int, str]] = []
    for iid, row in goods.items():
        if not is_spell_rune_item(int(iid), row):
            continue
        out.append((int(iid), _goods_name(zh, en, int(iid), row)))
    return sorted(out, key=lambda t: t[0])


def _collect_spirit_ashes_for_magic(
    zh: dict,
    en: dict,
    goods: dict[int, dict[str, str]],
    on_slots: set[int],
) -> list[tuple[int, str]]:
    """基础档 + 有世界槽的骨灰（进法术册；强化/无槽已排除）。"""
    out: list[tuple[int, str]] = []
    for iid, row in goods.items():
        sc = classify_goods_subcat(int(iid), row)
        if sc not in {"spirit_lesser", "spirit_greater"}:
            continue
        name = _goods_name(zh, en, int(iid), row)
        if name.startswith("#"):
            continue
        if _is_upgraded_spirit_ash(name, int(iid)):
            continue
        if int(iid) not in on_slots:
            continue
        out.append((int(iid), name))
    return sorted(out, key=lambda t: t[0])


def _write_equip_table(
    path: Path,
    title: str,
    switch_note: str,
    rows: list[tuple[int, str, str]],
    *,
    audit_hint: str,
    count_note: str,
    slot_occ: Counter[int] | None = None,
) -> int:
    """rows: (id, name, audit_cell). 世界槽数 = 该 id 在洗槽原槽出现次数。"""
    occ = slot_occ or Counter()
    slot_sum = sum(occ[iid] for iid, *_rest in rows)
    lines = [
        f"# {title}",
        "",
        "> 分类开关审计分册。总览见 [物品分类开关审计_索引_当前.md](../物品分类开关审计_索引_当前.md)。",
        f"> {switch_note}",
        "",
        audit_hint,
        "",
        f"**种类**：{len(rows)}　**世界槽合计**：{slot_sum}　{count_note}",
        "",
        "| 序号 | id | 中文名 | 世界槽数 | 审计 |",
        "|------|-----|--------|----------|------|",
    ]
    for i, (iid, name, audit) in enumerate(rows, 1):
        lines.append(f"| {i} | {iid} | {name} | {occ[iid]} | {audit} |")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return len(rows)


def _write_goods_table(
    path: Path,
    title: str,
    switch_note: str,
    rows: list[tuple[int, str, str]],
    *,
    audit_hint: str,
    slot_occ: Counter[int] | None = None,
) -> int:
    """rows: (id, name_zh, subcat_label)."""
    occ = slot_occ or Counter()
    slot_sum = sum(occ[iid] for iid, *_rest in rows)
    lines = [
        f"# {title}",
        "",
        "> 分类开关审计分册。总览见 [物品分类开关审计_索引_当前.md](../物品分类开关审计_索引_当前.md)。",
        f"> {switch_note}",
        "",
        audit_hint,
        "",
        f"**种类**：{len(rows)}　**世界槽合计**：{slot_sum}",
        "",
        "| 序号 | id | 中文名 | 内部子类 | 世界槽数 | 审计 |",
        "|------|-----|--------|----------|----------|------|",
    ]
    for i, (iid, name, sub_label) in enumerate(rows, 1):
        lines.append(
            f"| {i} | {iid} | {name} | {sub_label} | {occ[iid]} | |"
        )
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return len(rows)


def _chunk_equip(
    base_stem: str,
    title: str,
    switch_note: str,
    rows: list[tuple[int, str, str]],
    audit_hint: str,
    count_note: str,
    slot_occ: Counter[int] | None = None,
) -> list[tuple[str, Path, int, int]]:
    """返回 (label, path, 种类数, 本册世界槽合计)。"""
    occ = slot_occ or Counter()
    out: list[tuple[str, Path, int, int]] = []
    if len(rows) <= MAX_ROWS:
        p = OUT_DIR / f"{base_stem}_当前.md"
        n = _write_equip_table(
            p,
            title,
            switch_note,
            rows,
            audit_hint=audit_hint,
            count_note=count_note,
            slot_occ=occ,
        )
        out.append((title, p, n, sum(occ[i] for i, *_ in rows)))
        return out
    parts = (len(rows) + MAX_ROWS - 1) // MAX_ROWS
    for pi in range(parts):
        chunk = rows[pi * MAX_ROWS : (pi + 1) * MAX_ROWS]
        label = f"{title}（{pi + 1}/{parts}）"
        p = OUT_DIR / f"{base_stem}_{pi + 1}_当前.md"
        n = _write_equip_table(
            p,
            label,
            switch_note,
            chunk,
            audit_hint=audit_hint,
            count_note=count_note,
            slot_occ=occ,
        )
        out.append((label, p, n, sum(occ[i] for i, *_ in chunk)))
    return out


def _chunk_goods(
    base_stem: str,
    title: str,
    switch_note: str,
    rows: list[tuple[int, str, str]],
    audit_hint: str,
    slot_occ: Counter[int] | None = None,
) -> list[tuple[str, Path, int, int]]:
    occ = slot_occ or Counter()
    out: list[tuple[str, Path, int, int]] = []
    if len(rows) <= MAX_ROWS:
        p = OUT_DIR / f"{base_stem}_当前.md"
        n = _write_goods_table(
            p, title, switch_note, rows, audit_hint=audit_hint, slot_occ=occ
        )
        out.append((title, p, n, sum(occ[i] for i, *_ in rows)))
        return out
    parts = (len(rows) + MAX_ROWS - 1) // MAX_ROWS
    for pi in range(parts):
        chunk = rows[pi * MAX_ROWS : (pi + 1) * MAX_ROWS]
        label = f"{title}（{pi + 1}/{parts}）"
        p = OUT_DIR / f"{base_stem}_{pi + 1}_当前.md"
        n = _write_goods_table(
            p, label, switch_note, chunk, audit_hint=audit_hint, slot_occ=occ
        )
        out.append((label, p, n, sum(occ[i] for i, *_ in chunk)))
    return out


def _collect_equip_ids(csv_dir: Path, type_index: dict) -> dict[int, set[int]]:
    weapons = load_weapon_rows(csv_dir)
    protectors = load_protector_rows(csv_dir)
    cat_ids: dict[int, set[int]] = defaultdict(set)
    for iid, cat in type_index.items():
        if cat in {CAT_WEAPON, CAT_ARMOR, CAT_TALISMAN, CAT_ASH, CAT_MAGIC}:
            cat_ids[cat].add(int(iid))
    for iid in weapons:
        cat_ids[CAT_WEAPON].add(int(iid))
    for iid in protectors:
        cat_ids[CAT_ARMOR].add(int(iid))
    for fname, cat in (
        ("EquipParamAccessory.csv", CAT_TALISMAN),
        ("EquipParamGem.csv", CAT_ASH),
        ("Magic.csv", CAT_MAGIC),
    ):
        fp = csv_dir / fname
        if not fp.is_file():
            continue
        _, rows = read_csv(fp)
        for r in rows:
            sid = str(r.get("ID") or r.get("id") or "").strip()
            if sid.isdigit():
                cat_ids[cat].add(int(sid))
    return cat_ids


def main() -> None:
    cfg = core.load_config(ROOT / "config.json")
    csv_dir = Path(cfg["csv_dir"])
    zh = _load_zh()
    en = _load_en()
    goods = load_goods_rows(csv_dir)
    type_index = load_item_type_index(csv_dir)
    cfg["goods_rows"] = goods
    slot_occ = _collect_world_slot_occ(csv_dir, cfg)
    on_slots = set(slot_occ)

    _clear_out_dir()

    index_rows: list[str] = [
        "# 物品分类开关审计（索引）",
        "",
        f"**日期**：{date.today()}",
        "**用途**：按界面勾选类别审「各自含哪些物品」；分册 = **最终物品池真源**。",
        "**物品池接线**：同步 `_sync_category_switch_pool.py` → "
        "[分类开关物品池_当前.json](../捐皮契约/分类开关物品池_当前.json)；"
        "主程序只读∩GUI。",
        "**世界槽数**：分册「种类」≠「出现次数」；每行有世界槽数列，页头有合计"
        "（不含小怪随机掉落）。",
        "**回我**：`武器#12 不该算装备` / `重要道具#30 应归到任务` / `杂项#5 保持`",
        "",
        "## 装备类（勾选 = 进入随机池）",
        "",
        "| 开关 | 现网默认 | 种类 | 世界槽合计 | 分册 |",
        "|------|----------|------|------------|------|",
    ]

    fmg_for_cat = {
        CAT_WEAPON: "WeaponName.fmg",
        CAT_ARMOR: "ProtectorName.fmg",
        CAT_TALISMAN: "AccessoryName.fmg",
        CAT_ASH: "GemName.fmg",
        CAT_MAGIC: "MagicName.fmg",
    }
    cat_ids = _collect_equip_ids(csv_dir, type_index)

    for key, cat in EQUIP_SWITCHES:
        label = CATEGORY_LABELS[key]
        on = _cfg_on(cfg, key, "cat")
        all_ids = sorted(cat_ids.get(cat, set()))
        fmg = fmg_for_cat[cat]
        rows: list[tuple[int, str, str]] = []
        count_note = "（有世界槽 ∩ 规则）"
        audit_default = ""

        if key == "armor":
            # 有护甲中文名（含 DLC）；不借道具名；踢占位空壳；无槽踢出（不再∩旧A允许表）
            for iid in all_ids:
                if iid not in on_slots:
                    continue
                name = _protector_name(zh, iid)
                if not _is_armor_keep_name(name):
                    continue
                rows.append((iid, name, "保持"))
            count_note = "（口径：有护甲中文名∩有世界槽；无槽/占位/错名已踢）"
            note = (
                f"界面开关 **{label}** · 现网默认 **{'开' if on else '关'}** · "
                f"护甲表约 **{len(all_ids)}** 件 · "
                f"本册 **{len(rows)}**（有名∩有槽）· "
                "**人审口径 ✅** + **洗槽有槽**"
            )
            hint = (
                "已按护甲中文名∩有槽过滤；若某条不该算护甲回我："
                f"`{label}#序号 踢出`"
            )
        elif key == "magic":
            # 法术开关 = 法术卢恩 + 骨灰 + 战灰（有槽）
            rune_named = [
                (iid, name)
                for iid, name in _collect_spell_runes(zh, en, goods)
                if iid in on_slots
            ]
            spirit_named = _collect_spirit_ashes_for_magic(zh, en, goods, on_slots)
            war_named = [
                (iid, name)
                for iid, name in _collect_ash_by_name(zh)
                if iid in on_slots
            ]
            rows = (
                [(iid, name, "法术卢恩") for iid, name in rune_named]
                + [(iid, name, "骨灰") for iid, name in spirit_named]
                + [(iid, name, "战灰") for iid, name in war_named]
            )
            all_ids = (
                [iid for iid, _ in rune_named]
                + [iid for iid, _ in spirit_named]
                + [iid for iid, _ in war_named]
            )
            count_note = (
                "（口径：法术卢恩 + 基础有槽骨灰 + 「战灰：」有槽；"
                "强化骨灰/无槽已踢；战灰已并入本开关）"
            )
            note = (
                f"界面开关 **{label}** · 现网默认 **{'开' if on else '关'}** · "
                f"卢恩 **{len(rune_named)}** + 骨灰 **{len(spirit_named)}** "
                f"+ 战灰 **{len(war_named)}** = **{len(rows)}** · "
                "**战灰并入法术 ✅**"
            )
            hint = (
                "卢恩/骨灰/战灰同册；若某条不该算回我："
                f"`{label}#序号 踢出`"
            )
        elif key == "weapon":
            # 有武器中文名；禁 GoodsName 回落；踢假武器行 / 空壳（不再∩旧A）
            weapons = load_weapon_rows(csv_dir)
            for iid in all_ids:
                if iid not in on_slots:
                    continue
                name = _weapon_name(zh, iid)
                if not _is_weapon_keep_name(name):
                    continue
                row = weapons.get(iid)
                if row is None or is_pseudo_weapon_param_row(row):
                    continue
                rows.append((iid, name, audit_default))
            count_note = (
                "（口径：有武器中文名∩有世界槽∩非假武器；"
                "空壳/借道具名/假武器已踢）"
            )
            note = (
                f"界面开关 **{label}** · 现网默认 **{'开' if on else '关'}** · "
                f"武器表约 **{len(all_ids)}** 件 · "
                f"本册 **{len(rows)}**（有名∩有槽∩真武器）· "
                "**空壳/借名踢出 ✅**"
            )
            hint = (
                "已按武器中文名∩有槽∩非假武器过滤；若某条不该算武器回我："
                f"`{label}#序号 踢出`"
            )
        else:
            for iid in all_ids:
                if iid not in on_slots:
                    continue
                name = _name(zh, fmg, iid)
                if name == f"#{iid}":
                    continue
                rows.append((iid, name, audit_default))
            note = (
                f"界面开关 **{label}** · 现网默认 **{'开' if on else '关'}** · "
                f"全库约 **{len(all_ids)}** 件 · "
                f"本册只列**有世界槽**（{len(rows)}）"
            )
            hint = f"回我格式：`{label}#序号 保持` / `{label}#序号 不该算装备`"

        stem = _safe_stem(f"装备_{label}")
        written = _chunk_equip(
            stem,
            f"分类开关 · 装备 · {label}",
            note,
            rows,
            hint,
            count_note,
            slot_occ=slot_occ,
        )
        library_n = (
            len(rows) if key in {"armor", "magic", "weapon"} else len(all_ids)
        )
        total_slots = sum(s for _lab, _p, _n, s in written)
        for lab, p, n, slots in written:
            rel = p.relative_to(REPORTS).as_posix()
            show_slots = total_slots if lab == written[0][0] else "↑"
            index_rows.append(
                f"| {label} | {'✅开' if on else '❌关'} | {library_n} | "
                f"{show_slots} | "
                f"[{lab}](./{rel}) |"
            )
        if not written:
            p = OUT_DIR / f"{stem}_当前.md"
            _write_equip_table(
                p,
                f"分类开关 · 装备 · {label}",
                note,
                [],
                audit_hint=hint,
                count_note=count_note,
                slot_occ=slot_occ,
            )
            rel = p.relative_to(REPORTS).as_posix()
            index_rows.append(
                f"| {label} | {'✅开' if on else '❌关'} | {library_n} | 0 | "
                f"[{label}](./{rel}) |"
            )

    # 护符：遗物兑换永不进池（不进装备勾选表）
    tal_note = (
        "界面**不勾选** · **永不进池** · 法魂护符靠**遗物兑换**，无拾取/Boss固定奖/箱槽 "
        "（同露滴口径）；洗牌硬排除已接线"
    )
    tal_path = OUT_DIR / "装备_护符_永不进池_当前.md"
    _write_equip_table(
        tal_path,
        "分类开关 · 装备 · 护符（永不进池）",
        tal_note,
        [],
        audit_hint="无需人审条目；整类踢出。若日后确认有真拾取槽再改口径。",
        count_note="（遗物兑换 · 0 条进池）",
        slot_occ=slot_occ,
    )
    index_rows.append(
        f"| 护符 | ❌永不进池 | 0 | 0 | "
        f"[护符（永不进池）](./{tal_path.relative_to(REPORTS).as_posix()}) |"
    )

    index_rows.extend(
        [
            "",
            "## 道具大类（未勾选 = 保持原位）",
            "",
            "| 开关 | 现网默认 | 说明 | 种类 | 世界槽合计 | 分册 |",
            "|------|----------|------|------|------------|------|",
        ]
    )

    by_group: dict[str, list[tuple[int, str, str]]] = defaultdict(list)
    ungrouped: list[tuple[int, str, str]] = []
    kick_counts: Counter[str] = Counter()
    for iid, row in goods.items():
        sc = classify_goods_subcat(int(iid), row) or "misc"
        gid = subcat_to_goods_group(sc)
        name = _goods_name(zh, en, int(iid), row)
        reason = _goods_never_pool_reason(name, row, int(iid))
        if reason:
            kick_counts[reason] += 1
            continue
        sc_now = classify_goods_subcat(int(iid), row) or sc
        # 强化骨灰：无原槽，先点名踢
        if sc_now in ("spirit_lesser", "spirit_greater") and _is_upgraded_spirit_ash(
            name, int(iid)
        ):
            kick_counts["ash_upgraded"] += 1
            continue
        # 洗槽硬规则：无拾取/Boss固定奖/箱槽 → 不进池
        if int(iid) not in on_slots:
            kick_counts["no_slot"] += 1
            continue
        # 骨灰只进装备·法术分册（与法术卢恩同开关）
        if sc_now in ("spirit_lesser", "spirit_greater"):
            kick_counts["ash_to_equip"] += 1
            continue
        # 法术卢恩只进装备·法术分册，不进道具大类（防重要道具双挂）
        if is_spell_rune_item(int(iid), row) or sc == "spell_rune":
            kick_counts["spell_rune_to_equip"] += 1
            continue
        # 说明：进任务开关（2026-09-19）
        from goods_subcats import goods_name_is_info_note

        if goods_name_is_info_note(name):
            sc = "quest_note"
            gid = "quest"
        # 大卢恩：审计挂到重要道具（人审口径）
        elif _is_great_rune_name(name):
            sc = "great_rune"
            gid = "important"
        # Boss 追忆：归重要道具（误进卢恩符文/杂项）
        elif "追忆" in name:
            sc = "remembrance"
            gid = "important"
        elif "遗物" in name:
            gid = "important"
        # 任务线钥物 / 使用物 / 唤声泥颅
        elif (
            name in {"亵渎兽爪", "纯血骑士勋章", "米凯拉的针", "玛尔基特的囚具", "蒙格的囚具"}
            or "唤声泥颅" in name
        ):
            sc = "quest_unique"
            gid = "quest"
        sub_label = GOODS_SUBCAT_LABELS.get(sc, sc)
        entry = (int(iid), name, sub_label)
        if gid:
            by_group[gid].append(entry)
        else:
            ungrouped.append(entry)

    kick_note = (
        "永不进池已踢：空壳/ERROR/调试/圣杯瓶/露滴/NPC瓶/"
        "地图碎片/哨笛/制作笔记/文件/铃珠/砥石刀/绘画/信件/"
        "祷告书·卷轴/魔法商品行；强化骨灰；"
        "**说明：已进池（2026-09-19）**；"
        "**无世界槽（拾取/Boss固定奖/箱/敌人掉落窄口）一律踢**；"
        "法术卢恩与骨灰只在法术装备册；大卢恩·追忆改挂重要道具"
    )
    for gid in GOODS_GROUP_ORDER:
        label = GOODS_GROUP_LABELS[gid]
        on = _cfg_on(cfg, gid, "group")
        items = sorted(by_group.get(gid, []), key=lambda t: t[0])
        note = (
            f"界面开关 **{label}** · 现网默认 **{'开' if on else '关'}** · "
            f"{GOODS_GROUP_HINTS.get(gid, '')} · "
            "「内部子类」仅方便纠错，界面上只有这一个大类开关 · "
            f"{kick_note}"
        )
        hint = (
            f"回我格式：`{label}#序号 保持` / "
            f"`{label}#序号 应归到任务|重要道具|强化材料|杂项`"
        )
        stem = _safe_stem(f"道具_{label}")
        written = _chunk_goods(
            stem,
            f"分类开关 · 道具 · {label}",
            note,
            items,
            hint,
            slot_occ=slot_occ,
        )
        total_slots = sum(s for _lab, _p, _n, s in written)
        for lab, p, n, slots in written:
            rel = p.relative_to(REPORTS).as_posix()
            show_slots = total_slots if lab == written[0][0] else "↑"
            index_rows.append(
                f"| {label} | {'✅开' if on else '❌关'} | "
                f"{GOODS_GROUP_HINTS.get(gid, '')} | {n} | {show_slots} | "
                f"[{lab}](./{rel}) |"
            )
        if not written:
            p = OUT_DIR / f"{stem}_当前.md"
            _write_goods_table(
                p,
                f"分类开关 · 道具 · {label}",
                note,
                [],
                audit_hint=hint,
                slot_occ=slot_occ,
            )
            rel = p.relative_to(REPORTS).as_posix()
            index_rows.append(
                f"| {label} | {'✅开' if on else '❌关'} | "
                f"{GOODS_GROUP_HINTS.get(gid, '')} | 0 | 0 | [{label}](./{rel}) |"
            )

    if ungrouped:
        items = sorted(ungrouped, key=lambda t: t[0])
        written = _chunk_goods(
            "道具_未归组",
            "分类开关 · 道具 · 未归组",
            "未落入四大道具开关（应并入某大类）",
            items,
            "回我：应归到哪个道具大类",
            slot_occ=slot_occ,
        )
        index_rows.append("")
        index_rows.append("## 未归组（应并入四大类之一）")
        index_rows.append("")
        for lab, p, n, slots in written:
            rel = p.relative_to(REPORTS).as_posix()
            index_rows.append(
                f"- [{lab}](./{rel}) · 种类 {n} · 世界槽 {slots}"
            )

    index_rows.extend(
        [
            "",
            "## 怎么审",
            "",
            "1. 从本索引点进某个**界面开关**分册",
            "2. 看「世界槽数」：一种物品一行，数字是全图出现几次（洗牌按源槽次数）",
            "3. 道具册看「内部子类」列，方便判断是否归错大类",
            "4. 发现错归类回我：`重要道具#序号 应归到任务`",
            "5. 改册后：`_export_category_switch_audit.py` → "
            "`_sync_category_switch_pool.py` → 再生成随机",
            "",
        ]
    )

    INDEX.write_text("\n".join(index_rows), encoding="utf-8")
    print("wrote", INDEX)
    for key, n in sorted(kick_counts.items()):
        print(f"kicked_{key}", n)
    print("booklets", len(list(OUT_DIR.glob("*.md"))), "dir", OUT_DIR)


if __name__ == "__main__":
    main()
