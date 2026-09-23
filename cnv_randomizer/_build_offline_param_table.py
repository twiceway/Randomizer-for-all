# -*- coding: utf-8 -*-
"""Rebuild 捐皮契约/离线参数大表.json from CNV Game/csv (full NpcParam).

用法:
  python _build_offline_param_table.py

覆盖「仅地图捐皮模板」旧快照；真源为法魂 csv（非未改装原版）。
"""
from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from dlc_donor_pool import (  # noqa: E402
    combat_hp_detailed,
    fmt_hp_mult,
    load_sp_hp_rates,
    npc_effective_hp_for_review,
)
from paths import REPO_ROOT  # noqa: E402

GAME_CSV = Path(r"V:/games/Elden Ring/Game/csv")
OUT_JSON = REPO_ROOT / "捐皮契约" / "离线参数大表.json"
OUT_MD = REPO_ROOT / "捐皮契约" / "离线参数大表.md"
NAME_ZH_PATH = SCRIPT_DIR / "npc_param_name_zh.json"

THINK_KEYS = (
    "eye_dist",
    "searchEye_dist",
    "nose_dist",
    "ear_dist",
    "maxBackhomeDist",
    "backhomeDist",
    "backhomeBattleDist",
    "BattleStartDist",
    "SightTargetForgetTime",
    "battleGoalID",
)


def _i(v: Any, default: int = 0) -> int:
    try:
        return int(float(str(v).strip()))
    except (TypeError, ValueError):
        return default


def _f(v: Any, default: float = 0.0) -> float:
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return default


def _load_name_zh() -> dict[str, str]:
    if not NAME_ZH_PATH.is_file():
        return {}
    raw = json.loads(NAME_ZH_PATH.read_text(encoding="utf-8"))
    names = raw.get("names") or {}
    return {str(k).strip(): str(v).strip() for k, v in names.items() if str(k).strip()}


def _load_csv(path: Path) -> dict[int, dict[str, str]]:
    out: dict[int, dict[str, str]] = {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            try:
                nid = int(row["ID"])
            except (TypeError, ValueError, KeyError):
                continue
            out[nid] = row
    return out


def main() -> None:
    npc_path = GAME_CSV / "NpcParam.csv"
    think_path = GAME_CSV / "NpcThinkParam.csv"
    if not npc_path.is_file():
        raise SystemExit(f"missing {npc_path}")

    npc_by_id = _load_csv(npc_path)
    think_by_id = _load_csv(think_path) if think_path.is_file() else {}
    sp_rates = load_sp_hp_rates(GAME_CSV)
    name_zh_map = _load_name_zh()

    rows: list[dict[str, Any]] = []
    for nid, row in sorted(npc_by_id.items()):
        model = f"c{nid // 10000}" if nid >= 10000 else ""
        pick = npc_effective_hp_for_review(
            nid,
            row,
            model=model,
            sp_rates=sp_rates,
            npc_by_id=npc_by_id,
        )
        eff_direct, mult, parts = combat_hp_detailed(row, sp_rates)
        name_en = str(row.get("Name") or "").strip()
        name_zh = name_zh_map.get(name_en, "")
        think = think_by_id.get(nid) or {}
        think_out = {k: _f(think.get(k)) for k in THINK_KEYS if think}
        entry: dict[str, Any] = {
            "npc": nid,
            "model": model,
            "name_en": name_en,
            "name_zh": name_zh,
            "table_hp": _i(row.get("hp")),
            "effective_hp": int(pick.get("effective_hp") or 0),
            "effective_hp_direct": int(eff_direct or 0),
            "hp_mult": round(float(mult), 6),
            "hp_mult_desc": str(pick.get("hp_mult_desc") or fmt_hp_mult(parts, mult)),
            "proxy_npc": int(pick.get("proxy_npc") or 0) or None,
            "getSoul": _i(row.get("getSoul")),
            "isSoulGetByBoss": str(row.get("isSoulGetByBoss") or ""),
            "defFlickPower": _i(row.get("defFlickPower")),
            "stamina": _i(row.get("stamina")),
            "def_phys": _i(row.get("def_phys")),
            "def_mag": _i(row.get("def_mag")),
            "def_fire": _i(row.get("def_fire")),
            "def_thunder": _i(row.get("def_thunder")),
            "def_dark": _i(row.get("def_dark")),
            "resist_poison": _i(row.get("resist_poison")),
            "resist_desease": _i(row.get("resist_desease")),
            "resist_blood": _i(row.get("resist_blood")),
            "resist_curse": _i(row.get("resist_curse")),
            "resist_sleep": _i(row.get("resist_sleep")),
            "resist_madness": _i(row.get("resist_madness")),
            "think_id_matched": nid if think else None,
            "think": think_out or None,
        }
        rows.append(entry)

    payload = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "schema": "offline_param_table_v2",
        "definition": (
            "法魂 Convergence Game/csv 全量 NpcParam 离线快照；"
            "effective_hp 用 npc_effective_hp_for_review（可代理/同族回填）；"
            "effective_hp_direct 为该行表血×身上加血 sp 连乘；"
            "think 按同 ID 左联 NpcThinkParam（无则 null）。"
            "非未改装原版艾尔登法环。"
        ),
        "sources": {
            "NpcParam": str(npc_path),
            "NpcThinkParam": str(think_path) if think_path.is_file() else None,
            "SpEffectParam": str(GAME_CSV / "SpEffectParam.csv"),
        },
        "counts": {
            "npc_rows": len(rows),
            "think_joined": sum(1 for r in rows if r.get("think")),
            "effective_hp_gt0": sum(1 for r in rows if int(r.get("effective_hp") or 0) > 0),
        },
        "rows": rows,
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    c = payload["counts"]
    OUT_MD.write_text(
        "\n".join(
            [
                "# 离线参数大表",
                "",
                f"- **文件**：`离线参数大表.json`",
                f"- **生成时间**：{payload['generated_at']}",
                f"- **schema**：`{payload['schema']}`",
                f"- **Npc 行数**：{c['npc_rows']}",
                f"- **已联 Think**：{c['think_joined']}",
                f"- **有效血>0**：{c['effective_hp_gt0']}",
                f"- **来源**：`{npc_path}` + `NpcThinkParam` + `SpEffectParam`",
                "- **口径**：法魂 Convergence 参数导出（**不是**未改装原版）",
                "- **重扫命令**：`python cnv_randomizer/_build_offline_param_table.py`",
                "",
                "旧版「仅地图捐皮模板」快照仍保留在 `捐池_原槽表/捐皮池表_1-7.json`。",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print("wrote", OUT_JSON, "rows", len(rows), "bytes", OUT_JSON.stat().st_size)
    print("wrote", OUT_MD)


if __name__ == "__main__":
    main()
