"""Rescan export: m61 slots with Chinese names + combat HP (all spEffect maxHpRate)."""
from __future__ import annotations

import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent
import sys
sys.path.insert(0, str(SCRIPT))
from paths import OUTPUT_REPORTS  # noqa: E402

GAME = Path(r"V:/games/Elden Ring/Game")
JSONL = OUTPUT_REPORTS / "_m61_slots.jsonl"
OUT = OUTPUT_REPORTS / "m61地图怪物详表.md"

# Soulsmodding / 官译常用对照（无项目表时补中文；英文仅作备注）
SUPPLEMENT_ZH: dict[str, str] = {
    "c0100": "骷髅",
    "c1000": "人形占位（玩家类）",
    "c5240": "平民幽影",
    "c5401": "鹰",
    "c5410": "鹿",
    "c5450": "公羊",
    "c5490": "春兔",
    "c5440": "蝎子（小）",
    "c5430": "蝎子",
    "c5460": "山羊",
    "c5470": "小角兽",
    "c5480": "野猪",
    "c5523": "幽影猎犬",
    "c5540": "人蝠",
    "c5570": "幽影乌鸦",
    "c5590": "大蝎",
    "c5641": "幽影飞龙（小）",
    "c5651": "幽影飞龙",
    "c5661": "幽影飞龙（大）",
    "c5740": "落叶虫",
    "c5760": "落叶虫（大）",
    "c5830": "幽影树灵",
    "c5900": "幽影树灵（大）",
    "c6290": "幽影树灵（精英）",
    "c5530": "咒蛙",
}


def load_zh() -> dict[str, str]:
    cats = json.loads((SCRIPT / "enemy_categories.json").read_text(encoding="utf-8"))
    zh: dict[str, str] = dict(cats.get("model_prefix_display_zh") or {})
    doc = (SCRIPT.parent / ".ai/docs/小怪原型中文表.md").read_text(encoding="utf-8")
    for m in re.finditer(r"\|\s*(c\d{4})\s*\|\s*([^|]+?)\s*\|", doc):
        zh.setdefault(m.group(1).lower(), m.group(2).strip())
    for k, v in SUPPLEMENT_ZH.items():
        zh.setdefault(k.lower(), v)
    return zh


def load_sp_rates() -> dict[str, float]:
    rates: dict[str, float] = {}
    with (GAME / "csv/SpEffectParam.csv").open(encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            sid = str(row.get("ID") or "").strip()
            if not sid:
                continue
            try:
                rate = float(row.get("maxHpRate") or 1.0)
            except (TypeError, ValueError):
                rate = 1.0
            if rate != 1.0:
                rates[sid] = rate
    return rates


def load_npc_rows() -> dict[int, dict[str, str]]:
    out: dict[int, dict[str, str]] = {}
    with (GAME / "csv/NpcParam.csv").open(encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            try:
                out[int(row["ID"])] = row
            except (KeyError, TypeError, ValueError):
                pass
    return out


def combat_hp(
    npc_row: dict[str, str] | None,
    sp_rates: dict[str, float],
) -> tuple[int, float, list[tuple[str, float]]]:
    if not npc_row:
        return 0, 1.0, []
    try:
        base = int(npc_row.get("hp") or 0)
    except (TypeError, ValueError):
        base = 0
    if base <= 0:
        return 0, 1.0, []
    mult = 1.0
    parts: list[tuple[str, float]] = []
    for key, val in npc_row.items():
        if not key.startswith("spEffectID"):
            continue
        sid = str(val or "").strip()
        if sid in ("", "0", "-1"):
            continue
        rate = sp_rates.get(sid)
        if rate is None or rate == 1.0:
            continue
        mult *= rate
        parts.append((sid, rate))
    parts.sort(key=lambda x: -x[1])
    return max(1, int(round(base * mult))), mult, parts


def fmt_mult(parts: list[tuple[str, float]], total: float) -> str:
    if not parts:
        return "×1"
    if len(parts) == 1:
        sid, rate = parts[0]
        return f"{sid} ×{rate:g}"
    top = " × ".join(f"{sid}×{r:g}" for sid, r in parts[:3])
    if len(parts) > 3:
        top += f" …共{len(parts)}项"
    return f"{top} → ×{total:.3g}"


def main() -> None:
    sys.path.insert(0, str(SCRIPT))
    import boss_npc_detect as bnd  # noqa: E402

    if not JSONL.is_file():
        raise SystemExit(f"missing {JSONL}; run ScanM61 first")

    zh = load_zh()
    sp_rates = load_sp_rates()
    npc_rows = load_npc_rows()
    cats = json.loads((SCRIPT / "enemy_categories.json").read_text(encoding="utf-8"))
    csv_dir = GAME / "csv"

    slots = [json.loads(line) for line in JSONL.read_text(encoding="utf-8").splitlines() if line.strip()]

    by_key: dict[tuple[str, int], dict] = {}
    boss_keys: set[tuple[str, int]] = set()
    for s in slots:
        model = str(s.get("model", ""))
        p5 = model[:5] if len(model) >= 5 else model
        nid = int(s.get("npc") or 0)
        key = (p5, nid)
        rec = by_key.setdefault(
            key,
            {
                "p5": p5,
                "model": model,
                "npc": nid,
                "slots": 0,
                "maps": set(),
            },
        )
        rec["slots"] += 1
        rec["maps"].add(str(s.get("map", "")))

        tpl = {"model": model, "npc": nid, "think": s.get("think", 0), "map": s.get("map", "")}
        if bnd.template_is_detected_boss(tpl, csv_dir=csv_dir, categories_cfg=cats):
            boss_keys.add(key)

    # per (p5, npc) stats
    detail_rows: list[dict] = []
    for key, rec in by_key.items():
        p5, nid = key
        row = npc_rows.get(nid) or {}
        hp = int(row.get("hp") or 0)
        eff, mult, parts = combat_hp(row, sp_rates)
        soul = int(row.get("getSoul") or 0)
        detail_rows.append(
            {
                "p5": p5,
                "npc": nid,
                "zh": zh.get(p5, "—"),
                "hp": hp,
                "eff": eff,
                "mult": mult,
                "mult_str": fmt_mult(parts, mult),
                "soul": soul,
                "slots": rec["slots"],
                "maps": len(rec["maps"]),
                "is_boss": key in boss_keys,
                "combat": eff >= 1000,
            }
        )
    detail_rows.sort(key=lambda r: (-r["slots"], r["p5"], r["npc"]))

    # aggregate by model prefix
    by_p5: dict[str, list[dict]] = defaultdict(list)
    for r in detail_rows:
        by_p5[r["p5"]].append(r)

    agg: list[dict] = []
    for p5, items in by_p5.items():
        slots_sum = sum(x["slots"] for x in items)
        hps = [x["hp"] for x in items if x["hp"] > 0]
        effs = [x["eff"] for x in items if x["eff"] > 0]
        agg.append(
            {
                "p5": p5,
                "zh": items[0]["zh"],
                "slots": slots_sum,
                "variants": len(items),
                "hp_min": min(hps) if hps else 0,
                "hp_max": max(hps) if hps else 0,
                "eff_min": min(effs) if effs else 0,
                "eff_max": max(effs) if effs else 0,
                "combat": any(x["combat"] for x in items),
                "is_boss": any(x["is_boss"] for x in items),
            }
        )
    agg.sort(key=lambda r: (-r["slots"], r["p5"]))

    maps_n = len({s["map"] for s in slots})
    boss_slot_n = sum(1 for s in slots if (str(s.get("model", ""))[:5], int(s.get("npc") or 0)) in boss_keys)
    combat_agg = [a for a in agg if a["combat"] and not a["is_boss"]]
    ambient_agg = [a for a in agg if not a["combat"] and not a["is_boss"]]

    lines = [
        "# m61 DLC 地图 — 怪物详表（含有效血量）",
        "",
        f"- 扫描：`m61_*.msb`（**{maps_n}** 张有怪；总槽 **{len(slots)}**）",
        f"- 数据：`{JSONL.name}` + `Game/csv/NpcParam.csv` + `SpEffectParam.csv`",
        f"- Boss 槽：**{boss_slot_n}**；小怪槽：**{len(slots) - boss_slot_n}**",
        "",
        "## 有效血量怎么算",
        "",
        "**有效 HP = NpcParam 表 `hp` × 该行所有 spEffect 的 `maxHpRate`（连乘）**",
        "",
        "- DLC 战斗兵常见 **`20007090`（×13.16）** 或 **`20007000`（×7.05）**",
        "- 交界地区域 **`7010`～`7170`** 若挂在行上也会乘入",
        "- **≥1000** 视为正常战斗小怪；低于多为环境生物",
        "",
        "## 1. 按模型汇总（槽数降序）",
        "",
        "| 序号 | 中文名 | 模型 | 槽数 | npc变体 | 表HP | 有效HP | 战斗怪 |",
        "|---:|---|---|---:|---:|---|---|---|",
    ]
    for i, a in enumerate(agg, 1):
        hp_rng = f"{a['hp_min']}" if a["hp_min"] == a["hp_max"] else f"{a['hp_min']}~{a['hp_max']}"
        eff_rng = (
            f"{a['eff_min']}" if a["eff_min"] == a["eff_max"] else f"{a['eff_min']}~{a['eff_max']}"
        )
        tag = "Boss" if a["is_boss"] else ("是" if a["combat"] else "环境")
        lines.append(
            f"| {i} | {a['zh']} | {a['p5']} | {a['slots']} | {a['variants']} | {hp_rng} | {eff_rng} | {tag} |"
        )

    lines += [
        "",
        f"### 战斗小怪（有效 HP≥1000，{len(combat_agg)} 种模型）",
        "",
        "| 中文名 | 模型 | 槽数 | 有效HP |",
        "|---|---|---:|---|",
    ]
    for a in sorted(combat_agg, key=lambda x: -x["slots"]):
        eff_rng = (
            f"{a['eff_min']}" if a["eff_min"] == a["eff_max"] else f"{a['eff_min']}~{a['eff_max']}"
        )
        lines.append(f"| {a['zh']} | {a['p5']} | {a['slots']} | {eff_rng} |")

    lines += [
        "",
        f"### 环境生物（有效 HP<1000，{len(ambient_agg)} 种模型）",
        "",
        "| 中文名 | 模型 | 槽数 | 表HP | 有效HP |",
        "|---|---|---:|---|---|",
    ]
    for a in sorted(ambient_agg, key=lambda x: -x["slots"])[:40]:
        hp_rng = f"{a['hp_min']}" if a["hp_min"] == a["hp_max"] else f"{a['hp_min']}~{a['hp_max']}"
        eff_rng = (
            f"{a['eff_min']}" if a["eff_min"] == a["eff_max"] else f"{a['eff_min']}~{a['eff_max']}"
        )
        lines.append(f"| {a['zh']} | {a['p5']} | {a['slots']} | {hp_rng} | {eff_rng} |")
    if len(ambient_agg) > 40:
        lines.append(f"| … | … | … | … | （另有 {len(ambient_agg) - 40} 种，见明细） |")

    lines += [
        "",
        "## 2. 明细（模型 + npc id）",
        "",
        "| 序号 | 中文名 | 模型 | npc id | 表HP | 倍率 | 有效HP | 卢恩 | 槽数 | 地图数 |",
        "|---:|---|---|---:|---:|---|---:|---:|---:|---:|",
    ]
    for i, r in enumerate(detail_rows, 1):
        lines.append(
            f"| {i} | {r['zh']} | {r['p5']} | {r['npc']} | {r['hp']} | {r['mult_str']} | {r['eff']} | {r['soul']} | {r['slots']} | {r['maps']} |"
        )

    # Boss-only section
    boss_detail = [r for r in detail_rows if r["is_boss"]]
    lines += [
        "",
        f"## 3. Boss 槽明细（{len(boss_detail)} 种 npc）",
        "",
        "| 中文名 | 模型 | npc id | 表HP | 倍率 | 有效HP | 槽数 |",
        "|---|---|---:|---:|---|---:|---:|",
    ]
    for r in sorted(boss_detail, key=lambda x: -x["slots"]):
        lines.append(
            f"| {r['zh']} | {r['p5']} | {r['npc']} | {r['hp']} | {r['mult_str']} | {r['eff']} | {r['slots']} |"
        )

    # per-map top 5
    by_map: dict[str, list] = defaultdict(list)
    for s in slots:
        by_map[str(s["map"])].append(s)
    lines += [
        "",
        "## 4. 各地图怪物组成（前 30 张，按槽数）",
        "",
        "| 地图 | 总槽 | Boss | 主要模型（槽数） |",
        "|---|---:|---:|---|",
    ]
    for map_id in sorted(by_map.keys(), key=lambda m: -len(by_map[m]))[:30]:
        ms = by_map[map_id]
        mc: dict[str, int] = defaultdict(int)
        for s in ms:
            mc[str(s.get("model", ""))[:5]] += 1
        top = ", ".join(f"{k}×{v}" for k, v in sorted(mc.items(), key=lambda x: -x[1])[:5])
        bn = sum(
            1
            for s in ms
            if (str(s.get("model", ""))[:5], int(s.get("npc") or 0)) in boss_keys
        )
        lines.append(f"| {map_id} | {len(ms)} | {bn} | {top} |")

    lines += [
        "",
        "---",
        "",
        "中文名来源：`model_prefix_display_zh` + `小怪原型中文表` + 本脚本 `SUPPLEMENT_ZH`（c54 环境生物为社区/文件对照，标「—」者待补）。",
        "",
    ]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {OUT} ({len(detail_rows)} detail rows, {len(agg)} models)")


if __name__ == "__main__":
    main()
