"""导出捐皮契约「中型及以上」体型 × NpcParam 碰撞体对照审计表。

用法:
  python _export_contract_size_collision_audit.py

输出:
  捐皮契约/体型碰撞审计_当前.md
  捐皮契约/体型碰撞审计_当前.json

口径:
  - 中型及以上 = size_tier rank ≥ 3（中型/高型/大型/超巨/飞行/主线Boss）
  - 碰撞体 = enemy_size_tiers.json 内同 model 前缀 chr_hit_radius/height 最大值
  - 「自动档」= 去掉 MANUAL_TIER 后按 build_size_tier_table 规则重算，与现档不一致则标 ⚠
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import enemy_randomizer_core as core  # noqa: E402
from build_size_tier_table import (  # noqa: E402
    MANUAL_TIER,
    aggregate_npcparam,
    classify_prefix,
    load_categories,
    mounted_rider_prefixes,
)
from enemy_category_rules import size_tier_rank_map  # noqa: E402
from paths import DONOR_POOL_CONTRACT_DIR  # noqa: E402

WL_JSON = DONOR_POOL_CONTRACT_DIR / "捐皮白名单_当前.json"
BL_JSON = DONOR_POOL_CONTRACT_DIR / "捐皮黑名单_当前.json"
SIZE_TIERS_JSON = SCRIPT_DIR / "enemy_size_tiers.json"
NPC_CSV = Path(r"V:\games\Elden Ring\Game\csv\NpcParam.csv")
OUT_MD = DONOR_POOL_CONTRACT_DIR / "体型碰撞审计_当前.md"
OUT_JSON = DONOR_POOL_CONTRACT_DIR / "体型碰撞审计_当前.json"

MEDIUM_PLUS_MIN_RANK = 3


def _load_prefix_metrics() -> dict[str, dict[str, Any]]:
    if not SIZE_TIERS_JSON.is_file():
        return {}
    data = json.loads(SIZE_TIERS_JSON.read_text(encoding="utf-8"))
    out: dict[str, dict[str, Any]] = {}
    for row in data.get("models") or []:
        prefix = str(row.get("prefix") or "").lower()
        if prefix:
            out[prefix] = row
    return out


def _flatten_contract_rows(path: Path, list_name: str) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    for pool, pool_rows in (data.get("rows_by_pool") or {}).items():
        for r in pool_rows:
            rows.append({**r, "pool": int(r.get("pool") or pool), "list": list_name})
    return rows


def _auto_tier_without_manual(
    model: str,
    agg: dict[str, dict[str, Any]],
    *,
    mounted_riders: set[str],
    old_map: dict[str, str],
    force_trash: set[str],
) -> tuple[str, str]:
    mp = str(model or "").lower()
    stats = agg.get(mp)
    if stats is None:
        return old_map.get(mp, "humanoid"), "npcparam_missing"
    saved = MANUAL_TIER.pop(mp, None)
    try:
        return classify_prefix(
            mp,
            stats,
            mounted_riders=mounted_riders,
            old_map=old_map,
            force_trash=force_trash,
        )
    finally:
        if saved is not None:
            MANUAL_TIER[mp] = saved


def _is_medium_plus(tier_id: str) -> bool:
    rank_map = size_tier_rank_map()
    return rank_map.get(tier_id, 1) >= MEDIUM_PLUS_MIN_RANK


def main() -> None:
    rank_map = size_tier_rank_map()
    prefix_metrics = _load_prefix_metrics()
    categories = load_categories()
    old_map = {
        str(k).lower(): str(v)
        for k, v in (categories.get("size_tier_by_model_prefix") or {}).items()
    }
    mounted_riders = mounted_rider_prefixes(categories)
    force_trash = {str(p).lower() for p in categories.get("force_trash_model_prefixes") or []}
    agg = aggregate_npcparam(NPC_CSV) if NPC_CSV.is_file() else {}

    audit_rows: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for list_name, path in (("白名单", WL_JSON), ("黑名单", BL_JSON)):
        for row in _flatten_contract_rows(path, list_name):
            model = str(row.get("model") or "").lower()
            npc = int(row.get("npc") or 0)
            tier_id = str(row.get("size_tier") or "")
            if not tier_id:
                meta = prefix_metrics.get(model) or {}
                tier_id = str(meta.get("tier") or old_map.get(model, "humanoid"))
            if not _is_medium_plus(tier_id):
                continue
            key = (model, npc)
            if key in seen:
                continue
            seen.add(key)
            meta = prefix_metrics.get(model) or {}
            metrics = meta.get("metrics") or {}
            chr_r = metrics.get("chr_hit_radius_max", "")
            chr_h = metrics.get("chr_hit_height_max", "")
            reason = str(meta.get("reason") or "")
            manual = model in MANUAL_TIER or reason == "manual"
            auto_tier, auto_reason = _auto_tier_without_manual(
                model,
                agg,
                mounted_riders=mounted_riders,
                old_map=old_map,
                force_trash=force_trash,
            )
            mismatch = auto_tier != tier_id and not manual
            audit_rows.append(
                {
                    "list": list_name,
                    "pool": int(row.get("pool") or 0),
                    "name_zh": row.get("name_zh", ""),
                    "name_en": row.get("name_en", ""),
                    "model": model,
                    "npc": npc,
                    "size_tier": tier_id,
                    "size_tier_zh": row.get("size_tier_zh")
                    or (meta.get("label_zh") or tier_id),
                    "tier_rank": rank_map.get(tier_id, 0),
                    "chr_hit_radius_max": chr_r,
                    "chr_hit_height_max": chr_h,
                    "classify_reason": reason,
                    "manual_override": manual,
                    "auto_tier": auto_tier,
                    "auto_reason": auto_reason,
                    "collision_mismatch": mismatch,
                    "effective_hp": row.get("effective_hp", ""),
                }
            )

    audit_rows.sort(
        key=lambda r: (
            -int(r.get("tier_rank") or 0),
            str(r.get("list") or ""),
            int(r.get("pool") or 0),
            -int(r.get("effective_hp") or 0),
            str(r.get("name_zh") or ""),
        )
    )

    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    mismatch_n = sum(1 for r in audit_rows if r.get("collision_mismatch"))
    manual_n = sum(1 for r in audit_rows if r.get("manual_override"))

    OUT_JSON.write_text(
        json.dumps(
            {
                "generated_at": generated,
                "medium_plus_min_rank": MEDIUM_PLUS_MIN_RANK,
                "source_size_tiers": str(SIZE_TIERS_JSON),
                "source_npc_csv": str(NPC_CSV) if NPC_CSV.is_file() else "",
                "row_count": len(audit_rows),
                "manual_override_count": manual_n,
                "collision_mismatch_count": mismatch_n,
                "rows": audit_rows,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    lines = [
        "# 体型碰撞审计（捐皮契约 · 中型及以上）",
        "",
        f"**生成**：{generated}  ",
        f"**条数**：{len(audit_rows)}（白名单+黑名单去重 model+npc；仅 rank≥{MEDIUM_PLUS_MIN_RANK}：中型/高型/大型/超巨/飞行/主线Boss）  ",
        "**碰撞口径**：`NpcParam.csv` 同 model 前缀 **chrHitRadius / chrHitHeight 取 max**（见 `enemy_size_tiers.json`）  ",
        f"**人工钉死**：{manual_n} 条（`build_size_tier_table.MANUAL_TIER` 或 reason=manual，不以自动重算为准）  ",
        f"**自动重算不一致**：{mismatch_n} 条（⚠ 建议人工核对碰撞体或改 MANUAL_TIER）  ",
        "**真源表**：`reports/怪物体型表.md` · 重生成体型表：`python build_size_tier_table.py --sync-categories`  ",
        "**机器可读**：`体型碰撞审计_当前.json`",
        "",
        "> 骑乘（rank=2）未列入本表；若也要审，可另开 rank≥2 导出。",
        "",
        "| 表 | 池 | 中文名 | model | 体型 | chrR | chrH | 分类依据 | 自动档 | 备注 |",
        "|---|---:|:---|:---|:---|---:|---:|:---|:---|:---|",
    ]
    for r in audit_rows:
        flags: list[str] = []
        if r.get("manual_override"):
            flags.append("人工")
        if r.get("collision_mismatch"):
            flags.append("⚠碰撞不符")
        note = " · ".join(flags) if flags else ""
        auto = f"`{r.get('auto_tier')}` ({r.get('auto_reason')})"
        lines.append(
            f"| {r.get('list', '')} | {r.get('pool', '')} | {r.get('name_zh', '')} | "
            f"`{r.get('model', '')}` | {r.get('size_tier_zh', '')} | "
            f"{r.get('chr_hit_radius_max', '')} | {r.get('chr_hit_height_max', '')} | "
            f"{r.get('classify_reason', '')} | {auto} | {note} |"
        )

    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(
        f"wrote {OUT_MD.name} rows={len(audit_rows)} "
        f"mismatch={mismatch_n} manual={manual_n}"
    )
    print(f"wrote {OUT_JSON.name}")


if __name__ == "__main__":
    main()
