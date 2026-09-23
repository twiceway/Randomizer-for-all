#!/usr/bin/env python3
"""Goods sub-category rules — user picks which subcats enter the shuffle pool."""

from __future__ import annotations

import csv
from pathlib import Path

# GUI: four top-level goods buckets (internal subcats unchanged for classification).
GOODS_GROUP_ORDER: tuple[str, ...] = ("quest", "important", "upgrade", "craft")

GOODS_GROUPS: dict[str, tuple[str, tuple[str, ...]]] = {
    "quest": (
        "任务",
        (
            "quest_key",
            "quest_note",
            "quest_unique",
            "wondrous_physick",
        ),
    ),
    "important": (
        "重要道具",
        (
            "golden_seed",
            "sacred_tear",
            "larval_tear",
            "memory_stone",
            "crystal_tear",
            # 骨灰 → 界面「法术」开关（与法术卢恩同册；2026-09-08）
            "remembrance",
            "great_rune",
            "sorcery_book",
            "incantation_book",
            # spell_rune → 界面「法术」开关（2026-09-08）
        ),
    ),
    "upgrade": (
        "强化材料",
        (
            "stone_smithing",
            "stone_somber",
            "stone_special",
            "spirit_upgrade",
        ),
    ),
    "craft": (
        "杂项",
        (
            "bolus",
            "grease",
            "pot_throw",
            "knife_throw",
            "food",
            "consumable_other",
            "rune",
            "misc",
            "mat_animal",
            "mat_plant",
            "mat_other",
        ),
    ),
}

GOODS_GROUP_HINTS: dict[str, str] = {
    "quest": "钥匙、说明、灵药瓶等影响剧情/玩法的道具",
    "important": "种子、圣杯露滴、铃珠、追忆等（结晶露滴等仍不进池；骨灰改挂法术）",
    "upgrade": "锻造石、失色石、铃兰/手套草等",
    "craft": "壶、脂、食材、卢恩、素材等杂物（不含魔法/祷告商品行）",
}

GOODS_GROUP_LABELS: dict[str, str] = {
    group_id: label for group_id, (label, _) in GOODS_GROUPS.items()
}

SUBCAT_TO_GOODS_GROUP: dict[str, str] = {
    subcat: group_id
    for group_id, (_, subcats) in GOODS_GROUPS.items()
    for subcat in subcats
}

# GUI display order
GOODS_SUBCAT_ORDER: tuple[str, ...] = (
    # 任务 / 进度
    "quest_key",
    "quest_note",
    "quest_unique",
    # 重要升级
    "golden_seed",
    "sacred_tear",
    "larval_tear",
    "memory_stone",
    "wondrous_physick",
    # 光柱素材
    "mat_animal",
    "mat_plant",
    "mat_other",
    # 强化
    "stone_smithing",
    "stone_somber",
    "stone_special",
    "spirit_upgrade",
    # 卢恩 / 法术卢恩
    "rune",
    "spell_rune",
    # 消耗 / 投掷
    "bolus",
    "grease",
    "pot_throw",
    "knife_throw",
    "food",
    "consumable_other",
    # 骨灰 / 露滴 / 追忆
    "spirit_lesser",
    "spirit_greater",
    "crystal_tear",
    "remembrance",
    "great_rune",
    # 法术书
    "sorcery_book",
    "incantation_book",
    "misc",
)

GOODS_SUBCAT_LABELS: dict[str, str] = {
    "quest_key": "任务·钥匙地图",
    "quest_note": "任务·说明信件",
    "quest_unique": "任务·唯一物品",
    "golden_seed": "黄金种子",
    "sacred_tear": "圣露滴",
    "larval_tear": "泪滴",
    "memory_stone": "铃珠",
    "wondrous_physick": "灵药圣杯瓶",
    "mat_animal": "素材·兽肉骨血",
    "mat_plant": "素材·花草果实",
    "mat_other": "素材·其他",
    "stone_smithing": "锻造石",
    "stone_somber": "失色锻造石",
    "stone_special": "特殊强化石",
    "spirit_upgrade": "铃兰/手套草",
    "rune": "卢恩符文",
    "spell_rune": "法术卢恩（微光～幽影）",
    "bolus": "抗性/失衡药",
    "grease": "油脂附魔",
    "pot_throw": "壶类",
    "knife_throw": "飞刀类",
    "food": "肉类食材",
    "consumable_other": "其他消耗品",
    "spirit_lesser": "骨灰·普通",
    "spirit_greater": "骨灰·传奇",
    "crystal_tear": "结晶露滴",
    "remembrance": "Boss追忆",
    "great_rune": "大卢恩",
    "sorcery_book": "魔法卷轴（换法术）",
    "incantation_book": "祷告书（换法术）",
    "misc": "其他道具",
}

GOODS_SUBCAT_HINTS: dict[str, str] = {
    "quest_key": "地图碎片、支线钥匙",
    "quest_note": "说明类、教程信",
    "quest_unique": "isOnlyOne 唯一道具",
    "golden_seed": "黄金种子",
    "sacred_tear": "圣露滴（含升级用）",
    "larval_tear": "泪滴",
    "memory_stone": "商人铃珠（229000 段，非卢恩光柱）",
    "wondrous_physick": "灵药瓶本身",
    "mat_animal": "兽骨、兽肉、血液等",
    "mat_plant": "蘑菇、花朵、果实（光柱多）",
    "mat_other": "其余制作素材",
    "stone_smithing": "锻造石1-8",
    "stone_somber": "失色锻造石",
    "stone_special": "龙鳞等特殊石",
    "spirit_upgrade": "墓地铃兰、手套草",
    "rune": "可捏碎卢恩（含地上 2900 段光柱占位）",
    "spell_rune": "捏碎获得一堆法术（法魂 CNV）",
    "bolus": "火/毒/出血药等",
    "grease": "油脂类",
    "pot_throw": "各类壶",
    "knife_throw": "飞刀、飞镖",
    "food": "生肉、干肉等",
    "consumable_other": "肥皂、诱敌等",
    "spirit_lesser": "普通骨灰",
    "spirit_greater": "传奇骨灰",
    "crystal_tear": "灵药露滴",
    "remembrance": "Boss追忆",
    "great_rune": "大卢恩",
    "sorcery_book": "辉石/卷轴",
    "incantation_book": "祷告书",
    "misc": "未归类",
}

# Never enter any pool (flasks of grace, critical keys)
HARD_EXCLUDE_GOODS_IDS = frozenset({
    12, 100, 101, 102, 130, 150, 240, 292, 310, 330,
    1001, 1051, 6001, 60000, 11500, 710000,
})

# Crimson / cerulean flask charges and wondrous physick flask pair.
FLASK_GOODS_RANGES: tuple[tuple[int, int], ...] = (
    (250, 251),
    (1000, 1099),
)

# E 键采集素材子类：不进洗牌目标池，不受 GUI 勾选影响。
# 尸体光柱战利品（41010xxx 等地上 lot）用 CSV 物品参与洗牌，runtime 差异见 lot_effective_items.json。
HARD_DISABLED_GOODS_SUBCATS = frozenset({
    "mat_animal",
    "mat_plant",
    "mat_other",
})

# CNV / 原版植物 E 键等采集专用 lot 段（与地上箱/尸体 lot 分开）。
GATHERING_LOT_RANGES: tuple[tuple[int, int], ...] = (
    (996000, 999999),
    (9990000, 9999999),
)

# May be reward target for multiple pickups (stacking items).
STACKABLE_GOODS_SUBCATS = frozenset({
    "stone_smithing",
    "stone_somber",
    "spirit_upgrade",
    "rune",
    "spell_rune",
    "golden_seed",
    "sacred_tear",
    "bolus",
    "grease",
    "pot_throw",
    "knife_throw",
    "food",
    "consumable_other",
})

# ID bands (inclusive)
GOLDEN_SEED_IDS = frozenset({10010})
SACRED_TEAR_IDS = frozenset({10020})
SACRED_TEAR_RANGES: tuple[tuple[int, int], ...] = ((1001, 1023),)
STARLIGHT_SHARD_IDS = frozenset({1290})
LARVAL_TEAR_IDS = frozenset({130})
# CNV map lots label these Golden Rune [N] — crushable runes, not memory stones.
CNV_MAP_RUNE_RANGES: tuple[tuple[int, int], ...] = ((2900, 2999),)
# Roundtable bell bearings (goodsType 7, same as ashes — disambiguate by ID band).
BELL_BEARING_RANGES: tuple[tuple[int, int], ...] = ((229000, 229099),)

SMITHING_STONE_RANGES: tuple[tuple[int, int], ...] = ((10100, 10139),)
SOMBER_STONE_RANGES: tuple[tuple[int, int], ...] = ((10160, 10299),)
SPECIAL_STONE_IDS = frozenset({10140, 10168})
SPIRIT_UPGRADE_RANGES: tuple[tuple[int, int], ...] = ((10900, 10999),)

# CNV spell runes: light-prefix + school + 卢恩 (微光腐败卢恩 … 幽影*).
# Internal CSV names remain \"* Tome #N\"; display names are Faint/Radiant/Shadow Rune.
SPELL_RUNE_RANGES: tuple[tuple[int, int], ...] = ((8300, 8485),)
# True spell-teach books (scrolls / prayerbooks) — NOT real sorcery/incantation goods.
SORCERY_TEACH_BOOK_IDS = frozenset({8850, 8851, 8852, 8853, 8854, 8866, 2008014})
INCANTATION_TEACH_BOOK_IDS = frozenset({
    8855, 8856, 8857, 8858, 8859, 8860, 8861, 8862, 8863, 8864, 8865,
})
TRUE_SPELL_TEACH_BOOK_IDS = SORCERY_TEACH_BOOK_IDS | INCANTATION_TEACH_BOOK_IDS
# CNV spell-rune crush lots (entity→lot collision). Do NOT use the full 942370xxx
# band — 942370060/070 are Gatefront wagon weapon chests.
SPELL_CRUSH_LOT_IDS = frozenset({942370020})
# Raw crafting meats (e.g. 生肉丸 1235): goodsType 0 + isDrop, not mat_other.
FOOD_CRAFT_REF_RANGES: tuple[tuple[int, int], ...] = ((501200, 501399),)
FOOD_CRAFT_IDS = frozenset({1235})
# CNV / 原版骨灰：末两位数 00=基础，01～10=+1～+10（同皮升级档）。
SPIRIT_ASH_GOODS_RANGES: tuple[tuple[int, int], ...] = (
    (200000, 299999),
    (2200000, 2699999),
)
RUNE_RANGES: tuple[tuple[int, int], ...] = CNV_MAP_RUNE_RANGES
MAT_ANIMAL_RANGES: tuple[tuple[int, int], ...] = ((15000, 15199),)
MAT_PLANT_RANGES: tuple[tuple[int, int], ...] = ((20650, 20899),)
BOLUS_RANGES: tuple[tuple[int, int], ...] = ((9000, 9599),)

MATERIAL_ORPHAN_RANGES: tuple[tuple[int, int], ...] = (
    (15000, 15999),
    (20000, 20999),
)

THROWABLE_USE_ANIMS = frozenset({1, 2, 3, 16, 17, 20})
GREASE_USE_ANIMS = frozenset({1, 16})
POT_USE_ANIMS = frozenset({3, 20})
KNIFE_USE_ANIMS = frozenset({2, 17})
FOOD_USE_ANIMS = frozenset({26})


def parse_int(value: str | None) -> int:
    if value is None:
        return 0
    value = str(value).strip()
    if not value or value in {"-", "-1"}:
        return 0
    try:
        return int(float(value))
    except ValueError:
        return 0


def in_ranges(item_id: int, ranges: tuple[tuple[int, int], ...]) -> bool:
    return any(lo <= item_id <= hi for lo, hi in ranges)


def goods_shuffle_key(subcat: str) -> str:
    return f"goods/{subcat}"


def subcat_to_goods_group(subcat: str) -> str | None:
    return SUBCAT_TO_GOODS_GROUP.get(subcat)


def expand_goods_group(group_id: str) -> set[str]:
    if group_id not in GOODS_GROUPS:
        return set()
    _, subcats = GOODS_GROUPS[group_id]
    return {s for s in subcats if s not in HARD_DISABLED_GOODS_SUBCATS}


def expand_goods_groups(group_ids: set[str]) -> set[str]:
    enabled: set[str] = set()
    for group_id in group_ids:
        enabled |= expand_goods_group(group_id)
    return enabled


def groups_from_enabled_subcats(enabled_subcats: set[str]) -> set[str]:
    groups: set[str] = set()
    for group_id in GOODS_GROUP_ORDER:
        pool = expand_goods_group(group_id)
        if pool & enabled_subcats:
            groups.add(group_id)
    return groups


def spell_rune_shuffle_enabled(cfg: dict) -> bool:
    """法术卢恩随界面「法术」开关（亦兼容 enabled_goods_subcats）。"""
    from cnv_randomizer_core import CAT_MAGIC

    if CAT_MAGIC in cfg.get("enabled_cats", set()):
        return True
    return "spell_rune" in cfg.get("enabled_goods_subcats", set())


def is_spell_rune_crush_lot(lot_id: int) -> bool:
    return lot_id in SPELL_CRUSH_LOT_IDS


def is_food_craft_item(item_id: int, row: dict[str, str] | None) -> bool:
    """Crafting meats / dried foods — GUI「肉类食材」, not mat_other."""
    if item_id in FOOD_CRAFT_IDS:
        return True
    if row is None:
        return False
    if parse_int(row.get("goodsUseAnim")) in FOOD_USE_ANIMS:
        return True
    ref_id = parse_int(row.get("refId_default"))
    if parse_int(row.get("goodsType")) == 0 and parse_int(row.get("isDrop")) == 1:
        if in_ranges(ref_id, FOOD_CRAFT_REF_RANGES):
            return True
    return False


def is_valid_cnv_shuffle_goods(item_id: int, cfg: dict) -> bool:
    """CNV-valid goods for shuffle targets — honors disableParam_NT（分类开关池内 / 卢恩/书例外）。"""
    goods_rows = cfg.get("goods_rows", {})
    row = goods_rows.get(item_id)
    if row is None:
        return False
    # Teach books may have empty Name on placeholder ids 8852–8854; still allow by id.
    named = bool((row.get("Name") or row.get("name") or "").strip())
    if not named and item_id not in TRUE_SPELL_TEACH_BOOK_IDS:
        return False
    if in_ranges(item_id, RUNE_RANGES):
        return True
    if in_ranges(item_id, SPELL_RUNE_RANGES):
        return True
    if item_id in TRUE_SPELL_TEACH_BOOK_IDS:
        return True
    if parse_int(row.get("disableParam_NT")) == 1:
        # 分类开关离线池已人审进池（锻造石/失色石/铃兰等）→ NT 例外
        all_ids = cfg.get("category_switch_all_ids")
        if all_ids is not None and item_id in all_ids:
            return True
        return False
    return True


def lot_has_spell_rune_item(row: dict[str, str], cfg: dict, iter_slots_fn) -> bool:
    goods_rows = cfg.get("goods_rows", {})
    for _slot_idx, _id_key, _cat_key, item_id, _lot_cat in iter_slots_fn(row):
        if is_spell_rune_item(item_id, goods_rows.get(item_id)):
            return True
    return False


def is_spell_rune_preserved(cfg: dict, item_id: int, row: dict[str, str] | None = None) -> bool:
    """Spell-rune map pickups stay vanilla unless user explicitly enables the subcat."""
    return is_spell_rune_item(item_id, row) and not spell_rune_shuffle_enabled(cfg)


def is_spell_teach_book_item(item_id: int) -> bool:
    return item_id in TRUE_SPELL_TEACH_BOOK_IDS


def is_spell_rune_item(item_id: int, row: dict[str, str] | None = None) -> bool:
    """CNV spell runes: id band 8300–8485 (微光…幽影 + 系别 + 卢恩)."""
    del row  # fingerprint is id-range; CSV Name is internal Tome label
    return in_ranges(item_id, SPELL_RUNE_RANGES)


def classify_goods_subcat(item_id: int, row: dict[str, str] | None) -> str:
    if item_id in GOLDEN_SEED_IDS:
        return "golden_seed"
    if item_id in SACRED_TEAR_IDS or in_ranges(item_id, SACRED_TEAR_RANGES):
        return "sacred_tear"
    if item_id in STARLIGHT_SHARD_IDS:
        # goodsType=2 would otherwise fall into mat_* (HARD_DISABLED gathering).
        return "consumable_other"
    if item_id in LARVAL_TEAR_IDS:
        return "larval_tear"
    if in_ranges(item_id, BELL_BEARING_RANGES):
        return "memory_stone"
    if is_spell_rune_item(item_id, row):
        return "spell_rune"
    if item_id in SORCERY_TEACH_BOOK_IDS:
        return "sorcery_book"
    if item_id in INCANTATION_TEACH_BOOK_IDS:
        return "incantation_book"
    if in_ranges(item_id, RUNE_RANGES):
        return "rune"
    if in_ranges(item_id, SPIRIT_UPGRADE_RANGES):
        return "spirit_upgrade"
    if in_ranges(item_id, SMITHING_STONE_RANGES):
        return "stone_smithing"
    if in_ranges(item_id, SOMBER_STONE_RANGES):
        return "stone_somber"
    if item_id in SPECIAL_STONE_IDS:
        return "stone_special"

    if row is None:
        if in_ranges(item_id, MAT_ANIMAL_RANGES):
            return "mat_animal"
        if in_ranges(item_id, MAT_PLANT_RANGES):
            return "mat_plant"
        if in_ranges(item_id, MATERIAL_ORPHAN_RANGES):
            return "mat_other"
        return "misc"

    goods_type = parse_int(row.get("goodsType"))
    is_consume = parse_int(row.get("isConsume"))
    is_only_one = parse_int(row.get("isOnlyOne"))
    is_drop = parse_int(row.get("isDrop"))
    use_anim = parse_int(row.get("goodsUseAnim"))

    if goods_type == 1:
        return "quest_key"
    if goods_type == 12:
        return "quest_note"
    if is_only_one or (goods_type == 0 and in_ranges(item_id, ((100, 199),))):
        return "quest_unique"
    if goods_type == 9:
        return "wondrous_physick"
    if goods_type == 14:
        return "stone_smithing"
    if is_food_craft_item(item_id, row):
        return "food"
    if goods_type == 2:
        if in_ranges(item_id, MAT_ANIMAL_RANGES):
            return "mat_animal"
        if in_ranges(item_id, MAT_PLANT_RANGES):
            return "mat_plant"
        return "mat_other"
    if is_drop and goods_type == 0:
        return "mat_other"
    if in_ranges(item_id, BELL_BEARING_RANGES):
        return "memory_stone"
    if goods_type == 7:
        return "spirit_lesser"
    if goods_type == 8:
        return "spirit_greater"
    if goods_type == 10:
        return "crystal_tear"
    if is_spell_rune_item(item_id, row):
        return "spell_rune"
    if goods_type == 3:
        return "remembrance"
    if goods_type == 15:
        return "great_rune"
    # goodsType 5/16–18 are NOT teach books (real spells / throwables). Teach books = id list only.
    if goods_type == 5:
        return "misc"
    if use_anim == 9:
        if is_spell_rune_item(item_id, row):
            return "spell_rune"
        return "rune"
    if goods_type in {16, 17, 18}:
        if use_anim in GREASE_USE_ANIMS:
            return "grease"
        if use_anim in POT_USE_ANIMS:
            return "pot_throw"
        if use_anim in KNIFE_USE_ANIMS:
            return "knife_throw"
        if use_anim in FOOD_USE_ANIMS:
            return "food"
        if is_consume:
            return "consumable_other"
        return "misc"
    if goods_type == 11:
        return "consumable_other"
    if goods_type == 0 and is_consume:
        if in_ranges(item_id, BOLUS_RANGES):
            return "bolus"
        return "consumable_other"
    return "misc"


def load_goods_rows(csv_dir: Path) -> dict[int, dict[str, str]]:
    path = csv_dir / "EquipParamGoods.csv"
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    out: dict[int, dict[str, str]] = {}
    for row in rows:
        item_id = parse_int(row.get("ID"))
        if item_id > 0:
            out[item_id] = row
    return out


def load_weapon_rows(csv_dir: Path) -> dict[int, dict[str, str]]:
    path = csv_dir / "EquipParamWeapon.csv"
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    out: dict[int, dict[str, str]] = {}
    for row in rows:
        item_id = parse_int(row.get("ID"))
        if item_id > 0:
            out[item_id] = row
    return out


def load_accessory_rows(csv_dir: Path) -> dict[int, dict[str, str]]:
    path = csv_dir / "EquipParamAccessory.csv"
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    out: dict[int, dict[str, str]] = {}
    for row in rows:
        item_id = parse_int(row.get("ID"))
        if item_id > 0:
            out[item_id] = row
    return out


def load_protector_rows(csv_dir: Path) -> dict[int, dict[str, str]]:
    path = csv_dir / "EquipParamProtector.csv"
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    out: dict[int, dict[str, str]] = {}
    for row in rows:
        item_id = parse_int(row.get("ID"))
        if item_id > 0:
            out[item_id] = row
    return out


def load_gem_rows(csv_dir: Path) -> dict[int, dict[str, str]]:
    path = csv_dir / "EquipParamGem.csv"
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    out: dict[int, dict[str, str]] = {}
    for row in rows:
        item_id = parse_int(row.get("ID"))
        if item_id > 0:
            out[item_id] = row
    return out


def _cnv_param_row_named(row: dict[str, str] | None) -> bool:
    if row is None:
        return False
    return bool((row.get("Name") or row.get("name") or "").strip())


def _cnv_param_row_valid(row: dict[str, str] | None) -> bool:
    """Named + NT=0 — for talisman (vanilla ER rows often NT=1 in CNV)."""
    if not _cnv_param_row_named(row):
        return False
    if parse_int(row.get("disableParam_NT")) == 1:
        return False
    return True


def is_valid_cnv_shuffle_talisman(item_id: int, cfg: dict) -> bool:
    """法魂护符靠遗物兑换，无拾取槽 — 永不进洗牌池（2026-09-08）。"""
    del item_id, cfg
    return False


def is_valid_cnv_shuffle_armor(item_id: int, cfg: dict) -> bool:
    """CNV lot armor — name only; NT=1 is common on valid CNV protector rows."""
    return _cnv_param_row_named(cfg.get("protector_rows", {}).get(item_id))


def is_valid_cnv_shuffle_ash(item_id: int, cfg: dict) -> bool:
    """CNV lot spirit ashes — name only; NT=1 is common on valid gem rows."""
    return _cnv_param_row_named(cfg.get("gem_rows", {}).get(item_id))


def is_pseudo_weapon_param_row(row: dict[str, str]) -> bool:
    """CNV placeholder rows in EquipParamWeapon (pots/puppets) — not equippable weapons."""
    return parse_int(row.get("equipModelId")) == 0 and parse_int(row.get("wepType")) == 0


def is_valid_cnv_shuffle_weapon(item_id: int, cfg: dict) -> bool:
    """CNV-valid weapon targets — named, real equipModel, not pseudo weapon-table rows."""
    weapon_rows = cfg.get("weapon_rows", {})
    row = weapon_rows.get(item_id)
    if row is None:
        return False
    if not (row.get("Name") or row.get("name") or "").strip():
        return False
    if is_pseudo_weapon_param_row(row):
        return False
    return True


def load_goods_subcat_index(csv_dir: Path) -> dict[int, str]:
    goods_rows = load_goods_rows(csv_dir)
    index: dict[int, str] = {}
    for item_id, row in goods_rows.items():
        index[item_id] = classify_goods_subcat(item_id, row)
    return index


def is_gathering_material_id(item_id: int) -> bool:
    return in_ranges(item_id, MAT_ANIMAL_RANGES) or in_ranges(
        item_id, MAT_PLANT_RANGES
    ) or in_ranges(item_id, MATERIAL_ORPHAN_RANGES)


def is_gathering_lot_id(lot_id: int) -> bool:
    """E-key / 光柱采集点 lot — never in slot_shuffle multiset."""
    return in_ranges(lot_id, GATHERING_LOT_RANGES)


def is_gathering_shuffle_source(
    item_id: int,
    cfg: dict,
    goods_row: dict[str, str] | None = None,
    *,
    lot_id: int | None = None,
) -> bool:
    """True only for E-key / 采集专用 lot — not corpse glow on ground lots."""
    if lot_id is not None:
        return is_gathering_lot_id(lot_id)
    return False


def goods_subcat_for(item_id: int, cfg: dict) -> str | None:
    index = cfg.get("goods_subcat_index", {})
    if item_id in index:
        return index[item_id]
    rows = cfg.get("goods_rows", {})
    if item_id not in rows:
        return None
    return classify_goods_subcat(item_id, rows[item_id])


def is_flask_goods(item_id: int) -> bool:
    return in_ranges(item_id, FLASK_GOODS_RANGES)


def goods_display_name(name: str | None) -> str:
    return str(name or "").strip()


def goods_name_is_info_note(name: str | None) -> bool:
    """「说明：…」类信件 — 2026-09-19 进池；制作笔记不含。"""
    return goods_display_name(name).startswith("说明")


def goods_name_is_map_fragment(name: str | None) -> bool:
    """地图碎片（含冒号变体）— 永不进池。"""
    s = goods_display_name(name)
    if s.startswith("地图碎片"):
        return True
    if s.startswith("地图：") or s.startswith("地图:"):
        return True
    low = s.lower()
    if low.startswith("map fragment") or low.startswith("map:"):
        return True
    return False


def is_spirit_ash_goods_id(item_id: int) -> bool:
    return in_ranges(item_id, SPIRIT_ASH_GOODS_RANGES)


def spirit_ash_base_id(item_id: int) -> int:
    """CNV/原版：末两位数 00=基础，01～10=+1～+10。"""
    if not is_spirit_ash_goods_id(item_id):
        return item_id
    rem = item_id % 100
    if rem <= 10:
        return item_id - rem
    return item_id


def is_spirit_ash_base_tier(item_id: int) -> bool:
    return is_spirit_ash_goods_id(item_id) and item_id == spirit_ash_base_id(item_id)


def is_goods_hard_excluded(item_id: int) -> bool:
    return item_id in HARD_EXCLUDE_GOODS_IDS or is_flask_goods(item_id)


def is_golden_rune_item(item_id: int) -> bool:
    return in_ranges(item_id, RUNE_RANGES)


def golden_rune_shuffle_sources_enabled(cfg: dict) -> bool:
    """True when GUI enabled_goods_subcats includes rune (卢恩符文)."""
    enabled = cfg.get("enabled_goods_subcats", set())
    return "rune" in enabled


def is_golden_rune_preserved(cfg: dict, item_id: int) -> bool:
    """GUI-only: golden rune lots participate when rune subcat is enabled."""
    return is_golden_rune_item(item_id) and not golden_rune_shuffle_sources_enabled(cfg)


def is_unique_pool_item(item_id: int, type_index: dict[int, int], cfg: dict) -> bool:
    """Weapons, bell bearings, etc. — reward target at most once per seed."""
    cat = type_index.get(item_id)
    if cat in {0, 2, 3, 4, 5}:  # weapon, armor, talisman, ash, magic
        return True
    if cat != 1:
        return True
    sub = goods_subcat_for(item_id, cfg)
    if sub is None:
        return True
    if sub in HARD_DISABLED_GOODS_SUBCATS:
        return False
    return sub not in STACKABLE_GOODS_SUBCATS


# Presets for GUI quick buttons (group level)
GOODS_GROUP_PRESET_PILLAR = frozenset({"upgrade", "craft"})
GOODS_GROUP_PRESET_SAFE = frozenset({"craft"})

GOODS_PRESET_PILLAR = frozenset({
    "stone_smithing",
    "stone_somber",
    "stone_special",
    "spirit_upgrade",
    "rune",
    "bolus",
    "grease",
    "pot_throw",
    "knife_throw",
    "food",
    "consumable_other",
})

GOODS_PRESET_SAFE = frozenset({
    "rune",
    "bolus",
    "grease",
    "pot_throw",
    "knife_throw",
    "food",
})
