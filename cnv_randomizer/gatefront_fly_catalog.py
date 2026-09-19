"""关卡前方 · 飞行认外观目录与分批表（每组 17）。

种类真源：``捐皮契约/捐皮白名单_当前.json`` ∩ ``flying_slot_model_prefixes``。
写盘槽：F6 note2～15（14）+ note16～18 蝙蝠巡逻 ``c4200_9000/9001/9002``（3）= 17。
不足 17 种时循环铺满（``donor_cycle`` 标记第几轮）。
飞龙/古龙（c450x/c451x/c4520）不算飞行体态，不进本目录（T-076 2026-08-19）。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from gatefront_dog_catalog import GATEFRONT_BAT_TEST_SLOTS
from gatefront_quad_catalog import (
    GATEFRONT_MAP_ID,
    GRACE_NOTE,
    GRACE_SUPPRESS_SLOT,
    MARKED_SLOTS_PATH,
    QUAD_BATCH_SIZE,
    _contract_whitelist_path,
    _donor_physique_meta,
    _load_categories_cfg,
    _resolve_whitelist_donor_template,
    iter_contract_whitelist_rows,
    load_gatefront_marked_lineup,
    load_npc_english_names,
)

from paths import SCRIPT_DIR  # frozen-safe
FLY_CATALOG_CACHE = SCRIPT_DIR / "test_lab" / "gatefront_fly_catalog.json"
FLY_BATCHES_CACHE = SCRIPT_DIR / "test_lab" / "gatefront_fly_lineup_batches.json"
FLY_TABLE_PATH = SCRIPT_DIR / "test_lab" / "gatefront_fly_lineup_table.txt"

# 14（note2～15）+ 3 蝙蝠巡逻
FLY_BATCH_SIZE = QUAD_BATCH_SIZE + len(GATEFRONT_BAT_TEST_SLOTS)
GIANT_CROW_NPC = 45601050
GIANT_CROW_MODEL_PREFIXES: tuple[str, ...] = ("c4560", "c4561")
CROW_CATALOG_CACHE = SCRIPT_DIR / "test_lab" / "gatefront_crow_catalog.json"


def _slug_key(model: str, npc: int, template: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", model.lower()).strip("_")
    map_part = template.split(":", 1)[0].replace("_", "")
    return f"fly_{slug}_{npc}_{map_part}"


def load_gatefront_fly_write_lineup() -> list[dict[str, Any]]:
    """飞行写盘 17 行：note2～15（14）+ note16～18 蝙蝠巡逻（3）。"""
    base = load_gatefront_marked_lineup()
    if not MARKED_SLOTS_PATH.is_file():
        raise FileNotFoundError(f"missing marked slots: {MARKED_SLOTS_PATH}")
    data = json.loads(MARKED_SLOTS_PATH.read_text(encoding="utf-8-sig"))
    bats: list[dict[str, Any]] = []
    for row in data.get("marks") or []:
        note = int(row.get("note") or 0)
        slot = str(row.get("slot") or "")
        if note <= GRACE_NOTE + QUAD_BATCH_SIZE or not slot:
            continue
        bats.append(
            {
                "note": note,
                "slot": slot,
                "world_est": row.get("world_est") or [],
            }
        )
    bats.sort(key=lambda r: r["note"])
    expected_bats = len(GATEFRONT_BAT_TEST_SLOTS)
    if len(bats) != expected_bats:
        raise ValueError(
            f"expected {expected_bats} bat patrol notes (note≥16), got {len(bats)}"
        )
    for i, slot in enumerate(GATEFRONT_BAT_TEST_SLOTS):
        if bats[i]["slot"] != slot:
            raise ValueError(
                f"bat note order mismatch: expected {slot}, got {bats[i]['slot']}"
            )
    out = base + bats
    if len(out) != FLY_BATCH_SIZE:
        raise ValueError(
            f"expected fly write lineup {FLY_BATCH_SIZE}, got {len(out)}"
        )
    return out


def _is_whitelist_flying_model(model: str, categories_cfg: dict[str, Any]) -> bool:
    from enemy_randomizer_core import _model_has_prefix, flying_model_prefixes

    model_l = str(model or "").lower()
    return _model_has_prefix(model_l, flying_model_prefixes(categories_cfg))


def build_flying_catalog(*, refresh: bool = False) -> dict[str, dict[str, Any]]:
    if not refresh and FLY_CATALOG_CACHE.is_file():
        try:
            cached = json.loads(FLY_CATALOG_CACHE.read_text(encoding="utf-8-sig"))
            if (
                cached.get("schema") == "gatefront_fly_catalog_v1"
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
        if not model or not _is_whitelist_flying_model(model, categories_cfg):
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

    FLY_CATALOG_CACHE.parent.mkdir(parents=True, exist_ok=True)
    FLY_CATALOG_CACHE.write_text(
        json.dumps(
            {
                "schema": "gatefront_fly_catalog_v1",
                "filter": "contract_whitelist_flying_model_prefix",
                "purpose": "freeze_probe_whitelist_flying",
                "whitelist_source": str(_contract_whitelist_path()),
                "batch_size": FLY_BATCH_SIZE,
                "entries": entries,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return entries


def ordered_flying_entries(*, refresh: bool = False) -> list[dict[str, Any]]:
    catalog = build_flying_catalog(refresh=refresh)
    return sorted(
        catalog.values(),
        key=lambda e: (str(e["model"]), str(e["english"]), int(e["npc"])),
    )


def fly_batch_count() -> int:
    n = len(ordered_flying_entries())
    if not n:
        return 0
    return max(1, (n + FLY_BATCH_SIZE - 1) // FLY_BATCH_SIZE)


def build_fly_lineup_batches(*, refresh: bool = False) -> dict[str, Any]:
    if refresh:
        build_flying_catalog(refresh=True)

    write_slots = load_gatefront_fly_write_lineup()
    ordered = ordered_flying_entries(refresh=refresh)
    if not ordered:
        raise ValueError("whitelist flying catalog empty")

    batches: list[dict[str, Any]] = []
    for batch_no in range(fly_batch_count()):
        start_offset = batch_no * FLY_BATCH_SIZE
        rows: list[dict[str, Any]] = []
        for i in range(FLY_BATCH_SIZE):
            mark = write_slots[i]
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
                    "fly_key": entry["key"],
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
        "schema": "gatefront_fly_lineup_v2",
        "map_id": GATEFRONT_MAP_ID,
        "batch_size": FLY_BATCH_SIZE,
        "marked_notes": QUAD_BATCH_SIZE,
        "bat_patrol_slots": list(GATEFRONT_BAT_TEST_SLOTS),
        "grace_note_excluded": GRACE_NOTE,
        "unique_mark_slots": list(dict.fromkeys(m["slot"] for m in write_slots)),
        "unique_write_slots": list(dict.fromkeys(m["slot"] for m in write_slots)),
        "total_flying": len(ordered),
        "total_batches": len(batches),
        "batches": batches,
    }
    FLY_BATCHES_CACHE.parent.mkdir(parents=True, exist_ok=True)
    FLY_BATCHES_CACHE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return payload


def format_fly_lineup_table(payload: dict[str, Any] | None = None) -> str:
    payload = payload or build_fly_lineup_batches()
    lines = [
        "# 关卡前方 · 飞行认外观分批表（每组 17 = note2～15 + 3 蝙蝠巡逻；note1 赐福不写）",
        f"# 捐皮 {payload['total_flying']} 条 · 共 {payload['total_batches']} 组 · 每组 {FLY_BATCH_SIZE} 行",
        f"# 测试槽 note→slot 见 test_lab/gatefront_marked_slots.json",
        "",
        f"{'B':>2} {'#':>2} {'note':>4}  {'write_slot':<14} {'model':<6} {'npc':>10}  {'ENGLISH':<28}  template",
        "-" * 130,
    ]
    for batch in payload.get("batches") or []:
        b = int(batch["batch"])
        for row in batch.get("rows") or []:
            cycle = int(row.get("donor_cycle") or 0)
            cycle_tag = f" ×{cycle + 1}" if cycle else ""
            lines.append(
                f"{b:>2} {int(row['idx']):>2} {int(row['note']):>4}  "
                f"{str(row.get('mark_slot') or row['test_slot']):<14} {row['model']:<6} {int(row['npc']):>10}  "
                f"{str(row.get('english') or '') + cycle_tag:<28}  {row['template']}"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_fly_lineup_table(*, refresh: bool = False) -> Path:
    payload = build_fly_lineup_batches(refresh=refresh)
    text = format_fly_lineup_table(payload)
    FLY_TABLE_PATH.write_text(text, encoding="utf-8")
    return FLY_TABLE_PATH


def _is_giant_crow_model(model: str) -> bool:
    model_l = str(model or "").lower()
    return any(model_l.startswith(pfx) for pfx in GIANT_CROW_MODEL_PREFIXES)


def _pick_crow_template_row(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """同 npc 多出处时优先 :c456 实体名，其次雪原图 m60_51_53。"""
    c456_rows = [r for r in rows if ":c456" in str(r.get("template_id") or "")]
    pool = c456_rows or rows

    def rank(row: dict[str, Any]) -> tuple[int, str]:
        tid = str(row.get("template_id") or "")
        return (
            0 if "m60_51_53" in tid else 1,
            0 if ":c456" in tid else 1,
            tid,
        )

    return sorted(pool, key=rank)[0]


def build_giant_crow_catalog(*, refresh: bool = False) -> dict[str, dict[str, Any]]:
    if not refresh and CROW_CATALOG_CACHE.is_file():
        try:
            cached = json.loads(CROW_CATALOG_CACHE.read_text(encoding="utf-8-sig"))
            if (
                cached.get("schema") == "gatefront_crow_catalog_v1"
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
    by_npc: dict[int, list[dict[str, Any]]] = {}
    for tpl in catalog_templates:
        model = str(tpl.get("model") or "").strip().lower()
        if not _is_giant_crow_model(model):
            continue
        try:
            npc = int(tpl.get("npc") or 0)
        except (TypeError, ValueError):
            continue
        if npc <= 0:
            continue
        by_npc.setdefault(npc, []).append(tpl)

    entries: dict[str, dict[str, Any]] = {}
    for npc in sorted(by_npc):
        tpl = _pick_crow_template_row(by_npc[npc])
        model = str(tpl.get("model") or "").strip().lower()
        template = str(tpl.get("template_id") or "")
        if not template:
            continue
        english = names.get(npc, "")
        meta = _donor_physique_meta(tpl, categories_cfg, compat_by_tid)
        think = int(tpl.get("think") or (npc // 100) * 100)
        source_msb = template.split(":", 1)[0] if ":" in template else ""
        key = _slug_key(model, npc, template).replace("fly_", "crow_", 1)
        entries[key] = {
            "key": key,
            "english": english,
            "npc": npc,
            "think": think,
            "model": model,
            "template": template,
            "source_msb": source_msb,
            "physique_bucket": meta["physique_bucket"],
            "donor_pose_label": meta["donor_pose_label"],
        }

    CROW_CATALOG_CACHE.parent.mkdir(parents=True, exist_ok=True)
    CROW_CATALOG_CACHE.write_text(
        json.dumps(
            {
                "schema": "gatefront_crow_catalog_v1",
                "filter": "enemy_index_c4560_c4561",
                "purpose": "gatefront_crow_lineup_variety",
                "batch_size": FLY_BATCH_SIZE,
                "entries": entries,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return entries


def ordered_giant_crow_entries(*, refresh: bool = False) -> list[dict[str, Any]]:
    catalog = build_giant_crow_catalog(refresh=refresh)
    return sorted(
        catalog.values(),
        key=lambda e: (str(e["model"]), str(e["english"]), int(e["npc"])),
    )


def giant_crow_catalog_entry(*, refresh: bool = False) -> dict[str, Any]:
    for entry in ordered_giant_crow_entries(refresh=refresh):
        if int(entry["npc"]) == GIANT_CROW_NPC:
            return entry
    for entry in ordered_giant_crow_entries(refresh=refresh):
        return entry
    raise ValueError("giant crow catalog empty (no c4560/c4561 in enemy_index)")


def build_crow_lineup_rows(*, refresh: bool = False) -> list[dict[str, Any]]:
    """14 个 F6 mark 槽轮询多种大乌鸦/鸦模（c4560、c4561）。"""
    marked = load_gatefront_marked_lineup()
    ordered = ordered_giant_crow_entries(refresh=refresh)
    if not ordered:
        raise ValueError("giant crow catalog empty")
    rows: list[dict[str, Any]] = []
    for i, mark in enumerate(marked):
        entry = ordered[i % len(ordered)]
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
                "fly_key": entry["key"],
                "english": entry.get("english") or "",
                "npc": entry["npc"],
                "model": entry["model"],
                "template": entry["template"],
                "physique_bucket": entry.get("physique_bucket") or "",
                "donor_pose_label": entry.get("donor_pose_label") or "",
                "donor_cycle": i // len(ordered),
            }
        )
    return rows


def build_uniform_crow_lineup_rows(*, refresh: bool = False) -> list[dict[str, Any]]:
    """兼容旧名；现为多种大乌鸦轮询。"""
    return build_crow_lineup_rows(refresh=refresh)


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


def _gatefront_slot_by_name() -> dict[str, dict[str, Any]]:
    from enemy_randomizer_core import load_enemy_index

    out: dict[str, dict[str, Any]] = {}
    for slot in load_enemy_index().get("slots") or []:
        if str(slot.get("map_id") or "") != GATEFRONT_MAP_ID:
            continue
        name = str(slot.get("name") or "")
        if name:
            out[name] = dict(slot)
    return out


def filter_lineup_rows_slot_compat(
    rows: list[dict[str, Any]],
    *,
    ignore_slot_compat: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """T-080: drop rows whose donor cannot match target mark_slot MSB class."""
    if ignore_slot_compat:
        return rows, []

    from donor_msb_compat import donor_slot_compat_reject_reason, load_donor_slot_compat
    from gatefront_quad_catalog import _load_categories_cfg

    slot_by_name = _gatefront_slot_by_name()
    compat = load_donor_slot_compat()
    categories_cfg = _load_categories_cfg()
    kept: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for row in rows:
        slot_name = str(row.get("mark_slot") or row.get("test_slot") or "")
        slot = slot_by_name.get(slot_name)
        if slot is None:
            kept.append(row)
            continue
        reason = donor_slot_compat_reject_reason(
            slot,
            str(row.get("template") or ""),
            compat,
            categories_cfg=categories_cfg,
        )
        if reason:
            rejected.append({**row, "slot_compat_reject": reason})
            continue
        kept.append(row)
    return kept, rejected


def _build_mark_slot_fly_specs(
    batch_rows: list[dict[str, Any]],
    *,
    vanilla_npc: bool = True,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    specs: dict[str, dict[str, Any]] = {}
    slot_conflicts: list[str] = []
    for row in batch_rows:
        slot = str(row["mark_slot"])
        if slot in specs and int(specs[slot]["npc"]) != int(row["npc"]):
            slot_conflicts.append(f"{slot}: idx {specs[slot]['idx']} vs {row['idx']}")
        spec: dict[str, Any] = {
            "label": str(row.get("english") or row.get("model") or ""),
            "template": str(row["template"]),
            "npc": int(row["npc"]),
            "think": int(row["npc"]) // 100 * 100,
            "model": str(row["model"]),
            "vanilla_npc": vanilla_npc,
            "fly_key": str(row.get("fly_key") or ""),
            "note": int(row["note"]),
            "idx": int(row["idx"]),
            "mark_slot": str(row.get("mark_slot") or ""),
            "fly_write_slot": str(row.get("test_slot") or ""),
            "physique_bucket": str(row.get("physique_bucket") or ""),
            "donor_pose_label": str(row.get("donor_pose_label") or ""),
            "donor_cycle": int(row.get("donor_cycle") or 0),
            "write_target": "mark_slot",
        }
        spec.update(_slot_msb_meta(slot))
        specs[slot] = spec

    specs[GRACE_SUPPRESS_SLOT] = {"suppress": True}

    if slot_conflicts:
        import warnings

        warnings.warn(
            "同槽多捐皮，后者覆盖（人形 mark 槽）: " + "; ".join(slot_conflicts),
            stacklevel=2,
        )

    return specs, batch_rows


def build_crow_apply_specs(
    *,
    vanilla_npc: bool = True,
    ignore_slot_compat: bool = False,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """14 槽多种大乌鸦；默认跳过 T-080 不兼容的巡逻 mark 槽。"""
    rows, rejected = filter_lineup_rows_slot_compat(
        build_crow_lineup_rows(),
        ignore_slot_compat=ignore_slot_compat,
    )
    if rejected:
        import warnings

        for row in rejected:
            warnings.warn(
                f"T-080 skip {row.get('mark_slot')}: {row.get('slot_compat_reject')} "
                f"(npc={row.get('npc')})",
                stacklevel=2,
            )
    return _build_mark_slot_fly_specs(
        rows,
        vanilla_npc=vanilla_npc,
    )


def build_fly_apply_specs(
    batch: int,
    *,
    vanilla_npc: bool = True,
    write_target: str = "mark_slot",
    ignore_slot_compat: bool = False,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    payload = build_fly_lineup_batches()
    batch_data = next(
        (b for b in payload.get("batches") or [] if int(b.get("batch") or 0) == batch),
        None,
    )
    if not batch_data:
        raise ValueError(f"fly batch {batch} not found (total={payload.get('total_batches')})")

    batch_rows = list(batch_data.get("rows") or [])
    if not batch_rows:
        raise ValueError(f"fly batch {batch}: no rows")

    wt = str(write_target or "mark_slot").strip().lower()
    if wt not in ("mark_slot", "human_mark"):
        raise ValueError(f"write_target must be mark_slot, got {write_target!r}")

    batch_rows, rejected = filter_lineup_rows_slot_compat(
        batch_rows,
        ignore_slot_compat=ignore_slot_compat,
    )
    if rejected:
        import warnings

        for row in rejected:
            warnings.warn(
                f"T-080 skip {row.get('mark_slot')}: {row.get('slot_compat_reject')}",
                stacklevel=2,
            )

    return _build_mark_slot_fly_specs(batch_rows, vanilla_npc=vanilla_npc)


def format_fly_batch_summary() -> str:
    payload = build_fly_lineup_batches()
    bat_n = len(payload.get("bat_patrol_slots") or GATEFRONT_BAT_TEST_SLOTS)
    lines = [
        f"飞行目录 {payload['total_flying']} 条 · {payload['total_batches']} 组 × {FLY_BATCH_SIZE}",
        f"写盘 {FLY_BATCH_SIZE} 行 = note2～15（{payload['marked_notes']}）+ 蝙蝠巡逻（{bat_n}）；赐福 note{GRACE_NOTE} 不写",
        "",
    ]
    if payload["total_flying"] < FLY_BATCH_SIZE:
        lines.append(
            f"注：白名单飞行仅 {payload['total_flying']} 种，组内循环铺满 {FLY_BATCH_SIZE} 槽（见 donor_cycle）"
        )
        lines.append("")
    for batch in payload["batches"]:
        b = batch["batch"]
        rows = batch["rows"]
        lines.append(
            f"组 {b}: {len(rows)} 条 · npc {rows[0]['npc']}…{rows[-1]['npc']} · "
            f"首槽 {rows[0]['test_slot']} · 末槽 {rows[-1]['test_slot']}"
        )
    lines.append("")
    lines.append(f"全文 -> {FLY_TABLE_PATH}")
    return "\n".join(lines)
