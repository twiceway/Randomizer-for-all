"""Mount pair donor helpers (extracted from enemy_randomizer_core)."""

from __future__ import annotations

import random
import re
from dataclasses import dataclass
from typing import Any

from enemy_category_rules import (
    _model_has_prefix,
    is_field_cavalry_mount_model,
    is_horse_mount_model,
)

def mount_pair_kind_configs(categories_cfg: dict[str, Any]) -> list[dict[str, Any]]:
    return list(categories_cfg.get("mount_pair_kinds") or [])


def mount_pair_randomize_enabled(categories_cfg: dict[str, Any]) -> bool:
    return bool(categories_cfg.get("mount_pair_randomize_enabled", True))


def slot_is_mount_pair_entity(slot: dict[str, Any], categories_cfg: dict[str, Any]) -> bool:
    """Rider or mount body listed in mount_pair_kinds / field_cavalry prefixes."""
    model = str(slot.get("model", ""))
    for kind in mount_pair_kind_configs(categories_cfg):
        prefixes = [str(p).lower() for p in kind.get("rider_prefixes") or []]
        prefixes.extend(str(p).lower() for p in kind.get("mount_prefixes") or [])
        if _model_has_prefix(model, prefixes):
            return True
    riders = [str(p).lower() for p in categories_cfg.get("field_cavalry_rider_model_prefixes") or []]
    mounts = [str(p).lower() for p in categories_cfg.get("field_cavalry_mount_model_prefixes") or []]
    return _model_has_prefix(model, riders) or _model_has_prefix(model, mounts)


def skip_mount_pair_entity_when_disabled(
    slot: dict[str, Any],
    categories_cfg: dict[str, Any],
    *,
    prep_row: dict[str, Any] | None = None,
    rider_to_mount: dict[tuple[str, str], dict[str, Any]] | None = None,
    map_id: str = "",
    entity_name: str = "",
) -> bool:
    """mount_pair 关闭时：仅跳过马身/有配对马的骑手；巡逻与无配对步兵骑手仍参与随机。"""
    if mount_pair_randomize_enabled(categories_cfg):
        return False
    if not slot_is_mount_pair_entity(slot, categories_cfg):
        return False
    if str(slot.get("walk_route") or "").strip():
        return False
    if is_horse_mount_model(str(slot.get("model", "")), categories_cfg):
        return True
    if prep_row and prep_row.get("p"):
        return True
    if rider_to_mount and (map_id, entity_name) in rider_to_mount:
        return True
    return False


def mount_entity_suffix(entity_name: str) -> str:
    """MSB 实体名末尾 _9000 / _9001 … 用于骑手↔马配对。"""
    match = re.search(r"_(900\d+)$", str(entity_name or ""))
    return match.group(1) if match else ""


@dataclass(frozen=True)
class MountPairDonor:
    """骑手+坐骑成套捐皮（池里抽一次 = 两条槽各装一半）。"""

    pair_id: str
    kind_id: str
    rider_tpl: dict[str, Any]
    mount_tpl: dict[str, Any]


def build_mount_pair_donors(
    templates: list[dict[str, Any]],
    categories_cfg: dict[str, Any],
) -> dict[str, list[MountPairDonor]]:
    out: dict[str, list[MountPairDonor]] = {}
    for kind in mount_pair_kind_configs(categories_cfg):
        kind_id = str(kind.get("id", "")).strip()
        riders_p = [str(p).lower() for p in kind.get("rider_prefixes") or []]
        mounts_p = [str(p).lower() for p in kind.get("mount_prefixes") or []]
        if not kind_id or not riders_p:
            continue
        riders_by_key: dict[tuple[str, str], dict[str, Any]] = {}
        mounts_by_key: dict[tuple[str, str], dict[str, Any]] = {}
        for tpl in templates:
            model = str(tpl.get("model", "")).lower()
            donor_map = str(tpl.get("donor_map") or "")
            donor_entity = str(
                tpl.get("donor_entity") or str(tpl.get("template_id", "")).split(":")[-1]
            )
            suffix = mount_entity_suffix(donor_entity)
            if not suffix:
                continue
            key = (donor_map, suffix)
            if _model_has_prefix(model, riders_p):
                riders_by_key[key] = tpl
            elif mounts_p and _model_has_prefix(model, mounts_p):
                mounts_by_key[key] = tpl
        pairs: list[MountPairDonor] = []
        for key, rider_tpl in sorted(riders_by_key.items()):
            mount_tpl = mounts_by_key.get(key)
            if not mount_tpl:
                continue
            donor_map, suffix = key
            pair_id = f"{kind_id}:{donor_map}:{suffix}" if donor_map else f"{kind_id}:{suffix}"
            pairs.append(
                MountPairDonor(
                    pair_id=pair_id,
                    kind_id=kind_id,
                    rider_tpl=rider_tpl,
                    mount_tpl=mount_tpl,
                )
            )
        if pairs:
            out[kind_id] = pairs
    return out


def index_rider_mount_slot_pairs(
    slots: list[dict[str, Any]],
    categories_cfg: dict[str, Any],
) -> tuple[dict[tuple[str, str], dict[str, Any]], set[tuple[str, str]]]:
    """(map_id, rider_entity) → mount_slot；以及应跳过独立抽奖的马槽。"""
    by_map: dict[str, list[dict[str, Any]]] = {}
    for slot in slots:
        by_map.setdefault(str(slot["map_id"]), []).append(slot)

    rider_to_mount: dict[tuple[str, str], dict[str, Any]] = {}
    skip_mount_keys: set[tuple[str, str]] = set()
    for kind in mount_pair_kind_configs(categories_cfg):
        riders_p = [str(p).lower() for p in kind.get("rider_prefixes") or []]
        mounts_p = [str(p).lower() for p in kind.get("mount_prefixes") or []]
        if not mounts_p:
            continue
        for map_id, map_slots in by_map.items():
            riders = [
                s
                for s in map_slots
                if _model_has_prefix(str(s.get("model", "")), riders_p)
            ]
            mounts = [
                s
                for s in map_slots
                if _model_has_prefix(str(s.get("model", "")), mounts_p)
            ]
            for rider in riders:
                suffix = mount_entity_suffix(str(rider.get("name", "")))
                if not suffix:
                    continue
                for mount in mounts:
                    if mount_entity_suffix(str(mount.get("name", ""))) != suffix:
                        continue
                    rider_key = (map_id, str(rider["name"]))
                    rider_to_mount[rider_key] = mount
                    skip_mount_keys.add((map_id, str(mount["name"])))
                    break
    return rider_to_mount, skip_mount_keys


def mount_pair_kind_for_category(
    tgt_cat: str, categories_cfg: dict[str, Any]
) -> dict[str, Any] | None:
    for kind in mount_pair_kind_configs(categories_cfg):
        if str(kind.get("category", "")) == tgt_cat:
            return kind
    return None


def pick_mount_pair_donor(
    pool: list[MountPairDonor], rng: random.Random
) -> MountPairDonor:
    if not pool:
        raise ValueError("empty mount pair pool")
    return rng.choice(sorted(pool, key=lambda p: p.pair_id))


def template_is_mount_unit_donor(
    tpl: dict[str, Any], categories_cfg: dict[str, Any]
) -> bool:
    """骑手+马成套捐皮（不可单独贴到无配对马槽的步兵位）。"""
    if template_is_mounted_rider(tpl):
        return True
    model = str(tpl.get("model", ""))
    if is_horse_mount_model(model, categories_cfg):
        return True
    if is_field_cavalry_mount_model(model, categories_cfg):
        return True
    for kind in mount_pair_kind_configs(categories_cfg):
        prefixes = [str(p).lower() for p in (kind.get("rider_prefixes") or [])]
        prefixes.extend(str(p).lower() for p in (kind.get("mount_prefixes") or []))
        if _model_has_prefix(model, prefixes):
            return True
    return False


def find_mount_pair_for_rider_template(
    tpl: dict[str, Any],
    mount_pair_donors_by_kind: dict[str, list[MountPairDonor]],
) -> MountPairDonor | None:
    """捐皮模板若是成套骑手，返回同 suffix 的 rider+mount 对。"""
    tpl_id = str(tpl.get("template_id", ""))
    model = str(tpl.get("model", "")).lower()
    donor_entity = str(tpl.get("donor_entity") or "")
    suffix = mount_entity_suffix(donor_entity) if donor_entity else ""
    fallback: MountPairDonor | None = None
    for pairs in mount_pair_donors_by_kind.values():
        for pair in pairs:
            rider_tpl = pair.rider_tpl
            if tpl_id and tpl_id == str(rider_tpl.get("template_id", "")):
                return pair
            if model != str(rider_tpl.get("model", "")).lower():
                continue
            rider_suffix = mount_entity_suffix(
                str(rider_tpl.get("donor_entity") or "")
            )
            if suffix and rider_suffix and suffix == rider_suffix:
                return pair
            if fallback is None:
                fallback = pair
    return fallback


def build_global_mount_pair_pool(
    mount_pair_donors_by_kind: dict[str, list[MountPairDonor]],
) -> list[MountPairDonor]:
    """全部成套骑马捐皮（骑手+马已配对），供有马槽的骑手槽互换。"""
    seen: set[str] = set()
    out: list[MountPairDonor] = []
    for pairs in mount_pair_donors_by_kind.values():
        for pair in pairs:
            pid = str(pair.pair_id)
            if pid in seen:
                continue
            seen.add(pid)
            out.append(pair)
    return out


def mount_pair_kind_label(
    pair: MountPairDonor, categories_cfg: dict[str, Any]
) -> str:
    kind_id = str(pair.kind_id or "")
    for kind in mount_pair_kind_configs(categories_cfg):
        if str(kind.get("id", "")) == kind_id:
            return str(kind.get("label_zh") or kind_id)
    return "骑马（成套）"


CNV_SUPPRESS_MOUNT_TEMPLATE = "cnv:suppress_mount"
CNV_SUPPRESS_DECORATIVE_TEMPLATE = "cnv:suppress_decorative"
CNV_DEMOUNT_TEMPLATE_SUFFIX = "|demount"


def mount_pair_pool_for_slot(
    slot_model: str,
    mount_pair_donors_by_kind: dict[str, list[MountPairDonor]],
    categories_cfg: dict[str, Any],
) -> tuple[list[MountPairDonor], str]:
    """Vanilla paired rider+mount donors for this slot model (whole unit in pool)."""
    for kind in mount_pair_kind_configs(categories_cfg):
        riders_p = [str(p).lower() for p in kind.get("rider_prefixes") or []]
        if not _model_has_prefix(slot_model, riders_p):
            continue
        kind_id = str(kind.get("id", "")).strip()
        pool = mount_pair_donors_by_kind.get(kind_id, [])
        if pool:
            label = str(kind.get("label_zh") or kind_id)
            return pool, label
    return [], ""
def slot_is_mounted_rider(slot: dict[str, Any], categories_cfg: dict[str, Any]) -> bool:
    """Rider on a horse (keeps WalkRoute); not the horse body entity."""
    model = str(slot.get("model", ""))
    if is_horse_mount_model(model, categories_cfg):
        return False
    tags = slot.get("slot_tags") or {}
    return bool(slot.get("walk_route") or tags.get("has_walk_route"))


def slot_is_mount_pair_rider_model(slot: dict[str, Any], categories_cfg: dict[str, Any]) -> bool:
    """mount_pair 骑手模型前缀（c4050/c3150/c4351…）；不含 WalkRoute 巡逻步兵。"""
    slot_model = str(slot.get("model", ""))
    for kind in mount_pair_kind_configs(categories_cfg):
        riders_p = [str(p).lower() for p in kind.get("rider_prefixes") or []]
        if _model_has_prefix(slot_model, riders_p):
            return True
    return False


def slot_is_mount_rider_slot(slot: dict[str, Any], categories_cfg: dict[str, Any]) -> bool:
    """配对/巡逻骑手槽（可抽步兵下马或成套骑马捐皮）。"""
    if slot_is_mounted_rider(slot, categories_cfg):
        return True
    return slot_is_mount_pair_rider_model(slot, categories_cfg)


def template_is_mounted_rider(tpl: dict[str, Any]) -> bool:
    """Donor came from an enemy that patrolled / fought mounted."""
    tags = tpl.get("template_tags") or {}
    return bool(tags.get("has_walk_route") or tags.get("mounted_rider"))

