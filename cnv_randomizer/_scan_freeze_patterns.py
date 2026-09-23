"""Static freeze-pattern scan on spawn map (no replay)."""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from _audit_freeze_pipeline import _parse_rows
from npc_think_sanitize import is_runtime_think_copy_id
from whitelist_slot_receptor import classify_receptor_bucket

spawn = Path(r"V:\games\Elden Ring\Game\mod\dll\cnv_enemy_spawn_map.txt")
slots = json.loads((SCRIPT_DIR / "cache/enemy_index.json").read_text(encoding="utf-8"))["slots"]
slot_by = {(s["map_id"], s["name"]): s for s in slots}

GROUND = {"ground", "collision_anchor"}


def boss_subband(think: int) -> str | None:
    """Heuristic: 01xx sub-line within model family (often boss/special)."""
    if think <= 0:
        return None
    tail = think % 10000
    if 100 <= tail < 200:
        return "01xx"
    if 900 <= tail < 1000:
        return "09xx"
    return None


c = Counter()
samples: dict[str, list[str]] = {}

for row in _parse_rows(spawn):
    slot = slot_by.get((row["map_id"], row["entity"]))
    if not slot:
        continue
    think = row["think"]
    if is_runtime_think_copy_id(think):
        continue
    plc = row["placement"]
    sw = str(slot.get("walk_route") or "").strip()
    bucket = classify_receptor_bucket(slot)

    if row["model"] == "c3180" and 3_180_010_0 <= think < 3_180_020_0 and plc in GROUND:
        c["wolf_boss_ground"] += 1
    if row["model"] == "c4460" and 44_607_800 <= think < 44_607_900 and plc in GROUND:
        c["chariot_boss_ground"] += 1
    if bucket == "ground_stand" and not sw and row["model"] == "c5250":
        c["c5250_ground_no_route"] += 1
        if len(samples.setdefault("c5250", [])) < 5:
            samples["c5250"].append(f"{row['map_id']}:{row['entity']} tpl={row['template_id']}")
    if bucket == "patrol" and sw and plc in GROUND:
        c["patrol_slot_ground_placement"] += 1
    band = boss_subband(think)
    if band and plc in GROUND and not sw and bucket == "ground_stand":
        key = f"ground_01xx_{row['model']}"
        c[key] += 1
        if len(samples.setdefault(key, [])) < 4:
            samples[key].append(
                f"{row['map_id']}:{row['entity']} think={think} tpl={row['template_id']}"
            )

print("=== static freeze pattern scan seed 60512803 ===")
for k, v in sorted(c.items(), key=lambda x: (-x[1], x[0])):
    if v:
        print(f"{k}: {v}")
for k, lines in samples.items():
    print(f"\n# {k}")
    for line in lines:
        print(f"  {line}")
