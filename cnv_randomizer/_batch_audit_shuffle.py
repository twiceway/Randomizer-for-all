#!/usr/bin/env python3
"""Generate N shuffle tables and audit each runtime map — find structural ?? risks."""
from __future__ import annotations

import random
import sys
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import cnv_randomizer_core as core
from goods_subcats import (
    is_goods_hard_excluded,
    is_valid_cnv_shuffle_goods,
    is_valid_cnv_shuffle_weapon,
    load_goods_rows,
    load_goods_subcat_index,
    load_weapon_rows,
)
from paths import OUTPUT_REPORTS  # noqa: E402

OUT_PATH = OUTPUT_REPORTS / "batch_shuffle_审计.md"

CAT_LABEL = {
    core.CAT_WEAPON: "weapon",
    core.CAT_GOODS: "goods",
    core.CAT_ARMOR: "armor",
    core.CAT_TALISMAN: "talisman",
    core.CAT_ASH: "ash",
    core.CAT_MAGIC: "magic",
}

CAT_CSV = {
    core.CAT_WEAPON: "EquipParamWeapon.csv",
    core.CAT_ARMOR: "EquipParamProtector.csv",
    core.CAT_TALISMAN: "EquipParamAccessory.csv",
    core.CAT_GOODS: "EquipParamGoods.csv",
    core.CAT_ASH: "EquipParamGem.csv",
    core.CAT_MAGIC: "Magic.csv",
}

# hook v8.7- wrote talisman as armour in lot memory
HOOK_TALISMAN_BUG = "hook_talisman_as_armour"


@dataclass
class AuditContext:
    cfg: dict
    type_index: dict[int, int]
    rows_by_id: dict[int, dict[str, str]]
    param_rows: dict[int, dict[str, dict[str, str]]]  # cat -> id -> row
    pool: set[int]
    named_weapons: set[int]
    named_armor: set[int]
    base_armor: set[int]
    collectible_weapons: set[int]


def load_context() -> AuditContext:
    cfg = core.load_config(ROOT / "config.json")
    cfg["dlc_rules"] = core.load_dlc_rules()
    cfg["dlc_ranges"] = cfg["dlc_rules"]["item_ranges"]
    csv_dir = Path(cfg["csv_dir"])
    goods_rows = load_goods_rows(csv_dir)
    cfg["goods_rows"] = goods_rows
    cfg["goods_subcat_index"] = load_goods_subcat_index(csv_dir)
    cfg["weapon_rows"] = load_weapon_rows(csv_dir)
    cfg["exclude_item_ids"] = set(cfg.get("exclude_item_ids", []))
    for item_id in goods_rows:
        if is_goods_hard_excluded(item_id):
            cfg["exclude_item_ids"].add(item_id)
    from lot_effective import load_lot_effective_items

    cfg["lot_effective_items"] = load_lot_effective_items()

    _, rows = core.read_csv(csv_dir / f"{cfg['target_param']}.csv")
    type_index = core.load_item_type_index(csv_dir)
    pool = core.build_unified_pool(rows, cfg, type_index)
    cfg["shuffle_target_pool"] = set(pool)

    param_rows: dict[int, dict[str, dict[str, str]]] = {}
    for cat, fname in CAT_CSV.items():
        path = csv_dir / fname
        if not path.exists():
            continue
        _, pr = core.read_csv(path)
        param_rows[cat] = {core.parse_int(r.get("ID")): r for r in pr if core.parse_int(r.get("ID")) > 0}

    return AuditContext(
        cfg=cfg,
        type_index=type_index,
        rows_by_id={core.parse_int(r.get("ID")): r for r in rows},
        param_rows=param_rows,
        pool=pool,
        named_weapons=core._named_equipment_ids(
            csv_dir, type_index, core.CAT_WEAPON, "EquipParamWeapon.csv"
        ),
        named_armor=core._named_equipment_ids(
            csv_dir, type_index, core.CAT_ARMOR, "EquipParamProtector.csv"
        ),
        base_armor=core._base_equipment_ids(
            csv_dir, type_index, core.CAT_ARMOR, "EquipParamProtector.csv"
        ),
        collectible_weapons=core._collectible_weapon_ids(csv_dir, rows, type_index),
    )


def param_row(ctx: AuditContext, item_id: int, cat: int) -> dict[str, str] | None:
    return ctx.param_rows.get(cat, {}).get(item_id)


def parse_lot_patches(path: Path) -> list[tuple[int, int, int, int]]:
    lots: list[tuple[int, int, int, int]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("lot "):
            continue
        parts = line.split()
        if len(parts) >= 5:
            lots.append((int(parts[1]), int(parts[2]), int(parts[3]), int(parts[4])))
    return lots


def audit_map(ctx: AuditContext, lot_patches: list[tuple[int, int, int, int]]) -> dict[str, list[tuple]]:
    issues: dict[str, list[tuple]] = defaultdict(list)

    for lot_id, slot, target, target_cat in lot_patches:
        true_cat = ctx.type_index.get(target)
        lot_name = (ctx.rows_by_id.get(lot_id) or {}).get("Name", "")

        if true_cat is None:
            issues["missing_id"].append((lot_id, slot, target, lot_name))
            continue

        if target_cat == core.CAT_TALISMAN:
            issues[HOOK_TALISMAN_BUG].append((lot_id, slot, target, lot_name))

        if true_cat != target_cat:
            issues["cat_mismatch"].append((lot_id, slot, target, true_cat, target_cat, lot_name))

        if target not in ctx.pool:
            issues["not_in_pool"].append((lot_id, slot, target, true_cat, lot_name))

        row = param_row(ctx, target, true_cat)
        name = (row.get("Name") or row.get("name") or "").strip() if row else ""
        nt = core.parse_int(row.get("disableParam_NT")) if row else 0

        if not name:
            issues["empty_name"].append((lot_id, slot, target, true_cat, lot_name))

        if true_cat == core.CAT_GOODS and not is_valid_cnv_shuffle_goods(target, ctx.cfg):
            issues["bad_goods"].append((lot_id, slot, target, lot_name))

        if true_cat == core.CAT_WEAPON and not is_valid_cnv_shuffle_weapon(target, ctx.cfg):
            issues["pseudo_weapon"].append((lot_id, slot, target, lot_name))

        if true_cat == core.CAT_TALISMAN:
            if not name:
                issues["talisman_no_name"].append((lot_id, slot, target, lot_name))
            if nt == 1:
                issues["talisman_nt"].append((lot_id, slot, target, name or "?", lot_name))

        if true_cat == core.CAT_WEAPON and target not in ctx.named_weapons:
            issues["weapon_unnamed"].append((lot_id, slot, target, lot_name))

        if true_cat == core.CAT_ARMOR and target not in ctx.base_armor:
            issues["armor_not_base"].append((lot_id, slot, target, lot_name))

    return issues


def audit_pool(ctx: AuditContext) -> dict[str, list[int]]:
    """Static pool defects — appear in every seed."""
    out: dict[str, list[int]] = defaultdict(list)
    for item_id in sorted(ctx.pool):
        cat = ctx.type_index.get(item_id)
        if cat is None:
            out["pool_missing_id"].append(item_id)
            continue
        row = param_row(ctx, item_id, cat)
        name = (row.get("Name") or row.get("name") or "").strip() if row else ""
        nt = core.parse_int(row.get("disableParam_NT")) if row else 0
        if not name:
            out["pool_empty_name"].append(item_id)
        if cat == core.CAT_TALISMAN and nt == 1:
            out["pool_talisman_nt"].append(item_id)
        if cat == core.CAT_GOODS and not is_valid_cnv_shuffle_goods(item_id, ctx.cfg):
            out["pool_bad_goods"].append(item_id)
        if cat == core.CAT_WEAPON and not is_valid_cnv_shuffle_weapon(item_id, ctx.cfg):
            out["pool_pseudo_weapon"].append(item_id)
        if cat == core.CAT_WEAPON and item_id not in ctx.named_weapons:
            out["pool_weapon_unnamed"].append(item_id)
        if cat == core.CAT_ARMOR and item_id not in ctx.base_armor:
            out["pool_armor_not_base"].append(item_id)
    return out


def run_batch(seeds: list[int], ctx: AuditContext) -> dict:
    per_seed_counts: dict[int, Counter] = {}
    item_hits: dict[str, Counter] = defaultdict(Counter)  # issue -> item_id -> count
    lot_hits: dict[str, Counter] = defaultdict(Counter)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        for seed in seeds:
            cfg = dict(ctx.cfg)
            cfg["seed"] = seed
            map_path = tmp_path / f"map_{seed}.txt"
            core.run_randomize(cfg, runtime_map_path=map_path, deploy=False)
            patches = parse_lot_patches(map_path)
            issues = audit_map(ctx, patches)
            c = Counter({k: len(v) for k, v in issues.items()})
            per_seed_counts[seed] = c
            for kind, rows in issues.items():
                for row in rows:
                    if kind == HOOK_TALISMAN_BUG:
                        item_hits[kind][row[2]] += 1
                        lot_hits[kind][row[0]] += 1
                    elif kind in ("empty_name", "talisman_no_name", "talisman_nt", "bad_goods"):
                        item_hits[kind][row[2]] += 1
                    elif kind == "missing_id":
                        item_hits[kind][row[2]] += 1

    return {
        "per_seed": per_seed_counts,
        "item_hits": item_hits,
        "lot_hits": lot_hits,
    }


def write_report(
    seeds: list[int],
    ctx: AuditContext,
    pool_issues: dict[str, list[int]],
    batch: dict,
) -> None:
    per_seed: dict[int, Counter] = batch["per_seed"]
    item_hits = batch["item_hits"]

    # aggregate averages
    kinds = sorted({k for c in per_seed.values() for k in c})
    avg: dict[str, float] = {}
    for k in kinds:
        avg[k] = sum(per_seed[s].get(k, 0) for s in seeds) / len(seeds)

    lines = [
        "# 多 seed 随机表批量审计",
        "",
        f"- 生成 **{len(seeds)}** 张表（seed: {', '.join(str(s) for s in seeds[:8])}{'…' if len(seeds) > 8 else ''}）",
        f"- 统一池大小：**{len(ctx.pool)}**",
        "",
        "## 这方法能查出什么？",
        "",
        "| 能查 | 不能查 |",
        "|------|--------|",
        "| 每张表固定比例的问题（护符 hook 类型错 → 每张表 87 条） | 真机 UI 贴图缺失 |",
        "| 池子里「无中文名 / NT 禁用」的 ID 会不会被抽到 | 运行时 ID 与 CSV 不一致（需 log） |",
        "| 多 seed 下「必坏」vs「偶发」 | 已修复的 hook bug（修后重跑应归零） |",
        "",
        "## 每张表问题条数（平均）",
        "",
        "| 问题类型 | 含义 | 平均条/表 |",
        "|----------|------|-----------|",
    ]

    desc = {
        HOOK_TALISMAN_BUG: "hook v8.7- 护符写成盔甲 → ?ProtectorName?（v8.8 已修）",
        "talisman_no_name": "护符 ID 无 CSV 名 → 可能 ?AccessoryName?",
        "talisman_nt": "护符 disableParam_NT=1（CNV 可能无效）",
        "empty_name": "任意类别无显示名",
        "bad_goods": "goods NT/硬排除",
        "missing_id": "ID 不在 param 表",
        "cat_mismatch": "runtime map 类别与真类别不一致",
        "not_in_pool": "目标不在统一池（不应出现）",
        "weapon_unnamed": "武器无命名（不应入池）",
        "armor_not_base": "盔甲非基础 tier",
    }
    for k in sorted(avg, key=lambda x: -avg[x]):
        lines.append(f"| `{k}` | {desc.get(k, k)} | **{avg[k]:.1f}** |")

    lines += [
        "",
        "## 静态池缺陷（与 seed 无关，每张表都会抽到）",
        "",
        "| 类型 | 池内条数 | 说明 |",
        "|------|----------|------|",
        f"| pool_talisman_nt | {len(pool_issues['pool_talisman_nt'])} | 护符 NT 禁用仍在池 |",
        f"| pool_empty_name | {len(pool_issues['pool_empty_name'])} | 无 CSV 显示名 |",
        f"| pool_bad_goods | {len(pool_issues['pool_bad_goods'])} | goods 校验不过 |",
        f"| pool_pseudo_weapon | {len(pool_issues['pool_pseudo_weapon'])} | 假武器行仍在池 |",
        f"| pool_weapon_unnamed | {len(pool_issues['pool_weapon_unnamed'])} | 武器无命名 |",
        f"| pool_armor_not_base | {len(pool_issues['pool_armor_not_base'])} | 盔甲非基础 |",
        "",
        "### 池内无名护符（抽到必 ?? 风险）",
        "",
    ]
    for iid in pool_issues["pool_empty_name"]:
        if ctx.type_index.get(iid) == core.CAT_TALISMAN:
            lines.append(f"- `{iid}`")
    if not any(ctx.type_index.get(i) == core.CAT_TALISMAN for i in pool_issues["pool_empty_name"]):
        lines.append("- （无）")

    lines += ["", "### 多 seed 最常命中的无名护符 ID", ""]
    for iid, cnt in item_hits.get("talisman_no_name", Counter()).most_common(15):
        lines.append(f"- `{iid}` — {cnt}/{len(seeds)} 张表出现")

    lines += [
        "",
        "## 各 seed 明细",
        "",
        "| seed | talisman_hook | talisman_no_name | talisman_nt | empty_name | patches |",
        "|------|---------------|------------------|-------------|------------|---------|",
    ]
    for seed in seeds:
        c = per_seed[seed]
        # count patches from talisman_hook + others rough
        patch_est = sum(c.values())  # not exact
        lines.append(
            f"| {seed} | {c.get(HOOK_TALISMAN_BUG, 0)} | "
            f"{c.get('talisman_no_name', 0)} | {c.get('talisman_nt', 0)} | "
            f"{c.get('empty_name', 0)} | ~{patch_est} issues |"
        )

    lines += [
        "",
        "## 结论与下一步",
        "",
        "1. **护符 ?ProtectorName?**：hook 类型映射 bug，与 seed 无关；部署 v8.8 后 `hook_talisman_as_armour` 仍会被审计标出但真机应正常。",
        "2. **其余 ??**：重点收紧 **护符入池**（补 `disableParam_NT` + 非空 `Name` 校验，与 goods 同级）。",
        "3. 真机仍异常时：对照本表 item id + `cnv_pickup_hook.log` 的 runtime raw id。",
        "",
    ]

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    base = int(sys.argv[2]) if len(sys.argv) > 2 else random.randint(1, 999_999_999)
    rng = random.Random(base)
    seeds = [rng.randint(1, 2_000_000_000) for _ in range(n)]

    print(f"Loading context...")
    ctx = load_context()
    pool_issues = audit_pool(ctx)
    print(f"Pool: {len(ctx.pool)} items, empty_name={len(pool_issues['pool_empty_name'])}, "
          f"talisman_nt={len(pool_issues['pool_talisman_nt'])}")

    print(f"Generating {n} tables...")
    batch = run_batch(seeds, ctx)
    write_report(seeds, ctx, pool_issues, batch)
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
