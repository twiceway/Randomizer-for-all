"""捐皮契约黑白名单 → 运行时实装（allowlist / manual_includes / never_donor）。

用法:
  python _apply_donor_contract.py

读 `捐皮契约/捐皮白名单_当前.md` + `捐皮黑名单_当前.md`，解析 npc 后写入:
  - donor_pool_review_allowlist.json（6 池 CATEGORY_ORDER）
  - donor_pool_review_manual_includes.json（清空；池归属已在白名单）
  - enemy_categories.json never_donor_npc_ids / exclude_slot_npc_ids（龙类·不捐不随机）
  - 捐皮契约/捐皮白名单_当前.json（同步 npc 字段）
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import enemy_randomizer_core as core  # noqa: E402
from _donor_export_common import (  # noqa: E402
    enrich_donor_row,
    load_curated_display_names,
    load_donor_export_context,
    resolve_display_name_zh,
)
from dlc_donor_pool import build_vanilla_donor_npc_by_model  # noqa: E402
from paths import DONOR_POOL_CONTRACT_DIR, DONOR_POOL_REVIEW_DIR, REPO_ROOT  # noqa: E402

WL_MD = DONOR_POOL_CONTRACT_DIR / "捐皮白名单_当前.md"
BL_MD = DONOR_POOL_CONTRACT_DIR / "捐皮黑名单_当前.md"
WL_JSON = DONOR_POOL_CONTRACT_DIR / "捐皮白名单_当前.json"
ALLOWLIST_PATH = SCRIPT_DIR / "donor_pool_review_allowlist.json"
MANUAL_INCLUDES_PATH = SCRIPT_DIR / "donor_pool_review_manual_includes.json"
CATEGORIES_PATH = SCRIPT_DIR / "enemy_categories.json"

POOL_HEADER_RE = re.compile(r"^##\s*池\s*(\d+)\s*·")
CONTRACT_POOL_TO_CATEGORY: dict[int, str] = {
    1: "trash",
    2: "elite",
    3: "minor_boss",
    4: "evergaol",
    5: "night",
    6: "major_boss",
}

# 契约简表按名解析时易误配任务壳/对话行；在此钉死战斗用 npc。
CONTRACT_NPC_PIN: dict[tuple[str, str], int] = {
    ("食粪者", "dung eater"): 523230035,
    ("夏玻利利", "shabriri"): 523180050,
    ("血指猎人尤拉", "yura- hunter of bloody fingers"): 523180000,
    # T-063 龙人狱卒同 HP 多 npc，中文后缀 disambiguate
    ("龙人狱卒（死骑士地下城·12030）", "dragonkin jailer [dk dungeon]"): 30712030,
    ("龙人狱卒（死骑士地下城·12031）", "dragonkin jailer [dk dungeon]"): 30712031,
    ("龙人狱卒（死骑士地下城·13030）", "dragonkin jailer [dk dungeon]"): 30713030,
    ("龙人狱卒（死骑士地下城·13031）", "dragonkin jailer [dk dungeon]"): 30713031,
    ("龙人狱卒（死骑士地下城·14031）", "dragonkin jailer [dk dungeon]"): 30714031,
    ("龙人狱卒（死骑士地下城·14032）", "dragonkin jailer [dk dungeon]"): 30714032,
    ("龙人狱卒（死骑士地下城·10030）", "dragonkin jailer [dk dungeon]"): 30710030,
    ("龙人狱卒（死骑士地下城·10031）", "dragonkin jailer [dk dungeon]"): 30710031,
    ("龙人狱卒（死骑士地下城·11030）", "dragonkin jailer [dk dungeon]"): 30711030,
    ("龙人狱卒（死骑士地下城·11031）", "dragonkin jailer [dk dungeon]"): 30711031,
    ("玛莲妮亚（米凯拉之刃）", "malenia, blade of miquella"): 21200056,
}

# 黑名单禁捐原因 → 同步 never_donor + exclude_slot（槽位不随机 + 不作捐皮）
CONTRACT_BLOCK_MARKERS = (
    "不随机不捐皮",
    "不捐不随机（龙类）",
    "不捐不随机(龙类)",
)
DRAGON_REASON_MARKERS = ("不捐不随机（龙类）", "不捐不随机(龙类)")


def _norm_en(name: str) -> str:
    return re.sub(r"\s+", " ", str(name or "").strip().casefold().replace("é", "e"))


def _norm_model(model: str) -> str:
    return str(model or "").strip().strip("`").lower()


def _hp_close(a: int, b: int, tol: float = 0.12) -> bool:
    if a <= 0 and b <= 0:
        return True
    if a <= 0 or b <= 0:
        return False
    return abs(a - b) / max(a, b) <= tol


def _parse_md_table_rows(
    path: Path,
    *,
    min_cols: int = 6,
) -> list[dict[str, Any]]:
    """解析契约简表：序号|中文|英文|model|[体型]|有效HP|..."""
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    current_pool = 0
    colmap: dict[str, int] | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        m = POOL_HEADER_RE.match(line.strip())
        if m:
            current_pool = int(m.group(1))
            colmap = None
            continue
        if not line.startswith("|") or "---" in line:
            continue
        parts = [p.strip() for p in line.split("|")]
        if "序号" in line:
            colmap = _header_map(line)
            continue
        if colmap is None:
            continue
        if len(parts) < min_cols + 1:
            continue
        try:
            int(parts[1])
        except (TypeError, ValueError):
            continue
        model_i = colmap.get("model")
        hp_i = colmap.get("有效hp") or colmap.get("有效 hp")
        zh_i = colmap.get("中文名")
        en_i = colmap.get("英文名")
        if model_i is None or hp_i is None:
            continue
        if len(parts) <= max(model_i, hp_i):
            continue
        model = _norm_model(parts[model_i])
        if not model:
            continue
        try:
            hp = int(str(parts[hp_i]).replace(",", ""))
        except (TypeError, ValueError):
            hp = 0
        extra_i = hp_i + 1
        extra = parts[extra_i] if len(parts) > extra_i else ""
        rows.append(
            {
                "pool": current_pool,
                "name_zh": parts[zh_i] if zh_i is not None and zh_i < len(parts) else "",
                "name_en": parts[en_i] if en_i is not None and en_i < len(parts) else "",
                "model": model,
                "effective_hp": hp,
                "synthetic": str(extra).strip() == "是",
                "reason_zh": extra if path == BL_MD else "",
            }
        )
    return rows


def _header_map(header_line: str) -> dict[str, int]:
    parts = [p.strip() for p in header_line.split("|")]
    out: dict[str, int] = {}
    for i, name in enumerate(parts):
        key = name.casefold()
        if key in ("npc", "英文名", "中文名", "model", "有效hp", "有效 hp"):
            out[key] = i
    return out


def _build_npc_index(ctx: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[tuple[str, str, int], int]]:
    """审阅原槽表 + enemy index + 旧契约 json → 可匹配行 + 精确 (model,en,hp) 表。"""
    entries: list[dict[str, Any]] = []
    exact: dict[tuple[str, str, int], int] = {}
    seen: set[tuple[int, str, int]] = set()

    def add(
        npc: int,
        model: str,
        name_en: str,
        name_zh: str,
        hp: int,
        pool: int = 0,
    ) -> None:
        if npc <= 0 or not model:
            return
        model_n = _norm_model(model)
        hp_i = int(hp or 0)
        key = (npc, model_n, hp_i)
        if key not in seen:
            seen.add(key)
            entries.append(
                {
                    "npc": npc,
                    "model": model_n,
                    "name_en": str(name_en or "").strip(),
                    "name_zh": str(name_zh or "").strip(),
                    "name_en_norm": _norm_en(name_en),
                    "effective_hp": hp_i,
                    "pool_hint": pool,
                }
            )
        en_n = _norm_en(name_en)
        if en_n and hp_i > 0:
            exact[(model_n, en_n, hp_i)] = npc
            for delta in (-1, 1):
                exact.setdefault((model_n, en_n, hp_i + delta), npc)

    for md in sorted(DONOR_POOL_REVIEW_DIR.rglob("*.md")):
        if "索引" in md.name:
            continue
        colmap: dict[str, int] | None = None
        for line in md.read_text(encoding="utf-8").splitlines():
            if not line.startswith("|"):
                continue
            if "npc" in line and "序号" in line:
                colmap = _header_map(line)
                continue
            if colmap is None or "---" in line:
                continue
            parts = [p.strip() for p in line.split("|")]
            try:
                int(parts[1])
            except (TypeError, ValueError):
                continue
            npc_i = colmap.get("npc")
            model_i = colmap.get("model")
            en_i = colmap.get("英文名")
            zh_i = colmap.get("中文名")
            hp_i = colmap.get("有效hp") or colmap.get("有效 hp")
            if npc_i is None or model_i is None:
                continue
            if len(parts) <= max(npc_i, model_i):
                continue
            try:
                npc = int(parts[npc_i])
            except (TypeError, ValueError):
                continue
            model = parts[model_i]
            name_en = parts[en_i] if en_i is not None and en_i < len(parts) else ""
            name_zh = parts[zh_i] if zh_i is not None and zh_i < len(parts) else ""
            hp = 0
            if hp_i is not None and hp_i < len(parts):
                try:
                    hp = int(parts[hp_i].replace(",", ""))
                except (TypeError, ValueError):
                    hp = 0
            add(npc, model, name_en, name_zh, hp)

    index_data = core.load_enemy_index()
    npc_rows = ctx["npc_rows"]
    sp_rates = ctx["sp_rates"]
    vanilla = ctx.get("vanilla_npc_by_model") or {}
    for tpl in index_data.get("templates") or []:
        try:
            npc = int(tpl.get("npc", 0) or 0)
        except (TypeError, ValueError):
            continue
        model = str(tpl.get("model") or "")
        extra = enrich_donor_row(
            tpl,
            categories_cfg=ctx["categories_cfg"],
            npc_rows=npc_rows,
            sp_rates=sp_rates,
            paramdex_names=ctx["paramdex_names"],
            review_name_zh=ctx["review_name_zh"],
            archetype_index=ctx["archetype_index"],
            vanilla_npc_by_model=vanilla,
        )
        add(npc, model, extra["name_en"], extra["name_zh"], extra["effective_hp"])

    return entries, exact


def _resolve_npc(
    row: dict[str, Any],
    index: list[dict[str, Any]],
    exact: dict[tuple[str, str, int], int],
) -> tuple[int, str]:
    model = _norm_model(row.get("model"))
    name_en = _norm_en(row.get("name_en"))
    name_zh = str(row.get("name_zh") or "").strip().casefold()
    hp = int(row.get("effective_hp") or 0)

    for (zh_key, en_key), pinned_npc in CONTRACT_NPC_PIN.items():
        if name_zh and name_zh == zh_key.casefold():
            return pinned_npc, "contract_pin_zh"
    for (zh_key, en_key), pinned_npc in CONTRACT_NPC_PIN.items():
        if name_en and name_en == en_key:
            return pinned_npc, "contract_pin_en"

    if name_en and hp > 0:
        hit = exact.get((model, name_en, hp))
        if hit:
            return hit, "exact"
        for e in index:
            if e["model"] != model or e["name_en_norm"] != name_en:
                continue
            if _hp_close(hp, e["effective_hp"]):
                return int(e["npc"]), "exact_hp"

    candidates = [e for e in index if e["model"] == model]
    if not candidates:
        return 0, "no_model_match"

    if hp > 0:
        hp_hits = [e for e in candidates if _hp_close(hp, e["effective_hp"])]
        if len(hp_hits) == 1:
            return int(hp_hits[0]["npc"]), "hp_unique"
        if hp_hits and name_en:
            en_hits = [e for e in hp_hits if e["name_en_norm"] == name_en]
            if len(en_hits) == 1:
                return int(en_hits[0]["npc"]), "hp_en"
        if hp_hits and name_zh:
            zh_hits = [
                e
                for e in hp_hits
                if name_zh in str(e.get("name_zh") or "").strip().casefold()
            ]
            if len(zh_hits) == 1:
                return int(zh_hits[0]["npc"]), "hp_zh"

    def rank(e: dict[str, Any]) -> tuple[int, int, int]:
        en = e["name_en_norm"]
        zh = str(e.get("name_zh") or "").strip().casefold()
        en_match = 3 if name_en and en == name_en else 0
        zh_match = 2 if name_zh and zh == name_zh else (
            1 if name_zh and name_zh in zh else 0
        )
        hp_diff = abs(hp - e["effective_hp"]) if hp > 0 else 0
        return (en_match + zh_match, -hp_diff, -e["effective_hp"])

    ranked = sorted(candidates, key=rank, reverse=True)
    best = ranked[0]
    if rank(best)[0] == 0:
        if hp > 0:
            by_hp = sorted(candidates, key=lambda e: abs(hp - e["effective_hp"]))
            if _hp_close(hp, by_hp[0]["effective_hp"]):
                close = [e for e in by_hp if _hp_close(hp, e["effective_hp"])]
                if len(close) == 1:
                    return int(close[0]["npc"]), "hp_only"
        return 0, "no_name_match"
    if len(ranked) > 1 and rank(ranked[1]) == rank(best):
        top = rank(best)[0]
        group = [e for e in ranked if rank(e)[0] == top]
        pick = min(group, key=lambda e: abs(hp - e["effective_hp"]) if hp > 0 else 0)
        return int(pick["npc"]), "tiebreak_hp"
    return int(best["npc"]), "ok"


def _enrich_row(npc: int, pool: int, ctx: dict[str, Any]) -> dict[str, Any]:
    cat = CONTRACT_POOL_TO_CATEGORY[pool]
    curated = ctx.get("curated") or {}
    npc_rows = ctx["npc_rows"]
    row = npc_rows.get(npc) or {}
    model = str(row.get("model") or row.get("Model") or "")
    extra = enrich_donor_row(
        {"npc": npc, "model": model, "template_id": ""},
        categories_cfg=ctx["categories_cfg"],
        npc_rows=npc_rows,
        sp_rates=ctx["sp_rates"],
        paramdex_names=ctx["paramdex_names"],
        review_name_zh=ctx["review_name_zh"],
        archetype_index=ctx["archetype_index"],
        vanilla_npc_by_model=ctx.get("vanilla_npc_by_model") or {},
    )
    return {
        "pool": pool,
        "pool_zh": core.CATEGORY_DISPLAY_ZH.get(cat, cat),
        "category": cat,
        "model": model or extra.get("model") or "",
        "name_zh": resolve_display_name_zh(extra["name_en"], extra, curated_names=curated)
        or str(ctx.get("_contract_zh") or ""),
        "name_en": extra["name_en"],
        "effective_hp": extra["effective_hp"],
        "hp_mult_desc": extra["hp_mult_desc"],
        "npc": npc,
        "archetype_zh": extra.get("archetype_zh", ""),
        "synthetic": False,
    }


def _merge_sorted_ids(by_cat: dict[str, set[int]]) -> dict[str, list[int]]:
    return {k: sorted(v) for k, v in sorted(by_cat.items())}


def _update_npc_id_list(data: dict[str, Any], key: str, add_ids: set[int]) -> list[int]:
    existing = {int(x) for x in (data.get(key) or [])}
    merged = sorted(existing | add_ids)
    data[key] = merged
    return merged


def main() -> None:
    ctx = load_donor_export_context()
    ctx["curated"] = load_curated_display_names()
    index_data = core.load_enemy_index()
    ctx["vanilla_npc_by_model"] = build_vanilla_donor_npc_by_model(
        index_data.get("templates") or [],
        npc_by_id=ctx["npc_rows"],
        sp_rates=ctx["sp_rates"],
    )
    npc_index, exact_index = _build_npc_index(ctx)

    wl_rows = _parse_md_table_rows(WL_MD)
    bl_rows = _parse_md_table_rows(BL_MD)
    if not wl_rows:
        raise SystemExit(f"白名单为空或无法解析: {WL_MD}")

    by_cat: dict[str, set[int]] = {c: set() for c in core.CATEGORY_ORDER}
    resolved_wl: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []

    for row in wl_rows:
        pool = int(row["pool"])
        if pool not in CONTRACT_POOL_TO_CATEGORY:
            unresolved.append({**row, "resolve_note": f"bad_pool_{pool}"})
            continue
        cat = CONTRACT_POOL_TO_CATEGORY[pool]
        ctx["_contract_zh"] = row.get("name_zh")
        npc, note = _resolve_npc(row, npc_index, exact_index)
        if npc <= 0:
            unresolved.append({**row, "resolve_note": note})
            continue
        enriched = _enrich_row(npc, pool, ctx)
        if row.get("model"):
            enriched["model"] = _norm_model(row["model"])
        if row.get("name_zh"):
            enriched["name_zh"] = str(row["name_zh"])
        if row.get("name_en"):
            enriched["name_en"] = str(row["name_en"])
        if row.get("synthetic"):
            enriched["synthetic"] = True
        if int(row.get("effective_hp") or 0) > 0:
            enriched["effective_hp"] = int(row["effective_hp"])
        resolved_wl.append(enriched)
        by_cat[cat].add(npc)

    rows_by_pool: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in resolved_wl:
        rows_by_pool[int(row["pool"])].append(row)
    for pool in rows_by_pool:
        rows_by_pool[pool].sort(
            key=lambda r: (
                str(r.get("name_zh") or r.get("name_en") or ""),
                str(r.get("model") or ""),
            )
        )

    total_wl = len(resolved_wl)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    allowlist_payload = {
        "source": str(DONOR_POOL_CONTRACT_DIR / "捐皮白名单_当前.md"),
        "applied_at": now,
        "manual_includes": str(MANUAL_INCLUDES_PATH),
        "pool_to_category": {str(k): v for k, v in CONTRACT_POOL_TO_CATEGORY.items()},
        "npc_ids_by_category": _merge_sorted_ids(by_cat),
        "counts": {k: len(v) for k, v in _merge_sorted_ids(by_cat).items()},
    }
    ALLOWLIST_PATH.write_text(
        json.dumps(allowlist_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    wl_json = {
        "generated_at": now,
        "schema": "donor_whitelist_v1",
        "source": "捐皮契约实装",
        "rows_after_dedupe": total_wl,
        "by_category": {k: len(v) for k, v in allowlist_payload["npc_ids_by_category"].items()},
        "rows_by_pool": {str(p): rows for p, rows in sorted(rows_by_pool.items())},
        "unresolved": unresolved,
    }
    WL_JSON.write_text(json.dumps(wl_json, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    includes_payload = {
        "note": f"捐皮契约实装 {now}：池归属已在 donor_pool_review_allowlist.json；此处仅保留强制覆写",
        "entries": [],
    }
    MANUAL_INCLUDES_PATH.write_text(
        json.dumps(includes_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    block_npc_ids: set[int] = set()
    for row in bl_rows:
        reason = str(row.get("reason_zh") or "")
        if not any(m in reason for m in CONTRACT_BLOCK_MARKERS):
            continue
        npc, note = _resolve_npc(row, npc_index, exact_index)
        if npc > 0:
            block_npc_ids.add(npc)
        else:
            unresolved.append({**row, "resolve_note": f"block:{note}"})

    categories_cfg = json.loads(CATEGORIES_PATH.read_text(encoding="utf-8"))
    if block_npc_ids:
        _update_npc_id_list(categories_cfg, "never_donor_npc_ids", block_npc_ids)
        _update_npc_id_list(categories_cfg, "exclude_slot_npc_ids", block_npc_ids)
        note = str(categories_cfg.get("never_donor_npc_ids_definition") or "")
        stamp = now.split()[0]
        if "柏克/辉石法师尸体" not in note:
            categories_cfg["never_donor_npc_ids_definition"] = (
                note.rstrip("；")
                + f"；柏克/辉石法师尸体 {stamp}（契约黑名单·不随机不捐皮）"
            )
        if "装饰尸体" not in note:
            categories_cfg["never_donor_npc_ids_definition"] = (
                str(categories_cfg.get("never_donor_npc_ids_definition") or note).rstrip("；")
                + f"；装饰尸体 npc {stamp}（契约黑名单·不随机不捐皮）"
            )
        ex_note = str(categories_cfg.get("exclude_slot_npc_ids_definition") or "")
        if "柏克/辉石法师尸体" not in ex_note:
            categories_cfg["exclude_slot_npc_ids_definition"] = (
                ex_note.rstrip("；")
                + f"；柏克 41109010/41109170、辉石法师尸体 37022022 {stamp}（用户）"
            )
        CATEGORIES_PATH.write_text(
            json.dumps(categories_cfg, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    print(f"whitelist resolved: {total_wl} / {len(wl_rows)} md rows")
    print(f"allowlist unique npc: {sum(len(v) for v in allowlist_payload['npc_ids_by_category'].values())}")
    print(f"allowlist counts: {allowlist_payload['counts']}")
    print(f"contract block never_donor+exclude_slot: {len(block_npc_ids)} npc")
    if unresolved:
        print(f"UNRESOLVED: {len(unresolved)}")
        for u in unresolved[:20]:
            print(
                f"  pool{u.get('pool')} {u.get('name_zh') or u.get('name_en')} "
                f"{u.get('model')} hp={u.get('effective_hp')} -> {u.get('resolve_note')}"
            )
        if len(unresolved) > 20:
            print(f"  ... and {len(unresolved) - 20} more (see {WL_JSON.name} unresolved)")


if __name__ == "__main__":
    main()
