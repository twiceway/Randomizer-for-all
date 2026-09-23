"""T-084 B3 — enemy index enrich / export pipeline (extracted from enemy_randomizer_core)."""
from __future__ import annotations

import hashlib
import json
import pickle
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from boss_npc_detect import resolve_entity_category
from enemy_category_rules import (
    all_size_tier_ids,
    boss_donor_allowed_on_compact_slot,
    effective_slot_map_kind,
    infer_category,
    infer_size_tier,
    is_excluded_size_tier,
    is_horse_mount_model,
    is_unsafe_donor_template,
    needs_summon,
    promote_cnv_named_boss_slots,
    promote_cnv_named_boss_template_categories,
    refine_cnv_boss_tag_slots,
    refine_cnv_boss_tag_template_categories,
    refine_cnv_new_npc_red_spirit_categories,
    refine_cnv_new_npc_red_spirit_slots,
    refine_cnv_special_template_categories,
    resolve_donor_origin,
    resolve_size_tier,
    size_tier_rank,
)
from enemy_contract_templates import (
    supplement_contract_allowlist_templates,
    supplement_dlc_boss_templates,
    supplement_dlc_trash_templates,
    supplement_synthetic_boss_templates,
)
from paths import CACHE_DIR, GAME_DIR, subprocess_no_window_kwargs

INDEX_ENRICH_VERSION = 1

_ENRICHED_INDEX_CACHE: tuple[float, dict[str, Any]] | None = None


def clear_enriched_index_cache() -> None:
    global _ENRICHED_INDEX_CACHE
    _ENRICHED_INDEX_CACHE = None


def index_pickle_path(index_path: Path) -> Path:
    return index_path.with_suffix(".pkl")


def index_pickle_key_path(index_path: Path) -> Path:
    return index_pickle_path(index_path).with_suffix(".pkl.key")


def _index_pickle_fingerprint(index_path: Path) -> str:
    from enemy_slot_prep import _categories_compat_fingerprint

    if not index_path.is_file():
        return "missing"
    st = index_path.stat()
    blob = (
        f"v{INDEX_ENRICH_VERSION}|{st.st_size}|{int(st.st_mtime_ns)}|"
        f"{_categories_compat_fingerprint()}"
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _clear_index_pickle_sidecars(index_path: Path) -> None:
    for path in (index_pickle_path(index_path), index_pickle_key_path(index_path)):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def _index_pickle_fresh(index_path: Path) -> bool:
    pkl = index_pickle_path(index_path)
    key_path = index_pickle_key_path(index_path)
    if not pkl.is_file() or not key_path.is_file():
        return False
    try:
        return key_path.read_text(encoding="utf-8").strip() == _index_pickle_fingerprint(
            index_path
        )
    except OSError:
        return False


def _write_index_pickle(index_path: Path, enriched: dict[str, Any]) -> None:
    pkl = index_pickle_path(index_path)
    key_path = index_pickle_key_path(index_path)
    try:
        with pkl.open("wb") as fh:
            pickle.dump(enriched, fh, protocol=pickle.HIGHEST_PROTOCOL)
        key_path.write_text(_index_pickle_fingerprint(index_path), encoding="utf-8")
    except OSError:
        pass


def _load_index_pickle(index_path: Path) -> dict[str, Any]:
    with index_pickle_path(index_path).open("rb") as fh:
        return pickle.load(fh)


def _index_slots_look_enriched(raw: dict[str, Any]) -> bool:
    slots = raw.get("slots") or []
    if len(slots) < 32:
        return False
    sample = slots[0]
    tags = sample.get("slot_tags") or {}
    return bool(sample.get("src_cat")) and bool(tags.get("src_cat"))


def _apply_template_supplements(
    templates: list[dict[str, Any]],
    categories_cfg: dict[str, Any],
    *,
    npc_csv_dir: str,
) -> list[dict[str, Any]]:
    templates_out = supplement_synthetic_boss_templates(templates, categories_cfg)
    templates_out = supplement_dlc_boss_templates(
        templates_out, categories_cfg, csv_dir=npc_csv_dir
    )
    templates_out = supplement_dlc_trash_templates(
        templates_out, categories_cfg, csv_dir=npc_csv_dir
    )
    templates_out = supplement_contract_allowlist_templates(
        templates_out, categories_cfg, csv_dir=Path(npc_csv_dir)
    )
    refine_cnv_special_template_categories(
        templates_out, categories_cfg, csv_dir=npc_csv_dir
    )
    refine_cnv_new_npc_red_spirit_categories(templates_out, csv_dir=npc_csv_dir)
    promote_cnv_named_boss_template_categories(templates_out, categories_cfg)
    refine_cnv_boss_tag_template_categories(templates_out, csv_dir=npc_csv_dir)
    return templates_out


def enrich_index(
    raw: dict[str, Any],
    categories_cfg: dict[str, Any],
    *,
    full: bool = False,
) -> dict[str, Any]:
    npc_csv_dir = str(Path(GAME_DIR / "csv").resolve())
    if not full and _index_slots_look_enriched(raw):
        templates_out = _apply_template_supplements(
            list(raw.get("templates") or []),
            categories_cfg,
            npc_csv_dir=npc_csv_dir,
        )
        slots_out = list(raw.get("slots") or [])
        refine_cnv_new_npc_red_spirit_slots(slots_out, csv_dir=npc_csv_dir)
        promote_cnv_named_boss_slots(slots_out, categories_cfg)
        refine_cnv_boss_tag_slots(slots_out, csv_dir=npc_csv_dir)
        return {
            "version": int(raw.get("version", 2) or 2),
            "schema": raw.get("schema") or "enemy_index_v2",
            "generated_at": raw.get("generated_at")
            or datetime.now(timezone.utc).isoformat(),
            "maps_scanned": raw.get("maps_scanned", 0),
            "maps_skipped": raw.get("maps_skipped", 0),
            "routes_by_map": raw.get("routes_by_map") or {},
            "zero_npc_slots_skipped": raw.get("zero_npc_slots_skipped", 0),
            "slots": slots_out,
            "templates": templates_out,
        }

    rules = categories_cfg.get("src_cat_rules", [])
    default_cat = categories_cfg.get("template_default_category", "trash")
    size_map = categories_cfg.get("size_tier_by_model_prefix", {})
    summon_prefixes = categories_cfg.get("needs_summon_model_prefixes", [])

    slots_out: list[dict[str, Any]] = []
    walk_route_by_entity: dict[str, str] = {}
    for slot in raw.get("slots", []):
        name = str(slot.get("name", ""))
        walk_route = str(slot.get("walk_route") or "")
        if name and walk_route:
            walk_route_by_entity[name] = walk_route

    for slot in raw.get("slots", []):
        model = str(slot.get("model", ""))
        rules_cat = infer_category(model, rules, default_cat)
        src_cat = resolve_entity_category(
            slot,
            categories_cfg=categories_cfg,
            csv_dir=npc_csv_dir,
            rules_category=rules_cat,
        )
        size_tier = infer_size_tier(model, size_map)
        slots_out.append(
            {
                **slot,
                "src_cat": src_cat,
                "slot_tags": {
                    "src_cat": src_cat,
                    "size_tier": size_tier,
                    "has_walk_route": bool(slot.get("walk_route")),
                    "is_sitting": bool(slot.get("backup_anim", 0) > 0 and not slot.get("walk_route")),
                    "map_kind": effective_slot_map_kind(slot, categories_cfg),
                    "orig_model_prefix": model[:5] if len(model) >= 5 else model,
                    "siege_mount_rider": bool(slot.get("siege_mount_rider")),
                    **(
                        {"siege_mount_weapon": str(slot.get("siege_mount_weapon"))}
                        if slot.get("siege_mount_weapon")
                        else {}
                    ),
                },
            }
        )

    templates_out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for tpl in raw.get("templates", []):
        model = str(tpl.get("model", ""))
        rules_cat = infer_category(model, rules, default_cat)
        cat = resolve_entity_category(
            tpl,
            categories_cfg=categories_cfg,
            csv_dir=npc_csv_dir,
            rules_category=rules_cat,
        )
        tpl_id = str(tpl.get("template_id", ""))
        if not tpl_id or tpl_id in seen:
            continue
        seen.add(tpl_id)
        donor_entity = str(tpl.get("donor_entity") or tpl_id.split(":", 1)[-1])
        tpl_walk = str(tpl.get("walk_route") or "").strip()
        has_walk_route = bool(tpl_walk) or bool(
            walk_route_by_entity.get(donor_entity, "")
        )
        templates_out.append(
            {
                **tpl,
                "category": cat,
                "template_tags": {
                    "size_tier": infer_size_tier(model, size_map),
                    "needs_summon": needs_summon(model, summon_prefixes),
                    "has_flight_ai": infer_size_tier(model, size_map) == "flying",
                    "has_walk_route": has_walk_route,
                    "mounted_rider": has_walk_route,
                    "horse_mount": is_horse_mount_model(model, categories_cfg),
                    "donor_origin": resolve_donor_origin(
                        {"model": model, "template_id": tpl_id, "donor_map": tpl.get("donor_map")},
                        categories_cfg,
                    ),
                },
            }
        )

    templates_out = _apply_template_supplements(
        templates_out, categories_cfg, npc_csv_dir=npc_csv_dir
    )
    refine_cnv_new_npc_red_spirit_slots(slots_out, csv_dir=npc_csv_dir)
    promote_cnv_named_boss_slots(slots_out, categories_cfg)
    refine_cnv_boss_tag_slots(slots_out, csv_dir=npc_csv_dir)

    return {
        "version": 2,
        "schema": raw.get("schema") or "enemy_index_v2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "maps_scanned": raw.get("maps_scanned", 0),
        "maps_skipped": raw.get("maps_skipped", 0),
        "routes_by_map": raw.get("routes_by_map") or {},
        "zero_npc_slots_skipped": raw.get("zero_npc_slots_skipped", 0),
        "slots": slots_out,
        "templates": templates_out,
    }


def run_index_export(
    *,
    out_path: Path | None = None,
    max_maps: int | None = None,
) -> Path:
    from enemy_randomizer_core import DEFAULT_CATEGORIES_PATH, DEFAULT_INDEX_PATH, _load_json
    out_path = out_path or DEFAULT_INDEX_PATH
    out_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path = out_path.with_suffix(".raw.json")

    exe = _ensure_msb_poc_built()
    cmd = [
        str(exe),
        "index-export",
        f"--out={raw_path}",
        f"--game={GAME_DIR}",
    ]
    if max_maps is not None:
        cmd.append(f"--max-maps={max_maps}")

    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        **subprocess_no_window_kwargs(),
    )
    if proc.returncode != 0:
        raise RuntimeError(
            "index-export failed:\n" + (proc.stderr or proc.stdout or "(no output)")
        )

    raw = _load_json(raw_path)
    categories_cfg = _load_json(DEFAULT_CATEGORIES_PATH)
    enriched = enrich_index(raw, categories_cfg, full=True)
    out_path.write_text(json.dumps(enriched, ensure_ascii=False, indent=2), encoding="utf-8")
    clear_enriched_index_cache()
    _clear_index_pickle_sidecars(out_path)
    _write_index_pickle(out_path, enriched)
    return out_path


def load_enemy_index(path: Path | None = None) -> dict[str, Any]:
    from enemy_randomizer_core import DEFAULT_CATEGORIES_PATH, DEFAULT_INDEX_PATH, _load_json
    global _ENRICHED_INDEX_CACHE
    path = path or DEFAULT_INDEX_PATH
    if not path.is_file():
        raise FileNotFoundError(
            f"缺少 enemy_index.json：请先运行扫描（GUI「扫描地图」或 enemy_scan.py）。路径：{path}"
        )
    mtime = path.stat().st_mtime
    if _ENRICHED_INDEX_CACHE is not None and _ENRICHED_INDEX_CACHE[0] == mtime:
        return _ENRICHED_INDEX_CACHE[1]
    if _index_pickle_fresh(path):
        enriched = _load_index_pickle(path)
        _ENRICHED_INDEX_CACHE = (mtime, enriched)
        return enriched
    raw = _load_json(path)
    categories_cfg = _load_json(DEFAULT_CATEGORIES_PATH)
    enriched = enrich_index(raw, categories_cfg)
    _write_index_pickle(path, enriched)
    _ENRICHED_INDEX_CACHE = (mtime, enriched)
    return enriched


def _ensure_msb_poc_built() -> Path:
    from enemy_randomizer_core import MSB_POC_EXE, MSB_POC_PROJECT
    src = MSB_POC_PROJECT.parent / "Program.cs"
    if MSB_POC_EXE.is_file() and (
        not src.is_file() or MSB_POC_EXE.stat().st_mtime >= src.stat().st_mtime
    ):
        return MSB_POC_EXE

    combined = ""
    for attempt in range(2):
        build = subprocess.run(
            ["dotnet", "build", str(MSB_POC_PROJECT), "-c", "Release"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            **subprocess_no_window_kwargs(),
        )
        combined = (build.stderr or "") + (build.stdout or "")
        if build.returncode == 0 and MSB_POC_EXE.is_file():
            return MSB_POC_EXE
        locked = "MSB3027" in combined or "being used by another process" in combined
        if locked and attempt == 0:
            subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "Get-Process -Name MsbEnemyPoc -ErrorAction SilentlyContinue | Stop-Process -Force",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                **subprocess_no_window_kwargs(),
            )
            continue
        break

    if "MSB3027" in combined or "being used by another process" in combined:
        raise RuntimeError(
            "MsbEnemyPoc 编译失败：exe 被占用。\n"
            "请先完全关闭随机器 GUI，或在任务管理器结束 MsbEnemyPoc.exe 后重试。\n"
            + combined
        )
    raise RuntimeError("MsbEnemyPoc build failed:\n" + combined)


def compat_filter(
    pool: list[dict[str, Any]],
    slot: dict[str, Any],
    *,
    size_map: dict[str, str] | None = None,
    exclude_donor_tiers: set[str] | None = None,
    categories_cfg: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    tags = slot.get("slot_tags") or {}
    map_k = (
        effective_slot_map_kind(slot, categories_cfg)
        if categories_cfg
        else str(tags.get("map_kind", "overworld"))
    )
    slot_tier = resolve_size_tier(str(slot.get("model", "")), size_map or {})
    max_rank = size_tier_rank(slot_tier)
    out: list[dict[str, Any]] = []
    for tpl in pool:
        donor_tier = resolve_size_tier(str(tpl.get("model", "")), size_map or {})
        if exclude_donor_tiers and is_excluded_size_tier(donor_tier, exclude_donor_tiers):
            continue
        if size_tier_rank(donor_tier) > max_rank:
            continue
        tt = tpl.get("template_tags") or {}
        if tt.get("needs_summon"):
            continue
        if (
            donor_tier == "flying" or tt.get("has_flight_ai")
        ) and map_k == "dungeon":
            continue
        out.append(tpl)
    return out


def build_compat_pools(
    templates_by_cat: dict[str, list[dict[str, Any]]],
    *,
    size_map: dict[str, str],
    exclude_donor_tiers: set[str],
    categories_cfg: dict[str, Any] | None = None,
) -> dict[tuple[str, str, str], list[dict[str, Any]]]:
    from enemy_randomizer_core import BOSS_SOURCE_CATEGORIES, BOSS_TARGET_CATEGORIES, CATEGORY_ORDER
    from enemy_category_rules import (
        is_wyvern_or_ancient_dragon_donor,
        narrow_map_medium_max_rank,
    )
    """Pre-filter pools by (tgt_cat, slot_tier, map_kind) — avoids O(slots×templates)."""
    cache: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    slot_tiers = all_size_tier_ids()
    map_kinds = ("overworld", "dungeon")

    for cat in CATEGORY_ORDER:
        annotated: list[tuple[dict[str, Any], str, dict[str, Any]]] = []
        for tpl in templates_by_cat.get(cat, []):
            if categories_cfg and is_unsafe_donor_template(tpl, categories_cfg):
                continue
            donor_tier = resolve_size_tier(str(tpl.get("model", "")), size_map)
            annotated.append((tpl, donor_tier, tpl.get("template_tags") or {}))

        for slot_tier in slot_tiers:
            max_rank = size_tier_rank(slot_tier)
            for map_k in map_kinds:
                out: list[dict[str, Any]] = []
                medium_cap = narrow_map_medium_max_rank(categories_cfg or {})
                for tpl, donor_tier, tt in annotated:
                    model = str(tpl.get("model", ""))
                    if exclude_donor_tiers and is_excluded_size_tier(
                        donor_tier, exclude_donor_tiers
                    ):
                        if cat not in BOSS_SOURCE_CATEGORIES:
                            continue
                    # T-097：狭窄/室内禁大型/超巨/主线Boss/飞龙（含 Boss 目标池）
                    if map_k == "dungeon" and size_tier_rank(donor_tier) > medium_cap:
                        continue
                    if cat == "night":
                        pass
                    elif cat in BOSS_TARGET_CATEGORIES:
                        eff_max = max_rank
                    elif map_k == "dungeon":
                        eff_max = min(max_rank, medium_cap)
                    else:
                        eff_max = max_rank
                    if (
                        cat not in BOSS_TARGET_CATEGORIES
                        and size_tier_rank(donor_tier) > eff_max
                    ):
                        continue
                    if (
                        cat in BOSS_TARGET_CATEGORIES
                        and slot_tier in ("small", "humanoid")
                        and categories_cfg
                    ):
                        if map_k == "dungeon":
                            if is_wyvern_or_ancient_dragon_donor(
                                model, categories_cfg
                            ):
                                continue
                            if donor_tier == "flying":
                                continue
                        elif not boss_donor_allowed_on_compact_slot(
                            model, donor_tier, categories_cfg, slot_tier=slot_tier
                        ):
                            continue
                    if tt.get("needs_summon"):
                        continue
                    if (donor_tier == "flying" or tt.get("has_flight_ai")) and map_k == "dungeon":
                        continue
                    out.append(tpl)
                cache[(cat, slot_tier, map_k)] = out
    return cache

