"""同池出场统计共用：npc 解析、TopN/EndN 聚合。"""
from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from enemy_donor_pick import identify_structural_tail_npcs  # canonical: T-098


def donor_npc_from_spawn(parts: list[str], tgt: str) -> str:
    """spawn 末列 npc 对 synthetic 契约行不可靠，从 template 名解析真 donor。"""
    npc = parts[12]
    tpl = parts[4]
    m = re.match(rf"synthetic:contract_{re.escape(tgt)}_(\d+)$", tpl)
    if m:
        return m.group(1)
    m2 = re.match(
        r"synthetic:contract_(?:trash|elite|minor_boss|evergaol|night|major_boss)_(\d+)$",
        tpl,
    )
    if m2:
        return m2.group(1)
    return npc


@dataclass
class TopEndBand:
    n: int
    top: list[tuple[str, int]]
    end: list[tuple[str, int]]
    top_avg_pct: float
    end_avg_pct: float
    top_sum_pct: float
    end_sum_pct: float
    ratio: float


def top_end_band(
    counter: Counter[str],
    total: int,
    *,
    n: int = 10,
) -> TopEndBand:
    ranked = counter.most_common()
    k = min(n, len(ranked))
    top = ranked[:k]
    end = list(reversed(ranked))[:k]
    top_pcts = [100 * c / total for _, c in top] if total else []
    end_pcts = [100 * c / total for _, c in end] if total else []
    top_avg = sum(top_pcts) / len(top_pcts) if top_pcts else 0.0
    end_avg = sum(end_pcts) / len(end_pcts) if end_pcts else 0.0
    return TopEndBand(
        n=k,
        top=top,
        end=end,
        top_avg_pct=top_avg,
        end_avg_pct=end_avg,
        top_sum_pct=sum(top_pcts),
        end_sum_pct=sum(end_pcts),
        ratio=(top_avg / end_avg) if end_avg > 0 else 0.0,
    )


def top_end_band_fair_only(
    counter: Counter[str],
    total: int,
    tail_npcs: set[str],
    *,
    n: int = 10,
) -> TopEndBand:
    """Top/End 仅在公平池皮上排序；分母=非尾皮出场总和。"""
    fair = Counter({k: v for k, v in counter.items() if k not in tail_npcs})
    fair_total = sum(fair.values())
    if not fair_total:
        return top_end_band(counter, total, n=n)
    return top_end_band(fair, fair_total, n=n)


def load_pool_npc_slot_caps(cache_path: Path) -> dict[str, dict[str, int]]:
    if not cache_path.is_file():
        return {}
    raw = json.loads(cache_path.read_text(encoding="utf-8"))
    out: dict[str, dict[str, int]] = {}
    for tgt, caps in raw.items():
        if isinstance(caps, dict):
            out[tgt] = {str(k): int(v) for k, v in caps.items()}
    return out


def fmt_skin_line(
    npc: str,
    count: int,
    total: int,
    name_by_npc: dict[str, str],
) -> str:
    zh = name_by_npc.get(npc, f"npc {npc}")
    pct = 100 * count / total if total else 0.0
    return f"{zh}（npc {npc}）· {count} 次 · {pct:.2f}%"


def fmt_band_table(
    band: TopEndBand,
    total: int,
    name_by_npc: dict[str, str],
    *,
    title: str,
    rows: list[tuple[str, int]],
) -> list[str]:
    lines = [f"### {title}", "", "| # | 占比 | 次数 | npc | 中文名 |", "|:---:|---:|---:|---:|:---|"]
    for i, (npc, c) in enumerate(rows, start=1):
        zh = name_by_npc.get(npc, f"npc {npc}")
        lines.append(f"| {i} | {100 * c / total:.2f}% | {c} | {npc} | {zh} |")
    lines.append("")
    return lines
