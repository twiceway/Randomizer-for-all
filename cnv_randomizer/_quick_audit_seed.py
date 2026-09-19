"""Quick high-risk scan for current spawn map."""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from _audit_freeze_pipeline import _parse_rows, freeze_gate_summary
from donor_vanilla_states import (
    build_model_vanilla_state_index,
    vanilla_static_thinks_for_model,
)
from npc_think_sanitize import is_runtime_think_copy_id, think_matches_model_family
from whitelist_slot_receptor import classify_receptor_bucket

spawn = SCRIPT_DIR / "output/runtime/cnv_enemy_spawn_map.txt"
slots = json.loads((SCRIPT_DIR / "cache/enemy_index.json").read_text(encoding="utf-8"))["slots"]
slot_by = {(s["map_id"], s["name"]): s for s in slots}
mi = build_model_vanilla_state_index(slots)
GROUND = {"ground", "collision_anchor"}

gate, gate_total = freeze_gate_summary(spawn)
print(f"seed_line: {[l for l in spawn.read_text(encoding='utf-8').splitlines() if l.startswith('seed=')][0]}")
print(f"rows: {len(_parse_rows(spawn))}")
print(f"freeze_gate_total: {gate_total}")
print(f"freeze_gate: {gate}")

c = Counter()
bad = Counter()
for row in _parse_rows(spawn):
    think = row["think"]
    if is_runtime_think_copy_id(think):
        continue
    slot = slot_by.get((row["map_id"], row["entity"]))
    if not slot:
        continue
    sw = str(slot.get("walk_route") or "").strip()
    bucket = classify_receptor_bucket(slot)
    model = row["model"]
    plc = row["placement"]
    tail = think % 10000
    if model == "c3180" and 3_180_010_0 <= think < 3_180_020_0 and plc in GROUND:
        c["wolf_boss_ground"] += 1
    if model == "c4460" and 44_607_800 <= think < 44_607_900 and plc in GROUND:
        c["chariot_boss_ground"] += 1
    if not think_matches_model_family(model, think):
        c["think_family_fail"] += 1
    if bucket == "ground_stand" and not sw and plc in GROUND:
        vanilla = vanilla_static_thinks_for_model(model, mi)
        if 100 <= tail < 200:
            c[f"static_01xx_{model}"] += 1
            if think not in vanilla:
                bad[f"bad_01xx_{model}"] += 1
        if 900 <= tail < 1000 and think not in vanilla:
            bad[f"bad_09xx_{model}"] += 1

print("pattern_counts:", dict(c))
print("non_vanilla_danger:", dict(bad))
