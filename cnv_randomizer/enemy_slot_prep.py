"""T-043 — slot prep cache: pre-filtered donor pools per map slot (seed-independent)."""

from __future__ import annotations

import hashlib
import gzip
import json
import os
import pickle
import shutil
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from paths import SCRIPT_DIR

DEFAULT_SLOT_PREP_PATH = SCRIPT_DIR / "cache" / "enemy_slot_prep.json"
DEFAULT_SLOT_PREP_GZ_PATH = DEFAULT_SLOT_PREP_PATH.with_name(
    DEFAULT_SLOT_PREP_PATH.name + ".gz"
)
DEFAULT_SLOT_PREP_META_PATH = DEFAULT_SLOT_PREP_PATH.with_name(
    "enemy_slot_prep.meta.json"
)
DEFAULT_INDEX_PATH = SCRIPT_DIR / "cache" / "enemy_index.json"
DEFAULT_CATEGORIES_PATH = SCRIPT_DIR / "enemy_categories.json"
DEFAULT_ARCHETYPES_PATH = SCRIPT_DIR / "enemy_archetypes.json"
DEFAULT_MANUAL_EXCLUDES_PATH = (
    SCRIPT_DIR / "donor_pool_review_manual_excludes.json"
)
DEFAULT_ALLOWLIST_PATH = (
    SCRIPT_DIR / "donor_pool_review_allowlist.json"
)
from donor_pool_review_allowlist import normalize_category_id


def migrate_legacy_prep_row(row: dict[str, Any]) -> None:
    """旧 prep：field_boss 池并入 evergaol；源类别 id 同步归一。"""
    s = str(row.get("s") or "")
    normed = normalize_category_id(s)
    if normed != s:
        row["s"] = normed
    pools = row.get("o")
    if not isinstance(pools, dict) or "field_boss" not in pools:
        return
    fb_ids = list(pools.pop("field_boss") or [])
    eg_ids = list(pools.get("evergaol") or [])
    seen = set(eg_ids)
    for i in fb_ids:
        if i not in seen:
            eg_ids.append(i)
            seen.add(i)
    if eg_ids:
        pools["evergaol"] = eg_ids


PREP_VERSION = 66  # 红狮子祭典助战 map+entity 原位；2026-09-17


def prep_row_has_pools(row: dict[str, Any]) -> bool:
    """True when row['o'] has at least one non-empty tgt_cat donor id list."""
    pools = row.get("o")
    if not isinstance(pools, dict) or not pools:
        return False
    return any(isinstance(ids, list) and ids for ids in pools.values())
# categories 全文件不入指纹（hub/talk 跳过仍走 runtime）；compat 子集入指纹见 _categories_compat_fingerprint
PREP_META_KEYS = (
    "index",
    "archetypes",
    "dlc_pool_mode",
    "categories_compat",
    "donor_review_excludes",
    "donor_review_allowlist",
    "bundle_catalog",
    "slot_tags",
    "bundle_slot_compat",
    "donor_msb_compat",
)
_WORKER_CTX: dict[str, Any] | None = None


def _core():
    import enemy_randomizer_core as core

    return core


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _file_fingerprint(path: Path) -> str:
    if not path.is_file():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()[:16]


_CATEGORIES_COMPAT_KEYS = (
    "size_tier_by_model_prefix",
    "exclude_slot_size_tiers",
    "exclude_donor_size_tiers",
    "interior_map_id_prefixes",
    "slot_map_kind_overrides",
    "size_tier_placement_aux",
    "hub_map_ids",
    "pristine_map_ids",
    "exclude_slot_npc_ids",
    "humanoid_slot_exclude_boss_donor_prefixes",
    "humanoid_slot_exclude_donor_prefixes",
    "humanoid_slot_allow_donor_prefixes",
    "boss_pool_exclude_donor_prefixes",
    "boss_pool_exclude_synthetic_template_ids",
    "minor_boss_donor_model_prefixes",
    "never_donor_model_prefixes",
    "shared_model_force_trash_unless_synthetic_prefixes",
    "dlc_map_tile_min",
    "horse_mount_model_prefixes",
    "dlc_trash_donor_model_prefixes",
    "red_spirit_model_prefixes",
    "trash_donor_hp_promotion",
    "donor_min_effective_hp",
    "cnv_caravan_event_maps",
    "cnv_caravan_event_slot_model_prefixes",
    "keep_original_map_entity_slots",
)


def _categories_compat_fingerprint(categories_path: Path | None = None) -> str:
    """影响 prep `o` 捐皮池 compat/体型 的 categories 子集；变更须重建 prep。"""
    path = categories_path or DEFAULT_CATEGORIES_PATH
    if not path.is_file():
        return "missing"
    try:
        data = _load_json(path)
    except (OSError, json.JSONDecodeError):
        return "invalid"
    subset = {k: data.get(k) for k in _CATEGORIES_COMPAT_KEYS if k in data}
    blob = json.dumps(subset, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def prep_meta(
    *,
    index_path: Path | None = None,
    categories_path: Path | None = None,
    archetypes_path: Path | None = None,
    dlc_pool_mode: str = "mixed",
) -> dict[str, str]:
    from bundle_cache import bundle_export_fingerprints
    from donor_msb_compat import compat_cache_fingerprint

    bundle_fps = bundle_export_fingerprints()
    # categories 全文件不入指纹：hub/NPC 跳过等仍走 runtime；compat 子集见 categories_compat
    return {
        "index": _file_fingerprint(index_path or DEFAULT_INDEX_PATH),
        "archetypes": _file_fingerprint(archetypes_path or DEFAULT_ARCHETYPES_PATH),
        "dlc_pool_mode": dlc_pool_mode,
        "categories_compat": _categories_compat_fingerprint(categories_path),
        "donor_review_excludes": _file_fingerprint(DEFAULT_MANUAL_EXCLUDES_PATH),
        "donor_review_allowlist": _file_fingerprint(DEFAULT_ALLOWLIST_PATH),
        "bundle_catalog": bundle_fps["bundle_catalog"],
        "slot_tags": bundle_fps["slot_tags"],
        "bundle_slot_compat": bundle_fps["bundle_slot_compat"],
        "donor_msb_compat": compat_cache_fingerprint(),
    }


def slot_prep_gz_path(prep_path: Path) -> Path:
    return prep_path.with_name(prep_path.name + ".gz")


def slot_prep_meta_path(prep_path: Path) -> Path:
    return prep_path.with_name("enemy_slot_prep.meta.json")


def read_slot_prep_meta_record(prep_path: Path | None = None) -> dict[str, Any] | None:
    """侧车元数据（入库用，校验不读 280MB 正文）。"""
    path = slot_prep_meta_path(prep_path or DEFAULT_SLOT_PREP_PATH)
    if not path.is_file():
        return None
    try:
        return _load_json(path)
    except (OSError, json.JSONDecodeError):
        return None


def write_slot_prep_sidecars(
    payload: dict[str, Any],
    prep_path: Path,
) -> None:
    meta_record = {
        "version": int(payload.get("version", PREP_VERSION)),
        "meta": {
            k: str((payload.get("meta") or {}).get(k, ""))
            for k in PREP_META_KEYS
        },
        "stats": payload.get("stats") or {},
        "artifact": slot_prep_gz_path(prep_path).name,
    }
    slot_prep_meta_path(prep_path).write_text(
        json.dumps(meta_record, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    gz_path = slot_prep_gz_path(prep_path)
    with prep_path.open("rb") as src, gzip.open(gz_path, "wb", compresslevel=6) as dst:
        shutil.copyfileobj(src, dst)


def slot_prep_pickle_path(prep_path: Path) -> Path:
    return prep_path.with_suffix(".pkl")


def _prep_pickle_key_path(prep_path: Path) -> Path:
    return slot_prep_pickle_path(prep_path).with_suffix(".pkl.key")


def _prep_pickle_fingerprint(meta_record: dict[str, Any]) -> str:
    """Content key for .pkl freshness (not mtime — zip extract touches gz)."""
    version = int(meta_record.get("version", 0))
    meta = meta_record.get("meta") or {}
    blob = json.dumps(
        {"version": version, "meta": meta},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _ensure_prep_pickle_key(
    prep_path: Path, meta_record: dict[str, Any] | None
) -> None:
    if meta_record is None:
        return
    key_path = _prep_pickle_key_path(prep_path)
    try:
        key_path.write_text(
            _prep_pickle_fingerprint(meta_record), encoding="utf-8"
        )
    except OSError:
        pass


def _pickle_sidecar_fresh(
    prep_path: Path, meta_record: dict[str, Any] | None
) -> bool:
    pkl = slot_prep_pickle_path(prep_path)
    if not pkl.is_file():
        return False
    if meta_record is None:
        return False
    want = _prep_pickle_fingerprint(meta_record)
    key_path = _prep_pickle_key_path(prep_path)
    if key_path.is_file():
        try:
            return key_path.read_text(encoding="utf-8").strip() == want
        except OSError:
            return False
    # No .pkl.key yet: trust pkl when meta sidecar exists (fingerprints checked upstream).
    return True


def _write_prep_pickle(
    prep_path: Path,
    data: dict[str, Any],
    *,
    meta_record: dict[str, Any] | None = None,
) -> None:
    pkl = slot_prep_pickle_path(prep_path)
    try:
        with pkl.open("wb") as fh:
            pickle.dump(data, fh, protocol=pickle.HIGHEST_PROTOCOL)
        _ensure_prep_pickle_key(prep_path, meta_record)
    except OSError:
        pass


def _read_prep_payload(
    prep_path: Path,
    *,
    on_progress: Callable[[str, int, int, str], None] | None = None,
) -> dict[str, Any]:
    """Load prep from .pkl sidecar, .json, or .json.gz (no 280MB decompress required)."""
    meta_record = read_slot_prep_meta_record(prep_path)
    if _pickle_sidecar_fresh(prep_path, meta_record):
        if on_progress:
            on_progress("prep_cache", 0, 1, "敌人：载入槽位缓存（.pkl 快载，跳过重建）…")
        with slot_prep_pickle_path(prep_path).open("rb") as fh:
            data = pickle.load(fh)
        _ensure_prep_pickle_key(prep_path, meta_record)
        if on_progress:
            on_progress(
                "prep_cache",
                1,
                1,
                f"敌人：槽位缓存已载入（{len(data.get('slots') or [])} 槽，跳过重建）",
            )
        return data

    gz_path = slot_prep_gz_path(prep_path)
    if on_progress:
        on_progress("prep_cache", 0, 1, "敌人：载入槽位缓存（.json.gz，跳过重建）…")
    if prep_path.is_file():
        data = _load_json(prep_path)
    elif gz_path.is_file():
        with gzip.open(gz_path, "rt", encoding="utf-8") as fh:
            data = json.load(fh)
    else:
        raise FileNotFoundError(f"missing slot prep: {prep_path} / {gz_path}")
    _write_prep_pickle(prep_path, data, meta_record=meta_record)
    slot_count = len(data.get("slots") or [])
    if on_progress:
        on_progress(
            "prep_cache",
            1,
            1,
            f"敌人：槽位缓存已载入（{slot_count} 槽，跳过重建）",
        )
    return data


def materialize_slot_prep_json(
    prep_path: Path | None = None,
    *,
    on_progress: Callable[[str, int, int, str], None] | None = None,
) -> bool:
    """Optional: decompress .json.gz → .json for Smithbox 调试；日常生成不必调用。"""
    prep_path = prep_path or DEFAULT_SLOT_PREP_PATH
    if prep_path.is_file():
        return True
    gz_path = slot_prep_gz_path(prep_path)
    if not gz_path.is_file():
        return False
    if on_progress:
        on_progress("prep_cache", 0, 1, "敌人：解压槽位缓存到 .json（可选）…")
    prep_path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(gz_path, "rb") as src, prep_path.open("wb") as dst:
        shutil.copyfileobj(src, dst)
    if on_progress:
        on_progress("prep_cache", 1, 1, "敌人：槽位 .json 已解压")
    return True


def is_slot_prep_valid(
    prep_path: Path,
    *,
    meta: dict[str, str] | None = None,
) -> bool:
    prep_path = Path(prep_path)
    record = read_slot_prep_meta_record(prep_path)
    # 发行包发布缓存：frozen exe 只认版本+成品文件，跳过指纹（解压不得逼重建）。
    if (
        record is not None
        and bool(record.get("release_cache"))
        and getattr(sys, "frozen", False)
    ):
        if int(record.get("version", 0)) != PREP_VERSION:
            return False
        gz_path = prep_path.parent / str(
            record.get("artifact") or slot_prep_gz_path(prep_path).name
        )
        return gz_path.is_file() or prep_path.is_file()

    if meta is None:
        meta = prep_meta()
    if record is not None:
        if int(record.get("version", 0)) != PREP_VERSION:
            return False
        stored = record.get("meta") or {}
        for key in PREP_META_KEYS:
            if str(stored.get(key, "")) != str(meta.get(key, "")):
                return False
        gz_path = prep_path.parent / str(record.get("artifact") or slot_prep_gz_path(prep_path).name)
        if gz_path.is_file():
            return True
        return prep_path.is_file()
    if not prep_path.is_file():
        gz_only = slot_prep_gz_path(prep_path)
        if not gz_only.is_file():
            return False
    try:
        data = _load_json(prep_path) if prep_path.is_file() else {}
    except (OSError, json.JSONDecodeError):
        return False
    if prep_path.is_file():
        if int(data.get("version", 0)) != PREP_VERSION:
            return False
        stored = data.get("meta") or {}
        for key in PREP_META_KEYS:
            if str(stored.get(key, "")) != str(meta.get(key, "")):
                return False
        return bool(data.get("donors")) and bool(data.get("slots"))
    return False


def stamp_release_prep_cache(prep_path: Path | None = None) -> Path:
    """Mark sidecar as shipped release cache (pack only). Dev rebuilds omit this flag."""
    prep_path = Path(prep_path or DEFAULT_SLOT_PREP_PATH)
    record = read_slot_prep_meta_record(prep_path)
    if record is None:
        raise FileNotFoundError(f"missing prep meta for release stamp: {prep_path}")
    if int(record.get("version", 0)) != PREP_VERSION:
        raise ValueError(
            f"cannot stamp release_cache: version={record.get('version')} want={PREP_VERSION}"
        )
    gz_path = prep_path.parent / str(
        record.get("artifact") or slot_prep_gz_path(prep_path).name
    )
    if not gz_path.is_file() and not prep_path.is_file():
        raise FileNotFoundError(f"missing prep artifact for release stamp: {gz_path}")
    record["release_cache"] = True
    out = slot_prep_meta_path(prep_path)
    out.write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return out


_PREP_CACHE_MISS_LABELS: dict[str, str] = {
    "index": "敌人索引 enemy_index.json",
    "archetypes": "原型表 enemy_archetypes.json",
    "dlc_pool_mode": "DLC 混池模式",
    "categories_compat": "categories 兼容规则子集",
    "donor_review_excludes": "捐皮手工剔除 donor_pool_review_manual_excludes.json",
    "donor_review_allowlist": "捐皮白名单 donor_pool_review_allowlist.json",
    "bundle_catalog": "Bundle 捐皮大表 bundle_catalog.json",
    "slot_tags": "槽位标签 slot_tags.json",
    "bundle_slot_compat": "槽×Bundle 兼容 bundle_slot_compat.json",
    "donor_msb_compat": "捐皮 MSB compat cache + overrides",
}

_PREP_REBUILD_LOG = "敌人：重建槽位缓存"


def assert_bundle_exports_for_generate(prep: dict[str, Any] | None = None) -> None:
    """Hard gate: bundle export fingerprints must match prep meta (R3)."""
    from bundle_cache import BundleExportError, validate_bundle_exports_for_prep

    expected = None
    if prep is not None:
        stored = prep.get("meta") or {}
        expected = {
            k: str(stored.get(k, ""))
            for k in ("bundle_catalog", "slot_tags", "bundle_slot_compat")
        }
    try:
        validate_bundle_exports_for_prep(expected=expected)
    except BundleExportError as exc:
        raise SystemExit(str(exc)) from exc


def explain_prep_cache_miss(
    prep_path: Path | None = None,
    *,
    meta: dict[str, str] | None = None,
) -> str:
    """槽位缓存为何失效（供 GUI/CLI 日志）。"""
    prep_path = prep_path or DEFAULT_SLOT_PREP_PATH
    if meta is None:
        meta = prep_meta()
    record = read_slot_prep_meta_record(prep_path)
    if record is None:
        gz_path = slot_prep_gz_path(prep_path)
        if not prep_path.is_file() and not gz_path.is_file():
            return "缺少 enemy_slot_prep.json.gz"
        return "缺少 meta 侧车"
    if int(record.get("version", 0)) != PREP_VERSION:
        return f"PREP_VERSION {record.get('version')} → {PREP_VERSION}"
    stored = record.get("meta") or {}
    parts: list[str] = []
    for key in PREP_META_KEYS:
        if str(stored.get(key, "")) != str(meta.get(key, "")):
            parts.append(_PREP_CACHE_MISS_LABELS.get(key, key))
    if parts:
        return "指纹变更（" + "、".join(parts) + "）— 将全图筛选捐皮模板，约 5～8 分钟"
    gz_path = prep_path.parent / str(
        record.get("artifact") or slot_prep_gz_path(prep_path).name
    )
    if not gz_path.is_file() and not prep_path.is_file():
        return "缓存文件缺失"
    return "未知原因"


def _emit_prep_progress(
    on_progress: Callable[[str, int, int, str], None] | None,
    done: int,
    total: int,
    msg: str,
    *,
    state: dict[str, float] | None = None,
    heartbeat_s: float = 30.0,
    step: int = 200,
) -> None:
    """prep 构建进度：每 step 条 + 超时心跳（防长时间无日志）。"""
    if not on_progress:
        return
    total = max(int(total), 1)
    done = max(0, int(done))
    now = time.monotonic()
    st = state if state is not None else {}
    force = done in (0, total) or done % max(step, 1) == 0
    if force:
        on_progress("prep_cache", done, total, msg)
        st["last"] = now
        return
    last = float(st.get("last") or 0.0)
    if now - last >= heartbeat_s:
        pct = f"{100 * done / total:.0f}%"
        on_progress("prep_cache", done, total, f"{msg}（仍在运行 {pct}）")
        st["last"] = now


def _donor_compact(
    tpl: dict[str, Any],
    compat_by_tid: dict[str, dict[str, Any]] | None = None,
    *,
    size_tier: str | None = None,
    size_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    from donor_msb_compat import attach_donor_msb_tags

    model = str(tpl.get("model") or "")
    tier = size_tier or str(tpl.get("size_tier") or "")
    if not tier:
        tags = tpl.get("template_tags") or {}
        tier = str(tags.get("size_tier") or "")
    if not tier and model and size_map:
        from enemy_category_rules import resolve_size_tier

        tier = resolve_size_tier(model, size_map)
    rec = {
        "template_id": tpl.get("template_id"),
        "donor_map": tpl.get("donor_map"),
        "donor_entity": tpl.get("donor_entity"),
        "model": tpl.get("model"),
        "npc": tpl.get("npc"),
        "think": tpl.get("think"),
        "chara": tpl.get("chara", -1),
        "walk_route": tpl.get("walk_route"),
    }
    if tier:
        rec["size_tier"] = tier
    return attach_donor_msb_tags(rec, compat_by_tid)


_SLOT_PREP_CACHE: tuple[float, dict[str, Any]] | None = None


def _donor_expand(rec: dict[str, Any]) -> dict[str, Any]:
    return dict(rec)


def clear_slot_prep_cache() -> None:
    global _SLOT_PREP_CACHE
    _SLOT_PREP_CACHE = None


def _catalog_index_for(
    tpl: dict[str, Any],
    donors: list[dict[str, Any]],
    index: dict[str, int],
    compat_by_tid: dict[str, dict[str, Any]] | None = None,
    *,
    size_map: dict[str, str] | None = None,
) -> int:
    key = str(tpl.get("template_id", ""))
    if key in index:
        return index[key]
    idx = len(donors)
    donors.append(_donor_compact(tpl, compat_by_tid, size_map=size_map))
    index[key] = idx
    return idx


def _prep_slot_entry(slot: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    core = _core()
    categories_cfg = ctx["categories_cfg"]
    npc_csv_dir = ctx["npc_csv_dir"]
    skip_mount_slot_keys = ctx["skip_mount_slot_keys"]
    rider_to_mount = ctx["rider_to_mount"]

    map_id = str(slot["map_id"])
    entity_name = str(slot["name"])
    if (map_id, entity_name) in skip_mount_slot_keys:
        return {"m": map_id, "n": entity_name, "k": "mount"}

    slot_model = str(slot.get("model", ""))
    rules_cat = core.resolve_src_category(slot_model, categories_cfg)
    src_cat = core.resolve_entity_category(
        slot,
        categories_cfg=categories_cfg,
        csv_dir=npc_csv_dir,
        rules_category=rules_cat,
    )
    if core.is_non_participating_map(map_id, categories_cfg):
        return {"m": map_id, "n": entity_name, "k": "hub", "s": src_cat}
    if core.is_keep_original_map_entity_slot(slot, categories_cfg):
        return {"m": map_id, "n": entity_name, "k": "npc", "s": src_cat}
    if core.is_excluded_slot_npc_id(slot, categories_cfg):
        return {"m": map_id, "n": entity_name, "k": "npc", "s": src_cat}
    if core.is_cnv_original_boss_slot_npc_id(slot, categories_cfg):
        return {"m": map_id, "n": entity_name, "k": "npc", "s": src_cat}
    # 雾门主线 _9000：常挂过场 talk_id / boss 体型；仍参与 6 池互洗（满月等 exclude 除外）
    fog_main = core.is_scripted_dungeon_main_boss_slot(
        slot, categories_cfg
    ) and not core.is_excluded_slot_model(
        slot_model, categories_cfg, slot, npc_csv_dir
    )
    if not fog_main:
        if core.is_talk_npc_slot(slot, npc_csv_dir):
            return {"m": map_id, "n": entity_name, "k": "npc", "s": src_cat}
        if core.is_msb_talk_slot(slot):
            return {"m": map_id, "n": entity_name, "k": "npc", "s": src_cat}
        if core.is_script_event_npc_slot(slot, npc_csv_dir, categories_cfg):
            return {"m": map_id, "n": entity_name, "k": "npc", "s": src_cat}
        if core.is_caravan_event_slot(slot, categories_cfg):
            return {"m": map_id, "n": entity_name, "k": "npc", "s": src_cat}
        if core.is_siege_operator_slot(slot, categories_cfg):
            return {"m": map_id, "n": entity_name, "k": "siege", "s": src_cat}
        if core.is_excluded_slot_model(slot_model, categories_cfg, slot, npc_csv_dir):
            return {"m": map_id, "n": entity_name, "k": "npc", "s": src_cat}
        if core.is_invisible_enemy_model(slot_model, categories_cfg):
            return {"m": map_id, "n": entity_name, "k": "npc", "s": src_cat}
        if core.is_decorative_npc_slot(slot, categories_cfg):
            return {"m": map_id, "n": entity_name, "k": "npc", "s": src_cat}
        if core.is_passive_animal_model(slot_model, categories_cfg):
            return {"m": map_id, "n": entity_name, "k": "animal", "s": src_cat}
        if core.is_keep_original_slot_model(slot_model, categories_cfg):
            return {"m": map_id, "n": entity_name, "k": "scarab", "s": src_cat}
        size_map = ctx["size_map"]
        slot_tier = core.resolve_size_tier(slot_model, size_map)
        exclude_slot_tiers = ctx["exclude_slot_tiers"]
        if core.should_skip_excluded_slot_tier(slot_tier, exclude_slot_tiers):
            return {"m": map_id, "n": entity_name, "k": "large", "s": src_cat}

    partner_mount = rider_to_mount.get((map_id, entity_name))
    pools = _build_prep_row_pools(slot, src_cat, ctx)
    if not pools:
        if fog_main:
            # 生成侧 fog_major_boss_swap_indices 会补合成皮；此处勿冻成 k=npc
            return {"m": map_id, "n": entity_name, "s": "major_boss"}
        return {"m": map_id, "n": entity_name, "k": "npc", "s": src_cat}

    entry: dict[str, Any] = {
        "m": map_id,
        "n": entity_name,
        "s": src_cat,
        "o": pools,
    }
    baked = _bake_prep_runtime_pools(slot, pools, ctx)
    if baked:
        entry["w"] = baked
    if partner_mount is not None:
        entry["p"] = str(partner_mount.get("name", ""))
    return entry


def _bake_prep_runtime_pools(
    slot: dict[str, Any],
    pools: dict[str, list[int]],
    ctx: dict[str, Any],
) -> dict[str, list[list[int]]]:
    """R5：prep 合成时模拟 resolve，generate 直读 w 列（对齐 T-084 §5.4）。"""
    model_index = ctx.get("model_vanilla_index")
    if not model_index:
        return {}
    from donor_vanilla_states import resolve_slot_runtime_npc_and_think

    categories_cfg = ctx["categories_cfg"]
    donors: list[dict[str, Any]] = ctx.get("donors") or []
    core = _core()
    out: dict[str, list[list[int]]] = {}
    for cat, idxs in pools.items():
        pairs: list[list[int]] = []
        for i in idxs:
            if i < 0 or i >= len(donors):
                continue
            rec = donors[i]
            try:
                donor_npc = int(rec.get("npc") or 0)
            except (TypeError, ValueError):
                donor_npc = 0
            npc, think = resolve_slot_runtime_npc_and_think(
                slot,
                rec,
                donor_npc,
                categories_cfg,
                model_index,
            )
            # 对齐后的实战行若在 never_donor_npc_ids（如拉车山妖 46001010），勿写入 w
            if core.is_never_donor_npc_id({"npc": npc}, categories_cfg):
                continue
            if core.is_excluded_slot_npc_id({"npc": npc}, categories_cfg):
                continue
            pairs.append([npc, think])
        if pairs:
            out[cat] = pairs
    return out


def _slot_pool_fingerprint(slot: dict[str, Any], src_cat: str) -> tuple[Any, ...]:
    from whitelist_slot_receptor import classify_receptor_bucket

    tags = slot.get("slot_tags") or {}
    return (
        str(slot.get("model", "")),
        str(src_cat),
        str(tags.get("map_kind", "")),
        str(tags.get("size_tier", "")),
        classify_receptor_bucket(slot),
        bool(tags.get("has_walk_route")),
        int(slot.get("backup_anim", -1) or -1) > 0,
    )


def _build_prep_row_pools(
    slot: dict[str, Any],
    src_cat: str,
    ctx: dict[str, Any],
) -> dict[str, list[int]]:
    fp = _slot_pool_fingerprint(slot, src_cat)
    cache = ctx.setdefault("pool_by_fingerprint", {})
    cached = cache.get(fp)
    if cached is not None:
        return cached

    core = _core()
    categories_cfg = ctx["categories_cfg"]
    compat_pools = ctx["compat_pools"]
    dlc_pool_mode = ctx["dlc_pool_mode"]
    size_map = ctx["size_map"]
    donors: list[dict[str, Any]] = ctx["donors"]
    catalog_index: dict[str, int] = ctx["catalog_index"]
    compat_by_tid: dict[str, dict[str, Any]] = ctx.get("donor_msb_compat") or {}
    receptor_index: dict[str, dict[str, Any]] = ctx.get("whitelist_receptor_index") or {}

    pools: dict[str, list[int]] = {}
    for tgt_cat in core.CATEGORY_ORDER:
        pool = core.filter_slot_donor_pool(
            compat_pools,
            slot,
            tgt_cat,
            src_cat,
            categories_cfg=categories_cfg,
            dlc_pool_mode=dlc_pool_mode,
            size_map=size_map,
            donor_msb_compat=compat_by_tid,
            whitelist_receptor_index=receptor_index,
        )
        if pool:
            indices = [
                _catalog_index_for(
                    tpl, donors, catalog_index, compat_by_tid, size_map=size_map
                )
                for tpl in pool
            ]
            pools[tgt_cat] = _bake_prep_pool_sort(
                indices,
                donors,
                slot,
                compat_by_tid,
                categories_cfg,
            )
    cache[fp] = pools
    return pools


def _bake_prep_pool_sort(
    indices: list[int],
    donors: list[dict[str, Any]],
    slot: dict[str, Any],
    compat_by_tid: dict[str, dict[str, Any]],
    categories_cfg: dict[str, Any],
) -> list[int]:
    """R3 — patrol donor order baked into prep (flyer soft prefer removed T-088)."""
    if not indices:
        return indices
    from donor_vanilla_states import (
        prioritize_flyer_donor_indices,
        prioritize_patrol_donor_indices,
    )

    prep_stub = {"donors": donors}
    ordered = prioritize_patrol_donor_indices(
        prep_stub, indices, slot, compat_by_tid
    )
    return prioritize_flyer_donor_indices(
        prep_stub, ordered, slot, compat_by_tid, categories_cfg
    )


def build_prep_hydrate_ctx_light(
    prep: dict[str, Any],
    index: dict[str, Any],
    categories_cfg: dict[str, Any],
    *,
    dlc_pool_mode: str,
    npc_csv_dir: Path,
) -> dict[str, Any]:
    """Hydrate ctx from prep.donors only — avoids re-scanning full enemy_index templates."""
    core = _core()
    exclude_slot_tiers = set(categories_cfg.get("exclude_slot_size_tiers") or [])
    exclude_donor_tiers = set(categories_cfg.get("exclude_donor_size_tiers") or [])
    size_map = categories_cfg.get("size_tier_by_model_prefix", {})

    templates_by_cat: dict[str, list[dict[str, Any]]] = {
        c: [] for c in core.CATEGORY_ORDER
    }
    for rec in prep.get("donors") or []:
        tpl = _donor_expand(rec)
        model = str(tpl.get("model", ""))
        rules_cat = core.resolve_src_category(model, categories_cfg)
        cat = normalize_category_id(
            core.resolve_entity_category(
                tpl,
                categories_cfg=categories_cfg,
                csv_dir=npc_csv_dir,
                rules_category=rules_cat,
            )
        )
        tpl["category"] = cat
        if cat in templates_by_cat:
            templates_by_cat[cat].append(tpl)

    compat_pools = core.build_compat_pools(
        templates_by_cat,
        size_map=size_map,
        exclude_donor_tiers=exclude_donor_tiers,
        categories_cfg=categories_cfg,
    )
    slots = index.get("slots", [])
    rider_to_mount, skip_mount_slot_keys = core.index_rider_mount_slot_pairs(
        slots, categories_cfg
    )
    mount_pair_donors_by_kind = core.build_mount_pair_donors(
        index.get("templates", []), categories_cfg
    )
    from bundle_cache import compat_by_tid_from_bundle_slot_compat

    donors = prep.setdefault("donors", [])
    catalog_index: dict[str, int] = {}
    for i, donor in enumerate(donors):
        key = str(donor.get("template_id", ""))
        if key:
            catalog_index[key] = i
    bundle_compat = compat_by_tid_from_bundle_slot_compat()
    from donor_vanilla_states import build_model_vanilla_state_index

    return {
        "categories_cfg": categories_cfg,
        "compat_pools": compat_pools,
        "dlc_pool_mode": dlc_pool_mode,
        "size_map": size_map,
        "npc_csv_dir": npc_csv_dir,
        "exclude_slot_tiers": exclude_slot_tiers,
        "skip_mount_slot_keys": skip_mount_slot_keys,
        "rider_to_mount": rider_to_mount,
        "mount_pair_donors_by_kind": mount_pair_donors_by_kind,
        "donor_msb_compat": bundle_compat,
        # T-084 R5：反扫表不进 pick；恒空（reports 对账另走 export）
        "whitelist_receptor_index": {},
        "donors": donors,
        "catalog_index": catalog_index,
        "pool_by_fingerprint": {},
        "model_vanilla_index": build_model_vanilla_state_index(slots),
    }


def make_prep_hydrate_ctx(
    prep: dict[str, Any],
    index: dict[str, Any],
    categories_cfg: dict[str, Any],
    *,
    dlc_pool_mode: str,
    npc_csv_dir: Path,
    on_progress: Callable[[str, int, int, str], None] | None = None,
) -> dict[str, Any]:
    """Lazy donor-pool fill for prep rows that were skipped when cache was built."""
    if prep.get("donors"):
        return build_prep_hydrate_ctx_light(
            prep,
            index,
            categories_cfg,
            dlc_pool_mode=dlc_pool_mode,
            npc_csv_dir=npc_csv_dir,
        )
    ctx = build_prep_context(
        index,
        categories_cfg,
        dlc_pool_mode=dlc_pool_mode,
        npc_csv_dir=npc_csv_dir,
        on_progress=on_progress,
    )
    donors = prep.setdefault("donors", [])
    catalog_index: dict[str, int] = {}
    for i, donor in enumerate(donors):
        key = str(donor.get("template_id", ""))
        if key:
            catalog_index[key] = i
    ctx["donors"] = donors
    ctx["catalog_index"] = catalog_index
    return ctx


def hydrate_missing_prep_pools(
    row: dict[str, Any],
    slot: dict[str, Any],
    hydrate_ctx: dict[str, Any],
) -> bool:
    """旧 prep 仅有部分 `o` 类别时补全（如 cnv_special 池规则变更后）。"""
    if not prep_row_has_pools(row):
        return False
    pools = row.get("o") or {}
    core = _core()
    src_cat = str(
        row.get("s")
        or slot.get("src_cat")
        or (slot.get("slot_tags") or {}).get("src_cat")
        or core.resolve_entity_category(
            slot,
            categories_cfg=hydrate_ctx["categories_cfg"],
            csv_dir=hydrate_ctx["npc_csv_dir"],
        )
    )
    row["s"] = src_cat
    missing_cats: list[str] = []
    if normalize_category_id(src_cat) == "major_boss" and not pools.get("major_boss"):
        missing_cats.append("major_boss")
    if src_cat == "major_boss" and not pools.get("major_boss"):
        missing_cats.append("major_boss")
    if not missing_cats:
        return prep_row_has_pools(row)
    fresh = _build_prep_row_pools(slot, src_cat, hydrate_ctx)
    if not fresh:
        return prep_row_has_pools(row)
    for cat in missing_cats:
        indices = fresh.get(cat) or []
        if indices:
            pools[cat] = indices
    row["o"] = pools
    return prep_row_has_pools(row)


def hydrate_stale_prep_row(
    row: dict[str, Any],
    slot: dict[str, Any],
    hydrate_ctx: dict[str, Any],
) -> bool:
    """Backfill row['o'] when an old skip flag was cleared. Returns True if pools exist."""
    if prep_row_has_pools(row):
        return hydrate_missing_prep_pools(row, slot, hydrate_ctx)
    core = _core()
    src_cat = str(
        row.get("s")
        or slot.get("src_cat")
        or (slot.get("slot_tags") or {}).get("src_cat")
        or core.resolve_entity_category(
            slot,
            categories_cfg=hydrate_ctx["categories_cfg"],
            csv_dir=hydrate_ctx["npc_csv_dir"],
        )
    )
    row["s"] = src_cat
    pools = _build_prep_row_pools(slot, src_cat, hydrate_ctx)
    if not pools:
        return False
    row["o"] = pools
    return True


def fresh_prep_row_src_cat(
    slot: dict[str, Any],
    categories_cfg: dict[str, Any],
    npc_csv_dir: Path,
) -> str:
    """当前规则下的 src_cat（不建 compat 池）。"""
    core = _core()
    slot_model = str(slot.get("model", ""))
    rules_cat = core.resolve_src_category(slot_model, categories_cfg)
    return core.resolve_entity_category(
        slot,
        categories_cfg=categories_cfg,
        csv_dir=npc_csv_dir,
        rules_category=rules_cat,
    )


def reconcile_prep_row_src_cat(
    row: dict[str, Any],
    slot: dict[str, Any],
    *,
    categories_cfg: dict[str, Any],
    npc_csv_dir: Path,
    hydrate_ctx: dict[str, Any] | None = None,
    get_hydrate_ctx: Callable[[], dict[str, Any]] | None = None,
) -> bool:
    """Re-derive src_cat from current rules; rebuild donor pools only when it changes."""
    fresh = fresh_prep_row_src_cat(slot, categories_cfg, npc_csv_dir)
    if fresh == str(row.get("s", "")):
        return prep_row_has_pools(row)
    row["s"] = fresh
    ctx = hydrate_ctx
    if ctx is None:
        if get_hydrate_ctx is None:
            return False
        ctx = get_hydrate_ctx()
    pools = _build_prep_row_pools(slot, fresh, ctx)
    if not pools:
        row.pop("o", None)
        return False
    row["o"] = pools
    return True


def _worker_init(pickle_path: str) -> None:
    global _WORKER_CTX
    with open(pickle_path, "rb") as fh:
        _WORKER_CTX = pickle.load(fh)


def _worker_chunk(slots: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    assert _WORKER_CTX is not None
    ctx = {
        **_WORKER_CTX,
        "donors": [],
        "catalog_index": {},
    }
    out: list[dict[str, Any]] = []
    for slot in slots:
        out.append(_prep_slot_entry(slot, ctx))
    return out, ctx["donors"]


def _merge_donor_chunks(
    chunks: list[tuple[list[dict[str, Any]], list[dict[str, Any]]]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    global_donors: list[dict[str, Any]] = []
    global_index: dict[str, int] = {}
    merged_slots: list[dict[str, Any]] = []

    for slot_entries, local_donors in chunks:
        local_remap: dict[int, int] = {}
        for local_i, donor in enumerate(local_donors):
            key = str(donor.get("template_id", ""))
            if key in global_index:
                local_remap[local_i] = global_index[key]
            else:
                global_index[key] = len(global_donors)
                local_remap[local_i] = len(global_donors)
                global_donors.append(donor)

        for entry in slot_entries:
            pools = entry.get("o")
            if pools:
                entry["o"] = {
                    cat: [local_remap[i] for i in ids]
                    for cat, ids in pools.items()
                }
            merged_slots.append(entry)

    return merged_slots, global_donors


def build_prep_context(
    index: dict[str, Any],
    categories_cfg: dict[str, Any],
    *,
    dlc_pool_mode: str,
    npc_csv_dir: Path,
    on_progress: Callable[[str, int, int, str], None] | None = None,
) -> dict[str, Any]:
    """R3 — prep synthesis reads bundle export tables; no full-index donor scan."""
    core = _core()

    from bundle_cache import (
        compat_by_tid_from_bundle_slot_compat,
        load_bundle_catalog,
        templates_by_cat_from_bundle_catalog,
        validate_bundle_exports_for_prep,
    )

    validate_bundle_exports_for_prep()

    exclude_slot_tiers = set(categories_cfg.get("exclude_slot_size_tiers") or [])
    exclude_donor_tiers = set(categories_cfg.get("exclude_donor_size_tiers") or [])
    size_map = categories_cfg.get("size_tier_by_model_prefix", {})

    catalog = load_bundle_catalog()
    bundle_count = int(catalog.get("bundle_count") or len(catalog.get("bundles") or {}))
    if on_progress:
        on_progress(
            "prep_cache",
            0,
            1,
            f"{_PREP_REBUILD_LOG} — ①读 Bundle 大表（{bundle_count} 种捐皮）…",
        )

    templates_by_cat = templates_by_cat_from_bundle_catalog(
        catalog, index, categories_cfg
    )
    donor_tpl_count = sum(len(v) for v in templates_by_cat.values())
    if on_progress:
        on_progress(
            "prep_cache",
            1,
            1,
            f"{_PREP_REBUILD_LOG} — ②合并捐皮池（{donor_tpl_count} 条）…",
        )
    compat_pools = core.build_compat_pools(
        templates_by_cat,
        size_map=size_map,
        exclude_donor_tiers=exclude_donor_tiers,
        categories_cfg=categories_cfg,
    )
    slots = index.get("slots", [])
    rider_to_mount, skip_mount_slot_keys = core.index_rider_mount_slot_pairs(
        slots, categories_cfg
    )
    mount_pair_donors_by_kind = core.build_mount_pair_donors(
        index.get("templates", []), categories_cfg
    )
    if on_progress:
        on_progress(
            "prep_cache",
            1,
            1,
            f"{_PREP_REBUILD_LOG} — ②捐皮池就绪（{len(compat_pools)} 组）…",
        )

    from bundle_cache import compat_by_tid_from_bundle_slot_compat

    slots = index.get("slots", [])
    from donor_vanilla_states import build_model_vanilla_state_index

    model_vanilla_index = build_model_vanilla_state_index(slots)

    return {
        "categories_cfg": categories_cfg,
        "compat_pools": compat_pools,
        "dlc_pool_mode": dlc_pool_mode,
        "size_map": size_map,
        "npc_csv_dir": npc_csv_dir,
        "exclude_slot_tiers": exclude_slot_tiers,
        "skip_mount_slot_keys": skip_mount_slot_keys,
        "rider_to_mount": rider_to_mount,
        "mount_pair_donors_by_kind": mount_pair_donors_by_kind,
        "donor_msb_compat": compat_by_tid_from_bundle_slot_compat(),
        # T-084 R5：反扫表不进 pick；恒空（reports 对账另走 export）
        "whitelist_receptor_index": {},
        "model_vanilla_index": model_vanilla_index,
    }


def build_slot_prep(
    index: dict[str, Any],
    categories_cfg: dict[str, Any],
    *,
    dlc_pool_mode: str = "mixed",
    npc_csv_dir: Path,
    out_path: Path | None = None,
    workers: int | None = None,
    on_progress: Callable[[str, int, int, str], None] | None = None,
) -> Path:
    out_path = out_path or DEFAULT_SLOT_PREP_PATH
    out_path.parent.mkdir(parents=True, exist_ok=True)

    ctx = build_prep_context(
        index,
        categories_cfg,
        dlc_pool_mode=dlc_pool_mode,
        npc_csv_dir=npc_csv_dir,
        on_progress=on_progress,
    )
    slots = list(index.get("slots", []))
    total = len(slots)
    worker_n = workers or max(1, os.cpu_count() or 4)
    # PyInstaller: ProcessPool re-execs the GUI entry; GUI often passes workers=CPU
    # explicitly, so always force 1 when frozen (orphans + 32× slow disk thrash).
    if getattr(sys, "frozen", False):
        worker_n = 1
    slot_prog: dict[str, float] = {}

    _emit_prep_progress(
        on_progress,
        0,
        total,
        f"{_PREP_REBUILD_LOG} — ③为 MSB 槽分配捐皮池（{worker_n} 进程 / {total} 槽）…",
        state=slot_prog,
    )

    chunk_size = max(50, (total + worker_n * 4 - 1) // (worker_n * 4))
    chunks = [slots[i : i + chunk_size] for i in range(0, total, chunk_size)]

    if on_progress:
        on_progress("prep_cache", 0, total, f"{_PREP_REBUILD_LOG} — ③启动并行 worker…")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pkl") as tmp:
        pickle_path = tmp.name
        pickle.dump(ctx, tmp, protocol=pickle.HIGHEST_PROTOCOL)

    try:
        results: list[tuple[list[dict[str, Any]], list[dict[str, Any]]]] = []
        if worker_n <= 1 or len(chunks) <= 1:
            local_ctx = {**ctx, "donors": [], "catalog_index": {}}
            entries: list[dict[str, Any]] = []
            for i, s in enumerate(slots, start=1):
                entries.append(_prep_slot_entry(s, local_ctx))
                _emit_prep_progress(
                    on_progress,
                    i,
                    total,
                    f"{_PREP_REBUILD_LOG} — ③分配 MSB 槽 {i}/{total}…",
                    state=slot_prog,
                )
            results = [(entries, local_ctx["donors"])]
        else:
            done = 0
            with ProcessPoolExecutor(
                max_workers=worker_n,
                initializer=_worker_init,
                initargs=(pickle_path,),
            ) as pool:
                futures = {pool.submit(_worker_chunk, ch): len(ch) for ch in chunks}
                for fut in as_completed(futures):
                    results.append(fut.result())
                    done += futures[fut]
                    _emit_prep_progress(
                        on_progress,
                        done,
                        total,
                        f"{_PREP_REBUILD_LOG} — ③分配 MSB 槽 {done}/{total}…",
                        state=slot_prog,
                    )
    finally:
        try:
            os.unlink(pickle_path)
        except OSError:
            pass

    merged_slots, donors = _merge_donor_chunks(results)
    if on_progress:
        on_progress(
            "prep_cache",
            total,
            total,
            f"{_PREP_REBUILD_LOG} — ④写入 enemy_slot_prep（{len(donors)} 捐皮 / {len(merged_slots)} 槽）…",
        )
    meta = prep_meta(dlc_pool_mode=dlc_pool_mode)
    payload = {
        "version": PREP_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "meta": meta,
        "donors": donors,
        "slots": merged_slots,
        "stats": {
            "slot_rows": len(merged_slots),
            "donor_templates": len(donors),
            "workers": worker_n,
        },
    }
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    _write_prep_pickle(out_path, payload)
    if on_progress:
        on_progress(
            "prep_cache",
            total,
            total,
            f"{_PREP_REBUILD_LOG} — ④压缩 enemy_slot_prep.json.gz…",
        )
    write_slot_prep_sidecars(payload, out_path)
    if on_progress:
        on_progress(
            "prep_cache",
            total,
            total,
            f"{_PREP_REBUILD_LOG}完成（{len(donors)} 捐皮 / {len(merged_slots)} 槽；下次生成直读缓存）",
        )
    return out_path


def load_slot_prep(
    path: Path | None = None,
    *,
    on_progress: Callable[[str, int, int, str], None] | None = None,
) -> dict[str, Any]:
    global _SLOT_PREP_CACHE
    path = path or DEFAULT_SLOT_PREP_PATH
    cache_key = 0.0
    for candidate in (
        slot_prep_pickle_path(path),
        path,
        slot_prep_gz_path(path),
    ):
        if candidate.is_file():
            cache_key = max(cache_key, candidate.stat().st_mtime)
    if _SLOT_PREP_CACHE is not None and _SLOT_PREP_CACHE[0] == cache_key:
        return _SLOT_PREP_CACHE[1]
    data = _read_prep_payload(path, on_progress=on_progress)
    _SLOT_PREP_CACHE = (cache_key, data)
    return data


def warn_stale_prep_version(
    prep_path: Path | None = None,
) -> None:
    """启动时检查 cache 版本，若低于当前 PREP_VERSION 则打印警告。"""
    path = prep_path or DEFAULT_SLOT_PREP_PATH
    record = read_slot_prep_meta_record(path)
    if record is None:
        return  # no cache
    cached_ver = int(record.get("version", 0))
    if cached_ver < PREP_VERSION:
        print(
            f"[WARN] cache/enemy_slot_prep.json version={cached_ver} < PREP_VERSION={PREP_VERSION}  "
            f"({_VER_NOTES.get(PREP_VERSION, '口径已更新')}): 请重跑 prep"
        )
    elif cached_ver > PREP_VERSION:
        print(
            f"[WARN] cache/enemy_slot_prep.json version={cached_ver} > PREP_VERSION={PREP_VERSION}  "
            f"cache 比代码新，可能需要升级代码"
        )


_VER_NOTES: dict[int, str] = {
    57: "T-097 大型/超巨/主线Boss 野外可捐（2026-09-02）",
    58: "P0-1: c2151 禁捐；P0-2: 骑乘骑士结构性零捐清理（2026-09-04）",
    59: "残破喷火石像鬼 npc 47702034 禁捐（仅此行，非整模 c4770；2026-09-04）",
    60: "沉默灵 Silent Spirit npc 500000010/042/066 禁捐（teamType=0 站着不打；2026-09-09）",
    61: "火焰战车 c4460 不捐不随机（车不算怪；2026-09-09）",
    62: "马车事件 c4300 排除 + 植物锚点 + attack sp 禁区域 hp（2026-09-09）",
    63: "马车假人小兵：事件图仅 c0110/c0100/c4600 保住、c0110 不沉；小兵走密集（2026-09-09）",
    66: "红狮子祭典助战 keep_original_map_entity_slots（2026-09-17）",
}


def load_slot_prep_if_valid(
    *,
    prep_path: Path | None = None,
    meta: dict[str, str] | None = None,
    on_progress: Callable[[str, int, int, str], None] | None = None,
) -> Path | None:
    """读已有槽位缓存；缺失时由生成流程自动 build_slot_prep，不走慢扫描。"""
    prep_path = prep_path or DEFAULT_SLOT_PREP_PATH
    if meta is None:
        meta = prep_meta()
    if not is_slot_prep_valid(prep_path, meta=meta):
        return None
    if not any(
        p.is_file()
        for p in (
            slot_prep_pickle_path(prep_path),
            prep_path,
            slot_prep_gz_path(prep_path),
        )
    ):
        return None
    return prep_path


def ensure_slot_prep(
    index: dict[str, Any],
    categories_cfg: dict[str, Any],
    *,
    dlc_pool_mode: str,
    npc_csv_dir: Path,
    prep_path: Path | None = None,
    workers: int | None = None,
    on_progress: Callable[[str, int, int, str], None] | None = None,
) -> Path:
    """维护者显式构建缓存（`python enemy_randomizer_core.py prep`）；日常生成不调用。"""
    prep_path = prep_path or DEFAULT_SLOT_PREP_PATH
    meta = prep_meta(dlc_pool_mode=dlc_pool_mode)
    existing = load_slot_prep_if_valid(prep_path=prep_path, meta=meta)
    if existing is not None:
        return existing
    return build_slot_prep(
        index,
        categories_cfg,
        dlc_pool_mode=dlc_pool_mode,
        npc_csv_dir=npc_csv_dir,
        out_path=prep_path,
        workers=workers,
        on_progress=on_progress,
    )


def prep_slots_for_map(
    prep: dict[str, Any],
    map_filter: str | None = None,
) -> list[dict[str, Any]]:
    rows = prep.get("slots") or []
    if not map_filter:
        return rows
    return [r for r in rows if str(r.get("m", "")) == map_filter]


def prep_donor_indices(
    prep: dict[str, Any],
    entry: dict[str, Any],
    tgt_cat: str,
    *,
    categories_cfg: dict[str, Any] | None = None,
    blocked_indices: frozenset[int] | None = None,
) -> list[int]:
    """Donor catalog indices for a prep row — no template dict materialization."""
    migrate_legacy_prep_row(entry)
    donors = prep.get("donors") or []
    ids = (entry.get("o") or {}).get(tgt_cat) or []
    if blocked_indices is not None:
        return [i for i in ids if 0 <= i < len(donors) and i not in blocked_indices]
    if not categories_cfg:
        return [i for i in ids if 0 <= i < len(donors)]
    core = _core()
    out: list[int] = []
    for i in ids:
        if i < 0 or i >= len(donors):
            continue
        model = str(donors[i].get("model", ""))
        if core.is_never_donor_hard_block_model(model, categories_cfg):
            continue
        if core.is_never_donor_model(model, categories_cfg):
            continue
        donor_rec = donors[i]
        if tgt_cat in core.BOSS_SOURCE_CATEGORIES and core.is_boss_pool_excluded_donor(
            donor_rec, categories_cfg
        ):
            continue
        if tgt_cat in core.BOSS_SOURCE_CATEGORIES and core.should_downgrade_shared_model_to_trash(
            {
                "model": model,
                "template_id": donor_rec.get("template_id", ""),
                "donor_entity": donor_rec.get("donor_entity", ""),
            },
            categories_cfg,
        ):
            continue
        if tgt_cat == "minor_boss" and not core.is_minor_boss_catalog_donor(
            donor_rec, categories_cfg
        ):
            continue
        out.append(i)
    return out


def blocked_donor_indices(
    prep: dict[str, Any],
    categories_cfg: dict[str, Any],
) -> frozenset[int]:
    """Precompute never_donor catalog rows once per generate (O(donors))."""
    from donor_pool_review_allowlist import is_allowlisted_donor_template

    core = _core()
    donors = prep.get("donors") or []
    blocked: set[int] = set()
    allowlist_on = bool(categories_cfg.get("donor_review_allowlist_enabled", False))
    for i, rec in enumerate(donors):
        allowlisted = allowlist_on and is_allowlisted_donor_template(
            rec, categories_cfg
        )
        model = str(rec.get("model", ""))
        if core.is_never_donor_hard_block_model(model, categories_cfg):
            blocked.add(i)
            continue
        if core.is_never_donor_model(model, categories_cfg) and not allowlisted:
            blocked.add(i)
    return frozenset(blocked)


def prep_donor_at(prep: dict[str, Any], index: int) -> dict[str, Any]:
    return _donor_expand((prep.get("donors") or [])[index])


def prep_pool_templates(
    prep: dict[str, Any],
    entry: dict[str, Any],
    tgt_cat: str,
) -> list[dict[str, Any]]:
    donors = prep.get("donors") or []
    ids = (entry.get("o") or {}).get(tgt_cat) or []
    return [_donor_expand(donors[i]) for i in ids if 0 <= i < len(donors)]
