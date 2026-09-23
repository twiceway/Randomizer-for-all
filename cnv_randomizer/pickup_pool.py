import json
from pathlib import Path

from paths import SCRIPT_DIR

from cnv_randomizer_core import (
    CAT_ARMOR,
    CAT_ASH,
    CAT_GOODS,
    CAT_MAGIC,
    CAT_NAMES,
    CAT_TALISMAN,
    CAT_WEAPON,
    DEFAULT_SHOP_LOT_RANGES,
    ShuffleKey,
    iter_slots,
    parse_int,
    read_csv,
)

def load_goods_ids(csv_dir: Path) -> set[int]:
    from goods_subcats import load_goods_rows

    return set(load_goods_rows(csv_dir).keys())

def resolve_item_category(
    item_id: int, lot_cat: int, type_index: dict[int, int]
) -> int | None:
    ti_cat = type_index.get(item_id)
    if ti_cat is None:
        if lot_cat == CAT_GOODS:
            return CAT_GOODS
        return None
    if lot_cat == ti_cat:
        return ti_cat
    # Equipment param tables win over a wrong ItemLot category (e.g. Greatsword
    # lot marked armor/cat=2 while EquipParamWeapon says weapon). Goods/talisman
    # id collisions still prefer the lot row (Rune Arc etc.).
    if ti_cat in {CAT_WEAPON, CAT_ARMOR, CAT_ASH, CAT_MAGIC}:
        return ti_cat
    if lot_cat in {
        CAT_WEAPON,
        CAT_GOODS,
        CAT_ARMOR,
        CAT_TALISMAN,
        CAT_ASH,
        CAT_MAGIC,
    }:
        return lot_cat
    return ti_cat

def resolve_shuffle_key(
    item_id: int,
    true_cat: int,
    cfg: dict,
) -> ShuffleKey | None:
    if true_cat != CAT_GOODS:
        return true_cat
    from goods_subcats import classify_goods_subcat, goods_shuffle_key

    goods_rows = cfg.get("goods_rows", {})
    subcat_index = cfg.get("goods_subcat_index", {})
    subcat = subcat_index.get(item_id)
    if subcat is None:
        subcat = classify_goods_subcat(item_id, goods_rows.get(item_id))
    return goods_shuffle_key(subcat)

def shuffle_key_enabled(key: ShuffleKey, cfg: dict) -> bool:
    if isinstance(key, str) and key.startswith("goods/"):
        subcat = key.split("/", 1)[1]
        from goods_subcats import HARD_DISABLED_GOODS_SUBCATS

        if subcat in HARD_DISABLED_GOODS_SUBCATS:
            return False
        if subcat == "spell_rune":
            from goods_subcats import spell_rune_shuffle_enabled

            return spell_rune_shuffle_enabled(cfg)
        if subcat in {"spirit_lesser", "spirit_greater"}:
            return CAT_MAGIC in cfg.get("enabled_cats", set()) or subcat in cfg.get(
                "enabled_goods_subcats", set()
            )
        return subcat in cfg.get("enabled_goods_subcats", set())
    if key == CAT_MAGIC:
        return False
    if key == CAT_TALISMAN:
        return False  # 遗物兑换，永不进池
    return key in cfg.get("enabled_cats", set())

def shuffle_key_label(key: ShuffleKey) -> str:
    if isinstance(key, str) and key.startswith("goods/"):
        from goods_subcats import GOODS_GROUP_LABELS, GOODS_SUBCAT_LABELS, subcat_to_goods_group

        sub = key.split("/", 1)[1]
        if sub == "spell_rune":
            return "法术卢恩"
        if sub in {"spirit_lesser", "spirit_greater"}:
            return "法术/骨灰"
        group_id = subcat_to_goods_group(sub)
        if group_id:
            return f"道具/{GOODS_GROUP_LABELS.get(group_id, group_id)}"
        return f"道具/{GOODS_SUBCAT_LABELS.get(sub, sub)}"
    if int(key) == CAT_MAGIC:
        return "法术卢恩"
    return CAT_NAMES.get(int(key), str(key))

def load_dlc_item_rules(path: Path | None = None) -> list[tuple[int, int]]:
    return load_dlc_rules(path).item_ranges

def load_dlc_rules(path: Path | None = None) -> dict:
    path = path or (SCRIPT_DIR / "dlc_item_rules.json")
    if not path.exists():
        return {"item_ranges": [], "lot_ranges": [], "region_keywords": []}
    data = json.loads(path.read_text(encoding="utf-8"))

    def _ranges(key: str) -> list[tuple[int, int]]:
        out: list[tuple[int, int]] = []
        for entry in data.get(key, []):
            if len(entry) != 2:
                continue
            lo, hi = int(entry[0]), int(entry[1])
            if lo <= hi:
                out.append((lo, hi))
        return out

    return {
        "item_ranges": _ranges("id_ranges"),
        "lot_ranges": _ranges("lot_id_ranges"),
        "region_keywords": [
            str(k).strip() for k in data.get("region_keywords", []) if str(k).strip()
        ],
    }

def is_dlc_lot(
    row: dict[str, str],
    lot_id: int,
    type_index: dict[int, int],
    dlc_rules: dict,
) -> bool:
    for lo, hi in dlc_rules.get("lot_ranges", []):
        if lo <= lot_id <= hi:
            return True
    name = (row.get("Name") or "").lower()
    for keyword in dlc_rules.get("region_keywords", []):
        if keyword.lower() in name:
            return True
    item_ranges = dlc_rules.get("item_ranges", [])
    for _slot_idx, _id_key, _cat_key, item_id, _lot_cat in iter_slots(row):
        if item_id > 0 and is_dlc_item(item_id, item_ranges):
            return True
    return False

def lot_in_randomize_pool(
    row: dict[str, str],
    lot_id: int,
    cfg: dict,
    type_index: dict[int, int],
    dlc_rules: dict,
) -> bool:
    from goods_subcats import (
        is_gathering_lot_id,
        lot_has_spell_rune_item,
        spell_rune_shuffle_enabled,
    )

    if is_gathering_lot_id(lot_id):
        return False
    if not is_randomizable_lot(lot_id, cfg):
        return False
    if lot_has_spell_rune_item(row, cfg, iter_slots) and not spell_rune_shuffle_enabled(cfg):
        return False
    if cfg.get("include_dlc", True):
        return True
    return not is_dlc_lot(row, lot_id, type_index, dlc_rules)

def is_dlc_item(item_id: int, dlc_ranges: list[tuple[int, int]]) -> bool:
    return any(lo <= item_id <= hi for lo, hi in dlc_ranges)

def item_allowed_by_dlc(item_id: int, cfg: dict, dlc_ranges: list[tuple[int, int]]) -> bool:
    if cfg.get("include_dlc", True):
        return True
    return not is_dlc_item(item_id, dlc_ranges)

def load_item_type_index(csv_dir: Path) -> dict[int, int]:
    index: dict[int, int] = {}
    sources: list[tuple[str, int]] = [
        ("EquipParamGoods.csv", CAT_GOODS),
        ("EquipParamWeapon.csv", CAT_WEAPON),
        ("EquipParamProtector.csv", CAT_ARMOR),
        ("EquipParamAccessory.csv", CAT_TALISMAN),
        ("EquipParamGem.csv", CAT_ASH),
        ("Magic.csv", CAT_MAGIC),
        ("EquipParamCustomWeapon.csv", CAT_WEAPON),
    ]
    for filename, cat in sources:
        path = csv_dir / filename
        if not path.exists():
            continue
        _, rows = read_csv(path)
        for row in rows:
            item_id = parse_int(row.get("ID"))
            if item_id > 0 and item_id not in index:
                index[item_id] = cat
    return index

def classify_item(item_id: int, lot_cat: int, type_index: dict[int, int]) -> int | None:
    return resolve_item_category(item_id, lot_cat, type_index)

def is_shop_lot(lot_id: int, ranges: list[tuple[int, int]]) -> bool:
    return any(lo <= lot_id <= hi for lo, hi in ranges)

def is_skipped_lot(lot_id: int, ranges: list[tuple[int, int]]) -> bool:
    return any(lo <= lot_id <= hi for lo, hi in ranges)

def is_randomizable_lot(lot_id: int, cfg: dict) -> bool:
    from goods_subcats import is_spell_rune_crush_lot, spell_rune_shuffle_enabled

    if is_spell_rune_crush_lot(lot_id) and not spell_rune_shuffle_enabled(cfg):
        return False
    if lot_id in cfg["skip_lot_ids"]:
        return False
    if is_shop_lot(lot_id, cfg["shop_lot_ranges"]):
        return False
    if is_skipped_lot(lot_id, cfg.get("skip_lot_ranges", [])):
        return False
    return True

def count_kept_slots(
    rows: list[dict[str, str]], cfg: dict, type_index: dict[int, int]
) -> int:
    """Slots with items that exist but are not in any enabled shuffle pool."""
    dlc_rules = cfg.get("dlc_rules") or load_dlc_rules()
    kept = 0
    for row in rows:
        lot_id = parse_int(row.get("ID"))
        if not lot_in_randomize_pool(row, lot_id, cfg, type_index, dlc_rules):
            continue
        for slot_idx, id_key, cat_key, item_id, lot_cat in iter_slots(row):
            if item_id <= 0:
                continue
            if item_id in cfg.get("exclude_item_ids", set()):
                kept += 1
                continue
            true_cat = resolve_item_category(item_id, lot_cat, type_index)
            if true_cat is None:
                continue
            shuffle_key = resolve_shuffle_key(item_id, true_cat, cfg)
            if shuffle_key is None or not shuffle_key_enabled(shuffle_key, cfg):
                kept += 1
    return kept

def lot_randomizable_slots(
    row: dict[str, str], cfg: dict, type_index: dict[int, int]
) -> list[tuple[int, str, str, int, int, int, ShuffleKey]]:
    exclude = cfg["exclude_item_ids"]
    dlc_ranges = cfg.get("dlc_ranges", [])
    from goods_subcats import (
        is_golden_rune_preserved,
        is_spell_rune_preserved,
    )

    hits = []
    goods_rows = cfg.get("goods_rows", {})
    for slot_idx, id_key, cat_key, item_id, lot_cat in iter_slots(row):
        if item_id <= 0 or item_id in exclude:
            continue
        # Shuffle pool uses CSV item id. Gathering lots are excluded in
        # lot_in_randomize_pool(); corpse material glows (e.g. 41010240) stay in.
        source_id = item_id
        if not item_allowed_by_dlc(source_id, cfg, dlc_ranges):
            continue
        if is_spell_rune_preserved(cfg, source_id, goods_rows.get(source_id)):
            continue
        if is_golden_rune_preserved(cfg, source_id):
            continue
        from goods_subcats import is_goods_hard_excluded, goods_name_is_map_fragment

        if is_goods_hard_excluded(source_id):
            continue
        gname = str((goods_rows.get(source_id) or {}).get("Name") or "")
        if goods_name_is_map_fragment(gname):
            continue
        true_cat = resolve_item_category(source_id, lot_cat, type_index)
        if true_cat is None:
            continue
        from goods_subcats import (
            is_valid_cnv_shuffle_ash,
            is_valid_cnv_shuffle_armor,
            is_valid_cnv_shuffle_goods,
            is_valid_cnv_shuffle_talisman,
            is_valid_cnv_shuffle_weapon,
        )

        if true_cat == CAT_GOODS and not is_valid_cnv_shuffle_goods(source_id, cfg):
            continue
        if true_cat == CAT_WEAPON and not is_valid_cnv_shuffle_weapon(source_id, cfg):
            continue
        if true_cat == CAT_TALISMAN and not is_valid_cnv_shuffle_talisman(source_id, cfg):
            continue
        if true_cat == CAT_ARMOR and not is_valid_cnv_shuffle_armor(source_id, cfg):
            continue
        if true_cat == CAT_ASH and not is_valid_cnv_shuffle_ash(source_id, cfg):
            continue
        shuffle_key = resolve_shuffle_key(source_id, true_cat, cfg)
        if shuffle_key is None or not shuffle_key_enabled(shuffle_key, cfg):
            continue
        hits.append(
            (slot_idx, id_key, cat_key, item_id, source_id, true_cat, shuffle_key)
        )
    return hits

def _row_has_display_name(row: dict[str, str]) -> bool:
    return bool((row.get("Name") or row.get("name") or "").strip())

def _valid_goods_ids(goods_rows: dict[int, dict[str, str]], type_index: dict[int, int]) -> set[int]:
    """Goods with a CSV name and not disableParam_NT — avoids [ERROR] / ?GoodsInfo? pickups."""
    from goods_subcats import is_valid_cnv_shuffle_goods

    ids: set[int] = set()
    cfg_stub = {"goods_rows": goods_rows}
    for item_id, row in goods_rows.items():
        if type_index.get(item_id) != CAT_GOODS:
            continue
        if is_valid_cnv_shuffle_goods(item_id, cfg_stub):
            ids.add(item_id)
    return ids

def is_valid_shuffle_target(item_id: int, type_index: dict[int, int], cfg: dict) -> bool:
    """Items allowed as slot_shuffle reward targets (CNV NT filter + hard excludes)."""
    from goods_subcats import (
        is_gathering_material_id,
        is_goods_hard_excluded,
        is_pseudo_weapon_param_row,
        is_valid_cnv_shuffle_ash,
        is_valid_cnv_shuffle_armor,
        is_valid_cnv_shuffle_goods,
        is_valid_cnv_shuffle_talisman,
        is_valid_cnv_shuffle_weapon,
    )

    pool = cfg.get("shuffle_target_pool")
    if pool is not None and item_id not in pool:
        return False
    # 离线分类开关全集：表外物永不作目标（即使未先设 shuffle_target_pool）
    all_ids = cfg.get("category_switch_all_ids")
    if all_ids is not None and item_id not in all_ids:
        return False
    if item_id <= 0 or item_id in cfg.get("exclude_item_ids", set()):
        return False
    # 采集素材可进分类开关展示，但 hook 写出层会丢弃 — 抽签阶段即禁止
    if is_gathering_material_id(item_id):
        return False
    cat = type_index.get(item_id)
    if cat == CAT_GOODS:
        if is_goods_hard_excluded(item_id):
            return False
        if not is_valid_cnv_shuffle_goods(item_id, cfg):
            return False
        from goods_subcats import goods_name_is_map_fragment

        gname = str((cfg.get("goods_rows") or {}).get(item_id, {}).get("Name") or "")
        if goods_name_is_map_fragment(gname):
            return False
    if cat == CAT_WEAPON and not is_valid_cnv_shuffle_weapon(item_id, cfg):
        return False
    if cat == CAT_TALISMAN and not is_valid_cnv_shuffle_talisman(item_id, cfg):
        return False
    if cat == CAT_ARMOR and not is_valid_cnv_shuffle_armor(item_id, cfg):
        return False
    if cat == CAT_ASH and not is_valid_cnv_shuffle_ash(item_id, cfg):
        return False
    return True

def _named_equipment_ids(
    csv_dir: Path, type_index: dict[int, int], cat: int, csv_name: str
) -> set[int]:
    path = csv_dir / csv_name
    if not path.exists():
        return set()
    ids: set[int] = set()
    _, rows = read_csv(path)
    from goods_subcats import is_pseudo_weapon_param_row

    for row in rows:
        item_id = parse_int(row.get("ID"))
        if item_id <= 0 or type_index.get(item_id) != cat:
            continue
        if cat == CAT_WEAPON and is_pseudo_weapon_param_row(row):
            continue
        if _row_has_display_name(row):
            ids.add(item_id)
    return ids

def _base_equipment_ids(
    csv_dir: Path, type_index: dict[int, int], cat: int, csv_name: str
) -> set[int]:
    """Lowest named item id per id//100 group — one entry per upgrade line."""
    path = csv_dir / csv_name
    if not path.exists():
        return set()
    groups: dict[int, int] = {}
    _, rows = read_csv(path)
    for row in rows:
        item_id = parse_int(row.get("ID"))
        if item_id <= 0 or type_index.get(item_id) != cat:
            continue
        if not _row_has_display_name(row):
            continue
        group = item_id // 100
        prev = groups.get(group)
        groups[group] = item_id if prev is None else min(prev, item_id)
    return set(groups.values())

def _weapon_groups_in_lots(
    rows: list[dict[str, str]], type_index: dict[int, int]
) -> set[int]:
    """Weapon id//100 groups that appear in any ItemLotParam_map row."""
    groups: set[int] = set()
    for row in rows:
        for _slot_idx, _id_key, _cat_key, item_id, lot_cat in iter_slots(row):
            if item_id <= 0:
                continue
            true_cat = resolve_item_category(item_id, lot_cat, type_index)
            if true_cat == CAT_WEAPON:
                groups.add(item_id // 100)
    return groups

def _collectible_weapon_ids(
    csv_dir: Path,
    rows: list[dict[str, str]],
    type_index: dict[int, int],
) -> set[int]:
    """Base-tier weapons whose line appears in the item lot table."""
    allowed_groups = _weapon_groups_in_lots(rows, type_index)
    if not allowed_groups:
        return set()
    path = csv_dir / "EquipParamWeapon.csv"
    if not path.exists():
        return set()
    groups: dict[int, int] = {}
    _, wrows = read_csv(path)
    from goods_subcats import is_pseudo_weapon_param_row

    for row in wrows:
        item_id = parse_int(row.get("ID"))
        if type_index.get(item_id) != CAT_WEAPON:
            continue
        if is_pseudo_weapon_param_row(row):
            continue
        if not _row_has_display_name(row):
            continue
        group = item_id // 100
        if group not in allowed_groups:
            continue
        prev = groups.get(group)
        groups[group] = item_id if prev is None else min(prev, item_id)
    return set(groups.values())

def _pool_accepts_item(
    item_id: int,
    cat: int,
    cfg: dict,
    type_index: dict[int, int],
    collectible_weapons: set[int],
    base_armor: set[int],
    named_armor: set[int],
    named_weapons: set[int],
    valid_goods: set[int],
) -> bool:
    from goods_subcats import (
        is_goods_hard_excluded,
        is_spirit_ash_base_tier,
        is_spirit_ash_goods_id,
    )

    if item_id <= 0 or item_id in cfg.get("exclude_item_ids", set()):
        return False
    if not item_allowed_by_dlc(item_id, cfg, cfg.get("dlc_ranges", [])):
        return False
    if cat == CAT_WEAPON:
        if item_id not in collectible_weapons:
            return False
        if item_id not in named_weapons:
            return False
    if cat == CAT_ARMOR:
        if item_id not in base_armor:
            return False
        if item_id not in named_armor:
            return False
    if cat == CAT_GOODS and is_goods_hard_excluded(item_id):
        return False
    if cat == CAT_GOODS and item_id not in valid_goods:
        return False
    if cat == CAT_GOODS and is_spirit_ash_goods_id(item_id) and not is_spirit_ash_base_tier(item_id):
        return False
    if cat == CAT_TALISMAN:
        from goods_subcats import is_valid_cnv_shuffle_talisman

        if not is_valid_cnv_shuffle_talisman(item_id, cfg):
            return False
    if cat == CAT_ARMOR:
        from goods_subcats import is_valid_cnv_shuffle_armor

        if not is_valid_cnv_shuffle_armor(item_id, cfg):
            return False
    if cat == CAT_ASH:
        from goods_subcats import is_valid_cnv_shuffle_ash

        if not is_valid_cnv_shuffle_ash(item_id, cfg):
            return False
    shuffle_key = resolve_shuffle_key(item_id, cat, cfg)
    if shuffle_key is None or not shuffle_key_enabled(shuffle_key, cfg):
        return False
    return True

def build_unified_pool(
    rows: list[dict[str, str]], cfg: dict, type_index: dict[int, int]
) -> set[int]:
    """可捐目标池 = 分类开关离线表 ∩ GUI 分开开关为开。

    ``rows`` / ``type_index`` 保留签名兼容调用方；池真源不再扫全 ton。
    """
    del rows, type_index  # 池不依赖 ton 扫表
    if cfg.get("category_switch_items") is None:
        from category_switch_pool import apply_category_switch_pool_to_cfg

        apply_category_switch_pool_to_cfg(cfg)
    from category_switch_pool import build_pool_from_category_switch

    return build_pool_from_category_switch(cfg)

