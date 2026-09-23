"""Scan all m61 DLC overworld MSB — trash + boss report."""
from __future__ import annotations

import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from subprocess import run

SCRIPT = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT))
from paths import OUTPUT_REPORTS  # noqa: E402

GAME = Path(r"V:/games/Elden Ring/Game")
OUT_MD = OUTPUT_REPORTS / "m61地图小怪Boss扫描.md"
JSONL = OUTPUT_REPORTS / "_m61_slots.jsonl"

# 1) export slots
scan_proj = SCRIPT / "_peek_msb_dlc_soldiers/ScanM61.csproj"
r = run(["dotnet", "run", "--project", str(scan_proj)], capture_output=True, text=True, encoding="utf-8", errors="replace")
print(r.stdout)
if r.returncode != 0:
    print(r.stderr, file=sys.stderr)
    raise SystemExit(r.returncode)

sys.path.insert(0, str(SCRIPT))
import boss_npc_detect as bnd  # noqa: E402

cats = json.loads((SCRIPT / "enemy_categories.json").read_text(encoding="utf-8"))
dlc_whitelist = set(cats.get("dlc_trash_donor_model_prefixes") or [])
csv_dir = GAME / "csv"

ZH: dict[str, str] = {}
doc = (SCRIPT.parent / ".ai/docs/小怪原型中文表.md").read_text(encoding="utf-8")
for m in re.finditer(r"\|\s*(c\d{4})\s*\|\s*([^|]+?)\s*\|", doc):
    ZH[m.group(1).lower()] = m.group(2).strip()

REGION = {
    "7010": 1.141, "7020": 1.141, "7030": 1.656,
    "7060": 2.266, "7070": 2.266, "7080": 2.688, "7090": 2.688,
    "7110": 4.125, "7120": 4.844, "7170": 4.844, "7160": 5.484,
}


def region_mult(row: dict[str, str]) -> float:
    m = 1.0
    for k, v in row.items():
        if k.startswith("spEffectID") and str(v or "").strip() in REGION:
            m = max(m, REGION[str(v).strip()])
    return m


npc_rows: dict[int, dict[str, str]] = {}
with (GAME / "csv/NpcParam.csv").open(encoding="utf-8-sig") as f:
    for row in csv.DictReader(f):
        try:
            npc_rows[int(row["ID"])] = row
        except (KeyError, TypeError, ValueError):
            pass

slots = [json.loads(line) for line in JSONL.read_text(encoding="utf-8").splitlines() if line.strip()]
print(f"loaded slots: {len(slots)}")

BOSS_CAT_ZH = {
    "major_boss": "主线大Boss",
    "field_boss": "次要Boss",
    "minor_boss": "小Boss/人形Boss",
    "evergaol": "封印监牢",
    "night": "红灵",
    "cnv_special": "法魂特殊Boss",
}

by_model: dict[str, list[dict]] = defaultdict(list)
by_map: dict[str, list[dict]] = defaultdict(list)
boss_by_cat: dict[str, list[tuple]] = defaultdict(list)
trash_models: dict[str, list[tuple]] = defaultdict(list)
npc50_slots: list[tuple] = []

for s in slots:
    model = str(s.get("model", ""))
    p5 = model[:5] if len(model) >= 5 else model
    nid = int(s.get("npc") or 0)
    map_id = str(s.get("map", ""))
    row = npc_rows.get(nid) or {}
    hp = int(row.get("hp") or 0)
    eff = int(round(hp * region_mult(row))) if hp else 0
    rec = {**s, "p5": p5, "hp": hp, "eff": eff}
    by_model[p5].append(rec)
    by_map[map_id].append(rec)

    if 50100000 <= nid < 54000000:
        npc50_slots.append((nid, model, hp, eff, map_id, str(s.get("name", ""))))

    tpl = {"model": model, "npc": nid, "think": s.get("think", 0), "map": map_id}
    if bnd.template_is_detected_boss(tpl, csv_dir=csv_dir, categories_cfg=cats):
        cat = bnd.classify_detected_boss(model, donor_map_id=map_id, categories_cfg=cats)
        boss_by_cat[cat].append((p5, nid, hp, eff, map_id, str(s.get("name", "")), ZH.get(p5, "—")))
    else:
        trash_models[p5].append((hp, eff, nid, map_id, str(s.get("name", ""))))

maps_with_enemies = sorted(by_map.keys())
lines = [
    "# m61 DLC 野外地图 — 小怪 & Boss 全扫",
    "",
    "- 来源：`Game/mod/map/MapStudio/m61_*.msb.dcx`",
    "- 解析：`_sfnext/SoulsFormats`（旧 DSMSPortable 读不了 m61）",
    f"- 有敌人槽地图：**{len(maps_with_enemies)}** 张；总槽：**{len(slots)}**",
    f"- Boss 槽：**{sum(len(v) for v in boss_by_cat.values())}**；小怪槽：**{len(slots) - sum(len(v) for v in boss_by_cat.values())}**",
    "",
    "## 1. Boss 按类别",
    "",
]

for cat in ("major_boss", "field_boss", "minor_boss", "evergaol", "night", "cnv_special"):
    items = boss_by_cat.get(cat, [])
    if not items:
        continue
    lines.append(f"### {BOSS_CAT_ZH.get(cat, cat)}（{len(items)} 槽）")
    lines.append("")
    by_p5: dict[str, list] = defaultdict(list)
    for t in items:
        by_p5[t[0]].append(t)
    lines.append("| 模型 | 中文 | 槽数 | 表HP | 示例地图 |")
    lines.append("|------|------|------|------|----------|")
    for p5 in sorted(by_p5, key=lambda k: -len(by_p5[k])):
        ts = by_p5[p5]
        hps = sorted(t[2] for t in ts if t[2] > 0)
        hp_s = f"{hps[0]}~{hps[-1]}" if len(hps) > 1 else (str(hps[0]) if hps else "—")
        lines.append(f"| {p5} | {ts[0][6]} | {len(ts)} | {hp_s} | {ts[0][4]} |")
    lines.append("")

lines += ["## 2. npc 50xxxxxx（DLC NpcParam 段）", ""]
if npc50_slots:
    by_npc: dict[int, list] = defaultdict(list)
    for t in npc50_slots:
        by_npc[t[0]].append(t)
    lines.append(f"**{len(npc50_slots)} 槽** / **{len(by_npc)}** 个 npc id")
    lines.append("")
    lines.append("| npc | 模型 | 中文 | 表HP | 有效HP~ | 槽数 | 示例地图 |")
    lines.append("|-----|------|------|------|---------|------|----------|")
    for nid in sorted(by_npc, key=lambda n: -len(by_npc[n])):
        ts = by_npc[nid]
        p5 = ts[0][1][:5]
        hp, eff = ts[0][2], ts[0][3]
        lines.append(f"| {nid} | {p5} | {ZH.get(p5, '—')} | {hp} | {eff} | {len(ts)} | {ts[0][4]} |")
else:
    lines.append("**0 槽**")

lines += ["", "## 3. DLC 捐皮白名单 c50xx 实地", ""]
wl_found = [(p, trash_models[p]) for p in sorted(dlc_whitelist) if trash_models.get(p)]
if wl_found:
    lines.append("| 模型 | 中文 | 槽数 | 表HP |")
    lines.append("|------|------|------|------|")
    for p, vals in wl_found:
        hps = sorted(x[0] for x in vals if x[0] > 0)
        hp_s = f"{hps[0]}~{hps[-1]}" if len(hps) > 1 else (str(hps[0]) if hps else "—")
        lines.append(f"| {p} | {ZH.get(p, '—')} | {len(vals)} | {hp_s} |")
else:
    lines.append("**白名单 20 前缀：实地 0 槽**")

lines += ["", "## 4. 小怪 Top40（按槽数）", ""]
lines.append("| 模型 | 中文 | 槽数 | 表HP中位 | DLC白名单 |")
lines.append("|------|------|------|----------|-----------|")
trash_sorted = sorted(trash_models.items(), key=lambda x: -len(x[1]))
for p5, vals in trash_sorted[:40]:
    hps = sorted(x[0] for x in vals if x[0] > 0)
    med = hps[len(hps) // 2] if hps else 0
    lines.append(f"| {p5} | {ZH.get(p5, '—')} | {len(vals)} | {med} | {'是' if p5 in dlc_whitelist else '否'} |")

lines += ["", "## 5. 全模型 Top30（含Boss）", ""]
all_sorted = sorted(by_model.items(), key=lambda x: -len(x[1]))
lines.append("| 模型 | 中文 | 槽数 | 表HP中位 |")
lines.append("|------|------|------|----------|")
for p5, vals in all_sorted[:30]:
    hps = sorted(v["hp"] for v in vals if v["hp"] > 0)
    med = hps[len(hps) // 2] if hps else 0
    lines.append(f"| {p5} | {ZH.get(p5, '—')} | {len(vals)} | {med} |")

lines += ["", "## 6. 每张图槽位概览", ""]
lines.append("| 地图 | 总槽 | Boss | 小怪 | Top3模型 |")
lines.append("|------|------|------|------|----------|")
for map_id in maps_with_enemies:
    ms = by_map[map_id]
    boss_n = sum(
        1 for s in ms
        if bnd.template_is_detected_boss(
            {"model": s["model"], "npc": s.get("npc", 0), "think": s.get("think", 0), "map": map_id},
            csv_dir=csv_dir,
            categories_cfg=cats,
        )
    )
    top = sorted(by_model.keys(), key=lambda p: -sum(1 for x in ms if x["p5"] == p))[:3]
    top_s = ", ".join(f"{p}x{sum(1 for x in ms if x['p5']==p)}" for p in top if sum(1 for x in ms if x["p5"] == p))
    lines.append(f"| {map_id} | {len(ms)} | {boss_n} | {len(ms)-boss_n} | {top_s} |")

OUT_MD.parent.mkdir(parents=True, exist_ok=True)
OUT_MD.write_text("\n".join(lines), encoding="utf-8")
print(f"wrote {OUT_MD}")
