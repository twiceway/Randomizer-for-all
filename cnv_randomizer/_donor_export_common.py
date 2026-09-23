"""捐皮导出表共用：中文名 / 英文名 / 有效 HP（与审阅表口径一致）。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import enemy_randomizer_core as core
from enemy_category_rules import load_size_tier_meta, resolve_size_tier
from enemy_spawn_io import _model_prefix_zh
from dlc_donor_pool import (
    build_vanilla_donor_npc_by_model,
    is_synthetic_donor_template,
    load_sp_hp_rates,
    npc_effective_hp_for_review,
    resolve_synthetic_template_donor_npc,
)

REVIEW_NPC_NAME_ZH_PATH = Path(__file__).resolve().parent / "npc_param_name_zh.json"
CURATED_DISPLAY_NAMES_PATH = Path(__file__).resolve().parent / "donor_blacklist_name_zh.json"


def pool_sections() -> list[tuple[int, str, str]]:
    """现网 GUI / CATEGORY_NUM：1～6 池。"""
    return [
        (core.CATEGORY_NUM[cat], cat, core.CATEGORY_DISPLAY_ZH.get(cat, cat))
        for cat in core.CATEGORY_ORDER
    ]


def load_curated_display_names() -> dict[str, str]:
    if not CURATED_DISPLAY_NAMES_PATH.is_file():
        return {}
    try:
        raw = core._load_json(CURATED_DISPLAY_NAMES_PATH)
        names = raw.get("names") or {}
        return {str(k).strip(): str(v).strip() for k, v in names.items()}
    except (OSError, TypeError, ValueError):
        return {}


def resolve_display_name_zh(
    name_en: str,
    extra: dict[str, Any],
    *,
    curated_names: dict[str, str] | None = None,
) -> str:
    curated = curated_names if curated_names is not None else load_curated_display_names()
    en = str(name_en or "").strip()
    # 空英文名勿命中 curated[""]→「通用剧情壳」；合成捐皮优先 model 前缀译名
    if en and en in curated:
        return curated[en]
    name_zh = str(extra.get("name_zh") or "").strip()
    # 有英文名时优先英译（同 model 复用 Boss 皮时前缀会误导，如 c4800/c4670）
    if en and name_zh:
        return name_zh
    model_zh = str(extra.get("model_zh") or "").strip()
    if model_zh:
        return model_zh
    if name_zh:
        return name_zh
    if en in curated:
        return curated[en]
    return ""


def name_key(row: dict[str, Any]) -> str:
    zh = str(row.get("name_zh") or "").strip().casefold()
    en = str(row.get("name_en") or "").strip().casefold()
    if zh:
        return zh
    if en:
        return en
    return str(row.get("model") or "").strip().casefold()


def resolve_size_tier_zh(
    model: str,
    *,
    categories_cfg: dict[str, Any] | None = None,
) -> tuple[str, str]:
    """返回 (size_tier_id, label_zh)，真源 enemy_size_tiers.json + categories 前缀表。"""
    categories_cfg = categories_cfg or core._load_json(core.DEFAULT_CATEGORIES_PATH)
    tier_map = categories_cfg.get("size_tier_by_model_prefix") or {}
    tier_id = resolve_size_tier(str(model or ""), tier_map)
    meta = load_size_tier_meta()
    label = str((meta.get(tier_id) or {}).get("label_zh") or tier_id)
    return tier_id, label


def pick_better_row_by_hp(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    if int(b.get("effective_hp") or 0) > int(a.get("effective_hp") or 0):
        return b
    if int(b.get("effective_hp") or 0) < int(a.get("effective_hp") or 0):
        return a
    return a if str(a.get("model", "")) <= str(b.get("model", "")) else b


def load_review_npc_name_zh() -> dict[str, str]:
    if not REVIEW_NPC_NAME_ZH_PATH.is_file():
        return {}
    raw = core._load_json(REVIEW_NPC_NAME_ZH_PATH)
    names = raw.get("names") or {}
    return {str(k).strip(): str(v).strip() for k, v in names.items() if str(k).strip()}


def resolve_name_zh(
    model_zh: str,
    name_en: str,
    review_name_zh: dict[str, str],
    *,
    archetype_zh: str = "",
) -> str:
    en = str(name_en or "").strip()
    if en:
        if en in review_name_zh:
            return review_name_zh[en]
        for key, zh in review_name_zh.items():
            if key.replace("é", "e").lower() == en.replace("é", "e").lower():
                return zh
    if model_zh:
        return model_zh
    return archetype_zh or ""


def resolve_npc_display_names(
    npc: int,
    model: str,
    *,
    categories_cfg: dict[str, Any],
    npc_rows: dict[int, dict[str, str]],
    paramdex_names: dict[int, str],
    review_name_zh: dict[str, str],
    archetype_zh: str = "",
) -> tuple[str, str, str]:
    """返回 (model_zh, name_en, name_zh)。"""
    model_zh = _model_prefix_zh(model, categories_cfg)
    npc_row = npc_rows.get(npc, {})
    name_csv = str(npc_row.get("Name") or "").strip()
    name_en = name_csv or str(paramdex_names.get(npc) or "").strip()
    name_zh = resolve_name_zh(
        model_zh, name_en, review_name_zh, archetype_zh=archetype_zh
    )
    return model_zh, name_en, name_zh


def resolve_template_effective_hp(
    tpl: dict[str, Any],
    *,
    npc_rows: dict[int, dict[str, str]],
    sp_rates: dict[str, float],
    vanilla_npc_by_model: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    model = str(tpl.get("model", ""))
    try:
        npc = int(tpl.get("npc", 0) or 0)
    except (TypeError, ValueError):
        npc = 0
    tpl_id = str(tpl.get("template_id") or "")
    tt = tpl.get("template_tags") or {}
    npc_row = npc_rows.get(npc, {})

    if is_synthetic_donor_template({"template_id": tpl_id}):
        origin = str(tt.get("donor_origin") or "")
        if origin != "cnv" and vanilla_npc_by_model:
            ref_npc = resolve_synthetic_template_donor_npc(
                {"template_id": tpl_id, "model": model, "npc": npc, "template_tags": tt},
                vanilla_npc_by_model,
            )
            ref_row = npc_rows.get(ref_npc, {})
            hp_pick = npc_effective_hp_for_review(
                ref_npc,
                ref_row or None,
                model=model,
                sp_rates=sp_rates,
                npc_by_id=npc_rows,
            )
            if model.lower() in vanilla_npc_by_model:
                vanilla_eff = int(
                    vanilla_npc_by_model[model.lower()]["effective_hp"]
                )
                ref_eff = int(hp_pick.get("effective_hp") or 0)
                hp_pick = {
                    **hp_pick,
                    "npc": ref_npc,
                    "effective_hp": max(vanilla_eff, ref_eff),
                    "hp_mult_desc": (
                        f"原版{vanilla_npc_by_model[model.lower()]['variant_count']}"
                        f"皮均值·合成→{ref_npc}"
                    ),
                }
            return hp_pick

    return npc_effective_hp_for_review(
        npc,
        npc_row or None,
        model=model,
        sp_rates=sp_rates,
        npc_by_id=npc_rows,
    )


def enrich_donor_row(
    tpl: dict[str, Any],
    *,
    categories_cfg: dict[str, Any],
    npc_rows: dict[int, dict[str, str]],
    sp_rates: dict[str, float],
    paramdex_names: dict[int, str],
    review_name_zh: dict[str, str],
    archetype_index: core.ArchetypeIndex,
    vanilla_npc_by_model: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    model = str(tpl.get("model", ""))
    try:
        npc = int(tpl.get("npc", 0) or 0)
    except (TypeError, ValueError):
        npc = 0
    arch_id = archetype_index.trash_archetype_for_model(model)
    arch_zh = archetype_index.trash_archetype_labels.get(arch_id, "") if arch_id else ""
    size_tier, size_tier_zh = resolve_size_tier_zh(model, categories_cfg=categories_cfg)
    model_zh, name_en, name_zh = resolve_npc_display_names(
        npc,
        model,
        categories_cfg=categories_cfg,
        npc_rows=npc_rows,
        paramdex_names=paramdex_names,
        review_name_zh=review_name_zh,
        archetype_zh=arch_zh,
    )
    hp_pick = resolve_template_effective_hp(
        tpl,
        npc_rows=npc_rows,
        sp_rates=sp_rates,
        vanilla_npc_by_model=vanilla_npc_by_model,
    )
    return {
        "model_zh": model_zh,
        "name_en": name_en,
        "name_zh": name_zh,
        "archetype_zh": arch_zh,
        "size_tier": size_tier,
        "size_tier_zh": size_tier_zh,
        "table_hp": int(hp_pick.get("table_hp") or 0),
        "effective_hp": int(hp_pick.get("effective_hp") or 0),
        "hp_mult_desc": str(hp_pick.get("hp_mult_desc") or ""),
    }


def render_whitelist_pool_sections(by_pool: dict[int, list[dict[str, Any]]]) -> list[str]:
    lines: list[str] = []
    for pool_num, _cat_id, pool_title in pool_sections():
        rows = by_pool.get(pool_num, [])
        lines.append("")
        lines.append(f"## 池 {pool_num} · {pool_title}（{len(rows)} 种）")
        lines.append("")
        if not rows:
            lines.append("（无）")
            lines.append("")
            continue
        lines.append("| 序号 | 中文名 | 英文名 | model | 体型 | 有效HP | 合成 |")
        lines.append("|---:|:---|:---|:---|:---|---:|:---|")
        for i, r in enumerate(rows, start=1):
            syn = "是" if r.get("synthetic") else ""
            lines.append(
                f"| {i} | {r.get('name_zh', '')} | {r.get('name_en', '')} | "
                f"`{r.get('model', '')}` | {r.get('size_tier_zh', '')} | "
                f"{r.get('effective_hp', '')} | {syn} |"
            )
    return lines


def render_blacklist_pool_sections(by_pool: dict[int, list[dict[str, Any]]]) -> list[str]:
    lines: list[str] = [""]
    for pool_num, _cat_id, pool_title in pool_sections():
        rows = by_pool.get(pool_num, [])
        lines.append(f"## 池 {pool_num} · {pool_title}（{len(rows)} 种）")
        lines.append("")
        if not rows:
            lines.append("（无）")
            lines.append("")
            continue
        lines.append("| 序号 | 中文名 | 英文名 | model | 体型 | 有效HP | 禁捐原因 |")
        lines.append("|---:|:---|:---|:---|:---|---:|:---|")
        for i, r in enumerate(rows, start=1):
            reason = r.get("reason_zh", r.get("reason", ""))
            lines.append(
                f"| {i} | {r.get('name_zh', '')} | {r.get('name_en', '')} | "
                f"`{r.get('model', '')}` | {r.get('size_tier_zh', '')} | "
                f"{r.get('effective_hp', '')} | {reason} |"
            )
        lines.append("")
    return lines


def load_donor_export_context(categories_cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    from boss_npc_detect import load_npc_rows

    categories_cfg = categories_cfg or core._load_json(core.DEFAULT_CATEGORIES_PATH)
    npc_csv_dir = core.GAME_DIR / "csv"
    return {
        "categories_cfg": categories_cfg,
        "npc_rows": load_npc_rows(npc_csv_dir),
        "sp_rates": load_sp_hp_rates(),
        "paramdex_names": core.load_npc_display_names(),
        "review_name_zh": load_review_npc_name_zh(),
        "archetype_index": core.load_archetype_index(categories_cfg),
        "npc_csv_dir": npc_csv_dir,
    }
