"""T-080 v2 — scan vanilla MSB slots by model → supported receptor buckets / slot classes."""

from __future__ import annotations

from collections import Counter
from functools import lru_cache
from typing import Any

from _export_slot_initial_state import apply_slot_class
from whitelist_slot_receptor import BUCKET_IDS, classify_receptor_bucket

EMPTY_BUCKET_TOTALS = {bid: 0 for bid in BUCKET_IDS}


def _slot_npc_think(slot: dict[str, Any]) -> tuple[int, int] | None:
    try:
        npc = int(slot.get("npc") or 0)
        think = int(slot.get("think") or 0)
    except (TypeError, ValueError):
        return None
    if npc <= 0:
        return None
    return npc, think


_VANILLA_STATE_INDEX_CACHE: tuple[tuple[Any, ...], dict[str, dict[str, Any]]] | None = None


def vanilla_state_index_cache_key(
    slots: list[dict[str, Any]],
    *,
    index_mtime: float | None = None,
) -> tuple[Any, ...]:
    if index_mtime is None:
        try:
            from enemy_randomizer_core import DEFAULT_INDEX_PATH

            if DEFAULT_INDEX_PATH.is_file():
                index_mtime = DEFAULT_INDEX_PATH.stat().st_mtime
            else:
                index_mtime = 0.0
        except OSError:
            index_mtime = 0.0
    return (float(index_mtime or 0.0), len(slots))


def clear_vanilla_state_index_cache() -> None:
    global _VANILLA_STATE_INDEX_CACHE
    _VANILLA_STATE_INDEX_CACHE = None


def build_model_vanilla_state_index(
    slots: list[dict[str, Any]],
    *,
    cache_key: tuple[Any, ...] | None = None,
) -> dict[str, dict[str, Any]]:
    """Group enemy_index slots by model; collect bucket + apply_slot_class counts."""
    global _VANILLA_STATE_INDEX_CACHE
    key = cache_key if cache_key is not None else vanilla_state_index_cache_key(slots)
    if _VANILLA_STATE_INDEX_CACHE is not None and _VANILLA_STATE_INDEX_CACHE[0] == key:
        return _VANILLA_STATE_INDEX_CACHE[1]
    bucket_ctr: dict[str, Counter[str]] = {}
    class_ctr: dict[str, Counter[str]] = {}
    patrol_pair_ctr: dict[str, Counter[tuple[int, int]]] = {}
    static_pair_ctr: dict[str, Counter[tuple[int, int]]] = {}

    for slot in slots:
        model = str(slot.get("model") or "").strip()
        if not model:
            continue
        bucket = classify_receptor_bucket(slot)
        slot_class = apply_slot_class(slot)
        bucket_ctr.setdefault(model, Counter())[bucket] += 1
        class_ctr.setdefault(model, Counter())[slot_class] += 1
        pair = _slot_npc_think(slot)
        if str(slot.get("walk_route") or "").strip():
            if pair is not None:
                patrol_pair_ctr.setdefault(model, Counter())[pair] += 1
        elif bucket in {"ground_stand", "collision_perch"} and pair is not None:
            static_pair_ctr.setdefault(model, Counter())[pair] += 1

    out: dict[str, dict[str, Any]] = {}
    for model, ctr in bucket_ctr.items():
        totals = {bid: int(ctr.get(bid, 0)) for bid in BUCKET_IDS}
        supported_buckets = [bid for bid in BUCKET_IDS if totals[bid] > 0]
        class_counts = class_ctr.get(model, Counter())
        supported_classes = sorted(class_counts.keys())
        class_totals = {k: int(class_counts[k]) for k in supported_classes}
        pair_ctr = patrol_pair_ctr.get(model, Counter())
        profiles = [
            {"npc": npc, "think": think, "count": int(pair_ctr[(npc, think)])}
            for npc, think in sorted(pair_ctr.keys())
        ]
        patrol_ref: dict[str, int] | None = None
        if pair_ctr:
            (ref_npc, ref_think), ref_count = pair_ctr.most_common(1)[0]
            patrol_ref = {
                "npc": int(ref_npc),
                "think": int(ref_think),
                "count": int(ref_count),
            }
        static_ctr = static_pair_ctr.get(model, Counter())
        static_profiles = [
            {"npc": npc, "think": think, "count": int(static_ctr[(npc, think)])}
            for npc, think in sorted(static_ctr.keys())
        ]
        static_ref: dict[str, int] | None = None
        if static_ctr:
            (s_npc, s_think), s_count = static_ctr.most_common(1)[0]
            static_ref = {
                "npc": int(s_npc),
                "think": int(s_think),
                "count": int(s_count),
            }
        out[model] = {
            "vanilla_scan_model": model,
            "vanilla_occurrence_total": sum(totals.values()),
            "vanilla_bucket_totals": totals,
            "vanilla_supported_buckets": supported_buckets,
            "vanilla_slot_class_totals": class_totals,
            "vanilla_supported_slot_classes": supported_classes,
            "vanilla_patrol_profiles": profiles,
            "vanilla_patrol_reference": patrol_ref,
            "vanilla_static_profiles": static_profiles,
            "vanilla_static_reference": static_ref,
        }
    _VANILLA_STATE_INDEX_CACHE = (key, out)
    return out


def patrol_reference_for_model(
    model: str,
    model_index: dict[str, dict[str, Any]],
) -> dict[str, int] | None:
    model = str(model or "").strip()
    if not model:
        return None
    scan = model_index.get(model)
    if not scan:
        return None
    ref = scan.get("vanilla_patrol_reference")
    if not isinstance(ref, dict):
        return None
    try:
        npc = int(ref.get("npc") or 0)
        think = int(ref.get("think") or 0)
    except (TypeError, ValueError):
        return None
    if npc <= 0 or think <= 0:
        return None
    return {"npc": npc, "think": think}


def static_reference_for_model(
    model: str,
    model_index: dict[str, dict[str, Any]],
) -> dict[str, int] | None:
    model = str(model or "").strip()
    if not model:
        return None
    scan = model_index.get(model)
    if not scan:
        return None
    ref = scan.get("vanilla_static_reference")
    if not isinstance(ref, dict):
        return None
    try:
        npc = int(ref.get("npc") or 0)
        think = int(ref.get("think") or 0)
    except (TypeError, ValueError):
        return None
    if npc <= 0 or think <= 0:
        return None
    return {"npc": npc, "think": think}


def static_profile_keys(
    model: str,
    model_index: dict[str, dict[str, Any]],
) -> set[tuple[int, int]]:
    scan = model_index.get(str(model or "").strip()) or {}
    profiles = scan.get("vanilla_static_profiles") or []
    out: set[tuple[int, int]] = set()
    for p in profiles:
        try:
            npc = int(p.get("npc") or 0)
            think = int(p.get("think") or 0)
        except (TypeError, ValueError):
            continue
        if npc > 0 and think > 0:
            out.add((npc, think))
    return out


def vanilla_static_thinks_for_model(
    model: str,
    model_index: dict[str, dict[str, Any]],
) -> set[int]:
    """原版无 walk_route 地面/挂靠槽出现过的 think（门禁白名单）。"""
    scan = model_index.get(str(model or "").strip()) or {}
    out: set[int] = set()
    for p in scan.get("vanilla_static_profiles") or []:
        try:
            think = int(p.get("think") or 0)
        except (TypeError, ValueError):
            continue
        if think > 0:
            out.add(think)
    return out


def _static_boss_variant_think(think: int) -> bool:
    """地面站桩易冻的 think 子带：01xx / 09xx（相对模型族末四位）。"""
    if think <= 0:
        return False
    tail = think % 10000
    if 100 <= tail < 200:
        return True
    if 900 <= tail < 1000:
        return True
    return False


def apply_static_runtime_alignment(
    slot: dict[str, Any],
    template: dict[str, Any],
    npc: int,
    think: int,
    model_index: dict[str, dict[str, Any]],
    categories_cfg: dict[str, Any] | None = None,
) -> tuple[int, int]:
    """T-083d：无 walk_route 的地面/挂靠槽 → 01xx/09xx 子带对齐原版静态共识。"""
    if str(slot.get("walk_route") or "").strip():
        return npc, think
    from donor_msb_compat import _is_script_patrol_flyer_slot

    if _is_script_patrol_flyer_slot(slot, categories_cfg):
        return npc, think
    from whitelist_slot_receptor import classify_receptor_bucket

    bucket = classify_receptor_bucket(slot)
    if bucket not in {"ground_stand", "collision_perch"}:
        return npc, think
    model_l = str(template.get("model") or "").strip().lower()
    ref = static_reference_for_model(model_l, model_index)
    if ref is None:
        return npc, think
    try:
        cur_think = int(think)
    except (TypeError, ValueError):
        return npc, think
    vanilla_static = vanilla_static_thinks_for_model(model_l, model_index)
    if cur_think in vanilla_static:
        return npc, think
    from npc_think_sanitize import infer_think_from_npc, think_matches_model_family

    if not think_matches_model_family(model_l, cur_think):
        return npc, think
    try:
        donor_think = int(template.get("think") or 0)
    except (TypeError, ValueError):
        donor_think = 0
    try:
        tpl_npc = int(template.get("npc") or 0)
    except (TypeError, ValueError):
        tpl_npc = 0
    inferred = infer_think_from_npc(tpl_npc if tpl_npc > 0 else int(npc))
    if donor_think in vanilla_static and cur_think != inferred:
        return npc, donor_think
    if cur_think == inferred or _static_boss_variant_think(cur_think):
        return ref["npc"], ref["think"]
    return npc, think


def _quadruped_standing_boss_line(npc: int, think: int) -> bool:
    """四足 Boss 线 npc/think（如 31800100）在站桩槽易冻。"""
    for value in (npc, think):
        if 3_180_010_0 <= int(value) < 3_180_020_0:
            return True
    return False


def chariot_boss_line(npc: int, think: int) -> bool:
    """火焰战车 Boss 线（446078xx）在站桩/无路线槽易冻。"""
    for value in (npc, think):
        if 44_607_800 <= int(value) < 44_607_900:
            return True
    return False


def shade_boss_line(npc: int, think: int) -> bool:
    """墓地影子 Boss 线（551309xx）在站桩/无路线槽易冻。"""
    for value in (npc, think):
        if 55_130_900 <= int(value) < 55_131_000:
            return True
    return False


def apply_chariot_runtime_alignment(
    slot: dict[str, Any],
    template: dict[str, Any],
    npc: int,
    think: int,
    model_index: dict[str, dict[str, Any]],
) -> tuple[int, int]:
    """T-083c：c4460 火焰战车 Boss 线 → 对齐原版巡逻共识 think=44600000。"""
    model_l = str(template.get("model") or "").strip().lower()
    if model_l != "c4460":
        return npc, think
    ref = patrol_reference_for_model(model_l, model_index)
    if ref is None:
        return npc, think
    try:
        donor_npc = int(template.get("npc") or npc or 0)
        donor_think = int(template.get("think") or think or 0)
    except (TypeError, ValueError):
        donor_npc, donor_think = npc, think
    if chariot_boss_line(donor_npc, donor_think) or chariot_boss_line(npc, think):
        return ref["npc"], ref["think"]
    return npc, think


def apply_shade_runtime_alignment(
    slot: dict[str, Any],
    template: dict[str, Any],
    npc: int,
    think: int,
    model_index: dict[str, dict[str, Any]],
) -> tuple[int, int]:
    """T-083g：c5513 墓地影子 Boss 线 → 对齐原版静态共识 think=55130000。"""
    model_l = str(template.get("model") or "").strip().lower()
    if model_l != "c5513":
        return npc, think
    ref = static_reference_for_model(model_l, model_index)
    if ref is None:
        return npc, think
    try:
        donor_npc = int(template.get("npc") or npc or 0)
        donor_think = int(template.get("think") or think or 0)
    except (TypeError, ValueError):
        donor_npc, donor_think = npc, think
    if shade_boss_line(donor_npc, donor_think) or shade_boss_line(npc, think):
        return ref["npc"], ref["think"]
    return npc, think


def apply_patrol_runtime_alignment(
    slot: dict[str, Any],
    template: dict[str, Any],
    npc: int,
    think: int,
    model_index: dict[str, dict[str, Any]],
    categories_cfg: dict[str, Any] | None = None,
) -> tuple[int, int]:
    """T-076：站立四足捐皮 → 对齐原版巡逻共识 npc/think（巡逻槽或地面站桩槽）。"""
    slot_walk = str(slot.get("walk_route") or "").strip()
    donor_walk = str(template.get("walk_route") or "").strip()
    model_l = str(template.get("model") or "").strip().lower()
    ref = patrol_reference_for_model(model_l, model_index)
    if ref is None:
        return npc, think
    from donor_msb_compat import _is_quadruped_scan_model

    if not _is_quadruped_scan_model(model_l, categories_cfg):
        return npc, think
    if slot_walk:
        return ref["npc"], ref["think"]
    try:
        donor_npc = int(template.get("npc") or npc or 0)
        donor_think = int(template.get("think") or think or 0)
    except (TypeError, ValueError):
        donor_npc, donor_think = npc, think
    if _quadruped_standing_boss_line(donor_npc, donor_think):
        return ref["npc"], ref["think"]
    if donor_walk:
        return npc, think
    if donor_think != ref["think"] or donor_npc != ref["npc"]:
        return ref["npc"], ref["think"]
    return npc, think


def apply_npc_think_thousands_alignment(
    slot: dict[str, Any],
    template: dict[str, Any],
    npc: int,
    think: int,
    model_index: dict[str, dict[str, Any]],
    categories_cfg: dict[str, Any] | None = None,
) -> tuple[int, int]:
    """T-083h：捐皮 npc 推 think 与写出 think 千位组不一致 → 对齐 npc 惯例 think。"""
    from npc_think_sanitize import (
        infer_think_from_npc,
        is_runtime_think_copy_id,
        think_matches_model_family,
        think_param_has_id,
    )
    from donor_msb_compat import _is_script_patrol_flyer_slot

    if think <= 0 or is_runtime_think_copy_id(think):
        return npc, think
    if _is_script_patrol_flyer_slot(slot, categories_cfg):
        return npc, think
    try:
        donor_npc = int(template.get("npc") or npc or 0)
    except (TypeError, ValueError):
        donor_npc = int(npc or 0)
    if donor_npc <= 0 or is_runtime_think_copy_id(donor_npc):
        return npc, think
    inferred = infer_think_from_npc(donor_npc)
    if inferred <= 0 or inferred // 1000 == int(think) // 1000:
        return npc, think
    model_l = str(template.get("model") or "").strip().lower()
    if not think_matches_model_family(model_l, inferred):
        return npc, think
    candidate = inferred
    if str(slot.get("walk_route") or "").strip():
        ref = patrol_reference_for_model(model_l, model_index)
        if ref is not None:
            try:
                ref_think = int(ref.get("think") or 0)
            except (TypeError, ValueError):
                ref_think = 0
            if (
                ref_think > 0
                and ref_think // 1000 == inferred // 1000
                and think_matches_model_family(model_l, ref_think)
            ):
                candidate = ref_think
    if not think_param_has_id(candidate):
        return npc, think
    return npc, candidate


def clamp_runtime_think_to_param(
    slot: dict[str, Any],
    template: dict[str, Any],
    npc: int,
    think: int,
    model_index: dict[str, dict[str, Any]],
    categories_cfg: dict[str, Any] | None = None,
) -> tuple[int, int]:
    """T-083i：写出 think 必须在 NpcThinkParam 有行；空行回退捐皮 think / 共识。"""
    from npc_think_sanitize import (
        first_existing_think_for_model,
        infer_think_from_npc,
        is_runtime_think_copy_id,
        think_matches_model_family,
        think_param_has_id,
    )

    if think > 0 and (is_runtime_think_copy_id(think) or think_param_has_id(think)):
        return npc, think
    model_l = str(template.get("model") or "").strip().lower()
    fallbacks: list[int] = []
    try:
        fallbacks.append(int(template.get("think") or 0))
    except (TypeError, ValueError):
        pass
    ref = patrol_reference_for_model(model_l, model_index)
    if ref is not None:
        try:
            fallbacks.append(int(ref.get("think") or 0))
        except (TypeError, ValueError):
            pass
    static_ref = static_reference_for_model(model_l, model_index)
    if static_ref is not None:
        try:
            fallbacks.append(int(static_ref.get("think") or 0))
        except (TypeError, ValueError):
            pass
    try:
        donor_npc = int(template.get("npc") or npc or 0)
    except (TypeError, ValueError):
        donor_npc = int(npc or 0)
    inferred = infer_think_from_npc(donor_npc)
    if inferred > 0:
        fallbacks.append(inferred)
    seen: set[int] = set()
    for cand in fallbacks:
        if cand <= 0 or cand in seen:
            continue
        seen.add(cand)
        if not think_param_has_id(cand):
            continue
        if model_l and not think_matches_model_family(model_l, cand):
            continue
        return npc, cand
    family = first_existing_think_for_model(model_l)
    if family > 0:
        return npc, family
    return npc, think


_RUNTIME_THINK_PICK_CTX: dict[str, Any] = {}


def _slot_runtime_pick_key(slot: dict[str, Any]) -> tuple[Any, ...]:
    return (
        str(slot.get("map_id", "")),
        str(slot.get("name", "")),
        str(slot.get("model", "")),
        str(slot.get("walk_route", "")),
        int(slot.get("backup_anim", -1) or -1),
        str(slot.get("collision_part", "")),
        str(slot.get("think", "")),
        str(slot.get("npc", "")),
    )


def _tpl_runtime_pick_key(template: dict[str, Any], donor_npc: int) -> tuple[Any, ...]:
    return (
        int(donor_npc),
        str(template.get("model", "")),
        str(template.get("template_id", "")),
        int(template.get("npc") or 0),
        int(template.get("think") or 0),
    )


def _runtime_think_cfg_token(categories_cfg: dict[str, Any] | None) -> int:
    return id(categories_cfg) if categories_cfg is not None else 0


def bind_runtime_think_pick_ctx(
    *,
    categories_cfg: dict[str, Any] | None,
    model_index: dict[str, dict[str, Any]],
    csv_dir_str: str | None = None,
) -> None:
    _RUNTIME_THINK_PICK_CTX["categories_cfg"] = categories_cfg
    _RUNTIME_THINK_PICK_CTX["model_index"] = model_index
    if csv_dir_str is not None:
        _RUNTIME_THINK_PICK_CTX["csv_dir_str"] = csv_dir_str


@lru_cache(maxsize=262144)
def _resolve_slot_runtime_npc_and_think_cached(
    slot_key: tuple[Any, ...],
    tpl_key: tuple[Any, ...],
    cfg_token: int,
) -> tuple[int, int]:
    ctx = _RUNTIME_THINK_PICK_CTX
    slot = {
        "map_id": slot_key[0],
        "name": slot_key[1],
        "model": slot_key[2],
        "walk_route": slot_key[3],
        "backup_anim": slot_key[4],
        "collision_part": slot_key[5],
        "think": slot_key[6],
        "npc": slot_key[7],
    }
    template = {
        "model": tpl_key[1],
        "template_id": tpl_key[2],
        "npc": tpl_key[3],
        "think": tpl_key[4],
    }
    return _resolve_slot_runtime_npc_and_think_body(
        slot,
        template,
        int(tpl_key[0]),
        ctx.get("categories_cfg"),
        ctx.get("model_index") or {},
        csv_dir_str=ctx.get("csv_dir_str"),
    )


def _resolve_slot_runtime_npc_and_think_body(
    slot: dict[str, Any],
    template: dict[str, Any],
    donor_npc: int,
    categories_cfg: dict[str, Any] | None,
    model_index: dict[str, dict[str, Any]],
    *,
    csv_dir_str: str | None = None,
) -> tuple[int, int]:
    """生成侧统一出口：think 清洗 + 对齐 + 空行 think 回退。"""
    from enemy_category_rules import is_excluded_slot_npc_id, is_never_donor_npc_id
    from enemy_randomizer_core import resolve_runtime_think

    try:
        orig_npc = int(donor_npc or 0)
    except (TypeError, ValueError):
        orig_npc = 0
    think = resolve_runtime_think(
        slot, template, categories_cfg, csv_dir=csv_dir_str
    )
    try:
        orig_think = int(think or 0)
    except (TypeError, ValueError):
        orig_think = 0
    donor_npc, think = apply_patrol_runtime_alignment(
        slot, template, donor_npc, think, model_index, categories_cfg
    )
    donor_npc, think = apply_chariot_runtime_alignment(
        slot, template, donor_npc, think, model_index
    )
    donor_npc, think = apply_shade_runtime_alignment(
        slot, template, donor_npc, think, model_index
    )
    donor_npc, think = apply_npc_think_thousands_alignment(
        slot, template, donor_npc, think, model_index, categories_cfg
    )
    donor_npc, think = apply_static_runtime_alignment(
        slot, template, donor_npc, think, model_index, categories_cfg
    )
    donor_npc, think = clamp_runtime_think_to_param(
        slot, template, donor_npc, think, model_index, categories_cfg
    )
    if categories_cfg:
        aligned = {"npc": donor_npc}
        if is_never_donor_npc_id(aligned, categories_cfg) or is_excluded_slot_npc_id(
            aligned, categories_cfg
        ):
            return orig_npc, orig_think
    return donor_npc, think


def resolve_slot_runtime_npc_and_think(
    slot: dict[str, Any],
    template: dict[str, Any],
    donor_npc: int,
    categories_cfg: dict[str, Any] | None,
    model_index: dict[str, dict[str, Any]],
) -> tuple[int, int]:
    """生成侧统一出口：think 清洗 + 对齐 + 空行 think 回退。

    巡逻/千位等对齐若落到 never_donor / exclude_slot npc（如拉车山妖 46001010），
    回退到对齐前的捐皮 npc/think，避免禁捐行进复制表。
    """
    ctx = _RUNTIME_THINK_PICK_CTX
    if ctx.get("model_index") is model_index and (
        categories_cfg is None or ctx.get("categories_cfg") is categories_cfg
    ):
        return _resolve_slot_runtime_npc_and_think_cached(
            _slot_runtime_pick_key(slot),
            _tpl_runtime_pick_key(template, donor_npc),
            _runtime_think_cfg_token(categories_cfg),
        )
    return _resolve_slot_runtime_npc_and_think_body(
        slot,
        template,
        donor_npc,
        categories_cfg,
        model_index,
    )


def filter_prep_donor_indices_for_runtime_think(
    prep: dict[str, Any],
    indices: list[int],
    slot: dict[str, Any],
    model_index: dict[str, dict[str, Any]],
    categories_cfg: dict[str, Any] | None = None,
    *,
    csv_dir_str: str | None = None,
) -> list[int]:
    """T-083：模拟生成侧 npc/think，拒绝族≠皮的捐皮（890M 复制行 / c0000 除外）。"""
    if not indices:
        return indices
    from npc_think_sanitize import think_matches_model_family, think_param_has_id, warm_think_csv_cache

    if csv_dir_str is None:
        warm_think_csv_cache()
    else:
        warm_think_csv_cache(csv_dir_str)
    bind_runtime_think_pick_ctx(
        categories_cfg=categories_cfg,
        model_index=model_index,
        csv_dir_str=csv_dir_str,
    )

    donors = prep.get("donors") or []
    out: list[int] = []
    for i in indices:
        if i < 0 or i >= len(donors):
            continue
        rec = donors[i]
        try:
            donor_npc = int(rec.get("npc") or 0)
        except (TypeError, ValueError):
            donor_npc = 0
        _, think = resolve_slot_runtime_npc_and_think(
            slot,
            rec,
            donor_npc,
            categories_cfg,
            model_index,
        )
        model = str(rec.get("model") or "")
        if think > 0 and not think_matches_model_family(model, think):
            continue
        if think > 0 and not think_param_has_id(think):
            continue
        out.append(i)
    return out


def prioritize_patrol_donor_indices(
    prep: dict[str, Any],
    indices: list[int],
    slot: dict[str, Any],
    compat_by_tid: dict[str, dict[str, Any]] | None = None,
) -> list[int]:
    """巡逻槽优先抽带 walk_route 的捐皮；人形站立出处已由 T-080/T-083 拒绝。"""
    if not str(slot.get("walk_route") or "").strip() or not indices:
        return indices
    from donor_msb_compat import compat_entry_for_template

    donors = prep.get("donors") or []
    patrol_idx: list[int] = []
    stand_idx: list[int] = []
    for i in indices:
        if i < 0 or i >= len(donors):
            continue
        rec = donors[i]
        tid = str(rec.get("template_id") or "")
        entry = compat_entry_for_template(tid, compat_by_tid or {}) or rec
        walk = str(
            entry.get("donor_walk_route")
            or rec.get("walk_route")
            or rec.get("donor_walk_route")
            or ""
        ).strip()
        if walk:
            patrol_idx.append(i)
        else:
            stand_idx.append(i)
    if patrol_idx:
        return patrol_idx + stand_idx
    return stand_idx


def prioritize_flyer_donor_indices(
    prep: dict[str, Any],
    indices: list[int],
    slot: dict[str, Any],
    compat_by_tid: dict[str, dict[str, Any]] | None = None,
    categories_cfg: dict[str, Any] | None = None,
) -> list[int]:
    """T-087/T-088：飞巡槽与普通槽同规则；历史状态过闸即可，不再飞行皮软排前。"""
    del prep, slot, compat_by_tid, categories_cfg
    return indices


def vanilla_state_fields_for_model(
    model: str,
    model_index: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    model = str(model or "").strip()
    scan = model_index.get(model)
    if not scan:
        return {
            "vanilla_scan_model": model,
            "vanilla_occurrence_total": 0,
            "vanilla_bucket_totals": dict(EMPTY_BUCKET_TOTALS),
            "vanilla_supported_buckets": [],
            "vanilla_slot_class_totals": {},
            "vanilla_supported_slot_classes": [],
            "vanilla_patrol_profiles": [],
            "vanilla_patrol_reference": None,
        }
    return dict(scan)


def attach_vanilla_state_fields(
    entry: dict[str, Any],
    model: str,
    model_index: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    out = dict(entry)
    vanilla = vanilla_state_fields_for_model(model, model_index)
    out.update(vanilla)
    return out
