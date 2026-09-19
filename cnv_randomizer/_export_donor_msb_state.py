"""Export donor template MSB initial state + slot-compat flags from enemy_index.json."""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from donor_vanilla_states import attach_vanilla_state_fields, build_model_vanilla_state_index
from _export_slot_initial_state import (
    DECORATIVE_CORPSE_PREFIXES,
    AERIAL_PREFIXES,
    PERCH_PREFIXES,
    SCRIPTED_FLYER_PREFIXES,
    _pref,
    apply_slot_class,
    placement_kind,
    pose_label,
)

SCRIPT_DIR = Path(__file__).resolve().parent
INDEX_PATH = SCRIPT_DIR / "cache" / "enemy_index.json"
OVERRIDES_PATH = SCRIPT_DIR / "donor_msb_compat_overrides.json"
OUT_JSON = SCRIPT_DIR.parent / "reports" / "MSB捐皮初态全表.json"
OUT_MD = SCRIPT_DIR.parent / "reports" / "MSB捐皮初态全表.md"
CACHE_JSON = SCRIPT_DIR / "cache" / "donor_slot_compat.json"
RULE_VERSION = 2

DONOR_MSB_KEYS = (
    "walk_route",
    "backup_anim",
    "talk_id",
    "chr_activate",
    "collision_part",
    "pos_x",
    "pos_y",
    "pos_z",
)


def _split_template_id(template_id: str) -> tuple[str, str]:
    if ":" in template_id:
        map_id, name = template_id.split(":", 1)
        return map_id, name
    return "", template_id


def _slot_key(slot: dict) -> tuple[str, str]:
    return str(slot.get("map_id", "")), str(slot.get("name", ""))


def _msb_row_from_template(tpl: dict, slot_lookup: dict[tuple[str, str], dict]) -> dict:
    tpl_id = str(tpl.get("template_id", ""))
    map_id, entity = _split_template_id(tpl_id)
    donor_map = str(tpl.get("donor_map", ""))
    msb_source = "synthetic"
    if donor_map and donor_map != "synthetic":
        msb_source = "index_template"
    base = slot_lookup.get((map_id, entity), {})
    row: dict = {
        "template_id": tpl_id,
        "donor_map": donor_map,
        "donor_entity": str(tpl.get("donor_entity") or entity),
        "model": str(tpl.get("model", "")),
        "npc": tpl.get("npc"),
        "think": tpl.get("think"),
        "chara": tpl.get("chara"),
        "category": tpl.get("category"),
        "msb_source": msb_source,
    }
    for k in DONOR_MSB_KEYS:
        if k in tpl and tpl.get(k) is not None:
            row[k] = tpl.get(k)
        elif base.get(k) is not None:
            row[k] = base.get(k)
        else:
            row[k] = "" if k in ("walk_route", "collision_part") else (
                -1 if k == "backup_anim" else 0
            )
    if msb_source == "synthetic":
        row["msb_source"] = "synthetic"
    return row


def _infer_force_donor_msb(row: dict, tags: dict) -> bool:
    model = str(row.get("model", ""))
    if _pref(model, SCRIPTED_FLYER_PREFIXES) or _pref(model, ("c6270",)):
        return True
    if _pref(model, AERIAL_PREFIXES):
        return True
    if tags.get("needs_summon"):
        return True
    walk = str(row.get("walk_route") or "").strip()
    backup = int(row.get("backup_anim", -1) or -1)
    if int(row.get("chr_activate", 0) or 0) != 0:
        return True
    if backup > 0 and not walk:
        return True
    collision = str(row.get("collision_part") or "").strip()
    if collision and not _pref(model, PERCH_PREFIXES) and not _pref(
        model, DECORATIVE_CORPSE_PREFIXES
    ):
        return True
    return False


def _apply_overrides(row: dict, overrides: dict) -> None:
    tpl_id = row["template_id"]
    patch = overrides.get(tpl_id)
    if not patch:
        return
    for k in (
        "force_donor_msb",
        "compat_standing_keep",
        "compat_patrol_keep",
        "note",
    ):
        if k in patch:
            row[k] = patch[k]
    if patch.get("force_donor_msb"):
        row["compat_standing_keep"] = False
        row["compat_patrol_keep"] = False


def donor_row(tpl: dict, slot_lookup: dict[tuple[str, str], dict]) -> dict:
    msb = _msb_row_from_template(tpl, slot_lookup)
    tags = tpl.get("template_tags") or {}
    pose = pose_label(msb)
    out = {
        **msb,
        "donor_placement_kind": placement_kind(msb),
        "donor_pose_label": pose,
        "donor_msb_class": apply_slot_class(msb),
        "template_tags": tags,
    }
    force = _infer_force_donor_msb(msb, tags)
    out["force_donor_msb"] = force
    out["compat_standing_keep"] = not force
    out["compat_patrol_keep"] = not force
    return out


def main() -> None:
    raw = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    overrides_doc = json.loads(OVERRIDES_PATH.read_text(encoding="utf-8"))
    overrides = overrides_doc.get("overrides") or {}

    index_slots = list(raw.get("slots") or [])
    slot_lookup = {_slot_key(s): s for s in index_slots}
    model_vanilla_index = build_model_vanilla_state_index(index_slots)
    templates = raw.get("templates") or []
    rows = [donor_row(tpl, slot_lookup) for tpl in templates]
    for row in rows:
        _apply_overrides(row, overrides)

    force_ctr = Counter(bool(r["force_donor_msb"]) for r in rows)
    pose_ctr = Counter(r["donor_pose_label"] for r in rows)

    compat_cache: dict[str, dict] = {}
    for r in rows:
        tid = str(r["template_id"])
        base = {
            "force_donor_msb": r["force_donor_msb"],
            "compat_standing_keep": r["compat_standing_keep"],
            "compat_patrol_keep": r["compat_patrol_keep"],
            "donor_pose_label": r["donor_pose_label"],
            "donor_walk_route": str(r.get("walk_route") or "").strip(),
            "donor_npc": r.get("npc"),
            "donor_think": r.get("think"),
        }
        compat_cache[tid] = attach_vanilla_state_fields(
            base,
            str(r.get("model") or ""),
            model_vanilla_index,
        )

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "rule_version": RULE_VERSION,
        "source": str(INDEX_PATH),
        "index_generated_at": raw.get("generated_at"),
        "template_count": len(rows),
        "summary": {
            "force_donor_msb": dict(force_ctr),
            "donor_pose_label_top": dict(pose_ctr.most_common(30)),
        },
        "donors": rows,
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    CACHE_JSON.write_text(
        json.dumps(
            {
                "rule_version": RULE_VERSION,
                "generated_at": payload["generated_at"],
                "index_generated_at": raw.get("generated_at"),
                "templates": compat_cache,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    lines = [
        "# MSB 捐皮初态全表",
        "",
        f"**生成**：`_export_donor_msb_state.py` · 规则 v{RULE_VERSION}",
        f"**模板数**：{len(rows)}",
        f"**强制捐皮出场**：{force_ctr.get(True, 0)}",
        f"**JSON**：[`MSB捐皮初态全表.json`](./MSB捐皮初态全表.json)",
        f"**快取**：`cnv_randomizer/cache/donor_slot_compat.json`",
        f"**补丁**：`cnv_randomizer/donor_msb_compat_overrides.json`",
        "",
        "## rule v2 — 捐皮状态真源",
        "",
        "每张捐皮 `vanilla_supported_buckets` = 全图 MSB 中 **同 model** 原版槽的状态桶并集（T-080 §3）。",
        "pick/apply 拒绝：目标槽桶 **不在** 该并集 → `vanilla_state_unsupported`。",
        "",
        "## force_donor_msb 含义（审计列 · v1 遗留）",
        "",
        "为 true 时 apply **绝对**用捐皮出场 MSB（覆盖原槽站立/巡逻保留）。",
        "",
        "## donor_pose_label Top",
        "",
        "| pose | 数量 |",
        "|------|-----:|",
    ]
    for k, v in pose_ctr.most_common(20):
        lines.append(f"| `{k}` | {v:,} |")

    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {OUT_JSON}")
    print(f"Wrote {CACHE_JSON}")
    print(f"Wrote {OUT_MD}")
    print("force_donor_msb:", dict(force_ctr))


if __name__ == "__main__":
    main()
