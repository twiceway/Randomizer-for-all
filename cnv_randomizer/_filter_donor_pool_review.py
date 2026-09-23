"""从全量捐皮审阅 JSON 过滤 Dummy/鹿/商人，写入筛选后目录（不改原表）。

用法:
  python _build_donor_pool_tables_1_7.py   # 先刷新全量 → 捐池_原槽表/
  python _filter_donor_pool_review.py      # 过滤 → 筛选后捐池表/ + 筛选后槽表/排除_*.md
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import enemy_randomizer_core as core  # noqa: E402
from donor_pool_review_filter import split_review_rows  # noqa: E402
from paths import (  # noqa: E402
    DONOR_POOL_REVIEW_DIR,
    FILTERED_DONOR_REVIEW_DIR,
    FILTERED_SLOT_REVIEW_DIR,
    ensure_donor_review_dirs,
)

# 复用生成脚本的写表工具
from _build_donor_pool_tables_1_7 import (  # noqa: E402
    DEDUPE_NOTE_NAME_EN,
    _md_table,
    _pool1_archetype_order,
    _write_pool_md,
)

COLS_POOL1 = [
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

COLS_OTHER = [
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

COLS_EXCLUDED = [
    ("exclude_reason", "排除原因"),
    *COLS_POOL1,
]


def _write_pool1_split_to(
    out_dir: Path,
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
        "# 池 1 · 路边小怪 — 按原型拆分索引（已过滤）",
        "",
        f"生成：{generated}",
        f"审阅行合计：{len(review_rows)}（{DEDUPE_NOTE_NAME_EN} · 已剔除 Dummy/鹿/商人）· 模板：{template_count}",
        "",
        "> 全量对照见 `../捐皮池表_池1_索引.md`；剔除项见 `../筛选后槽表/剔除表_索引.md`。",
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
            out_dir / fname,
            title=f"池 1 · {arch_zh}（{arch_id}）",
            generated=generated,
            review_rows=rows,
            template_count=sum(int(r.get("slot_count") or 0) for r in rows),
            columns=columns,
            dedupe_note=DEDUPE_NOTE_NAME_EN,
            extra_lines=["> 已去掉剔除项（见 `../筛选后槽表/剔除表_索引.md`）；全量见上级 `捐池_原槽表/`。"],
        )

    (out_dir / "捐皮池表_池1_索引.md").write_text("\n".join(index_lines) + "\n", encoding="utf-8")
    (out_dir / "捐皮池表_池1_trash.md").write_text(
        "\n".join(
            [
                "# 池 1 · 路边小怪（已过滤）",
                "",
                f"生成：{generated}",
                "",
                "本池已按 archetype 拆分，见 **`捐皮池表_池1_索引.md`**。",
                "",
                f"审阅行合计：{len(review_rows)} · 模板：{template_count}",
                "",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


_EXCLUDE_FILES: dict[str, tuple[str, str, str]] = {
    "dummy": (
        "剔除_测试Dummy.md",
        "# 剔除 · 测试 Dummy / BuddyStone / Bonfire",
        "> 规则：测试 model 壳（c0100/c011x/c0130/c800x）· Npc/实体名含 Dummy · BuddyStone/Bonfire",
    ),
    "deer": (
        "剔除_鹿.md",
        "# 剔除 · 鹿（被动动物）",
        "> 规则：model c6010 · 或 Npc 名 Deer / 中文名 鹿",
    ),
    "critter": (
        "剔除_小动物.md",
        "# 剔除 · 小动物 / 被动动物",
        "> 规则：小螃蟹 c2271/c2270低HP · `passive_animal_model_prefixes`（鹰/猪/兔/羊等）· 鹿 c6010",
    ),
    "merchant": (
        "剔除_商人.md",
        "# 剔除 · 商人 / 驴 / 洞窟游牧商",
        "> 规则：model c3200/c3201/c3210 · 或英文名含 Merchant/Nomad Trader/Frenzied Nomad · 中文含 商人/流浪商",
    ),
    "horse": (
        "剔除_战马.md",
        "# 剔除 · 独立战马",
        "> 规则：仅 `horse_mount_model_prefixes` · 英文名 Horse/Steed · 中文 战马/灵马/的马（不含成套骑手）",
    ),
    "scarab": (
        "剔除_圣甲虫.md",
        "# 剔除 · 圣甲虫",
        "> 规则：`scarab_model_prefixes`（c4190/c4191/c4192/c6201）· 英文名含 Scarab · 中文含 圣甲虫",
    ),
    "mausoleum": (
        "剔除_灵庙.md",
        "# 剔除 · 漫步灵庙",
        "> 规则：`mausoleum_model_prefixes`（c4450）· 英文名 Walking Mausoleum · 中文 漫步灵庙（不含灵庙士兵/骑士）",
    ),
    "talk": (
        "剔除_对话Npc.md",
        "# 剔除 · 剧情/对话 Npc",
        "> 规则：`is_talk_npc_id`（NpcParam 对话 sp / 剧情特征）· 门卫葛托克英文名兜底",
    ),
    "manual": (
        "剔除_审阅手工.md",
        "# 剔除 · 审阅手工指定",
        "> 规则：见 `cnv_randomizer/donor_pool_review_manual_excludes.json`（按 npc id）",
    ),
}

_LEGACY_EXCLUDE_FILENAMES: tuple[str, ...] = (
    "排除_测试Dummy.md",
    "排除_鹿.md",
    "排除_商人.md",
)

_EXCLUDE_INDEX_LABELS: dict[str, str] = {
    "dummy": "测试 Dummy",
    "deer": "鹿",
    "critter": "小动物",
    "merchant": "商人",
    "horse": "独立战马",
    "scarab": "圣甲虫",
    "mausoleum": "漫步灵庙",
    "talk": "对话 Npc",
    "manual": "审阅手工",
}


def _write_excluded_md(
    excluded: list[dict[str, Any]],
    generated: str,
) -> list[Path]:
    by_bucket: dict[str, list[dict[str, Any]]] = {k: [] for k in _EXCLUDE_FILES}
    for row in excluded:
        bucket = str(row.get("exclude_bucket") or "dummy")
        by_bucket.setdefault(bucket, []).append(row)

    paths: list[Path] = []
    for bucket, (fname, title, rule_line) in _EXCLUDE_FILES.items():
        rows = by_bucket.get(bucket, [])
        path = FILTERED_SLOT_REVIEW_DIR / fname
        lines = [
            title,
            "",
            f"生成：{generated}",
            f"合计：{len(rows)} 行（从筛选后捐池表挪出；全量对照见 `../捐皮池表_1-7.json`）",
            "",
            rule_line,
            "",
        ]
        if rows:
            lines.extend(_md_table(rows, COLS_EXCLUDED))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        paths.append(path)

    for legacy in _LEGACY_EXCLUDE_FILENAMES:
        legacy_path = FILTERED_SLOT_REVIEW_DIR / legacy
        if legacy_path.is_file():
            legacy_path.unlink()

    index_path = _write_exclude_index(generated, by_bucket, paths)
    paths.append(index_path)
    return paths


def _write_exclude_index(
    generated: str,
    by_bucket: dict[str, list[dict[str, Any]]],
    detail_paths: list[Path],
) -> Path:
    total = sum(len(rows) for rows in by_bucket.values())
    path = FILTERED_SLOT_REVIEW_DIR / "剔除表_索引.md"
    lines = [
        "# 剔除表索引",
        "",
        f"生成：{generated}",
        f"合计：**{total}** 行（不删原数据，只从 `../筛选后捐池表/` 挪出）",
        "",
        "| 层级 | 目录/文件 | 说明 |",
        "| --- | --- | --- |",
        "| 全量原表 | `../捐皮池表_*.md` | 永不改动，含鹿/商人/Dummy |",
        "| 筛选后捐池 | `../筛选后捐池表/` | 审阅用，已去掉下列剔除项 |",
        "| 剔除表 | `剔除_*.md`（本目录） | 被挪出的行，带排除原因 |",
        "",
        "## 分类明细",
        "",
        "| 序号 | 类别 | 行数 | 文件 |",
        "| ---: | --- | ---:|---|",
    ]
    for i, bucket in enumerate(_EXCLUDE_FILES, start=1):
        fname = _EXCLUDE_FILES[bucket][0]
        label = _EXCLUDE_INDEX_LABELS.get(bucket, bucket)
        lines.append(f"| {i} | {label} | {len(by_bucket.get(bucket, []))} | `{fname}` |")

    lines.extend(
        [
            "",
            "> 重跑：`python _filter_donor_pool_review.py`（只刷新筛选后目录，不动全量原表）",
            "",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main() -> None:
    ensure_donor_review_dirs()
    json_path = DONOR_POOL_REVIEW_DIR / "捐皮池表_1-7.json"
    if not json_path.is_file():
        raise SystemExit(f"缺少全量 JSON，请先运行 _build_donor_pool_tables_1_7.py：{json_path}")

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    archetype_index = core.load_archetype_index()

    pool_count = len(core.CATEGORY_ORDER)
    review_by_pool: dict[int, list[dict[str, Any]]] = {n: [] for n in range(1, pool_count + 1)}
    excluded_all: list[dict[str, Any]] = []

    for n in range(1, pool_count + 1):
        pool = payload.get("pools", {}).get(str(n), {})
        raw_rows = list(pool.get("review_rows") or [])
        # 若 JSON 曾被拆过，合并 excluded 再统一过滤
        raw_rows.extend(pool.get("review_rows_excluded") or [])
        kept, excluded = split_review_rows(raw_rows)
        review_by_pool[n] = kept
        excluded_all.extend(excluded)

    md: list[str] = [
        "# 捐皮池表 1～6（已过滤 · 审阅用）",
        "",
        f"**生成**：{generated}  ",
        f"**全量源**：`../捐皮池表_1-7.json`  ",
        f"**已剔除**：{len(excluded_all)} 行 → `../筛选后槽表/剔除表_索引.md`  ",
        "",
        "> 本目录为筛选后捐皮审阅表；剔除行在 `筛选后槽表/`，全量原表在 `捐池_原槽表/` **勿改**。",
        "",
        "## 池概览",
        "",
        "| 序号 | 池 | 类 | 模板数 | 审阅行(过滤后) | compat入池 |",
        "|---:|---:|---|---:|---:|---:|",
    ]
    for n in range(1, pool_count + 1):
        cat = core.CATEGORY_ORDER[n - 1]
        pool = payload.get("pools", {}).get(str(n), {})
        md.append(
            f"| {n} | {core.CATEGORY_DISPLAY_ZH.get(cat, cat)} | {pool.get('count', 0)} | "
            f"{len(review_by_pool[n])} | {pool.get('in_prep', 0)} |"
        )

    md.extend(
        [
            "",
            "## 池 1 拆分",
            "",
            "见 **`捐皮池表_池1_索引.md`**。",
            "",
        ]
    )

    for n in range(2, pool_count + 1):
        cat = core.CATEGORY_ORDER[n - 1]
        cat_zh = core.CATEGORY_DISPLAY_ZH.get(cat, cat)
        review_rows = review_by_pool[n]
        pool = payload.get("pools", {}).get(str(n), {})
        md.extend(
            [
                "",
                f"## 池 {n} · {cat_zh}（过滤后 {len(review_rows)} / 模板 {pool.get('count', 0)}）",
                "",
            ]
        )
        if review_rows:
            md.extend(_md_table(review_rows, COLS_OTHER))
        dedupe_note = DEDUPE_NOTE_NAME_EN
        _write_pool_md(
            FILTERED_DONOR_REVIEW_DIR / f"捐皮池表_池{n}_{cat}.md",
            title=f"池 {n} · {cat_zh}（已过滤）",
            generated=generated,
            review_rows=review_rows,
            template_count=int(pool.get("count") or 0),
            columns=COLS_OTHER,
            dedupe_note=dedupe_note,
            extra_lines=["> 已去掉剔除项（见 `../筛选后槽表/剔除表_索引.md`）。"],
        )

    pool1 = payload.get("pools", {}).get("1", {})
    _write_pool1_split_to(
        FILTERED_DONOR_REVIEW_DIR,
        review_by_pool[1],
        int(pool1.get("count") or 0),
        generated,
        archetype_index,
        COLS_POOL1,
    )

    excluded_paths = _write_excluded_md(excluded_all, generated)
    summary_path = FILTERED_DONOR_REVIEW_DIR / "捐皮池表_1-7.md"
    summary_path.write_text("\n".join(md) + "\n", encoding="utf-8")

    bucket_counts = Counter(r.get("exclude_bucket", "dummy") for r in excluded_all)
    print(f"excluded_total={len(excluded_all)} dummy={bucket_counts.get('dummy', 0)} "
          f"deer={bucket_counts.get('deer', 0)} merchant={bucket_counts.get('merchant', 0)} "
          f"manual={bucket_counts.get('manual', 0)}")
    for n in range(1, pool_count + 1):
        c = Counter(r["model"] for r in review_by_pool[n])
        print(f"  pool{n} kept={len(review_by_pool[n])} models={len(c)}")
    print(f"Wrote {summary_path}")
    for p in excluded_paths:
        print(f"Wrote {p}")

    from donor_pool_review_allowlist import export_allowlist_json

    allow_path = export_allowlist_json()
    print(f"Wrote {allow_path}")


if __name__ == "__main__":
    main()
