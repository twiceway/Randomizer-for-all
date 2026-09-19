"""Compare think pipeline on two spawn maps."""
from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from donor_msb_compat import compat_entry_for_template, load_donor_slot_compat
from donor_vanilla_states import build_model_vanilla_state_index, resolve_slot_runtime_npc_and_think
from npc_think_sanitize import is_runtime_think_copy_id, think_matches_model_family


def audit(path: Path) -> None:
    slots = json.loads((SCRIPT_DIR / "cache" / "enemy_index.json").read_text(encoding="utf-8"))["slots"]
    slot_by = {(s["map_id"], s["name"]): s for s in slots}
    with gzip.open(SCRIPT_DIR / "cache" / "enemy_slot_prep.json.gz", "rt", encoding="utf-8") as fh:
        prep = json.load(fh)
    donor_by = {str(d["template_id"]): d for d in prep["donors"]}
    compat = load_donor_slot_compat()
    cats = json.loads((SCRIPT_DIR / "enemy_categories.json").read_text(encoding="utf-8"))
    mi = build_model_vanilla_state_index(slots)

    rows = ff = bw = sim = t059 = 0
    samples: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("m"):
            continue
        c = line.split("\t")
        rows += 1
        think = int(c[7])
        model = c[5]
        plc = c[13] if len(c) > 13 else ""
        if is_runtime_think_copy_id(think):
            t059 += 1
            continue
        if not think_matches_model_family(model, think):
            ff += 1
        if model == "c3180" and 3_180_010_0 <= think < 3_180_020_0 and plc in {"ground", "collision_anchor"}:
            bw += 1
        slot = slot_by.get((c[0], c[1]))
        tpl = donor_by.get(c[4].split("|", 1)[0])
        if not slot or not tpl:
            continue
        ce = compat_entry_for_template(c[4].split("|", 1)[0], compat) or {}
        template = {
            **tpl,
            "template_id": c[4].split("|", 1)[0],
            "model": model,
            "think": ce.get("donor_think") or tpl.get("think"),
            "npc": ce.get("donor_npc") or tpl.get("npc"),
            "walk_route": ce.get("donor_walk_route") or tpl.get("walk_route") or "",
        }
        _, st = resolve_slot_runtime_npc_and_think(slot, template, int(c[6]), cats, mi)
        if st != think:
            sim += 1
            if len(samples) < 8:
                samples.append(f"{c[0]}:{c[1]} spawn={think} sim={st} tpl={c[4].split('|',1)[0]}")

    print(f"=== {path.name} ===")
    print(f"rows={rows} t059={t059} family_fail={ff} boss_wolf_ground={bw} sim_mismatch={sim}")
    for s in samples:
        print(f"  {s}")


if __name__ == "__main__":
    old = SCRIPT_DIR / "output" / "runtime" / "cnv_enemy_spawn_map.txt"
    fresh = SCRIPT_DIR / "output" / "runtime" / "_think_audit" / "cnv_enemy_spawn_map.txt"
    audit(old)
    if fresh.is_file():
        audit(fresh)
