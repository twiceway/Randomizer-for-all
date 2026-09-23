"""Export monster table for user-confirmed m61 DLC map whitelist."""
from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent
import sys
sys.path.insert(0, str(SCRIPT))
from paths import OUTPUT_REPORTS  # noqa: E402

GAME = Path(r"V:/games/Elden Ring/Game")
OUT = OUTPUT_REPORTS / "m61确认DLC区域怪物表.md"

MAPS = {
    "m61_00_00_99", "m61_10_10_02", "m61_10_11_02", "m61_10_12_02",
    "m61_11_08_02", "m61_11_09_02", "m61_11_10_02", "m61_11_11_02",
    "m61_11_11_12", "m61_11_12_02", "m61_11_13_02", "m61_12_08_02",
    "m61_12_09_02", "m61_12_10_02", "m61_12_11_02", "m61_12_12_02",
    "m61_12_13_02", "m61_13_08_02", "m61_13_09_02", "m61_13_10_02",
    "m61_13_11_02", "m61_13_12_02",
    "m61_43_44_00", "m61_43_45_00", "m61_43_46_00", "m61_43_47_00", "m61_43_48_00",
    "m61_44_40_00", "m61_44_41_00", "m61_44_42_00", "m61_44_43_00",
    "m61_44_44_00", "m61_44_44_10", "m61_44_45_00", "m61_44_45_10",
    "m61_44_46_00", "m61_44_46_10", "m61_44_47_00", "m61_44_47_10",
    "m61_44_48_00", "m61_44_49_00",
}

cats = json.loads((SCRIPT / "enemy_categories.json").read_text(encoding="utf-8"))
ZH: dict[str, str] = dict(cats.get("model_prefix_display_zh") or {})
doc = (SCRIPT.parent / ".ai/docs/小怪原型中文表.md").read_text(encoding="utf-8")
for m in re.finditer(r"\|\s*(c\d{4})\s*\|\s*([^|]+?)\s*\|", doc):
    ZH.setdefault(m.group(1).lower(), m.group(2).strip())

npc_rows: dict[int, dict[str, str]] = {}
with (GAME / "csv/NpcParam.csv").open(encoding="utf-8-sig") as f:
    for row in csv.DictReader(f):
        try:
            npc_rows[int(row["ID"])] = row
        except (KeyError, TypeError, ValueError):
            pass

slots = [
    json.loads(line)
    for line in (OUTPUT_REPORTS / "_m61_slots.jsonl").read_text(encoding="utf-8").splitlines()
    if line.strip()
]
slots = [s for s in slots if s["map"] in MAPS]

by_key: dict[tuple[str, int], dict] = defaultdict(
    lambda: {"slots": 0, "maps": set(), "model": "", "npc": 0}
)
for s in slots:
    model = str(s.get("model", ""))
    p5 = model[:5] if len(model) >= 5 else model
    nid = int(s.get("npc") or 0)
    key = (p5, nid)
    rec = by_key[key]
    rec["slots"] += 1
    rec["maps"].add(s["map"])
    rec["model"] = p5
    rec["npc"] = nid

rows: list[tuple[int, str, int, str, int, int]] = []
for (p5, nid), rec in by_key.items():
    row = npc_rows.get(nid) or {}
    hp = int(row.get("hp") or 0)
    zh = ZH.get(p5, "—")
    rows.append((rec["slots"], p5, nid, zh, hp, len(rec["maps"])))
rows.sort(key=lambda x: (-x[0], x[1], x[2]))

maps_with = sorted({s["map"] for s in slots})
maps_empty = sorted(MAPS - set(maps_with))

lines = [
    "# m61 确认 DLC 区域 — 怪物表",
    "",
    f"- 地图白名单：**{len(MAPS)}** 张（Smithbox 确认）",
    f"- 有敌人槽：**{len(maps_with)}** 张；总槽：**{len(slots)}**",
    f"- 不同「模型 + npc」组合：**{len(rows)}** 种",
    "",
]
if maps_empty:
    lines += ["## 无敌人槽的图", ""]
    lines += [f"- `{m}`" for m in maps_empty]
    lines += [""]

lines += [
    "## 怪物列表（按槽数降序）",
    "",
    "| 序号 | 中文名 | 表HP | 模型 | npc id | 槽数 | 图数 |",
    "|------|--------|------|------|--------|------|------|",
]
for i, (cnt, p5, nid, zh, hp, nmaps) in enumerate(rows, 1):
    lines.append(f"| {i} | {zh} | {hp} | {p5} | {nid} | {cnt} | {nmaps} |")

by_p5: dict[str, dict] = defaultdict(lambda: {"slots": 0, "hps": set(), "npcs": set()})
for cnt, p5, nid, _zh, hp, _nmaps in rows:
    by_p5[p5]["slots"] += cnt
    by_p5[p5]["npcs"].add(nid)
    if hp > 0:
        by_p5[p5]["hps"].add(hp)

lines += ["", "## 按模型前缀汇总", ""]
lines += ["| 序号 | 中文名 | 表HP | 模型 | 槽数 |", "|------|--------|------|------|------|"]
for i, (p5, rec) in enumerate(sorted(by_p5.items(), key=lambda x: -x[1]["slots"]), 1):
    hps = sorted(rec["hps"])
    hp_s = f"{hps[0]}~{hps[-1]}" if len(hps) > 1 else (str(hps[0]) if hps else "—")
    lines.append(f"| {i} | {ZH.get(p5, '—')} | {hp_s} | {p5} | {rec['slots']} |")

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text("\n".join(lines), encoding="utf-8")
print(f"wrote {OUT}")
print(f"rows={len(rows)} maps_with={len(maps_with)} slots={len(slots)} empty_maps={len(maps_empty)}")
