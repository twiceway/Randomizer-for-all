# -*- coding: utf-8 -*-
"""Build getSoul=0 → GameAreaParam.bonusSoul reverse table (strict)."""
from __future__ import annotations

import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

CSV = Path(r"V:\games\Elden Ring\Game\csv")
IDX = Path(r"V:\1_mel\Ringrandom\cnv_randomizer\cache\enemy_index.json")
CAT = Path(r"V:\1_mel\Ringrandom\cnv_randomizer\enemy_categories.json")
OUT = Path(r"V:\1_mel\Ringrandom\cnv_randomizer\enemy_gamearea_souls.json")

MAP_RE = re.compile(r"^m(\d+)_(\d+)_(\d+)_(\d+)$", re.I)
SUFFIXES = (800, 850, 830, 801, 390, 340, 720, 860)

# 合成/无名 GameArea / 同图多Boss：手工钉死 npc → GameAreaParam.ID
MANUAL_NPC: dict[int, int] = {
    # Stormveil：同图两档，必须按怪分
    21300014: 10000850,  # 玛尔基特 → 12000
    21300050: 10000850,
    47500014: 10000800,  # 葛瑞克 → 20000
    # Leyndell
    21300534: 11000800,  # 蒙葛特 → 120000
    47600050: 11000800,  # 法魂蒙格特皮
    57700084: 11000850,  # 荷莱·露/葛孚雷 → 80000
    47200050: 11000850,
    # Academy
    20300024: 14000800,  # 蕾娜拉 → 40000
    20310024: 14000800,
    # 战场 / 火山 / 圣树 / 法姆 / 蒙格温
    47300040: 1052380800,  # 拉塔恩 → 70000
    47100038: 16000800,  # 拉卡德 → 130000
    46700065: 12050800,  # 蒙格（合成占用祖灵行）→ 420000
    52700100: 1052520800,  # 火焰巨人 → 180000
    57000083: 15000800,  # 玛莲妮亚合成 → 480000
    21200000: 15000800,
    51100080: 13000800,  # 玛利喀斯 → 220000
    45200010: 13000830,  # 普拉顿桑克斯 → 280000
    22000000: 19000800,  # 艾尔登之兽 → 500000
    22000078: 19000800,
    21900078: 19000800,
    48000010: 19000800,  # 拉达冈同台
    # DLC 主线（GameArea 常无名，按 bonus 与 wiki 对齐）
    50300094: 2044450800,  # 萝蜜娜 → 380000
    50300000: 2044450800,
    50300001: 2044450800,
    51200085: 2054390800,  # 贝勒 → 490000
    51300099: 21010800,  # 梅瑟莫 → 400000
    50500086: 28000800,  # 米德拉 → 410000
    50200087: 22000800,  # 腐朽 → 220000
    52000097: 25000800,  # 指头之母 → 420000
    52200089: 20010800,  # 约定之王 → 500000
    53000082: 2048440800,  # 蕾菈娜量级 → 240000
    52300096: 2047390800,  # 幽影树人量级 → 230000
}

# model 兜底（同模多 npc 时用；精确 npc 仍优先 MANUAL_NPC）
MANUAL_MODEL: dict[str, int] = {
    "c2130": 10000850,
    "c4750": 10000800,
    "c4760": 11000800,
    "c4730": 1052380800,
    "c4710": 16000800,
    "c4670": 12050800,
    "c5270": 1052520800,
    "c5700": 15000800,
    "c2120": 15000800,
    "c5110": 13000800,
    "c4520": 13000830,
    "c2200": 19000800,
    "c4800": 19000800,
    "c2030": 14000800,
    "c5030": 2044450800,
    "c5120": 2054390800,
    "c5130": 21010800,
    "c5050": 28000800,
    "c5020": 22000800,
    "c5200": 25000800,
    "c5220": 20010800,
    "c5300": 2048440800,
    "c5230": 2047390800,
    "c5770": 11000850,
    "c4720": 11000850,
}


def load_game_areas() -> dict[int, dict]:
    out: dict[int, dict] = {}
    with (CSV / "GameAreaParam.csv").open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            i = int(row["ID"])
            out[i] = {
                "bonus": int(row.get("bonusSoul_single") or 0),
                "name": (row.get("Name") or "").strip(),
            }
    return out


def load_npcs() -> dict[int, dict]:
    out: dict[int, dict] = {}
    with (CSV / "NpcParam.csv").open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            i = int(row["ID"])
            out[i] = {
                "soul": int(row.get("getSoul") or 0),
                "boss": int(row.get("isSoulGetByBoss") or 0),
                "name": (row.get("Name") or "").strip(),
            }
    return out


def map_gamearea_candidates(map_id: str) -> list[int]:
    m = MAP_RE.match(str(map_id).replace(".msb.dcx", "").replace(".msb", ""))
    if not m:
        return []
    a, b, c, _d = (int(x) for x in m.groups())
    ids: list[int] = []
    if a == 60:
        for suf in SUFFIXES:
            ids.append(int(f"10{b:02d}{c:02d}{suf:04d}"))
    if a == 20:
        for suf in SUFFIXES:
            ids.append(int(f"20{b:02d}{c:02d}{suf:04d}"))
    for suf in SUFFIXES:
        ids.append(a * 1_000_000 + b * 10_000 + suf)
    return ids


def areas_on_map(map_id: str, areas: dict[int, dict]) -> list[tuple[int, int, str]]:
    found: list[tuple[int, int, str]] = []
    seen: set[int] = set()
    mid = str(map_id).replace(".msb.dcx", "").replace(".msb", "")
    for gid in map_gamearea_candidates(mid):
        if gid in seen:
            continue
        info = areas.get(gid)
        if not info or info["bonus"] <= 0:
            continue
        seen.add(gid)
        found.append((gid, info["bonus"], info["name"]))
    return found


def boss_title(area_name: str) -> str:
    """Take trailing boss title from '[Place] Boss Name'."""
    if not area_name:
        return ""
    if "]" in area_name:
        return area_name.split("]", 1)[-1].strip(" -")
    return area_name.strip()


def significant_tokens(text: str) -> set[str]:
    low = text.lower()
    toks = set(re.findall(r"[a-z]{5,}", low))
    # drop generic place words
    stop = {
        "castle",
        "palace",
        "church",
        "cave",
        "tunnel",
        "catacombs",
        "grave",
        "river",
        "lake",
        "capital",
        "plateau",
        "mountains",
        "battlefield",
        "entrance",
        "village",
        "ruins",
        "swamp",
        "tower",
        "manor",
        "academy",
        "haligtree",
        "leyndell",
        "stormveil",
        "limgrave",
        "liurnia",
        "caelid",
        "altus",
        "soldier",
        "knight",
        "warrior",
        "hunter",
        "spirit",
        "watchdog",
        "burial",
        "erdtree",
        "avatar",
        "naturalborn",
    }
    return {t for t in toks if t not in stop}


def strong_name_match(npc_name: str, area_name: str) -> bool:
    if not npc_name or not area_name:
        return False
    title = boss_title(area_name)
    if not title:
        return False
    nlow = npc_name.lower()
    tlow = title.lower()
    # full title substring either way (min length)
    if len(title) >= 6 and (tlow in nlow or nlow in tlow):
        return True
    nt = significant_tokens(npc_name)
    at = significant_tokens(title)
    if not nt or not at:
        return False
    inter = nt & at
    # require a distinctive token (>=6) or >=2 tokens
    if any(len(t) >= 6 for t in inter):
        return True
    return len(inter) >= 2


def put(
    by_npc: dict[str, dict],
    npc: int,
    bonus: int,
    gid: int,
    source: str,
    npcs: dict[int, dict],
    models: set[str],
) -> None:
    if bonus <= 0:
        return
    key = str(npc)
    prev = by_npc.get(key)
    # manual / stronger source wins; else higher bonus only if same confidence tier
    if prev and prev.get("source", "").startswith("manual") and not source.startswith("manual"):
        return
    if prev and not prev.get("source", "").startswith("manual"):
        if prev["bonus_soul"] >= bonus and not source.startswith("manual"):
            # keep existing unless new is name match and old is weak map_single
            if not (source.startswith("name") and prev.get("source", "").startswith("map_single")):
                return
    info = npcs.get(npc) or {"name": "", "boss": 0}
    by_npc[key] = {
        "bonus_soul": int(bonus),
        "game_area_id": int(gid),
        "source": source,
        "npc_name": info.get("name") or "",
        "is_soul_get_by_boss": bool(info.get("boss")),
        "models": sorted(models),
    }


def main() -> None:
    areas = load_game_areas()
    npcs = load_npcs()
    idx = json.loads(IDX.read_text(encoding="utf-8"))
    cats = json.loads(CAT.read_text(encoding="utf-8"))
    zh = cats.get("model_prefix_display_zh") or {}

    npc_maps: dict[int, set[str]] = defaultdict(set)
    npc_models: dict[int, set[str]] = defaultdict(set)
    for t in idx.get("templates") or []:
        try:
            npc = int(t.get("npc") or 0)
        except (TypeError, ValueError):
            continue
        if not npc:
            continue
        dm = str(t.get("donor_map") or "")
        if dm and not dm.startswith("synthetic"):
            npc_maps[npc].add(dm)
        model = str(t.get("model") or "")
        if model:
            npc_models[npc].add(model)

    for t in cats.get("synthetic_boss_templates") or []:
        if not isinstance(t, dict):
            continue
        try:
            npc = int(t.get("npc") or 0)
        except (TypeError, ValueError):
            continue
        if not npc:
            continue
        model = str(t.get("model") or "")
        if model:
            npc_models[npc].add(model)

    by_npc: dict[str, dict] = {}

    # 1) manual npc
    for npc, gid in MANUAL_NPC.items():
        info = areas.get(gid)
        if not info:
            continue
        put(
            by_npc,
            npc,
            info["bonus"],
            gid,
            f"manual:npc->{gid}",
            npcs,
            npc_models.get(npc, set()),
        )

    # 2) strong name match: GameArea titled bosses → soul=0 npcs
    named_areas = [(gid, info) for gid, info in areas.items() if info["bonus"] > 0 and info["name"]]
    soul0 = [i for i, n in npcs.items() if n["soul"] <= 0]
    for gid, info in named_areas:
        title = boss_title(info["name"])
        if len(significant_tokens(title)) == 0 and len(title) < 6:
            continue
        for npc in soul0:
            ninfo = npcs[npc]
            if not strong_name_match(ninfo["name"], info["name"]):
                continue
            # prefer boss-flag or already in templates
            if ninfo["boss"] != 1 and npc not in npc_models and npc not in npc_maps:
                continue
            put(
                by_npc,
                npc,
                info["bonus"],
                gid,
                f"name:{title[:40]}->{gid}",
                npcs,
                npc_models.get(npc, set()),
            )

    # 3) map with exactly one GameArea bonus → boss-flag soul=0 templates on that map
    map_to_npcs: dict[str, set[int]] = defaultdict(set)
    for npc, maps in npc_maps.items():
        for mid in maps:
            map_to_npcs[mid].add(npc)

    for mid, npc_set in map_to_npcs.items():
        found = areas_on_map(mid, areas)
        if len(found) != 1:
            continue
        gid, bonus, _name = found[0]
        for npc in npc_set:
            ninfo = npcs.get(npc)
            if not ninfo or ninfo["soul"] > 0:
                continue
            if ninfo["boss"] != 1 and str(npc) not in by_npc:
                # only auto-fill boss-flag on single-area maps
                continue
            if ninfo["boss"] != 1:
                continue
            put(
                by_npc,
                npc,
                bonus,
                gid,
                f"map_single:{mid}->{gid}",
                npcs,
                npc_models.get(npc, set()),
            )

    # 4) manual model fill for npcs still missing but with that model
    for model, gid in MANUAL_MODEL.items():
        info = areas.get(gid)
        if not info:
            continue
        for npc, models in npc_models.items():
            if model not in models:
                continue
            ninfo = npcs.get(npc)
            if not ninfo or ninfo["soul"] > 0:
                continue
            if str(npc) in by_npc:
                continue
            put(
                by_npc,
                npc,
                info["bonus"],
                gid,
                f"manual:model:{model}->{gid}",
                npcs,
                models,
            )

    # by_model from by_npc + manual model
    by_model: dict[str, dict] = {}
    for model, gid in MANUAL_MODEL.items():
        info = areas.get(gid)
        if info:
            by_model[model] = {
                "bonus_soul": info["bonus"],
                "game_area_id": gid,
                "from_npc": None,
                "zh": zh.get(model, ""),
                "source": "manual",
            }
    model_best: dict[str, tuple[int, int]] = {}
    for npc_s, row in by_npc.items():
        for model in row.get("models") or []:
            b = row["bonus_soul"]
            cur = model_best.get(model)
            if cur is None or b > cur[0]:
                model_best[model] = (b, int(npc_s))
    for model, (b, npc) in model_best.items():
        prev = by_model.get(model)
        if prev and prev.get("source") == "manual":
            continue
        by_model[model] = {
            "bonus_soul": b,
            "game_area_id": by_npc[str(npc)]["game_area_id"],
            "from_npc": npc,
            "zh": zh.get(model, ""),
            "source": "derived",
        }

    # also dump full GameArea reference for audit
    game_areas_ref = {
        str(gid): {"bonus_soul": info["bonus"], "name": info["name"]}
        for gid, info in sorted(areas.items(), key=lambda x: -x[1]["bonus"])
        if info["bonus"] > 0
    }

    zero_template = sorted(
        {
            int(t.get("npc") or 0)
            for t in (idx.get("templates") or [])
            if int(t.get("npc") or 0) and npcs.get(int(t.get("npc") or 0), {}).get("soul", 1) <= 0
        }
    )
    covered = sum(1 for n in zero_template if str(n) in by_npc)
    boss_zero = [i for i, n in npcs.items() if n["boss"] == 1 and n["soul"] <= 0]
    boss_covered = sum(1 for n in boss_zero if str(n) in by_npc)

    payload = {
        "definition": (
            "getSoul=0 时反查 GameAreaParam.bonusSoul_single。"
            "优先级：manual钉死 → GameArea/Npc 强名匹配 → 单GameArea地图上的 boss 旗 npc → model 手工/派生。"
            "lookup 顺序：getSoul>0 用原值；否则 by_npc → by_model → by_category。"
        ),
        "generated_from": {
            "NpcParam": str(CSV / "NpcParam.csv"),
            "GameAreaParam": str(CSV / "GameAreaParam.csv"),
            "enemy_index": str(IDX),
        },
        "stats": {
            "by_npc_count": len(by_npc),
            "by_model_count": len(by_model),
            "game_area_with_bonus": len(game_areas_ref),
            "zero_template_npcs": len(zero_template),
            "zero_template_covered": covered,
            "boss_flag_soul0": len(boss_zero),
            "boss_flag_soul0_covered": boss_covered,
        },
        "by_npc": dict(sorted(by_npc.items(), key=lambda x: -x[1]["bonus_soul"])),
        "by_model": dict(sorted(by_model.items(), key=lambda x: -x[1]["bonus_soul"])),
        "game_areas": game_areas_ref,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("wrote", OUT)
    print("stats", payload["stats"])
    for nid in (50300094, 21300014, 21300534, 20300024, 21200000, 22000000, 47600050, 46700065):
        print("check", nid, by_npc.get(str(nid)))
    print("model c5030", by_model.get("c5030"))


if __name__ == "__main__":
    main()
