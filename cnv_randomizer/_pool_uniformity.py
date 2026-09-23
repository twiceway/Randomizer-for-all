"""同池出场均匀度：σ + Top10/End10 均比。"""
from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from _pool_share_stats import donor_npc_from_spawn, top_end_band

SPAWN = Path("output/runtime/cnv_enemy_spawn_map.txt")
WL = Path("../捐皮契约/捐皮白名单_当前.json")
TGT = {
    "trash": 1,
    "elite": 2,
    "minor_boss": 3,
    "evergaol": 4,
    "night": 5,
    "major_boss": 6,
}
ZH = {
    1: "P1路边",
    2: "P2精英",
    3: "P3洞Boss",
    4: "P4场地",
    5: "P5红灵",
    6: "P6主线",
}
BAND_N = 10


def main() -> None:
    wl = json.loads(WL.read_text(encoding="utf-8"))
    wl_pool: dict[int, set[str]] = defaultdict(set)
    for ps, rows in wl.get("rows_by_pool", {}).items():
        for r in rows:
            wl_pool[int(ps)].add(str(r["npc"]))

    by_tgt: dict[str, Counter[str]] = defaultdict(Counter)
    seed = ""
    for line in SPAWN.read_text(encoding="utf-8").splitlines():
        if line.startswith("seed="):
            seed = line.split("=", 1)[1]
        elif line and not line.startswith("#") and "\t" in line:
            p = line.split("\t")
            if len(p) >= 13:
                tgt = p[3]
                by_tgt[tgt][donor_npc_from_spawn(p, tgt)] += 1

    print(f"seed {seed}")
    print(
        f"池      槽位  皮数 WL  覆盖   理想%   σ%  T{BAND_N}均%  E{BAND_N}均%  均比"
    )
    for tgt in ["trash", "elite", "minor_boss", "evergaol", "night", "major_boss"]:
        p = TGT[tgt]
        c = by_tgt[tgt]
        n = sum(c.values())
        k = len(c)
        wl_n = {x for x in wl_pool[p]}
        app = wl_n & set(c.keys())
        pcts_wl = [100 * c[x] / n for x in app] if n and app else []
        sd = statistics.pstdev(pcts_wl) if len(pcts_wl) > 1 else 0.0
        ideal = 100 / len(app) if app else 0.0
        band = top_end_band(c, n, n=BAND_N)
        print(
            f"{ZH[p]:<8} {n:>4} {k:>4} {len(wl_n):>3} "
            f"{len(app):>2}/{len(wl_n):<2} {ideal:>5.2f} {sd:>5.2f} "
            f"{band.top_avg_pct:>6.2f} {band.end_avg_pct:>6.2f} {band.ratio:>5.2f}"
        )


if __name__ == "__main__":
    main()
