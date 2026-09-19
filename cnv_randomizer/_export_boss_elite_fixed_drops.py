# -*- coding: utf-8 -*-
"""Export multi-category pickup audit tables (Chinese) — temporary contract."""
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

import cnv_randomizer_core as core
from cnv_randomizer_core import (
    CAT_ARMOR,
    CAT_ASH,
    CAT_GOODS,
    CAT_TALISMAN,
    CAT_WEAPON,
    iter_slots,
    load_item_type_index,
    read_csv,
)
from goods_subcats import (
    GOLDEN_SEED_IDS,
    GOODS_SUBCAT_LABELS,
    MAT_ANIMAL_RANGES,
    SMITHING_STONE_RANGES,
    SOMBER_STONE_RANGES,
    SPIRIT_UPGRADE_RANGES,
    classify_goods_subcat,
    in_ranges,
    is_goods_hard_excluded,
    is_valid_cnv_shuffle_goods,
    load_accessory_rows,
    load_goods_rows,
    load_goods_subcat_index,
    load_protector_rows,
    load_weapon_rows,
)
from lot_effective import load_lot_effective_items
from pickup_pool import lot_in_randomize_pool, lot_randomizable_slots, resolve_item_category
from pickup_shuffle import _lot_name_looks_boss_reward
from pickup_slot_index import DEFAULT_PICKUP_INDEX_PATH, load_pickup_slot_index

ROOT = Path(__file__).resolve().parent
REPORTS = ROOT.parent / "reports"
OUT_INDEX = REPORTS / "Boss精英固定掉落审计表_当前.md"
OUT_PARTS = {
    "怪物": REPORTS / "物品槽审计_怪物固定掉落_当前.md",
    "箱子": REPORTS / "物品槽审计_箱子_当前.md",
    "地光": REPORTS / "物品槽审计_地光_当前.md",
    "尸体_上": REPORTS / "物品槽审计_地图尸体_上_当前.md",
    "尸体_下": REPORTS / "物品槽审计_地图尸体_下_当前.md",
}
# 旧单文件尸体册（若存在则删，避免再打开卡顿）
OUT_CORPSE_LEGACY = REPORTS / "物品槽审计_地图尸体_当前.md"
ZH_FMG = ROOT / "cache" / "item_names_zhocn_dlc02.json"
EN_FMG = ROOT / "cache" / "item_names_engus_dlc02.json"

CAT_ZH = {
    CAT_WEAPON: "武器",
    CAT_GOODS: "道具",
    CAT_ARMOR: "防具",
    CAT_TALISMAN: "护符",
    CAT_ASH: "战灰",
}

CHEST_ZH = {1: "箱子", 2: "地光", 0: "地图尸体等"}

AREA_ABBR = {
    "LD": "传说掉落",
    "Limgrave": "宁姆格福",
    "Liurnia": "利耶尼亚",
    "Caelid": "盖利德",
    "Altus": "亚坛高原",
    "Altus Plateau": "亚坛高原",
    "Mt. Gelmir": "格密尔火山",
    "Mountaintops": "巨人山顶",
    "Mountaintops of the Giants": "巨人山顶",
    "Consecrated Snowfield": "化圣雪原",
    "Haligtree": "圣树",
    "Miquella's Haligtree": "米凯拉的圣树",
    "Farum Azula": "化为灰烬的法姆·亚兹拉",
    "Deeproot Depths": "深根底层",
    "Ainsel": "安瑟尔河",
    "Ainsel River": "安瑟尔河",
    "Siofra": "希芙拉河",
    "Siofra River": "希芙拉河",
    "Nokron": "诺克龙",
    "Nokstella": "诺克史黛拉",
    "Lake of Rot": "腐败湖",
    "Lake or Rot": "腐败湖",
    "Mohgwyn Palace": "蒙格温王朝",
    "Volcano Manor": "火山官邸",
    "Raya Lucaria": "雷亚卢卡利亚学院",
    "Stormveil": "史东薇尔城",
    "Weeping Peninsula": "啜泣半岛",
    "Weeping Penisula": "啜泣半岛",
    "Caria Manor": "卡利亚城馆",
    "Field": "野外",
    "Evergaol": "监牢",
    "Godrick": "接肢葛瑞克",
    "Margit": "恶兆妖鬼玛尔基特",
    "Morgott": "恶兆蒙格特",
    "Mohg": "血王蒙格",
    "Malenia": "女武神玛莲妮亚",
    "Radahn": "星碎拉塔恩",
    "Radagon": "拉达冈",
    "Rennala": "满月女王蕾娜菈",
    "Rykard": "亵渎君王拉卡德",
    "Astel": "黑暗弃子艾丝缇",
    "Placidusax": "龙王普拉基杜萨克斯",
    "Fortissax": "死龙弗尔桑克斯",
    "Loretta": "骑士罗蕾塔",
    "Godfrey": "初王葛孚雷",
    "Hoarah Loux": "荷莱·露",
    "Maliketh": "黑剑玛利喀斯",
    "Fire Giant": "火焰巨人",
    "Elden Beast": "艾尔登之兽",
    "Siluria": "熔炉骑士希芙利亚",
    "Siluria's boss drop": "熔炉骑士希芙利亚",
    "Oleg": "流放骑士奥列格",
    "Oleg boss": "流放骑士奥列格",
}


def _load_fmg_pair() -> tuple[dict[str, dict[str, str]], dict[str, str]]:
    zh = json.loads(ZH_FMG.read_text(encoding="utf-8"))
    en = json.loads(EN_FMG.read_text(encoding="utf-8"))
    phrase: dict[str, str] = {}
    for key in (
        "PlaceName.fmg",
        "PlaceName_dlc01.fmg",
        "NpcName.fmg",
        "NpcName_dlc01.fmg",
        "GoodsName.fmg",
        "GoodsName_dlc01.fmg",
        "WeaponName.fmg",
        "WeaponName_dlc01.fmg",
        "ProtectorName.fmg",
        "ProtectorName_dlc01.fmg",
        "AccessoryName.fmg",
        "AccessoryName_dlc01.fmg",
        "ArtsName.fmg",
        "ArtsName_dlc01.fmg",
        "GemName.fmg",
        "GemName_dlc01.fmg",
    ):
        em = en.get(key) or {}
        zm = zh.get(key) or {}
        for iid, e in em.items():
            z = (zm.get(iid) or "").strip()
            e = (e or "").strip()
            if e and z and e not in phrase:
                phrase[e] = z
    phrase.update(AREA_ABBR)
    return zh, phrase


def _merge_name_maps(zh_fmg: dict) -> dict[str, dict[int, str]]:
    out: dict[str, dict[int, str]] = {
        "goods": {},
        "weapon": {},
        "protector": {},
        "accessory": {},
        "arts": {},
        "gem": {},
    }
    pairs = [
        ("goods", ("GoodsName.fmg", "GoodsName_dlc01.fmg", "GoodsName_dlc02.fmg")),
        ("weapon", ("WeaponName.fmg", "WeaponName_dlc01.fmg", "WeaponName_dlc02.fmg")),
        ("protector", ("ProtectorName.fmg", "ProtectorName_dlc01.fmg", "ProtectorName_dlc02.fmg")),
        ("accessory", ("AccessoryName.fmg", "AccessoryName_dlc01.fmg", "AccessoryName_dlc02.fmg")),
        ("arts", ("ArtsName.fmg", "ArtsName_dlc01.fmg", "ArtsName_dlc02.fmg")),
        ("gem", ("GemName.fmg", "GemName_dlc01.fmg", "GemName_dlc02.fmg")),
    ]
    for bucket, keys in pairs:
        for key in keys:
            for sid, name in (zh_fmg.get(key) or {}).items():
                if sid.isdigit() and name:
                    out[bucket][int(sid)] = name
    return out


def _zh_phrase(text: str, phrase: dict[str, str]) -> str:
    t = (text or "").strip()
    if not t:
        return ""
    if t in phrase:
        return phrase[t]
    if " - " in t:
        parts = [p.strip() for p in t.split(" - ")]
        return " · ".join(_zh_phrase(p, phrase) for p in parts if p)
    best = ""
    best_z = ""
    for e, z in phrase.items():
        if len(e) < 4:
            continue
        if e in t and len(e) > len(best):
            best, best_z = e, z
    if best_z:
        return best_z if best == t else t.replace(best, best_z)
    return t


def _area_enemy(name: str) -> tuple[str, str]:
    m = re.match(r"^\[([^\]]+)\]", (name or "").strip())
    if not m:
        return ("（无括号）", "")
    inside = m.group(1).strip()
    if " - " in inside:
        a, e = inside.split(" - ", 1)
        return (a.strip() or "（空）", e.strip())
    return (inside or "（空）", "")


def _item_name_en(iid: int, cat: int | None, cfg: dict) -> str:
    if cat == CAT_GOODS or iid in cfg["goods_rows"]:
        return (cfg["goods_rows"].get(iid) or {}).get("Name") or ""
    if cat == CAT_WEAPON:
        return (cfg.get("weapon_rows") or {}).get(iid, {}).get("Name") or ""
    if cat == CAT_ARMOR:
        return (cfg.get("protector_rows") or {}).get(iid, {}).get("Name") or ""
    if cat == CAT_TALISMAN:
        return (cfg.get("accessory_rows") or {}).get(iid, {}).get("Name") or ""
    return ""


def _item_name_zh(iid: int, cat: int | None, cfg: dict, names: dict) -> str:
    if cat == CAT_ASH:
        return names["arts"].get(iid) or names["gem"].get(iid) or ""
    if cat == CAT_WEAPON:
        return names["weapon"].get(iid) or ""
    if cat == CAT_ARMOR:
        return names["protector"].get(iid) or ""
    if cat == CAT_TALISMAN:
        return names["accessory"].get(iid) or ""
    for bucket in ("goods", "weapon", "protector", "accessory", "arts", "gem"):
        if iid in names[bucket]:
            return names[bucket][iid]
    return ""


def _item_kind(iid: int, cat: int | None, cfg: dict) -> str:
    if cat == CAT_GOODS or iid in cfg["goods_rows"]:
        sc = classify_goods_subcat(iid, cfg["goods_rows"].get(iid))
        return GOODS_SUBCAT_LABELS.get(sc, sc)
    return CAT_ZH.get(cat if cat is not None else -1, "其它")


def _is_bell_bearing(iid: int, kind: str, name_zh: str = "") -> bool:
    if kind == "铃珠":
        return True
    if 8900 <= iid <= 8999:
        return True
    if "铃珠" in (name_zh or ""):
        return True
    return False


def _is_friendly_npc_lot(lot_name: str) -> bool:
    n = (lot_name or "").strip()
    return n.startswith("[Corpse -") or n.lower().startswith("[corpse -")


SHADOW_RUNE_ZH = {
    2002950: "蕾妲的卢恩",
    2002951: "破碎卢恩",
    2002952: "幽影之地卢恩【１】",
    2002953: "幽影之地卢恩【２】",
    2002954: "幽影之地卢恩【３】",
    2002955: "幽影之地卢恩【４】",
    2002956: "幽影之地卢恩【５】",
    2002957: "幽影之地卢恩【６】",
    2002958: "幽影之地卢恩【７】",
    2002959: "无名英雄的卢恩",
    2002960: "玛丽卡的卢恩",
}


def _audit_allow_label(iid: int, kind: str, name_zh: str = "") -> str:
    """审计口径：关掉标记/排除名单仍进池的同类。洗牌代码待改。"""
    if _is_bell_bearing(iid, kind, name_zh):
        return ""
    if in_ranges(iid, SOMBER_STONE_RANGES):
        return "失色石"
    if (
        kind == "锻造石"
        or kind == "特殊强化石"
        or in_ranges(iid, SMITHING_STONE_RANGES)
        or iid == 10140
    ):
        return "锻造石"
    if kind == "铃兰/手套草" or in_ranges(iid, SPIRIT_UPGRADE_RANGES):
        return "铃兰"
    if iid in (190, 4070):
        return "卢恩弯弧"
    if in_ranges(iid, MAT_ANIMAL_RANGES):
        return "兽肉骨血素材"
    if kind in ("骨灰·普通", "骨灰·传奇") and iid % 10 == 0:
        return "骨灰"
    if kind == "黄金种子" or iid in GOLDEN_SEED_IDS:
        return "黄金种子"
    if kind == "Boss追忆" or in_ranges(iid, ((20900, 20999), (2950, 2971))):
        return "追忆遗物"
    if 2500 <= iid <= 2503:
        return "坐骑"
    if iid in (3360, 3361):
        return "床帘恩泽"
    if kind == "壶类" or 300 <= iid <= 680:
        return "壶"
    if in_ranges(iid, ((2002950, 2002960),)):
        return "幽影之地卢恩"
    if iid in (102, 107, 111, 113, 172, 183) or "血指" in (name_zh or ""):
        return "血指"
    if 3500 <= iid <= 3610 or "香药" in (name_zh or ""):
        return "香药"
    return ""


def _lot_items(
    row: dict,
    type_index,
    cfg: dict,
    names: dict,
    ex: set,
    goods: dict,
) -> list[dict]:
    items: list[dict] = []
    for slot_idx, _, _, iid, lot_cat in iter_slots(row):
        if iid <= 0:
            continue
        tc = resolve_item_category(iid, lot_cat, type_index)
        kind = _item_kind(iid, tc, cfg)
        zh_n = _item_name_zh(iid, tc, cfg, names) or SHADOW_RUNE_ZH.get(iid, "")
        en_n = _item_name_en(iid, tc, cfg)
        label = _audit_allow_label(iid, kind, zh_n)
        blocked: list[str] = []
        if iid in ex and not label:
            blocked.append("排除名单")
        nt_blocked = (tc == CAT_GOODS or iid in goods) and not is_valid_cnv_shuffle_goods(
            iid, cfg
        )
        if nt_blocked and not label:
            blocked.append("关掉标记")
        items.append(
            {
                "slot": slot_idx,
                "iid": iid,
                "kind": kind,
                "name_zh": zh_n or en_n or str(iid),
                "name_en": en_n,
                "blocked": blocked,
                "nt_exception": label,
            }
        )
    return items


def _drop_brief(items: list[dict], limit: int = 140) -> str:
    parts = []
    for it in items:
        s = it["name_zh"]
        notes = list(it["blocked"])
        if it.get("nt_exception"):
            notes.append(f"{it['nt_exception']}·按新口径进池")
        if notes:
            s += "（" + "、".join(notes) + "）"
        parts.append(s)
    return "；".join(parts)[:limit]


def _item_ok(it: dict) -> bool:
    if _is_bell_bearing(it["iid"], it.get("kind") or "", it.get("name_zh") or ""):
        return False
    return (not it["blocked"]) or bool(it.get("nt_exception"))


def _hard_deny(lot_name: str, items: list[dict]) -> tuple[str, str] | None:
    if _is_friendly_npc_lot(lot_name):
        return "不进池", "友善NPC掉落不进池"
    if items and all(
        _is_bell_bearing(it["iid"], it.get("kind") or "", it.get("name_zh") or "")
        for it in items
    ):
        return "不进池", "铃珠不进池"
    return None


def _pool_reason_ok(items: list[dict], live: bool) -> str:
    labels = sorted({it["nt_exception"] for it in items if it.get("nt_exception")})
    if labels and not live:
        return "、".join(labels) + "·按新口径应进池（洗牌代码待改）"
    if labels:
        return "按新口径应进池（洗牌代码待改）"
    if live:
        return "现网可进洗牌池"
    return "按新口径应进池（洗牌代码待改）"


def _blocked_reason(items: list[dict]) -> str:
    blocked = set()
    for it in items:
        blocked.update(it["blocked"])
    reasons = []
    if "排除名单" in blocked:
        reasons.append("道具在排除名单")
    if "关掉标记" in blocked:
        reasons.append("道具关掉标记")
    return "；".join(reasons) if reasons else "过闸失败/其它"


def _pool_status_fixed(
    row, lid, items, cfg, type_index, lot_name: str = ""
) -> tuple[str, str]:
    """新口径：固定掉落都进池；友善NPC/铃珠不进。"""
    deny = _hard_deny(lot_name, items)
    if deny:
        return deny
    if not any(_item_ok(it) for it in items):
        return "不进池", _blocked_reason(items)
    live = lot_in_randomize_pool(row, lid, cfg, type_index, cfg["dlc_rules"])
    if live:
        rand = {x[4] for x in lot_randomizable_slots(row, cfg, type_index)}
        if any(
            (it["iid"] in rand or it.get("nt_exception")) and _item_ok(it)
            for it in items
        ):
            return "进池", _pool_reason_ok(items, True)
    if any(it.get("nt_exception") and _item_ok(it) for it in items):
        return "进池", _pool_reason_ok(items, False)
    if live:
        return "进池", "按新口径应进池（洗牌代码待改）"
    return "不进池", _blocked_reason(items)


def _pool_status_msb(row, lid, items, cfg, type_index, lot_name: str = "") -> tuple[str, str]:
    deny = _hard_deny(lot_name, items)
    if deny:
        return deny
    if any(it.get("nt_exception") for it in items) and all(
        _item_ok(it) for it in items
    ):
        live = lot_in_randomize_pool(row, lid, cfg, type_index, cfg["dlc_rules"])
        return "进池", _pool_reason_ok(items, live)
    if not lot_in_randomize_pool(row, lid, cfg, type_index, cfg["dlc_rules"]):
        if any(it.get("nt_exception") and _item_ok(it) for it in items):
            return "进池", _pool_reason_ok(items, False)
        return "不进池", _blocked_reason(items)
    rand = {x[4] for x in lot_randomizable_slots(row, cfg, type_index)}
    if any(
        (it["iid"] in rand or it.get("nt_exception")) and _item_ok(it) for it in items
    ):
        live = not any(it.get("nt_exception") for it in items)
        return "进池", _pool_reason_ok(items, live)
    if any(it.get("nt_exception") and _item_ok(it) for it in items):
        return "进池", _pool_reason_ok(items, False)
    return "不进池", _blocked_reason(items)


def _emit_table(
    lines: list[str],
    title: str,
    tag: str,
    rows: list[dict],
    cols: list[str],
    cell_fn,
    group_key: str | None = None,
    *,
    seq_start: int = 1,
    count_note: str | None = None,
) -> int:
    """Append one audit table. Returns next seq (last+1)."""
    lines.append(f"## {title}")
    lines.append("")
    lines.append(
        f"> 回我格式：**{tag}#序号** + `要洗`/`不要`/`再说`"
        + (
            f"（本册序号从 {seq_start} 起，全表连续）。"
            if seq_start > 1
            else "（本表序号从 1 起）。"
        )
    )
    lines.append("")
    n_pool = sum(1 for r in rows if r.get("pool") == "进池")
    if count_note:
        lines.append(count_note)
    else:
        lines.append(f"**条数**：{len(rows)}　**按新口径进池**：{n_pool}")
    lines.append("")

    if group_key:
        by_g: dict[str, list] = defaultdict(list)
        for r in rows:
            by_g[r.get(group_key) or "（未分组）"].append(r)
        groups = sorted(by_g.keys(), key=lambda a: (-len(by_g[a]), a))
    else:
        by_g = {"": rows}
        groups = [""]

    seq = seq_start - 1
    header = "| 序号 | " + " | ".join(cols) + " | 审计 |"
    sep = "|------|" + "|".join(["------"] * len(cols)) + "|------|"
    for g in groups:
        group = by_g[g]
        if g:
            lines.append(f"### {g}（{len(group)}）")
            lines.append("")
        lines.append(header)
        lines.append(sep)
        for r in group:
            seq += 1
            r["_seq"] = seq
            cells = cell_fn(r)
            lines.append(f"| {seq} | " + " | ".join(cells) + " | |")
        lines.append("")
    return seq + 1


def _split_rows_by_group_mid(
    rows: list[dict], group_key: str
) -> tuple[list[dict], list[dict]]:
    """Split rows into two halves at a group boundary (approx mid by row count)."""
    by_g: dict[str, list] = defaultdict(list)
    for r in rows:
        by_g[r.get(group_key) or "（未分组）"].append(r)
    groups = sorted(by_g.keys(), key=lambda a: (-len(by_g[a]), a))
    total = len(rows)
    target = total // 2
    acc = 0
    cut = 0
    for i, g in enumerate(groups):
        acc += len(by_g[g])
        if acc >= target:
            cut = i + 1
            break
    if cut <= 0:
        cut = max(1, len(groups) // 2)
    if cut >= len(groups):
        cut = len(groups) - 1
    upper_keys = set(groups[:cut])
    upper = [r for r in rows if (r.get(group_key) or "（未分组）") in upper_keys]
    lower = [r for r in rows if (r.get(group_key) or "（未分组）") not in upper_keys]
    return upper, lower


def _part_header(title: str, tag: str) -> list[str]:
    return [
        f"# 物品槽审计 · {title}",
        "",
        "> 分册（打开不卡）。总览与口径见 "
        "[Boss精英固定掉落审计表_当前.md](./Boss精英固定掉落审计表_当前.md)。",
        f"> 回我格式：**{tag}#序号** + `要洗`/`不要`/`再说`",
        "",
    ]


def main() -> None:
    if not ZH_FMG.is_file() or not EN_FMG.is_file():
        raise SystemExit(f"缺少中文名缓存：先跑 DumpItemFmg → {ZH_FMG.name}")

    zh_fmg, phrase = _load_fmg_pair()
    names = _merge_name_maps(zh_fmg)

    cfg = core.load_config(ROOT / "config.json")
    csv_dir = Path(cfg["csv_dir"])
    goods = load_goods_rows(csv_dir)
    cfg["goods_rows"] = goods
    cfg["goods_subcat_index"] = load_goods_subcat_index(csv_dir)
    cfg["weapon_rows"] = load_weapon_rows(csv_dir)
    cfg["protector_rows"] = load_protector_rows(csv_dir)
    cfg["accessory_rows"] = load_accessory_rows(csv_dir)
    cfg["lot_effective_items"] = load_lot_effective_items()
    cfg["dlc_rules"] = core.load_dlc_rules()
    cfg["dlc_ranges"] = cfg["dlc_rules"]["item_ranges"]
    cfg["exclude_item_ids"] = set(cfg.get("exclude_item_ids") or [])
    for iid in goods:
        if is_goods_hard_excluded(iid):
            cfg["exclude_item_ids"].add(iid)
    type_index = load_item_type_index(csv_dir)
    _, map_rows = read_csv(csv_dir / "ItemLotParam_map.csv")
    rows_by = {
        int(r["ID"]): r for r in map_rows if str(r.get("ID", "")).strip().isdigit()
    }
    idx = load_pickup_slot_index(DEFAULT_PICKUP_INDEX_PATH) or {}
    placements = idx.get("placements") or []
    indexed = {
        int(p["lot_id"]) for p in placements if int(p.get("lot_id") or 0)
    }
    ex = cfg["exclude_item_ids"]

    # —— 表A：怪物固定掉落（不在地上扫图）——
    fixed: list[dict] = []
    for lid, row in sorted(rows_by.items()):
        name = (row.get("Name") or row.get("name") or "").strip()
        if name.lower().startswith("tome #"):
            continue
        boss_kw = _lot_name_looks_boss_reward(name)
        area, enemy = _area_enemy(name)
        bracket_area = name.startswith("[") and " - " in name
        if lid in indexed:
            continue
        if not boss_kw and not bracket_area:
            continue
        items = _lot_items(row, type_index, cfg, names, ex, goods)
        if not items:
            continue
        pool, reason = _pool_status_fixed(row, lid, items, cfg, type_index)
        fixed.append(
            {
                "lid": lid,
                "area_zh": _zh_phrase(area, phrase),
                "enemy_zh": _zh_phrase(enemy, phrase) if enemy else "（见 ton 名）",
                "drop_zh": _drop_brief(items),
                "pool": pool,
                "reason": reason,
            }
        )

    # —— 表B/C/D：扫图摆点 ——
    msb: dict[int, list[dict]] = {0: [], 1: [], 2: []}
    for p in placements:
        lid = int(p.get("lot_id") or 0)
        if not lid:
            continue
        ic = int(p.get("in_chest") or 0)
        if ic not in msb:
            continue
        row = rows_by.get(lid)
        if not row:
            continue
        items = _lot_items(row, type_index, cfg, names, ex, goods)
        if not items:
            continue
        pool, reason = _pool_status_msb(row, lid, items, cfg, type_index)
        msb[ic].append(
            {
                "map": str(p.get("map_id") or ""),
                "entity": str(p.get("entity") or p.get("name") or "")[:36],
                "lid": lid,
                "drop_zh": _drop_brief(items),
                "pool": pool,
                "reason": reason,
            }
        )

    n_fixed = len(fixed)
    n_chest = len(msb[1])
    n_glow = len(msb[2])
    n_corpse = len(msb[0])
    pool_fixed = sum(1 for r in fixed if r["pool"] == "进池")
    pool_chest = sum(1 for r in msb[1] if r["pool"] == "进池")
    pool_glow = sum(1 for r in msb[2] if r["pool"] == "进池")
    pool_corpse = sum(1 for r in msb[0] if r["pool"] == "进池")

    corpse_up, corpse_lo = _split_rows_by_group_mid(msb[0], "map")

    # —— 分册 ——
    cols_msb = ["地图", "摆点", "ton", "掉什么", "进池？", "原因"]
    cell_msb = lambda r: [
        r["map"],
        r["entity"],
        str(r["lid"]),
        r["drop_zh"],
        r["pool"],
        r["reason"],
    ]

    part_monster: list[str] = _part_header("怪物固定掉落", "怪物")
    _emit_table(
        part_monster,
        "表A · 怪物固定掉落",
        "怪物",
        fixed,
        ["ton", "敌人/精英", "掉什么", "进池？", "原因"],
        lambda r: [
            str(r["lid"]),
            r["enemy_zh"][:42],
            r["drop_zh"],
            r["pool"],
            r["reason"],
        ],
        group_key="area_zh",
    )
    OUT_PARTS["怪物"].write_text("\n".join(part_monster) + "\n", encoding="utf-8")

    part_chest: list[str] = _part_header("箱子", "箱子")
    _emit_table(
        part_chest,
        "表B · 箱子",
        "箱子",
        msb[1],
        cols_msb,
        cell_msb,
        group_key="map",
    )
    OUT_PARTS["箱子"].write_text("\n".join(part_chest) + "\n", encoding="utf-8")

    part_glow: list[str] = _part_header("地光", "地光")
    _emit_table(
        part_glow,
        "表C · 地光",
        "地光",
        msb[2],
        cols_msb,
        cell_msb,
        group_key="map",
    )
    OUT_PARTS["地光"].write_text("\n".join(part_glow) + "\n", encoding="utf-8")

    note_all = (
        f"**条数**：{n_corpse}（全表）　**按新口径进池**：{pool_corpse}（全表）"
    )
    part_cu: list[str] = _part_header("地图尸体等（上）", "尸体")
    next_seq = _emit_table(
        part_cu,
        "表D · 地图尸体等（非箱非光）· 上",
        "尸体",
        corpse_up,
        cols_msb,
        cell_msb,
        group_key="map",
        count_note=note_all + "\n**本册**：上",
    )
    OUT_PARTS["尸体_上"].write_text("\n".join(part_cu) + "\n", encoding="utf-8")

    part_cl: list[str] = _part_header("地图尸体等（下）", "尸体")
    _emit_table(
        part_cl,
        "表D · 地图尸体等（非箱非光）· 下",
        "尸体",
        corpse_lo,
        cols_msb,
        cell_msb,
        group_key="map",
        seq_start=next_seq,
        count_note=note_all + f"\n**本册**：下（序号从 {next_seq} 起）",
    )
    part_cl.append("> 小怪随机掉落不在本册。审完按「分类#序号」发我即可。")
    part_cl.append("")
    OUT_PARTS["尸体_下"].write_text("\n".join(part_cl) + "\n", encoding="utf-8")

    if OUT_CORPSE_LEGACY.is_file():
        OUT_CORPSE_LEGACY.unlink()

    # —— 索引（短，不卡）——
    index = [
        "# 物品槽审计契约表（临时 · 索引）",
        "",
        "**日期**：2026-09-06（拆分册，减轻编辑器卡顿）",
        "**用途**：你审「要洗/不要」的临时契约底表；审完双方对齐后再改洗牌实现。",
        "**口径（已钉）**：有固定掉落 → **都进池**（不卡 Boss 关键词）；"
        "**失色锻造石**、**普通锻造石**、**铃兰**、**卢恩弯弧**、"
        "**兽肉骨血素材**、**骨灰基础档**、**黄金种子**、"
        "**床帘恩泽**、**坐骑**、**追忆/遗物** → **进池**（关掉标记/排除名单例外）；"
        "**随机掉落不管**；箱子/地光/地图尸体同册审。",
        "**进池列**：按新口径推算；洗牌实现**尚未改**（审完再动码）。",
        "**中文名**：游戏简体中文（法魂改版包）；对不上留英文。",
        "",
        "## 怎么审",
        "",
        "每张表自己从 1 编号。回我时写：**怪物#12 要洗** / **箱子#3 不要**。",
        "",
        "| 分类 | 代号 | 条数 | 按新口径进池 | 打开这个分册 |",
        "|------|------|------|--------------|--------------|",
        f"| 怪物固定掉落 | 怪物 | **{n_fixed}** | **{pool_fixed}** | "
        f"[物品槽审计_怪物固定掉落_当前.md](./物品槽审计_怪物固定掉落_当前.md) |",
        f"| 箱子 | 箱子 | **{n_chest}** | **{pool_chest}** | "
        f"[物品槽审计_箱子_当前.md](./物品槽审计_箱子_当前.md) |",
        f"| 地光 | 地光 | **{n_glow}** | **{pool_glow}** | "
        f"[物品槽审计_地光_当前.md](./物品槽审计_地光_当前.md) |",
        f"| 地图尸体等（上 · #1 起） | 尸体 | **{n_corpse}**（全表） | "
        f"**{pool_corpse}**（全表） | "
        f"[物品槽审计_地图尸体_上_当前.md](./物品槽审计_地图尸体_上_当前.md) |",
        f"| 地图尸体等（下 · #{next_seq} 起） | 尸体 | ↑ | ↑ | "
        f"[物品槽审计_地图尸体_下_当前.md](./物品槽审计_地图尸体_下_当前.md) |",
        "",
        "> 小怪随机掉落不在本册。审完按「分类#序号」发我即可。"
        "尸体上下册**序号连续**，回我时仍写 `尸体#序号`。",
        "",
    ]
    OUT_INDEX.write_text("\n".join(index), encoding="utf-8")
    print(
        "wrote index + parts",
        "fixed",
        n_fixed,
        "chest",
        n_chest,
        "glow",
        n_glow,
        "corpse",
        n_corpse,
        f"(up={len(corpse_up)} lo={len(corpse_lo)} lo_start={next_seq})",
    )


if __name__ == "__main__":
    main()
