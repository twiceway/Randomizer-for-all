"""T-084 R4/R5 — generate pick: read prep pools only.

PREP_VERSION≥42：池已含 receptor_bucket 指纹 + T-080 compat，pick 不再重滤（C-6）。
低于 42 的旧 prep 仍做一次 MSB compat 重判以防过期缓存。
"""

from __future__ import annotations

from typing import Any

from enemy_slot_prep import prep_donor_indices

PREP_TRUST_BAKED_COMPAT_VERSION = 42


def donor_indices_from_prep(
    prep: dict[str, Any],
    row: dict[str, Any],
    tgt_cat: str,
    *,
    slot: dict[str, Any] | None = None,
    blocked_indices: frozenset[int] | None,
    categories_cfg: dict[str, Any],
) -> list[int]:
    """Read prep pools for tgt_cat; re-apply T-080 MSB compat when slot is known."""
    indices = prep_donor_indices(
        prep,
        row,
        tgt_cat,
        blocked_indices=blocked_indices,
        categories_cfg=categories_cfg,
    )
    if not indices or slot is None:
        return indices
    if int(prep.get("version") or 0) >= PREP_TRUST_BAKED_COMPAT_VERSION:
        return indices
    from bundle_cache import compat_by_tid_from_bundle_slot_compat
    from donor_msb_compat import filter_prep_donor_indices_for_msb_compat

    compat = compat_by_tid_from_bundle_slot_compat()
    return filter_prep_donor_indices_for_msb_compat(
        prep,
        indices,
        slot,
        compat,
        categories_cfg=categories_cfg,
    )


def first_nonempty_prep_pool(
    prep: dict[str, Any],
    row: dict[str, Any],
    tgt_try_order: list[str],
    *,
    slot: dict[str, Any],
    blocked_indices: frozenset[int] | None,
    categories_cfg: dict[str, Any],
) -> tuple[str, list[int]]:
    """Try target categories in order; return first non-empty prep pool."""
    for try_tgt in tgt_try_order:
        indices = donor_indices_from_prep(
            prep,
            row,
            try_tgt,
            slot=slot,
            blocked_indices=blocked_indices,
            categories_cfg=categories_cfg,
        )
        if indices:
            return try_tgt, indices
    return "", []
