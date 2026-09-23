"""Detect Elden Ring bosses via NpcParam proxies for bottom HP bar fights.

CNV csv export has no explicit displayBossHealthBar field. In practice bosses
carry spEffect 90400/95000/95010 (and often 5300/5360/5333) plus isSoulGetByBoss
on many story fights. Named humanoid bosses (Gideon-like) often have nameId>0
and hp>=1200 without isSoulGetByBoss.
"""
from __future__ import annotations

import csv
import json
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

_SCRIPTED_BOSS_ARENA_SLOT_RE = re.compile(r"^c\d{4}_9000$", re.IGNORECASE)
_CNV_NEW_NPC_RED_SPIRIT_NAME_RE = re.compile(r"New NPC #\d+", re.IGNORECASE)
_CNV_BOSS_NAME_TAG_RE = re.compile(r"\[Boss\]", re.IGNORECASE)
_CNV_TRAILING_BRACKET_RE = re.compile(r"\[([^\]]+)\]\s*$")
_CNV_SKIP_LOCATION_BRACKETS = frozenset(
    {
        "boss",
        "blob",
        "madness",
        "reprimand",
        "no scaling",
        "dagger",
        "spear",
        "bomb",
        "pot",
        "gs",
        "axe",
        "scythe",
        "staff",
        "bow/quiver",
        "caimar summon",
    }
)
_EVERGAOL_PRISONER_ENTITY_RE = re.compile(r"^c\d{4}_9\d+", re.IGNORECASE)
_EVERGAOL_PLACEHOLDER_MODEL_PREFIXES: tuple[str, ...] = ("c3010", "c3300", "c1000")

# SpEffects enriched on isSoulGetByBoss rows vs trash soldiers (empirical scan).
BOSS_BAR_SP_EFFECT_IDS: frozenset[int] = frozenset(
    {90400, 95000, 95010, 5300, 5360, 5333, 7040}
)

# Finger Reader 等可对话 NPC 的 spEffect 标记（NpcParam spEffectID*）。
DIALOGUE_NPC_SP_EFFECT_IDS: frozenset[int] = frozenset({10440, 10441})
# MSB 对话菜单事件（商人/任务 NPC 常见，talk 槽富集）。
DIALOGUE_MENU_SP_EFFECT_IDS: frozenset[int] = frozenset({9510})
# 命名任务 NPC 常见对话组合（90300+90060+90100，需配合 getSoul=0+nameId>0）。
DIALOGUE_NPC_SP_BUNDLE: frozenset[int] = frozenset({90300, 90060, 90100})
# CNV 剧情人形：托普斯/涅斐丽等，常 getSoul>0 仍带 ≥2 个对话 sp（真机扫 talk 槽）。
CNV_DIALOGUE_NPC_SP_CORE: frozenset[int] = frozenset({9630, 9634, 9642, 18699})

# Flying dragons + larger than typical field dragons (user: exclude from donor pool).
OVERSIZE_MODEL_PREFIXES: tuple[str, ...] = (
    "c4500",
    "c4501",
    "c4502",
    "c4503",
    "c4504",
    "c4505",
    "c4510",
    "c4520",
    "c4530",
    "c2200",
    "c4630",
    "c4800",
    "c4880",
    "c4920",
    "c4930",
    "c4940",
    "c3250",
    "c3251",
    "c5270",
    "c4710",
    "c5120",
    "c4911",
    "c5370",
    "c5580",
    "c5581",
    "c5661",
    "c5662",
)

# force_trash 野外巨型：体型表误标 small，洞窟 Boss 房会穿模/隐形（卢恩熊等）
DUNGEON_INCOMPATIBLE_FIELD_TRASH_PREFIXES: tuple[str, ...] = (
    "c4460",
    "c4480",
    "c4481",
    "c4482",
    "c4483",
    "c4550",
    "c4560",
    "c4561",
    "c4630",
)

# 路边蟹/虾；历史上误把 c227x 当封印监牢 Boss，现排除。
CRAB_MODEL_PREFIXES: tuple[str, ...] = (
    "c2270",
    "c2271",
    "c2272",
    "c2273",
    "c2274",
    "c2275",
    "c2276",
    "c2277",
    "c2278",
)
FIELD_BOSS_PREFIXES: tuple[str, ...] = (
    "c3150",
    "c3160",
    "c3171",
    "c4600",
    "c4601",
    "c4602",
    "c4604",
    "c4880",
    "c4241",
    "c4911",
    "c4720",
    "c4770",
    "c3250",
    "c3251",
)
MAJOR_BOSS_PREFIXES: tuple[str, ...] = (
    "c4750",
    "c4760",
    "c4730",
    "c4670",
    "c5110",
    "c5770",
    "c5130",
    "c5220",
    "c5120",
)
# 法魂具名/自定义 Boss 皮 → 7 池 cnv_special（非 2 池洞穴）
CNV_BOSS_PREFIXES: tuple[str, ...] = (
    "c3460",
    "c3570",
    "c4380",
    "c5800",
    "c5820",
    "c5840",
    "c5860",
    "c5870",
    "c5880",
    "c5900",
    "c5910",
    "c5920",
)
HUMANOID_BOSS_PREFIXES: tuple[str, ...] = (
    "c0000",
    "c1000",
    "c2010",
    "c2030",
    "c2031",
    "c3050",
    "c3100",
    "c3252",
    "c3664",
    "c5380",
)
DLC_BOSS_PREFIXES: tuple[str, ...] = tuple(
    f"c{prefix}"
    for prefix in (
        "5000",
        "5010",
        "5020",
        "5030",
        "5040",
        "5050",
        "5051",
        "5070",
        "5081",
        "5120",
        "5130",
        "5131",
        "5132",
        "5200",
        "5210",
        "5220",
        "5230",
        "5232",
        "5240",
        "5241",
        "5242",
        "5300",
        "5311",
        "5312",
        "5320",
        "5360",
        "5370",
        "5380",
        "5820",
        "5830",
        "5840",
        "5860",
    )
)

NPC_SP_COLS = [f"spEffectID{i}" for i in range(32)]


def _model_prefixes(model: str, prefixes: tuple[str, ...]) -> bool:
    model = (model or "").lower()
    return any(model.startswith(p) for p in prefixes)


def is_evergaol_placeholder_model(model: str) -> bool:
    """监牢囚犯槽 MSB 占位皮（非实战 Boss 外观）。"""
    m = (model or "").lower()
    return any(m.startswith(p) for p in _EVERGAOL_PLACEHOLDER_MODEL_PREFIXES)


def is_donor_template_record(entity: dict[str, Any]) -> bool:
    return bool(str(entity.get("template_id") or "").strip())


def evergaol_boss_model_prefixes(
    categories_cfg: dict[str, Any] | None,
) -> tuple[str, ...]:
    if categories_cfg:
        raw = categories_cfg.get("evergaol_boss_model_prefixes")
        if raw:
            return tuple(str(p).lower() for p in raw)
    return (
        "c2500",
        "c3010",
        "c4201",
        "c4290",
        "c3400",
        "c4650",
        "c3600",
        "c3704",
    )


def is_evergaol_boss_model(
    model: str, categories_cfg: dict[str, Any] | None = None
) -> bool:
    """封印监牢 Boss 白名单（熔炉/流放骑士/猎犬/墓影/祖玛英雄/黑剑之王/战斗法师等）。"""
    return _model_prefixes(model, evergaol_boss_model_prefixes(categories_cfg))


def evergaol_direct_prisoner_model_prefixes(
    categories_cfg: dict[str, Any] | None,
) -> tuple[str, ...]:
    if categories_cfg:
        raw = categories_cfg.get("evergaol_direct_prisoner_model_prefixes")
        if raw:
            return tuple(str(p).lower() for p in raw)
    return ("c7100",)


def is_evergaol_prisoner_slot_entity(
    entity: dict[str, Any],
    categories_cfg: dict[str, Any] | None = None,
    *,
    csv_dir: str | Path | None = None,
) -> bool:
    """MSB 囚犯槽实体名 c3010_9000 等；地上图常挂占位 model（如 c3300）。

    啜泣半岛萨米尔等用真 Boss 皮（c7100_9001 + model c7100），见
    evergaol_direct_prisoner_model_prefixes；须无巡逻、isSoulGetByBoss。
    """
    name = str(
        entity.get("name")
        or entity.get("donor_entity")
        or entity.get("template_id")
        or ""
    )
    if not name or not _EVERGAOL_PRISONER_ENTITY_RE.match(name):
        return False
    prefixes = evergaol_boss_model_prefixes(categories_cfg)
    lower = name.lower()
    if any(lower.startswith(f"{str(p).lower()}_9") for p in prefixes):
        return True
    m = re.match(r"^(c\d{4})_9", lower)
    if not m:
        return False
    prefix = m.group(1)
    direct_prefixes = evergaol_direct_prisoner_model_prefixes(categories_cfg)
    if prefix not in direct_prefixes:
        return False
    model = str(entity.get("model", "")).lower()
    if not model.startswith(prefix):
        return False
    if str(entity.get("walk_route") or "").strip():
        return False
    if csv_dir is None:
        return False
    try:
        npc_id = int(entity.get("npc", 0))
    except (TypeError, ValueError):
        return False
    if npc_id <= 0:
        return False
    row = load_npc_rows(csv_dir).get(npc_id)
    if not row:
        return False
    return int(row.get("isSoulGetByBoss") or 0) != 0


def force_trash_model_prefixes(
    categories_cfg: dict[str, Any] | None,
) -> tuple[str, ...]:
    if categories_cfg:
        raw = categories_cfg.get("force_trash_model_prefixes")
        if raw:
            return tuple(str(p).lower() for p in raw)
    return CRAB_MODEL_PREFIXES


def is_force_trash_model(
    model: str, categories_cfg: dict[str, Any] | None = None
) -> bool:
    """野外小怪：NpcParam 带 Boss 标记也保持 trash（米兰达/卢恩熊/火焰战车/蟹等）。"""
    return _model_prefixes(model, force_trash_model_prefixes(categories_cfg))


def is_dungeon_incompatible_field_trash_model(
    model: str, categories_cfg: dict[str, Any] | None = None
) -> bool:
    """洞窟/墓地 Boss 房禁贴：野外巨型 trash（体型表 small 但实体过大）。"""
    del categories_cfg
    return _model_prefixes(model, DUNGEON_INCOMPATIBLE_FIELD_TRASH_PREFIXES)


def red_spirit_model_prefixes(
    categories_cfg: dict[str, Any] | None,
) -> tuple[str, ...]:
    if categories_cfg:
        raw = categories_cfg.get("red_spirit_model_prefixes")
        if raw:
            return tuple(str(p).lower() for p in raw)
    return (
        "c0000",
        "c2010",
        "c2100",
        "c2030",
        "c2031",
        "c3100",
        "c3664",
        "c5380",
    )


def npc_name_is_cnv_new_red_spirit(name: str) -> bool:
    """法魂 Changelog 原创红灵：NpcParam Name 含 ``New NPC #N``。"""
    return bool(_CNV_NEW_NPC_RED_SPIRIT_NAME_RE.search(str(name or "").strip()))


def is_cnv_new_npc_red_spirit_npc(
    npc_id: int,
    csv_dir: str | Path,
) -> bool:
    row = load_npc_rows(csv_dir).get(int(npc_id))
    if not row:
        return False
    return npc_name_is_cnv_new_red_spirit(str(row.get("Name") or ""))


def template_is_cnv_new_npc_red_spirit(
    tpl: dict[str, Any],
    csv_dir: str | Path,
) -> bool:
    try:
        npc = int(tpl.get("npc", 0))
    except (TypeError, ValueError):
        return False
    if npc <= 0:
        return False
    return is_cnv_new_npc_red_spirit_npc(npc, csv_dir)


def npc_name_has_cnv_boss_tag(name: str) -> bool:
    """法魂具名 Boss：NpcParam Name 含 ``[Boss]``。"""
    return bool(_CNV_BOSS_NAME_TAG_RE.search(str(name or "").strip()))


def is_cnv_boss_tag_npc(
    npc_id: int,
    csv_dir: str | Path,
) -> bool:
    row = load_npc_rows(csv_dir).get(int(npc_id))
    if not row:
        return False
    return npc_name_has_cnv_boss_tag(str(row.get("Name") or ""))


def template_is_cnv_boss_tag_npc(
    tpl: dict[str, Any],
    csv_dir: str | Path,
) -> bool:
    try:
        npc = int(tpl.get("npc", 0))
    except (TypeError, ValueError):
        return False
    if npc <= 0:
        return False
    return is_cnv_boss_tag_npc(npc, csv_dir)


def _cnv_dungeon_bracket_label_ok(label: str) -> bool:
    low = str(label or "").strip().lower()
    if not low or low in _CNV_SKIP_LOCATION_BRACKETS:
        return False
    if low.startswith("tier "):
        return False
    return True


def npc_name_has_cnv_dungeon_boss_bracket(
    name: str,
    *,
    npc_row: dict[str, Any] | None = None,
) -> bool:
    """法魂改洞窟 Boss：名尾 ``[地名]``（如 ``[Cliffbottom Catacombs]``）。"""
    text = str(name or "").strip()
    if not text or _CNV_BOSS_NAME_TAG_RE.search(text):
        return False
    match = _CNV_TRAILING_BRACKET_RE.search(text)
    if not match:
        return False
    label = match.group(1)
    if not _cnv_dungeon_bracket_label_ok(label):
        return False
    if re.search(r"\bboss\b", text, re.IGNORECASE):
        return True
    if re.search(r"\bboss\b", label, re.IGNORECASE):
        return True
    if npc_row is not None and int(npc_row.get("isSoulGetByBoss") or 0) == 1:
        return True
    return False


def is_cnv_dungeon_boss_bracket_npc(
    npc_id: int,
    csv_dir: str | Path,
) -> bool:
    row = load_npc_rows(csv_dir).get(int(npc_id))
    if not row:
        return False
    return npc_name_has_cnv_dungeon_boss_bracket(
        str(row.get("Name") or ""),
        npc_row=row,
    )


def template_is_cnv_dungeon_boss_bracket_npc(
    tpl: dict[str, Any],
    csv_dir: str | Path,
) -> bool:
    try:
        npc = int(tpl.get("npc", 0))
    except (TypeError, ValueError):
        return False
    if npc <= 0:
        return False
    return is_cnv_dungeon_boss_bracket_npc(npc, csv_dir)


def template_is_cnv_pool7_marked_npc(
    tpl: dict[str, Any],
    csv_dir: str | Path,
) -> bool:
    """7 池 NpcParam 名标记：``[Boss]`` 或法魂改洞窟 ``[地名]``。"""
    return template_is_cnv_boss_tag_npc(
        tpl, csv_dir
    ) or template_is_cnv_dungeon_boss_bracket_npc(tpl, csv_dir)


def is_red_spirit_model(
    model: str, categories_cfg: dict[str, Any] | None = None
) -> bool:
    """5 池红灵：入侵人形 / 黑刀 / 铃珠猎人等。"""
    return _model_prefixes(model, red_spirit_model_prefixes(categories_cfg))


def is_red_spirit_combat_slot(
    slot: dict[str, Any],
    csv_dir: str | Path,
    categories_cfg: dict[str, Any] | None = None,
) -> bool:
    """战斗红灵 c0000 槽：getSoul>0，非对话/事件/装饰 — 豁免 exclude_slot_model。

    c0000 同时在 exclude_slot_model_prefixes（挡玩家皮/事件 NPC）；本函数识别仍应进 5 池的红灵。
    法魂 ``New NPC #`` 原创红灵可挂 c1000 等非 c0000 皮，按 NpcParam 名识别。
    """
    try:
        npc = int(slot.get("npc", 0))
    except (TypeError, ValueError):
        npc = 0
    if npc > 0 and is_cnv_new_npc_red_spirit_npc(npc, csv_dir):
        row = load_npc_rows(csv_dir).get(npc)
        if not row:
            return False
        if row_has_dialogue_event(row):
            return False
        if int(row.get("getSoul") or 0) <= 0:
            return False
        return True
    model = str(slot.get("model", "")).lower()
    if not model.startswith("c0000"):
        return False
    if not is_red_spirit_model(model, categories_cfg):
        return False
    try:
        npc = int(slot.get("npc", 0))
    except (TypeError, ValueError):
        return False
    if npc <= 0:
        return False
    row = load_npc_rows(csv_dir).get(npc)
    if not row:
        return False
    if row_has_dialogue_event(row):
        return False
    if int(row.get("getSoul") or 0) <= 0:
        return False
    return True


def is_crab_model(model: str, categories_cfg: dict[str, Any] | None = None) -> bool:
    del categories_cfg
    return _model_prefixes(model, CRAB_MODEL_PREFIXES)


def is_oversize_boss_model(model: str) -> bool:
    """Dragons and bosses larger than typical field dragons — skip as donors."""
    return _model_prefixes(model, OVERSIZE_MODEL_PREFIXES)


def _normalize_npc_csv_dir(csv_dir: str | Path) -> str:
    return str(Path(os.fspath(csv_dir)).resolve())


@lru_cache(maxsize=4)
def _load_npc_rows_cached(csv_dir_key: str) -> dict[int, dict[str, str]]:
    path = Path(csv_dir_key) / "NpcParam.csv"
    out: dict[int, dict[str, str]] = {}
    if not path.is_file():
        return out
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            raw = row.get("ID")
            if not raw:
                continue
            try:
                out[int(raw)] = row
            except ValueError:
                continue
    return out


def load_npc_rows(csv_dir: str | Path) -> dict[int, dict[str, str]]:
    """NpcParam 行表；缓存键统一 resolve 后的路径字符串（避免 Path/str 混用击穿 maxsize=1）。"""
    return _load_npc_rows_cached(_normalize_npc_csv_dir(csv_dir))


def detect_boss_npc_row(row: dict[str, str]) -> tuple[bool, str]:
    """Return (is_boss, reason_tag). Proxy for bottom HP bar boss fights."""
    try:
        if int(row.get("isSoulGetByBoss") or 0) == 1:
            return True, "isSoulGetByBoss"
    except (TypeError, ValueError):
        pass
    sp_ids: set[int] = set()
    for col in NPC_SP_COLS:
        try:
            val = int(row.get(col) or 0)
        except (TypeError, ValueError):
            val = 0
        if val > 0:
            sp_ids.add(val)
    hit = sp_ids & BOSS_BAR_SP_EFFECT_IDS
    if hit:
        return True, f"spEffect:{min(hit)}"
    try:
        hp = int(row.get("hp") or 0)
        name_id = int(row.get("nameId") or 0)
    except (TypeError, ValueError):
        hp = name_id = 0
    if name_id > 0 and hp >= 1200:
        return True, "nameId_hp"
    return False, ""


def _row_sp_effect_ids(row: dict[str, str]) -> set[int]:
    out: set[int] = set()
    for col in NPC_SP_COLS:
        try:
            val = int(row.get(col) or 0)
        except (TypeError, ValueError):
            val = 0
        if val > 0:
            out.add(val)
    return out


def _is_boss_fight_npc_row(row: dict[str, str]) -> bool:
    try:
        if int(row.get("isSoulGetByBoss") or 0) == 1:
            return True
    except (TypeError, ValueError):
        pass
    is_boss, why = detect_boss_npc_row(row)
    return bool(
        is_boss and (why == "isSoulGetByBoss" or str(why).startswith("spEffect:"))
    )


def row_has_dialogue_event(row: dict[str, str]) -> bool:
    """NpcParam 带对话/菜单事件 spEffect（商人、任务、CNV 同伴）。

    不依赖 getSoul=0：CNV 托普斯(523330020) 等 soul>0 仍带 9630+9634+9642+18699。
    与纯入侵红灵区分：后者多为 18690/9632 等，不含上述对话组合。
    """
    sp = _row_sp_effect_ids(row)
    if sp & DIALOGUE_NPC_SP_EFFECT_IDS:
        return True
    if sp & DIALOGUE_MENU_SP_EFFECT_IDS:
        return True
    if len(sp & CNV_DIALOGUE_NPC_SP_CORE) >= 2:
        return True
    try:
        soul = int(row.get("getSoul") or 0)
        name_id = int(row.get("nameId") or 0)
    except (TypeError, ValueError):
        return False
    if soul == 0 and name_id > 0 and DIALOGUE_NPC_SP_BUNDLE.issubset(sp):
        return True
    return False


def row_has_dialogue_sp(row: dict[str, str]) -> bool:
    """NpcParam 带可对话 spEffect（优先于命名兜底）。"""
    return row_has_dialogue_event(row)


def is_talk_npc_row(row: dict[str, str]) -> bool:
    """Dialogue / story NPC — slot must not be enemy-randomized."""
    try:
        soul = int(row.get("getSoul") or 0)
    except (TypeError, ValueError):
        soul = 0
    # 对话事件 sp（CNV 同伴 soul>0、商人 9510、指痕 10440 等）优先于 getSoul 门槛
    if row_has_dialogue_event(row):
        if _is_boss_fight_npc_row(row):
            return False
        return True
    # CNV 剧情 NPC 常带对话 SP 且 soul=0，但 isSoulGetByBoss=1（如罐灵 c2031）
    if soul == 0 and row_has_dialogue_sp(row):
        return True
    if _is_boss_fight_npc_row(row):
        return False
    if row_has_dialogue_sp(row):
        return True
    try:
        if int(row.get("getSoul") or 0) != 0:
            return False
        if int(row.get("nameId") or 0) <= 0:
            return False
    except (TypeError, ValueError):
        return False
    is_boss, why = detect_boss_npc_row(row)
    if is_boss and (why == "isSoulGetByBoss" or str(why).startswith("spEffect:")):
        return False
    return True


def is_talk_npc_id(npc_id: int, csv_dir: str | Path) -> bool:
    row = load_npc_rows(csv_dir).get(int(npc_id))
    if not row:
        return False
    return is_talk_npc_row(row)


def is_script_event_npc_slot(
    slot: dict[str, Any],
    csv_dir: str | Path,
    categories_cfg: dict[str, Any] | None = None,
) -> bool:
    """CNV 剧情/事件 MSB 槽：think>=5e8 且 (getSoul=0 或 对话事件 sp)。

    与战斗蹲姿贵族区分：后者 think 为正常 NpcThink（如 36600000）且常有 getSoul。
    红灵 c0000：有对话 sp 仍跳过；无对话 sp 且 getSoul>0 进 5 池。
    """
    try:
        think = int(slot.get("think", 0))
        npc = int(slot.get("npc", 0))
    except (TypeError, ValueError):
        return False
    if npc <= 0:
        return False
    think_min = int(
        (categories_cfg or {}).get("exclude_donor_think_min", 500_000_000) or 500_000_000
    )
    if think < think_min:
        return False
    row = load_npc_rows(csv_dir).get(npc)
    model = str(slot.get("model", "")).lower()
    if row:
        if row_has_dialogue_event(row):
            return True
        if categories_cfg and is_red_spirit_model(model, categories_cfg):
            if int(row.get("getSoul") or 0) > 0:
                return False
        if int(row.get("getSoul") or 0) != 0:
            return False
    elif categories_cfg and is_red_spirit_model(model, categories_cfg):
        return False
    return True


def is_boss_npc(npc_id: int, csv_dir: str | Path) -> bool:
    row = load_npc_rows(csv_dir).get(int(npc_id))
    if not row:
        return False
    ok, _ = detect_boss_npc_row(row)
    return ok


def classify_detected_boss(
    model: str,
    *,
    donor_map_id: str = "",
    categories_cfg: dict[str, Any] | None = None,
) -> str:
    """Assign detected boss template into categories 2-7 (not trash)."""
    model = (model or "").lower()
    if categories_cfg and is_red_spirit_model(model, categories_cfg):
        return "night"
    if categories_cfg and is_evergaol_boss_model(model, categories_cfg):
        return "evergaol"
    if _model_prefixes(model, MAJOR_BOSS_PREFIXES):
        return "major_boss"
    if _model_prefixes(model, CNV_BOSS_PREFIXES):
        return "cnv_special"
    if _model_prefixes(model, FIELD_BOSS_PREFIXES):
        return "evergaol"
    if _model_prefixes(model, DLC_BOSS_PREFIXES):
        return "minor_boss"
    if _model_prefixes(model, HUMANOID_BOSS_PREFIXES):
        return "minor_boss"
    if categories_cfg:
        tile_min = int(categories_cfg.get("dlc_map_tile_min", 50))
        parts = str(donor_map_id).split("_")
        if len(parts) >= 2:
            try:
                if int(parts[1]) >= tile_min:
                    return "minor_boss"
            except ValueError:
                pass
    return "minor_boss"


def template_is_detected_boss(
    tpl: dict[str, Any],
    *,
    csv_dir: str | Path,
    categories_cfg: dict[str, Any] | None = None,
) -> bool:
    model = str(tpl.get("model", ""))
    if is_oversize_boss_model(model):
        return False
    try:
        npc_id = int(tpl.get("npc", 0))
    except (TypeError, ValueError):
        return False
    if not is_boss_npc(npc_id, csv_dir):
        return False
    if categories_cfg:
        from enemy_randomizer_core import (
            is_never_donor_model,
            is_passive_animal_model,
        )

        if is_never_donor_model(model, categories_cfg):
            return False
        if is_passive_animal_model(model, categories_cfg):
            return False
    return True


_DUNGEON_ENTITY_TOKEN_RE = re.compile(r"^(c\d{4}_9\d+)", re.IGNORECASE)
_DUNGEON_BOSS_NAME_RE = re.compile(r"\bboss\b", re.IGNORECASE)


def is_dungeon_map_id(
    map_id: str, categories_cfg: dict[str, Any] | None = None
) -> bool:
    mid = str(map_id or "").lower()
    return any(mid.startswith(p) for p in dungeon_boss_map_id_prefixes(categories_cfg))


def slot_entity_token(raw_name: str) -> str:
    """MSB 显示名可能带后缀，如 ``c3370_9000 Ancestral Follower Shaman Boss``。"""
    raw = str(raw_name or "").strip()
    m = _DUNGEON_ENTITY_TOKEN_RE.match(raw)
    return m.group(1).lower() if m else raw.lower()


def is_dungeon_main_boss_slot_token(entity_token: str) -> bool:
    return bool(_SCRIPTED_BOSS_ARENA_SLOT_RE.match(entity_token))


def is_summon_clone_slot_token(entity_token: str) -> bool:
    """``c####_9001+`` 召唤/技能分身（非 ``_9000`` 主 Boss 战点）。"""
    token = slot_entity_token(entity_token)
    return bool(re.match(r"^c\d{4}_9\d{3}$", token, re.IGNORECASE)) and not is_dungeon_main_boss_slot_token(
        token
    )


def donor_template_entity_token(template: dict[str, Any]) -> str:
    """捐皮模板 MSB 实体名（``map:c####_9xxx`` 或 synthetic id）。"""
    tid = str(
        template.get("template_id")
        or template.get("donor_entity")
        or template.get("name")
        or ""
    )
    if ":" in tid:
        tid = tid.split(":", 1)[1]
    return slot_entity_token(tid)


def is_summon_clone_donor_template(
    template: dict[str, Any],
    categories_cfg: dict[str, Any] | None = None,
) -> bool:
    """技能/召唤捐皮：仅白名单 npc/模板（T-070）；禁止用 ``_9001+`` 后缀泛化。"""
    cfg = categories_cfg if isinstance(categories_cfg, dict) else {}
    try:
        donor_npc = int(template.get("npc", 0))
    except (TypeError, ValueError):
        donor_npc = 0
    npc_ids = cfg.get("summon_clone_trash_rune_npc_ids") or [21202056]
    try:
        whitelist = {int(x) for x in npc_ids}
    except (TypeError, ValueError):
        whitelist = {21202056}
    if donor_npc in whitelist:
        return True
    entity = donor_template_entity_token(template).lower()
    tokens = cfg.get("summon_clone_trash_rune_entity_tokens") or ["c2120_9001"]
    return entity in {str(t).lower() for t in tokens}


def is_indoor_dungeon_boss_arena_slot(
    slot: dict[str, Any],
    categories_cfg: dict[str, Any] | None = None,
) -> bool:
    """洞窟/墓地室内 ``c####_9000`` Boss 战点（T-069 兼容捐皮）。"""
    map_id = str(slot.get("map_id", ""))
    if not is_dungeon_map_id(map_id, categories_cfg):
        return False
    return is_dungeon_main_boss_slot_token(slot_entity_token(str(slot.get("name", ""))))


def indoor_dungeon_boss_arena_exclude_donor_prefixes(
    categories_cfg: dict[str, Any] | None = None,
) -> tuple[str, ...]:
    """室内终点战点禁捐皮（挂天花板/笼头等，真机隐形）。"""
    cfg = categories_cfg if isinstance(categories_cfg, dict) else {}
    raw = cfg.get("indoor_dungeon_boss_arena_exclude_donor_prefixes")
    if raw:
        return tuple(str(p).lower() for p in raw)
    return ("c4342", "c4470", "c5970")


def is_indoor_dungeon_boss_arena_exclude_donor(
    model: str,
    categories_cfg: dict[str, Any] | None = None,
) -> bool:
    return _model_prefixes(model, indoor_dungeon_boss_arena_exclude_donor_prefixes(categories_cfg))


def _dungeon_promote_high_soul_min(categories_cfg: dict[str, Any]) -> int:
    pol = categories_cfg.get("dungeon_source_slot_policy") or {}
    try:
        return int(pol.get("promote_9000_min_getSoul") or 500)
    except (TypeError, ValueError):
        return 500


@lru_cache(maxsize=128)
def _dungeon_singleton_boss_soul_token(csv_dir: str, map_id: str) -> str | None:
    """全图仅一条 bossSoul 槽时返回其 token（如兽人洞 ``c4640_9001``）。"""
    idx_path = Path(__file__).resolve().parent / "cache" / "enemy_index.json"
    if not idx_path.is_file():
        return None
    try:
        idx = json.loads(idx_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    rows = load_npc_rows(csv_dir)
    tokens: list[str] = []
    for slot in idx.get("slots") or []:
        if str(slot.get("map_id", "")) != map_id:
            continue
        try:
            npc = int(slot.get("npc", 0) or 0)
        except (TypeError, ValueError):
            continue
        row = rows.get(npc, {})
        if int(row.get("isSoulGetByBoss") or 0) != 1:
            continue
        tokens.append(slot_entity_token(str(slot.get("name", ""))))
    uniq = set(tokens)
    if len(uniq) == 1:
        return next(iter(uniq))
    return None


def is_dungeon_evergaol_boss_9000_slot(
    entity_token: str, model: str, categories_cfg: dict[str, Any]
) -> bool:
    """洞窟监牢主囚犯格：``c3010_9000`` / ``c4201_9000`` 等（模型在白名单且 token 为 ``_9000``）。

    ``promote_9000_boss_model_prefixes`` 里的守墓斗士/看门犬等是墓地雾门 Boss（2 池），
    虽在 evergaol 白名单，不得按洞窟监牢囚犯格归类。
    """
    if not is_dungeon_main_boss_slot_token(entity_token):
        return False
    if not is_evergaol_boss_model(model, categories_cfg):
        return False
    model_l = str(model or "").lower()
    if _is_dungeon_boss_9000_model(model_l, categories_cfg):
        return False
    prefixes = evergaol_boss_model_prefixes(categories_cfg)
    return any(model_l.startswith(str(p).lower()) for p in prefixes)


def _classify_dungeon_boss_slot(
    tpl: dict[str, Any],
    *,
    rules_category: str,
    csv_dir: str | Path,
    categories_cfg: dict[str, Any],
) -> str:
    model = str(tpl.get("model", ""))
    if is_red_spirit_model(model, categories_cfg):
        return "night"
    if (
        is_evergaol_boss_model(model, categories_cfg)
        and not _is_dungeon_boss_9000_model(model, categories_cfg)
    ):
        return "evergaol"
    if rules_category in ("major_boss", "cnv_special"):
        return rules_category
    if _is_dungeon_boss_9000_model(model, categories_cfg):
        return "minor_boss"
    donor_map = str(tpl.get("donor_map") or tpl.get("map_id") or "")
    return classify_detected_boss(
        model,
        donor_map_id=donor_map,
        categories_cfg=categories_cfg,
    )


def _dungeon_boss_9000_model_prefixes(
    categories_cfg: dict[str, Any],
) -> tuple[str, ...]:
    pol = categories_cfg.get("dungeon_source_slot_policy") or {}
    raw = pol.get("promote_9000_boss_model_prefixes") or []
    return tuple(str(p).lower() for p in raw)


def _is_dungeon_boss_9000_model(model: str, categories_cfg: dict[str, Any]) -> bool:
    model = (model or "").lower()
    return any(model.startswith(p) for p in _dungeon_boss_9000_model_prefixes(categories_cfg))


def resolve_dungeon_source_category(
    tpl: dict[str, Any],
    *,
    rules_category: str,
    csv_dir: str | Path,
    categories_cfg: dict[str, Any],
) -> str | None:
    """洞窟/墓地源槽收紧：仅真 Boss 战点升 2~7 池，其余一律 1 池 trash。

    特征（来自原 MSB + NpcParam 扫描）：
    - 主 Boss 格：实体 token 恰为 ``c####_9000``（``_9001+`` 为召唤/分身 → trash）
    - ``isSoulGetByBoss=1`` / major_boss 规则 / 监牢囚犯 / MSB 名含 Boss
    - 无 ``_9000`` bossSoul 时，允许单条 ``_9xxx``+bossSoul 兜底（如 ``c4640_9001``）
    """
    map_id = str(tpl.get("donor_map") or tpl.get("map_id") or "")
    if not is_dungeon_map_id(map_id, categories_cfg):
        return None

    raw_name = str(
        tpl.get("template_id") or tpl.get("name") or tpl.get("donor_entity") or ""
    )
    token = slot_entity_token(raw_name)
    model = str(tpl.get("model", ""))
    try:
        npc = int(tpl.get("npc", 0) or 0)
    except (TypeError, ValueError):
        npc = 0
    row = load_npc_rows(csv_dir).get(npc, {})
    boss_soul = int(row.get("isSoulGetByBoss") or 0) if row else 0
    try:
        get_soul = int(row.get("getSoul") or 0) if row else 0
    except (TypeError, ValueError):
        get_soul = 0
    boss_ok, boss_why = detect_boss_npc_row(row) if row else (False, "")

    if is_evergaol_prisoner_slot_entity(tpl, categories_cfg, csv_dir=csv_dir):
        if not (
            is_donor_template_record(tpl) and is_evergaol_placeholder_model(model)
        ):
            # 守墓斗士等墓地雾门 _9000 虽形如监牢囚犯格，走 2 池 minor_boss
            if not (
                is_dungeon_main_boss_slot_token(token)
                and _is_dungeon_boss_9000_model(model, categories_cfg)
            ):
                return "evergaol"

    if is_dungeon_main_boss_slot_token(token):
        if is_dungeon_evergaol_boss_9000_slot(token, model, categories_cfg):
            return "evergaol"
        if _DUNGEON_BOSS_NAME_RE.search(raw_name):
            return _classify_dungeon_boss_slot(
                tpl,
                rules_category=rules_category,
                csv_dir=csv_dir,
                categories_cfg=categories_cfg,
            )
        if boss_soul == 1:
            return _classify_dungeon_boss_slot(
                tpl,
                rules_category=rules_category,
                csv_dir=csv_dir,
                categories_cfg=categories_cfg,
            )
        if _is_dungeon_boss_9000_model(model, categories_cfg):
            return _classify_dungeon_boss_slot(
                tpl,
                rules_category=rules_category,
                csv_dir=csv_dir,
                categories_cfg=categories_cfg,
            )
        if rules_category in ("major_boss", "cnv_special"):
            return rules_category
        if (
            boss_ok
            and get_soul >= _dungeon_promote_high_soul_min(categories_cfg)
            and not is_force_trash_model(model, categories_cfg)
        ):
            return _classify_dungeon_boss_slot(
                tpl,
                rules_category=rules_category,
                csv_dir=csv_dir,
                categories_cfg=categories_cfg,
            )
        return "trash"

    # 非 _9000：全图仅一条 bossSoul 槽时兜底（如 ``c4640_9001``）
    singleton = _dungeon_singleton_boss_soul_token(str(csv_dir), map_id)
    if boss_soul == 1 and singleton and token == singleton:
        return _classify_dungeon_boss_slot(
            tpl,
            rules_category=rules_category,
            csv_dir=csv_dir,
            categories_cfg=categories_cfg,
        )
    return "trash"


def dungeon_boss_map_id_prefixes(
    categories_cfg: dict[str, Any] | None,
) -> tuple[str, ...]:
    """洞窟/墓地/英雄墓等：Boss 战点 _9000 槽位归类豁免 force_trash。"""
    if categories_cfg:
        raw = categories_cfg.get("dungeon_boss_map_id_prefixes")
        if raw:
            return tuple(str(p).lower() for p in raw)
    return ("m30_", "m31_", "m32_", "m35_")


def is_dungeon_boss_arena_slot_entity(
    tpl: dict[str, Any], categories_cfg: dict[str, Any] | None = None
) -> bool:
    """洞窟/墓地 MSB 里 c####_9000 战点实体（非捐皮模板行）。"""
    entity = str(
        tpl.get("template_id") or tpl.get("name") or tpl.get("donor_entity") or ""
    )
    if not _SCRIPTED_BOSS_ARENA_SLOT_RE.match(entity):
        return False
    map_id = str(tpl.get("donor_map") or tpl.get("map_id") or "").lower()
    return any(map_id.startswith(p) for p in dungeon_boss_map_id_prefixes(categories_cfg))


def force_trash_blocks_slot_categorization(
    tpl: dict[str, Any],
    model: str,
    *,
    categories_cfg: dict[str, Any],
    csv_dir: str | Path,
) -> bool:
    """force_trash 仅禁捐皮；洞窟源槽由 ``resolve_dungeon_source_category`` 单独处理。"""
    if is_dungeon_map_id(
        str(tpl.get("donor_map") or tpl.get("map_id") or ""), categories_cfg
    ):
        return False
    return is_force_trash_model(model, categories_cfg)


def should_downgrade_shared_model_to_trash(
    tpl: dict[str, Any], categories_cfg: dict[str, Any]
) -> bool:
    """同模分流：拉车山妖 vs 大树守卫(c4600) 等。"""
    model = str(tpl.get("model", "")).lower()
    prefixes = categories_cfg.get("shared_model_force_trash_unless_synthetic_prefixes") or []
    if not prefixes:
        return False
    if not any(model.startswith(str(p).lower()) for p in prefixes):
        return False
    tpl_id = str(tpl.get("template_id", ""))
    if tpl_id.startswith("synthetic:"):
        return False
    for key in ("name", "donor_entity", "template_id"):
        slot_name = str(tpl.get(key) or "")
        if _SCRIPTED_BOSS_ARENA_SLOT_RE.match(slot_name):
            return False
    return True


def resolve_template_category_with_boss_detect(
    tpl: dict[str, Any],
    *,
    rules_category: str,
    csv_dir: str | Path,
    categories_cfg: dict[str, Any],
) -> str:
    """If NpcParam says boss (long HP bar proxy), map into 2-7; else keep rules."""
    model = str(tpl.get("model", ""))
    if is_evergaol_prisoner_slot_entity(tpl, categories_cfg, csv_dir=csv_dir):
        if not (
            is_donor_template_record(tpl) and is_evergaol_placeholder_model(model)
        ):
            return "evergaol"
    if template_is_cnv_pool7_marked_npc(tpl, csv_dir):
        return "cnv_special"
    if template_is_cnv_new_npc_red_spirit(tpl, csv_dir):
        return "night"
    if force_trash_blocks_slot_categorization(
        tpl, model, categories_cfg=categories_cfg, csv_dir=csv_dir
    ):
        return "trash"
    if is_red_spirit_model(model, categories_cfg):
        return "night"
    if is_evergaol_boss_model(model, categories_cfg):
        return "evergaol"
    if rules_category != "trash":
        if should_downgrade_shared_model_to_trash(tpl, categories_cfg):
            return "trash"
        return rules_category
    if is_crab_model(model, categories_cfg):
        return rules_category
    if not template_is_detected_boss(tpl, csv_dir=csv_dir, categories_cfg=categories_cfg):
        return rules_category
    if should_downgrade_shared_model_to_trash(tpl, categories_cfg):
        return "trash"
    donor_map = str(tpl.get("donor_map") or "")
    if donor_map.endswith(".msb.dcx"):
        donor_map = donor_map.replace(".msb.dcx", "")
    tpl_id = str(tpl.get("template_id", ""))
    if ":" in tpl_id and not donor_map:
        donor_map = tpl_id.split(":", 1)[0]
    return classify_detected_boss(
        str(tpl.get("model", "")),
        donor_map_id=donor_map,
        categories_cfg=categories_cfg,
    )


def resolve_entity_category(
    entity: dict[str, Any],
    *,
    categories_cfg: dict[str, Any],
    csv_dir: str | Path,
    rules_category: str,
) -> str:
    """统一槽位/模板归类：监牢室内 Boss 优先，再 trash→Boss 检测。"""
    tpl = {
        "model": entity.get("model", ""),
        "npc": entity.get("npc", 0),
        "donor_map": entity.get("donor_map") or entity.get("map_id") or "",
        "template_id": entity.get("template_id") or entity.get("name") or "",
        "name": entity.get("name", ""),
        "donor_entity": entity.get("donor_entity") or entity.get("name") or "",
        "walk_route": entity.get("walk_route", ""),
    }
    dungeon_cat = resolve_dungeon_source_category(
        tpl,
        rules_category=rules_category,
        csv_dir=csv_dir,
        categories_cfg=categories_cfg,
    )
    if dungeon_cat is not None:
        return dungeon_cat
    return resolve_template_category_with_boss_detect(
        tpl,
        rules_category=rules_category,
        csv_dir=csv_dir,
        categories_cfg=categories_cfg,
    )
