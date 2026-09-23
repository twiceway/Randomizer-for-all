"""Apply human-NPC night HP path to all c0000 night copies in current soul manifest + regulation."""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from enemy_difficulty import (  # noqa: E402
    is_human_npc_hp_model,
    load_difficulty_cfg,
    rebind_human_npc_sp_effects,
    resolve_human_npc_table_hp,
)
from npc_soul_copies import DEFAULT_NPC_CSV, patch_regulation_npc_copies  # noqa: E402
from paths import OUTPUT_RUNTIME  # noqa: E402


def _load_npc_rows(csv_path: Path) -> dict[int, dict[str, str]]:
    import csv

    out: dict[int, dict[str, str]] = {}
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            try:
                out[int(row["ID"])] = row
            except (TypeError, ValueError, KeyError):
                continue
    return out


def main() -> int:
    spawn = OUTPUT_RUNTIME / "cnv_enemy_spawn_map.txt"
    copies_path = OUTPUT_RUNTIME / "cnv_npc_soul_copies.json"
    if not spawn.is_file() or not copies_path.is_file():
        print("missing spawn or soul copies")
        return 1

    # copy_id -> list of map_ids (night c0000 only)
    by_copy: dict[int, list[str]] = defaultdict(list)
    for line in spawn.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or not line.strip():
            continue
        p = line.split("\t")
        if len(p) < 7 or p[3] != "night":
            continue
        if not is_human_npc_hp_model(p[5]):
            continue
        try:
            cid = int(p[6])
        except ValueError:
            continue
        by_copy[cid].append(p[0])

    sc = json.loads(copies_path.read_text(encoding="utf-8"))
    difficulty = dict(sc.get("difficulty") or {})
    if "user_mult" not in difficulty:
        difficulty["user_mult"] = 0.5
    npc_by_id = _load_npc_rows(DEFAULT_NPC_CSV)
    cfg = load_difficulty_cfg()

    updated = 0
    missing_base = 0
    for c in sc.get("copies") or []:
        try:
            cid = int(c.get("copy_id") or 0)
        except (TypeError, ValueError):
            continue
        if cid not in by_copy:
            continue
        try:
            base = int(c.get("base_npc") or 0)
        except (TypeError, ValueError):
            continue
        donor = npc_by_id.get(base)
        if not donor:
            missing_base += 1
            continue
        map_id = by_copy[cid][0]
        hp = resolve_human_npc_table_hp(donor, difficulty)
        ov = rebind_human_npc_sp_effects(donor, map_id, cfg)
        # keep pure attack override if present and rate==1
        old_ov = dict(c.get("sp_effect_overrides") or {})
        for slot, sp in old_ov.items():
            try:
                sid = int(sp)
            except (TypeError, ValueError):
                continue
            if slot.startswith("spEffect") and 8500 <= sid <= 8599:
                ov[slot] = str(sid)
        # force clear leftover monster NG inject keys if still in old ov
        for slot, sp in list(ov.items()):
            try:
                sid = int(sp)
            except (TypeError, ValueError):
                continue
            if 7400 <= sid <= 7580:
                ov[slot] = "0"
        c["hp"] = hp
        c["donor_eff_hp"] = hp
        c["anchor_eff_hp"] = hp
        c["sp_effect_overrides"] = {str(k): int(v) for k, v in ov.items()}
        c["human_npc_hp_scale"] = True
        updated += 1

    copies_path.write_text(json.dumps(sc, ensure_ascii=False, indent=2), encoding="utf-8")
    dll = Path(r"V:/games/Elden Ring/Game/mod/dll/cnv_npc_soul_copies.json")
    if dll.parent.is_dir():
        dll.write_text(copies_path.read_text(encoding="utf-8"), encoding="utf-8")

    msg = patch_regulation_npc_copies(copies_path)
    print(f"updated_copies={updated} missing_base={missing_base} unique_night_c0000={len(by_copy)}")
    print(msg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
