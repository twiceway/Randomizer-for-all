"""One-shot Phase B3 extractor — run from cnv_randomizer/, delete after use."""
from __future__ import annotations

import ast
import textwrap
from pathlib import Path

CORE_PATH = Path(__file__).resolve().parent / "enemy_randomizer_core.py"
CORE_TEXT = CORE_PATH.read_text(encoding="utf-8")
CORE_LINES = CORE_TEXT.splitlines(keepends=True)
TREE = ast.parse(CORE_TEXT)

MODULES: dict[str, list[str]] = {
    "enemy_donor_pick": [
        "_weighted_category_try_order",
        "_audit_spawn_plan_gaps",
        "ArchetypeIndex",
        "ARCHETYPE_INDEX_CACHE",
        "load_archetype_index",
        "get_archetype_index",
        "group_pool_by_archetype",
        "resolve_donor_archetype_weight",
        "_TRASH_REVIEW_GROUP_BY_MODEL",
        "_TRASH_REVIEW_GROUP_BY_ARCHETYPE",
        "_load_trash_review_group_by_model",
        "trash_review_group_for_model",
        "trash_review_group_for_archetype",
        "resolve_trash_review_group_weight",
        "same_slot_model_pick_multiplier",
        "boss_donor_template_weights",
        "pick_boss_donor_by_template_indices",
        "trash_archetype_pick_mode",
        "trash_uniform_model_within_archetype",
        "archetype_model_counts_from_templates",
        "archetype_model_counts_from_indices",
        "resolve_trash_archetype_weights_balanced",
        "pick_weighted_archetype_id",
        "resolve_night_npc_weight",
        "resolve_pool_model_weight",
        "resolve_donor_model_weight",
        "pick_donor_model_from_bucket",
        "_pick_donor_model_key",
        "_POOL_PICK_MODES",
        "night_pick_mode",
        "pool_pick_mode",
        "pool_pick_uses_balanced_deal",
        "_indices_by_npc",
        "_uniform_npc_pick_weights",
        "_pick_uniform_npc_donor_index",
        "_night_npc_pick_weights",
        "night_donor_template_weights",
        "_pick_pool_donor_index",
        "_pick_night_donor_index",
        "_eligible_donor_indices_for_pick",
        "_plan_eligible_by_npc",
        "_clip_npc_balance_weight",
        "identify_structural_tail_npcs",
        "build_pool_npc_balance_weights",
        "_pick_balanced_npc_for_slot",
        "_contract_whitelist_pool_sizes",
        "build_balanced_pool_donor_assignments",
        "donor_pick_from_prep_index",
        "pick_donor_by_archetype",
        "pick_donor_by_archetype_indices",
        "drawable_category_weights",
        "_SlotPickPlan",
        "slot_rng",
        "normalize_row_weights",
        "weighted_choice",
        "_pick_plans_from_prep",
    ],
    "enemy_contract_templates": [
        "_group_templates_by_model",
        "supplement_synthetic_boss_templates",
        "_parse_contract_whitelist_model_map",
        "donor_template_chara",
        "is_contract_synthetic_template",
        "pick_best_donor_template",
        "build_contract_synthetic_donor_template",
        "compose_allowlist_donor_templates_by_cat",
        "supplement_contract_allowlist_templates",
        "_infer_think_from_npc",
        "resolve_runtime_think",
        "supplement_dlc_trash_templates",
        "supplement_dlc_boss_templates",
    ],
    "enemy_index_pipeline": [
        "_ENRICHED_INDEX_CACHE",
        "clear_enriched_index_cache",
        "_index_slots_look_enriched",
        "_apply_template_supplements",
        "enrich_index",
        "run_index_export",
        "load_enemy_index",
        "_ensure_msb_poc_built",
        "compat_filter",
        "build_compat_pools",
    ],
    "enemy_rune_soul": [
        "red_spirit_rune_tier_only",
        "NPC_SOUL_CACHE",
        "GAMEAREA_SOUL_CACHE",
        "load_npc_soul_map",
        "load_gamearea_soul_maps",
        "resolve_gamearea_soul",
        "normalize_mob_drop_mode",
        "apply_radahn_phase1_think",
        "apply_rune_map_scaling",
        "tier_baseline_rune_amount",
        "raw_donor_rune_soul",
        "_rune_allows_gamearea",
        "lookup_rune_amount",
    ],
    "enemy_spawn_io": [
        "write_map_spawn_audit",
        "NPC_DISPLAY_NAME_CACHE",
        "MAP_DISPLAY_NAME_CACHE",
        "prune_stale_flat_sidecars",
        "write_spawn_map",
        "pin_spawn_map_for_apply",
        "deploy_enemy_spawn_map",
        "write_risk_report",
        "_dsms_paramdex_paths",
        "load_npc_display_names",
        "load_map_display_names",
        "_format_category_zh",
        "resolve_model_display_zh",
        "_model_prefix_zh",
        "_donor_origin_tag",
        "write_spoiler_zh",
        "write_spoiler",
    ],
}

KEEP_IN_CORE = {
    "SCRIPT_DIR",
    "DEFAULT_INDEX_PATH",
    "DEFAULT_CATEGORIES_PATH",
    "DEFAULT_SIZE_TIERS_PATH",
    "DEFAULT_ARCHETYPES_PATH",
    "DEFAULT_RUNE_TIERS_PATH",
    "DEFAULT_GAMEAREA_SOULS_PATH",
    "DEFAULT_CONFIG_PATH",
    "MSB_POC_PROJECT",
    "MSB_POC_EXE",
    "CATEGORY_ORDER",
    "BOSS_SOURCE_CATEGORIES",
    "BOSS_TARGET_CATEGORIES",
    "TRASH_LIKE_TARGET_CATEGORIES",
    "RUNE_TIER_CAP_RED_SPIRIT_TGT",
    "resolve_enemy_worker_count",
    "resolve_prep_worker_count",
    "resolve_enemy_apply_parallel",
    "resolve_enemy_apply_max_parallel",
    "resolve_enemy_apply_map_inflight",
    "_enemy_gui_perf",
    "CATEGORY_DISPLAY_ZH",
    "CATEGORY_NUM",
    "EnemyGenerateResult",
    "_load_json",
    "_ENEMY_CALC_PHASE_SPAN",
    "_enemy_calc_progress",
    "run_enemy_randomize",
    "run_enemy_smoke",
}

HEADERS: dict[str, str] = {
    "enemy_donor_pick": '''"""T-084 B3 — donor pick / archetype lottery (extracted from enemy_randomizer_core)."""
from __future__ import annotations

import hashlib
import random
import statistics
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from boss_npc_detect import (
    is_horse_mount_model,
    is_summon_clone_donor_template,
)
from donor_pool_review_allowlist import normalize_category_id
from enemy_category_rules import (
    dungeon_boss_arena_pick_weights,
    evergaol_src_pick_weights,
    filter_scripted_fog_boss_donor_indices,
    is_scripted_dungeon_main_boss_slot,
    minor_boss_src_pick_weights,
    night_model_label,
    scripted_dungeon_boss_pick_weights,
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
    _PREP_REVALIDATE_SKIP_KEYS,
    _count_prep_skip_bucket,
    describe_slot_policy,
    revalidate_prep_skip_key,
    resolve_effective_slot_skip,
    runtime_slot_skip_after_prep,
    slot_physique_bucket,
)
from paths import GAME_DIR

''',
    "enemy_contract_templates": '''"""T-084 B3 — contract / synthetic donor templates (extracted from enemy_randomizer_core)."""
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

''',
    "enemy_index_pipeline": '''"""T-084 B3 — enemy index enrich / export pipeline (extracted from enemy_randomizer_core)."""
from __future__ import annotations

import json
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
from paths import CACHE_DIR, GAME_DIR

''',
    "enemy_rune_soul": '''"""T-084 B3 — rune / soul reward helpers (extracted from enemy_randomizer_core)."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from boss_npc_detect import is_red_spirit_model, is_summon_clone_donor_template
from paths import GAME_DIR

''',
    "enemy_spawn_io": '''"""T-084 B3 — spawn map I/O, audit, spoiler (extracted from enemy_randomizer_core)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from enemy_category_rules import (
    is_dlc_trash_donor_model,
    is_risky_assignment,
    resolve_src_category,
    slot_physique_bucket,
    _model_has_prefix,
)
from enemy_donor_pick import _SlotPickPlan
from enemy_rune_soul import load_npc_soul_map
from enemy_slot_rules import describe_slot_policy
from enemy_spawn_bundle import (
    DEFAULT_ENEMY_SPAWN_MAP,
    parse_spawn_map_header,
    resolve_spawn_map_sidecar_paths,
    spawn_map_seed_from_path,
    spawn_map_sidecar_paths,
    validate_spawn_bundle,
    verify_spawn_deployed,
)
from paths import GAME_DIR

''',
}


def _node_range(node: ast.AST) -> tuple[int, int]:
    start = node.lineno - 1
    end = getattr(node, "end_lineno", node.lineno) - 1
    return start, end


def _name_from_target(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    return None


def _node_matches(node: ast.AST, names: set[str]) -> bool:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return node.name in names
    if isinstance(node, ast.Assign):
        return any(_name_from_target(t) in names for t in node.targets)
    if isinstance(node, ast.AnnAssign):
        return _name_from_target(node.target) in names
    return False


def extract_names(names: set[str]) -> str:
    chunks: list[str] = []
    for node in TREE.body:
        if _node_matches(node, names):
            s, e = _node_range(node)
            chunks.append("".join(CORE_LINES[s : e + 1]))
    return "\n\n".join(chunks)


def collect_module_top_names(path: Path) -> set[str]:
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    names.add(t.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


B2_REMOVE_NAMES: set[str] = set()
for _mod in (
    "enemy_category_rules.py",
    "enemy_mount_pairs.py",
    "enemy_slot_rules.py",
    "enemy_pool_filters.py",
):
    _p = CORE_PATH.parent / _mod
    if _p.is_file():
        B2_REMOVE_NAMES |= collect_module_top_names(_p)

# Core keeps these even if duplicated in B2 modules
B2_REMOVE_NAMES -= KEEP_IN_CORE
B2_REMOVE_NAMES -= {
    "SCRIPT_DIR",
    "DEFAULT_SIZE_TIERS_PATH",
    "BOSS_SOURCE_CATEGORIES",
    "BOSS_TARGET_CATEGORIES",
    "TRASH_LIKE_TARGET_CATEGORIES",
    "CATEGORY_ORDER",
    "_load_json",
}

B2_FACADE = textwrap.dedent(
    '''
    # --- Phase B2 extracted modules (facade re-exports) ---
    from enemy_pool_filters import (  # noqa: E402
        filter_pool_for_major_boss_named_targets as filter_pool_for_cnv_special_targets,
    )
    from enemy_category_rules import (  # noqa: F401
        EVERGAOL_SRC_ALLOWED_TGT,
        MINOR_BOSS_SRC_ALLOWED_TGT,
        SIZE_TIER_RANK,
        all_size_tier_ids,
        boss_donor_allowed_on_compact_slot,
        compact_slot_donor_block_tiers,
        compact_slot_tiers,
        dlc_trash_enabled_for_slot,
        donor_blocked_for_narrow_placement,
        donor_physique_bucket,
        dungeon_boss_arena_pick_weights,
        effective_map_kind,
        effective_slot_map_kind,
        evergaol_src_pick_weights,
        field_cavalry_mount_prefixes,
        field_cavalry_rider_prefixes,
        filter_pool_by_dlc_mode,
        filter_scripted_fog_boss_donor_indices,
        flying_model_prefixes,
        infer_category,
        infer_size_tier,
        is_boss_pool_excluded_donor,
        is_boss_pool_excluded_donor_model,
        is_cnv_named_boss_donor_template,
        is_cnv_original_boss_slot_npc_id,
        is_dlc_enemy_map,
        is_dlc_trash_donor_model,
        is_eligible_trash_donor_model,
        is_excluded_size_tier,
        is_excluded_slot_model,
        is_excluded_slot_npc_id,
        is_field_cavalry_mount_model,
        is_field_cavalry_rider_model,
        is_horse_mount_model,
        is_humanoid_slot_allowed_donor,
        is_humanoid_slot_blocked_boss_donor,
        is_humanoid_slot_blocked_donor,
        is_hub_map_slot,
        is_invisible_enemy_model,
        is_keep_original_slot_model,
        is_minor_boss_catalog_donor,
        is_never_donor_model,
        is_never_donor_npc_id,
        is_night_mount_model,
        is_night_rider_model,
        is_non_participating_map,
        is_passive_animal_model,
        is_pristine_map_slot,
        is_risky_assignment,
        is_siege_c1000_operator_slot,
        is_siege_mount_rider_slot,
        is_siege_operator_slot,
        is_scripted_dungeon_main_boss_slot,
        is_trash_donor_model,
        is_unsafe_donor_template,
        load_size_tier_meta,
        map_kind,
        minor_boss_src_pick_weights,
        narrow_map_donor_block_tiers,
        narrow_map_kinds,
        needs_summon,
        night_model_label,
        passive_animal_model_prefixes,
        promote_cnv_named_boss_slots,
        promote_cnv_named_boss_template_categories,
        quadruped_model_prefixes,
        red_spirit_model_label,
        refine_cnv_boss_tag_slots,
        refine_cnv_boss_tag_template_categories,
        refine_cnv_new_npc_red_spirit_categories,
        refine_cnv_new_npc_red_spirit_slots,
        refine_cnv_special_template_categories,
        resolve_donor_npc_id,
        resolve_donor_origin,
        resolve_size_tier,
        resolve_src_category,
        restore_hub_map_overlays,
        scripted_dungeon_boss_pick_weights,
        should_skip_excluded_slot_tier,
        should_skip_large_slot,
        should_skip_medium_dungeon_slot,
        should_skip_zone_restricted_slot,
        size_tier_placement_aux,
        size_tier_rank,
        size_tier_rank_map,
        slot_physique_bucket,
        template_donor_map_id,
        template_is_dlc_boss_donor,
        _model_has_prefix,
    )
    from enemy_mount_pairs import (  # noqa: F401
        CNV_DEMOUNT_TEMPLATE_SUFFIX,
        CNV_SUPPRESS_DECORATIVE_TEMPLATE,
        CNV_SUPPRESS_MOUNT_TEMPLATE,
        MountPairDonor,
        build_global_mount_pair_pool,
        build_mount_pair_donors,
        find_mount_pair_for_rider_template,
        index_rider_mount_slot_pairs,
        mount_entity_suffix,
        mount_pair_kind_configs,
        mount_pair_kind_for_category,
        mount_pair_kind_label,
        mount_pair_pool_for_slot,
        mount_pair_randomize_enabled,
        pick_mount_pair_donor,
        skip_mount_pair_entity_when_disabled,
        slot_is_mount_pair_entity,
        slot_is_mount_pair_rider_model,
        slot_is_mount_rider_slot,
        slot_is_mounted_rider,
        template_is_mount_unit_donor,
        template_is_mounted_rider,
    )
    from enemy_slot_rules import (  # noqa: F401
        _assignment_to_spawn_line,
        _count_prep_skip_bucket,
        _slot_apply_collision_policy,
        _slot_placement_kind,
        augment_spawn_map_path_with_decorative_suppress,
        build_decorative_suppress_assignments,
        collect_slot_skip_rule_ids,
        describe_slot_policy,
        is_decorative_npc_slot,
        is_decorative_suppress_slot,
        is_msb_talk_slot,
        is_talk_npc_slot,
        revalidate_prep_skip_key,
        resolve_effective_slot_skip,
        runtime_slot_skip_after_prep,
        runtime_slot_skip_bucket,
        slot_has_walk_route,
    )
    '''
)

POOL_FILTERS_FACADE = textwrap.dedent(
    '''
    from enemy_pool_filters import (  # noqa: F401 — facade re-export
        filter_pool_for_narrow_placement,
        filter_pool_for_scripted_fog_boss_donors,
        filter_pool_for_red_spirit_targets,
        filter_pool_for_major_boss_named_targets,
        filter_pool_for_field_boss_targets,
        filter_pool_for_night_targets,
        filter_pool_for_physique_compat,
        filter_prep_donor_indices_for_physique_compat,
        filter_pool_for_trash_targets,
        filter_pool_for_boss_target_donors,
        filter_pool_for_boss_slot_compat,
        filter_prep_donor_indices_for_slot,
        filter_pool_for_safe_donors,
        filter_pool_for_mount_compat,
        _compat_pool_for_slot_tier,
        filter_slot_donor_pool,
    )
    '''
)


def build_removed_line_set() -> set[int]:
    removed: set[int] = set()
    all_moved = set().union(*MODULES.values()) | B2_REMOVE_NAMES
    for node in TREE.body:
        if _node_matches(node, all_moved):
            s, e = _node_range(node)
            removed.update(range(s, e + 1))
    return removed


FACADE = textwrap.dedent(
    '''
    # --- Phase B3 extracted modules (facade re-exports) ---
    from enemy_donor_pick import (  # noqa: F401
        ARCHETYPE_INDEX_CACHE,
        ArchetypeIndex,
        _SlotPickPlan,
        _audit_spawn_plan_gaps,
        _pick_plans_from_prep,
        _weighted_category_try_order,
        archetype_model_counts_from_indices,
        archetype_model_counts_from_templates,
        boss_donor_template_weights,
        build_balanced_pool_donor_assignments,
        build_pool_npc_balance_weights,
        donor_pick_from_prep_index,
        drawable_category_weights,
        get_archetype_index,
        group_pool_by_archetype,
        identify_structural_tail_npcs,
        load_archetype_index,
        night_donor_template_weights,
        night_pick_mode,
        normalize_row_weights,
        pick_boss_donor_by_template_indices,
        pick_donor_by_archetype,
        pick_donor_by_archetype_indices,
        pick_donor_model_from_bucket,
        pick_weighted_archetype_id,
        pool_pick_mode,
        pool_pick_uses_balanced_deal,
        resolve_donor_archetype_weight,
        resolve_donor_model_weight,
        resolve_night_npc_weight,
        resolve_pool_model_weight,
        resolve_trash_archetype_weights_balanced,
        resolve_trash_review_group_weight,
        same_slot_model_pick_multiplier,
        slot_rng,
        trash_archetype_pick_mode,
        trash_review_group_for_archetype,
        trash_review_group_for_model,
        trash_uniform_model_within_archetype,
        weighted_choice,
    )
    from enemy_contract_templates import (  # noqa: F401
        build_contract_synthetic_donor_template,
        compose_allowlist_donor_templates_by_cat,
        donor_template_chara,
        is_contract_synthetic_template,
        pick_best_donor_template,
        resolve_runtime_think,
        supplement_contract_allowlist_templates,
        supplement_dlc_boss_templates,
        supplement_dlc_trash_templates,
        supplement_synthetic_boss_templates,
    )
    from enemy_index_pipeline import (  # noqa: F401
        build_compat_pools,
        clear_enriched_index_cache,
        compat_filter,
        enrich_index,
        load_enemy_index,
        run_index_export,
    )
    from enemy_rune_soul import (  # noqa: F401
        apply_radahn_phase1_think,
        apply_rune_map_scaling,
        load_gamearea_soul_maps,
        load_npc_soul_map,
        lookup_rune_amount,
        normalize_mob_drop_mode,
        raw_donor_rune_soul,
        red_spirit_rune_tier_only,
        resolve_gamearea_soul,
        tier_baseline_rune_amount,
    )
    from enemy_spawn_io import (  # noqa: F401
        deploy_enemy_spawn_map,
        load_map_display_names,
        load_npc_display_names,
        pin_spawn_map_for_apply,
        prune_stale_flat_sidecars,
        resolve_model_display_zh,
        write_map_spawn_audit,
        write_risk_report,
        write_spawn_map,
        write_spoiler,
        write_spoiler_zh,
    )
    '''
)


def inject_function_imports(module: str, body: str) -> str:
    """Prepend lazy core imports inside functions that need them."""
    injections: dict[str, dict[str, str]] = {
        "enemy_donor_pick": {
            "load_archetype_index": "    from enemy_randomizer_core import DEFAULT_ARCHETYPES_PATH, SCRIPT_DIR, _load_json\n",
            "_load_trash_review_group_by_model": "    from enemy_randomizer_core import SCRIPT_DIR, _load_json\n",
            "_pick_plans_from_prep": "    from enemy_randomizer_core import _enemy_calc_progress\n    from enemy_slot_rules import _PREP_REVALIDATE_SKIP_KEYS\n",
        },
        "enemy_index_pipeline": {
            "run_index_export": "    from enemy_randomizer_core import DEFAULT_CATEGORIES_PATH, DEFAULT_INDEX_PATH, _load_json\n",
            "load_enemy_index": "    from enemy_randomizer_core import DEFAULT_CATEGORIES_PATH, DEFAULT_INDEX_PATH, _load_json\n",
            "_ensure_msb_poc_built": "    from enemy_randomizer_core import MSB_POC_EXE, MSB_POC_PROJECT\n",
            "build_compat_pools": "    from enemy_randomizer_core import BOSS_SOURCE_CATEGORIES, BOSS_TARGET_CATEGORIES, CATEGORY_ORDER\n",
        },
        "enemy_rune_soul": {
            "red_spirit_rune_tier_only": "    from enemy_randomizer_core import RUNE_TIER_CAP_RED_SPIRIT_TGT, TRASH_LIKE_TARGET_CATEGORIES\n",
            "load_gamearea_soul_maps": "    from enemy_randomizer_core import DEFAULT_GAMEAREA_SOULS_PATH\n",
            "_rune_allows_gamearea": "    from enemy_randomizer_core import BOSS_SOURCE_CATEGORIES\n",
            "lookup_rune_amount": "    from enemy_randomizer_core import BOSS_SOURCE_CATEGORIES, TRASH_LIKE_TARGET_CATEGORIES\n",
        },
        "enemy_spawn_io": {
            "_format_category_zh": "    from enemy_randomizer_core import CATEGORY_DISPLAY_ZH, CATEGORY_NUM\n",
            "resolve_model_display_zh": "    from enemy_randomizer_core import BOSS_SOURCE_CATEGORIES\n",
            "write_spawn_map": "    from enemy_randomizer_core import DEFAULT_CATEGORIES_PATH\n",
            "write_spoiler_zh": "    from enemy_randomizer_core import CATEGORY_DISPLAY_ZH, CATEGORY_NUM, CATEGORY_ORDER\n",
        },
        "enemy_contract_templates": {
            "compose_allowlist_donor_templates_by_cat": "    from enemy_randomizer_core import CATEGORY_ORDER\n",
            "supplement_contract_allowlist_templates": "    from enemy_randomizer_core import CATEGORY_ORDER\n",
        },
    }
    for func, imp in injections.get(module, {}).items():
        needle = f"def {func}("
        idx = body.find(needle)
        if idx < 0:
            continue
        colon = body.find(":", idx)
        if colon < 0:
            continue
        doc_end = colon + 1
        if body[colon + 1 : colon + 4] == ' """' or body[colon + 1 : colon + 4] == " '''":
            q = body[colon + 2]
            doc_end = body.find(q * 3, colon + 3)
            if doc_end >= 0:
                doc_end = body.find("\n", doc_end) + 1
        else:
            doc_end = body.find("\n", colon) + 1
        if imp.strip() not in body[doc_end : doc_end + 400]:
            body = body[:doc_end] + imp + body[doc_end:]
    return body


def collapse_blank_lines(text: str, max_run: int = 2) -> str:
    out: list[str] = []
    blank = 0
    for line in text.splitlines(keepends=True):
        if line.strip() == "":
            blank += 1
            if blank <= max_run:
                out.append(line)
        else:
            blank = 0
            out.append(line)
    return "".join(out)


def main() -> None:
    root = CORE_PATH.parent
    for mod, names in MODULES.items():
        body = extract_names(set(names))
        body = inject_function_imports(mod, body)
        content = HEADERS[mod] + body + "\n"
        (root / f"{mod}.py").write_text(content, encoding="utf-8")
        print(f"wrote {mod}.py lines={content.count(chr(10))}")

    removed = build_removed_line_set()
    kept: list[str] = []
    for i, line in enumerate(CORE_LINES):
        if i not in removed:
            kept.append(line)

    # Insert facade before final enemy_pool_filters re-export
    text = collapse_blank_lines("".join(kept))

    # Insert facades before CLI block
    cli_marker = 'if __name__ == "__main__":'
    if cli_marker not in text:
        raise SystemExit("CLI marker not found")
    facade_block = (
        B2_FACADE.lstrip("\n")
        + "\n"
        + FACADE.lstrip("\n")
        + "\n"
        + POOL_FILTERS_FACADE.lstrip("\n")
        + "\n\n"
    )
    text = text.replace(cli_marker, facade_block + cli_marker)

    CORE_PATH.write_text(text, encoding="utf-8")
    print(f"core lines={text.count(chr(10))}")


if __name__ == "__main__":
    main()
