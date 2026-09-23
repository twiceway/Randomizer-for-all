"""T-084 B3 — rune / soul reward helpers (extracted from enemy_randomizer_core)."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from boss_npc_detect import is_red_spirit_model, is_summon_clone_donor_template
from paths import GAME_DIR

def red_spirit_rune_tier_only(
    tgt_cat: str,
    donor_model: str,
    categories_cfg: dict[str, Any] | None = None,
) -> bool:
    from enemy_randomizer_core import RUNE_TIER_CAP_RED_SPIRIT_TGT, TRASH_LIKE_TARGET_CATEGORIES
    """红灵卢恩对齐 minor_boss 阶梯，废止捐皮 engine getSoul / GameArea。"""
    tgt = str(tgt_cat or "")
    if tgt == "night":
        return True
    model = str(donor_model or "")
    if not is_red_spirit_model(model, categories_cfg):
        return False
    if tgt in RUNE_TIER_CAP_RED_SPIRIT_TGT:
        return True
    # 红灵皮落在路边/精英槽仍按 minor_boss 发钱（契约 §击杀卢恩 · 红灵捐皮）
    return tgt in TRASH_LIKE_TARGET_CATEGORIES or tgt == "elite"


NPC_SOUL_CACHE: dict[int, int] | None = None


GAMEAREA_SOUL_CACHE: tuple[dict[int, int], dict[str, int]] | None = None


def load_npc_soul_map(csv_dir: Path | None = None) -> dict[int, int]:
    """NpcParam.getSoul — donor default rune reward."""
    global NPC_SOUL_CACHE
    if NPC_SOUL_CACHE is not None:
        return NPC_SOUL_CACHE
    base = Path(csv_dir) if csv_dir else (GAME_DIR / "csv")
    path = base / "NpcParam.csv"
    souls: dict[int, int] = {}
    if not path.is_file():
        NPC_SOUL_CACHE = souls
        return souls
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            raw_id = row.get("ID")
            if not raw_id:
                continue
            try:
                npc_id = int(raw_id)
                souls[npc_id] = int(row.get("getSoul") or 0)
            except (TypeError, ValueError):
                continue
    NPC_SOUL_CACHE = souls
    return souls


def load_gamearea_soul_maps(
    path: Path | None = None,
) -> tuple[dict[int, int], dict[str, int]]:
    """getSoul=0 反查表：npc / model → GameAreaParam.bonusSoul_single。"""
    from enemy_randomizer_core import DEFAULT_GAMEAREA_SOULS_PATH
    global GAMEAREA_SOUL_CACHE
    if GAMEAREA_SOUL_CACHE is not None:
        return GAMEAREA_SOUL_CACHE
    src = Path(path) if path else DEFAULT_GAMEAREA_SOULS_PATH
    by_npc: dict[int, int] = {}
    by_model: dict[str, int] = {}
    if src.is_file():
        try:
            raw = json.loads(src.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = {}
        for k, row in (raw.get("by_npc") or {}).items():
            try:
                bonus = int((row or {}).get("bonus_soul") or 0)
                if bonus > 0:
                    by_npc[int(k)] = bonus
            except (TypeError, ValueError):
                continue
        for k, row in (raw.get("by_model") or {}).items():
            try:
                bonus = int((row or {}).get("bonus_soul") or 0)
                if bonus > 0:
                    by_model[str(k)] = bonus
            except (TypeError, ValueError):
                continue
    GAMEAREA_SOUL_CACHE = (by_npc, by_model)
    return GAMEAREA_SOUL_CACHE


def resolve_gamearea_soul(
    *,
    npc: int,
    model: str,
    by_npc: dict[int, int],
    by_model: dict[str, int],
) -> int:
    if npc and npc in by_npc:
        return int(by_npc[npc])
    model_key = str(model or "").strip()
    if model_key and model_key in by_model:
        return int(by_model[model_key])
    if len(model_key) >= 5:
        prefix = model_key[:5]
        if prefix in by_model:
            return int(by_model[prefix])
    return 0


def normalize_mob_drop_mode(mode: str | None, *, keep_original_drops: bool | None = None) -> str:
    if mode in ("keep_original", "donor_default"):
        return mode
    if mode == "rune_by_difficulty":
        return "donor_default"
    if keep_original_drops is False:
        return "donor_default"
    return "keep_original"


def apply_radahn_phase1_think(
    row: dict[str, Any],
    slot: dict[str, Any],
    categories_cfg: dict[str, Any],
) -> None:
    """Mark Starscourge Radahn donors; use landed NpcParam (47300041) via synthetic template.

    AI meteor Act13 is still neutered on shared ``473000_battle`` as a safety net.
    Landed donor spawns with phase-2 spEffects so roadside/evergaol should not fly away.
    """
    _ = slot
    model = str(row.get("model") or "").lower()
    if not model.startswith("c4730"):
        return
    row["radahn_phase1"] = True
    row["radahn_landed"] = True
    think_id = int(categories_cfg.get("radahn_phase1_think_id", 47300000) or 47300000)
    row["think"] = think_id
    landed_npc = int(categories_cfg.get("radahn_landed_npc_id", 47300041) or 47300041)
    try:
        if int(row.get("npc") or 0) == 47300040:
            row["npc"] = landed_npc
    except (TypeError, ValueError):
        pass


def apply_rune_map_scaling(amount: int, map_id: str) -> int:
    """× 落点图 tier；卢恩增幅指数高于血量（见 enemy_difficulty.rune_over_difficulty_power）。"""
    from enemy_difficulty import scale_rune_by_slot_tier

    if map_id:
        amount = scale_rune_by_slot_tier(amount, map_id)
    return max(0, int(amount))


def tier_baseline_rune_amount(
    reward_cat: str,
    rune_tiers: dict[str, int],
    map_id: str = "",
    *,
    apply_map_scale: bool = True,
) -> int:
    """by_category[tgt_cat]；T-058 起 HP 平衡池可跳过地图卢恩倍率。"""
    amount = int(rune_tiers.get(reward_cat, rune_tiers.get("trash", 0)))
    if apply_map_scale:
        return apply_rune_map_scaling(amount, map_id)
    return max(0, int(amount))


def raw_donor_rune_soul(
    *,
    npc: int,
    model: str,
    reward_cat: str,
    allow_gamearea: bool,
    soul_map: dict[int, int],
    gamearea_by_npc: dict[int, int],
    gamearea_by_model: dict[str, int],
) -> int:
    """Donor NpcParam.getSoul, optionally GameArea when Boss-class tgt and soul=0."""
    soul = int(soul_map.get(npc, 0)) if npc else 0
    if soul <= 0 and allow_gamearea and _rune_allows_gamearea(reward_cat):
        soul = resolve_gamearea_soul(
            npc=npc,
            model=model,
            by_npc=gamearea_by_npc,
            by_model=gamearea_by_model,
        )
    return max(0, int(soul))


def _rune_allows_gamearea(cat: str) -> bool:
    """Fog GameArea bonuses only for real boss categories (not trash skins)."""
    from enemy_randomizer_core import BOSS_SOURCE_CATEGORIES
    return cat in BOSS_SOURCE_CATEGORIES


def lookup_rune_amount(
    *,
    mob_drop_mode: str,
    slot: dict[str, Any],
    template: dict[str, Any],
    src_cat: str,
    tgt_cat: str,
    rune_tiers: dict[str, int],
    soul_map: dict[int, int],
    gamearea_by_npc: dict[int, int] | None = None,
    gamearea_by_model: dict[str, int] | None = None,
    keep_original_multiplier: int = 1,
    categories_cfg: dict[str, Any] | None = None,
    map_id: str = "",
) -> int:
    """Bake kill-rune amount for spawn_map.

    用户口径（2026-07-29）：按**随机后** ``tgt_cat`` + 落点图 tier 发钱。
    2026-07-31：废止 Boss ÷10，仅用 ``by_category`` 阶梯；小怪封顶 / Boss 保底；
    地图卢恩缩放指数 ``rune_over_difficulty_power``（默认 1.4）> 血量线性比。
    2026-08-04：``night`` 红灵按捐皮原版 getSoul / GameArea，**不做**阶梯封顶。
    2026-08-07：废止上条；5 池 + 红灵捐皮落 3/4 池 → 对齐 ``minor_boss`` 阶梯。
    """
    from enemy_randomizer_core import BOSS_SOURCE_CATEGORIES, TRASH_LIKE_TARGET_CATEGORIES
    _ = mob_drop_mode, categories_cfg, keep_original_multiplier

    from enemy_difficulty import load_difficulty_cfg, rune_category_uses_hp_balance

    ga_npc = gamearea_by_npc or {}
    ga_model = gamearea_by_model or {}
    donor_model = str(template.get("model") or "")
    reward_cat = str(tgt_cat or "trash")
    src_reward_cat = str(src_cat or "trash")
    diff_cfg = load_difficulty_cfg()
    # T-058：走 HP 平衡的池不再叠地图 tier 卢恩（与血量层双乘）
    map_scale = True
    if not bool(diff_cfg.get("rune_map_scale_with_hp_balance", False)):
        if rune_category_uses_hp_balance(reward_cat, diff_cfg):
            map_scale = False

    if is_summon_clone_donor_template(template, categories_cfg):
        # 玛莲妮亚水鸟分身等白名单捐皮：只按 1 池 trash 发钱（T-070：不用 _900x 后缀泛化）
        return tier_baseline_rune_amount(
            "trash", rune_tiers, map_id, apply_map_scale=map_scale
        )

    try:
        donor_npc = int(template.get("npc", 0))
    except (TypeError, ValueError):
        donor_npc = 0

    # 红灵：对齐 3 池 minor_boss 阶梯（2026-08-07）；废止按捐皮原版 getSoul/GameArea
    if red_spirit_rune_tier_only(reward_cat, donor_model, categories_cfg):
        # night 不走 HP 平衡 → 仍可地图缩放
        return tier_baseline_rune_amount(
            "minor_boss", rune_tiers, map_id, apply_map_scale=True
        )

    allow_gamearea = _rune_allows_gamearea(reward_cat) and src_reward_cat in BOSS_SOURCE_CATEGORIES

    tier_amount = tier_baseline_rune_amount(
        reward_cat, rune_tiers, map_id, apply_map_scale=map_scale
    )
    donor_raw = raw_donor_rune_soul(
        npc=donor_npc,
        model=donor_model,
        reward_cat=reward_cat,
        allow_gamearea=allow_gamearea,
        soul_map=soul_map,
        gamearea_by_npc=ga_npc,
        gamearea_by_model=ga_model,
    )
    if donor_raw > 0:
        donor_amount = (
            apply_rune_map_scaling(donor_raw, map_id) if map_scale else int(donor_raw)
        )
    else:
        donor_amount = 0

    if reward_cat in TRASH_LIKE_TARGET_CATEGORIES:
        amount = tier_amount if donor_amount <= 0 else min(donor_amount, tier_amount)
    else:
        amount = max(donor_amount, tier_amount)
    return amount

