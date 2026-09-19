# -*- coding: utf-8 -*-
"""分类开关物品池：离线 JSON 加载 + 按 GUI 分开开关滤池。"""
from __future__ import annotations

import json
from pathlib import Path

from paths import DONOR_POOL_CONTRACT_DIR, REPO_ROOT

DEFAULT_CATEGORY_SWITCH_POOL_PATH = (
    DONOR_POOL_CONTRACT_DIR / "分类开关物品池_当前.json"
)

# switch_key → 是否装备大类（否则道具大类）
EQUIP_SWITCH_KEYS = frozenset({"weapon", "armor", "magic"})
GOODS_SWITCH_KEYS = frozenset({"quest", "important", "upgrade", "craft"})


def resolve_category_switch_pool_path(cfg: dict | None = None) -> Path:
    raw = (cfg or {}).get("category_switch_pool_path")
    if raw:
        p = Path(raw)
        if not p.is_absolute():
            p = (REPO_ROOT / p).resolve()
        return p
    return DEFAULT_CATEGORY_SWITCH_POOL_PATH


def load_category_switch_pool(path: Path | None = None) -> dict:
    """加载离线池；缺表 / schema 不对则硬失败。"""
    p = path or DEFAULT_CATEGORY_SWITCH_POOL_PATH
    if not p.is_file():
        raise FileNotFoundError(
            f"分类开关物品池缺失：{p}；请先运行 "
            f"python _sync_category_switch_pool.py"
        )
    data = json.loads(p.read_text(encoding="utf-8"))
    ver = int(data.get("schema_version") or 0)
    if ver < 1:
        raise ValueError(f"分类开关物品池 schema_version 无效：{p}")
    items = data.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError(f"分类开关物品池 items 为空：{p}")
    for i, row in enumerate(items):
        if not isinstance(row, dict) or "item_id" not in row or "switch_key" not in row:
            raise ValueError(f"分类开关物品池第 {i} 行缺 item_id/switch_key：{p}")
    return data


def enabled_category_switch_keys(cfg: dict) -> set[str]:
    """当前 GUI 打开的分开开关（装备 + 道具大类）。"""
    from cnv_randomizer_core import CAT_ARMOR, CAT_MAGIC, CAT_WEAPON, NAME_TO_CAT

    on: set[str] = set()
    enabled_cats = cfg.get("enabled_cats")
    if enabled_cats is not None:
        if CAT_WEAPON in enabled_cats:
            on.add("weapon")
        if CAT_ARMOR in enabled_cats:
            on.add("armor")
        if CAT_MAGIC in enabled_cats:
            on.add("magic")
    else:
        cats = cfg.get("randomize_categories") or {}
        for key in EQUIP_SWITCH_KEYS:
            if cats.get(key):
                on.add(key)

    groups = cfg.get("enabled_goods_groups")
    if groups is None:
        raw = cfg.get("randomize_goods_groups") or {}
        groups = {gid for gid, v in raw.items() if v}
    for gid in GOODS_SWITCH_KEYS:
        if gid in groups:
            on.add(gid)
    return on


def apply_category_switch_pool_to_cfg(cfg: dict, path: Path | None = None) -> Path:
    """写入 cfg 池字段；返回实际路径。"""
    p = path or resolve_category_switch_pool_path(cfg)
    data = load_category_switch_pool(p)
    items = data["items"]
    by_id: dict[int, list[str]] = {}
    for row in items:
        iid = int(row["item_id"])
        by_id.setdefault(iid, []).append(str(row["switch_key"]))
    cfg["category_switch_pool_path"] = str(p)
    cfg["category_switch_items"] = items
    cfg["category_switch_by_id"] = by_id
    cfg["category_switch_all_ids"] = set(by_id.keys())
    return p


def build_pool_from_category_switch(cfg: dict) -> set[int]:
    """表内 ∩ 开关为开 − exclude − DLC 挡。"""
    from pickup_pool import item_allowed_by_dlc

    items = cfg.get("category_switch_items")
    if items is None:
        raise RuntimeError(
            "category_switch_items 未加载；run_randomize 须先 "
            "apply_category_switch_pool_to_cfg"
        )
    on = enabled_category_switch_keys(cfg)
    exclude = cfg.get("exclude_item_ids", set())
    dlc_ranges = cfg.get("dlc_ranges", [])
    pool: set[int] = set()
    for row in items:
        if str(row.get("switch_key")) not in on:
            continue
        iid = int(row["item_id"])
        if iid <= 0 or iid in exclude:
            continue
        if not item_allowed_by_dlc(iid, cfg, dlc_ranges):
            continue
        pool.add(iid)
    return pool
