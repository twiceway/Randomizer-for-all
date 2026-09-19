"""Rescan 525 CNV DLC maps — analyze exported jsonl."""
import csv
import json
import re
from collections import defaultdict
from pathlib import Path
from subprocess import run

SCRIPT = Path(__file__).resolve().parent
import sys
sys.path.insert(0, str(SCRIPT))
from paths import OUTPUT_REPORTS  # noqa: E402

GAME = Path(r"V:/games/Elden Ring/Game")
OUT = OUTPUT_REPORTS / "法魂DLC地图小怪扫描.md"

# export slots via C#
scan_proj = SCRIPT / "_peek_msb_dlc_soldiers/Scan525.csproj"
r = run(["dotnet", "run", "--project", str(scan_proj)], capture_output=True, text=True, encoding="utf-8", errors="replace")
print(r.stdout)
if r.returncode != 0:
    print(r.stderr)
    raise SystemExit(r.returncode)

ZH: dict[str, str] = {}
doc = (SCRIPT.parent / ".ai/docs/小怪原型中文表.md").read_text(encoding="utf-8")
for m in re.finditer(r"\|\s*(c\d{4})\s*\|\s*([^|]+?)\s*\|", doc):
    ZH[m.group(1).lower()] = m.group(2).strip()
cats = json.loads((SCRIPT / "enemy_categories.json").read_text(encoding="utf-8"))
dlc_whitelist = set(cats.get("dlc_trash_donor_model_prefixes") or [])

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


npc: dict[int, dict[str, str]] = {}
with (GAME / "csv/NpcParam.csv").open(encoding="utf-8-sig") as f:
    for row in csv.DictReader(f):
        try:
            npc[int(row["ID"])] = row
        except (KeyError, TypeError, ValueError):
            pass

jsonl = OUTPUT_REPORTS / "_dlc525_slots.jsonl"
slots = [json.loads(line) for line in jsonl.read_text(encoding="utf-8").splitlines() if line.strip()]
print(f"loaded slots: {len(slots)}")

SOLDIER_KNIGHT = {
    "c3010", "c3020", "c3030", "c3300", "c4200", "c4201", "c4310", "c4311", "c4312",
    "c4313", "c4314", "c4315", "c4316", "c4351", "c4353", "c4371", "c4372", "c4374",
    "c5010", "c5011", "c5020", "c5040", "c5060", "c5061", "c5080", "c5081", "c5090",
    "c5160", "c5190", "c5192", "c5193", "c5250", "c5251", "c5271", "c5330", "c5340",
    "c5360", "c5381", "c5391", "c5392", "c5180", "c5181", "c5280", "c5310",
}

by_model: dict[str, list[tuple[int, int, int, str, str]]] = defaultdict(list)
npc50_slots = []
for s in slots:
    model = str(s.get("model", ""))
    p5 = model[:5] if len(model) >= 5 else model
    nid = int(s.get("npc") or 0)
    row = npc.get(nid) or {}
    hp = int(row.get("hp") or 0)
    eff = int(round(hp * region_mult(row))) if hp else 0
    by_model[p5].append((hp, eff, nid, str(s.get("map")), str(s.get("name", ""))))
    if 50100000 <= nid < 54000000:
        npc50_slots.append((nid, model, hp, eff, str(s.get("map"))))

all_models = sorted(by_model.items(), key=lambda x: -len(x[1]))
maps_seen = len({s["map"] for s in slots})

lines = [
    "# 法魂 DLC 地图小怪扫描（525 张 m60+m61 MSB）",
    "",
    "- 来源：`Game/mod/map/MapStudio`",
    f"- 有敌人槽的地图：**{maps_seen}** 张；总敌人槽：**{len(slots)}**",
    "- 按 **MSB 实地摆怪**，不是 NpcParam 捐皮白名单",
    "",
    "## 1. npc 50xxxxxx（DLC NpcParam 段）",
    "",
]
if npc50_slots:
    by_npc: dict[int, list] = defaultdict(list)
    for t in npc50_slots:
        by_npc[t[0]].append(t)
    lines.append(f"**{len(npc50_slots)} 槽** / **{len(by_npc)}** 个 npc id")
    lines.append("")
    lines.append("| npc | 模型 | 中文 | 表HP | 有效HP~ | 槽数 | 示例地图 |")
    lines.append("|-----|------|------|------|---------|------|----------|")
    for nid in sorted(by_npc, key=lambda n: -len(by_npc[n]))[:50]:
        ts = by_npc[nid]
        model = ts[0][1][:5]
        zh = ZH.get(model, "—")
        hp, eff = ts[0][2], ts[0][3]
        lines.append(f"| {nid} | {model} | {zh} | {hp} | {eff} | {len(ts)} | {ts[0][4]} |")
else:
    lines.append("**0 槽**")

lines += ["", "## 2. 士兵/骑士类（扩展）", ""]
lines.append("| 模型 | 中文 | 槽数 | 表HP | 有效HP~ | DLC白名单 |")
lines.append("|------|------|------|------|---------|-----------|")
for p in sorted(SOLDIER_KNIGHT):
    vals = by_model.get(p, [])
    if not vals:
        continue
    hps = sorted(x[0] for x in vals if x[0] > 0)
    effs = sorted(x[1] for x in vals if x[1] > 0)
    if not hps:
        continue
    lines.append(
        f"| {p} | {ZH.get(p, '—')} | {len(vals)} | "
        f"{hps[0]}~{hps[-1]} | {effs[0]}~{effs[-1]} | "
        f"{'是' if p in dlc_whitelist else '否'} |"
    )

lines += ["", "## 3. 捐皮白名单 c50xx 实地出现", ""]
wl_found = [(p, by_model[p]) for p in sorted(dlc_whitelist) if by_model.get(p)]
if wl_found:
    lines.append("| 模型 | 槽数 | 表HP |")
    lines.append("|------|------|------|")
    for p, vals in wl_found:
        hps = sorted(x[0] for x in vals if x[0] > 0)
        lines.append(f"| {p} | {len(vals)} | {hps[0]}~{hps[-1] if hps else 0} |")
else:
    lines.append("**白名单 20 个前缀：实地 0 槽**")

lines += ["", "## 4. Top30 摆怪模型", ""]
lines.append("| 模型 | 中文 | 槽数 | 表HP中位 |")
lines.append("|------|------|------|----------|")
for p, vals in all_models[:30]:
    hps = sorted(x[0] for x in vals if x[0] > 0)
    med = hps[len(hps) // 2] if hps else 0
    lines.append(f"| {p} | {ZH.get(p, '—')} | {len(vals)} | {med} |")

lines += ["", "## 5. m60 vs m61", ""]
for mp in ("m60_", "m61_"):
    sub = [s for s in slots if str(s.get("map", "")).startswith(mp)]
    sk = sum(1 for s in sub if str(s.get("model", ""))[:5] in SOLDIER_KNIGHT)
    c50 = sum(1 for s in sub if 50100000 <= int(s.get("npc") or 0) < 54000000)
    lines.append(f"- `{mp}*`：槽 {len(sub)}，士兵/骑士 {sk}，npc50段 {c50}")

# high HP trash-like on DLC maps (table hp >= 1000, not boss models)
lines += ["", "## 6. 表HP≥1000 的非Boss槽（可能是真 DLC 强度小怪）", ""]
boss_p = {x[:5] for x in [
    "c5030", "c5050", "c5070", "c5120", "c5130", "c5210", "c5220", "c5230",
    "c5300", "c5311", "c5320", "c5200", "c5380",
]}
hi = []
for s in slots:
    p5 = str(s.get("model", ""))[:5]
    if p5 in boss_p:
        continue
    nid = int(s.get("npc") or 0)
    hp = int((npc.get(nid) or {}).get("hp") or 0)
    if hp >= 1000:
        eff = int(round(hp * region_mult(npc.get(nid) or {})))
        hi.append((hp, eff, p5, nid, str(s.get("map")), ZH.get(p5, "—")))
hi.sort(reverse=True)
lines.append("| 表HP | 有效~ | 模型 | 中文 | npc | 地图 |")
lines.append("|------|-------|------|------|-----|------|")
seen = set()
for hp, eff, p5, nid, m, zh in hi:
    key = (p5, nid)
    if key in seen:
        continue
    seen.add(key)
    lines.append(f"| {hp} | {eff} | {p5} | {zh} | {nid} | {m} |")
    if len(seen) >= 40:
        break

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text("\n".join(lines), encoding="utf-8")
print(f"wrote {OUT}")
