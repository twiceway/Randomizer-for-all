"""Export vanilla MSB slot positions for enemy debug HUD (cnv_enemy_debug_slots.txt)."""
from __future__ import annotations

import json
from pathlib import Path

from paths import SCRIPT_DIR  # frozen-safe
INDEX = SCRIPT_DIR / "cache" / "enemy_index.json"
OUT = SCRIPT_DIR / "cache" / "cnv_enemy_debug_slots.txt"


def main() -> int:
    if not INDEX.is_file():
        print(f"ERROR: missing {INDEX} — run enemy index scan first")
        return 1
    data = json.loads(INDEX.read_text(encoding="utf-8"))
    slots = data.get("slots") or []
    lines = [
        "# map_id\tentity_name\tpos_x\tpos_y\tpos_z\tmodel\tnpc",
        "# vanilla MSB positions for F6/F7 nearest-slot resolve",
    ]
    seen: set[tuple[str, str]] = set()
    count = 0
    for slot in slots:
        map_id = str(slot.get("map_id") or "").strip()
        name = str(slot.get("name") or "").strip()
        if not map_id or not name:
            continue
        key = (map_id, name)
        if key in seen:
            continue
        seen.add(key)
        try:
            px = float(slot.get("pos_x", 0) or 0)
            py = float(slot.get("pos_y", 0) or 0)
            pz = float(slot.get("pos_z", 0) or 0)
        except (TypeError, ValueError):
            continue
        model = str(slot.get("model") or "")
        npc = int(slot.get("npc") or 0)
        lines.append(
            f"{map_id}\t{name}\t{px:.3f}\t{py:.3f}\t{pz:.3f}\t{model}\t{npc}"
        )
        count += 1
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[export] slots={count} -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
