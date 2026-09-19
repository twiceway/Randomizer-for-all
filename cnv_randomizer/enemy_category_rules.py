"""Enemy category / size-tier / map-kind / donor classification rules (extracted from enemy_randomizer_core)."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from boss_npc_detect import (
    is_dungeon_map_id,
    is_force_trash_model,
    is_indoor_dungeon_boss_arena_slot,
    is_oversize_boss_model,
    is_red_spirit_combat_slot,
    is_talk_npc_id,
    resolve_entity_category,
    template_is_cnv_new_npc_red_spirit,
    template_is_cnv_pool7_marked_npc,
)
from donor_pool_review_allowlist import (
    is_allowlisted_donor_template,
    normalize_category_id,
)
from paths import GAME_DIR, SCRIPT_DIR

DEFAULT_SIZE_TIERS_PATH = SCRIPT_DIR / "enemy_size_tiers.json"

_SCRIPTED_DUNGEON_BOSS_TGT = frozenset({"major_boss"})
_SCRIPTED_DUNGEON_BOSS_SLOT_RE = re.compile(r"^c\d{4}_9000$", re.IGNORECASE)
EVERGAOL_SRC_ALLOWED_TGT = frozenset({"evergaol", "night", "major_boss"})
MINOR_BOSS_SRC_ALLOWED_TGT = frozenset(
    {
        "elite",
        "minor_boss",
        "evergaol",
        "night",
        "major_boss",
    }
)

_SIZE_TIER_META_CACHE: dict[str, Any] | None = None


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


SIZE_TIER_RANK = {
    "tiny": 0,
    "small": 0,
    "humanoid": 1,
    "mounted": 2,
    "medium": 3,
    "tall": 3,
    "large": 4,
    "colossal": 4,
    "flying": 4,
    "boss": 5,
}

_SIZE_TIER_META_CACHE: dict[str, Any] | None = None


def load_size_tier_meta(path: Path | None = None) -> dict[str, Any]:
    global _SIZE_TIER_META_CACHE
    if _SIZE_TIER_META_CACHE is not None:
        return _SIZE_TIER_META_CACHE
    p = path or DEFAULT_SIZE_TIERS_PATH
    if p.is_file():
        data = _load_json(p)
        meta = data.get("tier_meta") or {}
        if meta:
            _SIZE_TIER_META_CACHE = meta
            return meta
    _SIZE_TIER_META_CACHE = {}
    return {}


def size_tier_rank_map() -> dict[str, int]:
    meta = load_size_tier_meta()
    if meta:
        return {str(k): int(v.get("rank", 1)) for k, v in meta.items()}
    return dict(SIZE_TIER_RANK)


def all_size_tier_ids() -> tuple[str, ...]:
    meta = load_size_tier_meta()
    if meta:
        return tuple(meta.keys())
    return tuple(SIZE_TIER_RANK.keys())


def size_tier_placement_aux(categories_cfg: dict[str, Any]) -> dict[str, Any]:
    """体型表辅助七类池：仅约束狭窄放置，不改 src/tgt 池归属。"""
    aux = categories_cfg.get("size_tier_placement_aux")
    if isinstance(aux, dict) and aux:
        return aux
    return {
        "definition": "不改动七类池；狭窄地图禁捐皮体型>槽位体型；小型槽禁骑乘/中型/高型捐皮",
        "narrow_map_kinds": ["dungeon"],
        "compact_slot_tiers": ["tiny", "small", "humanoid"],
        "compact_slot_donor_block_tiers": ["mounted", "tall", "boss", "large"],
    }


def narrow_map_donor_block_tiers(categories_cfg: dict[str, Any]) -> set[str]:
    aux = size_tier_placement_aux(categories_cfg)
    return set(str(t) for t in (aux.get("narrow_map_donor_block_tiers") or []))


def compact_slot_donor_block_tiers(categories_cfg: dict[str, Any]) -> set[str]:
    aux = size_tier_placement_aux(categories_cfg)
    explicit = aux.get("compact_slot_donor_block_tiers")
    if explicit:
        return set(str(t) for t in explicit)
    return narrow_map_donor_block_tiers(categories_cfg)


def compact_slot_tiers(categories_cfg: dict[str, Any]) -> set[str]:
    aux = size_tier_placement_aux(categories_cfg)
    return set(
        str(t)
        for t in (aux.get("compact_slot_tiers") or ["tiny", "small", "humanoid"])
    )


def narrow_map_kinds(categories_cfg: dict[str, Any]) -> set[str]:
    aux = size_tier_placement_aux(categories_cfg)
    return set(str(k) for k in (aux.get("narrow_map_kinds") or ["dungeon"]))


_NARROW_ENV_BOSS_TGT = frozenset({"minor_boss", "major_boss", "evergaol"})
_DEFAULT_NARROW_DRAGON_DONOR_PREFIXES = (
    "c4500",
    "c4501",
    "c4502",
    "c4503",
    "c4504",
    "c4505",
    "c4510",
    "c4511",
    "c4520",
    "c4690",
    "c5370",
    "c5580",
    "c5661",
)


def narrow_map_medium_max_rank(categories_cfg: dict[str, Any] | None = None) -> int:
    """狭窄环境非 Boss 位：捐皮体型上限（含 medium/tall 同 rank=3）。"""
    cfg = categories_cfg if isinstance(categories_cfg, dict) else {}
    aux = size_tier_placement_aux(cfg)
    tier_id = str(aux.get("narrow_map_medium_max_tier") or "medium")
    return size_tier_rank(tier_id)


def narrow_map_block_dragon_donor_prefixes(
    categories_cfg: dict[str, Any],
) -> list[str]:
    aux = size_tier_placement_aux(categories_cfg)
    raw = aux.get("narrow_map_block_dragon_donor_prefixes")
    if raw:
        return [str(p).lower() for p in raw]
    return list(_DEFAULT_NARROW_DRAGON_DONOR_PREFIXES)


def is_wyvern_or_ancient_dragon_donor(
    model: str, categories_cfg: dict[str, Any]
) -> bool:
    """飞龙/古龙：洞窟/墓穴/室内/城内一律不捐（含 Boss 位）。"""
    return _model_has_prefix(model, narrow_map_block_dragon_donor_prefixes(categories_cfg))


def is_narrow_environment_boss_slot(
    slot: dict[str, Any],
    categories_cfg: dict[str, Any],
    *,
    tgt_cat: str = "",
) -> bool:
    """洞窟/墓穴/室内/城内 Boss 战点（含 _9000 雾门与 2/3/6 池目标）。"""
    map_k = effective_slot_map_kind(slot, categories_cfg)
    if map_k not in narrow_map_kinds(categories_cfg):
        return False
    if is_scripted_dungeon_main_boss_slot(slot, categories_cfg):
        return True
    if is_indoor_dungeon_boss_arena_slot(slot, categories_cfg):
        return True
    return str(tgt_cat or "") in _NARROW_ENV_BOSS_TGT


def donor_blocked_for_narrow_placement(
    donor_tier: str,
    slot_tier: str,
    map_id: str,
    categories_cfg: dict[str, Any],
    *,
    tgt_cat: str = "",
    entity_name: str = "",
    donor_model: str = "",
    slot: dict[str, Any] | None = None,
    is_boss_slot: bool | None = None,
) -> bool:
    """狭窄环境体型辅助（T-097）：≤中型可捐；大型/超巨/主线Boss/飞龙古龙禁区一律拒。"""
    del is_boss_slot  # T-097：不再用「室内 Boss 位豁免 oversized」
    block_tiers = compact_slot_donor_block_tiers(categories_cfg)
    medium_cap = narrow_map_medium_max_rank(categories_cfg)
    map_k = effective_map_kind(
        map_id, categories_cfg, entity_name=entity_name or None
    )
    narrow = map_k in narrow_map_kinds(categories_cfg)
    if tgt_cat == "night":
        # 5 池红灵：可贴 tiny/small/洞窟路边；仍禁 oversized 与 compact 禁档
        if slot_tier in compact_slot_tiers(categories_cfg) and donor_tier in block_tiers:
            return True
        if narrow and size_tier_rank(donor_tier) > medium_cap:
            return True
        return False
    if donor_model and narrow and is_wyvern_or_ancient_dragon_donor(
        donor_model, categories_cfg
    ):
        return True
    # T-097：禁区不放 oversized（含室内 Boss 位；废止「仅 Boss 位可捐大型」）
    if narrow and size_tier_rank(donor_tier) > medium_cap:
        return True
    if narrow and donor_tier == "flying":
        return True
    if slot_tier in compact_slot_tiers(categories_cfg) and donor_tier in block_tiers:
        return True
    if narrow and slot_tier == "medium" and donor_tier in block_tiers:
        return True
    return False
def map_kind(map_id: str) -> str:
    parts = map_id.rsplit("_", 1)
    if len(parts) == 2 and parts[1] == "00":
        return "overworld"
    return "dungeon"


def effective_map_kind(
    map_id: str,
    categories_cfg: dict[str, Any] | None = None,
    *,
    entity_name: str | None = None,
) -> str:
    """城内/室内图按 dungeon 做体型辅助（禁飞行捐皮等），尽管 map id 末段常为 _00。"""
    mid = str(map_id)
    if categories_cfg and entity_name:
        key = f"{mid}:{entity_name}"
        overrides = categories_cfg.get("slot_map_kind_overrides") or {}
        if key in overrides:
            return str(overrides[key])
    if categories_cfg:
        for prefix in categories_cfg.get("interior_map_id_prefixes") or []:
            if mid.startswith(str(prefix)):
                return "dungeon"
    return map_kind(mid)


def effective_slot_map_kind(
    slot: dict[str, Any],
    categories_cfg: dict[str, Any] | None = None,
) -> str:
    """槽位室内判定：先 slot_map_kind_overrides，再图前缀。"""
    return effective_map_kind(
        str(slot.get("map_id", "")),
        categories_cfg,
        entity_name=str(slot.get("name") or slot.get("entity") or ""),
    )


_SCRIPTED_DUNGEON_BOSS_TGT = frozenset({"major_boss"})
_SCRIPTED_DUNGEON_BOSS_SLOT_RE = re.compile(r"^c\d{4}_9000$", re.IGNORECASE)
# 监牢源槽（3 池）允许的目标：3~7 池；禁止 1 池 trash、2 池洞穴小 Boss
EVERGAOL_SRC_ALLOWED_TGT = frozenset({"evergaol", "night", "major_boss"})
# 洞穴/墓地 Boss 源槽（2 池）：只抽 2~7 池；禁止 1 池 trash（防 Boss 房刷肉泥/亚人）
MINOR_BOSS_SRC_ALLOWED_TGT = frozenset(
    {
        "elite",
        "minor_boss",
        "evergaol",
        "night",
        "major_boss",
    }
)


def is_scripted_dungeon_main_boss_slot(
    slot: dict[str, Any], categories_cfg: dict[str, Any]
) -> bool:
    """主线 Boss 雾门战点（妖鬼/葛瑞克/大树守卫等 MSB _9000 槽）。

    entity_id 不变、只换 model/npc/think，故 trash 皮也能触发 Boss 血条与雾门结算。
    注：史东薇尔 m10_00_00_00 经 interior_map_id_prefixes 按 dungeon 做体型辅助；雾门 _9000 主线 Boss 槽不受狭窄过滤。
    """
    model = str(slot.get("model", "")).lower()
    if resolve_src_category(model, categories_cfg) != "major_boss":
        return False
    return bool(_SCRIPTED_DUNGEON_BOSS_SLOT_RE.match(str(slot.get("name", ""))))


def scripted_dungeon_boss_pick_weights(
    src_cat: str,
    norm: dict[str, float],
    slot: dict[str, Any],
    categories_cfg: dict[str, Any],
) -> tuple[str, dict[str, float]]:
    """防旧 prep 把妖鬼等标成 minor_boss 后抽到亚人：强制只抽 6/7 池。"""
    if not is_scripted_dungeon_main_boss_slot(slot, categories_cfg):
        return src_cat, norm
    src_cat = "major_boss"
    clamped = {k: v for k, v in norm.items() if k in _SCRIPTED_DUNGEON_BOSS_TGT}
    if not clamped:
        clamped = {"major_boss": 1.0}
    from enemy_randomizer_core import normalize_row_weights

    return src_cat, normalize_row_weights(clamped)


def evergaol_src_pick_weights(
    src_cat: str,
    norm: dict[str, float],
    slot: dict[str, Any],
    categories_cfg: dict[str, Any],
) -> tuple[str, dict[str, float]]:
    """监牢源槽：只抽监牢及以上 Boss 目标；GUI 矩阵若误留 trash/minor_boss 也剔除。"""
    _ = slot, categories_cfg
    if src_cat != "evergaol":
        return src_cat, norm
    clamped = {k: v for k, v in norm.items() if k in EVERGAOL_SRC_ALLOWED_TGT}
    if not clamped:
        clamped = {"evergaol": 1.0}
    from enemy_randomizer_core import normalize_row_weights

    return src_cat, normalize_row_weights(clamped)


def minor_boss_src_pick_weights(
    src_cat: str,
    norm: dict[str, float],
    slot: dict[str, Any],
    categories_cfg: dict[str, Any],
) -> tuple[str, dict[str, float]]:
    """洞窟/墓地 Boss 源槽（2 池）：禁止抽到 1 池 trash 目标。"""
    _ = slot, categories_cfg
    if src_cat != "minor_boss":
        return src_cat, norm
    clamped = {k: v for k, v in norm.items() if k in MINOR_BOSS_SRC_ALLOWED_TGT}
    if not clamped:
        clamped = {"minor_boss": 1.0}
    from enemy_randomizer_core import normalize_row_weights

    return src_cat, normalize_row_weights(clamped)


def dungeon_boss_arena_pick_weights(
    src_cat: str,
    norm: dict[str, float],
    slot: dict[str, Any],
    categories_cfg: dict[str, Any],
) -> tuple[str, dict[str, float]]:
    """洞窟/墓地 ``c####_9000`` Boss 战点：默认锁 3 池 minor_boss；可被 ``dungeon_boss_arena_tgt_overrides`` 覆盖。"""
    map_id = str(slot.get("map_id", ""))
    entity = str(slot.get("name", ""))
    if not _SCRIPTED_DUNGEON_BOSS_SLOT_RE.match(entity):
        return src_cat, norm
    if not is_dungeon_map_id(map_id, categories_cfg):
        return src_cat, norm
    overrides = categories_cfg.get("dungeon_boss_arena_tgt_overrides") or {}
    override_key = f"{map_id}:{entity}"
    if override_key in overrides:
        row = overrides[override_key]
        if isinstance(row, dict) and row:
            clamped = {
                str(k): float(v)
                for k, v in row.items()
                if float(v) > 0
            }
            if clamped:
                from enemy_randomizer_core import normalize_row_weights

                return src_cat, normalize_row_weights(clamped)
    if src_cat not in ("minor_boss", "evergaol"):
        return src_cat, norm
    return src_cat, {"minor_boss": 1.0}


def filter_scripted_fog_boss_donor_indices(
    prep: dict[str, Any],
    slot: dict[str, Any],
    indices: list[int],
    *,
    categories_cfg: dict[str, Any],
) -> list[int]:
    """雾门主线 Boss 槽：仅 synthetic 捐皮（禁路边山妖/亚人等借皮）。"""
    if not indices or not is_scripted_dungeon_main_boss_slot(slot, categories_cfg):
        return indices
    donors = prep.get("donors") or []
    return [
        i
        for i in indices
        if 0 <= i < len(donors)
        and str(donors[i].get("template_id", "")).startswith("synthetic:")
        and not is_boss_pool_excluded_donor(donors[i], categories_cfg)
    ]


def fog_major_boss_swap_indices(
    prep: dict[str, Any],
    categories_cfg: dict[str, Any],
    *,
    blocked_indices: frozenset[int] | set[int] | None = None,
) -> list[int]:
    """雾门 6 池互洗：合成主线 Boss 全表互抽。

    prep 紧凑捐皮常无 ``category``，且故事 Boss 合成行未必进过 ``donors``。
    以 ``synthetic_boss_templates`` 为准：缺的补进 ``prep["donors"]``，再返回下标。
    """
    donors: list[dict[str, Any]] = prep.setdefault("donors", [])
    blocked = blocked_indices or frozenset()
    by_id: dict[str, int] = {
        str(d.get("template_id", "")): i
        for i, d in enumerate(donors)
        if d.get("template_id")
    }
    out: list[int] = []
    seen: set[int] = set()
    for raw in categories_cfg.get("synthetic_boss_templates") or []:
        tid = str(raw.get("template_id", ""))
        if not tid.startswith("synthetic:"):
            continue
        cat = str(raw.get("category") or "")
        if cat not in ("major_boss", "cnv_special"):
            inferred = resolve_src_category(str(raw.get("model", "")), categories_cfg)
            if inferred not in ("major_boss", "cnv_special"):
                continue
            cat = inferred
        stub = {
            "template_id": tid,
            "model": raw.get("model"),
            "npc": raw.get("npc"),
            "think": raw.get("think"),
            "chara": raw.get("chara", -1),
            "category": cat,
            "donor_map": raw.get("donor_map"),
            "donor_entity": raw.get("donor_entity"),
        }
        if is_boss_pool_excluded_donor(stub, categories_cfg):
            continue
        if tid in by_id:
            i = by_id[tid]
            if not donors[i].get("category"):
                donors[i]["category"] = cat
        else:
            i = len(donors)
            donors.append(stub)
            by_id[tid] = i
        if i in blocked or i in seen:
            continue
        seen.add(i)
        out.append(i)
    return out
def infer_category(model: str, rules: list[dict[str, str]], default: str) -> str:
    model_lower = (model or "").lower()
    return _infer_category_cached(model_lower, _src_cat_rules_key(rules), str(default))


_SRC_CAT_RULES_KEYS: dict[int, tuple[tuple[str, str], ...]] = {}


def _src_cat_rules_key(rules: list[dict[str, str]]) -> tuple[tuple[str, str], ...]:
    mid = id(rules)
    key = _SRC_CAT_RULES_KEYS.get(mid)
    if key is None:
        key = tuple(
            (str(r.get("match_model_prefix", "")).lower(), str(r.get("category", "")))
            for r in rules
        )
        _SRC_CAT_RULES_KEYS[mid] = key
    return key


@lru_cache(maxsize=32768)
def _infer_category_cached(
    model_lower: str,
    rules_key: tuple[tuple[str, str], ...],
    default: str,
) -> str:
    for prefix, category in rules_key:
        if prefix and model_lower.startswith(prefix):
            return category
    return default


_TIER_MAP_KEYS: dict[int, tuple[tuple[str, str], ...]] = {}


def _tier_map_key(tier_map: dict[str, str]) -> tuple[tuple[str, str], ...]:
    mid = id(tier_map)
    key = _TIER_MAP_KEYS.get(mid)
    if key is None:
        key = tuple(sorted((str(k), str(v)) for k, v in tier_map.items()))
        _TIER_MAP_KEYS[mid] = key
    return key


@lru_cache(maxsize=32768)
def _infer_size_tier_cached(
    model_lower: str, tier_map_key: tuple[tuple[str, str], ...]
) -> str:
    best = ""
    best_len = -1
    for prefix, tier in tier_map_key:
        p = prefix.lower()
        if model_lower.startswith(p) and len(p) > best_len:
            best = tier
            best_len = len(p)
    return best or "humanoid"


def infer_size_tier(model: str, tier_map: dict[str, str]) -> str:
    model_lower = (model or "").lower()
    return _infer_size_tier_cached(model_lower, _tier_map_key(tier_map))


def resolve_size_tier(model: str, tier_map: dict[str, str]) -> str:
    """Always derive from current size_map; ignore stale cached template/slot tags."""
    return infer_size_tier(model, tier_map)


def needs_summon(model: str, prefixes: list[str]) -> bool:
    model = (model or "").lower()
    return any(model.startswith(p.lower()) for p in prefixes)


def size_tier_rank(tier: str) -> int:
    return size_tier_rank_map().get(tier, SIZE_TIER_RANK.get(tier, 1))


def is_excluded_size_tier(tier: str, excluded: set[str]) -> bool:
    return tier in excluded


def should_skip_excluded_slot_tier(slot_tier: str, excluded: set[str]) -> bool:
    return bool(excluded and is_excluded_size_tier(slot_tier, excluded))


def should_skip_zone_restricted_slot(
    slot_tier: str, map_id: str, categories_cfg: dict[str, Any]
) -> bool:
    """体型辅助层不跳过槽位；仅超大档原位（见 exclude_slot_size_tiers）。"""
    del slot_tier, map_id, categories_cfg
    return False


def should_skip_medium_dungeon_slot(slot_tier: str, map_id: str) -> bool:
    """Deprecated — use should_skip_zone_restricted_slot with categories_cfg."""
    del slot_tier, map_id
    return False


def should_skip_large_slot(
    slot_model: str, slot_tier: str, excluded: set[str], categories_cfg: dict[str, Any]
) -> bool:
    """Deprecated alias — use should_skip_excluded_slot_tier."""
    del slot_model, categories_cfg
    return should_skip_excluded_slot_tier(slot_tier, excluded)


def _prefixes_key(prefixes: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    return tuple(str(p).lower() for p in prefixes)


@lru_cache(maxsize=65536)
def _model_has_prefix_cached(model_lower: str, prefixes_key: tuple[str, ...]) -> bool:
    return any(model_lower.startswith(p) for p in prefixes_key)


def _model_has_prefix(model: str, prefixes: list[str]) -> bool:
    return _model_has_prefix_cached((model or "").lower(), _prefixes_key(prefixes))


def passive_animal_model_prefixes(categories_cfg: dict[str, Any]) -> list[str]:
    """不主动攻击的动物模型前缀；兼容旧键 wildlife_model_prefixes。"""
    return (
        categories_cfg.get("passive_animal_model_prefixes")
        or categories_cfg.get("wildlife_model_prefixes")
        or []
    )


def is_passive_animal_model(model: str, categories_cfg: dict[str, Any]) -> bool:
    return _model_has_prefix(model, passive_animal_model_prefixes(categories_cfg))


def is_trash_donor_model(model: str, categories_cfg: dict[str, Any]) -> bool:
    """路边小怪捐皮：模型须落在 archetype 表（见 enemy_archetypes.json）。"""
    from enemy_randomizer_core import get_archetype_index

    return get_archetype_index(categories_cfg).is_trash_donor_model(model)


def is_dlc_trash_donor_model(model: str, categories_cfg: dict[str, Any]) -> bool:
    """DLC 幽影之地普通小怪（非 Boss）；仅 mixed/separate+DLC图 时作 trash 捐皮。"""
    return _model_has_prefix(
        model, categories_cfg.get("dlc_trash_donor_model_prefixes") or []
    )


def dlc_trash_enabled_for_slot(
    dlc_pool_mode: str,
    map_id: str,
    categories_cfg: dict[str, Any],
) -> bool:
    """mixed 固定语义：随机怪物不分地图（2026-07-29 口径）；separate 已废止。"""
    del dlc_pool_mode, map_id, categories_cfg
    return True


def is_eligible_trash_donor_model(
    model: str,
    categories_cfg: dict[str, Any],
    *,
    dlc_trash_enabled: bool = False,
) -> bool:
    del dlc_trash_enabled
    if is_never_donor_model(model, categories_cfg):
        return False
    if is_passive_animal_model(model, categories_cfg):
        return False
    return is_trash_donor_model(model, categories_cfg)


def field_cavalry_rider_prefixes(categories_cfg: dict[str, Any]) -> list[str]:
    raw = (
        categories_cfg.get("field_cavalry_rider_model_prefixes")
        or categories_cfg.get("night_rider_model_prefixes")
        or []
    )
    return list(raw)


def field_cavalry_mount_prefixes(categories_cfg: dict[str, Any]) -> list[str]:
    raw = (
        categories_cfg.get("field_cavalry_mount_model_prefixes")
        or categories_cfg.get("night_mount_model_prefixes")
        or []
    )
    return list(raw)


def is_field_cavalry_rider_model(model: str, categories_cfg: dict[str, Any]) -> bool:
    return _model_has_prefix(model, field_cavalry_rider_prefixes(categories_cfg))


def is_field_cavalry_mount_model(model: str, categories_cfg: dict[str, Any]) -> bool:
    return _model_has_prefix(model, field_cavalry_mount_prefixes(categories_cfg))


def is_night_rider_model(model: str, categories_cfg: dict[str, Any]) -> bool:
    return is_field_cavalry_rider_model(model, categories_cfg)


def is_night_mount_model(model: str, categories_cfg: dict[str, Any]) -> bool:
    return is_field_cavalry_mount_model(model, categories_cfg)



def is_cnv_named_boss_donor_template(
    tpl: dict[str, Any],
    categories_cfg: dict[str, Any],
    *,
    csv_dir: str | Path | None = None,
) -> bool:
    """7 池可捐皮：绑定表 · ``[Boss]`` / ``[地名]`` 标记 · 合成 donor_origin=cnv。"""
    base = Path(csv_dir) if csv_dir else (GAME_DIR / "csv")
    if template_is_cnv_pool7_marked_npc(tpl, base):
        return True
    model = str(tpl.get("model", "")).lower()
    if is_force_trash_model(model, categories_cfg):
        return False
    bindings = [
        b
        for b in (categories_cfg.get("cnv_named_boss_bindings") or [])
        if str(b.get("model", "")).lower() == model
        and normalize_category_id(str(b.get("category") or "major_boss")) == "major_boss"
    ]
    if not bindings:
        return False
    tags = tpl.get("template_tags") or {}
    if tags.get("synthetic_boss") and str(tags.get("donor_origin") or "") == "cnv":
        return True
    try:
        npc = int(tpl.get("npc", 0))
    except (TypeError, ValueError):
        return False
    return any(int(b.get("npc", 0)) == npc for b in bindings)


def refine_cnv_special_template_categories(
    templates: list[dict[str, Any]],
    categories_cfg: dict[str, Any],
    *,
    csv_dir: Path,
) -> None:
    """踢出共享皮小怪（如 c4380 矿工）：非绑定条目不保留 major_boss/cnv_special。"""
    world = frozenset({"c8100", "c8101", "c8110"})
    rules_all = categories_cfg.get("src_cat_rules") or []
    rules_no_cnv = [
        r
        for r in rules_all
        if normalize_category_id(str(r.get("category"))) != "major_boss"
    ]
    default = categories_cfg.get("template_default_category", "trash")
    for tpl in templates:
        cat = normalize_category_id(str(tpl.get("category") or ""))
        if cat not in ("cnv_special", "major_boss"):
            continue
        model = str(tpl.get("model", "")).lower()
        if model in world:
            continue
        if is_cnv_named_boss_donor_template(tpl, categories_cfg):
            continue
        rules_cat = infer_category(model, rules_no_cnv, default)
        tpl["category"] = resolve_entity_category(
            tpl,
            categories_cfg=categories_cfg,
            csv_dir=csv_dir,
            rules_category=rules_cat,
        )


def refine_cnv_new_npc_red_spirit_categories(
    templates: list[dict[str, Any]],
    *,
    csv_dir: str | Path,
) -> None:
    """法魂 Changelog ``New NPC #`` → 5 池 night（含 c1000 等非红灵皮）。"""
    for tpl in templates:
        if template_is_cnv_new_npc_red_spirit(tpl, csv_dir):
            tpl["category"] = "night"


def refine_cnv_new_npc_red_spirit_slots(
    slots: list[dict[str, Any]],
    *,
    csv_dir: str | Path,
) -> None:
    for slot in slots:
        if not template_is_cnv_new_npc_red_spirit(slot, csv_dir):
            continue
        slot["src_cat"] = "night"
        tags = dict(slot.get("slot_tags") or {})
        tags["src_cat"] = "night"
        slot["slot_tags"] = tags


def _cnv_named_boss_binding_category_map(
    categories_cfg: dict[str, Any],
) -> dict[tuple[str, int], str]:
    out: dict[tuple[str, int], str] = {}
    for b in categories_cfg.get("cnv_named_boss_bindings") or []:
        model = str(b.get("model") or "").lower()
        try:
            npc = int(b.get("npc", 0))
        except (TypeError, ValueError):
            continue
        if model and npc > 0:
            out[(model, npc)] = normalize_category_id(
                str(b.get("category") or "major_boss")
            )
    return out


def promote_cnv_named_boss_template_categories(
    templates: list[dict[str, Any]],
    categories_cfg: dict[str, Any],
) -> None:
    """绑定表 model+npc → 指定池（默认 7 池 major_boss）。"""
    keys = _cnv_named_boss_binding_category_map(categories_cfg)
    for tpl in templates:
        model = str(tpl.get("model", "")).lower()
        try:
            npc = int(tpl.get("npc", 0))
        except (TypeError, ValueError):
            continue
        cat = keys.get((model, npc))
        if cat:
            tpl["category"] = cat


def promote_cnv_named_boss_slots(
    slots: list[dict[str, Any]],
    categories_cfg: dict[str, Any],
) -> None:
    keys = _cnv_named_boss_binding_category_map(categories_cfg)
    for slot in slots:
        model = str(slot.get("model", "")).lower()
        try:
            npc = int(slot.get("npc", 0))
        except (TypeError, ValueError):
            continue
        cat = keys.get((model, npc))
        if not cat:
            continue
        slot["src_cat"] = cat
        tags = dict(slot.get("slot_tags") or {})
        tags["src_cat"] = cat
        slot["slot_tags"] = tags


def refine_cnv_boss_tag_template_categories(
    templates: list[dict[str, Any]],
    *,
    csv_dir: str | Path,
) -> None:
    """NpcParam ``[Boss]`` / ``[地名]`` → 7 池 major_boss。"""
    for tpl in templates:
        if template_is_cnv_pool7_marked_npc(tpl, csv_dir):
            tpl["category"] = "major_boss"


def refine_cnv_boss_tag_slots(
    slots: list[dict[str, Any]],
    *,
    csv_dir: str | Path,
) -> None:
    for slot in slots:
        if not template_is_cnv_pool7_marked_npc(slot, csv_dir):
            continue
        slot["src_cat"] = "major_boss"
        tags = dict(slot.get("slot_tags") or {})
        tags["src_cat"] = "major_boss"
        slot["slot_tags"] = tags



# 兼容旧名（函数体已迁至 enemy_pool_filters；此处早于文末 facade re-export）
from enemy_pool_filters import (  # noqa: E402
    filter_pool_for_major_boss_named_targets as filter_pool_for_cnv_special_targets,
)



def red_spirit_model_label(model: str, categories_cfg: dict[str, Any]) -> str:
    zh = (categories_cfg.get("model_prefix_display_zh") or {}).get(
        (model or "").lower()
    )
    return str(zh or model or "")


def night_model_label(model: str, categories_cfg: dict[str, Any]) -> str:
    return red_spirit_model_label(model, categories_cfg)
def is_humanoid_slot_blocked_boss_donor(model: str, categories_cfg: dict[str, Any]) -> bool:
    """人形槽换大体型/特殊 Boss 会缺材质或武器错位。"""
    return _model_has_prefix(
        model, categories_cfg.get("humanoid_slot_exclude_boss_donor_prefixes") or []
    )


def is_humanoid_slot_blocked_donor(model: str, categories_cfg: dict[str, Any]) -> bool:
    """仅 humanoid 体型槽禁捐皮（性能/巨模）。"""
    return _model_has_prefix(
        model, categories_cfg.get("humanoid_slot_exclude_donor_prefixes") or []
    )


def is_humanoid_slot_allowed_donor(model: str, categories_cfg: dict[str, Any]) -> bool:
    """祖灵等白名单：人形槽可贴（绕开 compact Boss 捐皮额外限制）。"""
    return _model_has_prefix(
        model, categories_cfg.get("humanoid_slot_allow_donor_prefixes") or []
    )


def is_hub_map_slot(map_id: str, categories_cfg: dict[str, Any]) -> bool:
    """安全区地图（大赐福等）：槽位不参与随机。"""
    mid = str(map_id)
    exact = categories_cfg.get("hub_map_ids") or []
    if mid in exact:
        return True
    prefixes = categories_cfg.get("hub_map_id_prefixes") or []
    return any(mid.startswith(p) for p in prefixes)


def is_pristine_map_slot(map_id: str, categories_cfg: dict[str, Any]) -> bool:
    """整张图保持原版 MSB（游荡灵庙共享层等）。"""
    mid = str(map_id)
    exact = categories_cfg.get("pristine_map_ids") or []
    return mid in {str(x) for x in exact}


def is_non_participating_map(map_id: str, categories_cfg: dict[str, Any]) -> bool:
    return is_hub_map_slot(map_id, categories_cfg) or is_pristine_map_slot(
        map_id, categories_cfg
    )


def restore_hub_map_overlays(categories_cfg: dict[str, Any]) -> list[str]:
    """删除 mod 叠加层里须保持原版的 MSB（安全区 + pristine 图）。"""
    overlay_dir = GAME_DIR / "mod" / "cnv_enemy" / "map" / "MapStudio"
    if not overlay_dir.is_dir():
        return []
    restored: list[str] = []
    for path in sorted(overlay_dir.glob("*.msb.dcx")):
        map_id = path.name[: -len(".msb.dcx")]
        if not (
            is_hub_map_slot(map_id, categories_cfg)
            or is_pristine_map_slot(map_id, categories_cfg)
        ):
            continue
        path.unlink(missing_ok=True)
        msbe = path.with_name(path.name.replace(".msb.dcx", ".msbe.dcx"))
        msbe.unlink(missing_ok=True)
        slot_log = overlay_dir / f"cnv_enemy_apply_slots_{map_id}.txt"
        slot_log.unlink(missing_ok=True)
        restored.append(map_id)
    return restored


def is_excluded_slot_model(
    model: str,
    categories_cfg: dict[str, Any],
    slot: dict[str, Any] | None = None,
    npc_csv_dir: str | Path | None = None,
) -> bool:
    if not _model_has_prefix(model, categories_cfg.get("exclude_slot_model_prefixes") or []):
        return False
    if slot is not None:
        base = Path(npc_csv_dir) if npc_csv_dir else (GAME_DIR / "csv")
        if is_red_spirit_combat_slot(slot, base, categories_cfg):
            return False
    return True


def is_siege_mount_rider_slot(
    slot: dict[str, Any],
    categories_cfg: dict[str, Any] | None = None,
) -> bool:
    """MSB Events.Mounts 骑手：MountPartName 为 c81xx 攻城武器（index-export 写入）。"""
    if slot.get("siege_mount_rider"):
        return True
    tags = slot.get("slot_tags") or {}
    return bool(tags.get("siege_mount_rider"))


def is_siege_c1000_operator_slot(
    slot: dict[str, Any],
    categories_cfg: dict[str, Any],
) -> bool:
    """c1000 操作员皮：think=1 + talk/npc 成对（弩炮 1000/10000000，投石 2000/10001000）。"""
    model = str(slot.get("model", "")).lower()
    if not model.startswith("c1000"):
        return False
    src_cat = str(
        slot.get("src_cat") or (slot.get("slot_tags") or {}).get("src_cat") or ""
    )
    if src_cat != "trash":
        return False
    try:
        think = int(slot.get("think", 0))
        talk = int(slot.get("talk_id") or slot.get("talkId") or 0)
        npc = int(slot.get("npc", 0))
    except (TypeError, ValueError):
        return False
    siege_think = int(categories_cfg.get("siege_operator_think_id", 1) or 1)
    if think != siege_think:
        return False
    profiles = categories_cfg.get("siege_operator_c1000_profiles") or [
        {"talk_id": 1000, "npc_id": 10_000_000},
        {"talk_id": 2000, "npc_id": 10_001_000},
    ]
    for profile in profiles:
        try:
            want_talk = int(profile.get("talk_id", 0))
            want_npc = int(profile.get("npc_id", 0))
        except (TypeError, ValueError):
            continue
        if talk == want_talk and npc == want_npc:
            return True
    return False


def is_siege_operator_slot(
    slot: dict[str, Any],
    categories_cfg: dict[str, Any],
) -> bool:
    """攻城操作员：MSB Mount 骑手（主）或 c1000+专用 talk_id（辅）。

    废止宽 npc 段猜测；c1000 已由 exclude_slot_model_prefixes 双保险跳过。
    """
    if is_siege_mount_rider_slot(slot, categories_cfg):
        return True
    return is_siege_c1000_operator_slot(slot, categories_cfg)


def is_keep_original_slot_model(model: str, categories_cfg: dict[str, Any]) -> bool:
    """圣甲虫等：槽位保持原位、不参与随机。"""
    return _model_has_prefix(
        model, categories_cfg.get("keep_original_slot_model_prefixes") or []
    )


def is_keep_original_map_entity_slot(
    slot: dict[str, Any],
    categories_cfg: dict[str, Any],
) -> bool:
    """单图+实体名原位（祭典助战等）；早于红灵豁免，挡住误进 5 池。"""
    map_id = str(slot.get("map_id") or "")
    entity = str(slot.get("name") or slot.get("entity_name") or "")
    if not map_id or not entity:
        return False
    want = (map_id.lower(), entity.lower())
    for row in categories_cfg.get("keep_original_map_entity_slots") or []:
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            continue
        if (str(row[0]).lower(), str(row[1]).lower()) == want:
            return True
    return False


def is_caravan_event_slot(
    slot: dict[str, Any],
    categories_cfg: dict[str, Any],
) -> bool:
    """巨人拉车过场：事件层 MSB 上领队假人/拉车巨人槽保持原位（小兵走密集）。"""
    map_id = str(slot.get("map_id") or "")
    event_maps = {
        str(x) for x in (categories_cfg.get("cnv_caravan_event_maps") or [])
    }
    if map_id not in event_maps:
        return False
    entity = str(slot.get("name") or slot.get("entity_name") or "").lower()
    model = str(slot.get("model") or "").lower()
    prefixes = [
        str(p).lower()
        for p in (
            categories_cfg.get("cnv_caravan_event_slot_model_prefixes")
            or ["c0110", "c0100", "c4600"]
        )
    ]
    if any(model.startswith(p) for p in prefixes):
        return True
    return any(f"-{p}_" in entity for p in prefixes)


def donor_blocked_for_anchor_plant_slot(
    slot_model: str,
    donor_model: str,
    categories_cfg: dict[str, Any],
) -> bool:
    """米兰达芽等植物锚点槽：仅植物族捐皮（防人形 T 字架）。"""
    slot_m = str(slot_model or "").lower()
    donor_m = str(donor_model or "").lower()
    slot_prefixes = categories_cfg.get("anchor_plant_slot_model_prefixes") or []
    if not _model_has_prefix(slot_m, slot_prefixes):
        return False
    allow = categories_cfg.get("anchor_plant_donor_model_prefixes") or []
    return not _model_has_prefix(donor_m, allow)


def is_never_donor_npc_id(
    tpl: dict[str, Any],
    categories_cfg: dict[str, Any],
) -> bool:
    """categories never_donor_npc_ids：按 NpcParam 精确禁捐（亚兹勒等）。"""
    try:
        npc = int(tpl.get("npc", 0))
    except (TypeError, ValueError):
        return False
    if npc <= 0:
        return False
    blocked = categories_cfg.get("never_donor_npc_ids") or []
    return npc in {int(x) for x in blocked}


def resolve_donor_npc_id(npc: int, categories_cfg: dict[str, Any]) -> int:
    """Quest/cutscene shells → combat rows (e.g. Dung Eater 523230033→523230035)."""
    try:
        npc_i = int(npc)
    except (TypeError, ValueError):
        return 0
    if npc_i <= 0:
        return 0
    remap = categories_cfg.get("donor_npc_id_remap") or {}
    if not isinstance(remap, dict):
        return npc_i
    target = remap.get(str(npc_i))
    if target is None:
        return npc_i
    try:
        return int(target)
    except (TypeError, ValueError):
        return npc_i


def is_never_donor_model(model: str, categories_cfg: dict[str, Any]) -> bool:
    if is_horse_mount_model(model, categories_cfg):
        return True
    return _model_has_prefix(model, categories_cfg.get("never_donor_model_prefixes") or [])


def is_never_donor_hard_block_model(
    model: str, categories_cfg: dict[str, Any]
) -> bool:
    """never_donor 且审阅白名单不得覆写（结晶/白金蟹 c2274/c2275/c2278 等）。"""
    if not is_never_donor_model(model, categories_cfg):
        return False
    return _model_has_prefix(
        model,
        categories_cfg.get("never_donor_hard_block_model_prefixes") or [],
    )


def is_invisible_enemy_model(model: str, categories_cfg: dict[str, Any]) -> bool:
    return _model_has_prefix(model, categories_cfg.get("invisible_enemy_model_prefixes") or [])


def is_horse_mount_model(model: str, categories_cfg: dict[str, Any]) -> bool:
    return _model_has_prefix(model, categories_cfg.get("horse_mount_model_prefixes") or [])


def is_excluded_slot_npc_id(
    slot: dict[str, Any],
    categories_cfg: dict[str, Any],
) -> bool:
    """categories exclude_slot_npc_ids：无 MSB talk 仍须原位的剧情槽。"""
    try:
        npc = int(slot.get("npc", 0))
    except (TypeError, ValueError):
        return False
    if npc <= 0:
        return False
    blocked = categories_cfg.get("exclude_slot_npc_ids") or []
    return npc in {int(x) for x in blocked}


def is_cnv_original_boss_slot_npc_id(
    slot: dict[str, Any],
    categories_cfg: dict[str, Any],
) -> bool:
    """法魂原创 Boss 原位槽：不参与随机，仍可作 7 池捐皮（见 cnv_original_boss_slot_npc_ids）。"""
    try:
        npc = int(slot.get("npc", 0))
    except (TypeError, ValueError):
        return False
    if npc <= 0:
        return False
    blocked = categories_cfg.get("cnv_original_boss_slot_npc_ids") or []
    return npc in {int(x) for x in blocked}
def quadruped_model_prefixes(categories_cfg: dict[str, Any]) -> list[str]:
    return [
        str(p).lower()
        for p in categories_cfg.get("quadruped_slot_model_prefixes") or []
    ]


def flying_model_prefixes(categories_cfg: dict[str, Any] | None) -> list[str]:
    raw = (categories_cfg or {}).get("flying_slot_model_prefixes") or []
    if raw:
        return [str(p).lower() for p in raw]
    return ["c4200", "c6001"]


def slot_physique_bucket(slot: dict[str, Any], categories_cfg: dict[str, Any]) -> str:
    from enemy_slot_rules import _slot_placement_kind

    model = str(slot.get("model", ""))
    placement = _slot_placement_kind(slot)
    if _model_has_prefix(model, flying_model_prefixes(categories_cfg)):
        return "flying"
    if _model_has_prefix(model, quadruped_model_prefixes(categories_cfg)):
        return "quadruped"
    if placement == "perch_or_squat":
        return "perch"
    return "humanoid"


def donor_physique_bucket(
    tpl: dict[str, Any],
    categories_cfg: dict[str, Any],
    compat_by_tid: dict[str, dict[str, Any]] | None = None,
) -> str:
    from donor_msb_compat import compat_entry_for_template

    model = str(tpl.get("model", ""))
    tags = tpl.get("template_tags") or {}
    tid = str(tpl.get("template_id", ""))
    entry = compat_entry_for_template(tid, compat_by_tid)
    pose = str(entry.get("donor_pose_label") or "").lower()
    if entry.get("force_donor_msb") and any(
        k in pose for k in ("sit", "squat", "backup", "perch")
    ):
        return "perch"
    if tags.get("has_flight_ai") or _model_has_prefix(
        model, flying_model_prefixes(categories_cfg)
    ):
        return "flying"
    if _model_has_prefix(model, quadruped_model_prefixes(categories_cfg)):
        return "quadruped"
    if any(k in pose for k in ("sit", "squat", "backup_700", "perch")):
        return "perch"
    return "humanoid"
def boss_donor_allowed_on_compact_slot(
    model: str,
    donor_tier: str,
    categories_cfg: dict[str, Any],
    *,
    slot_tier: str | None = None,
) -> bool:
    """人形/小型槽：禁飞行/主线 Boss/大型捐皮；6 池见 humanoid_slot_exclude（含火焰巨人 c5270）。"""
    if slot_tier == "humanoid" and is_humanoid_slot_allowed_donor(
        model, categories_cfg
    ):
        if is_never_donor_model(model, categories_cfg):
            return False
        if is_passive_animal_model(model, categories_cfg):
            return False
        return True
    if slot_tier == "humanoid" and is_humanoid_slot_blocked_donor(
        model, categories_cfg
    ):
        return False
    if donor_tier in ("flying", "boss", "large", "colossal"):
        return False
    donor_cat = resolve_src_category(model, categories_cfg)
    if donor_cat == "major_boss":
        return False
    if is_oversize_boss_model(model):
        return False
    if is_humanoid_slot_blocked_boss_donor(model, categories_cfg):
        return False
    if is_never_donor_model(model, categories_cfg):
        return False
    if is_passive_animal_model(model, categories_cfg):
        return False
    return True


def is_boss_pool_excluded_donor_model(
    model: str, categories_cfg: dict[str, Any]
) -> bool:
    prefixes = categories_cfg.get("boss_pool_exclude_donor_prefixes") or []
    model = (model or "").lower()
    return any(model.startswith(str(p).lower()) for p in prefixes)


def is_boss_pool_excluded_donor(
    tpl: dict[str, Any], categories_cfg: dict[str, Any]
) -> bool:
    """2~7 Boss 目标池禁捐皮（模型前缀 + synthetic template_id）。"""
    if is_boss_pool_excluded_donor_model(str(tpl.get("model", "")), categories_cfg):
        return True
    tid = str(tpl.get("template_id", ""))
    excluded = categories_cfg.get("boss_pool_exclude_synthetic_template_ids") or []
    return tid in set(str(x) for x in excluded)


def is_minor_boss_catalog_donor(
    tpl: dict[str, Any], categories_cfg: dict[str, Any]
) -> bool:
    """2 池捐皮白名单：仅具名/洞穴 Boss 皮，排除误归入 minor_boss 的洞窟小怪。"""
    prefixes = categories_cfg.get("minor_boss_donor_model_prefixes")
    if not prefixes:
        return True
    model = str(tpl.get("model", "")).lower()
    return any(model.startswith(str(p).lower()) for p in prefixes)
def resolve_src_category(model: str, categories_cfg: dict[str, Any]) -> str:
    """Always derive from current rules; ignore stale cached index tags."""
    rules = categories_cfg.get("src_cat_rules", [])
    default_cat = categories_cfg.get("template_default_category", "trash")
    return _infer_category_cached(
        (model or "").lower(),
        _src_cat_rules_key(rules),
        str(default_cat),
    )


def is_unsafe_donor_template(
    tpl: dict[str, Any],
    categories_cfg: dict[str, Any],
    *,
    csv_dir: str | Path | None = None,
) -> bool:
    """Skip NPC/scripted templates that crash when pasted into normal enemy slots.

    审阅白名单（``donor_review_allowlist``）显式收录的 npc：可覆盖
    talk_npc / never_donor_model / exclude_donor_model_prefixes（槽位仍由
    ``is_talk_npc_slot`` 跳过，不随机对话 NPC 本体）。
    """
    model = str(tpl.get("model", ""))
    try:
        npc = int(tpl.get("npc", 0))
    except (TypeError, ValueError):
        npc = 0
    allowlisted = bool(
        categories_cfg.get("donor_review_allowlist_enabled", False)
        and is_allowlisted_donor_template(tpl, categories_cfg)
    )
    if is_never_donor_hard_block_model(model, categories_cfg):
        return True
    if is_never_donor_model(model, categories_cfg) and not allowlisted:
        return True
    if is_never_donor_npc_id(tpl, categories_cfg):
        return True
    if is_passive_animal_model(model, categories_cfg) and not allowlisted:
        return True
    base = Path(csv_dir) if csv_dir else (GAME_DIR / "csv")
    if npc > 0 and is_talk_npc_id(npc, base) and not allowlisted:
        return True
    if is_excluded_slot_npc_id(tpl, categories_cfg) and not allowlisted:
        return True
    if categories_cfg.get("donor_review_filter_enabled"):
        from donor_pool_review_filter import is_donor_review_excluded_template

        if is_donor_review_excluded_template(
            tpl, categories_cfg=categories_cfg, csv_dir=base
        ):
            return True
    if not is_allowlisted_donor_template(tpl, categories_cfg):
        return True
    from dlc_donor_pool import is_below_min_donor_effective_hp

    if is_below_min_donor_effective_hp(
        tpl, categories_cfg, csv_dir=base
    ):
        return True
    for prefix in categories_cfg.get("exclude_donor_model_prefixes") or []:
        if model.lower().startswith(str(prefix).lower()) and not allowlisted:
            return True
    donor_cat = str(tpl.get("category") or "") or resolve_src_category(
        model, categories_cfg
    )
    from enemy_randomizer_core import BOSS_SOURCE_CATEGORIES

    boss_like = donor_cat in BOSS_SOURCE_CATEGORIES or donor_cat == "night"
    if not boss_like:
        think_min = categories_cfg.get("exclude_donor_think_min")
        if think_min is not None:
            try:
                if int(tpl.get("think", 0)) >= int(think_min):
                    return True
            except (TypeError, ValueError):
                pass
        npc_eq_below = categories_cfg.get("exclude_donor_npc_equals_think_below")
        if npc_eq_below is not None:
            try:
                npc = int(tpl.get("npc", 0))
                think = int(tpl.get("think", 0))
                if npc == think and 0 < npc < int(npc_eq_below):
                    return True
            except (TypeError, ValueError):
                pass
    return False


def is_risky_assignment(row: dict[str, Any], categories_cfg: dict[str, Any]) -> str | None:
    """Return a short risk tag for debug reports, or None if clean."""
    from enemy_mount_pairs import CNV_SUPPRESS_MOUNT_TEMPLATE

    if str(row.get("template_id", "")) == CNV_SUPPRESS_MOUNT_TEMPLATE:
        return None
    model = str(row.get("model", ""))
    if is_never_donor_model(model, categories_cfg):
        return "world_entity_donor"
    if is_invisible_enemy_model(model, categories_cfg):
        return "invisible_enemy_donor"
    if is_passive_animal_model(model, categories_cfg):
        return "passive_animal_donor"
    if is_excluded_slot_model(model, categories_cfg):
        return "npc_donor_model"
    donor_cat = resolve_src_category(model, categories_cfg)
    tgt_cat = str(row.get("tgt_cat", "trash"))
    if tgt_cat == "trash" and donor_cat != "trash":
        return f"non_trash_donor_{donor_cat}"
    try:
        npc = int(row.get("npc", 0))
        think = int(row.get("think", 0))
    except (TypeError, ValueError):
        npc = think = 0
    if npc == think and 0 < npc < int(categories_cfg.get("exclude_donor_npc_equals_think_below", 0) or 0):
        return "npc_equals_think"
    think_min = categories_cfg.get("exclude_donor_think_min")
    if think_min is not None and think >= int(think_min):
        return "high_think"
    return None


def template_donor_map_id(tpl: dict[str, Any]) -> str:
    tpl_id = str(tpl.get("template_id", ""))
    if ":" in tpl_id:
        return tpl_id.split(":", 1)[0]
    donor_map = str(tpl.get("donor_map", ""))
    if donor_map:
        return donor_map.replace(".msb.dcx", "").replace(".msb", "")
    return ""


def template_is_dlc_boss_donor(
    tpl: dict[str, Any], categories_cfg: dict[str, Any]
) -> bool:
    """DLC Boss 捐皮：只看模型/合成表，不用捐皮来源图块（避免小兵因 DLC 图误标）。"""
    tags = tpl.get("template_tags") or {}
    if tags.get("donor_origin") == "dlc":
        return True
    model = str(tpl.get("model", "")).lower()
    for prefix in categories_cfg.get("dlc_boss_model_prefixes") or []:
        if model.startswith(str(prefix).lower()):
            return True
    for rule in categories_cfg.get("donor_origin_by_model_prefix") or []:
        if str(rule.get("origin", "")) != "dlc":
            continue
        prefix = str(rule.get("prefix", "")).lower()
        if prefix and model.startswith(prefix):
            return True
    tpl_id = str(tpl.get("template_id", ""))
    for raw in categories_cfg.get("synthetic_boss_templates") or []:
        if str(raw.get("template_id", "")) == tpl_id and raw.get("donor_origin") == "dlc":
            return True
    return False


def resolve_donor_origin(tpl: dict[str, Any], categories_cfg: dict[str, Any]) -> str:
    """base | dlc | cnv — for separate DLC pool filtering."""
    tags = tpl.get("template_tags") or {}
    tagged = str(tags.get("donor_origin") or "")
    if tagged in ("base", "dlc", "cnv"):
        return tagged
    model = str(tpl.get("model", "")).lower()
    for rule in categories_cfg.get("donor_origin_by_model_prefix") or []:
        prefix = str(rule.get("prefix", "")).lower()
        if prefix and model.startswith(prefix):
            origin = str(rule.get("origin", "base"))
            if origin in ("base", "dlc", "cnv"):
                return origin
    for prefix in categories_cfg.get("dlc_trash_donor_model_prefixes") or []:
        if model.startswith(str(prefix).lower()):
            return "dlc"
    for prefix in categories_cfg.get("cnv_boss_model_prefixes") or []:
        if model.startswith(str(prefix).lower()):
            return "cnv"
    for prefix in categories_cfg.get("dlc_boss_model_prefixes") or []:
        if model.startswith(str(prefix).lower()):
            return "dlc"
    donor_map = template_donor_map_id(tpl)
    if donor_map and donor_map != "synthetic":
        if is_dlc_enemy_map(donor_map, categories_cfg):
            return "dlc"
    return "base"


def is_dlc_enemy_map(map_id: str, categories_cfg: dict[str, Any] | None = None) -> bool:
    """Shadow 幽影之地：地图块第一格 tile ≥ dlc_map_tile_min（默认 50）。"""
    tile_min = 50
    if categories_cfg:
        tile_min = int(categories_cfg.get("dlc_map_tile_min", 50))
    parts = str(map_id).split("_")
    if len(parts) < 2:
        return False
    try:
        return int(parts[1]) >= tile_min
    except ValueError:
        return False


def filter_pool_by_dlc_mode(
    pool: list[dict[str, Any]],
    *,
    slot_is_dlc: bool,
    dlc_pool_mode: str,
    categories_cfg: dict[str, Any],
) -> list[dict[str, Any]]:
    """全图混池：不按槽位地图过滤 DLC/本体捐皮（2026-07-29 口径；separate 废止）。"""
    del slot_is_dlc, dlc_pool_mode, categories_cfg
    return pool
