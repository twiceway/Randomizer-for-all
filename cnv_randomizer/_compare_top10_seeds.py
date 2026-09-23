"""三种子对比：各池 Top10/End10 全皮 vs 公平池（排除结构尾皮）。"""

from __future__ import annotations



import json

import subprocess

import sys

from collections import Counter, defaultdict

from pathlib import Path



SCRIPT_DIR = Path(__file__).resolve().parent

CORE = SCRIPT_DIR / "enemy_randomizer_core.py"

SPAWN = SCRIPT_DIR / "output/runtime/cnv_enemy_spawn_map.txt"

WL = SCRIPT_DIR.parent / "捐皮契约/捐皮白名单_当前.json"

CAPS_JSON = SCRIPT_DIR / "cache/pool_npc_slot_caps.json"

CATEGORIES = SCRIPT_DIR / "enemy_categories.json"



sys.path.insert(0, str(SCRIPT_DIR))

from _pool_share_stats import (  # noqa: E402

    donor_npc_from_spawn,

    identify_structural_tail_npcs,

    load_pool_npc_slot_caps,

    top_end_band,

    top_end_band_fair_only,

)



SEEDS = [9363498, 1234567, 889556974]

BAND_N = 10

FOCUS_POOLS = {"trash", "elite", "evergaol", "major_boss"}

TGT_ORDER = ["trash", "elite", "minor_boss", "evergaol", "night", "major_boss"]

POOL_ZH = {

    "trash": "P1",

    "elite": "P2",

    "minor_boss": "P3",

    "evergaol": "P4",

    "night": "P5",

    "major_boss": "P6",

}





def load_names() -> dict[str, str]:

    wl = json.loads(WL.read_text(encoding="utf-8"))

    out: dict[str, str] = {}

    for rows in wl.get("rows_by_pool", {}).values():

        for r in rows:

            out[str(r["npc"])] = str(r.get("name_zh") or r.get("name_en") or r["npc"])

    return out





def parse_spawn() -> tuple[str, dict[str, Counter[str]]]:

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

    return seed, by_tgt





def run_generate(seed: int) -> None:

    subprocess.run(

        [sys.executable, str(CORE), "generate", "--seed", str(seed)],

        cwd=SCRIPT_DIR,

        check=True,

    )





def fmt_npc(npc: str, names: dict[str, str]) -> str:

    return f"{names.get(npc, npc)}({npc})"





def overlap_label(sets: list[set[str]]) -> str:

    if not sets:

        return "—"

    inter = set.intersection(*sets)

    union = set.union(*sets)

    return f"{len(inter)}/{len(union)} 三种子交集/并集"





def main() -> None:

    names = load_names()

    categories_cfg = json.loads(CATEGORIES.read_text(encoding="utf-8"))

    slot_caps = load_pool_npc_slot_caps(CAPS_JSON)

    if not slot_caps:

        print("警告: 无 cache/pool_npc_slot_caps.json，先跑 _audit_npc_slot_caps.py", flush=True)



    tail_by_tgt = {

        tgt: identify_structural_tail_npcs(slot_caps.get(tgt, {}), categories_cfg, tgt)

        for tgt in TGT_ORDER

    }



    per_seed: dict[int, dict[str, dict]] = {}



    for seed in SEEDS:

        print(f"generate seed={seed} ...", flush=True)

        run_generate(seed)

        _, by_tgt = parse_spawn()

        per_seed[seed] = {}

        for tgt in TGT_ORDER:

            counter = by_tgt[tgt]

            total = sum(counter.values())

            all_band = top_end_band(counter, total, n=BAND_N)

            fair_band = top_end_band_fair_only(

                counter, total, tail_by_tgt[tgt], n=BAND_N

            )

            per_seed[seed][tgt] = {

                "top": [n for n, _ in all_band.top],

                "end": [n for n, _ in all_band.end],

                "top_avg": all_band.top_avg_pct,

                "end_avg": all_band.end_avg_pct,

                "ratio": all_band.ratio,

                "fair_top": [n for n, _ in fair_band.top],

                "fair_end": [n for n, _ in fair_band.end],

                "fair_top_avg": fair_band.top_avg_pct,

                "fair_end_avg": fair_band.end_avg_pct,

                "fair_ratio": fair_band.ratio,

            }



    print()

    print(f"三种子 Top{BAND_N}/End{BAND_N} — 全皮 vs 公平池（排除结构尾皮）")

    print("=" * 72)

    for tgt in TGT_ORDER:

        label = POOL_ZH[tgt]

        tail_n = len(tail_by_tgt[tgt])

        print(f"\n## {label}  结构尾皮={tail_n}")

        if tgt in FOCUS_POOLS:

            fair_top_sets = [set(per_seed[s][tgt]["fair_top"]) for s in SEEDS]

            fair_end_sets = [set(per_seed[s][tgt]["fair_end"]) for s in SEEDS]

            print(f"公平池 Top{BAND_N} 交集: {overlap_label(fair_top_sets)}")

            print(f"公平池 End{BAND_N} 交集: {overlap_label(fair_end_sets)}")

            fair_end_inter = set.intersection(*fair_end_sets)

            if fair_end_inter:

                print(

                    "  公平End固定:",

                    "、".join(fmt_npc(n, names) for n in sorted(fair_end_inter, key=int)[:8]),

                )

        top_sets = [set(per_seed[s][tgt]["top"]) for s in SEEDS]

        end_sets = [set(per_seed[s][tgt]["end"]) for s in SEEDS]

        print(f"全皮 Top{BAND_N} 交集: {overlap_label(top_sets)}")

        print(f"全皮 End{BAND_N} 交集: {overlap_label(end_sets)}")

        for seed in SEEDS:

            d = per_seed[seed][tgt]

            print(

                f"  seed {seed}: 全比{d['ratio']:.2f} "

                f"(T{d['top_avg']:.2f}/E{d['end_avg']:.2f}) | "

                f"公平比{d['fair_ratio']:.2f} "

                f"(T{d['fair_top_avg']:.2f}/E{d['fair_end_avg']:.2f})"

            )





if __name__ == "__main__":

    main()

