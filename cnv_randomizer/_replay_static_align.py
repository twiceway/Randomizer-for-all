"""Replay spawn map through resolve pipeline; count static 01xx freeze heuristics."""
from __future__ import annotations

import gzip
import json
import sys
from collections import Counter
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from _audit_freeze_pipeline import _parse_rows
from donor_vanilla_states import build_model_vanilla_state_index, resolve_slot_runtime_npc_and_think
from npc_think_sanitize import is_runtime_think_copy_id

spawn = Path(r"V:\games\Elden Ring\Game\mod\dll\cnv_enemy_spawn_map.txt")
slots = json.loads((SCRIPT_DIR / "cache/enemy_index.json").read_text(encoding="utf-8"))["slots"]
slot_by = {(s["map_id"], s["name"]): s for s in slots}
mi = build_model_vanilla_state_index(slots)
prep = json.loads(gzip.open(SCRIPT_DIR / "cache/enemy_slot_prep.json.gz", "rt", encoding="utf-8").read())
donor_by = {str(d.get("template_id") or ""): d for d in prep.get("donors", []) if d.get("template_id")}

GROUND = {"ground", "collision_anchor"}
still: Counter[str] = Counter()
fix: Counter[str] = Counter()

for row in _parse_rows(spawn):
    slot = slot_by.get((row["map_id"], row["entity"]))
    if not slot:
        continue
    tpl = dict(donor_by.get(row["template_id"]) or {})
    tpl.setdefault("model", row["model"])
    tpl.setdefault("think", row["think"])
    tpl.setdefault("npc", row["npc"])
    sim_npc, sim_think = resolve_slot_runtime_npc_and_think(
        slot, tpl, int(row["npc"]), None, mi
    )
    think = row["think"]
    if is_runtime_think_copy_id(think):
        continue
    plc = row["placement"]
    sw = str(slot.get("walk_route") or "").strip()
    from whitelist_slot_receptor import classify_receptor_bucket

    bucket = classify_receptor_bucket(slot)
    tail = think % 10000
    if bucket == "ground_stand" and not sw and plc in GROUND and 100 <= tail < 200:
        key = f"ground_01xx_{row['model']}"
        still[key] += 1
        if sim_think != think:
            fix["would_align"] += 1
        else:
            fix["still_01xx"] += 1

print("=== replay static 01xx heuristic on seed table ===")
for k, v in sorted(still.items(), key=lambda x: (-x[1], x[0])):
    print(f"{k}: {v}")
print("align:", dict(fix))
