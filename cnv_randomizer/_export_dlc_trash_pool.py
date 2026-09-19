"""Export live DLC trash donor pool: Chinese names + HP (donor pick + NpcParam range)."""
import csv
import json
import re
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent
cats = json.loads((SCRIPT / "enemy_categories.json").read_text(encoding="utf-8"))
prefixes = list(cats.get("dlc_trash_donor_model_prefixes") or [])
prefix_set = {p.lower() for p in prefixes}

# Chinese names from archetype doc table
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
    mult = 1.0
    for k, v in row.items():
        if k.startswith("spEffectID") and str(v or "").strip() in REGION:
            mult = max(mult, REGION[str(v).strip()])
    return mult


rows_by_model: dict[str, list[tuple[int, int, dict[str, str]]]] = {p: [] for p in prefixes}
npc_path = Path(r"V:/games/Elden Ring/Game/csv/NpcParam.csv")

with npc_path.open(encoding="utf-8-sig", newline="") as f:
    for row in csv.DictReader(f):
        try:
            npc = int(row["ID"])
        except (KeyError, TypeError, ValueError):
            continue
        if not (50100000 <= npc < 54000000):
            continue
        model = f"c{npc // 10000}"
        if model.lower() not in prefix_set:
            continue
        if row.get("isSoulGetByBoss") == "1":
            continue
        try:
            hp = int(row.get("hp") or 0)
        except (TypeError, ValueError):
            hp = 0
        if hp <= 0:
            continue
        rows_by_model.setdefault(model.lower(), []).append((hp, npc, row))

# Live donor pick = min HP per model (supplement_dlc_trash_templates)
print("| 模型 | 中文名 | 现网捐皮npc | 表HP | 有效HP~ | NpcParam行数 | 池内HP范围 | m60槽位 |")
print("|------|--------|-------------|------|---------|--------------|------------|---------|")

idx = json.loads((SCRIPT / "cache/enemy_index.json").read_text(encoding="utf-8"))
m60_models: dict[str, int] = {}
for s in idx.get("slots", []):
    if not str(s.get("map_id", "")).startswith("m60_"):
        continue
    m = str(s.get("model", "")).lower()[:5]
    if m in prefix_set:
        m60_models[m] = m60_models.get(m, 0) + 1

for p in prefixes:
    model = p.lower()
    vals = rows_by_model.get(model, [])
    zh = ZH.get(model, "（未录入原型表）")
    if not vals:
        print(f"| {p} | {zh} | — | — | — | 0 | — | {m60_models.get(model, 0)} |")
        continue
    # donor pick
    hp_d, npc_d, row_d = min(vals, key=lambda x: x[0])
    eff_d = int(round(hp_d * region_mult(row_d)))
    hps = sorted(x[0] for x in vals)
    effs = sorted(int(round(x[0] * region_mult(x[2]))) for x in vals)
    print(
        f"| {p} | {zh} | {npc_d} | {hp_d} | {eff_d} | {len(vals)} | "
        f"{hps[0]}～{hps[-1]}（有效 {effs[0]}～{effs[-1]}） | {m60_models.get(model, 0)} |"
    )

# Summary
all_donor_hp = []
for p in prefixes:
    vals = rows_by_model.get(p.lower(), [])
    if vals:
        all_donor_hp.append(min(vals, key=lambda x: x[0])[0])
if all_donor_hp:
    s = sorted(all_donor_hp)
    print()
    print(f"现网捐皮表HP: n={len(s)} min={s[0]} med={s[len(s)//2]} max={s[-1]}")
    for thr in (500, 1000, 1500, 2000, 3000):
        n = sum(1 for h in s if h >= thr)
        print(f"  捐皮 >= {thr}: {n}/{len(s)}")
