"""Export whitelist donor × full-map slot receptor buckets (T-081).

真源：捐皮契约/捐皮白名单_当前.json（377 行全量）· enemy_index slots · donor_slot_compat_reject_reason
"""
from __future__ import annotations

import json
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from _export_donor_msb_state import donor_row
from gatefront_quad_catalog import (
    _contract_whitelist_path,
    _load_categories_cfg,
    _resolve_whitelist_donor_template,
    iter_contract_whitelist_rows,
    load_npc_english_names,
)
from paths import GAME_DIR
from whitelist_slot_receptor import (
    BUCKET_IDS,
    HISTORICAL_SCHEMA,
    PRODUCT_NAME,
    RULE_VERSION,
    aggregate_donor_receptor,
    load_index_slots,
    receptor_fingerprint,
    scan_map_slots,
    slot_scan_summary_dict,
)

from paths import SCRIPT_DIR  # frozen-safe
INDEX_PATH = SCRIPT_DIR / "cache" / "enemy_index.json"
COMPAT_CACHE = SCRIPT_DIR / "cache" / "donor_slot_compat.json"
OUT_CACHE = SCRIPT_DIR / "cache" / "whitelist_donor_slot_receptor.json"
OUT_JSON = SCRIPT_DIR.parent / "reports" / "白名单捐皮槽位反扫表.json"
OUT_MD = SCRIPT_DIR.parent / "reports" / "白名单捐皮槽位反扫表.md"
OUT_MD_HIST = SCRIPT_DIR.parent / "reports" / "捐皮历史状态反扫表.md"
OUT_JSON_HIST = SCRIPT_DIR.parent / "reports" / "捐皮历史状态反扫表.json"


def _build_donor_base_rows() -> list[dict]:
    """One output row per contract whitelist row (377); resolve template_id once."""
    if not INDEX_PATH.is_file():
        raise FileNotFoundError(f"missing enemy index: {INDEX_PATH}")

    raw = json.loads(INDEX_PATH.read_text(encoding="utf-8-sig"))
    slot_lookup = {
        (str(s.get("map_id", "")), str(s.get("name", ""))): s
        for s in raw.get("slots") or []
    }
    catalog_templates = list(raw.get("templates") or [])
    categories_cfg = _load_categories_cfg()
    names = load_npc_english_names()

    rows: list[dict] = []
    for wl in iter_contract_whitelist_rows():
        tpl = _resolve_whitelist_donor_template(wl, catalog_templates, categories_cfg)
        try:
            npc = int(wl.get("npc") or 0)
        except (TypeError, ValueError):
            npc = 0
        base = {
            "pool": int(wl.get("pool") or 0),
            "category": str(wl.get("category") or ""),
            "npc": npc,
            "model": str(wl.get("model") or ""),
            "name_en": str(wl.get("name_en") or "").strip(),
            "name_zh": str(wl.get("name_zh") or ""),
        }
        if tpl is None:
            rows.append({**base, "template_id": "", "resolve_ok": False})
            continue
        dr = donor_row(tpl, slot_lookup)
        tid = str(dr.get("template_id") or "")
        rows.append(
            {
                **base,
                "name_en": base["name_en"] or names.get(npc, ""),
                "template_id": tid,
                "resolve_ok": bool(tid),
            }
        )
    return rows


def build_whitelist_receptor_donors(
    scanned,
    compat_by_tid: dict,
) -> list[dict]:
    base_rows = _build_donor_base_rows()
    donors: list[dict] = []
    for row in base_rows:
        out = dict(row)
        if not row.get("resolve_ok") or not row.get("template_id"):
            out["historical_states"] = []
            out["historical_state_counts"] = {bid: 0 for bid in BUCKET_IDS}
            out["vanilla_scan_model"] = ""
            out["vanilla_occurrence_total"] = 0
            out["donor_side"] = {}
            out["receptor_all_msb"] = {}
            out["receptor_pick_eligible"] = {}
            out["blocked_reason_top_all_msb"] = []
            out["blocked_reason_top_pick_eligible"] = []
            donors.append(out)
            continue
        agg = aggregate_donor_receptor(
            scanned,
            str(row["template_id"]),
            compat_by_tid,
        )
        out.update(agg)
        donors.append(out)
    return donors


def _bucket_cell(receptor: dict, bucket: str, *, pick: bool) -> str:
    scope = receptor.get("receptor_pick_eligible" if pick else "receptor_all_msb") or {}
    cell = scope.get(bucket) or {}
    allowed = int(cell.get("allowed") or 0)
    total = int(cell.get("total") or 0)
    return f"{allowed}/{total}"


def _format_md(payload: dict) -> str:
    donors = payload.get("donors") or []
    scan = payload.get("slot_scan") or {}
    unresolved = [d for d in donors if not d.get("resolve_ok")]

    lines = [
        "# 捐皮历史状态反扫表（T-081 / T-085）",
        "",
        "> **产品名**：历史状态表 · **配对允许/拒绝只认** `historical_states`（同 model 全图原版状态并集）。  ",
        "> **用户自选概率矩阵**仍先抽池；本表不决定抽哪一池。lift/难度不动。  ",
        f"> 契约：[T-085](../.ai/docs/T-085_槽位配对只认历史状态.md) · [T-081](../.ai/docs/T-081_白名单捐皮槽位反扫表.md)",
        "",
        f"**生成**：`export_whitelist_donor_slot_receptor.py` · rule v{RULE_VERSION} · historical_schema={HISTORICAL_SCHEMA}",
        f"**真源**：`捐皮契约/捐皮白名单_当前.json` · **377 行全量**",
        f"**生成时间**：{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "## 汇总",
        "",
        f"| 指标 | 数量 |",
        f"|------|-----:|",
        f"| 白名单行 | {len(donors)} |",
        f"| 全图 MSB 槽 | {scan.get('all_msb_total', 0)} |",
        f"| 可随机槽 | {scan.get('pick_eligible_total', 0)} |",
        f"| 模板未解析 | {len(unresolved)} |",
        "",
        "### 全图槽 · 按状态桶",
        "",
        "| 桶 | 全图 | 可随机 |",
        "|----|-----:|-------:|",
    ]
    for bid in BUCKET_IDS:
        all_n = (scan.get("bucket_totals_all_msb") or {}).get(bid, 0)
        pick_n = (scan.get("bucket_totals_pick_eligible") or {}).get(bid, 0)
        lines.append(f"| `{bid}` | {all_n} | {pick_n} |")

    lines.extend(
        [
            "",
            "## 全量明细（历史状态 + 可随机槽 allowed/total）",
            "",
            "| pool | cat | model | npc | 中文 | historical_states | patrol | ground | sit | collision | aerial | chr_act | force |",
            "|-----:|-----|-------|----:|------|-------------------|--------|--------|-----|-----------|--------|---------|------|",
        ]
    )
    for d in sorted(
        donors,
        key=lambda x: (
            int(x.get("pool") or 0),
            str(x.get("category") or ""),
            str(x.get("model") or ""),
        ),
    ):
        side = d.get("donor_side") or {}
        force = "Y" if side.get("force_donor_msb") else ""
        zh = str(d.get("name_zh") or d.get("name_en") or "")
        hist = ",".join(d.get("historical_states") or []) or "—"
        if not d.get("resolve_ok"):
            lines.append(
                f"| {int(d.get('pool') or 0)} | {d.get('category')} | `{d.get('model')}` | "
                f"{int(d.get('npc') or 0)} | {zh} | — | — | — | — | — | — | — | 未解析 |"
            )
            continue
        lines.append(
            f"| {int(d.get('pool') or 0)} | {d.get('category')} | `{d.get('model')}` | "
            f"{int(d.get('npc') or 0)} | {zh} | `{hist}` | "
            f"{_bucket_cell(d, 'patrol', pick=True)} | "
            f"{_bucket_cell(d, 'ground_stand', pick=True)} | "
            f"{_bucket_cell(d, 'sit_squat', pick=True)} | "
            f"{_bucket_cell(d, 'collision_perch', pick=True)} | "
            f"{_bucket_cell(d, 'aerial_slot', pick=True)} | "
            f"{_bucket_cell(d, 'script_chr_activate', pick=True)} | "
            f"{force} |"
        )

    if unresolved:
        lines.extend(["", "## 未解析模板", ""])
        for d in unresolved:
            lines.append(
                f"- pool={d.get('pool')} `{d.get('model')}` npc={d.get('npc')} {d.get('name_zh')}"
            )

    lines.extend(
        [
            "",
            f"**JSON 全量**：[`捐皮历史状态反扫表.json`](./捐皮历史状态反扫表.json)（与旧名反扫表同内容）",
            f"**主程序缓存**：`cnv_randomizer/cache/whitelist_donor_slot_receptor.json`",
            "",
            "契约：`.ai/docs/T-085_槽位配对只认历史状态.md` · `.ai/docs/T-081_白名单捐皮槽位反扫表.md`",
        ]
    )
    return "\n".join(lines) + "\n"


def build_payload() -> dict:
    from donor_msb_compat import compat_cache_fingerprint, load_donor_slot_compat

    whitelist_path = _contract_whitelist_path()
    index_slots, index_generated_at = load_index_slots(INDEX_PATH)
    categories_cfg = _load_categories_cfg()
    npc_csv_dir = GAME_DIR / "csv"

    t0 = time.perf_counter()
    scanned = scan_map_slots(
        index_slots,
        categories_cfg=categories_cfg,
        npc_csv_dir=npc_csv_dir,
    )
    compat_by_tid = load_donor_slot_compat()
    donors = build_whitelist_receptor_donors(scanned, compat_by_tid)
    elapsed = time.perf_counter() - t0

    patrol_blocked = sum(
        1
        for d in donors
        if d.get("resolve_ok")
        and int((d.get("receptor_pick_eligible") or {}).get("patrol", {}).get("allowed") or 0) == 0
        and int((d.get("receptor_pick_eligible") or {}).get("patrol", {}).get("total") or 0) > 0
    )

    return {
        "schema": "whitelist_donor_slot_receptor_v2",
        "product": PRODUCT_NAME,
        "rule_version": RULE_VERSION,
        "bucket_schema": 1,
        "historical_schema": HISTORICAL_SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "fingerprint": receptor_fingerprint(
            whitelist_path=whitelist_path,
            index_generated_at=index_generated_at,
            compat_cache_path=COMPAT_CACHE,
        ),
        "compat_fingerprint": compat_cache_fingerprint(cache_path=COMPAT_CACHE),
        "whitelist_source": str(whitelist_path),
        "index_source": str(INDEX_PATH),
        "compat_cache": str(COMPAT_CACHE),
        "build_seconds": round(elapsed, 2),
        "slot_scan": slot_scan_summary_dict(scanned),
        "summary": {
            "whitelist_rows": len(donors),
            "resolve_ok": sum(1 for d in donors if d.get("resolve_ok")),
            "unresolved": sum(1 for d in donors if not d.get("resolve_ok")),
            "patrol_allowed_zero_pick_eligible": patrol_blocked,
            "with_historical_states": sum(
                1 for d in donors if d.get("resolve_ok") and list(d.get("historical_states") or [])
            ),
            "empty_historical_states": sum(
                1 for d in donors if d.get("resolve_ok") and not list(d.get("historical_states") or [])
            ),
        },
        "donors": donors,
    }


def write_outputs(payload: dict) -> None:
    OUT_CACHE.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    OUT_CACHE.write_text(text, encoding="utf-8")
    OUT_JSON.write_text(text, encoding="utf-8")
    OUT_JSON_HIST.write_text(text, encoding="utf-8")
    md = _format_md(payload)
    OUT_MD.write_text(md, encoding="utf-8")
    OUT_MD_HIST.write_text(md, encoding="utf-8")


def main() -> int:
    if not COMPAT_CACHE.is_file():
        print("WARN: missing donor_slot_compat.json — run _export_donor_msb_state.py first")
    payload = build_payload()
    write_outputs(payload)
    print(f"Wrote {OUT_CACHE}")
    print(f"Wrote {OUT_JSON}")
    print(f"Wrote {OUT_JSON_HIST}")
    print(f"Wrote {OUT_MD}")
    print(f"Wrote {OUT_MD_HIST}")
    print("summary:", payload["summary"])
    print(f"build_seconds={payload['build_seconds']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
