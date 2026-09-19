#!/usr/bin/env python3
"""T-093：按血量档位挑真实白名单皮，出滑条叠乘报告表。"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from enemy_difficulty import load_difficulty_cfg  # noqa: E402
from enemy_world_progression import compute_slider_lift_mult, t093_config  # noqa: E402
from paths import OUTPUT_REPORTS  # noqa: E402

REPO = SCRIPT_DIR.parent
WHITELIST = REPO / "捐皮契约" / "捐皮白名单_当前.json"
OUT_MD = OUTPUT_REPORTS / "T-093_血量档滑条对照表.md"
SLIDERS = (0.1, 0.5, 1.0, 1.5, 2.0, 5.0)

# 目标血量中心 ± 容差；每档挑 1～2 条代表性皮
BRACKETS: list[tuple[str, int, int, int]] = [
    # label, target, lo, hi
    ("几百血", 600, 400, 800),
    ("约2000", 2000, 1800, 2200),
    ("约5000", 5000, 4500, 5500),
    ("约1万", 10000, 9000, 11000),
    ("约2万", 20000, 18000, 22000),
    ("约3万", 30000, 28000, 35000),
]


def _load_rows() -> list[dict]:
    data = json.loads(WHITELIST.read_text(encoding="utf-8-sig"))
    out: list[dict] = []
    bags = data.get("rows_by_pool") or {}
    for pool, items in bags.items():
        if not isinstance(items, list):
            continue
        for r in items:
            try:
                eh = int(r.get("effective_hp") or 0)
            except (TypeError, ValueError):
                continue
            if eh <= 0:
                continue
            model = str(r.get("model") or "")
            if not model:
                continue
            out.append(
                {
                    "pool": str(pool),
                    "model": model,
                    "name": str(r.get("name_zh") or r.get("name") or model),
                    "npc": int(r.get("npc") or r.get("npc_id") or 0),
                    "effective_hp": eh,
                }
            )
    return out


def _pick(rows: list[dict], lo: int, hi: int, target: int, n: int = 2) -> list[dict]:
    cands = [r for r in rows if lo <= r["effective_hp"] <= hi]
    cands.sort(key=lambda r: (abs(r["effective_hp"] - target), r["model"], r["npc"]))
    picked: list[dict] = []
    seen_model: set[str] = set()
    for r in cands:
        if r["model"] in seen_model:
            continue
        seen_model.add(r["model"])
        picked.append(r)
        if len(picked) >= n:
            break
    return picked


def main() -> int:
    cfg = load_difficulty_cfg()
    t093 = t093_config(cfg)
    href = float(t093.get("lift_h_ref", 2500))
    alpha = float(t093.get("lift_alpha", 0.5))
    rows = _load_rows()

    examples: list[tuple[str, dict]] = []
    for label, target, lo, hi in BRACKETS:
        for r in _pick(rows, lo, hi, target, n=2):
            examples.append((label, r))

    slider_sep = "".join("|---:" for _ in SLIDERS) + "|"
    lines: list[str] = [
        "# T-093 血量档 × 滑条对照表",
        "",
        f"**生成**：{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "## 怎么读",
        "",
        "- 皮来自白名单真实条目；血量 = **白名单有效血**（滑条=1、宁姆地图×1、非夜、周目=1 时的目标血）。",
        "- 下表先按「纯滑条 lift」对比（地图/夜/周目都当 1，方便看血量档差异）。",
        "- 公式：`最终 = 基准血 × lift(s)`；`s=1` 不变；`s>1` 低血加得多；`s<1` 高血降得多。",
        f"- 参考血 h_ref={href:g} · alpha={alpha:g}",
        f"- 滑条：{' / '.join(str(x) for x in SLIDERS)}",
        "",
        "## 总表（最终有效血）",
        "",
        "| 档 | 中文名 | 模型 | 池 | 基准血 | "
        + " | ".join(f"s={s:g}" for s in SLIDERS)
        + " |",
        "|---|---|---|---:|---:" + slider_sep,
    ]

    for label, r in examples:
        h = float(r["effective_hp"])
        cells = [
            label,
            r["name"][:28],
            f"`{r['model']}`",
            str(r["pool"]),
            str(r["effective_hp"]),
        ]
        for s in SLIDERS:
            m = compute_slider_lift_mult(h, s, h_ref=href, alpha=alpha)
            cells.append(str(int(round(h * m))))
        lines.append("| " + " | ".join(cells) + " |")

    lines += [
        "",
        "## 倍率表（相对基准的 lift×）",
        "",
        "| 档 | 中文名 | 模型 | 基准血 | "
        + " | ".join(f"s={s:g}" for s in SLIDERS)
        + " |",
        "|---|---|---|---:" + slider_sep,
    ]
    for label, r in examples:
        h = float(r["effective_hp"])
        cells = [label, r["name"][:28], f"`{r['model']}`", str(r["effective_hp"])]
        for s in SLIDERS:
            m = compute_slider_lift_mult(h, s, h_ref=href, alpha=alpha)
            cells.append(f"{m:.3f}")
        lines.append("| " + " | ".join(cells) + " |")

    # 叠乘示例：同一低/高血皮 × 地图档
    lines += [
        "",
        "## 叠乘例子（矩阵难度）",
        "",
        "`最终 = 白名单血 × 地图倍率 × 夜晚 × 周目(1) × 滑条lift`",
        "",
        "取两张皮：低血≈几百、高血≈2万；再乘宁姆×1 / 亚坛×1.46 / 深渊×3.28。",
        "",
    ]

    lo_ex = next(r for lab, r in examples if lab == "几百血")
    hi_ex = next(r for lab, r in examples if lab == "约2万")
    map_cases = [
        ("宁姆×1.00", 1.0),
        ("亚坛×1.46", 1.46),
        ("深渊×3.28", 3.28),
    ]
    for title, skin in (("低血皮", lo_ex), ("高血皮", hi_ex)):
        lines += [
            f"### {title}：{skin['name']}（`{skin['model']}` · 基准 {skin['effective_hp']}）",
            "",
            "| 地图 | s=0.5 | s=1 | s=2 | s=5 |",
            "|---|---:|---:|---:|---:|",
        ]
        base = float(skin["effective_hp"])
        for mname, map_m in map_cases:
            cells = [mname]
            for s in (0.5, 1.0, 2.0, 5.0):
                pre = base * map_m
                lift = compute_slider_lift_mult(pre, s, h_ref=href, alpha=alpha)
                cells.append(str(int(round(pre * lift))))
            lines.append("| " + " | ".join(cells) + " |")
        lines.append("")

    lines += [
        "## 一眼结论",
        "",
        "- **s=1**：各档都等于基准白名单血（本表未乘地图/夜）。",
        "- **s=2 / s=5**：几百血涨幅远大于 2万/3万（低血加得多）。",
        "- **s=0.1 / s=0.5**：2万/3万掉得更狠（高血降得多）；几百血相对扛得住。",
        "- 再乘地图档后，深渊同皮会整体抬高一截，但 lift 形态不变。",
        "",
    ]

    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {OUT_MD}")
    print(f"examples={len(examples)}")
    for lab, r in examples:
        print(f"  [{lab}] {r['effective_hp']} {r['model']} {r['name']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
