"""关卡前方 · 四足认外观目录与分批表（每组 14，F6 note 2～15；note1 赐福不写盘）。

目的：真机逐条验 **白名单内四足捐皮** 是否冻住/穿模（用户已审完白名单，试验台不再二次剔名）。
种类真源：``捐皮契约/捐皮白名单_当前.json`` ∩ ``quadruped_slot_model_prefixes``（+ DLC 犬 ``c552*``）。
参数真源：``enemy_index.templates`` + ``pick_best_donor_template``。
写盘槽：F6 标定 ``mark_slot``（``gatefront_marked_slots.json``，note2～15 各 1 张四足皮）。
"""
from __future__ import annotations

import csv
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from paths import SCRIPT_DIR  # frozen-safe
MARKED_SLOTS_PATH = SCRIPT_DIR / "test_lab" / "gatefront_marked_slots.json"
M61_SLOTS = SCRIPT_DIR.parent / "reports" / "_m61_slots.jsonl"
QUAD_CATALOG_CACHE = SCRIPT_DIR / "test_lab" / "gatefront_quad_catalog.json"
QUAD_BATCHES_CACHE = SCRIPT_DIR / "test_lab" / "gatefront_quad_lineup_batches.json"
QUAD_TABLE_PATH = SCRIPT_DIR / "test_lab" / "gatefront_quad_lineup_table.txt"

QUAD_BATCH_SIZE = 14
GRACE_NOTE = 1
GATEFRONT_MAP_ID = "m60_42_37_00"

GRACE_SUPPRESS_SLOT = "c1000_9002"

# 白名单 json 未列入 quadruped_slot_model_prefixes 但属四足犬模（DLC 野狗）
LAB_EXTRA_QUAD_MODEL_PREFIXES: tuple[str, ...] = tuple(f"c552{i}" for i in range(8))


def _categories_path() -> Path:
    return SCRIPT_DIR / "enemy_categories.json"


def _load_categories_cfg() -> dict[str, Any]:
    return json.loads(_categories_path().read_text(encoding="utf-8-sig"))


def _npc_csv_path() -> Path:
    from paths import GAME_DIR

    p = GAME_DIR / "csv" / "NpcParam.csv"
    if p.is_file():
        return p
    raise FileNotFoundError(f"NpcParam.csv not found: {p}")


@lru_cache(maxsize=1)
def load_npc_english_names() -> dict[int, str]:
    out: dict[int, str] = {}
    with _npc_csv_path().open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            try:
                nid = int(row.get("ID") or row.get("id") or 0)
            except (TypeError, ValueError):
                continue
            name = str(row.get("Name") or row.get("name") or "").strip()
            if name:
                out[nid] = name
    return out


def _slug_key(model: str, npc: int, template: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", model.lower()).strip("_")
    map_part = template.split(":", 1)[0].replace("_", "")
    return f"quad_{slug}_{npc}_{map_part}"


def load_gatefront_marked_lineup() -> list[dict[str, Any]]:
    """F6 标定 note 2～15（共 14 条）；note 1 赐福、note≥16 蝙蝠巡逻不进分批表。"""
    if not MARKED_SLOTS_PATH.is_file():
        raise FileNotFoundError(f"missing marked slots: {MARKED_SLOTS_PATH}")
    data = json.loads(MARKED_SLOTS_PATH.read_text(encoding="utf-8-sig"))
    marks = data.get("marks") or []
    out: list[dict[str, Any]] = []
    for row in marks:
        note = int(row.get("note") or 0)
        slot = str(row.get("slot") or "")
        if note <= 0 or not slot:
            continue
        if note == GRACE_NOTE:
            continue
        # note 16+：蝙蝠巡逻等附加槽，只进 init/inject，不占 14 行写盘
        if note > GRACE_NOTE + QUAD_BATCH_SIZE:
            continue
        world = row.get("world_est") or []
        out.append(
            {
                "note": note,
                "slot": slot,
                "world_est": world,
            }
        )
    out.sort(key=lambda r: r["note"])
    if len(out) != QUAD_BATCH_SIZE:
        raise ValueError(
            f"expected {QUAD_BATCH_SIZE} marked notes (F6 note 2～15), got {len(out)}"
        )
    return out


def _is_whitelist_quadruped_model(model: str, categories_cfg: dict[str, Any]) -> bool:
    from enemy_randomizer_core import _model_has_prefix, quadruped_model_prefixes

    model_l = str(model or "").lower()
    prefixes = list(quadruped_model_prefixes(categories_cfg)) + list(
        LAB_EXTRA_QUAD_MODEL_PREFIXES
    )
    return _model_has_prefix(model_l, prefixes)


def _contract_whitelist_path() -> Path:
    from paths import DONOR_POOL_CONTRACT_DIR

    return DONOR_POOL_CONTRACT_DIR / "捐皮白名单_当前.json"


def iter_contract_whitelist_rows() -> list[dict[str, Any]]:
    """捐皮契约白名单 json → 扁平行列表（种类真源，非 enemy_index.slots）。"""
    path = _contract_whitelist_path()
    if not path.is_file():
        raise FileNotFoundError(f"missing contract whitelist: {path}")
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    rows_by_pool = data.get("rows_by_pool") or {}
    out: list[dict[str, Any]] = []
    for pool_rows in rows_by_pool.values():
        if not isinstance(pool_rows, list):
            continue
        for row in pool_rows:
            if isinstance(row, dict):
                out.append(row)
    return out


def _resolve_whitelist_donor_template(
    row: dict[str, Any],
    catalog_templates: list[dict[str, Any]],
    categories_cfg: dict[str, Any],
) -> dict[str, Any] | None:
    from donor_pool_review_allowlist import normalize_category_id
    from enemy_randomizer_core import (
        build_contract_synthetic_donor_template,
        donor_template_chara,
        pick_best_donor_template,
    )

    try:
        npc = int(row.get("npc") or 0)
    except (TypeError, ValueError):
        return None
    model = str(row.get("model") or "").strip().lower()
    if npc <= 0 or not model:
        return None

    best = pick_best_donor_template(npc, model, catalog_templates)
    if best is not None:
        if model == "c0000" and donor_template_chara(best) <= 0:
            return None
        return dict(best)

    cat = normalize_category_id(str(row.get("category") or "trash"))
    return build_contract_synthetic_donor_template(
        cat,
        npc,
        model,
        categories_cfg=categories_cfg,
        catalog=catalog_templates,
    )


def _donor_physique_meta(
    tpl: dict[str, Any],
    categories_cfg: dict[str, Any],
    compat_by_tid: dict[str, dict[str, Any]],
) -> dict[str, str]:
    from donor_msb_compat import compat_entry_for_template
    from enemy_randomizer_core import donor_physique_bucket

    tid = str(tpl.get("template_id") or "")
    entry = compat_entry_for_template(tid, compat_by_tid)
    return {
        "physique_bucket": donor_physique_bucket(tpl, categories_cfg, compat_by_tid),
        "donor_pose_label": str(entry.get("donor_pose_label") or ""),
    }


def appearance_slot_for_idx(idx: int) -> str:
    """idx 1～14 → 循环铺到关卡前方原生四足槽。"""
    from gatefront_dog_catalog import QUADRUPED_LINEUP_SLOTS

    if idx <= 0 or idx > QUAD_BATCH_SIZE:
        raise ValueError(f"idx must be 1..{QUAD_BATCH_SIZE}, got {idx}")
    slots = QUADRUPED_LINEUP_SLOTS
    if not slots:
        raise ValueError("QUADRUPED_LINEUP_SLOTS empty")
    return slots[(idx - 1) % len(slots)]


def build_quadruped_catalog(*, refresh: bool = False) -> dict[str, dict[str, Any]]:
    if not refresh and QUAD_CATALOG_CACHE.is_file():
        try:
            cached = json.loads(QUAD_CATALOG_CACHE.read_text(encoding="utf-8-sig"))
            if (
                cached.get("schema") == "gatefront_quad_catalog_v4"
                and isinstance(cached.get("entries"), dict)
                and cached["entries"]
            ):
                return cached["entries"]
        except (OSError, json.JSONDecodeError):
            pass

    from donor_msb_compat import load_donor_slot_compat
    from enemy_randomizer_core import load_enemy_index

    categories_cfg = _load_categories_cfg()
    compat_by_tid = load_donor_slot_compat()
    names = load_npc_english_names()
    catalog_templates = list(load_enemy_index().get("templates") or [])
    seen_npc: set[int] = set()
    entries: dict[str, dict[str, Any]] = {}

    for row in iter_contract_whitelist_rows():
        try:
            npc = int(row.get("npc") or 0)
        except (TypeError, ValueError):
            continue
        if npc <= 0 or npc in seen_npc:
            continue
        model = str(row.get("model") or "").strip().lower()
        if not model or not _is_whitelist_quadruped_model(model, categories_cfg):
            continue

        tpl = _resolve_whitelist_donor_template(row, catalog_templates, categories_cfg)
        if tpl is None:
            continue

        english = str(row.get("name_en") or "").strip() or names.get(npc, "")
        meta = _donor_physique_meta(tpl, categories_cfg, compat_by_tid)

        seen_npc.add(npc)
        template = str(tpl.get("template_id") or "")
        if not template:
            continue
        think = int(tpl.get("think") or (npc // 100) * 100)
        source_msb = template.split(":", 1)[0] if ":" in template else ""
        key = _slug_key(model, npc, template)
        entries[key] = {
            "key": key,
            "english": english,
            "npc": npc,
            "think": think,
            "model": model,
            "template": template,
            "source_msb": source_msb,
            "whitelist_pool": int(row.get("pool") or 0),
            "whitelist_category": str(row.get("category") or ""),
            "physique_bucket": meta["physique_bucket"],
            "donor_pose_label": meta["donor_pose_label"],
        }

    QUAD_CATALOG_CACHE.parent.mkdir(parents=True, exist_ok=True)
    QUAD_CATALOG_CACHE.write_text(
        json.dumps(
            {
                "schema": "gatefront_quad_catalog_v4",
                "filter": "contract_whitelist_quadruped_model_prefix",
                "purpose": "freeze_probe_whitelist_quadrupeds",
                "whitelist_source": str(_contract_whitelist_path()),
                "batch_size": QUAD_BATCH_SIZE,
                "entries": entries,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return entries


def ordered_quadruped_entries(*, refresh: bool = False) -> list[dict[str, Any]]:
    catalog = build_quadruped_catalog(refresh=refresh)
    return sorted(
        catalog.values(),
        key=lambda e: (str(e["model"]), str(e["english"]), int(e["npc"])),
    )


def quad_batch_count() -> int:
    n = len(ordered_quadruped_entries())
    if not n:
        return 0
    return max(1, (n + QUAD_BATCH_SIZE - 1) // QUAD_BATCH_SIZE)


def build_quad_lineup_batches(*, refresh: bool = False) -> dict[str, Any]:
    if refresh:
        build_quadruped_catalog(refresh=True)

    marked = load_gatefront_marked_lineup()
    ordered = ordered_quadruped_entries(refresh=refresh)
    if not ordered:
        raise ValueError("whitelist quadruped catalog empty")

    batches: list[dict[str, Any]] = []
    for batch_no in range(quad_batch_count()):
        start_offset = batch_no * QUAD_BATCH_SIZE
        rows: list[dict[str, Any]] = []
        for i in range(QUAD_BATCH_SIZE):
            mark = marked[i]
            entry = ordered[(start_offset + i) % len(ordered)]
            idx = i + 1
            write_slot = str(mark["slot"])
            rows.append(
                {
                    "idx": idx,
                    "note": mark["note"],
                    "mark_slot": write_slot,
                    "test_slot": write_slot,
                    "appearance_slot": write_slot,
                    "world_est": mark.get("world_est") or [],
                    "quad_key": entry["key"],
                    "english": entry.get("english") or "",
                    "npc": entry["npc"],
                    "model": entry["model"],
                    "template": entry["template"],
                    "physique_bucket": entry.get("physique_bucket") or "",
                    "donor_pose_label": entry.get("donor_pose_label") or "",
                    "donor_cycle": (start_offset + i) // len(ordered),
                }
            )
        batches.append(
            {
                "batch": batch_no + 1,
                "count": len(rows),
                "rows": rows,
            }
        )

    payload = {
        "schema": "gatefront_quad_lineup_v2",
        "map_id": GATEFRONT_MAP_ID,
        "batch_size": QUAD_BATCH_SIZE,
        "marked_notes": QUAD_BATCH_SIZE,
        "grace_note_excluded": GRACE_NOTE,
        "unique_mark_slots": list(dict.fromkeys(m["slot"] for m in marked)),
        "unique_write_slots": list(dict.fromkeys(m["slot"] for m in marked)),
        "total_quadrupeds": len(ordered),
        "total_batches": len(batches),
        "batches": batches,
    }
    QUAD_BATCHES_CACHE.parent.mkdir(parents=True, exist_ok=True)
    QUAD_BATCHES_CACHE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return payload


def format_quad_lineup_table(payload: dict[str, Any] | None = None) -> str:
    payload = payload or build_quad_lineup_batches()
    lines = [
        "# 关卡前方 · 四足认外观分批表（每组 14 = F6 note 2～15；note1 赐福不写）",
        f"# 捐皮 {payload['total_quadrupeds']} 条 · 共 {payload['total_batches']} 组 · 每组 14 行 = F6 note2～15 → mark_slot",
        f"# 测试槽 note→slot 见 test_lab/gatefront_marked_slots.json",
        "",
        f"{'B':>2} {'#':>2} {'note':>4}  {'write_slot':<14} {'model':<6} {'npc':>10}  {'ENGLISH':<20}  template",
        "-" * 120,
    ]
    for batch in payload.get("batches") or []:
        b = int(batch["batch"])
        for row in batch.get("rows") or []:
            lines.append(
                f"{b:>2} {int(row['idx']):>2} {int(row['note']):>4}  "
                f"{str(row.get('mark_slot') or row['test_slot']):<14} {row['model']:<6} {int(row['npc']):>10}  "
                f"{str(row.get('english') or ''):<20}  {row['template']}"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_quad_lineup_table(*, refresh: bool = False) -> Path:
    payload = build_quad_lineup_batches(refresh=refresh)
    text = format_quad_lineup_table(payload)
    QUAD_TABLE_PATH.write_text(text, encoding="utf-8")
    return QUAD_TABLE_PATH


def build_quad_apply_specs(
    batch: int,
    *,
    vanilla_npc: bool = True,
    write_target: str = "mark_slot",
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """按组生成写盘规格（整组一次写盘）；返回 (slot_specs, batch_rows)。

    write_target:
      - ``mark_slot``（默认）— F6 标定槽，note2～15 各 1 张白名单四足皮
      - ``c4070`` — 遗留：写到原生 ``c4070_*``（非本试验台主路径）
    """
    payload = build_quad_lineup_batches()
    batch_data = next(
        (b for b in payload.get("batches") or [] if int(b.get("batch") or 0) == batch),
        None,
    )
    if not batch_data:
        raise ValueError(f"quad batch {batch} not found (total={payload.get('total_batches')})")

    batch_rows = list(batch_data.get("rows") or [])
    if not batch_rows:
        raise ValueError(f"quad batch {batch}: no rows")

    from gatefront_dog_catalog import GATEFRONT_MARKED_TEST_SLOTS, QUADRUPED_LINEUP_SLOTS

    wt = str(write_target or "mark_slot").strip().lower()
    human_mark = wt in ("mark_slot", "human_mark")
    c4070_legacy = wt in ("quadruped", "c4070")
    if not human_mark and not c4070_legacy:
        raise ValueError(f"write_target must be mark_slot or c4070, got {write_target!r}")

    def _slot_msb_meta(entity_name: str) -> dict[str, Any]:
        from _export_slot_initial_state import apply_slot_class, placement_kind, pose_label
        from enemy_randomizer_core import load_enemy_index

        for slot in load_enemy_index().get("slots") or []:
            if str(slot.get("map_id") or "") != GATEFRONT_MAP_ID:
                continue
            if str(slot.get("name") or "") != entity_name:
                continue
            backup = int(slot.get("backup_anim", -1) or -1)
            return {
                "slot_backup_anim": backup,
                "slot_pose_label": pose_label(slot),
                "slot_apply_class": apply_slot_class(slot),
                "slot_placement_kind": placement_kind(slot),
                "slot_walk_route": str(slot.get("walk_route") or ""),
            }
        return {}

    specs: dict[str, dict[str, Any]] = {}
    slot_conflicts: list[str] = []
    for row in batch_rows:
        slot = str(row["mark_slot"] if human_mark else row["test_slot"])
        if slot in specs and int(specs[slot]["npc"]) != int(row["npc"]):
            slot_conflicts.append(
                f"{slot}: idx {specs[slot]['idx']} vs {row['idx']}"
            )
        spec: dict[str, Any] = {
            "label": str(row.get("english") or row.get("model") or ""),
            "template": str(row["template"]),
            "npc": int(row["npc"]),
            "think": int(row["npc"]) // 100 * 100,
            "model": str(row["model"]),
            "vanilla_npc": vanilla_npc,
            "quad_key": str(row.get("quad_key") or ""),
            "note": int(row["note"]),
            "idx": int(row["idx"]),
            "mark_slot": str(row.get("mark_slot") or ""),
            "quad_write_slot": str(row.get("test_slot") or ""),
            "physique_bucket": str(row.get("physique_bucket") or ""),
            "donor_pose_label": str(row.get("donor_pose_label") or ""),
            "write_target": "mark_slot" if human_mark else "c4070",
        }
        spec.update(_slot_msb_meta(slot))
        specs[slot] = spec

    specs[GRACE_SUPPRESS_SLOT] = {"suppress": True}
    if not human_mark:
        for slot in GATEFRONT_MARKED_TEST_SLOTS:
            if slot != GRACE_SUPPRESS_SLOT:
                specs[slot] = {"suppress": True}

    if slot_conflicts:
        import warnings

        warnings.warn(
            "同槽多捐皮，后者覆盖（"
            + ("人形 mark 槽" if human_mark else "四足槽 9 个循环")
            + "）: "
            + "; ".join(slot_conflicts),
            stacklevel=2,
        )

    return specs, batch_rows


def format_quad_batch_summary() -> str:
    payload = build_quad_lineup_batches()
    lines = [
        f"四足目录 {payload['total_quadrupeds']} 条 · {payload['total_batches']} 组 × {QUAD_BATCH_SIZE}",
        f"测试 note 2～15 共 {payload['marked_notes']} 个（赐福 note{GRACE_NOTE} 不写 · 一次写盘 14 捐皮）",
        "",
    ]
    for batch in payload["batches"]:
        b = batch["batch"]
        rows = batch["rows"]
        lines.append(
            f"组 {b}: {len(rows)} 条 · npc {rows[0]['npc']}…{rows[-1]['npc']} · "
            f"首槽 {rows[0]['test_slot']}"
        )
    lines.append("")
    lines.append(f"全文 -> {QUAD_TABLE_PATH}")
    return "\n".join(lines)
