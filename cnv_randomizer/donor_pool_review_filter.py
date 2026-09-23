"""捐皮审阅表过滤规则（测试 Dummy、鹿、商人、对话Npc、审阅手工剔除等）。"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from boss_npc_detect import is_talk_npc_id
from paths import GAME_DIR

from paths import SCRIPT_DIR as _SCRIPT_DIR  # frozen-safe
_MANUAL_EXCLUDES_PATH = _SCRIPT_DIR / "donor_pool_review_manual_excludes.json"
_NPC_CSV_DIR = GAME_DIR / "csv"
# 纯测试壳 model（整模排除）
TEST_SHELL_MODEL_PREFIXES: tuple[str, ...] = (
    "c0100",
    "c0110",
    "c0130",
    "c8001",
    "c8002",
    "c8003",
    "c8004",
    "c8099",
)

# NpcParam Name / 实体名命中即排除（大小写不敏感子串）
_TEST_NAME_MARKERS: tuple[str, ...] = ("dummy",)

# 精确匹配（CNV 联机/赐福测试壳，非战斗捐皮）
_TEST_NPC_NAMES_EXACT: frozenset[str] = frozenset(
    {
        "BuddyStone",
        "Bonfire",
    }
)

# 被动鹿（c6010 及同名 Npc）
DEER_MODEL_PREFIXES: tuple[str, ...] = ("c6010",)

# 小螃蟹（c2271）及 c2270 低血量变体
SMALL_CRAB_MODEL_PREFIXES: tuple[str, ...] = ("c2271",)
# c2270「大螃蟹」里有效 HP 低于此值视为小螃蟹（如 misc 第 3 行 npc 22700000=357）
SMALL_CRAB_C2270_MAX_EFFECTIVE_HP = 600

# 商人 / 驴 / 洞窟游牧商（c320x）
MERCHANT_MODEL_PREFIXES: tuple[str, ...] = (
    "c3200",
    "c3201",
    "c3210",
)

_MERCHANT_NAME_EN_MARKERS: tuple[str, ...] = (
    "merchant",
    "nomad trader",
    "frenzied nomad",
)

_CATEGORIES_PATH = _SCRIPT_DIR / "enemy_categories.json"

_HORSE_NAME_EN_MARKERS: tuple[str, ...] = (
    " horse",
    " steed",
    "knight's horse",
    "sellsword horse",
    "black knight horse",
)

_HORSE_NAME_ZH_MARKERS: tuple[str, ...] = ("战马", "灵马", "的马")


@lru_cache(maxsize=1)
def _horse_mount_review_prefixes() -> frozenset[str]:
    """独立战马 model（`horse_mount_model_prefixes`；不含成套骑手）。"""
    if not _CATEGORIES_PATH.is_file():
        return frozenset()
    data = json.loads(_CATEGORIES_PATH.read_text(encoding="utf-8"))
    return frozenset(
        str(p).lower() for p in (data.get("horse_mount_model_prefixes") or [])
    )


def test_dummy_exclude_reason(row: dict[str, Any]) -> str:
    """若应排除则返回原因文案；否则返回空串。"""
    model = str(row.get("model") or "").lower()
    name_en = str(row.get("name_en") or "").strip()
    name_l = name_en.lower()
    entity = str(row.get("donor_entity") or "").strip()
    entity_l = entity.lower()

    for prefix in TEST_SHELL_MODEL_PREFIXES:
        if model.startswith(prefix):
            return f"测试模型 {prefix}"

    if name_en in _TEST_NPC_NAMES_EXACT:
        return f"测试Npc {name_en}"

    for marker in _TEST_NAME_MARKERS:
        if marker in name_l:
            return "Npc名含 Dummy"
        if marker in entity_l:
            return "实体名含 Dummy"

    return ""


def deer_exclude_reason(row: dict[str, Any]) -> str:
    if _is_deer_row(row):
        return "被动动物·鹿"
    return ""


def _is_deer_row(row: dict[str, Any]) -> bool:
    model = str(row.get("model") or "").lower()
    name_en = str(row.get("name_en") or "").strip()
    name_zh = str(row.get("name_zh") or "").strip()
    if model.startswith("c6010"):
        return True
    return name_en == "Deer" or name_zh == "鹿"


def _parse_effective_hp(row: dict[str, Any]) -> float | None:
    raw = row.get("effective_hp")
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def small_critter_exclude_reason(row: dict[str, Any]) -> str:
    """小螃蟹等小动物：c2271 · 或 c2270 有效 HP 明显偏低。"""
    model = str(row.get("model") or "").lower()

    for prefix in SMALL_CRAB_MODEL_PREFIXES:
        if model.startswith(prefix):
            return "小动物·小螃蟹"

    if model.startswith("c2270"):
        hp = _parse_effective_hp(row)
        if hp is not None and 0 < hp < SMALL_CRAB_C2270_MAX_EFFECTIVE_HP:
            return "小动物·小螃蟹"

    return ""


@lru_cache(maxsize=1)
def _passive_animal_review_prefixes() -> frozenset[str]:
    """被动小动物 model（`passive_animal_model_prefixes`）。"""
    if not _CATEGORIES_PATH.is_file():
        return frozenset()
    data = json.loads(_CATEGORIES_PATH.read_text(encoding="utf-8"))
    return frozenset(
        str(p).lower() for p in (data.get("passive_animal_model_prefixes") or [])
    )


_PASSIVE_ANIMAL_NAME_EN_MARKERS: tuple[str, ...] = (
    "eagle",
    "owl",
    "boar",
    "goat",
    "murre",
    "dragonfly",
    "springhare",
    "squirrel",
    "rabbit",
    "sheep",
)
_PASSIVE_ANIMAL_NAME_ZH_MARKERS: tuple[str, ...] = (
    "鹰",
    "猫头鹰",
    "野猪",
    "山羊",
    "海雀",
    "蜻蜓",
    "小动物",
)


def passive_animal_exclude_reason(row: dict[str, Any]) -> str:
    """被动小动物：槽位原位、全池禁捐（与运行时 passive_animal 口径一致）。"""
    model = str(row.get("model") or "").lower()
    for prefix in _passive_animal_review_prefixes():
        if prefix == "c6010":
            continue
        if model.startswith(prefix):
            return "小动物·被动动物"

    name_en = str(row.get("name_en") or "").lower()
    name_zh = str(row.get("name_zh") or "").strip()
    if name_en == "deer" or name_zh == "鹿":
        return "被动动物·鹿"
    for marker in _PASSIVE_ANIMAL_NAME_EN_MARKERS:
        if marker in name_en:
            return "小动物·被动动物"
    for marker in _PASSIVE_ANIMAL_NAME_ZH_MARKERS:
        if marker in name_zh and "猪人" not in name_zh:
            return "小动物·被动动物"
    return ""


def merchant_exclude_reason(row: dict[str, Any]) -> str:
    model = str(row.get("model") or "").lower()
    name_en = str(row.get("name_en") or "").strip()
    name_l = name_en.lower()
    name_zh = str(row.get("name_zh") or "").strip()

    for prefix in MERCHANT_MODEL_PREFIXES:
        if model.startswith(prefix):
            return f"商人模型 {prefix}"

    for marker in _MERCHANT_NAME_EN_MARKERS:
        if marker in name_l:
            return "商人Npc"

    if "商人" in name_zh or "流浪商" in name_zh:
        return "商人Npc"

    return ""


@lru_cache(maxsize=1)
def _scarab_review_prefixes() -> frozenset[str]:
    """圣甲虫 model（`scarab_model_prefixes`）。"""
    if not _CATEGORIES_PATH.is_file():
        return frozenset({"c4190", "c4191", "c4192", "c6201"})
    data = json.loads(_CATEGORIES_PATH.read_text(encoding="utf-8"))
    raw = data.get("scarab_model_prefixes") or []
    return frozenset(str(p).lower() for p in raw)


_SCARAB_NAME_EN_MARKERS: tuple[str, ...] = ("scarab",)
_SCARAB_NAME_ZH_MARKERS: tuple[str, ...] = ("圣甲虫",)


def scarab_exclude_reason(row: dict[str, Any]) -> str:
    """圣甲虫：槽位原位、全池禁捐。"""
    model = str(row.get("model") or "").lower()
    for prefix in _scarab_review_prefixes():
        if model.startswith(prefix):
            return "圣甲虫"

    name_en = str(row.get("name_en") or "").lower()
    name_zh = str(row.get("name_zh") or "").strip()
    for marker in _SCARAB_NAME_EN_MARKERS:
        if marker in name_en:
            return "圣甲虫"
    for marker in _SCARAB_NAME_ZH_MARKERS:
        if marker in name_zh:
            return "圣甲虫"
    return ""


@lru_cache(maxsize=1)
def _mausoleum_review_prefixes() -> frozenset[str]:
    """漫步灵庙 model（`mausoleum_model_prefixes`）。"""
    if not _CATEGORIES_PATH.is_file():
        return frozenset({"c4450"})
    data = json.loads(_CATEGORIES_PATH.read_text(encoding="utf-8"))
    raw = data.get("mausoleum_model_prefixes") or []
    return frozenset(str(p).lower() for p in raw)


_MAUSOLEUM_NAME_EN_MARKERS: tuple[str, ...] = ("walking mausoleum",)
_MAUSOLEUM_NAME_ZH_MARKERS: tuple[str, ...] = ("漫步灵庙",)


@lru_cache(maxsize=1)
def _decorative_corpse_review_prefixes() -> frozenset[str]:
    """装饰尸体 model（`decorative_corpse_model_prefixes`）。"""
    if not _CATEGORIES_PATH.is_file():
        return frozenset({"c3661", "c3662", "c4711"})
    data = json.loads(_CATEGORIES_PATH.read_text(encoding="utf-8"))
    raw = data.get("decorative_corpse_model_prefixes") or []
    return frozenset(str(p).lower() for p in raw)


_DECORATIVE_CORPSE_NAME_EN_MARKERS: tuple[str, ...] = (
    "putrid corpse",
    "rykard's corpse",
    "corpse ghost",
    "scholar - caria manor",
)
_DECORATIVE_CORPSE_NAME_ZH_MARKERS: tuple[str, ...] = (
    "腐败遗体",
    "拉卡德的尸体",
    "装饰尸体",
)


def decorative_corpse_exclude_reason(row: dict[str, Any]) -> str:
    """装饰尸体：槽位原位、全池禁捐（不能互动/非战斗）。"""
    model = str(row.get("model") or "").lower()
    for prefix in _decorative_corpse_review_prefixes():
        if model.startswith(prefix):
            return "装饰尸体"

    name_en = str(row.get("name_en") or "").lower()
    name_zh = str(row.get("name_zh") or "").strip()
    for marker in _DECORATIVE_CORPSE_NAME_EN_MARKERS:
        if marker in name_en:
            return "装饰尸体"
    for marker in _DECORATIVE_CORPSE_NAME_ZH_MARKERS:
        if marker in name_zh:
            return "装饰尸体"
    return ""


def mausoleum_exclude_reason(row: dict[str, Any]) -> str:
    """漫步灵庙：槽位原位、全池禁捐（不含灵庙士兵/骑士）。"""
    model = str(row.get("model") or "").lower()
    for prefix in _mausoleum_review_prefixes():
        if model.startswith(prefix):
            return "漫步灵庙"

    name_en = str(row.get("name_en") or "").lower()
    name_zh = str(row.get("name_zh") or "").strip()
    for marker in _MAUSOLEUM_NAME_EN_MARKERS:
        if marker in name_en:
            return "漫步灵庙"
    for marker in _MAUSOLEUM_NAME_ZH_MARKERS:
        if name_zh == marker or name_zh.startswith(marker):
            return "漫步灵庙"
    return ""


def horse_mount_exclude_reason(row: dict[str, Any]) -> str:
    """独立战马（不作捐皮审阅；成套骑手保留）。"""
    model = str(row.get("model") or "").lower()
    for prefix in _horse_mount_review_prefixes():
        if model.startswith(prefix):
            return "独立战马"

    name_en = str(row.get("name_en") or "").lower()
    name_zh = str(row.get("name_zh") or "").strip()
    for marker in _HORSE_NAME_EN_MARKERS:
        if marker in name_en:
            return "独立战马"
    for marker in _HORSE_NAME_ZH_MARKERS:
        if marker in name_zh:
            return "独立战马"
    return ""


def talk_npc_exclude_reason(row: dict[str, Any]) -> str:
    """剧情/对话 Npc（与运行时 talk_npc 跳过口径一致；葛托克 MSB 变体名兜底）。

    审阅白名单显式收录者可作捐皮（槽位仍 skip）；勿再按 talk 剔除。
    """
    name_en = str(row.get("name_en") or "").strip()
    name_zh = str(row.get("name_zh") or "").strip()
    if name_en == "Gatekeeper Gostoc" or name_zh == "门卫葛托克":
        return "剧情对话Npc"

    npc_raw = str(row.get("npc") or "").strip()
    if not npc_raw:
        return ""
    try:
        npc = int(npc_raw)
    except (TypeError, ValueError):
        return ""
    if npc <= 0:
        return ""
    from donor_pool_review_allowlist import donor_category_for_npc

    if donor_category_for_npc(npc) is not None:
        return ""
    if not _NPC_CSV_DIR.is_dir():
        return ""
    if is_talk_npc_id(npc, _NPC_CSV_DIR):
        return "剧情对话Npc"
    return ""


@lru_cache(maxsize=1)
def _manual_exclude_by_npc() -> dict[str, str]:
    out: dict[str, str] = {}
    if not _MANUAL_EXCLUDES_PATH.is_file():
        return out
    payload = json.loads(_MANUAL_EXCLUDES_PATH.read_text(encoding="utf-8"))
    for batch in payload.get("batches") or []:
        reason = str(batch.get("reason") or "审阅手工剔除").strip()
        for npc_id in batch.get("npc_ids") or []:
            out[str(npc_id).strip()] = reason
    return out


def manual_review_exclude_reason(row: dict[str, Any]) -> str:
    from donor_pool_review_allowlist import load_manual_includes

    npc_raw = str(row.get("npc") or "").strip()
    if not npc_raw:
        return ""
    try:
        npc = int(npc_raw)
    except (TypeError, ValueError):
        return ""
    _, overrides = load_manual_includes()
    if npc in overrides:
        return ""
    return _manual_exclude_by_npc().get(npc_raw, "")


def donor_review_exclude_reason(row: dict[str, Any]) -> str:
    """统一排除入口：测试壳 → 鹿 → 小螃蟹 → 被动小动物 → 商人 → 圣甲虫 → 灵庙 → 装饰尸体 → 战马 → 对话Npc → 审阅手工。"""
    for fn in (
        test_dummy_exclude_reason,
        deer_exclude_reason,
        small_critter_exclude_reason,
        passive_animal_exclude_reason,
        merchant_exclude_reason,
        scarab_exclude_reason,
        mausoleum_exclude_reason,
        decorative_corpse_exclude_reason,
        horse_mount_exclude_reason,
        talk_npc_exclude_reason,
        manual_review_exclude_reason,
    ):
        reason = fn(row)
        if reason:
            return reason
    return ""


def exclude_bucket(reason: str) -> str:
    """排除清单分文件：dummy / deer / critter / merchant / horse / talk / manual。"""
    if reason.startswith("审阅剔除"):
        return "manual"
    if reason == "剧情对话Npc" or "对话Npc" in reason:
        return "talk"
    if "独立战马" in reason:
        return "horse"
    if reason == "圣甲虫" or "圣甲虫" in reason:
        return "scarab"
    if reason == "漫步灵庙":
        return "mausoleum"
    if reason == "装饰尸体" or "尸体" in reason:
        return "corpse"
    if "小动物" in reason or "小螃蟹" in reason:
        return "critter"
    if "鹿" in reason:
        return "deer"
    if "商人" in reason:
        return "merchant"
    return "dummy"


def is_test_dummy_review_row(row: dict[str, Any]) -> bool:
    return bool(test_dummy_exclude_reason(row))


def split_review_rows(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    kept: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for row in rows:
        reason = donor_review_exclude_reason(row)
        if reason:
            excluded.append(
                {
                    **row,
                    "exclude_reason": reason,
                    "exclude_bucket": exclude_bucket(reason),
                }
            )
        else:
            kept.append(row)
    return kept, excluded


_NPC_ROWS_BY_CSV: dict[str, dict[int, dict[str, str]]] = {}


def _npc_rows_for(csv_dir: Path) -> dict[int, dict[str, str]]:
    key = str(csv_dir.resolve())
    cached = _NPC_ROWS_BY_CSV.get(key)
    if cached is not None:
        return cached
    if not csv_dir.is_dir():
        _NPC_ROWS_BY_CSV[key] = {}
        return {}
    from boss_npc_detect import load_npc_rows

    rows = load_npc_rows(csv_dir)
    _NPC_ROWS_BY_CSV[key] = rows
    return rows


def template_to_review_row(
    tpl: dict[str, Any],
    *,
    csv_dir: Path | None = None,
) -> dict[str, Any]:
    """运行时 template → 审阅行（与 `_build_donor_pool_tables_1_7` 口径对齐）。"""
    model = str(tpl.get("model") or "")
    donor_entity = str(tpl.get("donor_entity") or tpl.get("template_id") or "")
    try:
        npc = int(tpl.get("npc", 0) or 0)
    except (TypeError, ValueError):
        npc = 0
    name_en = ""
    effective_hp = 0
    if npc > 0 and csv_dir is not None:
        npc_row = _npc_rows_for(csv_dir).get(npc)
        if npc_row:
            name_en = str(npc_row.get("Name") or "").strip()
            from dlc_donor_pool import combat_hp_detailed, load_sp_hp_rates

            eff, _, _ = combat_hp_detailed(npc_row, load_sp_hp_rates(str(csv_dir)))
            effective_hp = eff
    return {
        "model": model,
        "npc": npc,
        "name_en": name_en,
        "name_zh": "",
        "donor_entity": donor_entity,
        "effective_hp": effective_hp,
    }


def is_donor_review_excluded_template(
    tpl: dict[str, Any],
    *,
    categories_cfg: dict[str, Any] | None = None,
    csv_dir: Path | None = None,
) -> bool:
    """筛选后捐皮审阅表口径：True = 不进 prep compat 池。"""
    if categories_cfg is not None and not categories_cfg.get(
        "donor_review_filter_enabled", False
    ):
        return False
    base = csv_dir if csv_dir is not None else _NPC_CSV_DIR
    return bool(donor_review_exclude_reason(template_to_review_row(tpl, csv_dir=base)))
