"""T-072 / T-073R / T-080 v2 — donor compat cache + slot/donor pairing."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from msb_template_id import normalize_template_id

from paths import SCRIPT_DIR  # frozen-safe (data/cnv_randomizer)
DEFAULT_COMPAT_CACHE = SCRIPT_DIR / "cache" / "donor_slot_compat.json"
DEFAULT_OVERRIDES_PATH = SCRIPT_DIR / "donor_msb_compat_overrides.json"
COMPAT_RULE_VERSION = 2

_OVERRIDES_CACHE: dict[str, dict[str, Any]] | None = None


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


_COMPAT_BY_TID_CACHE: tuple[str, dict[str, dict[str, Any]]] | None = None
# Memo: (path, size, mtime_ns) → "sha16:size" — zip/copy changes mtime but content hash stays stable in meta.
_FINGERPRINT_CACHE: tuple[
    tuple[str, int, int] | None, tuple[str, int, int] | None, str
] | None = None


def _content_fingerprint(path: Path) -> str:
    """sha256[:16]:size — zip-safe (mtime must not invalidate prep)."""
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as fh:
        while chunk := fh.read(1024 * 1024):
            size += len(chunk)
            digest.update(chunk)
    return f"{digest.hexdigest()[:16]}:{size}"


def compat_cache_fingerprint(
    cache_path: Path | None = None,
    overrides_path: Path | None = None,
) -> str:
    """Prep meta fingerprint: rule_version + content identity（禁 mtime，zip 解压不失效）。"""
    global _FINGERPRINT_CACHE
    cache_path = cache_path or DEFAULT_COMPAT_CACHE
    overrides_path = overrides_path or DEFAULT_OVERRIDES_PATH

    def _memo_key(path: Path) -> tuple[str, int, int] | None:
        if not path.is_file():
            return None
        st = path.stat()
        return (str(path.resolve()), int(st.st_size), int(st.st_mtime_ns))

    c_key = _memo_key(cache_path)
    o_key = _memo_key(overrides_path)
    if (
        _FINGERPRINT_CACHE is not None
        and _FINGERPRINT_CACHE[0] == c_key
        and _FINGERPRINT_CACHE[1] == o_key
    ):
        return _FINGERPRINT_CACHE[2]
    parts: list[str] = [f"rule={COMPAT_RULE_VERSION}"]
    if c_key is not None:
        parts.append(f"cache={_content_fingerprint(cache_path)}")
    else:
        parts.append("cache=missing")
    if o_key is not None:
        parts.append(f"ov={_content_fingerprint(overrides_path)}")
    else:
        parts.append("ov=missing")
    fp = "|".join(parts)
    _FINGERPRINT_CACHE = (c_key, o_key, fp)
    return fp


def load_donor_slot_compat(
    cache_path: Path | None = None,
) -> dict[str, dict[str, Any]]:
    global _COMPAT_BY_TID_CACHE
    path = cache_path or DEFAULT_COMPAT_CACHE
    fp = compat_cache_fingerprint(cache_path=path)
    if _COMPAT_BY_TID_CACHE is not None and _COMPAT_BY_TID_CACHE[0] == fp:
        return _COMPAT_BY_TID_CACHE[1]
    if not path.is_file():
        data: dict[str, dict[str, Any]] = {}
        _COMPAT_BY_TID_CACHE = (fp, data)
        return data
    try:
        raw = _load_json(path)
    except (OSError, json.JSONDecodeError):
        data = {}
        _COMPAT_BY_TID_CACHE = (fp, data)
        return data
    templates = raw.get("templates") or {}
    data = {str(k): dict(v) for k, v in templates.items()}
    _COMPAT_BY_TID_CACHE = (fp, data)
    return data


def load_donor_msb_overrides(
    overrides_path: Path | None = None,
) -> dict[str, dict[str, Any]]:
    global _OVERRIDES_CACHE
    if _OVERRIDES_CACHE is not None:
        return _OVERRIDES_CACHE
    path = overrides_path or DEFAULT_OVERRIDES_PATH
    if not path.is_file():
        _OVERRIDES_CACHE = {}
        return _OVERRIDES_CACHE
    try:
        data = _load_json(path)
        _OVERRIDES_CACHE = {
            str(k): dict(v) for k, v in (data.get("overrides") or {}).items()
        }
    except (OSError, json.JSONDecodeError):
        _OVERRIDES_CACHE = {}
    return _OVERRIDES_CACHE


def slot_msb_apply_class(slot: dict[str, Any]) -> str:
    from _export_slot_initial_state import apply_slot_class

    return apply_slot_class(slot)


def slot_has_walk_route(slot: dict[str, Any]) -> bool:
    return bool(str(slot.get("walk_route") or "").strip())


def _merge_override(entry: dict[str, Any], template_id: str) -> dict[str, Any]:
    tid = normalize_template_id(template_id) or template_id
    patch = load_donor_msb_overrides().get(tid) or load_donor_msb_overrides().get(
        template_id
    )
    if not patch:
        return entry
    out = dict(entry)
    for key in (
        "force_donor_msb",
        "compat_standing_keep",
        "compat_patrol_keep",
        "donor_pose_label",
        "donor_walk_route",
        "note",
    ):
        if key in patch:
            out[key] = patch[key]
    if patch.get("force_donor_msb"):
        out["compat_standing_keep"] = False
        out["compat_patrol_keep"] = False
    return out


def compat_entry_for_template(
    template_id: str,
    compat_by_tid: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    tid = normalize_template_id(template_id) or ""
    cache = compat_by_tid if compat_by_tid is not None else load_donor_slot_compat()
    entry = dict(cache.get(tid) or cache.get(template_id) or {})
    if not entry:
        entry = {
            "force_donor_msb": False,
            "compat_standing_keep": True,
            "compat_patrol_keep": True,
            "donor_pose_label": "",
            "donor_walk_route": "",
            "vanilla_supported_buckets": [],
            "vanilla_scan_model": "",
        }
    return _merge_override(entry, template_id)


def _is_quadruped_scan_model(
    model: str,
    categories_cfg: dict[str, Any] | None,
) -> bool:
    model_l = str(model or "").strip().lower()
    if not model_l or not categories_cfg:
        return False
    from enemy_randomizer_core import _model_has_prefix, quadruped_model_prefixes

    return _model_has_prefix(model_l, quadruped_model_prefixes(categories_cfg))


def _model_prefixes(cfg: dict[str, Any] | None, key: str) -> list[str]:
    if not cfg:
        return []
    return [str(p).lower() for p in cfg.get(key) or []]


def _donor_is_flying_pose(entry: dict[str, Any]) -> bool:
    """飞行捐皮出处：挂靠锚点 / 空中模型，非地面站立。"""
    pose = str(entry.get("donor_pose_label") or "").strip().lower()
    if pose in {"aerial_model"}:
        return True
    if pose.startswith("collision_anchor"):
        return True
    if pose.startswith("aerial"):
        return True
    buckets = [str(b) for b in (entry.get("vanilla_supported_buckets") or [])]
    if "aerial_slot" in buckets and pose not in {"ground_stand", "patrol", "sit", "squat"}:
        return True
    return False


def _is_script_patrol_flyer_slot(
    slot: dict[str, Any],
    categories_cfg: dict[str, Any] | None = None,
) -> bool:
    if int(slot.get("chr_activate", 0) or 0) == 0:
        return False
    if str(slot.get("walk_route") or "").strip():
        return False
    slot_model = str(slot.get("model") or "").strip().lower()
    prefixes = _model_prefixes(categories_cfg, "script_patrol_flyer_model_prefixes")
    if not prefixes:
        prefixes = ["c4200"]
    return bool(
        slot_model and any(slot_model.startswith(p) for p in prefixes)
    )


def _is_flying_scan_model(
    model: str,
    categories_cfg: dict[str, Any] | None,
) -> bool:
    model_l = str(model or "").strip().lower()
    if not model_l:
        return False
    from enemy_randomizer_core import _model_has_prefix, flying_model_prefixes

    return _model_has_prefix(model_l, flying_model_prefixes(categories_cfg))


def _patrol_slot_allows_ground_stand_humanoid(
    slot: dict[str, Any],
    entry: dict[str, Any],
    categories_cfg: dict[str, Any] | None,
) -> bool:
    """T-076 案例 B：从未巡逻的人形捐皮（如侍从）可走捐皮 think + 保留路。"""
    from whitelist_slot_receptor import classify_receptor_bucket

    if classify_receptor_bucket(slot) != "patrol":
        return False
    supported = list(entry.get("vanilla_supported_buckets") or [])
    if supported != ["ground_stand"]:
        return False
    if entry.get("vanilla_patrol_profiles"):
        return False
    model = str(entry.get("vanilla_scan_model") or "").strip().lower()
    if _is_quadruped_scan_model(model, categories_cfg):
        return False
    return bool(model)


def _patrol_donor_ground_reject(
    slot: dict[str, Any],
    entry: dict[str, Any],
    categories_cfg: dict[str, Any] | None = None,
) -> str | None:
    """T-083：巡逻出处不得进无 walk_route 的地面站立槽（与站立→巡逻对称）。"""
    from whitelist_slot_receptor import classify_receptor_bucket

    if classify_receptor_bucket(slot) != "ground_stand":
        return None
    if str(slot.get("walk_route") or "").strip():
        return None
    if not str(entry.get("donor_walk_route") or "").strip():
        return None
    model = str(entry.get("vanilla_scan_model") or "").strip().lower()
    if _is_quadruped_scan_model(model, categories_cfg):
        return None
    return "patrol_donor_ground_requires_slot_route"


def _shade_boss_line_route_reject(
    slot: dict[str, Any],
    entry: dict[str, Any],
) -> str | None:
    """T-083g：墓地影子 c5513 Boss 线不得进无 walk_route 的地面/挂靠槽。"""
    from donor_vanilla_states import shade_boss_line
    from whitelist_slot_receptor import classify_receptor_bucket

    bucket = classify_receptor_bucket(slot)
    if bucket not in {"ground_stand", "collision_perch"}:
        return None
    if str(slot.get("walk_route") or "").strip():
        return None
    model = str(entry.get("vanilla_scan_model") or "").strip().lower()
    if model != "c5513":
        return None
    try:
        donor_npc = int(entry.get("donor_npc") or 0)
        donor_think = int(entry.get("donor_think") or 0)
    except (TypeError, ValueError):
        donor_npc, donor_think = 0, 0
    if shade_boss_line(donor_npc, donor_think):
        return "shade_boss_line_requires_route"
    return None


def _chariot_boss_line_route_reject(
    slot: dict[str, Any],
    entry: dict[str, Any],
) -> str | None:
    """T-083c：火焰战车 446078xx Boss 线不得进无 walk_route 的地面/挂靠槽。"""
    from donor_vanilla_states import chariot_boss_line
    from whitelist_slot_receptor import classify_receptor_bucket

    bucket = classify_receptor_bucket(slot)
    if bucket not in {"ground_stand", "collision_perch"}:
        return None
    if str(slot.get("walk_route") or "").strip():
        return None
    model = str(entry.get("vanilla_scan_model") or "").strip().lower()
    if model != "c4460":
        return None
    try:
        donor_npc = int(entry.get("donor_npc") or 0)
        donor_think = int(entry.get("donor_think") or 0)
    except (TypeError, ValueError):
        donor_npc, donor_think = 0, 0
    if chariot_boss_line(donor_npc, donor_think):
        return "chariot_boss_line_requires_route"
    return None


def _sit_slot_incompatible_donor_reject(
    slot: dict[str, Any],
    entry: dict[str, Any],
) -> str | None:
    """T-083：坐/蹲槽须 sit 出处捐皮，避免 backup_anim 与皮错位冻住。"""
    from whitelist_slot_receptor import classify_receptor_bucket

    if classify_receptor_bucket(slot) != "sit_squat":
        return None
    pose = str(entry.get("donor_pose_label") or "").strip().lower()
    if pose.startswith("sit_squat") or pose in {"perch_or_squat", "sit", "squat"}:
        return None
    return "sit_slot_requires_sit_donor"


def _sit_slot_oversized_donor_reject(
    slot: dict[str, Any],
    entry: dict[str, Any],
    categories_cfg: dict[str, Any] | None = None,
) -> str | None:
    """T-083f：坐/蹲槽禁超大四足（如 c4550 大狗），避免碰撞卡墙。"""
    from whitelist_slot_receptor import classify_receptor_bucket

    if classify_receptor_bucket(slot) != "sit_squat":
        return None
    model = str(entry.get("vanilla_scan_model") or "").strip().lower()
    if not model:
        return None
    blocked = _model_prefixes(categories_cfg, "sit_slot_oversized_donor_model_prefixes")
    if any(model.startswith(p) for p in blocked):
        return "sit_slot_oversized_donor"
    return None


# T-087：已删死代码 `_script_patrol_flyer_donor_reject` /
# `_standing_donor_patrol_reject` / `_collision_script_slot_allows_standing_swap`
# （主闸 `donor_slot_compat_reject_reason` 早就不调用；配对只认历史状态）。


def _script_force_donor_reject(
    slot: dict[str, Any],
    entry: dict[str, Any],
    categories_cfg: dict[str, Any] | None = None,
) -> str | None:
    """T-086：配对阶段不再因缺 force_donor 拒皮（写出侧 apply 自动开 force）。"""
    del slot, entry, categories_cfg
    return None


def _reject_reason_v1_legacy(
    slot: dict[str, Any],
    entry: dict[str, Any],
    categories_cfg: dict[str, Any] | None = None,
) -> str | None:
    """Cache 缺 vanilla_supported_buckets 时的窄回退：T-086 配对不再卡 force。"""
    del slot, entry, categories_cfg
    return None


def donor_slot_compat_reject_reason(
    slot: dict[str, Any],
    template_id: str,
    compat_by_tid: dict[str, dict[str, Any]] | None = None,
    categories_cfg: dict[str, Any] | None = None,
) -> str | None:
    """T-085/T-086/T-087: pairing reject = historical buckets (+ sit oversized). None if allowed.
    飞巡「必须飞行皮」叠层已废（T-087）；飞行皮软排前已废（T-088）。"""
    if not str(template_id or "").strip():
        return None

    entry = compat_entry_for_template(template_id, compat_by_tid)
    supported = entry.get("vanilla_supported_buckets")
    if supported is not None:
        from whitelist_slot_receptor import classify_receptor_bucket

        bucket = classify_receptor_bucket(slot)
        if not supported:
            return "vanilla_no_occurrence"
        if bucket not in supported:
            if not _patrol_slot_allows_ground_stand_humanoid(
                slot, entry, categories_cfg
            ):
                return "vanilla_state_unsupported"
        # 体型闸（坐蹲禁超大四足）— 非类目拒配对
        if bucket == "sit_squat":
            oversized = _sit_slot_oversized_donor_reject(slot, entry, categories_cfg)
            if oversized:
                return oversized
        return None

    return _reject_reason_v1_legacy(slot, entry, categories_cfg)


def donor_allowed_for_slot(
    slot: dict[str, Any],
    template_id: str,
    compat_by_tid: dict[str, dict[str, Any]] | None = None,
    receptor_index: dict[str, dict[str, Any]] | None = None,
    categories_cfg: dict[str, Any] | None = None,
) -> bool:
    """T-080 pick/apply: reject donor skins without matching slot state."""
    tid = str(template_id or "").strip()
    if receptor_index and tid in receptor_index:
        from whitelist_slot_receptor import classify_receptor_bucket, receptor_fast_reject

        bucket = classify_receptor_bucket(slot)
        if receptor_fast_reject(receptor_index[tid], bucket):
            return False
    return donor_slot_compat_reject_reason(
        slot, template_id, compat_by_tid, categories_cfg=categories_cfg
    ) is None


def filter_prep_donor_indices_for_msb_compat(
    prep: dict[str, Any],
    indices: list[int],
    slot: dict[str, Any],
    compat_by_tid: dict[str, dict[str, Any]] | None = None,
    receptor_index: dict[str, dict[str, Any]] | None = None,
    categories_cfg: dict[str, Any] | None = None,
) -> list[int]:
    """Pick-time T-080 re-check (covers stale prep pools)."""
    if not indices:
        return indices
    cache = compat_by_tid if compat_by_tid is not None else load_donor_slot_compat()
    donors = prep.get("donors") or []
    out: list[int] = []
    from enemy_randomizer_core import is_never_donor_model, is_never_donor_npc_id

    for i in indices:
        if i < 0 or i >= len(donors):
            continue
        tpl = donors[i]
        if categories_cfg:
            if is_never_donor_model(str(tpl.get("model") or ""), categories_cfg):
                continue
            if is_never_donor_npc_id(tpl, categories_cfg):
                continue
        tid = str(tpl.get("template_id", ""))
        if donor_allowed_for_slot(
            slot, tid, cache, receptor_index, categories_cfg=categories_cfg
        ):
            out.append(i)
    return out


def filter_pool_for_donor_msb_compat(
    pool: list[dict[str, Any]],
    slot: dict[str, Any],
    compat_by_tid: dict[str, dict[str, Any]] | None = None,
    receptor_index: dict[str, dict[str, Any]] | None = None,
    categories_cfg: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if not pool:
        return pool
    cache = compat_by_tid if compat_by_tid is not None else load_donor_slot_compat()
    if not cache and not load_donor_msb_overrides() and not receptor_index:
        return pool
    return [
        tpl
        for tpl in pool
        if donor_allowed_for_slot(
            slot,
            str(tpl.get("template_id", "")),
            cache,
            receptor_index,
            categories_cfg=categories_cfg,
        )
    ]


def attach_donor_msb_tags(
    donor_rec: dict[str, Any],
    compat_by_tid: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    tid = str(donor_rec.get("template_id", ""))
    entry = compat_entry_for_template(tid, compat_by_tid)
    if entry:
        donor_rec["donor_msb_tags"] = {
            "force_donor_msb": bool(entry.get("force_donor_msb")),
            "compat_standing_keep": bool(entry.get("compat_standing_keep", True)),
            "compat_patrol_keep": bool(entry.get("compat_patrol_keep", True)),
            "donor_pose_label": entry.get("donor_pose_label"),
        }
    return donor_rec
