"""T-084 B3 — contract / synthetic donor templates (extracted from enemy_randomizer_core)."""
from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from boss_npc_detect import is_force_trash_model
from donor_pool_review_allowlist import normalize_category_id
from enemy_category_rules import (
    infer_category,
    infer_size_tier,
    is_horse_mount_model,
)
from paths import GAME_DIR

def _group_templates_by_model(
    pool: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for tpl in pool:
        model = str(tpl.get("model", ""))
        out.setdefault(model, []).append(tpl)
    return out


def supplement_synthetic_boss_templates(
    templates: list[dict[str, Any]],
    categories_cfg: dict[str, Any],
) -> list[dict[str, Any]]:
    """CNV MSB index lacks story bosses (c4750/c2200); add csv-fallback donors.

    `load_enemy_index` re-runs enrich on an already-enriched cache: synthetic rows
    get reclassified via force_trash / missing src_cat_rules. Restore configured
    category when the template_id already exists.
    """
    out = list(templates)
    by_id = {str(t.get("template_id", "")): t for t in out}
    size_map = categories_cfg.get("size_tier_by_model_prefix", {})
    rules = categories_cfg.get("src_cat_rules", [])
    default_cat = categories_cfg.get("template_default_category", "trash")
    for raw in categories_cfg.get("synthetic_boss_templates") or []:
        tpl_id = str(raw.get("template_id", ""))
        if not tpl_id:
            continue
        model = str(raw.get("model", ""))
        if is_force_trash_model(model, categories_cfg):
            cat = "trash"
        else:
            cat = str(
                raw.get("category") or infer_category(model, rules, default_cat)
            )
        origin = str(raw.get("donor_origin") or "base")
        if origin not in ("base", "dlc", "cnv"):
            origin = "base"
        tags = {
            "size_tier": infer_size_tier(model, size_map),
            "needs_summon": False,
            "has_flight_ai": infer_size_tier(model, size_map) == "flying",
            "has_walk_route": False,
            "mounted_rider": False,
            "horse_mount": is_horse_mount_model(model, categories_cfg),
            "synthetic_boss": True,
            "donor_origin": origin,
        }
        if tpl_id in by_id:
            existing = by_id[tpl_id]
            existing["category"] = cat
            existing["model"] = model
            if raw.get("npc") is not None:
                existing["npc"] = raw.get("npc", 0)
            if raw.get("think") is not None:
                existing["think"] = raw.get("think", 0)
            if raw.get("chara") is not None:
                existing["chara"] = raw.get("chara", -1)
            merged_tags = dict(existing.get("template_tags") or {})
            merged_tags.update(tags)
            existing["template_tags"] = merged_tags
            continue
        out.append(
            {
                "template_id": tpl_id,
                "donor_map": "synthetic",
                "donor_entity": tpl_id.split(":", 1)[-1],
                "model": model,
                "npc": raw.get("npc", 0),
                "think": raw.get("think", 0),
                "chara": raw.get("chara", -1),
                "category": cat,
                "template_tags": tags,
            }
        )
        by_id[tpl_id] = out[-1]
    return out


def _parse_contract_whitelist_model_map() -> dict[int, str]:
    """捐皮契约白名单 md → npc→model（补全无地图模板的合成捐皮）。"""
    from paths import DONOR_POOL_CONTRACT_DIR

    md = DONOR_POOL_CONTRACT_DIR / "捐皮白名单_当前.md"
    if not md.is_file():
        return {}
    pool_header_re = re.compile(r"^##\s*池\s*(\d+)\s*·")
    out: dict[int, str] = {}
    for line in md.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|") or "---" in line or "序号" in line:
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 6:
            continue
        try:
            int(parts[1])
        except (TypeError, ValueError):
            continue
        model = str(parts[4] or "").strip().strip("`").lower()
        if not model:
            continue
        # 末列 npc（契约表无 npc 列时用 json 反查 — 见 supplement_contract_allowlist_templates）
        npc_raw = parts[6] if len(parts) > 6 else ""
        try:
            npc = int(str(npc_raw).strip())
        except (TypeError, ValueError):
            continue
        if npc > 0:
            out[npc] = model
    if out:
        return out
    # md 无 npc 列：用契约 json 行序 + 英文名/HP 对齐
    wl_json = DONOR_POOL_CONTRACT_DIR / "捐皮白名单_当前.json"
    if not wl_json.is_file():
        return {}
    try:
        wl = json.loads(wl_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    rows_by_pool = wl.get("rows_by_pool") or {}
    md_rows: list[tuple[str, str, int]] = []
    for line in md.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|") or "---" in line or "序号" in line:
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 6:
            continue
        try:
            int(parts[1])
        except (TypeError, ValueError):
            continue
        model = str(parts[4] or "").strip().strip("`").lower()
        name_en = str(parts[3] or "").strip().casefold()
        try:
            hp = int(str(parts[5]).replace(",", ""))
        except (TypeError, ValueError):
            hp = 0
        if model:
            md_rows.append((model, name_en, hp))
    for pool_rows in rows_by_pool.values():
        for row in pool_rows:
            try:
                npc = int(row.get("npc", 0) or 0)
            except (TypeError, ValueError):
                continue
            if npc <= 0 or npc in out:
                continue
            name_en = str(row.get("name_en") or "").strip().casefold()
            hp = int(row.get("effective_hp") or 0)
            model = str(row.get("model") or "").strip().lower()
            if model:
                out[npc] = model
                continue
            for m, en, mhp in md_rows:
                if name_en and en == name_en:
                    if hp <= 0 or mhp <= 0 or abs(hp - mhp) <= max(hp, mhp) * 0.12:
                        out[npc] = m
                        break
    return out


def donor_template_chara(tpl: dict[str, Any]) -> int:
    try:
        return int(tpl.get("chara", -1) or -1)
    except (TypeError, ValueError):
        return -1


def is_contract_synthetic_template(tpl: dict[str, Any]) -> bool:
    return str(tpl.get("template_id", "")).startswith("synthetic:contract_")


def pick_best_donor_template(
    npc: int,
    model: str,
    candidates: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """同 npc 多 template 时择优：c0000 须 chara>0，优先地图皮。"""
    matches = [t for t in candidates if int(t.get("npc", 0) or 0) == npc]
    if not matches:
        return None
    model_l = str(model or "").lower()

    def score(tpl: dict[str, Any]) -> tuple[int, int, int]:
        chara = donor_template_chara(tpl)
        syn = is_contract_synthetic_template(tpl)
        if model_l == "c0000":
            if chara <= 0:
                return (0, 0, 0)
            return (2, chara, 0 if not syn else 1)
        return (1, 0 if not syn else 1, chara)

    best = max(matches, key=score)
    if model_l == "c0000" and donor_template_chara(best) <= 0:
        return None
    return best


def build_contract_synthetic_donor_template(
    cat: str,
    npc: int,
    model: str,
    *,
    categories_cfg: dict[str, Any],
    catalog: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    model_l = str(model or "").lower()
    chara = -1
    if catalog:
        best = pick_best_donor_template(npc, model_l, catalog)
        if best is not None:
            chara = donor_template_chara(best)
    think = _infer_think_from_npc(npc)
    size_map = categories_cfg.get("size_tier_by_model_prefix", {})
    tpl_id = f"synthetic:contract_{cat}_{npc}"
    tags = {
        "size_tier": infer_size_tier(model_l, size_map),
        "needs_summon": False,
        "has_flight_ai": False,
        "has_walk_route": False,
        "mounted_rider": False,
        "horse_mount": False,
        "synthetic_contract_allowlist": True,
        "donor_origin": "cnv",
    }
    return {
        "template_id": tpl_id,
        "donor_map": "synthetic",
        "donor_entity": tpl_id.split(":", 1)[-1],
        "model": model_l,
        "npc": npc,
        "think": think,
        "chara": chara,
        "category": cat,
        "template_tags": tags,
    }


def compose_allowlist_donor_templates_by_cat(
    templates_by_cat: dict[str, list[dict[str, Any]]],
    catalog_templates: list[dict[str, Any]],
    categories_cfg: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    """T-060：白名单池内每 npc 仅 1 张捐皮；c0000 须 chara>0。"""
    from enemy_randomizer_core import CATEGORY_ORDER
    if not categories_cfg.get("donor_review_allowlist_enabled", False):
        return templates_by_cat
    model_map = _parse_contract_whitelist_model_map()
    out: dict[str, list[dict[str, Any]]] = {c: [] for c in CATEGORY_ORDER}

    for cat in CATEGORY_ORDER:
        by_npc: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for tpl in templates_by_cat.get(cat) or []:
            npc = int(tpl.get("npc", 0) or 0)
            if npc > 0:
                by_npc[npc].append(tpl)
        picked: list[dict[str, Any]] = []
        for npc, tpls in sorted(by_npc.items()):
            model = model_map.get(npc) or str(tpls[0].get("model", "")).lower()
            best = pick_best_donor_template(npc, model, tpls)
            if best is None:
                cat_best = pick_best_donor_template(npc, model, catalog_templates)
                if cat_best is not None and (
                    model != "c0000" or donor_template_chara(cat_best) > 0
                ):
                    best = dict(cat_best)
                    best["category"] = cat
                else:
                    continue
            else:
                best = dict(best)
            picked.append(best)
        out[cat] = picked
    return out


def supplement_contract_allowlist_templates(
    templates: list[dict[str, Any]],
    categories_cfg: dict[str, Any],
    *,
    csv_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """白名单 npc 无地图模板时注入 synthetic:contract_* 捐皮行。"""
    from enemy_randomizer_core import CATEGORY_ORDER
    if not categories_cfg.get("donor_review_allowlist_enabled", False):
        return templates
    from donor_pool_review_allowlist import load_review_allowlist_by_category

    allowlist = load_review_allowlist_by_category()
    if not allowlist:
        return templates

    covered: set[tuple[str, int]] = set()
    for tpl in templates:
        try:
            npc = int(tpl.get("npc", 0) or 0)
        except (TypeError, ValueError):
            npc = 0
        if npc > 0:
            tpl_id = str(tpl.get("template_id", ""))
            if tpl_id.startswith("synthetic:contract_"):
                m = re.match(r"^synthetic:contract_(.+)_(\d+)$", tpl_id)
                if m:
                    covered.add((m.group(1), int(m.group(2))))

    model_map = _parse_contract_whitelist_model_map()
    out = list(templates)
    by_id = {str(t.get("template_id", "")): t for t in out}
    size_map = categories_cfg.get("size_tier_by_model_prefix", {})

    for cat, npc_set in allowlist.items():
        cat_n = normalize_category_id(str(cat))
        if cat_n not in CATEGORY_ORDER:
            continue
        for npc in sorted(npc_set):
            if (cat_n, npc) in covered:
                continue
            model_l = model_map.get(npc, "")
            if not model_l:
                continue
            if pick_best_donor_template(npc, model_l, out) is not None:
                continue
            tpl_id = f"synthetic:contract_{cat_n}_{npc}"
            chara = -1
            cat_best = pick_best_donor_template(npc, model_l, out)
            if cat_best is not None:
                chara = donor_template_chara(cat_best)
            think = _infer_think_from_npc(npc)
            tags = {
                "size_tier": infer_size_tier(model_l, size_map),
                "needs_summon": False,
                "has_flight_ai": False,
                "has_walk_route": False,
                "mounted_rider": False,
                "horse_mount": False,
                "synthetic_contract_allowlist": True,
                "donor_origin": "cnv",
            }
            if tpl_id in by_id:
                existing = by_id[tpl_id]
                existing["model"] = model_l
                existing["npc"] = npc
                existing["think"] = think
                existing["category"] = cat_n
                if chara > 0:
                    existing["chara"] = chara
                merged = dict(existing.get("template_tags") or {})
                merged.update(tags)
                existing["template_tags"] = merged
                covered.add((cat_n, npc))
                continue
            out.append(
                {
                    "template_id": tpl_id,
                    "donor_map": "synthetic",
                    "donor_entity": tpl_id.split(":", 1)[-1],
                    "model": model_l,
                    "npc": npc,
                    "think": think,
                    "chara": chara,
                    "category": cat_n,
                    "template_tags": tags,
                }
            )
            by_id[tpl_id] = out[-1]
            covered.add((cat_n, npc))
    return out


def _infer_think_from_npc(npc: int) -> int:
    """MSB 常见：think 与 npc 同族，末两位常为 00。"""
    from npc_think_sanitize import infer_think_from_npc as _infer

    return _infer(npc)


def resolve_runtime_think(
    slot: dict[str, Any],
    template: dict[str, Any],
    categories_cfg: dict[str, Any] | None = None,
    *,
    csv_dir: Path | str | None = None,
) -> int:
    """T-059/T-076：巡逻槽 + 巡逻出处捐皮 → MSB think 原样；其余走安全清洗。"""
    from npc_think_sanitize import resolve_think_csv_dir_str

    csv_key = resolve_think_csv_dir_str(csv_dir)
    try:
        donor_think = int(template.get("think") or 0)
    except (TypeError, ValueError):
        donor_think = 0
    try:
        npc = int(template.get("npc") or 0)
    except (TypeError, ValueError):
        npc = 0
    slot_walk = str(slot.get("walk_route") or "").strip()
    donor_walk = str(template.get("walk_route") or "").strip()
    from donor_msb_compat import _is_script_patrol_flyer_slot
    from npc_think_sanitize import (
        resolve_safe_think,
        think_matches_model_family,
        think_param_has_id,
    )

    if slot_walk and donor_walk and donor_think > 0 and think_param_has_id(
        donor_think, csv_dir=csv_key
    ):
        return donor_think
    if _is_script_patrol_flyer_slot(slot, categories_cfg) and donor_think > 0:
        model_l = str(template.get("model") or slot.get("model") or "").strip().lower()
        if think_matches_model_family(model_l, donor_think) and think_param_has_id(
            donor_think, csv_dir=csv_key
        ):
            return donor_think
    return resolve_safe_think(
        donor_think=donor_think,
        npc=npc,
        categories_cfg=categories_cfg,
        csv_dir=csv_key,
    )


def supplement_dlc_trash_templates(
    templates: list[dict[str, Any]],
    categories_cfg: dict[str, Any],
    *,
    csv_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """NpcParam 补 DLC 普通小怪捐皮；优先 m61 清单 + 有效 HP（含 20007 倍率）选行。"""
    from dlc_donor_pool import load_m61_dlc_manifest, pick_dlc_donor_npc

    prefixes = categories_cfg.get("dlc_trash_donor_model_prefixes") or []
    if not prefixes:
        return templates
    prefix_set = {str(p).lower() for p in prefixes}
    base = Path(csv_dir) if csv_dir else (GAME_DIR / "csv")
    path = base / "NpcParam.csv"
    manifest = load_m61_dlc_manifest()
    manifest_trash = {
        str(e.get("prefix", "")).lower(): e for e in (manifest.get("trash") or [])
    }

    npc_by_id: dict[int, dict[str, str]] = {}
    if path.is_file():
        with path.open(encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                try:
                    npc_by_id[int(row["ID"])] = row
                except (KeyError, TypeError, ValueError):
                    pass

    best: dict[str, tuple[int, int]] = {}
    for model_l in sorted(prefix_set):
        entry = manifest_trash.get(model_l)
        if entry and int(entry.get("npc") or 0) > 0:
            best[model_l] = (int(entry["effective_hp"]), int(entry["npc"]))
            continue
        pick = pick_dlc_donor_npc(model_l, npc_by_id, min_effective_hp=0)
        if pick:
            best[model_l] = (int(pick["effective_hp"]), int(pick["npc"]))

    out = list(templates)
    by_id = {str(t.get("template_id", "")): t for t in out}
    size_map = categories_cfg.get("size_tier_by_model_prefix", {})
    for model_l, (_eff, npc) in sorted(best.items()):
        model = model_l
        tpl_id = f"synthetic:dlc_trash_{model}"
        think = _infer_think_from_npc(npc)
        tags = {
            "size_tier": infer_size_tier(model, size_map),
            "needs_summon": False,
            "has_flight_ai": False,
            "has_walk_route": False,
            "mounted_rider": False,
            "horse_mount": False,
            "synthetic_dlc_trash": True,
            "donor_origin": "dlc",
        }
        if tpl_id in by_id:
            existing = by_id[tpl_id]
            existing["model"] = model
            existing["npc"] = npc
            existing["think"] = think
            existing["category"] = "trash"
            merged = dict(existing.get("template_tags") or {})
            merged.update(tags)
            existing["template_tags"] = merged
            continue
        out.append(
            {
                "template_id": tpl_id,
                "donor_map": "synthetic",
                "donor_entity": tpl_id.split(":", 1)[-1],
                "model": model,
                "npc": npc,
                "think": think,
                "chara": -1,
                "category": "trash",
                "template_tags": tags,
            }
        )
        by_id[tpl_id] = out[-1]
    return out


def supplement_dlc_boss_templates(
    templates: list[dict[str, Any]],
    categories_cfg: dict[str, Any],
    *,
    csv_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """m61 扫描 Boss 捐皮：有效 HP 选行 + donor_origin=dlc。"""
    from dlc_donor_pool import load_m61_dlc_manifest, pick_dlc_donor_npc

    manifest = load_m61_dlc_manifest()
    boss_rows = manifest.get("boss") or []
    if not boss_rows:
        return templates

    base = Path(csv_dir) if csv_dir else (GAME_DIR / "csv")
    npc_by_id: dict[int, dict[str, str]] = {}
    npc_path = base / "NpcParam.csv"
    if npc_path.is_file():
        with npc_path.open(encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                try:
                    npc_by_id[int(row["ID"])] = row
                except (KeyError, TypeError, ValueError):
                    pass

    out = list(templates)
    by_id = {str(t.get("template_id", "")): t for t in out}
    size_map = categories_cfg.get("size_tier_by_model_prefix", {})
    rules = categories_cfg.get("src_cat_rules", [])
    default_cat = categories_cfg.get("template_default_category", "trash")

    for raw in boss_rows:
        prefix = str(raw.get("prefix") or "")
        if not prefix:
            continue
        tpl_id = f"synthetic:dlc_boss_{prefix}"
        cat = str(raw.get("category") or "minor_boss")
        npc = int(raw.get("npc") or 0)
        if npc <= 0:
            pick = pick_dlc_donor_npc(prefix, npc_by_id, min_effective_hp=0, for_boss_pool=True)
            if not pick:
                continue
            npc = int(pick["npc"])
        think = _infer_think_from_npc(npc)
        tags = {
            "size_tier": infer_size_tier(prefix, size_map),
            "needs_summon": False,
            "has_flight_ai": infer_size_tier(prefix, size_map) == "flying",
            "has_walk_route": False,
            "mounted_rider": False,
            "horse_mount": is_horse_mount_model(prefix, categories_cfg),
            "synthetic_boss": True,
            "donor_origin": "dlc",
        }
        if tpl_id in by_id:
            existing = by_id[tpl_id]
            existing["category"] = cat
            existing["model"] = prefix
            existing["npc"] = npc
            existing["think"] = think
            merged = dict(existing.get("template_tags") or {})
            merged.update(tags)
            existing["template_tags"] = merged
            continue
        out.append(
            {
                "template_id": tpl_id,
                "donor_map": "synthetic",
                "donor_entity": tpl_id.split(":", 1)[-1],
                "model": prefix,
                "npc": npc,
                "think": think,
                "chara": -1,
                "category": cat,
                "template_tags": tags,
            }
        )
        by_id[tpl_id] = out[-1]
    return out

