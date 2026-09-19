"""T-059/T-062: duplicate NpcThinkParam rows with lift-scaled aggression fields."""

from __future__ import annotations

from typing import Any

from enemy_difficulty import (
    compute_row_adaptive_lift,
    load_difficulty_cfg,
    normalize_difficulty_settings,
)
from enemy_think_difficulty import (
    compute_think_aggression_overrides,
    compute_think_extreme_sanitize_overrides,
    compute_think_night_clamp_overrides,
    sanitize_think_field_overrides,
    think_aggression_config,
    think_patch_fingerprint,
)
from npc_think_sanitize import resolve_safe_think
from paths import GAME_DIR

THINK_COPY_ID_BASE = 890_000_000
THINK_COPY_ID_LIMIT = 891_000_000


def _merge_think_patches(
    primary: dict[str, Any] | None,
    extra: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if primary is None:
        return extra
    if extra is None:
        return primary
    merged = dict(primary)
    merged_fields = dict(primary.get("field_overrides") or {})
    merged_fields.update(extra.get("field_overrides") or {})
    merged["field_overrides"] = merged_fields
    merged["night_base_clamp"] = bool(
        primary.get("night_base_clamp") or extra.get("night_clamp") or extra.get("night_base_clamp")
    )
    return merged


def plan_think_copies(
    assignments: list[dict[str, Any]],
    *,
    categories_cfg: dict[str, Any] | None = None,
    difficulty_cfg: dict[str, Any] | None = None,
    csv_dir: Any | None = None,
    npc_by_id: dict[int, dict[str, str]] | None = None,
    difficulty: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Mutate assignments: think → runtime copy id when aggression patch needed."""
    from npc_soul_copies import DEFAULT_NPC_CSV, _load_npc_rows

    agg = think_aggression_config(difficulty_cfg)
    if not agg.get("enabled", True):
        return []

    base_dir = csv_dir or GAME_DIR / "csv"
    diff_cfg = difficulty_cfg if difficulty_cfg is not None else load_difficulty_cfg()
    diff_settings = normalize_difficulty_settings({"difficulty": difficulty or {}})
    if npc_by_id is None:
        npc_by_id = _load_npc_rows(DEFAULT_NPC_CSV)

    needed: dict[tuple[int, str], dict[str, Any]] = {}
    row_patch: dict[int, tuple[int, str]] = {}

    for row in assignments:
        try:
            base_think = int(row.get("think") or 0)
        except (TypeError, ValueError):
            base_think = 0
        # Re-plan path: spawn may already hold 890M ids — unwrap to donor base.
        if base_think >= THINK_COPY_ID_BASE:
            for key in ("think_donor", "think_base", "base_think"):
                try:
                    restored = int(row.get(key) or 0)
                except (TypeError, ValueError):
                    restored = 0
                if 0 < restored < THINK_COPY_ID_BASE:
                    base_think = restored
                    break
            else:
                continue
        if base_think >= THINK_COPY_ID_BASE:
            continue

        tgt_cat = str(row.get("tgt_cat") or "")
        if base_think <= 0:
            try:
                base_npc = int(row.get("npc_donor") or row.get("npc") or 0)
            except (TypeError, ValueError):
                base_npc = 0
            donor_row = npc_by_id.get(base_npc) if base_npc > 0 else None
            donor_think = 0
            if donor_row is not None:
                try:
                    donor_think = int(donor_row.get("think") or 0)
                except (TypeError, ValueError):
                    donor_think = 0
            base_think = resolve_safe_think(
                donor_think=donor_think,
                npc=base_npc,
                categories_cfg=categories_cfg,
                csv_dir=base_dir,
            )
            if base_think <= 0:
                continue
        lift = row.get("_adaptive_lift")
        t093_stat_mult = row.get("_t093_stat_mult")
        if lift is None:
            try:
                base_npc = int(row.get("npc_donor") or row.get("npc") or 0)
            except (TypeError, ValueError):
                base_npc = 0
            donor_row = npc_by_id.get(base_npc) if base_npc > 0 else None
            if donor_row is not None:
                meta = compute_row_adaptive_lift(
                    row,
                    donor_row,
                    difficulty=diff_settings,
                    npc_by_id=npc_by_id,
                    difficulty_cfg=diff_cfg,
                )
                lift = meta.get("lift", 0.0)
                t093_stat_mult = meta.get("t093_stat_mult", t093_stat_mult)
            else:
                lift = 0.0

        patch = compute_think_aggression_overrides(
            base_think,
            str(row.get("map_id") or ""),
            tgt_cat=tgt_cat,
            categories_cfg=categories_cfg,
            difficulty_cfg=diff_cfg,
            csv_dir=base_dir,
            adaptive_lift=float(lift or 0.0),
            t093_stat_mult=float(t093_stat_mult) if t093_stat_mult is not None else None,
        )
        # Extreme sense (eye 200 / nose 100 / forget 9999…): always clamp, even
        # when lift==0 or patrol kept the raw donor think id.
        patch = _merge_think_patches(
            patch,
            compute_think_extreme_sanitize_overrides(
                base_think,
                map_id=str(row.get("map_id") or ""),
                categories_cfg=categories_cfg,
                difficulty_cfg=diff_cfg,
                csv_dir=base_dir,
            ),
        )
        if tgt_cat == "night":
            patch = _merge_think_patches(
                patch,
                compute_think_night_clamp_overrides(
                    base_think,
                    categories_cfg=categories_cfg,
                    csv_dir=base_dir,
                ),
            )
        if patch is None:
            continue

        row["think_donor"] = base_think
        fp = think_patch_fingerprint(base_think, patch)
        needed[(base_think, fp)] = patch
        row_patch[id(row)] = (base_think, fp)

    keys = sorted(needed.keys())
    if len(keys) > (THINK_COPY_ID_LIMIT - THINK_COPY_ID_BASE):
        raise RuntimeError(
            f"T-059 think copy overflow: need {len(keys)} ids in "
            f"[{THINK_COPY_ID_BASE}, {THINK_COPY_ID_LIMIT})"
        )

    copy_ids = {k: THINK_COPY_ID_BASE + i for i, k in enumerate(keys)}

    for row in assignments:
        key = row_patch.get(id(row))
        if not key:
            continue
        row["think"] = copy_ids[key]
        row["think_copy"] = True

    copies: list[dict[str, Any]] = []
    for (base, fp), patch in sorted(needed.items(), key=lambda x: copy_ids[x[0]]):
        spec: dict[str, Any] = {
            "copy_id": copy_ids[(base, fp)],
            "base_think": base,
            "field_overrides": sanitize_think_field_overrides(
                dict(patch["field_overrides"])
            ),
            "slot_tier": patch["slot_tier"],
            "ai_scale": patch["ai_scale"],
            "adaptive_lift": patch.get("adaptive_lift", 0.0),
        }
        copies.append(spec)
    return copies
