"""离线敌人槽位全量表（T-077）— 后台扫 MSB 生成；主程序只读本表。

真源路径:
  cache/offline/enemy_slot_table.json
  reports/敌人槽位全量表.csv
  cache/offline/enemy_slot_table_animals.json  （小动物备用，主程序不读）
  reports/敌人槽位小动物备用表.csv
  cache/offline/enemy_slot_table_npc.json
  reports/敌人槽位NPC备用表.csv
  cache/offline/enemy_slot_table_decorative.json
  reports/敌人槽位装饰备用表.csv
  cache/offline/enemy_slot_table_other_skip.json
  reports/敌人槽位其他跳过备用表.csv
"""
from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from paths import CACHE_DIR, GAME_DIR, OUTPUT_REPORTS

from paths import SCRIPT_DIR  # frozen-safe (data/cnv_randomizer)
OFFLINE_DIR = CACHE_DIR / "offline"
RAW_INDEX_PATH = OFFLINE_DIR / "enemy_index.raw.json"
ENRICHED_SNAPSHOT_PATH = OFFLINE_DIR / "enemy_index.enriched.json"
TABLE_JSON_PATH = OFFLINE_DIR / "enemy_slot_table.json"
TABLE_ANIMAL_JSON_PATH = OFFLINE_DIR / "enemy_slot_table_animals.json"
TABLE_NPC_JSON_PATH = OFFLINE_DIR / "enemy_slot_table_npc.json"
TABLE_DECORATIVE_JSON_PATH = OFFLINE_DIR / "enemy_slot_table_decorative.json"
TABLE_OTHER_SKIP_JSON_PATH = OFFLINE_DIR / "enemy_slot_table_other_skip.json"
TABLE_META_PATH = OFFLINE_DIR / "enemy_slot_table.meta.json"
TABLE_CSV_PATH = OUTPUT_REPORTS / "敌人槽位全量表.csv"
TABLE_ANIMAL_CSV_PATH = OUTPUT_REPORTS / "敌人槽位小动物备用表.csv"
TABLE_NPC_CSV_PATH = OUTPUT_REPORTS / "敌人槽位NPC备用表.csv"
TABLE_DECORATIVE_CSV_PATH = OUTPUT_REPORTS / "敌人槽位装饰备用表.csv"
TABLE_OTHER_SKIP_CSV_PATH = OUTPUT_REPORTS / "敌人槽位其他跳过备用表.csv"
DEFAULT_CATEGORIES_PATH = SCRIPT_DIR / "enemy_categories.json"

EXCLUDED_BUCKET_ORDER = ("animal", "decorative", "npc", "other_skip")

EXCLUDED_BUCKET_PATHS: dict[str, tuple[Path, Path]] = {
    "animal": (TABLE_ANIMAL_JSON_PATH, TABLE_ANIMAL_CSV_PATH),
    "npc": (TABLE_NPC_JSON_PATH, TABLE_NPC_CSV_PATH),
    "decorative": (TABLE_DECORATIVE_JSON_PATH, TABLE_DECORATIVE_CSV_PATH),
    "other_skip": (TABLE_OTHER_SKIP_JSON_PATH, TABLE_OTHER_SKIP_CSV_PATH),
}

EXCLUDED_BUCKET_ROLES: dict[str, str] = {
    "animal": "passive_animal_backup",
    "npc": "npc_skip_backup",
    "decorative": "decorative_suppress_backup",
    "other_skip": "other_skip_backup",
}

TABLE_SCHEMA = "enemy_slot_table_v1"

TABLE_COLUMNS = [
    "map_id",
    "entity",
    "template_id",
    "model",
    "src_cat",
    "size_tier",
    "map_kind",
    "placement_kind",
    "physique_bucket",
    "apply_class",
    "policy",
    "slot_role",
    "participate",
    "skip_rules",
    "effective_skip",
    "walk_route",
    "walk_route_valid",
    "backup_anim",
    "collision_part",
    "npc",
    "think",
    "chara",
    "entity_id",
    "chr_activate",
    "talk_id",
    "platoon_id",
    "unk_t15",
    "rot_x",
    "rot_y",
    "rot_z",
    "entity_groups",
    "sp_effect_set",
    "pos_x",
    "pos_y",
    "pos_z",
    "is_zero_npc",
    "siege_mount_rider",
    "siege_mount_weapon",
]


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def table_fingerprint(table: dict[str, Any]) -> str:
    digest = hashlib.sha256(
        json.dumps(table.get("rows") or [], ensure_ascii=False, sort_keys=True).encode(
            "utf-8"
        )
    ).hexdigest()[:16]
    return digest


def load_enemy_slot_table(path: Path | None = None) -> dict[str, Any]:
    """主程序只读入口（表不存在则抛 FileNotFoundError）。"""
    path = Path(path or TABLE_JSON_PATH)
    if not path.is_file():
        raise FileNotFoundError(
            f"缺少离线槽位表：{path} — 请先运行 scan_enemy_slot_table.py"
        )
    return _load_json(path)


def is_animal_slot_row(
    row: dict[str, Any], categories_cfg: dict[str, Any] | None = None
) -> bool:
    """被动小动物槽（鹿/羊/鹰等）；与运行时 passive_animal 口径一致。"""
    import enemy_randomizer_core as core

    cfg = categories_cfg or core._load_json(DEFAULT_CATEGORIES_PATH)
    model = str(row.get("model") or "")
    if core.is_passive_animal_model(model, cfg):
        return True
    return str(row.get("slot_role") or "") == "ambient_animal"


def _row_to_slot(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "map_id": str(row.get("map_id") or ""),
        "name": str(row.get("entity") or ""),
        "model": str(row.get("model") or ""),
        "npc": int(row.get("npc", 0) or 0),
        "think": int(row.get("think", 0) or 0),
        "talk_id": int(row.get("talk_id", 0) or 0),
    }


def classify_excluded_slot_bucket(
    row: dict[str, Any],
    categories_cfg: dict[str, Any],
    *,
    npc_csv_dir: Path | None = None,
) -> str | None:
    """主表之外的备用桶；顺序：小动物 → 装饰 → NPC契约跳过 → 其他跳过。"""
    import enemy_randomizer_core as core

    if is_animal_slot_row(row, categories_cfg):
        return "animal"

    base = npc_csv_dir or (GAME_DIR / "csv")
    if core.is_decorative_suppress_slot(
        _row_to_slot(row), categories_cfg, base
    ):
        return "decorative"

    eff = str(row.get("effective_skip") or "")
    if eff in ("npc", "hub", "siege"):
        return "npc"

    participate = row.get("participate")
    if participate is False or str(participate).lower() == "false":
        return "other_skip"

    return None


def split_main_and_excluded_rows(
    rows: list[dict[str, Any]],
    categories_cfg: dict[str, Any],
    *,
    npc_csv_dir: Path | None = None,
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    main_rows: list[dict[str, Any]] = []
    excluded: dict[str, list[dict[str, Any]]] = {
        bucket: [] for bucket in EXCLUDED_BUCKET_ORDER
    }
    for row in rows:
        bucket = classify_excluded_slot_bucket(
            row, categories_cfg, npc_csv_dir=npc_csv_dir
        )
        if bucket is None:
            main_rows.append(row)
        else:
            excluded[bucket].append(row)
    return main_rows, excluded


def _write_csv_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=TABLE_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _run_msb_index_export(
    raw_path: Path,
    *,
    max_maps: int | None = None,
    include_zero_npc: bool = True,
) -> None:
    from enemy_randomizer_core import _ensure_msb_poc_built

    raw_path.parent.mkdir(parents=True, exist_ok=True)
    exe = _ensure_msb_poc_built()
    cmd = [
        str(exe),
        "index-export",
        f"--out={raw_path}",
        f"--game={GAME_DIR}",
    ]
    if max_maps is not None:
        cmd.append(f"--max-maps={max_maps}")
    if include_zero_npc:
        cmd.append("--include-zero-npc")

    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(
            "index-export failed:\n" + (proc.stderr or proc.stdout or "(no output)")
        )


def build_table_rows_from_index(
    index: dict[str, Any],
    categories_cfg: dict[str, Any],
    *,
    map_filter: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    import enemy_randomizer_core as core

    routes_by_map: dict[str, list[str]] = {
        str(k): [str(x) for x in (v or [])]
        for k, v in (index.get("routes_by_map") or {}).items()
    }
    npc_csv_dir = core.GAME_DIR / "csv"
    rows: list[dict[str, Any]] = []

    for slot in index.get("slots", []):
        map_id = str(slot.get("map_id", ""))
        if map_filter and map_id != map_filter:
            continue
        entity = str(slot.get("name", ""))
        walk = str(slot.get("walk_route") or "").strip()
        map_routes = routes_by_map.get(map_id, [])
        walk_valid = bool(walk and walk in map_routes)
        pol = core.describe_slot_policy(
            slot,
            categories_cfg,
            npc_csv_dir=npc_csv_dir,
        )
        placement = core._slot_placement_kind(slot)
        physique = core.slot_physique_bucket(slot, categories_cfg)
        from _export_slot_initial_state import apply_slot_class

        apply_class = apply_slot_class(slot)
        rule_ids = core.collect_slot_skip_rule_ids(
            slot, categories_cfg, npc_csv_dir=npc_csv_dir
        )
        tags = slot.get("slot_tags") or {}
        groups = slot.get("entity_groups") or []
        spfx = slot.get("sp_effect_set") or []
        rows.append(
            {
                "map_id": map_id,
                "entity": entity,
                "template_id": f"{map_id}:{entity}",
                "model": str(slot.get("model", "")),
                "src_cat": pol.get("src_cat", ""),
                "size_tier": str(tags.get("size_tier") or ""),
                "map_kind": str(tags.get("map_kind") or pol.get("map_kind") or ""),
                "placement_kind": placement,
                "physique_bucket": physique,
                "apply_class": apply_class,
                "policy": pol.get("policy", ""),
                "slot_role": pol.get("slot_role", ""),
                "participate": pol.get("policy") == "participate",
                "skip_rules": ",".join(rule_ids),
                "effective_skip": pol.get("effective_skip") or "",
                "walk_route": walk,
                "walk_route_valid": walk_valid,
                "backup_anim": int(slot.get("backup_anim", -1) or -1),
                "collision_part": str(slot.get("collision_part") or ""),
                "npc": int(slot.get("npc", 0) or 0),
                "think": int(slot.get("think", 0) or 0),
                "chara": int(
                    slot.get("chara", -1) if slot.get("chara") is not None else -1
                ),
                "entity_id": int(slot.get("entity_id", 0) or 0),
                "chr_activate": int(slot.get("chr_activate", 0) or 0),
                "talk_id": int(slot.get("talk_id", 0) or 0),
                "platoon_id": int(slot.get("platoon_id", 0) or 0),
                "unk_t15": bool(slot.get("unk_t15", False)),
                "rot_x": float(slot.get("rot_x", 0) or 0),
                "rot_y": float(slot.get("rot_y", 0) or 0),
                "rot_z": float(slot.get("rot_z", 0) or 0),
                "entity_groups": ",".join(str(g) for g in groups),
                "sp_effect_set": ",".join(str(x) for x in spfx),
                "pos_x": float(slot.get("pos_x", 0) or 0),
                "pos_y": float(slot.get("pos_y", 0) or 0),
                "pos_z": float(slot.get("pos_z", 0) or 0),
                "is_zero_npc": bool(slot.get("is_zero_npc")),
                "siege_mount_rider": bool(slot.get("siege_mount_rider")),
                "siege_mount_weapon": str(slot.get("siege_mount_weapon") or ""),
            }
        )
    return rows, routes_by_map


def write_enemy_slot_table(
    index: dict[str, Any],
    categories_cfg: dict[str, Any],
    *,
    map_filter: str | None = None,
    raw_index_path: Path | None = None,
) -> dict[str, Path]:
    rows, routes_by_map = build_table_rows_from_index(
        index, categories_cfg, map_filter=map_filter
    )
    main_rows, excluded = split_main_and_excluded_rows(
        rows, categories_cfg, npc_csv_dir=GAME_DIR / "csv"
    )
    generated = datetime.now(timezone.utc).isoformat()
    placement_counts = Counter(str(r.get("placement_kind")) for r in main_rows)
    policy_counts = Counter(str(r.get("policy")) for r in main_rows)
    invalid_walk = sum(
        1
        for r in main_rows
        if r.get("walk_route") and not r.get("walk_route_valid")
    )
    participate = sum(1 for r in main_rows if r.get("participate"))
    excluded_counts = {k: len(v) for k, v in excluded.items()}

    payload = {
        "schema": TABLE_SCHEMA,
        "generated_at": generated,
        "source_raw_index": str(raw_index_path or RAW_INDEX_PATH),
        "index_schema": index.get("schema"),
        "maps_scanned": index.get("maps_scanned"),
        "maps_skipped": index.get("maps_skipped", 0),
        "zero_npc_slots_skipped": index.get("zero_npc_slots_skipped", 0),
        "slot_count": len(main_rows),
        "excluded_slot_counts": excluded_counts,
        "participate_count": participate,
        "walk_route_invalid_count": invalid_walk,
        "routes_by_map": routes_by_map,
        "rows": main_rows,
    }
    fp = table_fingerprint(payload)

    OFFLINE_DIR.mkdir(parents=True, exist_ok=True)
    TABLE_JSON_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    for bucket, bucket_rows in excluded.items():
        json_path, csv_path = EXCLUDED_BUCKET_PATHS[bucket]
        backup_payload = {
            "schema": TABLE_SCHEMA,
            "generated_at": generated,
            "source_raw_index": str(raw_index_path or RAW_INDEX_PATH),
            "role": EXCLUDED_BUCKET_ROLES[bucket],
            "slot_count": len(bucket_rows),
            "rows": bucket_rows,
        }
        json_path.write_text(
            json.dumps(backup_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        _write_csv_rows(csv_path, bucket_rows)

    meta = {
        "schema": TABLE_SCHEMA,
        "generated_at": generated,
        "fingerprint": fp,
        "maps_scanned": index.get("maps_scanned"),
        "slot_count": len(main_rows),
        "excluded_slot_counts": excluded_counts,
        "participate_count": participate,
        "walk_route_invalid_count": invalid_walk,
        "placement_kind_counts": dict(placement_counts),
        "policy_counts": dict(policy_counts),
        "table_json": str(TABLE_JSON_PATH),
        "table_csv": str(TABLE_CSV_PATH),
        "excluded_tables": {
            bucket: {
                "json": str(EXCLUDED_BUCKET_PATHS[bucket][0]),
                "csv": str(EXCLUDED_BUCKET_PATHS[bucket][1]),
                "slot_count": excluded_counts[bucket],
            }
            for bucket in EXCLUDED_BUCKET_ORDER
        },
    }
    TABLE_META_PATH.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    _write_csv_rows(TABLE_CSV_PATH, main_rows)

    paths: dict[str, Path] = {
        "json": TABLE_JSON_PATH,
        "meta": TABLE_META_PATH,
        "csv": TABLE_CSV_PATH,
    }
    for bucket in EXCLUDED_BUCKET_ORDER:
        json_path, csv_path = EXCLUDED_BUCKET_PATHS[bucket]
        paths[f"{bucket}_json"] = json_path
        paths[f"{bucket}_csv"] = csv_path
    return paths


def build_offline_enemy_slot_table(
    *,
    rescan: bool = True,
    max_maps: int | None = None,
    include_zero_npc: bool = True,
    map_filter: str | None = None,
    write_enriched_snapshot: bool = True,
) -> dict[str, Any]:
    """后台全链路：MSB 扫描 → enrich → 离线表（不写入主程序 runtime 索引）。"""
    import enemy_randomizer_core as core

    categories_cfg = core._load_json(DEFAULT_CATEGORIES_PATH)

    if rescan:
        _run_msb_index_export(
            RAW_INDEX_PATH,
            max_maps=max_maps,
            include_zero_npc=include_zero_npc,
        )

    if not RAW_INDEX_PATH.is_file():
        raise FileNotFoundError(f"扫描产物不存在: {RAW_INDEX_PATH}")

    raw = _load_json(RAW_INDEX_PATH)
    enriched = core.enrich_index(raw, categories_cfg, full=True)

    if write_enriched_snapshot:
        ENRICHED_SNAPSHOT_PATH.write_text(
            json.dumps(enriched, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    paths = write_enemy_slot_table(
        enriched,
        categories_cfg,
        map_filter=map_filter,
        raw_index_path=RAW_INDEX_PATH,
    )
    return {
        "paths": paths,
        "maps_scanned": enriched.get("maps_scanned"),
        "slot_count": len(enriched.get("slots") or []),
        "table_rows": len(_load_json(paths["json"]).get("rows") or []),
        "fingerprint": _load_json(paths["meta"]).get("fingerprint"),
    }
