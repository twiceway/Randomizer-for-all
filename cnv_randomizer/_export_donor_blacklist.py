"""导出捐皮黑名单（按 1～6 池 · 同名去重 · 去掉白名单已有同名）。

用法:
  python _export_donor_blacklist.py

输出:
  捐皮契约/捐皮黑名单_当前.md
  捐皮契约/捐皮黑名单_当前.json
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import enemy_randomizer_core as core  # noqa: E402
from _donor_export_common import (  # noqa: E402
    enrich_donor_row,
    load_curated_display_names,
    load_donor_export_context,
    name_key,
    pick_better_row_by_hp,
    pool_sections,
    render_blacklist_pool_sections,
    resolve_display_name_zh,
)
from dlc_donor_pool import build_vanilla_donor_npc_by_model  # noqa: E402
from donor_pool_review_allowlist import (  # noqa: E402
    apply_review_allowlist_category,
    is_allowlisted_donor_template,
    normalize_category_id,
)
from enemy_slot_prep import build_prep_context  # noqa: E402
from paths import DONOR_POOL_CONTRACT_DIR  # noqa: E402

OUT_DIR = DONOR_POOL_CONTRACT_DIR

REASON_ZH: dict[str, str] = {
    "never_donor_model": "never_donor",
    "never_donor_npc": "never_donor npc",
    "horse_mount": "战马挂点",
    "passive_animal": "被动动物",
    "talk_npc": "对话Npc",
    "exclude_slot_npc": "剧情槽",
    "donor_review_excluded": "审阅剔除",
    "not_in_review_allowlist": "未入白名单",
    "exclude_donor_model": "exclude_donor",
    "script_event_think": "脚本think",
    "decorative_npc_equals_think": "装饰npc",
    "donor_hp_too_low": "有效HP过低",
}


def classify_donor_block_reason(
    tpl: dict[str, Any],
    categories_cfg: dict[str, Any],
    *,
    csv_dir: Path,
    npc_rows: dict[int, dict[str, str]] | None = None,
    sp_rates: dict[str, float] | None = None,
) -> str | None:
    model = str(tpl.get("model", ""))
    if core.is_never_donor_model(model, categories_cfg):
        if core.is_horse_mount_model(model, categories_cfg):
            return "horse_mount"
        return "never_donor_model"
    if core.is_never_donor_npc_id(tpl, categories_cfg):
        return "never_donor_npc"
    if core.is_passive_animal_model(model, categories_cfg):
        return "passive_animal"
    try:
        npc = int(tpl.get("npc", 0) or 0)
    except (TypeError, ValueError):
        npc = 0
    if npc > 0 and core.is_talk_npc_id(npc, csv_dir):
        return "talk_npc"
    if core.is_excluded_slot_npc_id(tpl, categories_cfg):
        return "exclude_slot_npc"
    if categories_cfg.get("donor_review_filter_enabled"):
        from donor_pool_review_filter import is_donor_review_excluded_template

        if is_donor_review_excluded_template(
            tpl, categories_cfg=categories_cfg, csv_dir=csv_dir
        ):
            return "donor_review_excluded"
    if not is_allowlisted_donor_template(tpl, categories_cfg):
        return "not_in_review_allowlist"
    from dlc_donor_pool import is_below_min_donor_effective_hp

    if is_below_min_donor_effective_hp(
        tpl,
        categories_cfg,
        npc_rows=npc_rows,
        sp_rates=sp_rates,
        csv_dir=csv_dir,
    ):
        return "donor_hp_too_low"
    for prefix in categories_cfg.get("exclude_donor_model_prefixes") or []:
        if model.lower().startswith(str(prefix).lower()):
            return "exclude_donor_model"
    donor_cat = str(tpl.get("category") or "") or core.resolve_src_category(
        model, categories_cfg
    )
    boss_like = donor_cat in core.BOSS_SOURCE_CATEGORIES or donor_cat == "night"
    if not boss_like:
        think_min = categories_cfg.get("exclude_donor_think_min")
        if think_min is not None:
            try:
                if int(tpl.get("think", 0)) >= int(think_min):
                    return "script_event_think"
            except (TypeError, ValueError):
                pass
        npc_eq_below = categories_cfg.get("exclude_donor_npc_equals_think_below")
        if npc_eq_below is not None:
            try:
                n = int(tpl.get("npc", 0))
                think = int(tpl.get("think", 0))
                if n == think and 0 < n < int(npc_eq_below):
                    return "decorative_npc_equals_think"
            except (TypeError, ValueError):
                pass
    return None


def _pool_for_category(cat: str) -> int:
    return int(core.CATEGORY_NUM.get(cat, 0) or 0)


def _collect_whitelist_name_keys_by_pool(
    categories_cfg: dict[str, Any],
    ctx_export: dict[str, Any],
) -> dict[int, set[str]]:
    index = core.load_enemy_index()
    prep = build_prep_context(
        index,
        categories_cfg,
        dlc_pool_mode="mixed",
        npc_csv_dir=ctx_export["npc_csv_dir"],
    )
    vanilla = build_vanilla_donor_npc_by_model(
        list(index.get("templates") or []),
        npc_by_id=ctx_export["npc_rows"],
        sp_rates=ctx_export["sp_rates"],
    )
    by_pool: dict[int, set[str]] = defaultdict(set)
    seen: set[tuple[str, str, int]] = set()
    for pool_key, tpl_list in prep["compat_pools"].items():
        cat = pool_key[0] if isinstance(pool_key, tuple) else str(pool_key)
        for tpl in tpl_list:
            model = str(tpl.get("model", ""))
            try:
                npc = int(tpl.get("npc", 0) or 0)
            except (TypeError, ValueError):
                npc = 0
            tpl_cat = str(tpl.get("category") or cat)
            p = _pool_for_category(tpl_cat)
            if p <= 0:
                continue
            key = (tpl_cat, model.lower(), npc)
            if key in seen:
                continue
            seen.add(key)
            extra = enrich_donor_row(
                tpl,
                categories_cfg=categories_cfg,
                npc_rows=ctx_export["npc_rows"],
                sp_rates=ctx_export["sp_rates"],
                paramdex_names=ctx_export["paramdex_names"],
                review_name_zh=ctx_export["review_name_zh"],
                archetype_index=ctx_export["archetype_index"],
                vanilla_npc_by_model=vanilla,
            )
            row = {"name_zh": extra["name_zh"], "name_en": extra["name_en"], "model": model}
            by_pool[p].add(name_key(row))
    return by_pool


def main() -> None:
    ctx = load_donor_export_context()
    categories_cfg = ctx["categories_cfg"]
    archetype_index = ctx["archetype_index"]
    curated_names = load_curated_display_names()

    whitelist_names = _collect_whitelist_name_keys_by_pool(categories_cfg, ctx)

    index = core.load_enemy_index()
    templates = list(index.get("templates") or [])
    vanilla_npc_by_model = build_vanilla_donor_npc_by_model(
        templates, npc_by_id=ctx["npc_rows"], sp_rates=ctx["sp_rates"]
    )

    raw_blocked: list[dict[str, Any]] = []
    seen_npc: set[tuple[str, str, int]] = set()
    allowed = 0

    for tpl in templates:
        tid = str(tpl.get("template_id") or "")
        if not tid:
            continue
        annotated = dict(tpl)
        model = str(annotated.get("model", ""))
        try:
            npc = int(annotated.get("npc", 0) or 0)
        except (TypeError, ValueError):
            npc = 0
        rules_cat = core.resolve_src_category(model, categories_cfg)
        cat = str(annotated.get("category") or "") or rules_cat
        annotated["category"] = cat
        wl_cat = apply_review_allowlist_category(annotated, categories_cfg)
        pool_cat = normalize_category_id(str(wl_cat or rules_cat or cat))
        annotated["category"] = pool_cat
        pool = _pool_for_category(pool_cat)
        if pool <= 0:
            pool = 1

        reason = classify_donor_block_reason(
            annotated,
            categories_cfg,
            csv_dir=ctx["npc_csv_dir"],
            npc_rows=ctx["npc_rows"],
            sp_rates=ctx["sp_rates"],
        )
        if reason is None:
            allowed += 1
            continue

        dedupe_key = (reason, model.lower(), npc)
        if dedupe_key in seen_npc:
            continue
        seen_npc.add(dedupe_key)

        extra = enrich_donor_row(
            annotated,
            categories_cfg=categories_cfg,
            npc_rows=ctx["npc_rows"],
            sp_rates=ctx["sp_rates"],
            paramdex_names=ctx["paramdex_names"],
            review_name_zh=ctx["review_name_zh"],
            archetype_index=archetype_index,
            vanilla_npc_by_model=vanilla_npc_by_model,
        )
        name_zh = resolve_display_name_zh(
            extra["name_en"], extra, curated_names=curated_names
        )
        row = {
            "pool": pool,
            "pool_zh": core.CATEGORY_DISPLAY_ZH.get(pool_cat, pool_cat),
            "category": pool_cat,
            "reason": reason,
            "reason_zh": REASON_ZH.get(reason, reason),
            "model": model,
            "name_zh": name_zh,
            "name_en": extra["name_en"],
            "effective_hp": extra["effective_hp"],
            "hp_mult_desc": extra["hp_mult_desc"],
            "npc": npc,
            "archetype_zh": extra["archetype_zh"],
            "size_tier": extra["size_tier"],
            "size_tier_zh": extra["size_tier_zh"],
        }
        raw_blocked.append(row)

    skipped_whitelist_name = 0
    by_pool_name: dict[tuple[int, str], dict[str, Any]] = {}
    for row in raw_blocked:
        pool = int(row["pool"])
        nk = name_key(row)
        if nk in whitelist_names.get(pool, set()):
            skipped_whitelist_name += 1
            continue
        k = (pool, nk)
        if k in by_pool_name:
            by_pool_name[k] = pick_better_row_by_hp(by_pool_name[k], row)
        else:
            by_pool_name[k] = row

    by_pool: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for (pool, _nk), row in by_pool_name.items():
        by_pool[pool].append(row)
    for pool in by_pool:
        by_pool[pool].sort(
            key=lambda r: (
                str(r.get("name_zh") or r.get("name_en") or r.get("model") or ""),
                str(r.get("model") or ""),
            )
        )

    total_rows = sum(len(v) for v in by_pool.values())
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = OUT_DIR / "捐皮黑名单_当前.json"
    json_path.write_text(
        json.dumps(
            {
                "generated_at": generated,
                "schema": "donor_blacklist_v3",
                "allowed_template_count": allowed,
                "raw_blocked_model_npc": len(raw_blocked),
                "skipped_same_name_as_whitelist": skipped_whitelist_name,
                "rows_after_dedupe": total_rows,
                "rows_by_pool": {str(p): rows for p, rows in sorted(by_pool.items())},
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    lines: list[str] = [
        "# 捐皮黑名单（按池 · 简化）",
        "",
        f"**生成**：{generated}  ",
        f"**条数**：{total_rows} 种（按池内中文/英文名去重；已去掉与同池白名单同名的 {skipped_whitelist_name} 条）  ",
        "**池归属**：审阅白名单类别 + 1 池 trash 按有效 HP 升格（≥4000/10000/14000 → 2/3/4 池）  ",
        "**中文名**：`donor_blacklist_name_zh.json` 人工校对，优先于自动译名  ",
        "**对照白名单**：`捐皮白名单_当前.md`  ",
        "**机器可读**：`捐皮黑名单_当前.json`",
        "",
        "> 现网 **6 池**；仅列「禁捐且白名单里没有同名」的敌人。配置级 `never_donor` 见 `enemy_categories.json`。",
        "",
    ]

    lines.extend(render_blacklist_pool_sections(by_pool))

    md_path = OUT_DIR / "捐皮黑名单_当前.md"
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(
        f"wrote {md_path} rows={total_rows} "
        f"skipped_whitelist_name={skipped_whitelist_name} allowed={allowed}"
    )
    print(f"wrote {json_path}")


if __name__ == "__main__":
    main()
