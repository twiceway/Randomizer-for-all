import csv, json, sys
from pathlib import Path
from collections import Counter

GAME = Path(r"V:/games/Elden Ring/Game")
SCRIPT = Path(r"V:/1_mel/Ringrandom/cnv_randomizer")
sys.path.insert(0, str(SCRIPT))
from paths import OUTPUT_REPORTS  # noqa: E402
REGION = {
    "7010": 1.141, "7020": 1.141, "7030": 1.656,
    "7060": 2.266, "7070": 2.266, "7080": 2.688, "7090": 2.688,
    "7110": 4.125, "7120": 4.844, "7170": 4.844, "7160": 5.484,
}

npc = {}
with open(GAME / "csv/NpcParam.csv", encoding="utf-8-sig") as f:
    for row in csv.DictReader(f):
        npc[int(row["ID"])] = row


def eff(row):
    hp = int(row.get("hp") or 0)
    m = 1.0
    for k, v in row.items():
        if k.startswith("spEffectID") and str(v or "").strip() in REGION:
            m = max(m, REGION[str(v).strip()])
    return int(round(hp * m))


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

slots = [json.loads(l) for l in (OUTPUT_REPORTS / "_m61_slots.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
conf = [s for s in slots if s["map"] in MAPS]

print("=== key npc: table HP vs effective HP ===")
for nid in [50600093, 50800080, 50801094, 50900080, 50110094, 51930094, 53600084, 53810081, 52400994, 54010094, 54100094]:
    r = npc.get(nid)
    if not r:
        print(nid, "MISSING")
        continue
    print(f"{nid}  hp={r.get('hp')}  eff={eff(r)}  soul={r.get('getSoul')}")

print("\n=== c50xx in YOUR confirmed maps ===")
c50 = [s for s in conf if str(s.get("model", "")).startswith("c50")]
by = Counter((s["model"][:5], int(s["npc"])) for s in c50)
for (p5, nid), cnt in by.most_common(20):
    r = npc.get(nid) or {}
    print(f"  {p5} npc={nid} slots={cnt} hp={r.get('hp','?')} eff={eff(r) if r else '?'}")

print("\n=== composition ===")
for label, arr in [("确认41图", conf), ("全m61", slots)]:
    c = Counter()
    for s in arr:
        nid = int(s.get("npc") or 0)
        if 50100000 <= nid < 54000000:
            c["npc50"] += 1
        elif 54000000 <= nid < 55000000:
            c["npc54"] += 1
        else:
            c["other"] += 1
    print(label, dict(c), "total", len(arr))

print("\n=== npc50 HP on FULL m61 (not your subset) ===")
hps = []
for s in slots:
    nid = int(s.get("npc") or 0)
    if 50100000 <= nid < 54000000:
        r = npc.get(nid)
        if r:
            hps.append((int(r["hp"]), eff(r), s["model"][:5]))
hps.sort()
print("count", len(hps), "min/med/max", hps[0][0], hps[len(hps)//2][0], hps[-1][0])
print("top models", Counter((x[2], x[0]) for x in hps).most_common(10))
