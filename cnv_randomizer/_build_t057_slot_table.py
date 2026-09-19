"""T-057: 法魂原创 Boss — 全 MSB（enemy_index）+ NpcParam/CSV 深扫，按源池分类。

用法:
  python _build_t057_slot_table.py

输出:
  reports/法魂原创槽位表.json
  reports/法魂原创槽位表.md
"""
from __future__ import annotations

import csv
import gzip
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import enemy_randomizer_core as core  # noqa: E402
from boss_npc_detect import detect_boss_npc_row, load_npc_rows  # noqa: E402
from paths import OUTPUT_REPORTS  # noqa: E402

INDEX_PATH = SCRIPT_DIR / "cache" / "enemy_index.json"
PREP_GZ = SCRIPT_DIR / "cache" / "enemy_slot_prep.json.gz"
CATEGORIES_PATH = SCRIPT_DIR / "enemy_categories.json"
SPAWN_PATH = SCRIPT_DIR / "output" / "runtime" / "cnv_enemy_spawn_map.txt"
SHOWCASE_MAP = "m11_10_00_00"  # 训练场/展示图，非剧情原位

POOL_ZH = {
    "trash": "1 路边小怪",
    "minor_boss": "2 野外洞穴Boss",
    "evergaol": "3 封印监牢",
    "field_boss": "4 次要Boss",
    "night": "5 红灵",
    "major_boss": "6 主线大Boss",
    "cnv_special": "7 法魂Boss",
}

# Changelog Hostile NPC → 地图前缀（CNV enemy_index map_id）
HOSTILE_NPC_HINTS: list[dict[str, Any]] = [
    {"en": "Nox Oracle Sadia", "zh": "诺克斯神谕者·萨迪亚", "loc": "瑟利亚魔法镇", "maps": ["m30_06", "m30_09", "m30_10"]},
    {"en": "Volcanist Dist", "zh": "火山官邸火山使", "loc": "火山官邸", "maps": ["m60_15"]},
    {"en": "Snuppet, Servant of Rot", "zh": "腐败仆从", "loc": "腐败湖", "maps": ["m60_52"]},
    {"en": "Stormcaller Curtis", "zh": "唤雷者·柯蒂斯", "loc": "史东薇尔城", "maps": ["m60_42"]},
    {"en": "Necromancer Domo", "zh": "死灵法师·多莫", "loc": "史东薇尔城", "maps": ["m60_42"]},
    {"en": "Glint Sorcerer Bree", "zh": "辉石法师·布里", "loc": "雷亚卢卡利亚学院", "maps": ["m30_10", "m30_11"]},
    {"en": "Fundamentalist Gino", "zh": "基要主义者·吉诺", "loc": "摩恩城", "maps": ["m60_43"]},
    {"en": "Darkmoon Knight Oroboro", "zh": "暗月骑士", "loc": "盖尔坑道/上升", "maps": ["m30_12"]},
    {"en": "Dragon Cultist Seki", "zh": "龙信徒·关", "loc": "王城罗德尔", "maps": ["m60_44"]},
    {"en": "Frost Witch Dino", "zh": "冰霜女巫·迪诺", "loc": "卡利亚城寨", "maps": ["m31_"]},
    {"en": "Ainrun the Mystic", "zh": "神秘主义者·艾恩伦", "loc": "希芙拉河", "maps": ["m12_"]},
    {"en": "Aberrant Heretic Loreena", "zh": "异端女巫", "loc": "日荫城", "maps": ["m60_47"]},
    {"en": "Dragon Mage Caleb", "zh": "龙法师·凯勒布", "loc": "仪典镇", "maps": ["m60_52"]},
    {"en": "Death Knight Lenny", "zh": "死亡骑士", "loc": "深根底层", "maps": ["m60_54"]},
    {"en": "Starcaller Dumpy", "zh": "唤星者", "loc": "坑道/摩恩周边", "maps": ["m60_43"]},
    {"en": "Blood Initiate Parky", "zh": "鲜血教徒", "loc": "蒙格温王朝", "maps": ["m60_48"]},
    {"en": "Godskin Celebrant Prod", "zh": "神皮庆典者", "loc": "盖利德神授塔", "maps": ["m34_"]},
    {"en": "Bee the Relentless", "zh": "不屈者·比", "loc": "森林之民废墟", "maps": ["m60_45", "m60_46"]},
    {"en": "Squilla of the Golden Order", "zh": "黄金律·斯奎拉", "loc": "圣树", "maps": ["m60_52"]},
]

EN_NAME_PATTERNS: list[tuple[str, list[str]]] = [
    ("Erdtree Guardian", ["erdtree guardian"]),
    ("Grafted Scion", ["grafted scion"]),
    ("Banished Knight Oleg", ["banished knight oleg"]),
]

# NpcParam.Name → 绑定 en（CSV 有 Name 后补全）
CSV_NAME_RULES: list[tuple[str, str, list[str]]] = [
    ("Dyru, Scavenger King", "dyru", [r"dyru", r"scavenger king"]),
    ("Shabiri's Chosen", "shabiri", [r"shabiri", r"shabibi"]),
    ("Godskin Matriarch", "matriarch", [r"godskin matriarch"]),
    ("Devonia", "devonia", [r"crucible knight devonia"]),
    ("Onze", "onze", [r"swordmaster onze", r"\bonze\b"]),
    ("Rhys, Carian Paragon", "rhys", [r"rhys", r"carian knight \[boss\]"]),
    ("Einar, Ice Guardian", "einar", [r"einar", r"ice guardian"]),
    ("Dakk, Starcaller Lord", "dakk", [r"dakk", r"starcaller lord"]),
    ("Goras, Scourge of Dreams", "goras", [r"goras", r"scourge of dreams"]),
    ("Seera, Blade of the Ancients", "seera", [r"seera", r"blade of the ancients"]),
    ("Sigur, Night's Captain", "sigur", [r"sigur", r"night's captain", r"nights captain"]),
    ("Skarde, Crucible's Betrayer", "skarde", [r"skarde", r"crucible's betrayer"]),
    ("Konrad, Pureblood Knight", "konrad", [r"konrad", r"pureblood knight"]),
    ("Daergarf", "daergarf", [r"daergarf", r"daergraf"]),
    ("Spiritshaper Caimar", "caimar", [r"spiritshaper caimar", r"caimar \[boss\]"]),
    ("Scion of the Sealed God", "vessel_rot", [r"scion of the sealed god"]),
    ("Bloodflame Dragon Sanguivaros", "sanguivaros", [r"sanguivaros", r"bloodflame dragon"]),
    ("Black Knight (CNV)", "black_knight", [r"black knight garrew", r"black knight \(boss\)"]),
]


def _load_prep() -> dict[tuple[str, str], dict[str, Any]]:
    if not PREP_GZ.is_file():
        return {}
    with gzip.open(PREP_GZ, "rt", encoding="utf-8") as fh:
        prep = json.load(fh)
    return {(str(r["m"]), str(r["n"])): r for r in prep.get("slots", [])}


def _load_spawn_keys() -> set[tuple[str, str]]:
    if not SPAWN_PATH.is_file():
        return set()
    out: set[tuple[str, str]] = set()
    for line in SPAWN_PATH.read_text(encoding="utf-8").splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and not parts[0].startswith("#"):
            out.add((parts[0], parts[1]))
    return out


def _is_boss_slot(
    slot: dict[str, Any],
    npc_rows: dict[int, dict[str, str]],
    categories_cfg: dict[str, Any] | None = None,
) -> bool:
    name = str(slot.get("name", ""))
    if re.search(r"_9000\b", name) or name in ("BearAmbush",):
        return True
    model = str(slot.get("model", ""))
    cnv_prefixes = (categories_cfg or {}).get("cnv_special_boss_model_prefixes") or []
    if any(model.startswith(p) for p in cnv_prefixes) and re.search(r"_90\d+", name):
        return True
    try:
        npc_id = int(slot.get("npc", 0) or 0)
    except (TypeError, ValueError):
        return False
    row = npc_rows.get(npc_id, {})
    ok, _ = detect_boss_npc_row(row)
    return ok


def _npc_name_hits(npc_rows: dict[int, dict[str, str]]) -> dict[str, set[int]]:
    hits: dict[str, set[int]] = defaultdict(set)
    for en, patterns in EN_NAME_PATTERNS:
        for nid, row in npc_rows.items():
            name = str(row.get("Name") or "").lower()
            if any(p in name for p in patterns):
                hits[en].add(nid)
    return hits


def _csv_name_npc_index(npc_rows: dict[int, dict[str, str]]) -> dict[str, list[dict[str, Any]]]:
    """NpcParam.Name 正则 → 绑定 id + npc 列表。"""
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for en, bid, patterns in CSV_NAME_RULES:
        rx = re.compile("|".join(patterns), re.I)
        for nid, row in npc_rows.items():
            name = str(row.get("Name") or "").strip()
            if not name or not rx.search(name):
                continue
            out[en].append({"npc": nid, "name": name, "binding_id": bid})
    for en in out:
        out[en].sort(key=lambda r: (r["name"], r["npc"]))
    return dict(out)


def _scan_red_spirits_csv(
    npc_rows: dict[int, dict[str, str]],
    slots: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Changelog 红灵：NpcParam `New NPC #` 精确 npc → MSB。"""
    rx = re.compile(r"New NPC #\d+:\s*(.+)", re.I)
    out: list[dict[str, Any]] = []
    for nid, row in sorted(npc_rows.items()):
        name = str(row.get("Name") or "").strip()
        m = rx.search(name)
        if not m:
            continue
        label = m.group(1).strip()
        msb = [
            s
            for s in slots
            if int(s.get("npc", 0) or 0) == nid
        ]
        out.append(
            {
                "npc": nid,
                "name": name,
                "label": label,
                "msb_count": len(msb),
                "slots": [
                    {
                        "map_id": s["map_id"],
                        "entity": s["name"],
                        "src_cat": s.get("src_cat"),
                    }
                    for s in msb
                ],
            }
        )
    return out


def _map_matches(map_id: str, prefixes: list[str]) -> bool:
    return any(map_id.startswith(p) for p in prefixes)


def _pick_primary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    canon = [r for r in rows if r["canonical"]]
    pool = canon or rows
    story = [r for r in pool if r["map_id"] != SHOWCASE_MAP]
    pool = story or pool
    nine = [r for r in pool if "_9000" in r["entity"] or r["entity"] == "BearAmbush"]
    nine = nine or [r for r in pool if re.search(r"_90\d+", r["entity"])]
    return (nine or pool)[0]


def _csv_npc_audit(
    bindings: list[dict[str, Any]],
    npc_rows: dict[int, dict[str, str]],
    slots: list[dict[str, Any]],
    categories_cfg: dict[str, Any],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for b in bindings:
        npc = int(b["npc"])
        think = int(b.get("think") or 0)
        model = str(b["model"])
        row = npc_rows.get(npc, {})
        msb_exact = [s for s in slots if int(s.get("npc", 0) or 0) == npc]
        msb_model = [s for s in slots if str(s.get("model", "")) == model]
        msb_think = [s for s in slots if int(s.get("think", 0) or 0) == think] if think else []
        out.append(
            {
                "id": b["id"],
                "en": b["en"],
                "zh": b.get("zh", ""),
                "npc": npc,
                "think": think,
                "model": model,
                "npcparam_name": str(row.get("Name") or ""),
                "npcparam_exists": bool(row),
                "msb_exact_npc": len(msb_exact),
                "msb_model_any": len(msb_model),
                "msb_think": len(msb_think),
                "msb_boss_model": sum(
                    1 for s in msb_model if _is_boss_slot(s, npc_rows, categories_cfg)
                ),
            }
        )
    return out


def _scan_red_spirit_hints(slots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    night_slots = [
        s
        for s in slots
        if s.get("src_cat") == "night" or str(s.get("model", "")) == "c0000"
    ]
    out: list[dict[str, Any]] = []
    for hint in HOSTILE_NPC_HINTS:
        hits = [
            s
            for s in night_slots
            if _map_matches(str(s["map_id"]), hint["maps"])
            and re.search(r"_90\d+", str(s.get("name", "")))
        ]
        out.append(
            {
                **hint,
                "night_slot_count": len(hits),
                "sample": [
                    {
                        "map_id": s["map_id"],
                        "entity": s["name"],
                        "npc": s.get("npc"),
                        "src_cat": s.get("src_cat"),
                    }
                    for s in hits[:3]
                ],
            }
        )
    return out


def main() -> None:
    categories_cfg = json.loads(CATEGORIES_PATH.read_text(encoding="utf-8"))
    index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    slots = index.get("slots", [])
    npc_csv_dir = core.GAME_DIR / "csv"
    npc_rows = load_npc_rows(npc_csv_dir)
    prep_by_key = _load_prep()
    spawn_keys = _load_spawn_keys()
    name_hits = _npc_name_hits(npc_rows)
    binding_list = categories_cfg.get("cnv_named_boss_bindings") or []
    bindings = {str(b["en"]): b for b in binding_list}

    slot_rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def attach(en: str, slot: dict[str, Any], *, via: str) -> None:
        key = (str(slot["map_id"]), str(slot["name"]))
        if key in seen:
            return
        seen.add(key)
        binding = bindings.get(en, {})
        try:
            npc_id = int(slot.get("npc", 0) or 0)
        except (TypeError, ValueError):
            npc_id = 0
        pol = core.describe_slot_policy(
            slot,
            categories_cfg,
            npc_csv_dir=npc_csv_dir,
            prep_row=prep_by_key.get(key),
            spawn_keys=spawn_keys,
        )
        bind_npc = int(binding.get("npc") or 0)
        canonical = bool(bind_npc and npc_id == bind_npc)
        slot_rows.append(
            {
                "en": en,
                "zh": binding.get("zh") or "",
                "via": via,
                "canonical": canonical,
                "showcase": key[0] == SHOWCASE_MAP,
                "map_id": key[0],
                "entity": key[1],
                "model": str(slot.get("model", "")),
                "npc": npc_id,
                "think": int(slot.get("think", 0) or 0),
                "npc_name": str((npc_rows.get(npc_id) or {}).get("Name") or ""),
                "src_cat": pol["src_cat"],
                "src_pool": pol["src_pool"],
                "src_pool_zh": POOL_ZH.get(pol["src_cat"], pol["src_cat"]),
                "policy": pol["policy"],
                "binding_confidence": binding.get("confidence") or "",
                "t057_registered": npc_id
                in (categories_cfg.get("cnv_original_boss_slot_npc_ids") or []),
            }
        )

    # A) model + Boss 槽
    for en, b in bindings.items():
        model = str(b["model"])
        for slot in slots:
            if str(slot.get("model")) != model:
                continue
            if not _is_boss_slot(slot, npc_rows, categories_cfg):
                continue
            attach(en, slot, via="binding_model")

    # B) 精确 npc
    for en, b in bindings.items():
        bnid = int(b["npc"])
        for slot in slots:
            if int(slot.get("npc") or 0) != bnid:
                continue
            attach(en, slot, via="binding_npc")

    # C) think 命中（深扫）
    for en, b in bindings.items():
        think = int(b.get("think") or 0)
        if not think:
            continue
        for slot in slots:
            if int(slot.get("think") or 0) != think:
                continue
            if not _is_boss_slot(slot, npc_rows, categories_cfg):
                continue
            attach(en, slot, via="binding_think")

    # D) NpcParam 英文名
    for en, nids in name_hits.items():
        for slot in slots:
            if int(slot.get("npc") or 0) not in nids:
                continue
            if not _is_boss_slot(slot, npc_rows, categories_cfg):
                continue
            attach(en, slot, via="npc_name")

    slot_rows.sort(key=lambda r: (r["en"], not r["canonical"], r["showcase"], r["map_id"], r["entity"]))

    by_en: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in slot_rows:
        by_en[r["en"]].append(r)

    primary = [_pick_primary(rows) for en, rows in sorted(by_en.items())]
    unmatched_bindings = [en for en in bindings if en not in by_en]
    csv_audit = _csv_npc_audit(binding_list, npc_rows, slots, categories_cfg)
    synthetic_only = [
        a for a in csv_audit
        if a["msb_exact_npc"] == 0 and a["msb_model_any"] == 0 and a["msb_think"] == 0
    ]
    red_spirits = _scan_red_spirit_hints(slots)
    index_maps = sorted({s["map_id"] for s in slots})
    has_m61 = any(m.startswith("m61_") for m in index_maps)

    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    payload = {
        "generated_at": generated,
        "schema": "cnv_original_slot_table_v3",
        "index_maps_scanned": index.get("maps_scanned"),
        "index_maps_skipped": index.get("maps_skipped"),
        "index_unique_maps": len(index_maps),
        "index_has_m61": has_m61,
        "primary_count": len(primary),
        "slot_count": len(slot_rows),
        "boss_count": len(by_en),
        "synthetic_only_count": len(synthetic_only),
        "red_spirit_hint_count": len(red_spirits),
        "primary": primary,
        "slots": slot_rows,
        "by_en": {k: v for k, v in sorted(by_en.items())},
        "unmatched_bindings": unmatched_bindings,
        "csv_audit": csv_audit,
        "synthetic_only": synthetic_only,
        "red_spirit_hints": red_spirits,
        "policy_notes": {
            "original_boss_slot": "cnv_original_boss_slot_npc_ids — 不参与随机，可 7 池捐皮",
            "red_spirit": "5 池 night — 参与随机 + 可捐皮；不进原位表（用户 2026-08-01）",
        },
    }

    OUTPUT_REPORTS.mkdir(parents=True, exist_ok=True)
    json_path = OUTPUT_REPORTS / "法魂原创槽位表.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    md: list[str] = [
        "# 法魂原创槽位表（T-057 · MSB+CSV 深扫）",
        "",
        f"**生成**：{generated}  ",
        f"**索引**：`enemy_index` {index.get('maps_scanned')} 图扫描 / {len(index_maps)} 图有槽 / m61={'有' if has_m61 else '**无**'}  ",
        "**方法**：绑定 model/npc/think + NpcParam + `describe_slot_policy`",
        "",
        "**口径**：原位 Boss → `cnv_original_boss_slot_npc_ids`（skip）；**红灵 5 池 → 参与随机 + 可捐皮**",
        "",
        f"**主表**：{len(primary)} 名 · **展开**：{len(slot_rows)} 槽 · **合成-only**：{len(synthetic_only)} 名",
        "",
        "## 主表（剧情原位 · 契约同步）",
        "",
        "| 英文名 | 中文 | 地图 | 实体 | model | npc | 源池 | policy |",
        "|--------|------|------|------|-------|-----|------|--------|",
    ]
    for r in primary:
        md.append(
            f"| {r['en']} | {r['zh'] or '—'} | `{r['map_id']}` | `{r['entity']}` | `{r['model']}` | {r['npc']} | {r['src_pool_zh']} | {r['policy']} |"
        )

    md.extend(["", "## CSV+MSB 审计（19 绑定）", ""])
    md.extend(
        _md_table(
            csv_audit,
            [
                ("en", "英文名"),
                ("npc", "绑定npc"),
                ("npcparam_exists", "NpcParam"),
                ("msb_exact_npc", "MSB同npc"),
                ("msb_model_any", "MSB同model"),
                ("msb_think", "MSB同think"),
            ],
        )
    )

    if synthetic_only:
        md.extend(["", "## 合成捐皮-only（NpcParam 有 · MSB 全图无槽）", ""])
        for a in synthetic_only:
            md.append(
                f"- **{a['en']}** — npc=`{a['npc']}` model=`{a['model']}` "
                f"NpcParam名=`{a['npcparam_name'] or '（空）'}`"
            )
        if not has_m61:
            md.append("")
            md.append("> ⚠️ `enemy_index` **无 m61_ 图**（Noxumbra/戴尔加夫等 DLC 区未入库）；需 `index-export` 且游戏目录有 m61 MSB。")

    md.extend(["", "## 红灵 Hostile NPC（5 池 · 参与随机+捐皮）", ""])
    md.append("Changelog 19 人 · NpcParam 无专名 · 按**地图前缀**对 `c0000`+`night` 槽计数（待 emevd 逐人绑定）")
    md.append("")
    md.extend(
        _md_table(
            red_spirits,
            [
                ("en", "英文名"),
                ("loc", "Changelog位置"),
                ("night_slot_count", "hint区红灵槽数"),
            ],
        )
    )

    if slot_rows:
        md.extend(["", "## 全部命中槽（含训练场/同皮他图）", ""])
        md.extend(
            _md_table(
                slot_rows,
                [
                    ("en", "英文名"),
                    ("map_id", "地图"),
                    ("entity", "实体"),
                    ("npc", "npc"),
                    ("src_pool_zh", "源池"),
                    ("showcase", "训练场"),
                    ("via", "via"),
                ],
            )
        )

    if unmatched_bindings:
        md.extend(["", "## 绑定表有 · MSB 零命中", ""])
        for en in unmatched_bindings:
            b = bindings[en]
            md.append(f"- **{en}** — npc={b.get('npc')} model={b.get('model')}")

    md_path = OUTPUT_REPORTS / "法魂原创槽位表.md"
    md_path.write_text("\n".join(md) + "\n", encoding="utf-8")
    print(
        f"primary={len(primary)} slots={len(slot_rows)} synthetic_only={len(synthetic_only)} "
        f"m61={'yes' if has_m61 else 'NO'}"
    )
    print(f"Wrote {json_path}")
    print(f"Wrote {md_path}")


def _md_table(rows: list[dict[str, Any]], columns: list[tuple[str, str]]) -> list[str]:
    header = "| " + " | ".join(h for _, h in columns) + " |"
    sep = "| " + " | ".join("---" for _ in columns) + " |"
    lines = [header, sep]
    for row in rows:
        cells = [str(row.get(k, "—")).replace("|", "\\|") for k, _ in columns]
        lines.append("| " + " | ".join(cells) + " |")
    return lines


if __name__ == "__main__":
    main()
