"""导出 1～6 池捐皮表（仅整理 · 不改 enemy_categories）。

用法:
  python _build_donor_pool_tables_1_7.py

输出:
  捐池_原槽表/捐皮池表_1-7.json
  捐池_原槽表/捐皮池表_1-7.md
  捐池_原槽表/捐皮池表_池{N}_*.md  （2～6 池各一份）
  捐池_原槽表/捐皮池表_池1_索引.md + 捐皮池表_池1_{原型id}.md（1 池按 archetype 拆分）
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
REVIEW_NPC_NAME_ZH_PATH = SCRIPT_DIR / "npc_param_name_zh.json"
sys.path.insert(0, str(SCRIPT_DIR))

import enemy_randomizer_core as core  # noqa: E402
from boss_npc_detect import load_npc_rows  # noqa: E402
from dlc_donor_pool import (  # noqa: E402
    build_vanilla_donor_npc_by_model,
    is_synthetic_donor_template,
    load_sp_hp_rates,
    npc_effective_hp_for_review,
    resolve_synthetic_template_donor_npc,
)
from enemy_slot_prep import build_prep_context  # noqa: E402
from paths import DONOR_POOL_REVIEW_DIR, ensure_donor_review_dirs  # noqa: E402


def _model_zh(model: str, categories_cfg: dict[str, Any]) -> str:
    """spoiler 口径：仅 model_prefix_display_zh 最长前缀，不拼英文名。"""
    return core._model_prefix_zh(model, categories_cfg)


def _load_review_npc_name_zh() -> dict[str, str]:
    if not REVIEW_NPC_NAME_ZH_PATH.is_file():
        return {}
    raw = core._load_json(REVIEW_NPC_NAME_ZH_PATH)
    names = raw.get("names") or {}
    return {str(k).strip(): str(v).strip() for k, v in names.items() if str(k).strip()}


def _resolve_name_zh(
    model_zh: str,
    name_en: str,
    review_name_zh: dict[str, str],
) -> str:
    if model_zh:
        return model_zh
    en = str(name_en or "").strip()
    if not en:
        return ""
    if en in review_name_zh:
        return review_name_zh[en]
    # NpcParam 偶发乱码（如 Merchant Kalé）
    for key, zh in review_name_zh.items():
        if key.replace("é", "e").lower() == en.replace("é", "e").lower():
            return zh
    return ""


def _donor_map_id(tpl: dict[str, Any]) -> str:
    raw = str(tpl.get("donor_map") or "")
    if raw.endswith(".msb.dcx"):
        return raw[:-8]
    if ":" in str(tpl.get("template_id", "")):
        return str(tpl["template_id"]).split(":", 1)[0]
    return raw


def _build_rows(
    templates: list[dict[str, Any]],
    *,
    categories_cfg: dict[str, Any],
    npc_rows: dict[int, dict[str, str]],
    sp_rates: dict[str, float],
    in_pool_ids: set[str],
    map_names: dict[str, str],
    paramdex_names: dict[int, str],
    archetype_index: core.ArchetypeIndex,
    review_name_zh: dict[str, str],
    vanilla_npc_by_model: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    never_npc = {int(x) for x in categories_cfg.get("never_donor_npc_ids") or []}
    original_npc = {int(x) for x in categories_cfg.get("cnv_original_boss_slot_npc_ids") or []}
    rows: list[dict[str, Any]] = []
    for tpl in templates:
        tpl_id = str(tpl.get("template_id") or "")
        if not tpl_id:
            continue
        model = str(tpl.get("model", ""))
        try:
            npc = int(tpl.get("npc", 0) or 0)
        except (TypeError, ValueError):
            npc = 0
        cat = str(tpl.get("category") or "")
        model_zh = _model_zh(model, categories_cfg)
        arch_id = archetype_index.trash_archetype_for_model(model)
        arch_zh = archetype_index.trash_archetype_labels.get(arch_id, "") if arch_id else ""
        trash_donor = core.is_trash_donor_model(model, categories_cfg)
        npc_row = npc_rows.get(npc, {})
        name_csv = str(npc_row.get("Name") or "").strip()
        name_en = name_csv or str(paramdex_names.get(npc) or "").strip()
        name_zh = _resolve_name_zh(model_zh, name_en, review_name_zh) or arch_zh
        tt = tpl.get("template_tags") or {}
        if is_synthetic_donor_template({"template_id": tpl_id}):
            origin = str(tt.get("donor_origin") or "")
            if origin != "cnv":
                ref_npc = resolve_synthetic_template_donor_npc(
                    {"template_id": tpl_id, "model": model, "npc": npc, "template_tags": tt},
                    vanilla_npc_by_model or {},
                )
                ref_row = npc_rows.get(ref_npc, {})
                hp_pick = npc_effective_hp_for_review(
                    ref_npc,
                    ref_row or None,
                    model=model,
                    sp_rates=sp_rates,
                    npc_by_id=npc_rows,
                )
                if vanilla_npc_by_model and model.lower() in vanilla_npc_by_model:
                    hp_pick = {
                        **hp_pick,
                        "npc": ref_npc,
                        "effective_hp": int(
                            vanilla_npc_by_model[model.lower()]["effective_hp"]
                        ),
                        "hp_mult_desc": (
                            f"原版{vanilla_npc_by_model[model.lower()]['variant_count']}"
                            f"皮均值·合成→{ref_npc}"
                        ),
                    }
            else:
                hp_pick = npc_effective_hp_for_review(
                    npc,
                    npc_row or None,
                    model=model,
                    sp_rates=sp_rates,
                    npc_by_id=npc_rows,
                )
        else:
            hp_pick = npc_effective_hp_for_review(
                npc,
                npc_row or None,
                model=model,
                sp_rates=sp_rates,
                npc_by_id=npc_rows,
            )
        map_id = _donor_map_id(tpl)
        unsafe = core.is_unsafe_donor_template(tpl, categories_cfg)
        display_npc = npc
        if (
            is_synthetic_donor_template({"template_id": tpl_id})
            and str(tt.get("donor_origin") or "") != "cnv"
            and vanilla_npc_by_model
        ):
            ref_npc = resolve_synthetic_template_donor_npc(
                {"template_id": tpl_id, "model": model, "npc": npc, "template_tags": tt},
                vanilla_npc_by_model,
            )
            if ref_npc != npc:
                display_npc = ref_npc
                ref_row = npc_rows.get(ref_npc, {})
                ref_name = str(ref_row.get("Name") or "").strip()
                if ref_name:
                    name_en = ref_name
                    name_csv = ref_name
        rows.append(
            {
                "pool": core.CATEGORY_NUM.get(cat, 0),
                "category": cat,
                "category_zh": core.CATEGORY_DISPLAY_ZH.get(cat, cat),
                "archetype_id": arch_id or "_misc",
                "archetype_zh": arch_zh or "未归类",
                "trash_donor_model": trash_donor,
                "template_id": tpl_id,
                "model": model,
                "model_zh": model_zh,
                "name_zh": name_zh,
                "npc": display_npc,
                "name_en": name_en,
                "name_csv": name_csv,
                "table_hp": int(hp_pick.get("table_hp") or 0),
                "effective_hp": int(hp_pick.get("effective_hp") or 0),
                "hp_mult_desc": str(hp_pick.get("hp_mult_desc") or ""),
                "map_id": map_id,
                "map_zh": str(map_names.get(map_id) or ""),
                "donor_entity": str(tpl.get("donor_entity") or tpl_id.split(":", 1)[-1]),
                "donor_origin": str(tt.get("donor_origin") or ""),
                "synthetic": tpl_id.startswith("synthetic:"),
                "in_prep_pool": tpl_id in in_pool_ids,
                "unsafe_donor": unsafe,
                "never_donor_npc": npc in never_npc,
                "original_boss_npc": npc in original_npc,
                "size_tier": str(tt.get("size_tier") or ""),
            }
        )
    rows.sort(key=lambda r: (r["pool"], r["model"], r["npc"], r["map_id"], r["donor_entity"]))
    return rows


DEDUPE_NOTE_NAME_EN = "按英文名合并·原版皮HP均值（不含合成）"
DEDUPE_NOTE_MODEL_NPC = "按 model+npc 去重"


def _merge_template_group(group: list[dict[str, Any]]) -> dict[str, Any]:
    """单组模板行 → 审阅行（槽位计数 + 示例地图）。"""
    best = max(group, key=lambda x: (int(x["effective_hp"]), int(x["in_prep_pool"])))
    maps = sorted({str(x["map_id"]) for x in group if x.get("map_id")})
    return {
        **best,
        "slot_count": len(group),
        "map_sample": maps[0] if maps else "",
        "map_count": len(maps),
        "in_prep_count": sum(1 for x in group if x["in_prep_pool"]),
    }


def _dedupe_by_model_npc(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按 model+npc 合并：保留最高有效 HP。"""
    buckets: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for r in rows:
        key = (str(r["model"]), int(r["npc"]))
        buckets.setdefault(key, []).append(r)
    out: list[dict[str, Any]] = []
    for _key, group in sorted(buckets.items()):
        merged = _merge_template_group(group)
        merged["merged_variants"] = 1
        out.append(merged)
    return out


def _dedupe_by_name_en(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """池 1～6：按 NpcParam 英文名（name_en）合并；HP 仅原版地图皮均值（不含 synthetic）。"""
    named: dict[str, list[dict[str, Any]]] = {}
    unnamed: list[dict[str, Any]] = []
    for r in rows:
        name_en = str(r.get("name_en") or "").strip()
        if name_en:
            named.setdefault(name_en, []).append(r)
        else:
            unnamed.append(r)

    out: list[dict[str, Any]] = []
    for name_en, templates in sorted(named.items()):
        vanilla = [r for r in templates if not r.get("synthetic")]
        merge_src = vanilla if vanilla else templates
        variant_buckets: dict[tuple[str, int], list[dict[str, Any]]] = {}
        for r in merge_src:
            vkey = (str(r["model"]), int(r["npc"]))
            variant_buckets.setdefault(vkey, []).append(r)

        variant_rows = [_merge_template_group(g) for g in variant_buckets.values()]
        avg_eff = round(sum(int(v["effective_hp"]) for v in variant_rows) / len(variant_rows))
        avg_table = round(sum(int(v["table_hp"]) for v in variant_rows) / len(variant_rows))
        rep = min(
            variant_rows,
            key=lambda x: (abs(int(x["effective_hp"]) - avg_eff), -int(x["slot_count"])),
        )
        hp_note = f"同名{len(variant_rows)}条均值"
        if vanilla and len(vanilla) < len(templates):
            hp_note += "·不含合成"
        maps = sorted(
            {
                str(t["map_id"])
                for g in variant_buckets.values()
                for t in g
                if t.get("map_id")
            }
        )
        out.append(
            {
                **rep,
                "name_en": name_en,
                "effective_hp": avg_eff,
                "table_hp": avg_table,
                "hp_mult_desc": hp_note,
                "slot_count": sum(int(x["slot_count"]) for x in variant_rows),
                "map_sample": maps[0] if maps else "",
                "map_count": len(maps),
                "in_prep_count": sum(int(x["in_prep_count"]) for x in variant_rows),
                "merged_variants": len(variant_rows),
                "merged_models": ",".join(sorted({str(x["model"]) for x in variant_rows})),
            }
        )

    out.extend(_dedupe_by_model_npc(unnamed))
    out.sort(key=lambda r: (str(r.get("name_en") or ""), str(r.get("model") or ""), int(r.get("npc") or 0)))
    return out


def _dedupe_for_review(rows: list[dict[str, Any]], *, pool: int = 0) -> list[dict[str, Any]]:
    """各池按 NpcParam 英文名（name_en）合并；无英文名则回退 model+npc。"""
    _ = pool
    return _dedupe_by_name_en(rows)


def _md_table(rows: list[dict[str, Any]], columns: list[tuple[str, str]]) -> list[str]:
    header = "| 序号 | " + " | ".join(h for _, h in columns) + " |"
    sep = "| ---: | " + " | ".join("---" for _ in columns) + " |"
    out = [header, sep]
    for idx, row in enumerate(rows, start=1):
        cells = [str(row.get(k, "—")).replace("|", "\\|") for k, _ in columns]
        out.append(f"| {idx} | " + " | ".join(cells) + " |")
    return out


def _write_pool_md(
    path: Path,
    *,
    title: str,
    generated: str,
    review_rows: list[dict[str, Any]],
    template_count: int,
    columns: list[tuple[str, str]],
    dedupe_note: str = DEDUPE_NOTE_MODEL_NPC,
    extra_lines: list[str] | None = None,
) -> None:
    lines = [
        f"# {title}",
        "",
        f"生成：{generated}",
        f"审阅行：{len(review_rows)}（{dedupe_note}）· 模板：{template_count}",
        "",
    ]
    if extra_lines:
        lines.extend(extra_lines)
        lines.append("")
    if review_rows:
        lines.extend(_md_table(review_rows, columns))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _pool1_archetype_order(archetype_index: core.ArchetypeIndex) -> list[tuple[str, str]]:
    order: list[tuple[str, str]] = [
        (aid, archetype_index.trash_archetype_labels.get(aid, aid))
        for aid in archetype_index.trash_archetype_ids
    ]
    order.append(("_misc", "未归类（非原型表）"))
    return order


def _write_pool1_split(
    review_rows: list[dict[str, Any]],
    template_count: int,
    generated: str,
    archetype_index: core.ArchetypeIndex,
    columns: list[tuple[str, str]],
) -> None:
    by_arch: dict[str, list[dict[str, Any]]] = {}
    for row in review_rows:
        arch_id = str(row.get("archetype_id") or "_misc")
        by_arch.setdefault(arch_id, []).append(row)

    index_lines = [
        "# 池 1 · 路边小怪 — 按原型拆分索引",
        "",
        f"生成：{generated}",
        f"审阅行合计：{len(review_rows)}（{DEDUPE_NOTE_NAME_EN}）· 模板：{template_count}",
        "",
        "> 中文名：`model_prefix_display_zh` 优先；空则 `npc_param_name_zh.json` 英译；仍空见英文名。",
        "> 同名 = **NpcParam 英文名**（`name_en`）相同的多条 npc 合并为一行；**有效 HP 仅原版地图皮均值，不含 synthetic 合成行**；合成捐皮运行时 npc 亦对齐原版均值代表行。",
        "",
        "| 序号 | 原型 id | 中文类名 | 审阅行 | 捐皮白名单 model | 入 prep 槽 | 文件 |",
        "| ---: | --- | --- | ---:|---:|---:|---|",
    ]

    index_no = 0
    for arch_id, arch_zh in _pool1_archetype_order(archetype_index):
        rows = by_arch.get(arch_id, [])
        if not rows and arch_id != "_misc":
            continue
        index_no += 1
        donor_models = sum(1 for r in rows if r.get("trash_donor_model"))
        in_prep = sum(int(r.get("in_prep_count") or 0) for r in rows)
        fname = f"捐皮池表_池1_{arch_id}.md"
        index_lines.append(
            f"| {index_no} | {arch_id} | {arch_zh} | {len(rows)} | {donor_models} | {in_prep} | `{fname}` |"
        )
        _write_pool_md(
            DONOR_POOL_REVIEW_DIR / fname,
            title=f"池 1 · {arch_zh}（{arch_id}）",
            generated=generated,
            review_rows=rows,
            template_count=sum(int(r.get("slot_count") or 0) for r in rows),
            columns=columns,
            dedupe_note=DEDUPE_NOTE_NAME_EN,
        )

    index_path = DONOR_POOL_REVIEW_DIR / "捐皮池表_池1_索引.md"
    index_path.write_text("\n".join(index_lines) + "\n", encoding="utf-8")

    # 旧单文件改为短指针，避免预览卡死
    stub = DONOR_POOL_REVIEW_DIR / "捐皮池表_池1_trash.md"
    stub.write_text(
        "\n".join(
            [
                "# 池 1 · 路边小怪",
                "",
                f"生成：{generated}",
                "",
                "本池已按 **enemy_archetypes.json** 原型拆分为多份小表，请打开：",
                "",
                "- **`捐皮池表_池1_索引.md`** — 各子表行数与链接",
                "",
                f"审阅行合计：{len(review_rows)} · 模板：{template_count}",
                "",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> None:
    categories_cfg = core._load_json(core.DEFAULT_CATEGORIES_PATH)
    archetype_index = core.load_archetype_index(categories_cfg)
    npc_csv_dir = core.GAME_DIR / "csv"
    npc_rows = load_npc_rows(npc_csv_dir)
    sp_rates = load_sp_hp_rates()
    paramdex_names = core.load_npc_display_names()
    map_names = core.load_map_display_names(categories_cfg)

    index = core.load_enemy_index()
    ctx = build_prep_context(
        index,
        categories_cfg,
        dlc_pool_mode="mixed",
        npc_csv_dir=npc_csv_dir,
    )

    in_pool_ids: set[str] = set()
    for tpl_list in ctx["compat_pools"].values():
        for tpl in tpl_list:
            tid = str(tpl.get("template_id") or "")
            if tid:
                in_pool_ids.add(tid)

    review_name_zh = _load_review_npc_name_zh()
    all_templates = list(index.get("templates") or [])
    vanilla_npc_by_model = build_vanilla_donor_npc_by_model(
        all_templates, npc_by_id=npc_rows, sp_rates=sp_rates
    )
    rows = _build_rows(
        all_templates,
        categories_cfg=categories_cfg,
        npc_rows=npc_rows,
        sp_rates=sp_rates,
        in_pool_ids=in_pool_ids,
        map_names=map_names,
        paramdex_names=paramdex_names,
        archetype_index=archetype_index,
        review_name_zh=review_name_zh,
        vanilla_npc_by_model=vanilla_npc_by_model,
    )

    pool_count = len(core.CATEGORY_ORDER)
    by_pool: dict[int, list[dict[str, Any]]] = {n: [] for n in range(1, pool_count + 1)}
    review_by_pool: dict[int, list[dict[str, Any]]] = {n: [] for n in range(1, pool_count + 1)}
    for r in rows:
        p = int(r.get("pool") or 0)
        if p in by_pool:
            by_pool[p].append(r)
    for n in range(1, pool_count + 1):
        review_by_pool[n] = _dedupe_for_review(by_pool[n], pool=n)

    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    payload = {
        "generated_at": generated,
        "schema": "donor_pool_tables_v1",
        "npc_csv": str(npc_csv_dir / "NpcParam.csv"),
        "template_total": len(rows),
        "in_prep_pool": sum(1 for r in rows if r["in_prep_pool"]),
        "pools": {
            str(n): {
                "category": core.CATEGORY_ORDER[n - 1],
                "category_zh": core.CATEGORY_DISPLAY_ZH.get(core.CATEGORY_ORDER[n - 1], ""),
                "count": len(by_pool[n]),
                "review_count": len(review_by_pool[n]),
                "in_prep": sum(1 for r in by_pool[n] if r["in_prep_pool"]),
                "rows": by_pool[n],
                "review_rows": review_by_pool[n],
            }
            for n in range(1, pool_count + 1)
        },
    }

    ensure_donor_review_dirs()
    json_path = DONOR_POOL_REVIEW_DIR / "捐皮池表_1-7.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    cols_review = [
        ("name_en", "英文名"),
        ("name_zh", "中文名"),
        ("merged_variants", "同名条数"),
        ("model", "model"),
        ("archetype_zh", "原型类"),
        ("npc", "npc"),
        ("effective_hp", "有效HP"),
        ("hp_mult_desc", "HP倍率"),
        ("map_sample", "示例地图"),
        ("donor_entity", "示例实体"),
        ("slot_count", "MSB槽数"),
        ("map_count", "分布图数"),
        ("in_prep_count", "入prep槽"),
        ("synthetic", "合成"),
        ("merged_models", "多model"),
    ]

    cols_review_other = [
        ("name_en", "英文名"),
        ("name_zh", "中文名"),
        ("merged_variants", "同名条数"),
        ("model", "model"),
        ("npc", "npc"),
        ("effective_hp", "有效HP"),
        ("hp_mult_desc", "HP倍率"),
        ("map_sample", "示例地图"),
        ("donor_entity", "示例实体"),
        ("slot_count", "MSB槽数"),
        ("map_count", "分布图数"),
        ("in_prep_count", "入prep槽"),
        ("synthetic", "合成"),
        ("merged_models", "多model"),
    ]

    md: list[str] = [
        "# 捐皮池表 1～6（审阅用 · 未落实配置）",
        "",
        f"**生成**：{generated}  ",
        f"**NpcParam**：`{npc_csv_dir / 'NpcParam.csv'}`  ",
        f"**模板总数**：{len(rows)} · **compat 入池**：{payload['in_prep_pool']}  ",
        "",
        "> 仅导出对照表；`in_prep_pool=False` = 被 never_donor/unsafe/体型等过滤。",
        "",
        "## 池概览",
        "",
        "| 序号 | 池 | 类 | 模板数 | 审阅行 | compat入池 | 去重口径 |",
        "|---:|---:|---|---:|---:|---:|---|",
    ]
    for n in range(1, pool_count + 1):
        cat = core.CATEGORY_ORDER[n - 1]
        md.append(
            f"| {n} | {core.CATEGORY_DISPLAY_ZH.get(cat, cat)} | {len(by_pool[n])} | "
            f"{len(review_by_pool[n])} | "
            f"{sum(1 for r in by_pool[n] if r['in_prep_pool'])} | {DEDUPE_NOTE_NAME_EN} |"
        )

    md.extend(
        [
            "",
            "## 池 1 拆分",
            "",
            "路边小怪审阅表已按 `enemy_archetypes.json` 原型拆为多份，见 **`捐皮池表_池1_索引.md`**。",
            "",
        ]
    )

    for n in range(2, pool_count + 1):
        cat = core.CATEGORY_ORDER[n - 1]
        cat_zh = core.CATEGORY_DISPLAY_ZH.get(cat, cat)
        review_rows = review_by_pool[n]
        md.extend(
            [
                "",
                f"## 池 {n} · {cat_zh}（审阅 {len(review_rows)} / 模板 {len(by_pool[n])}）",
                "",
            ]
        )
        if review_rows:
            md.extend(_md_table(review_rows, cols_review_other))

        per_path = DONOR_POOL_REVIEW_DIR / f"捐皮池表_池{n}_{cat}.md"
        _write_pool_md(
            per_path,
            title=f"池 {n} · {cat_zh}",
            generated=generated,
            review_rows=review_rows,
            template_count=len(by_pool[n]),
            columns=cols_review_other,
            dedupe_note=DEDUPE_NOTE_NAME_EN,
        )

    _write_pool1_split(
        review_by_pool[1],
        len(by_pool[1]),
        generated,
        archetype_index,
        cols_review,
    )

    md_path = DONOR_POOL_REVIEW_DIR / "捐皮池表_1-7.md"
    md_path.write_text("\n".join(md) + "\n", encoding="utf-8")

    print(f"templates={len(rows)} in_prep={payload['in_prep_pool']}")
    for n in range(1, pool_count + 1):
        c = Counter(r["model"] for r in review_by_pool[n])
        print(f"  pool{n} review={len(review_by_pool[n])} templates={len(by_pool[n])} models={len(c)}")
    print(f"Wrote {json_path}")
    print(f"Wrote {md_path}")


if __name__ == "__main__":
    main()
