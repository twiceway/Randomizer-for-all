"""T-063 新入库地图 → 捐皮候选表（排除白名单/黑名单/旧库已有）。"""
from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

import enemy_randomizer_core as core  # noqa: E402
from boss_npc_detect import load_npc_rows  # noqa: E402
from dlc_donor_pool import load_sp_hp_rates, npc_effective_hp_for_review  # noqa: E402
from donor_pool_review_filter import is_donor_review_excluded_template  # noqa: E402
from paths import DONOR_POOL_CONTRACT_DIR, GAME_DIR  # noqa: E402

NEW_MAPS_PATH = REPO_ROOT / "cnv_enemy_poc" / "_tmp_msb_probe_sfnext" / "maps.txt"
INDEX_PATH = SCRIPT_DIR / "cache" / "enemy_index.json"
OUT_MD = DONOR_POOL_CONTRACT_DIR / "T063_新扫捐皮候选表.md"


def _map_id(donor_map: str) -> str:
    s = str(donor_map or "").strip()
    if s.endswith(".msb.dcx"):
        return s[: -len(".msb.dcx")]
    if s.endswith(".msbe.dcx"):
        return s[: -len(".msbe.dcx")]
    return s


def _load_old_index() -> dict:
    raw = subprocess.check_output(
        ["git", "show", "HEAD:cnv_randomizer/cache/enemy_index.json"],
        cwd=REPO_ROOT,
    )
    return json.loads(raw)


def main() -> None:
    new_maps = {
        ln.strip()
        for ln in NEW_MAPS_PATH.read_text(encoding="utf-8").splitlines()
        if ln.strip()
    }
    old = _load_old_index()
    new = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    cats = json.loads((SCRIPT_DIR / "enemy_categories.json").read_text(encoding="utf-8"))
    wl = json.loads((DONOR_POOL_CONTRACT_DIR / "捐皮白名单_当前.json").read_text(encoding="utf-8"))

    bl_npc: set[int] = set()
    bl_json = DONOR_POOL_CONTRACT_DIR / "捐皮黑名单_当前.json"
    if bl_json.is_file():
        blj = json.loads(bl_json.read_text(encoding="utf-8"))
        for rows in (blj.get("rows_by_pool") or {}).values():
            for r in rows:
                if r.get("npc"):
                    bl_npc.add(int(r["npc"]))

    wl_npc: set[int] = set()
    wl_models: set[str] = set()
    wl_model_npc: set[tuple[str, int]] = set()
    for rows in (wl.get("rows_by_pool") or {}).values():
        for r in rows:
            npc = int(r.get("npc") or 0)
            model = str(r.get("model", "")).lower()
            if model:
                wl_models.add(model)
            if npc:
                wl_npc.add(npc)
            if npc and model:
                wl_model_npc.add((model, npc))

    t057_npc = {int(x) for x in (cats.get("cnv_original_boss_slot_npc_ids") or [])}

    old_keys: set[tuple[str, int]] = set()
    for t in old.get("templates") or []:
        m = str(t.get("model", "")).lower()
        n = int(t.get("npc") or 0)
        if m and n:
            old_keys.add((m, n))

    npc_rows = load_npc_rows(GAME_DIR / "csv")
    sp_rates = load_sp_hp_rates(GAME_DIR / "csv")
    min_hp = int(cats.get("donor_min_effective_hp") or 101)

    def eff_hp(npc: int, model: str = "") -> int:
        pick = npc_effective_hp_for_review(
            npc,
            npc_rows.get(npc),
            model=model,
            sp_rates=sp_rates,
            npc_by_id=npc_rows,
        )
        return int(pick.get("effective_hp") or 0)

    def npc_name(npc: int) -> str:
        row = npc_rows.get(int(npc)) or {}
        return str(row.get("Name") or row.get("name") or "")

    cat_zh = {
        "trash": "路边小怪",
        "elite": "精英",
        "minor_boss": "洞穴Boss",
        "evergaol": "场地Boss",
        "night": "红灵",
        "major_boss": "主线大Boss",
        "field_boss": "场地Boss",
    }

    candidates: list[dict] = []
    seen: set[tuple[str, int]] = set()
    for t in new.get("templates") or []:
        dmap = _map_id(str(t.get("donor_map") or ""))
        if dmap not in new_maps:
            continue
        model = str(t.get("model", "")).lower()
        npc = int(t.get("npc") or 0)
        if not model or not npc:
            continue
        key = (model, npc)
        if key in seen:
            continue
        seen.add(key)
        if key in old_keys:
            continue
        if npc in wl_npc or key in wl_model_npc:
            continue
        if model in wl_models:
            continue
        if npc in t057_npc:
            continue
        if npc in bl_npc:
            continue
        if core.is_never_donor_model(model, cats):
            continue
        if core.is_never_donor_npc_id(t, cats):
            continue
        if is_donor_review_excluded_template(t, categories_cfg=cats):
            continue
        hp = eff_hp(npc, model)
        if hp < min_hp:
            continue
        cat = str(t.get("category") or "")
        candidates.append(
            {
                "map": dmap,
                "model": model,
                "npc": npc,
                "cat": cat,
                "cat_zh": cat_zh.get(cat, cat or "?"),
                "hp": hp,
                "name": npc_name(npc),
            }
        )

    candidates.sort(key=lambda x: (-x["hp"], x["cat"], x["model"], x["npc"]))
    by_cat = Counter(c["cat_zh"] for c in candidates)

    lines = [
        "# T-063 新扫捐皮候选表",
        "",
        "**位置**：`捐皮契约/`（审计用；非白名单真源）  ",
        "**生成**：`python cnv_randomizer/_export_t063_new_donors.py`  ",
        f"**日期**：2026-08-08  ",
        "",
        "## 口径",
        "",
        "- **来源**：T-063 前 `index_skip` 的 **202** 张图，重扫后 `enemy_index` 捐皮库（①）新增模板。",
        "- **已排除**：旧索引已有同 model+npc · 白名单已登记的 model 或 npc · 黑名单 npc · T-057 原位 Boss npc · never_donor · 审阅过滤 · 有效 HP 不足 101。",
        "- **保留**：同图多实例、白名单未覆盖的新 model 变体，供审计是否扩池。",
        "",
        f"**候选种数**：**{len(candidates)}**（按 model+npc 去重）",
        "",
        "| 推断池 | 种数 |",
        "|:---|---:|",
    ]
    for cat, n in sorted(by_cat.items(), key=lambda x: (-x[1], x[0])):
        lines.append(f"| {cat} | {n} |")
    lines += [
        "",
        "## 明细",
        "",
        "| 序号 | 推断池 | 中文名 | 英文名 | model | npc | 有效HP | 示例图 |",
        "|---:|:---|:---|:---|:---|---:|---:|:---|",
    ]
    for i, c in enumerate(candidates, 1):
        name_en = c["name"].replace("|", "/") or "—"
        lines.append(
            f"| {i} | {c['cat_zh']} | （待译） | {name_en} | `{c['model']}` | {c['npc']} | {c['hp']} | `{c['map']}` |"
        )
    lines += [
        "",
        "> **注意**：重跑本脚本会覆盖本表；中文名列须人工校对（见 `T063_新扫捐皮候选表.md` 历史版本或 `donor_blacklist_name_zh.json`）。",
    ]
    lines.append("")
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {OUT_MD} ({len(candidates)} rows)")


if __name__ == "__main__":
    main()
