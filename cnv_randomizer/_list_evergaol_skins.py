"""List evergaol donor skins (Chinese) — one-off audit."""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from enemy_randomizer_core import is_never_donor_model, resolve_src_category  # noqa: E402
from boss_npc_detect import resolve_entity_category  # noqa: E402

cfg = json.loads((ROOT / "enemy_categories.json").read_text(encoding="utf-8"))
idx = json.loads((ROOT / "cache/enemy_index.json").read_text(encoding="utf-8"))
csv = Path(r"V:\games\Elden Ring\Game\csv")
zh = cfg.get("model_prefix_zh") or {}

by_model: dict[str, int] = defaultdict(int)
for tpl in idx.get("templates", []):
    model = str(tpl.get("model", ""))
    if is_never_donor_model(model, cfg):
        continue
    rules = resolve_src_category(model, cfg)
    cat = resolve_entity_category(
        tpl, categories_cfg=cfg, csv_dir=csv, rules_category=rules
    )
    if cat != "evergaol":
        continue
    prefix = model[:5] if model.startswith("c") and len(model) >= 5 else model
    by_model[prefix] += 1

name_map = {
    "c2500": "熔炉骑士",
    "c3010": "囚犯壳（已禁捐皮）",
    "c3300": "诺克斯剑士壳（已禁捐皮）",
    "c3400": "墓影",
    "c3600": "黑刀之王",
    "c3704": "战斗法师",
    "c4201": "失乡骑士（监牢版）",
    "c4290": "猎犬骑士",
    "c4650": "祖玛古老英雄",
    "c7100": "萨米尔古老英雄（半岛真皮）",
}

print("=== 监牢可捐皮（修后池子，按模型）===")
for prefix in sorted(by_model.keys(), key=lambda x: (-by_model[x], x)):
    label = zh.get(prefix) or name_map.get(prefix, "?")
    print(f"  {prefix}  {label}  （{by_model[prefix]} 条模板）")
print(f"\n共 {len(by_model)} 种皮，{sum(by_model.values())} 条捐皮模板")
