"""Apply-time Radahn meteor landing: patch emevd.js (428-style event helper).

Reads ``cnv_radahn_landing.json`` from the MSB overlay dir. Appends Restart events that
wait for meteor fly SpEffects (13947/13907/13906), warp the boss to the player, and play
landing anim 3037.

Many overworld / evergaol bosses live in ``common.emevd.dcx.js``, not ``{map_id}.emevd``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from paths import GAME_DIR, SCRIPT_DIR

MARKER_START = "// ==CNV_RADAHN_LANDING=="
MARKER_END = "// ==/CNV_RADAHN_LANDING=="
EVENT0_MARKER_START = "    // ==CNV_RADAHN_EVENT0=="
EVENT0_MARKER_END = "    // ==/CNV_RADAHN_EVENT0=="
EVENT0_HOOK = "$Event(0, Default, function() {"

# Log truth (v8.9.20): roadside evergaol fires 13907/13947, not 13906.
LANDING_SPEFFECTS = (13947, 13907, 13906)
LANDING_ANIM = 3037
EVENT_ID_SCAN_START = 5000
EVENT_ID_SCAN_STEP = 13

_ENTITY_INDEX: dict[tuple[str, str], int] | None = None


def _event_dir(game_dir: Path | None = None) -> Path:
    return (game_dir or GAME_DIR) / "mod" / "event"


def _load_entity_index() -> dict[tuple[str, str], int]:
    global _ENTITY_INDEX
    if _ENTITY_INDEX is not None:
        return _ENTITY_INDEX
    index_path = SCRIPT_DIR / "cache" / "enemy_index.json"
    lookup: dict[tuple[str, str], int] = {}
    if not index_path.is_file():
        _ENTITY_INDEX = lookup
        return lookup
    data = json.loads(index_path.read_text(encoding="utf-8-sig"))
    for slot in data.get("slots", []):
        if not isinstance(slot, dict):
            continue
        map_id = str(slot.get("map_id") or "")
        name = str(slot.get("name") or "")
        entity_id = int(slot.get("entity_id") or 0)
        if map_id and name and entity_id > 0:
            lookup[(map_id, name)] = entity_id
    _ENTITY_INDEX = lookup
    return lookup


def _normalize_record(raw: dict[str, Any]) -> dict[str, Any]:
    map_id = str(raw.get("map_id") or raw.get("MapId") or "")
    entity_name = str(raw.get("entity_name") or raw.get("EntityName") or "")
    boss_entity_id = int(raw.get("boss_entity_id") or raw.get("BossEntityId") or 0)
    helper_entity_id = int(raw.get("helper_entity_id") or raw.get("HelperEntityId") or 0)
    if boss_entity_id <= 0 and map_id and entity_name:
        boss_entity_id = _load_entity_index().get((map_id, entity_name), 0)
    return {
        "map_id": map_id,
        "entity_name": entity_name,
        "boss_entity_id": boss_entity_id,
        "helper_entity_id": helper_entity_id,
    }


def _event_exists(event_text: str, event_id: int) -> bool:
    return f"$Event({event_id}," in event_text


def _allocate_landing_event_id(event_text: str, boss_entity_id: int) -> int:
    boss = int(boss_entity_id)
    for offset in range(EVENT_ID_SCAN_START, 900_000, EVENT_ID_SCAN_STEP):
        landing = boss + offset + 10
        if not _event_exists(event_text, landing):
            return landing
    raise RuntimeError(f"no free emevd landing event id near boss={boss_entity_id}")


def _landing_wait_expr(boss: int) -> str:
    parts = [f"CharacterHasSpEffect({boss}, {fx})" for fx in LANDING_SPEFFECTS]
    return " || ".join(parts)


def _build_landing_block(rec: dict[str, Any], event_text: str) -> tuple[str, int]:
    boss = int(rec["boss_entity_id"])
    helper = int(rec["helper_entity_id"])
    landing = _allocate_landing_event_id(event_text, boss)
    entity_name = str(rec.get("entity_name") or "")
    wait_expr = _landing_wait_expr(boss)

    block = f"""{MARKER_START}
// map={rec.get("map_id")} entity={entity_name} boss={boss} helper={helper} event={landing}

$Event({landing}, Restart, function() {{
    EndIf(CharacterDead({boss}));
    WaitFor(PlayerIsInOwnWorld() && ({wait_expr}));
    DisableCharacterAI({boss});
    DisableCharacter({boss});
    DisableCharacterCollision({boss});
    SetSpEffect({boss}, 13918);
    WaitFixedTimeSeconds(3);
    WarpCharacterAndCopyFloor({boss}, TargetEntityType.Character, 10000, 235, 10000);
    EnableCharacter({boss});
    EnableCharacterCollision({boss});
    EnableCharacterAI({boss});
    ForceAnimationPlayback({boss}, {LANDING_ANIM}, false, false, false);
    WaitFixedTimeSeconds(1);
    RestartEvent();
}});

{MARKER_END}
"""
    return block, landing


def _strip_event0_inits(text: str) -> str:
    if EVENT0_MARKER_START not in text:
        return text
    pattern = re.compile(
        r"\n?" + re.escape(EVENT0_MARKER_START) + r"[\s\S]*?" + re.escape(EVENT0_MARKER_END) + r"\n?",
    )
    return pattern.sub("\n", text)


def _inject_event0_inits(text: str, landing_ids: list[int]) -> str:
    text = _strip_event0_inits(text)
    if not landing_ids or EVENT0_HOOK not in text:
        return text
    lines = [EVENT0_MARKER_START]
    for landing in landing_ids:
        lines.append(f"    InitializeEvent(0, {landing}, 0);")
    lines.append(EVENT0_MARKER_END)
    block = "\n" + "\n".join(lines) + "\n"
    return text.replace(EVENT0_HOOK, EVENT0_HOOK + block, 1)


def _strip_existing_block(text: str) -> str:
    if MARKER_START not in text:
        return text
    pattern = re.compile(
        re.escape(MARKER_START) + r"[\s\S]*?" + re.escape(MARKER_END) + r"\n?",
    )
    return pattern.sub("", text)


def resolve_event_paths(
    rec: dict[str, Any],
    *,
    game_dir: Path | None = None,
) -> list[Path]:
    event_dir = _event_dir(game_dir)
    map_id = str(rec.get("map_id") or "")
    boss = int(rec.get("boss_entity_id") or 0)
    paths: list[Path] = []

    map_path = event_dir / f"{map_id}.emevd.dcx.js"
    common_path = event_dir / "common.emevd.dcx.js"

    if boss > 0 and common_path.is_file():
        common_text = common_path.read_text(encoding="utf-8", errors="replace")
        if str(boss) in common_text:
            paths.append(common_path)

    if map_path.is_file() and map_path not in paths:
        paths.append(map_path)

    if paths:
        return paths

    if map_path.is_file():
        return [map_path]
    if common_path.is_file():
        return [common_path]
    raise FileNotFoundError(f"no emevd target for map={map_id} boss={boss}")


def patch_event_file_at(
    event_path: Path,
    records: list[dict[str, Any]],
    *,
    dry_run: bool = False,
) -> Path:
    if not records:
        return event_path
    text = _strip_existing_block(event_path.read_text(encoding="utf-8", errors="replace"))
    landing_ids: list[int] = []
    for rec in records:
        block, landing = _build_landing_block(rec, text)
        landing_ids.append(landing)
        if not text.endswith("\n"):
            text += "\n"
        text += "\n" + block
    text = _inject_event0_inits(text, landing_ids)
    if not dry_run:
        event_path.write_text(text, encoding="utf-8")
    return event_path


def load_landing_manifest(manifest_path: Path) -> list[dict[str, Any]]:
    if not manifest_path.is_file():
        return []
    data = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, list):
        return []
    out: list[dict[str, Any]] = []
    for raw in data:
        if not isinstance(raw, dict):
            continue
        rec = _normalize_record(raw)
        if rec["boss_entity_id"] > 0:
            out.append(rec)
    return out


def _strip_all_cnv_blocks(event_dir: Path) -> int:
    stripped = 0
    for path in sorted(event_dir.glob("*.emevd.dcx.js")):
        text = path.read_text(encoding="utf-8", errors="replace")
        if MARKER_START not in text:
            continue
        path.write_text(_strip_event0_inits(_strip_existing_block(text)), encoding="utf-8")
        stripped += 1
    return stripped


def inject_radahn_landing_events(
    manifest_path: Path,
    *,
    game_dir: Path | None = None,
    map_filter: str | None = None,
    dry_run: bool = False,
) -> list[Path]:
    records = load_landing_manifest(manifest_path)
    if map_filter:
        records = [r for r in records if str(r.get("map_id")) == map_filter]
    event_dir = _event_dir(game_dir)
    if not dry_run:
        _strip_all_cnv_blocks(event_dir)
    if not records:
        return []

    by_file: dict[Path, list[dict[str, Any]]] = {}
    for rec in records:
        for path in resolve_event_paths(rec, game_dir=game_dir):
            by_file.setdefault(path, []).append(rec)

    written: list[Path] = []
    for path in sorted(by_file, key=lambda p: str(p)):
        patch_event_file_at(path, by_file[path], dry_run=dry_run)
        written.append(path)
    return written


def summarize_injection(paths: list[Path], records: list[dict[str, Any]]) -> str:
    if not paths:
        skipped = " (all slots missing entity_id?)" if not records else ""
        return f"radahn_landing_inject: no c4730 slots (skipped){skipped}"
    maps = sorted({str(r.get("map_id")) for r in records})
    files = ", ".join(p.name for p in paths)
    return (
        f"radahn_landing_inject: maps={len(maps)} slots={len(records)} "
        f"event_files={len(paths)} [{files}]"
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Inject Radahn meteor landing emevd blocks")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=GAME_DIR / "mod" / "cnv_enemy" / "map" / "MapStudio" / "cnv_radahn_landing.json",
    )
    parser.add_argument("--map-filter", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    paths = inject_radahn_landing_events(
        args.manifest,
        map_filter=args.map_filter,
        dry_run=args.dry_run,
    )
    records = load_landing_manifest(args.manifest)
    if args.map_filter:
        records = [r for r in records if str(r.get("map_id")) == args.map_filter]
    print(summarize_injection(paths, records))
