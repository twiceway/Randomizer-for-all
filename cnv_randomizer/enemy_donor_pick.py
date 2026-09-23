"""T-084 B3 — donor pick / archetype lottery (extracted from enemy_randomizer_core)."""
from __future__ import annotations

import hashlib
import json
import random
import re
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from math import ceil
from pathlib import Path
from typing import Any

from boss_npc_detect import is_summon_clone_donor_template
from donor_pool_review_allowlist import normalize_category_id
from enemy_category_rules import (
    dungeon_boss_arena_pick_weights,
    evergaol_src_pick_weights,
    filter_scripted_fog_boss_donor_indices,
    fog_major_boss_swap_indices,
    is_excluded_slot_model,
    is_horse_mount_model,
    is_dlc_trash_donor_model,
    is_scripted_dungeon_main_boss_slot,
    minor_boss_src_pick_weights,
    night_model_label,
    scripted_dungeon_boss_pick_weights,
    slot_physique_bucket,
)
from enemy_mount_pairs import (
    CNV_SUPPRESS_MOUNT_TEMPLATE,
    MountPairDonor,
    build_global_mount_pair_pool,
    index_rider_mount_slot_pairs,
    mount_pair_kind_label,
    mount_pair_randomize_enabled,
    pick_mount_pair_donor,
    skip_mount_pair_entity_when_disabled,
    slot_is_mount_rider_slot,
    slot_is_mounted_rider,
)
from enemy_slot_rules import (
    _count_prep_skip_bucket,
    revalidate_prep_skip_key,
    resolve_effective_slot_skip,
    runtime_slot_skip_after_prep,
)
from enemy_pool_filters import (
    filter_prep_donor_indices_for_physique_compat,
    filter_prep_donor_indices_for_anchor_plant,
    filter_prep_donor_indices_for_slot,
)
from paths import GAME_DIR


class _ScanDonorFilterMemo:
    """Per-generate memo for hot donor-index filters in scan phase."""

    __slots__ = ("_anchor", "_msb", "_physique", "_prep_donor", "_slot", "_think")

    def __init__(self) -> None:
        self._slot: dict[tuple[Any, ...], list[int]] = {}
        self._anchor: dict[tuple[Any, ...], list[int]] = {}
        self._physique: dict[tuple[Any, ...], list[int]] = {}
        self._msb: dict[tuple[Any, ...], list[int]] = {}
        self._think: dict[tuple[Any, ...], list[int]] = {}
        self._prep_donor: dict[tuple[Any, ...], list[int]] = {}

    def prep_donor_indices_cached(
        self,
        prep: dict[str, Any],
        row: dict[str, Any],
        tgt_cat: str,
        *,
        categories_cfg: dict[str, Any],
        blocked_indices: frozenset[int] | None = None,
    ) -> list[int]:
        from enemy_slot_prep import prep_donor_indices

        block_key = (
            frozenset(blocked_indices)
            if blocked_indices is not None
            else frozenset()
        )
        key = (str(row.get("m", "")), str(row.get("n", "")), tgt_cat, block_key)
        hit = self._prep_donor.get(key)
        if hit is not None:
            return hit
        out = prep_donor_indices(
            prep,
            row,
            tgt_cat,
            blocked_indices=blocked_indices,
            categories_cfg=categories_cfg,
        )
        self._prep_donor[key] = out
        return out

    def filter_for_anchor_plant(
        self,
        prep: dict[str, Any],
        indices: list[int],
        slot: dict[str, Any],
        categories_cfg: dict[str, Any],
    ) -> list[int]:
        key = (
            str(slot.get("map_id", "")),
            str(slot.get("name", "")),
            tuple(indices),
        )
        hit = self._anchor.get(key)
        if hit is not None:
            return hit
        out = filter_prep_donor_indices_for_anchor_plant(
            prep, indices, slot, categories_cfg
        )
        self._anchor[key] = out
        return out

    def filter_for_physique_compat(
        self,
        prep: dict[str, Any],
        indices: list[int],
        slot: dict[str, Any],
        categories_cfg: dict[str, Any],
        *,
        compat_by_tid: dict[str, dict[str, Any]],
    ) -> list[int]:
        key = (
            str(slot.get("map_id", "")),
            str(slot.get("name", "")),
            tuple(indices),
        )
        hit = self._physique.get(key)
        if hit is not None:
            return hit
        out = filter_prep_donor_indices_for_physique_compat(
            prep,
            indices,
            slot,
            categories_cfg,
            compat_by_tid=compat_by_tid,
        )
        self._physique[key] = out
        return out

    def filter_for_slot(
        self,
        prep: dict[str, Any],
        indices: list[int],
        slot: dict[str, Any],
        tgt_cat: str,
        categories_cfg: dict[str, Any],
        *,
        src_cat: str,
    ) -> list[int]:
        key = (
            str(slot.get("map_id", "")),
            str(slot.get("name", "")),
            src_cat,
            tgt_cat,
            tuple(indices),
        )
        hit = self._slot.get(key)
        if hit is not None:
            return hit
        out = filter_prep_donor_indices_for_slot(
            prep,
            indices,
            slot,
            tgt_cat,
            categories_cfg,
            src_cat=src_cat,
        )
        self._slot[key] = out
        return out

    def filter_for_msb_compat(
        self,
        prep: dict[str, Any],
        indices: list[int],
        slot: dict[str, Any],
        *,
        compat_by_tid: dict[str, dict[str, Any]],
        receptor_index: dict[str, dict[str, Any]] | None,
        categories_cfg: dict[str, Any],
    ) -> list[int]:
        key = (
            str(slot.get("map_id", "")),
            str(slot.get("name", "")),
            tuple(indices),
        )
        hit = self._msb.get(key)
        if hit is not None:
            return hit
        from donor_msb_compat import filter_prep_donor_indices_for_msb_compat

        out = filter_prep_donor_indices_for_msb_compat(
            prep,
            indices,
            slot,
            compat_by_tid=compat_by_tid,
            receptor_index=receptor_index,
            categories_cfg=categories_cfg,
        )
        self._msb[key] = out
        return out

    def filter_for_runtime_think(
        self,
        prep: dict[str, Any],
        indices: list[int],
        slot: dict[str, Any],
        model_vanilla_index: dict[str, dict[str, Any]],
        *,
        categories_cfg: dict[str, Any],
    ) -> list[int]:
        key = (
            str(slot.get("map_id", "")),
            str(slot.get("name", "")),
            tuple(indices),
        )
        hit = self._think.get(key)
        if hit is not None:
            return hit
        from donor_vanilla_states import filter_prep_donor_indices_for_runtime_think

        out = filter_prep_donor_indices_for_runtime_think(
            prep,
            indices,
            slot,
            model_vanilla_index,
            categories_cfg=categories_cfg,
        )
        self._think[key] = out
        return out


def _weighted_category_try_order(
    norm: dict[str, Any],
    rng: Any,
) -> list[str]:
    """Primary weighted tgt_cat first, then remaining by weight (pool-empty fallback)."""
    weights = {
        normalize_category_id(k): float(v)
        for k, v in norm.items()
        if float(v) > 0
    }
    if not weights:
        return []
    primary = normalize_category_id(weighted_choice(weights, rng))
    rest = sorted(
        [cat for cat in weights if cat != primary],
        key=lambda cat: -weights[cat],
    )
    return [primary] + rest


def _audit_spawn_plan_gaps(
    pick_plans: list[_SlotPickPlan],
    assignments: list[dict[str, Any]],
    warnings: list[str],
) -> int:
    """参与抽签但无 spawn 行 → 真机显示原版；禁止静默丢失。"""
    assigned = {
        (str(a.get("map_id", "")), str(a.get("entity_name", "")))
        for a in assignments
        if not a.get("suppress_mount") and str(a.get("template_id", "")) != CNV_SUPPRESS_MOUNT_TEMPLATE
    }
    missing: list[tuple[str, str]] = []
    for plan in pick_plans:
        key = (plan.map_id, plan.entity_name)
        if key not in assigned:
            missing.append(key)
    for map_id, entity in missing[:25]:
        warnings.append(
            f"spawn_plan_gap {map_id}:{entity} "
            "(已抽签但无spawn行→真机原版；查empty pool/physique/mount阻断)"
        )
    if len(missing) > 25:
        warnings.append(f"spawn_plan_gap_more={len(missing) - 25}")
    return len(missing)


@dataclass(frozen=True)
class ArchetypeIndex:
    trash_model_to_archetype: dict[str, str]
    trash_archetype_labels: dict[str, str]
    trash_archetype_ids: tuple[str, ...]
    trash_model_set: frozenset[str]

    def is_trash_donor_model(self, model: str) -> bool:
        return (model or "").lower() in self.trash_model_set

    def trash_archetype_for_model(self, model: str) -> str:
        return self.trash_model_to_archetype.get((model or "").lower(), "")

    def label_for(self, archetype_id: str, tgt_cat: str, model: str = "") -> str:
        if tgt_cat == "trash":
            return self.trash_archetype_labels.get(archetype_id, archetype_id)
        return model or archetype_id


ARCHETYPE_INDEX_CACHE: ArchetypeIndex | None = None


def load_archetype_index(categories_cfg: dict[str, Any] | None = None) -> ArchetypeIndex:
    from enemy_randomizer_core import DEFAULT_ARCHETYPES_PATH, SCRIPT_DIR, _load_json
    global ARCHETYPE_INDEX_CACHE
    if ARCHETYPE_INDEX_CACHE is not None:
        return ARCHETYPE_INDEX_CACHE
    path = DEFAULT_ARCHETYPES_PATH
    if categories_cfg:
        raw_path = categories_cfg.get("archetypes_path")
        if raw_path:
            p = Path(str(raw_path))
            path = p if p.is_absolute() else SCRIPT_DIR / p
    data = _load_json(path) if path.is_file() else {}
    model_to_arch: dict[str, str] = {}
    labels: dict[str, str] = {}
    arch_ids: list[str] = []
    for raw in data.get("trash_archetypes") or []:
        arch_id = str(raw.get("id", "")).strip()
        if not arch_id:
            continue
        arch_ids.append(arch_id)
        labels[arch_id] = str(raw.get("label_zh") or arch_id)
        for m in raw.get("models") or []:
            model_to_arch[str(m).lower()] = arch_id
    ARCHETYPE_INDEX_CACHE = ArchetypeIndex(
        trash_model_to_archetype=model_to_arch,
        trash_archetype_labels=labels,
        trash_archetype_ids=tuple(arch_ids),
        trash_model_set=frozenset(model_to_arch.keys()),
    )
    return ARCHETYPE_INDEX_CACHE


def get_archetype_index(categories_cfg: dict[str, Any] | None = None) -> ArchetypeIndex:
    return load_archetype_index(categories_cfg)


def group_pool_by_archetype(
    pool: list[dict[str, Any]],
    tgt_cat: str,
    archetype_index: ArchetypeIndex,
) -> dict[str, list[dict[str, Any]]]:
    buckets: dict[str, list[dict[str, Any]]] = {}
    for tpl in pool:
        model = str(tpl.get("model", "")).lower()
        if tgt_cat == "trash":
            arch_id = archetype_index.trash_archetype_for_model(model)
            if not arch_id:
                continue
        else:
            arch_id = model
        buckets.setdefault(arch_id, []).append(tpl)
    return buckets


def resolve_donor_archetype_weight(archetype_id: str, categories_cfg: dict[str, Any]) -> float:
    """legacy：捐皮第 2 层静态相对权重；见 donor_archetype_weights。"""
    raw = categories_cfg.get("donor_archetype_weights") or {}
    return max(0.0, float(raw.get(archetype_id, 1.0)))


_TRASH_REVIEW_GROUP_BY_MODEL: dict[str, str] | None = None


_TRASH_REVIEW_GROUP_BY_ARCHETYPE: dict[str, str] | None = None


def _load_trash_review_group_by_model() -> dict[str, str]:
    from enemy_randomizer_core import SCRIPT_DIR, _load_json
    global _TRASH_REVIEW_GROUP_BY_MODEL
    if _TRASH_REVIEW_GROUP_BY_MODEL is not None:
        return _TRASH_REVIEW_GROUP_BY_MODEL
    path = SCRIPT_DIR / "trash_review_group_by_model.json"
    if not path.is_file():
        _TRASH_REVIEW_GROUP_BY_MODEL = {}
        return _TRASH_REVIEW_GROUP_BY_MODEL
    raw = _load_json(path)
    _TRASH_REVIEW_GROUP_BY_MODEL = {
        str(k).lower(): str(v) for k, v in (raw or {}).items() if str(k).strip()
    }
    return _TRASH_REVIEW_GROUP_BY_MODEL


def trash_review_group_for_model(model: str) -> str:
    return _load_trash_review_group_by_model().get((model or "").lower(), "")


def trash_review_group_for_archetype(
    archetype_id: str,
    archetype_index: ArchetypeIndex,
) -> str:
    global _TRASH_REVIEW_GROUP_BY_ARCHETYPE
    if _TRASH_REVIEW_GROUP_BY_ARCHETYPE is None:
        votes: dict[str, dict[str, int]] = {}
        model_map = _load_trash_review_group_by_model()
        for arch_id in archetype_index.trash_archetype_ids:
            bucket: dict[str, int] = {}
            for model, grp in model_map.items():
                if archetype_index.trash_archetype_for_model(model) == arch_id:
                    bucket[grp] = bucket.get(grp, 0) + 1
            if bucket:
                votes[arch_id] = bucket
        _TRASH_REVIEW_GROUP_BY_ARCHETYPE = {
            arch_id: max(counts, key=counts.get)  # type: ignore[arg-type]
            for arch_id, counts in votes.items()
        }
    return _TRASH_REVIEW_GROUP_BY_ARCHETYPE.get(archetype_id, "")


def resolve_trash_review_group_weight(
    archetype_id: str,
    categories_cfg: dict[str, Any],
    *,
    archetype_index: ArchetypeIndex | None = None,
) -> float:
    """1 池审阅分组权重（动物类/植物类/士兵类等）；缺省 1.0。"""
    raw = categories_cfg.get("trash_archetype_pick") or {}
    overrides = {
        str(k): float(v)
        for k, v in (raw.get("review_group_weight_overrides") or {}).items()
        if float(v) > 0
    }
    if not overrides:
        return 1.0
    idx = archetype_index or load_archetype_index(categories_cfg)
    group = trash_review_group_for_archetype(archetype_id, idx)
    if not group:
        return 1.0
    return max(0.0, float(overrides.get(group, 1.0)))


def same_slot_model_pick_multiplier(
    donor_model: str,
    slot_model: str,
    tgt_cat: str,
    categories_cfg: dict[str, Any],
) -> float:
    """2~7 池：捐皮 model 与槽位原皮相同则整组降权（见 boss_donor_template_weights）。"""
    if tgt_cat == "trash":
        return 1.0
    mult = float(categories_cfg.get("donor_same_slot_model_weight", 0.25))
    if mult <= 0:
        return 0.0
    donor_l = _norm_model_key(donor_model)
    slot_l = _norm_model_key(slot_model)
    if donor_l and slot_l and donor_l == slot_l:
        return mult
    return 1.0


def boss_donor_template_weights(
    indices: list[int],
    donors: list[dict[str, Any]],
    slot_model: str,
    categories_cfg: dict[str, Any],
    *,
    tgt_cat: str = "",
) -> dict[int, float]:
    """2~7 池：每 model 组权重 1.0（同原皮整组 × donor_same_slot_model_weight），组内按皮均分。

    例：龙人士兵 c4650 有 10 条模板 → 每条 0.1；槽位也是 c4650 时整组 ×0.25 → 每条 0.025。
    """
    model_counts: dict[str, int] = {}
    for i in indices:
        m = str(donors[i].get("model", "")).lower()
        if m:
            model_counts[m] = model_counts.get(m, 0) + 1

    weights: dict[int, float] = {}
    for i in indices:
        m = str(donors[i].get("model", "")).lower()
        if not m:
            continue
        n = max(1, model_counts.get(m, 1))
        group_w = same_slot_model_pick_multiplier(
            m, slot_model, tgt_cat, categories_cfg
        )
        model_w = resolve_pool_model_weight(m, tgt_cat, categories_cfg)
        weights[i] = (group_w / float(n)) * model_w
    return weights


def pick_boss_donor_by_template_indices(
    prep: dict[str, Any],
    indices: list[int],
    rng: random.Random,
    *,
    tgt_cat: str,
    archetype_index: ArchetypeIndex,
    categories_cfg: dict[str, Any],
    slot_model: str = "",
) -> tuple[dict[str, Any], str, str]:
    """2~7 池（night 除外）：按 prep 模板均分权重抽签。"""
    from enemy_slot_prep import prep_donor_at

    donors = prep.get("donors") or []
    weights = boss_donor_template_weights(
        indices, donors, slot_model, categories_cfg, tgt_cat=tgt_cat
    )
    positive = {k: v for k, v in weights.items() if v > 0}
    if not positive:
        raise ValueError("all donor templates zero weight in boss pool")
    if len(positive) == 1:
        idx = next(iter(positive))
    else:
        idx = weighted_choice(normalize_row_weights(positive), rng)
    tpl = prep_donor_at(prep, idx)
    model = str(tpl.get("model", "")).lower()
    arch_id = model
    label = archetype_index.label_for(arch_id, tgt_cat, arch_id)
    return tpl, arch_id, label


def trash_archetype_pick_mode(categories_cfg: dict[str, Any]) -> str:
    raw = categories_cfg.get("trash_archetype_pick") or {}
    mode = str(raw.get("mode") or "balanced").strip().lower()
    if mode in ("legacy", "static", "weighted"):
        return "legacy"
    return "balanced"


def trash_uniform_model_within_archetype(categories_cfg: dict[str, Any]) -> bool:
    raw = categories_cfg.get("trash_archetype_pick") or {}
    if trash_archetype_pick_mode(categories_cfg) != "balanced":
        return False
    return bool(raw.get("uniform_model_within_archetype", True))


def archetype_model_counts_from_templates(
    buckets: dict[str, list[dict[str, Any]]],
) -> dict[str, int]:
    out: dict[str, int] = {}
    for arch_id, tpls in buckets.items():
        models = {
            str(t.get("model", "")).lower()
            for t in tpls
            if str(t.get("model", "")).strip()
        }
        out[arch_id] = max(1, len(models))
    return out


def archetype_model_counts_from_indices(
    buckets: dict[str, list[int]],
    donors: list[dict[str, Any]],
) -> dict[str, int]:
    out: dict[str, int] = {}
    for arch_id, indices in buckets.items():
        models: set[str] = set()
        for i in indices:
            if 0 <= i < len(donors):
                model = str(donors[i].get("model", "")).lower()
                if model:
                    models.add(model)
        out[arch_id] = max(1, len(models))
    return out


def resolve_trash_archetype_weights_balanced(
    archetype_model_counts: dict[str, int],
    categories_cfg: dict[str, Any],
    *,
    archetype_index: ArchetypeIndex | None = None,
) -> dict[str, float]:
    """1 池第 2 层：原型等权 × 桶内 distinct model 数^exponent（本槽可抽）。"""
    raw = categories_cfg.get("trash_archetype_pick") or {}
    exponent = float(raw.get("model_count_exponent", 0.4))
    exponent = max(0.0, min(1.0, exponent))
    overrides = {
        str(k): float(v)
        for k, v in (raw.get("archetype_weight_overrides") or {}).items()
        if float(v) > 0
    }
    idx = archetype_index or load_archetype_index(categories_cfg)
    weights: dict[str, float] = {}
    for arch_id, model_count in archetype_model_counts.items():
        n = max(1, int(model_count))
        w = float(n) ** exponent
        if arch_id in overrides:
            w *= overrides[arch_id]
        w *= resolve_trash_review_group_weight(
            arch_id, categories_cfg, archetype_index=idx
        )
        weights[arch_id] = w
    return weights


def pick_weighted_archetype_id(
    archetype_ids: set[str] | list[str],
    rng: random.Random,
    categories_cfg: dict[str, Any],
    *,
    tgt_cat: str = "",
    archetype_model_counts: dict[str, int] | None = None,
    slot_model: str = "",
    archetype_index: ArchetypeIndex | None = None,
) -> str:
    idx = archetype_index or load_archetype_index(categories_cfg)
    if (
        tgt_cat == "trash"
        and trash_archetype_pick_mode(categories_cfg) == "balanced"
        and archetype_model_counts
    ):
        counts = {
            arch_id: archetype_model_counts.get(arch_id, 1) for arch_id in archetype_ids
        }
        weights = resolve_trash_archetype_weights_balanced(
            counts, categories_cfg, archetype_index=idx
        )
    elif tgt_cat == "trash":
        weights = {
            arch_id: resolve_donor_archetype_weight(arch_id, categories_cfg)
            * resolve_trash_review_group_weight(
                arch_id, categories_cfg, archetype_index=idx
            )
            for arch_id in archetype_ids
        }
    else:
        weights = {
            arch_id: resolve_donor_archetype_weight(arch_id, categories_cfg)
            for arch_id in archetype_ids
        }
    positive = {k: v for k, v in weights.items() if v > 0}
    if not positive:
        raise ValueError("all archetypes zero weight in donor pool")
    if len(positive) == 1:
        return next(iter(positive))
    return weighted_choice(normalize_row_weights(positive), rng)


def resolve_night_npc_weight(
    npc: int | str,
    categories_cfg: dict[str, Any],
) -> float:
    """5 池红灵：单皮（npc）相对权重；见 night_npc_weight_overrides。"""
    raw = categories_cfg.get("night_npc_weight_overrides") or {}
    key = str(npc)
    if key in raw:
        return max(0.0, float(raw[key]))
    return 1.0


def resolve_pool_model_weight(
    model: str,
    tgt_cat: str,
    categories_cfg: dict[str, Any],
) -> float:
    """同池（tgt_cat）内单皮相对权重；缺省 1.0。见 pool_model_weight_overrides。"""
    if not tgt_cat:
        return 1.0
    tgt = normalize_category_id(tgt_cat)
    overrides = categories_cfg.get("pool_model_weight_overrides") or {}
    pool = overrides.get(tgt) or {}
    model_l = (model or "").lower()
    if model_l in pool:
        return max(0.0, float(pool[model_l]))
    for prefix, w in pool.items():
        pfx = str(prefix).lower()
        if model_l.startswith(pfx):
            return max(0.0, float(w))
    return 1.0


def resolve_donor_model_weight(
    model: str,
    categories_cfg: dict[str, Any],
    *,
    tgt_cat: str = "",
) -> float:
    """捐皮 model 相对权重；见 donor_model_weights + pool_model_weight_overrides。"""
    raw = categories_cfg.get("donor_model_weights") or {}
    model_l = (model or "").lower()
    if model_l in raw:
        weight = max(0.0, float(raw[model_l]))
    else:
        weight = 1.0
        for prefix, w in raw.items():
            pfx = str(prefix).lower()
            if model_l.startswith(pfx):
                weight = max(0.0, float(w))
                break
    if is_dlc_trash_donor_model(model_l, categories_cfg):
        mult = float(categories_cfg.get("dlc_trash_pick_multiplier") or 1.0)
        if mult > 0:
            weight *= mult
    if tgt_cat:
        weight *= resolve_pool_model_weight(model_l, tgt_cat, categories_cfg)
    return weight


def pick_donor_model_from_bucket(
    by_model: dict[str, list[dict[str, Any]]],
    rng: random.Random,
    categories_cfg: dict[str, Any],
    *,
    tgt_cat: str = "",
) -> str:
    uniform = tgt_cat == "trash" and trash_uniform_model_within_archetype(categories_cfg)
    return _pick_donor_model_key(
        set(by_model.keys()), rng, categories_cfg, uniform_within_archetype=uniform, tgt_cat=tgt_cat
    )


def _pick_donor_model_key(
    models: set[str] | list[str],
    rng: random.Random,
    categories_cfg: dict[str, Any],
    *,
    uniform_within_archetype: bool = False,
    tgt_cat: str = "",
) -> str:
    if uniform_within_archetype:
        weights = {model: 1.0 for model in models}
    else:
        weights = {
            model: resolve_donor_model_weight(model, categories_cfg, tgt_cat=tgt_cat)
            for model in models
        }
    positive = {k: v for k, v in weights.items() if v > 0}
    if not positive:
        raise ValueError("all donor models zero weight in archetype bucket")
    if len(positive) == 1:
        return next(iter(positive))
    norm = normalize_row_weights(positive)
    return weighted_choice(norm, rng)


_POOL_PICK_MODES = frozenset(
    {"balanced_npc", "uniform_npc", "model_weighted", "uniform_template"}
)


def night_pick_mode(categories_cfg: dict[str, Any]) -> str:
    """5 池红灵抽签模式：balanced_npc | uniform_npc | model_weighted | uniform_template。"""
    raw = str(categories_cfg.get("night_pick_mode") or "balanced_npc").strip().lower()
    if raw in _POOL_PICK_MODES:
        return raw
    return "balanced_npc"


def pool_pick_mode(categories_cfg: dict[str, Any], tgt_cat: str) -> str:
    """目标池抽签模式；night 仍可读 night_pick_mode，其余读 pool_pick_mode_default / overrides。"""
    tgt = normalize_category_id(tgt_cat)
    overrides = categories_cfg.get("pool_pick_mode_overrides") or {}
    if tgt in overrides:
        raw = str(overrides[tgt]).strip().lower()
        if raw in _POOL_PICK_MODES:
            return raw
    if tgt == "night":
        return night_pick_mode(categories_cfg)
    raw = str(categories_cfg.get("pool_pick_mode_default") or "balanced_npc").strip().lower()
    if raw in _POOL_PICK_MODES:
        return raw
    return "balanced_npc"


def pool_pick_uses_balanced_deal(categories_cfg: dict[str, Any], tgt_cat: str) -> bool:
    return pool_pick_mode(categories_cfg, tgt_cat) == "balanced_npc"


def _indices_by_npc(
    indices: list[int],
    donors: list[dict[str, Any]],
) -> dict[Any, list[int]]:
    out: dict[Any, list[int]] = {}
    for i in indices:
        if not (0 <= i < len(donors)):
            continue
        npc = donors[i].get("npc")
        if npc is None:
            continue
        out.setdefault(npc, []).append(i)
    return out


def _uniform_npc_pick_weights(
    by_npc: dict[Any, list[int]],
    donors: list[dict[str, Any]],
    categories_cfg: dict[str, Any],
    *,
    tgt_cat: str,
    slot_model: str = "",
) -> dict[Any, float]:
    weights: dict[Any, float] = {}
    for npc, idxs in by_npc.items():
        i = idxs[0]
        m = str(donors[i].get("model", "")).lower()
        w = resolve_pool_model_weight(m, tgt_cat, categories_cfg)
        w *= same_slot_model_pick_multiplier(
            m, slot_model, tgt_cat, categories_cfg
        )
        if tgt_cat == "night":
            w *= resolve_night_npc_weight(npc, categories_cfg)
        weights[npc] = w
    return weights


def _pick_uniform_npc_donor_index(
    indices: list[int],
    donors: list[dict[str, Any]],
    rng: random.Random,
    categories_cfg: dict[str, Any],
    *,
    tgt_cat: str,
    slot_model: str = "",
) -> int:
    """各池 uniform_npc：先均匀抽 npc（可叠 pool_model / 同槽降权），再随机模板。"""
    valid = [i for i in indices if 0 <= i < len(donors)]
    if not valid:
        raise ValueError(f"empty donor pool for {tgt_cat}")
    if len(valid) == 1:
        return valid[0]
    by_npc = _indices_by_npc(indices, donors)
    if not by_npc:
        raise ValueError(f"empty donor pool for {tgt_cat}")
    if len(by_npc) == 1:
        npc = next(iter(by_npc))
    else:
        npc_weights = _uniform_npc_pick_weights(
            by_npc, donors, categories_cfg, tgt_cat=tgt_cat, slot_model=slot_model
        )
        positive = {k: v for k, v in npc_weights.items() if v > 0}
        if not positive:
            raise ValueError(f"empty donor pool for {tgt_cat}")
        if len(positive) == 1:
            npc = next(iter(positive))
        else:
            npc = weighted_choice(normalize_row_weights(positive), rng)
    return rng.choice(by_npc[npc])


def _night_npc_pick_weights(
    by_npc: dict[Any, list[int]],
    donors: list[dict[str, Any]],
    categories_cfg: dict[str, Any],
) -> dict[Any, float]:
    return _uniform_npc_pick_weights(
        by_npc, donors, categories_cfg, tgt_cat="night", slot_model=""
    )


def night_donor_template_weights(
    indices: list[int],
    donors: list[dict[str, Any]],
    categories_cfg: dict[str, Any],
) -> dict[int, float]:
    """5 池红灵（model_weighted）：每皮一票 × pool_model × night_npc（同 model 组内均分）。"""
    model_counts: dict[str, int] = {}
    for i in indices:
        if not (0 <= i < len(donors)):
            continue
        m = str(donors[i].get("model", "")).lower()
        if m:
            model_counts[m] = model_counts.get(m, 0) + 1
    weights: dict[int, float] = {}
    for i in indices:
        if not (0 <= i < len(donors)):
            continue
        m = str(donors[i].get("model", "")).lower()
        if not m:
            continue
        n = max(1, model_counts.get(m, 1))
        model_w = resolve_pool_model_weight(m, "night", categories_cfg)
        npc_w = resolve_night_npc_weight(donors[i].get("npc", 0), categories_cfg)
        weights[i] = (model_w / float(n)) * npc_w
    return weights


def _pick_pool_donor_index(
    indices: list[int],
    donors: list[dict[str, Any]],
    rng: random.Random,
    categories_cfg: dict[str, Any],
    *,
    tgt_cat: str,
    slot_model: str = "",
) -> int:
    """按 pool_pick_mode / night_pick_mode 从 prep 索引池抽一皮。"""
    mode = pool_pick_mode(categories_cfg, tgt_cat)
    valid = [i for i in indices if 0 <= i < len(donors)]
    if not valid:
        raise ValueError(f"empty donor pool for {tgt_cat}")
    if len(valid) == 1:
        return valid[0]

    if mode == "uniform_npc":
        return _pick_uniform_npc_donor_index(
            indices,
            donors,
            rng,
            categories_cfg,
            tgt_cat=tgt_cat,
            slot_model=slot_model,
        )

    if mode == "uniform_template":
        positive = {i: 1.0 for i in valid}
    elif tgt_cat == "night":
        weights = night_donor_template_weights(indices, donors, categories_cfg)
        positive = {k: v for k, v in weights.items() if v > 0}
        if not positive:
            raise ValueError("empty red spirit pool")
    else:
        weights = boss_donor_template_weights(
            indices, donors, slot_model, categories_cfg, tgt_cat=tgt_cat
        )
        positive = {k: v for k, v in weights.items() if v > 0}
        if not positive:
            raise ValueError(f"all donor templates zero weight in {tgt_cat} pool")
    if len(positive) == 1:
        return next(iter(positive))
    return weighted_choice(normalize_row_weights(positive), rng)


def _pick_night_donor_index(
    indices: list[int],
    donors: list[dict[str, Any]],
    rng: random.Random,
    categories_cfg: dict[str, Any],
) -> int:
    """5 池红灵：见 night_pick_mode（委托 _pick_pool_donor_index）。"""
    return _pick_pool_donor_index(
        indices, donors, rng, categories_cfg, tgt_cat="night", slot_model=""
    )


def _eligible_donor_indices_for_pick(
    indices: list[int],
    donors: list[dict[str, Any]],
    categories_cfg: dict[str, Any],
    *,
    tgt_cat: str,
    slot_model: str = "",
) -> list[int]:
    eligible: list[int] = []
    for i in indices:
        if not (0 <= i < len(donors)):
            continue
        tpl = donors[i]
        m = str(tpl.get("model", "")).lower()
        w = resolve_pool_model_weight(m, tgt_cat, categories_cfg)
        w *= same_slot_model_pick_multiplier(
            m, slot_model, tgt_cat, categories_cfg
        )
        if tgt_cat == "night":
            w *= resolve_night_npc_weight(tpl.get("npc", 0), categories_cfg)
        if w > 0:
            eligible.append(i)
    return eligible or [i for i in indices if 0 <= i < len(donors)]


def _plan_eligible_by_npc(
    plan: "_SlotPickPlan",
    donors: list[dict[str, Any]],
    categories_cfg: dict[str, Any],
    *,
    tgt_cat: str,
) -> dict[Any, list[int]]:
    eligible = _eligible_donor_indices_for_pick(
        plan.donor_indices,
        donors,
        categories_cfg,
        tgt_cat=tgt_cat,
        slot_model=str(plan.slot.get("model", "")),
    )
    by_npc: dict[Any, list[int]] = {}
    for i in eligible:
        npc = donors[i].get("npc")
        if npc is None:
            continue
        by_npc.setdefault(npc, []).append(i)
    return by_npc


def _clip_npc_balance_weight(w: float, categories_cfg: dict[str, Any]) -> float:
    raw = categories_cfg.get("pool_npc_balance_auto_clip") or [0.25, 8.0]
    lo = float(raw[0]) if len(raw) > 0 else 0.25
    hi = float(raw[1]) if len(raw) > 1 else 8.0
    return max(lo, min(hi, w))


def identify_structural_tail_npcs(
    npc_slot_cap: dict[Any, int],
    categories_cfg: dict[str, Any],
    tgt_cat: str,
    *,
    donors: list[dict[str, Any]] | None = None,
    npc_to_model: dict[Any, str] | None = None,
) -> set[Any]:
    """T-098：不再按可投槽自动打尾；仅 ``pool_npc_structural_tail_npcs`` 手工冷门。

    ``donors`` / ``npc_to_model`` / ``npc_slot_cap`` 保留签名兼容旧调用。
    """
    _ = (npc_slot_cap, donors, npc_to_model)
    manual_raw = (categories_cfg.get("pool_npc_structural_tail_npcs") or {}).get(
        tgt_cat
    ) or {}
    manual: set[Any] = set()
    for k in manual_raw:
        try:
            manual.add(int(k))
        except (TypeError, ValueError):
            manual.add(k)
    return manual


def build_pool_npc_balance_weights(
    npc_slot_cap: dict[Any, int],
    categories_cfg: dict[str, Any],
    tgt_cat: str,
    *,
    structural_tail: set[Any] | None = None,
    donors: list[dict[str, Any]] | None = None,
) -> dict[Any, float]:
    """balanced_npc：主桌恒 1.0；仅手工冷门可读 overrides / 自动权重。"""
    structural_tail = structural_tail or identify_structural_tail_npcs(
        npc_slot_cap, categories_cfg, tgt_cat, donors=donors
    )
    overrides = (categories_cfg.get("pool_npc_balance_weight_overrides") or {}).get(
        tgt_cat
    ) or {}
    auto_on = bool(categories_cfg.get("pool_npc_balance_auto_enabled", True))
    weights: dict[Any, float] = {}
    caps = [max(1, int(c)) for c in npc_slot_cap.values()]
    if not caps:
        return weights
    ref = float(statistics.median(caps))
    for npc, cap in npc_slot_cap.items():
        if npc not in structural_tail:
            weights[npc] = 1.0
            continue
        key = str(npc)
        if key in overrides:
            weights[npc] = max(0.0, float(overrides[key]))
            continue
        if not auto_on:
            weights[npc] = 1.0
            continue
        auto = ref / float(max(1, int(cap)))
        weights[npc] = _clip_npc_balance_weight(auto, categories_cfg)
    return weights


def _pick_balanced_npc_for_slot(
    by_npc: dict[Any, list[int]],
    npc_counts: Counter[Any],
    npc_slot_cap: dict[Any, int],
    npc_balance_weights: dict[Any, float],
    soft_cap: int,
    rng: random.Random,
    *,
    structural_tail: set[Any] | None = None,
) -> Any | None:
    """T-098：主桌全员；稀缺槽侧已排序。硬顶=可投槽；软上限下最少出场优先。

    手工 ``structural_tail``（点名冷门）：同槽还有主桌皮时不抽冷门。
    """
    structural_tail = structural_tail or set()
    if not by_npc:
        return None

    main_keys = [npc for npc in by_npc if npc not in structural_tail]
    active_keys = main_keys if main_keys else list(by_npc.keys())
    on_main_table = bool(main_keys)

    def _weight(npc: Any) -> float:
        if on_main_table:
            return 1.0
        return max(0.25, float(npc_balance_weights.get(npc, 1.0)))

    def _effective(npc: Any) -> float:
        w = _weight(npc)
        exp = 1.5 if w > 1.25 else 1.0
        return float(npc_counts.get(npc, 0)) / (w**exp)

    physical = [
        npc
        for npc in active_keys
        if npc_counts.get(npc, 0) < max(1, int(npc_slot_cap.get(npc, 1)))
    ]
    if not physical:
        physical = list(active_keys)
    under_soft = [npc for npc in physical if npc_counts.get(npc, 0) < soft_cap]
    if under_soft:
        pool = under_soft
        over_soft = False
    else:
        pool = physical
        over_soft = True

    def _rank(npc: Any) -> tuple[float, ...]:
        count = npc_counts.get(npc, 0)
        tie = rng.randint(0, 1_000_000)
        if on_main_table:
            return (float(count), float(tie))
        eff = _effective(npc)
        slots = max(1, int(npc_slot_cap.get(npc, 1)))
        util = eff / float(slots)
        if over_soft:
            return (util, eff, float(count), float(tie))
        return (eff, util, float(count), float(tie))

    return min(pool, key=_rank)


def _contract_whitelist_pool_sizes() -> dict[str, int]:
    """捐皮契约白名单各运行时池种数（用于 balanced 软上限）。"""
    from paths import DONOR_POOL_CONTRACT_DIR

    wl_json = DONOR_POOL_CONTRACT_DIR / "捐皮白名单_当前.json"
    if not wl_json.is_file():
        return {}
    try:
        wl = json.loads(wl_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    pool_to_tgt = {
        1: "trash",
        2: "elite",
        3: "minor_boss",
        4: "evergaol",
        5: "night",
        6: "major_boss",
    }
    out: dict[str, int] = {}
    for pool_s, rows in (wl.get("rows_by_pool") or {}).items():
        try:
            pool_n = int(pool_s)
        except (TypeError, ValueError):
            continue
        tgt = pool_to_tgt.get(pool_n)
        if tgt and isinstance(rows, list):
            out[tgt] = len(rows)
    return out


def build_balanced_pool_donor_assignments(
    pick_plans: list["_SlotPickPlan"],
    prep: dict[str, Any],
    seed: int,
    categories_cfg: dict[str, Any],
) -> dict[tuple[str, str], int]:
    """同池跨槽压平：稀缺槽优先 + 软上限 cap + 最少负载（目标接近 P5 均匀度）。"""
    donors = prep.get("donors") or []
    by_tgt: dict[str, list[_SlotPickPlan]] = defaultdict(list)
    for plan in pick_plans:
        if plan.mount_pair_pool:
            continue
        if not pool_pick_uses_balanced_deal(categories_cfg, plan.tgt_cat):
            continue
        by_tgt[plan.tgt_cat].append(plan)

    out: dict[tuple[str, str], int] = {}
    for tgt_cat, plans in by_tgt.items():
        rng = random.Random(f"{seed}:balanced:{tgt_cat}")
        plan_eligible: list[tuple[_SlotPickPlan, dict[Any, list[int]]]] = []
        npc_slot_cap: Counter[Any] = Counter()
        for plan in plans:
            by_npc = _plan_eligible_by_npc(plan, donors, categories_cfg, tgt_cat=tgt_cat)
            if not by_npc:
                continue
            plan_eligible.append((plan, by_npc))
            for npc in by_npc:
                npc_slot_cap[npc] += 1

        if not plan_eligible:
            continue

        structural_tail = identify_structural_tail_npcs(
            dict(npc_slot_cap), categories_cfg, tgt_cat, donors=donors
        )
        # T-098：软上限分母=本池全部参与皮（不再用 fair_npcs）
        wl_sizes = _contract_whitelist_pool_sizes()
        k = len(npc_slot_cap) or wl_sizes.get(tgt_cat) or 1
        soft_cap = max(1, ceil(len(plan_eligible) / max(1, k)))
        balance_weights = build_pool_npc_balance_weights(
            dict(npc_slot_cap),
            categories_cfg,
            tgt_cat,
            structural_tail=structural_tail,
            donors=donors,
        )

        plan_eligible.sort(
            key=lambda item: (len(item[1]), rng.randint(0, 1_000_000))
        )

        npc_counts: Counter[Any] = Counter()
        for plan, by_npc in plan_eligible:
            npc = _pick_balanced_npc_for_slot(
                by_npc,
                npc_counts,
                npc_slot_cap,
                balance_weights,
                soft_cap,
                rng,
                structural_tail=structural_tail,
            )
            if npc is None:
                continue
            idx = rng.choice(by_npc[npc])
            npc_counts[npc] += 1
            out[(plan.map_id, plan.entity_name)] = idx
    return out


def donor_pick_from_prep_index(
    prep: dict[str, Any],
    idx: int,
    *,
    tgt_cat: str,
    archetype_index: ArchetypeIndex,
    categories_cfg: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], str, str]:
    from enemy_slot_prep import prep_donor_at

    tpl = prep_donor_at(prep, idx)
    model = str(tpl.get("model", "")).lower()
    cfg = categories_cfg or {}
    if tgt_cat == "night":
        return tpl, "red_spirit", night_model_label(model, cfg)
    if tgt_cat == "trash":
        arch_id = archetype_index.trash_archetype_for_model(model) or model
        label = archetype_index.label_for(arch_id, tgt_cat, arch_id)
        return tpl, arch_id, label
    return tpl, model, archetype_index.label_for(model, tgt_cat, model)


def pick_donor_by_archetype(
    pool: list[dict[str, Any]],
    rng: random.Random,
    *,
    tgt_cat: str,
    archetype_index: ArchetypeIndex,
    categories_cfg: dict[str, Any] | None = None,
    slot_model: str = "",
) -> tuple[dict[str, Any], str, str]:
    """第2层原型（1 池 balanced：等权+按 model 数微调）→ 第3层 model → template 均匀。

    `pool_pick_mode_default`（默认 uniform_npc）：各池先均匀抽 npc 再抽模板。
    `night` 仍可读 `night_pick_mode`；`model_weighted` 时 1 池走原型、2~6 池走 model 组均分。
    """
    cfg = categories_cfg or {}
    mode = pool_pick_mode(cfg, tgt_cat)

    if mode == "uniform_npc":
        if not pool:
            raise ValueError(f"empty donor pool for {tgt_cat}")
        idx = _pick_uniform_npc_donor_index(
            list(range(len(pool))),
            pool,
            rng,
            cfg,
            tgt_cat=tgt_cat,
            slot_model=slot_model,
        )
        tpl = pool[idx]
        model = str(tpl.get("model", "")).lower()
        if tgt_cat == "night":
            return tpl, "red_spirit", model
        if tgt_cat == "trash":
            arch_id = archetype_index.trash_archetype_for_model(model) or model
            label = archetype_index.label_for(arch_id, tgt_cat, arch_id)
            return tpl, arch_id, label
        return tpl, model, archetype_index.label_for(model, tgt_cat, model)

    if mode == "uniform_template":
        if not pool:
            raise ValueError(f"empty donor pool for {tgt_cat}")
        idx = rng.choice(range(len(pool)))
        tpl = pool[idx]
        model = str(tpl.get("model", "")).lower()
        if tgt_cat == "night":
            return tpl, "red_spirit", model
        if tgt_cat == "trash":
            arch_id = archetype_index.trash_archetype_for_model(model) or model
            return tpl, arch_id, archetype_index.label_for(arch_id, tgt_cat, arch_id)
        return tpl, model, archetype_index.label_for(model, tgt_cat, model)

    if tgt_cat == "night":
        if not pool:
            raise ValueError("empty red spirit pool")
        cfg = categories_cfg or {}
        idx = _pick_night_donor_index(list(range(len(pool))), pool, rng, cfg)
        tpl = pool[idx]
        model = str(tpl.get("model", "")).lower()
        return tpl, "red_spirit", model

    cfg = categories_cfg or {}
    if tgt_cat != "trash":
        indices = list(range(len(pool)))
        weights = boss_donor_template_weights(
            indices,
            pool,
            slot_model,
            cfg,
            tgt_cat=tgt_cat,
        )
        positive = {k: v for k, v in weights.items() if v > 0}
        if not positive:
            raise ValueError("all donor templates zero weight in boss pool")
        if len(positive) == 1:
            idx = next(iter(positive))
        else:
            idx = weighted_choice(normalize_row_weights(positive), rng)
        tpl = pool[idx]
        model = str(tpl.get("model", "")).lower()
        return tpl, model, archetype_index.label_for(model, tgt_cat, model)

    buckets = group_pool_by_archetype(pool, tgt_cat, archetype_index)
    if not buckets:
        raise ValueError("empty archetype pool")
    cfg = categories_cfg or {}
    arch_counts = (
        archetype_model_counts_from_templates(buckets) if tgt_cat == "trash" else None
    )
    arch_id = pick_weighted_archetype_id(
        buckets.keys(),
        rng,
        cfg,
        tgt_cat=tgt_cat,
        archetype_model_counts=arch_counts,
        slot_model=slot_model,
        archetype_index=archetype_index,
    )
    label = archetype_index.label_for(arch_id, tgt_cat, arch_id)
    by_model = _group_templates_by_model(buckets[arch_id])
    model = pick_donor_model_from_bucket(by_model, rng, cfg, tgt_cat=tgt_cat)
    tpl = rng.choice(by_model[model])
    return tpl, arch_id, label


class SameModelExhausted(ValueError):
    """No donor skin differs from the slot model."""


def _norm_model_key(model: str) -> str:
    """Normalize to cXXXX when possible so entity-name-like values still match."""
    m = (model or "").strip().lower()
    if not m:
        return ""
    hit = re.match(r"(c\d{4})", m)
    return hit.group(1) if hit else m


def indices_excluding_slot_model(
    prep: dict[str, Any],
    indices: list[int],
    slot_model: str,
    tgt_cat: str,
) -> list[int]:
    """Drop donors whose model equals the slot. Widen to the same category if needed."""
    donors = prep.get("donors") or []
    slot_m = _norm_model_key(slot_model)
    valid = [i for i in indices if 0 <= i < len(donors)]
    if not slot_m:
        return valid
    kept = [
        i
        for i in valid
        if _norm_model_key(str(donors[i].get("model", ""))) != slot_m
    ]
    if kept:
        return kept
    cache = prep.setdefault("_same_model_widen", {})
    if tgt_cat not in cache:
        seen: list[int] = []
        seen_set: set[int] = set()
        for slot in prep.get("slots") or []:
            for i in (slot.get("o") or {}).get(tgt_cat) or []:
                if i not in seen_set:
                    seen_set.add(i)
                    seen.append(i)
        cache[tgt_cat] = seen
    return [
        i
        for i in cache[tgt_cat]
        if 0 <= i < len(donors)
        and _norm_model_key(str(donors[i].get("model", ""))) != slot_m
    ]


def pick_donor_by_archetype_indices(
    prep: dict[str, Any],
    donor_indices: list[int],
    rng: random.Random,
    *,
    tgt_cat: str,
    archetype_index: ArchetypeIndex,
    categories_cfg: dict[str, Any] | None = None,
    slot_model: str = "",
) -> tuple[dict[str, Any], str, str]:
    """Pick one donor from prep catalog indices — expands a single template only."""
    from enemy_slot_prep import prep_donor_at

    donors = prep.get("donors") or []
    indices = indices_excluding_slot_model(prep, list(donor_indices), slot_model, tgt_cat)
    if not indices:
        raise SameModelExhausted(slot_model or "?")

    cfg = categories_cfg or {}
    mode = pool_pick_mode(cfg, tgt_cat)

    if mode in ("uniform_npc", "uniform_template"):
        if mode == "uniform_npc":
            idx = _pick_uniform_npc_donor_index(
                indices,
                donors,
                rng,
                cfg,
                tgt_cat=tgt_cat,
                slot_model=slot_model,
            )
        else:
            idx = _pick_pool_donor_index(
                indices,
                donors,
                rng,
                cfg,
                tgt_cat=tgt_cat,
                slot_model=slot_model,
            )
        tpl = prep_donor_at(prep, idx)
        model = str(tpl.get("model", "")).lower()
        if tgt_cat == "night":
            return tpl, "red_spirit", model
        if tgt_cat == "trash":
            arch_id = archetype_index.trash_archetype_for_model(model) or model
            label = archetype_index.label_for(arch_id, tgt_cat, arch_id)
            return tpl, arch_id, label
        return tpl, model, archetype_index.label_for(model, tgt_cat, model)

    if tgt_cat == "night":
        idx = _pick_night_donor_index(indices, donors, rng, cfg)
        tpl = prep_donor_at(prep, idx)
        model = str(tpl.get("model", "")).lower()
        return tpl, "red_spirit", model

    if tgt_cat != "trash":
        return pick_boss_donor_by_template_indices(
            prep,
            indices,
            rng,
            tgt_cat=tgt_cat,
            archetype_index=archetype_index,
            categories_cfg=cfg,
            slot_model=slot_model,
        )

    buckets: dict[str, list[int]] = {}
    for i in indices:
        model = str(donors[i].get("model", "")).lower()
        arch_id = archetype_index.trash_archetype_for_model(model)
        if not arch_id:
            continue
        buckets.setdefault(arch_id, []).append(i)

    if not buckets:
        raise ValueError("empty archetype pool")
    arch_counts = archetype_model_counts_from_indices(buckets, donors)
    arch_id = pick_weighted_archetype_id(
        buckets.keys(),
        rng,
        cfg,
        tgt_cat=tgt_cat,
        archetype_model_counts=arch_counts,
        slot_model=slot_model,
        archetype_index=archetype_index,
    )
    label = archetype_index.label_for(arch_id, tgt_cat, arch_id)
    by_model: dict[str, list[int]] = {}
    for i in buckets[arch_id]:
        model = str(donors[i].get("model", "")).lower()
        by_model.setdefault(model, []).append(i)

    uniform = tgt_cat == "trash" and trash_uniform_model_within_archetype(cfg)
    model = _pick_donor_model_key(
        set(by_model.keys()), rng, cfg, uniform_within_archetype=uniform
    )
    tpl = prep_donor_at(prep, rng.choice(by_model[model]))
    return tpl, arch_id, label


def drawable_category_weights(
    norm: dict[str, float],
    row: dict[str, Any],
    prep: dict[str, Any],
    slot: dict[str, Any],
    *,
    categories_cfg: dict[str, Any],
    blocked_indices: frozenset[int] | None = None,
) -> dict[str, float]:
    """抽签前收窄矩阵：仅保留本槽 prep `o` 中仍有捐皮的 tgt_cat。

    prep 建池时已走 filter_slot_donor_pool；此处只查 `o[cat]` 非空（O(类)）。
    雾门主线 Boss 槽另做 synthetic 快检。选定 tgt 后再 filter_prep_donor_indices。
    """
    from enemy_slot_prep import migrate_legacy_prep_row, prep_donor_indices

    migrate_legacy_prep_row(row)
    pools = row.get("o") or {}
    fog_slot = is_scripted_dungeon_main_boss_slot(slot, categories_cfg)
    if not pools and not fog_slot:
        return {}
    out: dict[str, float] = {}
    for cat, weight in norm.items():
        if weight <= 0:
            continue
        # 雾门 6 池：不依赖旧 prep 窄池；合成主线 Boss 互洗表可临时补进 donors
        if fog_slot and cat == "major_boss":
            swap = fog_major_boss_swap_indices(
                prep,
                categories_cfg,
                blocked_indices=blocked_indices,
            )
            if swap:
                out[cat] = weight
            continue
        ids = pools.get(cat)
        if not ids:
            continue
        if blocked_indices is not None:
            if not any(
                0 <= i < len(prep.get("donors") or []) and i not in blocked_indices
                for i in ids
            ):
                continue
        if fog_slot:
            indices = prep_donor_indices(
                prep,
                row,
                cat,
                categories_cfg=categories_cfg,
                blocked_indices=blocked_indices,
            )
            indices = filter_scripted_fog_boss_donor_indices(
                prep, slot, indices, categories_cfg=categories_cfg
            )
            if not indices:
                continue
        out[cat] = weight
    return normalize_row_weights(out)


@dataclass
class _SlotPickPlan:
    slot: dict[str, Any]
    map_id: str
    entity_name: str
    src_cat: str
    tgt_cat: str
    donor_indices: list[int]
    mount_pair_pool: list[MountPairDonor] | None = None
    partner_mount_slot: dict[str, Any] | None = None
    mount_pair_label_zh: str = ""


def slot_rng(seed: int, map_id: str, entity_name: str, step: int) -> random.Random:
    key = f"{seed}|{map_id}|{entity_name}|{step}".encode("utf-8")
    digest = hashlib.sha256(key).digest()
    value = int.from_bytes(digest[:8], "big")
    return random.Random(value)


def normalize_row_weights(row: dict[str, float]) -> dict[str, float]:
    positive = {k: float(v) for k, v in row.items() if float(v) > 0}
    total = sum(positive.values())
    if total <= 0:
        return {}
    return {k: v / total for k, v in positive.items()}


def weighted_choice(weights: dict[str, float], rng: random.Random) -> str:
    roll = rng.random()
    acc = 0.0
    for key, w in weights.items():
        acc += w
        if roll <= acc:
            return key
    return next(reversed(weights))


def _pick_plans_from_prep(
    prep: dict[str, Any],
    index: dict[str, Any],
    weights: dict[str, dict[str, float]],
    seed: int,
    *,
    categories_cfg: dict[str, Any],
    map_filter: str | None,
    mount_pair_donors_by_kind: dict[str, list[MountPairDonor]],
    npc_csv_dir: Path,
    dlc_pool_mode: str = "mixed",
    on_progress: Any | None = None,
    prep_trusted: bool = False,
) -> tuple[list[_SlotPickPlan], dict[str, int], list[str]]:
    from enemy_randomizer_core import _enemy_calc_progress
    from enemy_slot_rules import _PREP_REVALIDATE_SKIP_KEYS
    from enemy_slot_prep import (
        blocked_donor_indices,
        hydrate_missing_prep_pools,
        hydrate_stale_prep_row,
        make_prep_hydrate_ctx,
        prep_donor_indices,
        prep_row_has_pools,
        prep_slots_for_map,
        reconcile_prep_row_src_cat,
    )
    from donor_msb_compat import (
        filter_prep_donor_indices_for_msb_compat,
        load_donor_slot_compat,
    )
    from donor_vanilla_states import (
        filter_prep_donor_indices_for_runtime_think,
        prioritize_flyer_donor_indices,
        prioritize_patrol_donor_indices,
    )
    from enemy_slot_prep import migrate_legacy_prep_row
    from whitelist_slot_receptor import (
        load_whitelist_receptor_index,
        whitelist_receptor_stale_warn,
    )

    compat_by_tid = load_donor_slot_compat()
    receptor_index = load_whitelist_receptor_index()
    receptor_warn = whitelist_receptor_stale_warn()
    from donor_vanilla_states import build_model_vanilla_state_index

    from donor_vanilla_states import vanilla_state_index_cache_key

    index_slots = index.get("slots", [])
    vanilla_key = vanilla_state_index_cache_key(index_slots)
    model_vanilla_index = build_model_vanilla_state_index(
        index_slots, cache_key=vanilla_key
    )
    filter_memo = _ScanDonorFilterMemo()

    slots_by_key = {
        (str(s.get("map_id", "")), str(s.get("name", ""))): s
        for s in index.get("slots", [])
    }
    prep_rows = prep_slots_for_map(prep, map_filter)
    prep_rows = sorted(
        prep_rows,
        key=lambda r: (str(r.get("m", "")), str(r.get("n", ""))),
    )
    warnings = [
        f"slot_prep_cache=on donors={len(prep.get('donors') or [])} "
        f"rows={len(prep_rows)}"
    ]
    if receptor_warn:
        warnings.append(f"whitelist_receptor_warn: {receptor_warn}")
    rider_to_mount, skip_mount_slot_keys = index_rider_mount_slot_pairs(
        index.get("slots", []), categories_cfg
    )
    from enemy_night_spatial_quota import (
        load_major_boss_spatial_quota_config,
        load_night_spatial_quota_config,
        major_boss_spatial_cell_key,
        is_major_boss_spatial_quota_exempt,
        night_cell_at_capacity,
        night_spatial_cell_key,
        record_night_cell_use,
    )
    skip_counts = {
        "skipped": 0,
        "skipped_large": 0,
        "skipped_passive_animal": 0,
        "skipped_npc_slot": 0,
        "skipped_scarab": 0,
        "skipped_dense_keep": 0,
        "dense_pool_1_2": 0,
        "night_spatial_quota_blocked": 0,
        "major_boss_spatial_quota_blocked": 0,
        "physique_compat_blocked": 0,
        "slot_compat_blocked": 0,
    }
    night_quota_cfg = load_night_spatial_quota_config(categories_cfg)
    major_quota_cfg = load_major_boss_spatial_quota_config(categories_cfg)
    night_cells_used: dict[tuple[str | int, ...], int] = {}
    major_cells_used: dict[tuple[str | int, ...], int] = {}
    stale_prep_unskip = 0
    stale_prep_hydrated = 0
    pick_plans: list[_SlotPickPlan] = []
    total = len(prep_rows)
    donor_block = blocked_donor_indices(prep, categories_cfg)
    hydrate_ctx: dict[str, Any] | None = None
    progress_stride = max(25, min(100, total // 160))

    def _lazy_hydrate_ctx() -> dict[str, Any]:
        nonlocal hydrate_ctx
        if hydrate_ctx is not None:
            return hydrate_ctx

        def _hydrate_progress(phase: str, done: int, tpl_total: int, msg: str) -> None:
            if phase != "prep_cache":
                return
            _enemy_calc_progress(
                on_progress,
                "scan",
                done,
                max(tpl_total, 1),
                msg,
                every=500,
            )

        _enemy_calc_progress(
            on_progress,
            "scan",
            0,
            total,
            "敌人：补算 compat 捐皮池（仅缺池/类别变更槽）…",
            every=1,
        )
        hydrate_ctx = make_prep_hydrate_ctx(
            prep,
            index,
            categories_cfg,
            dlc_pool_mode=dlc_pool_mode,
            npc_csv_dir=npc_csv_dir,
            on_progress=_hydrate_progress,
        )
        return hydrate_ctx

    from enemy_slot_density import (
        clear_density_cache,
        density_fingerprint_ok,
        restrict_weights_to_pool_1_2,
        slot_density_policy,
    )

    clear_density_cache()
    dens_ok, dens_msg = density_fingerprint_ok()
    if dens_ok:
        warnings.append(dens_msg)
    else:
        warnings.append(f"density_lookup_warn: {dens_msg}")

    _enemy_calc_progress(
        on_progress,
        "scan",
        0,
        total,
        f"敌人：规划替换槽位 0/{total}…",
    )

    def _legacy_empty_prep_pools(row: dict[str, Any]) -> bool:
        o = row.get("o")
        return isinstance(o, dict) and not o and not row.get("k")

    def _ensure_fog_major_boss_pools(row: dict[str, Any], slot: dict[str, Any]) -> bool:
        """雾门主线槽：旧 prep 常无 o / 被 talk 冻成 k=npc；用合成 6 池互洗表垫池。"""
        if not is_scripted_dungeon_main_boss_slot(slot, categories_cfg):
            return False
        if is_excluded_slot_model(
            str(slot.get("model", "")),
            categories_cfg,
            slot,
            npc_csv_dir,
        ):
            return False
        swap = fog_major_boss_swap_indices(
            prep,
            categories_cfg,
            blocked_indices=donor_block,
        )
        if not swap:
            return False
        row["s"] = "major_boss"
        row.pop("k", None)
        pools = row.get("o")
        if not isinstance(pools, dict):
            pools = {}
            row["o"] = pools
        if not pools.get("major_boss"):
            pools["major_boss"] = list(swap)
        return True

    def _ensure_prep_row_pools(row: dict[str, Any], slot: dict[str, Any]) -> bool:
        nonlocal stale_prep_hydrated
        # 雾门优先：旧缓存可能是空 o{}（legacy）或无 o；先垫合成互洗池
        if _ensure_fog_major_boss_pools(row, slot):
            return True
        if _legacy_empty_prep_pools(row):
            return False
        if prep_row_has_pools(row):
            src_cat = str(row.get("s") or "")
            pools = row.get("o") or {}
            if normalize_category_id(src_cat) == "major_boss" and not pools.get(
                "major_boss"
            ):
                hydrate_missing_prep_pools(row, slot, _lazy_hydrate_ctx())
            return prep_row_has_pools(row)
        had_o = prep_row_has_pools(row)
        if not hydrate_stale_prep_row(row, slot, _lazy_hydrate_ctx()):
            return False
        if not had_o:
            stale_prep_hydrated += 1
            if stale_prep_hydrated in (1, 5) or stale_prep_hydrated % 50 == 0:
                _enemy_calc_progress(
                    on_progress,
                    "scan",
                    row_i,
                    total,
                    f"敌人：补算捐皮池 {stale_prep_hydrated} 槽（旧缓存解冻）…",
                    every=1,
                )
        return True

    for row_i, row in enumerate(prep_rows, start=1):
        if row_i in (1, total) or row_i % progress_stride == 0:
            _enemy_calc_progress(
                on_progress,
                "scan",
                row_i,
                total,
                f"敌人：规划替换槽位 {row_i}/{total}…",
                every=1,
            )
        map_id = str(row.get("m", ""))
        entity_name = str(row.get("n", ""))
        if (map_id, entity_name) in skip_mount_slot_keys:
            continue

        slot = slots_by_key.get((map_id, entity_name))
        skip_key = row.get("k")
        frozen_skip = skip_key
        if skip_key in _PREP_REVALIDATE_SKIP_KEYS:
            skip_key = revalidate_prep_skip_key(
                skip_key,
                slot,
                categories_cfg=categories_cfg,
                npc_csv_dir=npc_csv_dir,
            )
            if frozen_skip and not skip_key:
                stale_prep_unskip += 1
        if skip_key:
            _count_prep_skip_bucket(str(skip_key), skip_counts)
            continue

        if slot is None:
            skip_counts["skipped"] += 1
            continue

        if skip_mount_pair_entity_when_disabled(
            slot,
            categories_cfg,
            prep_row=row,
            rider_to_mount=rider_to_mount,
            map_id=map_id,
            entity_name=entity_name,
        ):
            skip_counts["skipped"] += 1
            continue

        had_prep_pools = prep_row_has_pools(row)
        if had_prep_pools:
            # prep 参与槽建缓存时已判 npc/animal/大体型；仅补 hub/圣甲虫等后加规则
            runtime_skip = runtime_slot_skip_after_prep(slot, categories_cfg)
        else:
            runtime_skip = resolve_effective_slot_skip(
                None,
                slot,
                categories_cfg=categories_cfg,
                npc_csv_dir=npc_csv_dir,
            )
        if runtime_skip:
            _count_prep_skip_bucket(str(runtime_skip), skip_counts)
            continue

        if not _ensure_prep_row_pools(row, slot):
            skip_counts["skipped"] += 1
            continue

        if not (
            prep_trusted
            and prep_row_has_pools(row)
        ) and not reconcile_prep_row_src_cat(
            row,
            slot,
            categories_cfg=categories_cfg,
            npc_csv_dir=npc_csv_dir,
            get_hydrate_ctx=_lazy_hydrate_ctx,
        ):
            skip_counts["skipped"] += 1
            continue

        migrate_legacy_prep_row(row)

        density_policy = slot_density_policy(map_id, entity_name)
        if density_policy == "keep_original":
            skip_counts["skipped_dense_keep"] += 1
            continue

        src_cat = normalize_category_id(str(row.get("s", "")))
        row["s"] = src_cat
        if density_policy == "dense_pool_1_2":
            skip_counts["dense_pool_1_2"] += 1
            norm = normalize_row_weights(
                restrict_weights_to_pool_1_2(
                    {k: float(v) for k, v in (weights.get(src_cat) or {}).items()}
                )
            )
        else:
            norm = normalize_row_weights(
                {k: float(v) for k, v in (weights.get(src_cat) or {}).items()}
            )
            src_cat, norm = scripted_dungeon_boss_pick_weights(
                src_cat, norm, slot, categories_cfg
            )
            src_cat, norm = evergaol_src_pick_weights(
                src_cat, norm, slot, categories_cfg
            )
            src_cat, norm = minor_boss_src_pick_weights(
                src_cat, norm, slot, categories_cfg
            )
            src_cat, norm = dungeon_boss_arena_pick_weights(
                src_cat, norm, slot, categories_cfg
            )
        norm = drawable_category_weights(
            norm,
            row,
            prep,
            slot,
            categories_cfg=categories_cfg,
            blocked_indices=donor_block,
        )
        if density_policy == "dense_pool_1_2" and not norm:
            norm = drawable_category_weights(
                {"trash": 100.0},
                row,
                prep,
                slot,
                categories_cfg=categories_cfg,
                blocked_indices=donor_block,
            )
        if not norm:
            skip_counts["skipped"] += 1
            continue

        night_cell_key = None
        major_cell_key = None
        if night_quota_cfg.enabled and slot is not None:
            night_cell_key = night_spatial_cell_key(map_id, slot, night_quota_cfg)
            if night_cell_at_capacity(night_cell_key, night_cells_used, night_quota_cfg):
                if "night" in norm or any(
                    normalize_category_id(k) == "night" for k in norm
                ):
                    skip_counts["night_spatial_quota_blocked"] += 1
                norm = normalize_row_weights(
                    {
                        k: v
                        for k, v in norm.items()
                        if normalize_category_id(k) != "night"
                    }
                )
        if major_quota_cfg.enabled and slot is not None:
            major_cell_key = major_boss_spatial_cell_key(
                map_id, slot, major_quota_cfg, categories_cfg=categories_cfg
            )
            major_exempt = is_major_boss_spatial_quota_exempt(slot, categories_cfg)
            if (not major_exempt) and night_cell_at_capacity(
                major_cell_key, major_cells_used, major_quota_cfg
            ):
                if "major_boss" in norm or any(
                    normalize_category_id(k) == "major_boss" for k in norm
                ):
                    skip_counts["major_boss_spatial_quota_blocked"] += 1
                norm = normalize_row_weights(
                    {
                        k: v
                        for k, v in norm.items()
                        if normalize_category_id(k) != "major_boss"
                    }
                )
        if not norm:
            skip_counts["skipped"] += 1
            continue

        rng1 = slot_rng(seed, map_id, entity_name, 1)
        tgt_try_order = _weighted_category_try_order(norm, rng1)
        tgt_cat = tgt_try_order[0] if tgt_try_order else src_cat

        rider_key = (map_id, entity_name)
        partner_mount = None
        if row.get("p"):
            partner_mount = slots_by_key.get((map_id, str(row.get("p", ""))))
        elif rider_key in rider_to_mount:
            partner_mount = rider_to_mount[rider_key]

        if row.get("c") and not row.get("o"):
            skip_counts["skipped"] += 1
            warnings.append(
                f"stale_mount_prep {map_id}:{entity_name} — 请重建槽位缓存(prep v2)"
            )
            continue

        if partner_mount is not None and mount_pair_randomize_enabled(categories_cfg):
            pair_pool = build_global_mount_pair_pool(mount_pair_donors_by_kind)
            if not pair_pool:
                skip_counts["skipped"] += 1
                warnings.append(f"no_mount_pair_pool {map_id}:{entity_name}")
                continue
            pick_plans.append(
                _SlotPickPlan(
                    slot=slot,
                    map_id=map_id,
                    entity_name=entity_name,
                    src_cat=src_cat,
                    tgt_cat=tgt_cat,
                    donor_indices=[],
                    mount_pair_pool=list(pair_pool),
                    partner_mount_slot=partner_mount,
                    mount_pair_label_zh="骑马（成套）",
                )
            )
            continue

        tgt_cat = ""
        donor_indices: list[int] = []
        pre_physique: list[int] = []
        pre_msb: list[int] = []
        for try_tgt in tgt_try_order:
            fog_swap = (
                try_tgt == "major_boss"
                and is_scripted_dungeon_main_boss_slot(slot, categories_cfg)
            )
            if fog_swap:
                donor_indices = fog_major_boss_swap_indices(
                    prep,
                    categories_cfg,
                    blocked_indices=donor_block,
                )
                pre_physique = donor_indices
                pre_msb = donor_indices
            else:
                donor_indices = filter_memo.prep_donor_indices_cached(
                    prep,
                    row,
                    try_tgt,
                    categories_cfg=categories_cfg,
                    blocked_indices=donor_block,
                )
                donor_indices = filter_memo.filter_for_slot(
                    prep,
                    donor_indices,
                    slot,
                    try_tgt,
                    categories_cfg,
                    src_cat=src_cat,
                )
                donor_indices = filter_memo.filter_for_anchor_plant(
                    prep,
                    donor_indices,
                    slot,
                    categories_cfg,
                )
                pre_physique = donor_indices
                donor_indices = filter_memo.filter_for_physique_compat(
                    prep,
                    donor_indices,
                    slot,
                    categories_cfg,
                    compat_by_tid=compat_by_tid,
                )
                pre_msb = donor_indices
                donor_indices = filter_memo.filter_for_msb_compat(
                    prep,
                    donor_indices,
                    slot,
                    compat_by_tid=compat_by_tid,
                    receptor_index=receptor_index,
                    categories_cfg=categories_cfg,
                )
                donor_indices = filter_memo.filter_for_runtime_think(
                    prep,
                    donor_indices,
                    slot,
                    model_vanilla_index,
                    categories_cfg=categories_cfg,
                )
                donor_indices = filter_scripted_fog_boss_donor_indices(
                    prep, slot, donor_indices, categories_cfg=categories_cfg
                )
            donor_indices = prioritize_patrol_donor_indices(
                prep,
                donor_indices,
                slot,
                compat_by_tid=compat_by_tid,
            )
            donor_indices = prioritize_flyer_donor_indices(
                prep,
                donor_indices,
                slot,
                compat_by_tid=compat_by_tid,
                categories_cfg=categories_cfg,
            )
            if donor_indices:
                tgt_cat = try_tgt
                break

        if not donor_indices and pre_msb:
            skip_counts["slot_compat_blocked"] = skip_counts.get("slot_compat_blocked", 0) + 1
        if not donor_indices and pre_physique:
            skip_counts["physique_compat_blocked"] += 1
            warnings.append(
                f"physique_empty {map_id}:{entity_name} "
                f"slot={slot_physique_bucket(slot, categories_cfg)} "
                f"model={slot.get('model')}"
            )
        if not donor_indices:
            mount_note = ""
            if slot_is_mounted_rider(slot, categories_cfg):
                mount_note = " mounted_rider"
            elif is_horse_mount_model(str(slot.get("model", "")), categories_cfg):
                mount_note = " horse_mount"
            warnings.append(
                f"empty pool {map_id}:{entity_name} tgt={tgt_cat}{mount_note}"
            )
            skip_counts["skipped"] += 1
            continue

        pick_plans.append(
            _SlotPickPlan(
                slot=slot,
                map_id=map_id,
                entity_name=entity_name,
                src_cat=src_cat,
                tgt_cat=tgt_cat,
                donor_indices=donor_indices,
            )
        )
        if tgt_cat == "night" and night_quota_cfg.enabled:
            record_night_cell_use(night_cell_key, night_cells_used)
        if tgt_cat == "major_boss" and major_quota_cfg.enabled:
            record_night_cell_use(major_cell_key, major_cells_used)

    if stale_prep_unskip:
        warnings.append(
            f"prep_skip_revalidated={stale_prep_unskip}（旧缓存跳过标记已按当前规则解冻）"
        )
    if stale_prep_hydrated:
        warnings.append(
            f"prep_pools_hydrated={stale_prep_hydrated}（旧跳过槽位已补算捐皮池，无需重建 prep）"
        )
    if skip_counts["skipped_dense_keep"] or skip_counts["dense_pool_1_2"]:
        warnings.append(
            f"dense_keep={skip_counts['skipped_dense_keep']} "
            f"dense_pool_1_2={skip_counts['dense_pool_1_2']}"
        )
    if skip_counts["night_spatial_quota_blocked"]:
        warnings.append(
            f"night_spatial_quota_blocked={skip_counts['night_spatial_quota_blocked']}"
        )
    if skip_counts["major_boss_spatial_quota_blocked"]:
        warnings.append(
            f"major_boss_spatial_quota_blocked={skip_counts['major_boss_spatial_quota_blocked']}"
        )
    if skip_counts["physique_compat_blocked"]:
        warnings.append(
            f"physique_compat_blocked={skip_counts['physique_compat_blocked']}"
        )

    return pick_plans, skip_counts, warnings

