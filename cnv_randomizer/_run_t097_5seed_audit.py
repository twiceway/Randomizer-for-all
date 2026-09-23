# -*- coding: utf-8 -*-
"""T-097: run 5 full generates, keep outputs, audit missing / low / high donors."""
from __future__ import annotations

import json
import shutil
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from enemy_randomizer_core import run_enemy_randomize, _load_json
from paths import SCRIPT_DIR

SEEDS = [97001001, 97001002, 97001003, 97001004, 97001005]
BASE = SCRIPT_DIR / "output" / "runtime" / "_t097_5seeds"
REPORT = SCRIPT_DIR.parent / "reports" / "T-097_五次出表捐皮审计.md"
WL = SCRIPT_DIR.parent / "捐皮契约" / "捐皮白名单_当前.json"
CATS = SCRIPT_DIR / "enemy_categories.json"


def _run_one(seed: int) -> Path:
    out = BASE / f"seed_{seed}"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    cfg = _load_json(SCRIPT_DIR / "config.json")
    t0 = time.perf_counter()
    result = run_enemy_randomize(cfg, seed=seed, out_dir=out)
    elapsed = time.perf_counter() - t0
    meta = {
        "seed": seed,
        "elapsed_sec": round(elapsed, 2),
        "replaced": result.slots_replaced,
        "skipped": result.slots_skipped,
        "spawn_map": str(result.spawn_map_path),
        "spoiler": str(result.spoiler_path),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    (out / "run_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"[ok] seed={seed} replaced={result.slots_replaced} "
        f"skipped={result.slots_skipped} elapsed={elapsed:.1f}s -> {out}"
    )
    return out


def _count_donors(spawn_path: Path) -> Counter[str]:
    ctr: Counter[str] = Counter()
    for ln in spawn_path.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = ln.split("\t")
        if len(parts) < 6:
            continue
        d = parts[5].lower().strip()
        if not d or d in {"model", "-1"}:
            continue
        if len(parts) > 4 and str(parts[4]).startswith("cnv:suppress"):
            continue
        ctr[d] += 1
    return ctr


def _audit(seed_dirs: list[Path]) -> str:
    """
    统计口径说明（与 T-097b pool6 诊断的区别）：

    本脚本：按 **model 前缀**（如 c4351、c5680）聚合，统计该模型在前 5 次生成中合计被抽中多少次。
    白名单每一行代表一个 npc_id，但同一 model 前缀下所有 npc_id 共享同一行（合计列）。

    T-097b pool6 诊断：按 **npc_id** 分开统计，适合精确定位「某个具体 npc_id 是否出现」。

    两个视角可互补：model 视角看捐皮池健康度，npc 视角看具体条目是否零捐。
    """
    cats = json.loads(CATS.read_text(encoding="utf-8-sig"))
    size = cats.get("size_tier_by_model_prefix") or {}
    zh = cats.get("model_prefix_display_zh") or {}
    never = [str(x).lower() for x in (cats.get("never_donor_model_prefixes") or [])]
    wl = json.loads(WL.read_text(encoding="utf-8"))

    per_seed: dict[int, Counter[str]] = {}
    totals: Counter[str] = Counter()
    for d in seed_dirs:
        meta = json.loads((d / "run_meta.json").read_text(encoding="utf-8"))
        seed = int(meta["seed"])
        spawn = Path(meta["spawn_map"])
        if not spawn.is_file():
            spawn = d / "cnv_enemy_spawn_map.txt"
        ctr = _count_donors(spawn)
        per_seed[seed] = ctr
        totals.update(ctr)

    # whitelist rows
    rows = []
    for pool, pool_rows in wl.get("rows_by_pool", {}).items():
        for r in pool_rows:
            m = str(r.get("model") or "").lower()
            if not m:
                continue
            nd = any(m.startswith(p) for p in never)
            rows.append(
                {
                    "pool": int(pool),
                    "model": m,
                    "name": r.get("name_zh") or r.get("name_en") or m,
                    "hp": int(r.get("effective_hp") or 0),
                    "tier": size.get(m, "?"),
                    "never": nd,
                    "total": totals.get(m, 0),
                    "per": {s: per_seed[s].get(m, 0) for s in per_seed},
                    "seeds_hit": sum(1 for s in per_seed if per_seed[s].get(m, 0) > 0),
                }
            )

    # peer group = same pool
    by_pool: dict[int, list] = defaultdict(list)
    for r in rows:
        if not r["never"]:
            by_pool[r["pool"]].append(r)

    pool_med: dict[int, float] = {}
    for pool, lst in by_pool.items():
        vals = sorted(x["total"] for x in lst)
        if not vals:
            pool_med[pool] = 0.0
            continue
        mid = len(vals) // 2
        pool_med[pool] = (
            float(vals[mid])
            if len(vals) % 2
            else (vals[mid - 1] + vals[mid]) / 2.0
        )

    never_rows = [r for r in rows if r["never"]]
    zero = [r for r in rows if (not r["never"]) and r["total"] == 0]
    low = []
    high = []
    for r in rows:
        if r["never"]:
            continue
        med = pool_med.get(r["pool"], 0.0) or 0.0
        if med <= 0:
            continue
        ratio = r["total"] / med
        r["pool_median"] = med
        r["ratio"] = ratio
        if r["total"] > 0 and ratio <= 0.25:
            low.append(r)
        elif ratio >= 3.0:
            high.append(r)

    zero.sort(key=lambda x: (x["pool"], -x["hp"], x["model"]))
    low.sort(key=lambda x: (x["ratio"], x["pool"], -x["hp"]))
    high.sort(key=lambda x: (-x["ratio"], x["pool"], -x["hp"]))

    lines: list[str] = []
    lines.append("# T-097 五次出表捐皮审计")
    lines.append("")
    lines.append(f"**生成时间（UTC）**：{datetime.now(timezone.utc).isoformat()}")
    lines.append(f"**种子**：{', '.join(str(s) for s in SEEDS)}")
    lines.append(f"**留存目录**：`cnv_randomizer/output/runtime/_t097_5seeds/`")
    lines.append("")
    lines.append("## 各次概况")
    lines.append("")
    lines.append("| 种子 | 替换数 | 跳过 | 耗时秒 | 独特捐皮模型 |")
    lines.append("|---:|---:|---:|---:|---:|")
    for d in seed_dirs:
        meta = json.loads((d / "run_meta.json").read_text(encoding="utf-8"))
        seed = int(meta["seed"])
        lines.append(
            f"| {seed} | {meta['replaced']} | {meta['skipped']} | "
            f"{meta['elapsed_sec']} | {len(per_seed[seed])} |"
        )
    lines.append("")
    lines.append(
        f"**五次合计独特模型**：{len(totals)} · **白名单行**：{len(rows)} · "
        f"**仍 never_donor**：{len(never_rows)}"
    )
    lines.append("")

    lines.append("## A. 规则仍禁捐（白名单里却 never_donor）")
    lines.append("")
    if not never_rows:
        lines.append("（无）")
    else:
        lines.append("| 池 | 中文 | model | 体型 | 五次合计 |")
        lines.append("|---:|:---|:---|:---|---:|")
        for r in never_rows:
            lines.append(
                f"| {r['pool']} | {r['name']} | `{r['model']}` | {r['tier']} | {r['total']} |"
            )
    lines.append("")

    lines.append("## B. 可捐但五次全 0（没捐到）")
    lines.append("")
    lines.append(f"共 **{len(zero)}** 种。")
    lines.append("")
    if zero:
        lines.append("| 池 | 中文 | model | 体型 | 有效HP |")
        lines.append("|---:|:---|:---|:---|---:|")
        for r in zero[:80]:
            lines.append(
                f"| {r['pool']} | {r['name']} | `{r['model']}` | {r['tier']} | {r['hp']} |"
            )
        if len(zero) > 80:
            lines.append(f"| … | 另有 {len(zero) - 80} 种 | | | |")
    lines.append("")

    lines.append("## C. 同类偏低（同池合计 ≤ 该池中位数的 25%，且 >0）")
    lines.append("")
    lines.append(f"共 **{len(low)}** 种。")
    lines.append("")
    if low:
        lines.append("| 池 | 中文 | model | 体型 | 五次合计 | 池中位数 | 比例 | 命中种子数 |")
        lines.append("|---:|:---|:---|:---|---:|---:|---:|---:|")
        for r in low[:60]:
            lines.append(
                f"| {r['pool']} | {r['name']} | `{r['model']}` | {r['tier']} | "
                f"{r['total']} | {r['pool_median']:.0f} | {r['ratio']:.2f} | {r['seeds_hit']}/5 |"
            )
    lines.append("")

    lines.append("## D. 同类偏高（同池合计 ≥ 该池中位数的 3 倍）")
    lines.append("")
    lines.append(f"共 **{len(high)}** 种。")
    lines.append("")
    if high:
        lines.append("| 池 | 中文 | model | 体型 | 五次合计 | 池中位数 | 比例 | 命中种子数 |")
        lines.append("|---:|:---|:---|:---|---:|---:|---:|---:|")
        for r in high[:60]:
            lines.append(
                f"| {r['pool']} | {r['name']} | `{r['model']}` | {r['tier']} | "
                f"{r['total']} | {r['pool_median']:.0f} | {r['ratio']:.2f} | {r['seeds_hit']}/5 |"
            )
    lines.append("")

    lines.append("## E. T-097 关心：大型 / 超巨 / 主线Boss体型")
    lines.append("")
    lines.append("| 中文 | model | 体型 | 五次合计 | 各种子 | 状态 |")
    lines.append("|:---|:---|:---|---:|:---|:---|")
    focus = [
        r
        for r in rows
        if r["tier"] in {"large", "colossal", "boss"}
        or r["model"] in {"c2150", "c2030", "c2031", "c5270"}
    ]
    focus.sort(key=lambda x: (-x["total"], x["pool"], x["model"]))
    for r in focus:
        per = "/".join(str(r["per"][s]) for s in SEEDS)
        if r["never"]:
            st = "规则禁捐"
        elif r["total"] == 0:
            st = "可捐但五次0"
        else:
            st = "有捐"
        lines.append(
            f"| {r['name']} | `{r['model']}` | {r['tier']} | {r['total']} | {per} | {st} |"
        )
    lines.append("")

    lines.append("## F. 各池中位数（五次合计，排除 never_donor）")
    lines.append("")
    lines.append("| 池 | 可捐种数 | 中位数合计次数 |")
    lines.append("|---:|---:|---:|")
    for pool in sorted(by_pool):
        lines.append(
            f"| {pool} | {len(by_pool[pool])} | {pool_med.get(pool, 0):.0f} |"
        )
    lines.append("")

    # machine json sidecar
    payload = {
        "口径说明": "按 model 前缀聚合（同一 model 下所有 npc_id 合计一行）；T-097b pool6 诊断按 npc_id 分开",
        "seeds": SEEDS,
        "totals": dict(totals),
        "zero_donatable": [
            {"pool": r["pool"], "model": r["model"], "name": r["name"], "tier": r["tier"]}
            for r in zero
        ],
        "low": [
            {
                "pool": r["pool"],
                "model": r["model"],
                "name": r["name"],
                "total": r["total"],
                "median": r["pool_median"],
                "ratio": r["ratio"],
            }
            for r in low
        ],
        "high": [
            {
                "pool": r["pool"],
                "model": r["model"],
                "name": r["name"],
                "total": r["total"],
                "median": r["pool_median"],
                "ratio": r["ratio"],
            }
            for r in high
        ],
        "never_on_whitelist": [
            {"pool": r["pool"], "model": r["model"], "name": r["name"]}
            for r in never_rows
        ],
    }
    (BASE / "audit_summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    BASE.mkdir(parents=True, exist_ok=True)
    dirs: list[Path] = []
    for seed in SEEDS:
        dirs.append(_run_one(seed))
    md = _audit(dirs)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(md, encoding="utf-8")
    (BASE / "README.md").write_text(
        f"T-097 五次出表留存\n\n种子：{SEEDS}\n\n审计报告：`reports/T-097_五次出表捐皮审计.md`\n",
        encoding="utf-8",
    )
    print(f"Wrote {REPORT}")
    print(f"Kept under {BASE}")


if __name__ == "__main__":
    main()
