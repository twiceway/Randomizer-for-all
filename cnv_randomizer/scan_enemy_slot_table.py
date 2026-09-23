"""离线扫全图 MSB → 敌人槽位全量表（T-077）。与主程序生成/apply 无关。

用法:
  python scan_enemy_slot_table.py              # 全图重扫 + 建表
  python scan_enemy_slot_table.py --map m10_00_00_00   # 仅从已有 raw 快照筛一张图（快）
  python scan_enemy_slot_table.py --no-rescan  # 用 cache/offline/enemy_index.raw.json 重建表
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from paths import SCRIPT_DIR  # frozen-safe
def main() -> int:
    parser = argparse.ArgumentParser(description="Offline MSB scan → enemy_slot_table")
    parser.add_argument(
        "--no-rescan",
        action="store_true",
        help="跳过 MSB 扫描，仅用已有 offline/enemy_index.raw.json",
    )
    parser.add_argument("--max-maps", type=int, default=None, help="调试用：限制扫描图数")
    parser.add_argument(
        "--map",
        dest="map_filter",
        default=None,
        help="只输出单图行（仍需全图 raw；配合 --no-rescan 快筛）",
    )
    parser.add_argument(
        "--skip-zero-npc",
        action="store_true",
        help="扫描时不收录 npc=0 占位槽（默认收录并标 is_zero_npc）",
    )
    args = parser.parse_args()

    sys.path.insert(0, str(SCRIPT_DIR))
    from enemy_slot_table import build_offline_enemy_slot_table

    result = build_offline_enemy_slot_table(
        rescan=not args.no_rescan,
        max_maps=args.max_maps,
        include_zero_npc=not args.skip_zero_npc,
        map_filter=args.map_filter,
    )
    paths = result["paths"]
    meta_path = paths["meta"]
    import json
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    excluded = meta.get("excluded_slot_counts") or {}
    print(
        f"maps_scanned={result.get('maps_scanned')} "
        f"index_slots={result.get('slot_count')} "
        f"table_rows={result.get('table_rows')} "
        f"excluded_animal={excluded.get('animal')} "
        f"excluded_decorative={excluded.get('decorative')} "
        f"excluded_npc={excluded.get('npc')} "
        f"excluded_other={excluded.get('other_skip')} "
        f"fingerprint={result.get('fingerprint')}"
    )
    print(f"table_json={paths['json']}")
    print(f"table_meta={paths['meta']}")
    print(f"table_csv={paths['csv']}")
    for bucket in ("animal", "decorative", "npc", "other_skip"):
        print(f"table_{bucket}_csv={paths[f'{bucket}_csv']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
