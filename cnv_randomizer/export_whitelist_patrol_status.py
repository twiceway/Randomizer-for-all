"""Export whitelist donor patrol-slot compatibility (T-079).

真源：捐皮契约/捐皮白名单_当前.json（非 enemy_index 全表）。
规则：与 ``_export_donor_msb_state.donor_row`` + ``donor_msb_compat`` 一致。
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from _export_donor_msb_state import donor_row
from _export_slot_initial_state import (
    AERIAL_PREFIXES,
    DECORATIVE_CORPSE_PREFIXES,
    PERCH_PREFIXES,
    SCRIPTED_FLYER_PREFIXES,
    _pref,
)
from donor_msb_compat import compat_entry_for_template, load_donor_slot_compat
from gatefront_quad_catalog import (
    _contract_whitelist_path,
    _load_categories_cfg,
    _resolve_whitelist_donor_template,
    iter_contract_whitelist_rows,
    load_npc_english_names,
)

from paths import SCRIPT_DIR  # frozen-safe
INDEX_PATH = SCRIPT_DIR / "cache" / "enemy_index.json"
OUT_JSON = SCRIPT_DIR.parent / "reports" / "白名单捐皮巡逻状态表.json"
OUT_MD = SCRIPT_DIR.parent / "reports" / "白名单捐皮巡逻状态表.md"
MSB_DONOR_TABLE = SCRIPT_DIR.parent / "reports" / "MSB捐皮初态全表.json"
RULE_VERSION = 2

MSB_EXPORT_KEYS = (
    "walk_route",
    "backup_anim",
    "chr_activate",
    "collision_part",
    "talk_id",
    "donor_placement_kind",
    "donor_msb_class",
)


def _patrol_block_reason(msb: dict, pose: str) -> str:
    model = str(msb.get("model") or "")
    tags = msb.get("template_tags") or {}
    if _pref(model, AERIAL_PREFIXES) or pose == "aerial_model":
        return "飞行模型"
    if _pref(model, SCRIPTED_FLYER_PREFIXES) or _pref(model, ("c6270",)):
        return "脚本飞行"
    if tags.get("needs_summon"):
        return "召唤脚本"
    walk = str(msb.get("walk_route") or "").strip()
    backup = int(msb.get("backup_anim", -1) or -1)
    if int(msb.get("chr_activate", 0) or 0) != 0:
        return "ChrActivate"
    if backup > 0 and not walk:
        return "坐蹲躺Backup"
    collision = str(msb.get("collision_part") or "").strip()
    if collision and not _pref(model, PERCH_PREFIXES) and not _pref(
        model, DECORATIVE_CORPSE_PREFIXES
    ):
        return "碰撞挂靠"
    return "强制捐皮出场"


def _block_feature(dr: dict, pose: str) -> str:
    """可对照 MSB 捐皮初态全表同 template_id 行。"""
    model = str(dr.get("model") or "").lower()
    if _pref(model, AERIAL_PREFIXES) or pose == "aerial_model":
        return f"model:{model}→aerial_model"
    if _pref(model, SCRIPTED_FLYER_PREFIXES) or _pref(model, ("c6270",)):
        return f"model:{model}→scripted_flyer"
    backup = int(dr.get("backup_anim", -1) or -1)
    walk = str(dr.get("walk_route") or "").strip()
    if int(dr.get("chr_activate", 0) or 0) != 0:
        return f"chr_activate={dr.get('chr_activate')}"
    if backup > 0 and not walk:
        return f"backup_anim={backup}"
    collision = str(dr.get("collision_part") or "").strip()
    if collision:
        return f"collision_part={collision}"
    if dr.get("force_donor_msb"):
        return "force_donor_msb"
    return "ground_patrol_ok"


def _lacks_state(dr: dict, patrol_ok: bool, reason: str) -> str:
    """这块皮缺什么槽状态（白话 + 机器标签）。"""
    if patrol_ok:
        return ""
    walk = str(dr.get("walk_route") or "").strip()
    base = "patrol_keep"
    if reason == "飞行模型":
        return f"{base}（飞行模型，捐皮 walk_route={'有' if walk else '无'}，不能沿目标槽士兵路线走）"
    if reason == "脚本飞行":
        return f"{base}（脚本飞行，捐皮 walk_route={'有' if walk else '无'}）"
    if reason == "坐蹲躺Backup":
        backup = int(dr.get("backup_anim", -1) or -1)
        return f"{base}（坐蹲躺 backup_anim={backup}，须捐皮出场）"
    if reason == "碰撞挂靠":
        return f"{base}（碰撞挂靠 collision_part，须捐皮出场）"
    if reason == "ChrActivate":
        return f"{base}（ChrActivate 脚本出场）"
    return f"{base}（{reason}）"


def _msb_fields_from_donor_row(dr: dict) -> dict:
    out: dict[str, object] = {}
    for key in MSB_EXPORT_KEYS:
        val = dr.get(key)
        if key == "walk_route":
            out["msb_walk_route"] = str(val or "").strip()
            out["msb_has_walk_route"] = bool(str(val or "").strip())
        elif key == "backup_anim":
            out["msb_backup_anim"] = int(val if val is not None else -1)
        elif key == "chr_activate":
            out["msb_chr_activate"] = int(val or 0)
        elif key == "collision_part":
            out["msb_collision_part"] = str(val or "").strip()
        elif key == "talk_id":
            out["msb_talk_id"] = int(val or 0)
        else:
            out[key] = val
    return out


def _whitelist_row_key(row: dict) -> tuple:
    return (
        int(row.get("pool") or 0),
        str(row.get("category") or ""),
        int(row.get("npc") or 0),
        str(row.get("model") or "").lower(),
    )


def build_whitelist_patrol_rows() -> list[dict]:
    if not INDEX_PATH.is_file():
        raise FileNotFoundError(f"missing enemy index: {INDEX_PATH}")

    raw = json.loads(INDEX_PATH.read_text(encoding="utf-8-sig"))
    slot_lookup = {
        (str(s.get("map_id", "")), str(s.get("name", ""))): s
        for s in raw.get("slots") or []
    }
    catalog_templates = list(raw.get("templates") or [])
    categories_cfg = _load_categories_cfg()
    compat_by_tid = load_donor_slot_compat()
    names = load_npc_english_names()

    out: list[dict] = []
    for row in iter_contract_whitelist_rows():
        tpl = _resolve_whitelist_donor_template(row, catalog_templates, categories_cfg)
        if tpl is None:
            out.append(
                {
                    "pool": int(row.get("pool") or 0),
                    "category": str(row.get("category") or ""),
                    "npc": int(row.get("npc") or 0),
                    "model": str(row.get("model") or ""),
                    "name_en": str(row.get("name_en") or ""),
                    "name_zh": str(row.get("name_zh") or ""),
                    "template_id": "",
                    "resolve_ok": False,
                    "patrol_slot_ok": None,
                    "patrol_block_reason": "模板未解析",
                }
            )
            continue

        dr = donor_row(tpl, slot_lookup)
        tid = str(dr.get("template_id") or "")
        compat = compat_entry_for_template(tid, compat_by_tid)
        force = bool(compat.get("force_donor_msb"))
        patrol_ok = bool(compat.get("compat_patrol_keep", True))
        pose = str(compat.get("donor_pose_label") or dr.get("donor_pose_label") or "")
        reason = "" if patrol_ok else _patrol_block_reason(dr, pose)

        try:
            npc = int(row.get("npc") or dr.get("npc") or 0)
        except (TypeError, ValueError):
            npc = 0

        out.append(
            {
                "pool": int(row.get("pool") or 0),
                "category": str(row.get("category") or ""),
                "npc": npc,
                "model": str(row.get("model") or dr.get("model") or ""),
                "name_en": str(row.get("name_en") or "").strip() or names.get(npc, ""),
                "name_zh": str(row.get("name_zh") or ""),
                "template_id": tid,
                "resolve_ok": True,
                "force_donor_msb": force,
                "compat_patrol_keep": patrol_ok,
                "compat_standing_keep": bool(compat.get("compat_standing_keep", True)),
                "donor_pose_label": pose,
                "patrol_slot_ok": patrol_ok,
                "patrol_block_reason": reason,
                "block_feature": _block_feature(dr, pose),
                "lacks_state": _lacks_state(dr, patrol_ok, reason),
                "msb_source_table": str(MSB_DONOR_TABLE),
                **_msb_fields_from_donor_row(dr),
            }
        )
    return out


def _format_md(rows: list[dict]) -> str:
    ok_rows = [r for r in rows if r.get("patrol_slot_ok")]
    blocked = [r for r in rows if r.get("patrol_slot_ok") is False]
    unresolved = [r for r in rows if not r.get("resolve_ok")]

    reason_ctr = Counter(r.get("patrol_block_reason") or "?" for r in blocked)
    model_ctr = Counter(
        (r.get("model") or "?", r.get("patrol_block_reason") or "?") for r in blocked
    )

    lines = [
        "# 白名单捐皮 · 巡逻槽兼容状态表",
        "",
        f"**生成**：`export_whitelist_patrol_status.py` · 规则 v{RULE_VERSION}",
        f"**真源**：`捐皮契约/捐皮白名单_当前.json`（**非** enemy_index 全表）",
        f"**生成时间**：{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "## 结论（白话）",
        "",
        "- **巡逻槽** = 地图槽带士兵 `WalkRoute`（`patrol_keep_initial` 会**保留**这条路）。",
        "- **飞行捐皮**（大乌鸦 `c456*`、死之鸟 `c4980` 等）AI **不会沿地面路线走** → 换到巡逻槽会「盯人+待机不走」。",
        "- **站立槽**无巡逻路 → 大乌鸦等飞行皮可正常飞、可打。",
        "- `donor_tags.hidden` 清的是捐皮出处路线，**不能**去掉目标巡逻槽上原士兵路线。",
        "- **列说明**：`block_feature` = 判据特征；`lacks_state` = 这块皮**缺什么槽状态**；`msb_*` = 与 [`MSB捐皮初态全表.json`](./MSB捐皮初态全表.json) 同 `template_id` 的出场参数。",
        "",
        "## 汇总",
        "",
        f"| 指标 | 数量 |",
        f"|------|-----:|",
        f"| 白名单行 | {len(rows)} |",
        f"| 可进巡逻槽 | {len(ok_rows)} |",
        f"| **不可进巡逻槽** | **{len(blocked)}** |",
        f"| 模板未解析 | {len(unresolved)} |",
        "",
        "### 不可巡逻 · 按原因",
        "",
        "| 原因 | 行数 |",
        "|------|-----:|",
    ]
    for reason, count in reason_ctr.most_common():
        lines.append(f"| {reason} | {count} |")

    lines.extend(
        [
            "",
            "### 不可巡逻 · 按模型前缀（示例）",
            "",
            "| model | 原因 | 行数 |",
            "|-------|------|-----:|",
        ]
    )
    for (model, reason), count in sorted(model_ctr.items(), key=lambda x: (-x[1], x[0])):
        if count < 2 and len(model_ctr) > 40:
            continue
        lines.append(f"| `{model}` | {reason} | {count} |")

    lines.extend(
        [
            "",
            "## 不可巡逻明细（去重 npc+model）",
            "",
            "| pool | model | npc | 中文 | 特征 | 缺状态 | walk | backup | pose |",
            "|-----:|-------|----:|------|------|--------|------|-------|------|",
        ]
    )
    seen: set[tuple[int, str]] = set()
    for r in sorted(
        blocked,
        key=lambda x: (
            x.get("patrol_block_reason") or "",
            x.get("model") or "",
            x.get("npc") or 0,
        ),
    ):
        key = (int(r.get("npc") or 0), str(r.get("model") or ""))
        if key in seen:
            continue
        seen.add(key)
        zh = str(r.get("name_zh") or r.get("name_en") or "")
        walk = "有" if r.get("msb_has_walk_route") else "无"
        backup = r.get("msb_backup_anim", -1)
        lacks = str(r.get("lacks_state") or "").replace("|", "/")
        if len(lacks) > 36:
            lacks = lacks[:33] + "…"
        lines.append(
            f"| {int(r.get('pool') or 0)} | `{r.get('model')}` | {int(r.get('npc') or 0)} | "
            f"{zh} | `{r.get('block_feature')}` | {lacks} | {walk} | {backup} | "
            f"`{r.get('donor_pose_label')}` |"
        )

    lines.extend(
        [
            "",
            f"**JSON 全量**：[`白名单捐皮巡逻状态表.json`](./白名单捐皮巡逻状态表.json)",
            "",
            "契约：`.ai/docs/T-079_白名单捐皮巡逻状态表.md`",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    rows = build_whitelist_patrol_rows()
    blocked = [r for r in rows if r.get("patrol_slot_ok") is False]
    ok_rows = [r for r in rows if r.get("patrol_slot_ok")]
    payload = {
        "schema": "whitelist_patrol_status_v2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "rule_version": RULE_VERSION,
        "whitelist_source": str(_contract_whitelist_path()),
        "compat_cache": str(SCRIPT_DIR / "cache" / "donor_slot_compat.json"),
        "summary": {
            "whitelist_rows": len(rows),
            "patrol_slot_ok": len(ok_rows),
            "patrol_slot_blocked": len(blocked),
            "unresolved": sum(1 for r in rows if not r.get("resolve_ok")),
            "block_reason": dict(Counter(r.get("patrol_block_reason") or "?" for r in blocked)),
        },
        "rows": rows,
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUT_MD.write_text(_format_md(rows), encoding="utf-8")
    print(f"Wrote {OUT_JSON}")
    print(f"Wrote {OUT_MD}")
    print("summary:", payload["summary"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
