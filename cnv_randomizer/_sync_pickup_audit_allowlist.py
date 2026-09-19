# -*- coding: utf-8 -*-
"""增量同步：审计分册 MD → 离线允许表 JSON（主程序用）。

口径（2026-09-06）：
- 进池 = 槽参与洗牌 + 物品可作捐
- 仍受 GUI 分类开关；血瓶/蓝瓶/灵药瓶硬排除
- 后续审计：重跑本脚本即可合并进表（按 channel+seq 覆盖）

用法：
  cd V:\\1_mel\\Ringrandom\\cnv_randomizer
  python _sync_pickup_audit_allowlist.py
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import cnv_randomizer_core as core
from cnv_randomizer_core import iter_slots, load_item_type_index, read_csv
from goods_subcats import (
    FLASK_GOODS_RANGES,
    HARD_EXCLUDE_GOODS_IDS,
    is_flask_goods,
    is_goods_hard_excluded,
)

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
REPORTS = REPO / "reports"
OUT = REPO / "捐皮契约" / "物品槽审计允许表_当前.json"

# 已审计分册（有「审计」列）。pending 分册未列入则不写入 slots。
BOOKLETS: list[tuple[Path, str]] = [
    (REPORTS / "物品槽审计_地光_当前.md", "地光"),
    (REPORTS / "物品槽审计_地图尸体_上_当前.md", "尸体"),
    (REPORTS / "物品槽审计_地图尸体_下_当前.md", "尸体"),
    (REPORTS / "物品槽审计_怪物固定掉落_当前.md", "怪物"),
    (REPORTS / "物品槽审计_箱子_当前.md", "箱子"),
]


def _parse_booklet(path: Path, channel: str) -> list[dict]:
    """解析分册表行。

    MSB 分册（地光/箱子/尸体）：序号|地图|摆点|ton|掉什么|进池？|原因|审计
    怪物分册：序号|ton|敌人/精英|掉什么|进池？|原因|审计
    """
    rows: list[dict] = []
    if not path.is_file():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| "):
            continue
        parts = [x.strip() for x in line.strip().strip("|").split("|")]
        if not parts or not parts[0].isdigit():
            continue
        if channel == "怪物" and len(parts) >= 7:
            rows.append(
                {
                    "channel": channel,
                    "seq": int(parts[0]),
                    "map_id": "",
                    "entity": parts[2][:48],
                    "lot_id": int(parts[1]),
                    "drop_zh": parts[3],
                    "pool": parts[4],
                    "reason": parts[5],
                    "audit": parts[6],
                }
            )
        elif len(parts) >= 8:
            rows.append(
                {
                    "channel": channel,
                    "seq": int(parts[0]),
                    "map_id": parts[1],
                    "entity": parts[2],
                    "lot_id": int(parts[3]),
                    "drop_zh": parts[4],
                    "pool": parts[5],
                    "reason": parts[6],
                    "audit": parts[7],
                }
            )
    return rows


def _flask_and_hard_ids() -> list[int]:
    ids = set(HARD_EXCLUDE_GOODS_IDS)
    for lo, hi in FLASK_GOODS_RANGES:
        for iid in range(lo, hi + 1):
            if is_flask_goods(iid):
                ids.add(iid)
    return sorted(ids)


def _lot_item_ids(rows_by: dict[int, dict], lid: int) -> list[int]:
    row = rows_by.get(lid)
    if not row:
        return []
    out: list[int] = []
    for _, _, _, iid, _ in iter_slots(row):
        if iid > 0:
            out.append(int(iid))
    return out


def main() -> None:
    cfg = core.load_config(ROOT / "config.json")
    csv_dir = Path(cfg["csv_dir"])
    _, map_rows = read_csv(csv_dir / "ItemLotParam_map.csv")
    rows_by = {
        int(r["ID"]): r for r in map_rows if str(r.get("ID", "")).strip().isdigit()
    }
    _ = load_item_type_index(csv_dir)  # 确保 CSV 可读；捐物 id 不依赖 type

    # 增量：先读旧表，再按 channel+seq 覆盖
    prev_slots: dict[tuple[str, int], dict] = {}
    if OUT.is_file():
        old = json.loads(OUT.read_text(encoding="utf-8"))
        for s in old.get("slots") or []:
            prev_slots[(s["channel"], int(s["seq"]))] = s

    for path, channel in BOOKLETS:
        for row in _parse_booklet(path, channel):
            key = (channel, row["seq"])
            wash = row["audit"] == "要洗"
            prev_slots[key] = {
                "channel": channel,
                "seq": row["seq"],
                "map_id": row["map_id"],
                "entity": row["entity"],
                "lot_id": row["lot_id"],
                "audit": row["audit"],
                "slot_participates": wash,
                "item_donates": wash,
            }

    slots_out = sorted(
        prev_slots.values(), key=lambda s: (s["channel"], int(s["seq"]))
    )

    donor_by_item: dict[int, dict] = {}
    n_wash = n_no = 0
    for s in slots_out:
        if s["audit"] == "要洗":
            n_wash += 1
        elif s["audit"] == "不要":
            n_no += 1
        if not s.get("item_donates"):
            continue
        for iid in _lot_item_ids(rows_by, int(s["lot_id"])):
            if is_flask_goods(iid) or is_goods_hard_excluded(iid):
                continue
            d = donor_by_item.setdefault(
                iid,
                {
                    "item_id": iid,
                    "audit": "要洗",
                    "from_lots": set(),
                    "from_channels": set(),
                },
            )
            d["from_lots"].add(int(s["lot_id"]))
            d["from_channels"].add(s["channel"])

    donors_out = []
    for iid, d in sorted(donor_by_item.items()):
        donors_out.append(
            {
                "item_id": iid,
                "audit": d["audit"],
                "from_lots": sorted(d["from_lots"]),
                "from_channels": sorted(d["from_channels"]),
            }
        )

    by_ch: dict[str, int] = {}
    for s in slots_out:
        by_ch[s["channel"]] = by_ch.get(s["channel"], 0) + 1

    corpse_seqs = [int(s["seq"]) for s in slots_out if s["channel"] == "尸体"]
    payload = {
        "schema_version": 1,
        "updated": str(date.today()),
        "purpose": "物品槽审计允许表：主程序用；槽参与 + 物品进池（捐）；审计分册增量合并",
        "rules": {
            "slot_participates": True,
            "item_donates": True,
            "category_switches_apply": True,
            "flask_hard_exclude": True,
            "note": "GUI 分类开关运行时仍限；血瓶/蓝瓶/灵药瓶永不进池",
        },
        "channels": {
            "地光": {
                "status": "audited" if by_ch.get("地光") else "pending",
                "rows": by_ch.get("地光", 0),
            },
            "尸体": {
                "status": "audited" if by_ch.get("尸体") else "pending",
                "rows": by_ch.get("尸体", 0),
                "seq_from": min(corpse_seqs) if corpse_seqs else None,
                "seq_to": max(corpse_seqs) if corpse_seqs else None,
                "note": "上+下册已审并入",
            },
            "怪物": {
                "status": "audited" if by_ch.get("怪物") else "pending",
                "rows": by_ch.get("怪物", 0),
                "note": "除瓶类全要洗；铃珠等一并进池",
            },
            "箱子": {
                "status": "audited" if by_ch.get("箱子") else "pending",
                "rows": by_ch.get("箱子", 0),
                "note": "全要洗（瓶类除外）",
            },
        },
        "stats": {
            "slots_total": len(slots_out),
            "slots_wash": n_wash,
            "slots_deny": n_no,
            "donors_unique_items": len(donors_out),
        },
        "exclude_item_ids_flask_and_hard": _flask_and_hard_ids(),
        "slots": slots_out,
        "donors": donors_out,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote", OUT)
    print("stats", payload["stats"])


if __name__ == "__main__":
    main()
