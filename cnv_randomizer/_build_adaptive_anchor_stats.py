"""离线导出 T-062 锚点快照（供审计；运行时直接读 enemy_difficulty.json）。

用法:
  python _build_adaptive_anchor_stats.py
"""
from __future__ import annotations

import json
from pathlib import Path

from enemy_difficulty import adaptive_stat_config, load_difficulty_cfg, tier_stat_multiplier
from enemy_think_difficulty import think_anchor_targets

OUT = Path(__file__).resolve().parent / "cache" / "adaptive_anchor_stats.json"
CATS = ("trash", "elite", "night", "minor_boss", "evergaol", "major_boss")


def main() -> None:
    diff = load_difficulty_cfg()
    cfg = adaptive_stat_config(diff)
    poise_base = cfg.get("poise_anchor_base") or {}
    ref_tier = int(cfg.get("poise_anchor_reference_tier", 5))
    ref_mult = tier_stat_multiplier(ref_tier, diff)

    poise: dict[str, dict[str, float]] = {}
    think: dict[str, dict[str, dict[str, float]]] = {}
    for tier in range(1, 10):
        slot_mult = tier_stat_multiplier(tier, diff)
        ratio = (slot_mult / ref_mult) if ref_mult > 0 else 1.0
        poise[str(tier)] = {
            cat: round(float(poise_base.get(cat, poise_base.get("trash", 28))) * ratio, 2)
            for cat in CATS
        }
        think[str(tier)] = {
            cat: {k: round(float(v), 4) for k, v in think_anchor_targets(tier, cat, difficulty_cfg=diff).items()}
            for cat in CATS
        }

    payload = {
        "schema": "adaptive_anchor_stats_v1",
        "note": "派生自 enemy_difficulty.json；非手填 300 怪",
        "adaptive_lift_power": cfg.get("adaptive_lift_power"),
        "poise_anchor_table_value_space": poise,
        "think_anchor": think,
        "attack_sp_by_tier": cfg.get("attack_sp_by_tier"),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
