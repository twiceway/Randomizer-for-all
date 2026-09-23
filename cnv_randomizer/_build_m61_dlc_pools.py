"""Build m61 DLC donor manifest + merge prefix lists into enemy_categories.json."""
from __future__ import annotations

import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent
GAME = Path(r"V:/games/Elden Ring/Game")

sys.path.insert(0, str(SCRIPT))
from paths import OUTPUT_REPORTS  # noqa: E402

JSONL = OUTPUT_REPORTS / "_m61_slots.jsonl"
MANIFEST = SCRIPT / "m61_dlc_donor_pool.json"
CATEGORIES = SCRIPT / "enemy_categories.json"
ARCHETYPES = SCRIPT / "enemy_archetypes.json"
TAXONOMY = SCRIPT / "dlc_trash_taxonomy.json"
OUT_REPORT = OUTPUT_REPORTS / "m61_DLC捐皮池入库.md"

import boss_npc_detect as bnd  # noqa: E402
from dlc_donor_pool import (  # noqa: E402
    BOSS_TARGET_CATEGORIES,
    FORCE_M61_BOSS_CATEGORY,
    M61_BOSS_ZH,
    M61_EXCLUDE_PREFIXES,
    MIN_BOSS_COMBAT_HP,
    MIN_TRASH_COMBAT_HP,
    NEVER_DONOR_PREFIXES,
    SKIP_PREFIXES,
    combat_hp_detailed,
    load_sp_hp_rates,
    pick_dlc_donor_npc,
)


def load_taxonomy_force_prefixes() -> frozenset[str]:
    if not TAXONOMY.is_file():
        return frozenset()
    data = json.loads(TAXONOMY.read_text(encoding="utf-8"))
    out: set[str] = set()
    for arch in data.get("archetypes") or []:
        for entry in arch.get("entries") or []:
            for m in entry.get("models") or []:
                out.add(str(m).lower())
    return frozenset(out)


def load_zh() -> dict[str, str]:
    cats = json.loads(CATEGORIES.read_text(encoding="utf-8"))
    zh: dict[str, str] = dict(cats.get("model_prefix_display_zh") or {})
    doc = (SCRIPT.parent / ".ai/docs/小怪原型中文表.md").read_text(encoding="utf-8")
    for m in re.finditer(r"\|\s*(c\d{4})\s*\|\s*([^|]+?)\s*\|", doc):
        zh.setdefault(m.group(1).lower(), m.group(2).strip())
    return zh


def load_npc_rows() -> dict[int, dict[str, str]]:
    out: dict[int, dict[str, str]] = {}
    with (GAME / "csv/NpcParam.csv").open(encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            try:
                out[int(row["ID"])] = row
            except (KeyError, TypeError, ValueError):
                pass
    return out


def merge_prefix_list(existing: list[str], new_items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for p in list(existing) + sorted(new_items):
        pl = str(p).lower()
        if not pl or pl in seen:
            continue
        seen.add(pl)
        out.append(pl)
    return out


def ensure_donor_origin_rules(
    rules: list[dict[str, str]], prefixes: list[str], origin: str = "dlc"
) -> list[dict[str, str]]:
    have = {str(r.get("prefix", "")).lower() for r in rules}
    out = list(rules)
    for p in sorted(prefixes):
        pl = p.lower()
        if pl in have:
            continue
        out.append({"prefix": pl, "origin": origin})
        have.add(pl)
    out.sort(key=lambda r: str(r.get("prefix", "")))
    return out


def main() -> None:
    if not JSONL.is_file():
        raise SystemExit(f"missing {JSONL}")

    cats = json.loads(CATEGORIES.read_text(encoding="utf-8-sig"))
    zh = load_zh()
    zh.update(M61_BOSS_ZH)
    if TAXONOMY.is_file():
        tax_data = json.loads(TAXONOMY.read_text(encoding="utf-8"))
        for arch in tax_data.get("archetypes") or []:
            for entry in arch.get("entries") or []:
                label = str(entry.get("zh") or "").strip()
                if not label:
                    continue
                for m in entry.get("models") or []:
                    zh.setdefault(str(m).lower(), label)
    tax_force = load_taxonomy_force_prefixes()
    sp_rates = load_sp_hp_rates(str(GAME / "csv"))
    npc_by_id = load_npc_rows()
    slots = [json.loads(line) for line in JSONL.read_text(encoding="utf-8").splitlines() if line.strip()]

    by_p5: dict[str, dict] = defaultdict(
        lambda: {"slots": 0, "boss_slots": 0, "npcs": set(), "arena_npcs": []}
    )
    for s in slots:
        p5 = str(s.get("model", ""))[:5]
        if p5 in M61_EXCLUDE_PREFIXES or p5 in SKIP_PREFIXES or p5 in NEVER_DONOR_PREFIXES:
            continue
        by_p5[p5]["slots"] += 1
        nid = int(s.get("npc") or 0)
        by_p5[p5]["npcs"].add(nid)
        slot_name = str(s.get("name", ""))
        if "_9000" in slot_name or slot_name.endswith("_9001") or "_900" in slot_name:
            by_p5[p5]["arena_npcs"].append(nid)
        tpl = {
            "model": s["model"],
            "npc": int(s.get("npc") or 0),
            "think": s.get("think", 0),
            "map": s["map"],
        }
        if bnd.template_is_detected_boss(tpl, csv_dir=GAME / "csv", categories_cfg=cats):
            by_p5[p5]["boss_slots"] += 1

    trash_entries: list[dict] = []
    boss_entries: list[dict] = []
    skipped: list[dict] = []

    for p5, rec in sorted(by_p5.items(), key=lambda x: -x[1]["slots"]):
        if p5 in NEVER_DONOR_PREFIXES:
            skipped.append({"prefix": p5, "slots": rec["slots"], "reason": "never_donor"})
            continue
        effs = []
        boss_cat = FORCE_M61_BOSS_CATEGORY.get(p5, "")
        for nid in rec["npcs"]:
            row = npc_by_id.get(nid)
            if not row:
                continue
            eff, _, _ = combat_hp_detailed(row, sp_rates)
            if eff > 0:
                effs.append(eff)
            if boss_cat:
                continue
            tpl = {"model": p5, "npc": nid, "think": 0, "map": "m61_44_44_00"}
            if bnd.template_is_detected_boss(tpl, csv_dir=GAME / "csv", categories_cfg=cats):
                boss_cat = bnd.classify_detected_boss(
                    p5, donor_map_id="m61_44_44_00", categories_cfg=cats
                )
        max_eff = max(effs) if effs else 0
        prefer = list(dict.fromkeys(rec["arena_npcs"]))
        pick = pick_dlc_donor_npc(
            p5,
            npc_by_id,
            sp_rates=sp_rates,
            min_effective_hp=0,
            prefer_npcs=prefer,
            for_boss_pool=boss_cat in BOSS_TARGET_CATEGORIES,
        )
        if not pick:
            skipped.append({"prefix": p5, "slots": rec["slots"], "reason": "no_npc"})
            continue

        entry_base = {
            "prefix": p5,
            "zh": zh.get(p5, "—"),
            "m61_slots": rec["slots"],
            **pick,
        }
        if boss_cat in BOSS_TARGET_CATEGORIES and max_eff >= MIN_BOSS_COMBAT_HP:
            boss_entries.append({**entry_base, "category": boss_cat})
        elif max_eff >= MIN_TRASH_COMBAT_HP or p5 in tax_force:
            trash_entries.append({**entry_base, "category": "trash"})
        else:
            skipped.append(
                {
                    "prefix": p5,
                    "slots": rec["slots"],
                    "max_eff": max_eff,
                    "reason": "low_hp",
                }
            )

    boss_prefix_set = {e["prefix"] for e in boss_entries}
    trash_prefix_set = {e["prefix"] for e in trash_entries}
    for p5 in sorted(tax_force):
        if p5 in trash_prefix_set or p5 in boss_prefix_set:
            continue
        pick = pick_dlc_donor_npc(
            p5,
            npc_by_id,
            sp_rates=sp_rates,
            min_effective_hp=0,
        )
        if not pick:
            skipped.append({"prefix": p5, "slots": 0, "reason": "taxonomy_no_npc"})
            continue
        trash_entries.append(
            {
                "prefix": p5,
                "zh": zh.get(p5, "—"),
                "m61_slots": 0,
                "category": "trash",
                **pick,
            }
        )
        trash_prefix_set.add(p5)

    manifest = {
        "version": 2,
        "source": "m61_msb_scan",
        "exclude_prefixes": sorted(M61_EXCLUDE_PREFIXES),
        "never_donor_prefixes": sorted(NEVER_DONOR_PREFIXES),
        "min_trash_combat_hp": MIN_TRASH_COMBAT_HP,
        "min_boss_combat_hp": MIN_BOSS_COMBAT_HP,
        "trash": trash_entries,
        "boss": boss_entries,
        "skipped": skipped,
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    trash_prefixes = [e["prefix"] for e in trash_entries]
    boss_prefixes = [e["prefix"] for e in boss_entries]
    minor_boss_prefixes = [
        e["prefix"] for e in boss_entries if e.get("category") == "minor_boss"
    ]
    all_dlc_prefixes = sorted(set(trash_prefixes + boss_prefixes))

    block = set(M61_EXCLUDE_PREFIXES) | set(NEVER_DONOR_PREFIXES)
    boss_set = {p.lower() for p in boss_prefixes}
    trash_set = {p.lower() for p in trash_prefixes}
    cats["dlc_trash_donor_model_prefixes"] = merge_prefix_list(
        [
            p
            for p in (cats.get("dlc_trash_donor_model_prefixes") or [])
            if p.lower() not in block and p.lower() not in boss_set
        ],
        trash_prefixes,
    )
    cats["minor_boss_donor_model_prefixes"] = merge_prefix_list(
        cats.get("minor_boss_donor_model_prefixes") or [],
        minor_boss_prefixes,
    )
    cats["dlc_boss_model_prefixes"] = merge_prefix_list(
        [
            p
            for p in (cats.get("dlc_boss_model_prefixes") or [])
            if p.lower() not in block and p.lower() not in trash_set
        ],
        boss_prefixes,
    )
    cats["never_donor_model_prefixes"] = merge_prefix_list(
        cats.get("never_donor_model_prefixes") or [],
        sorted(NEVER_DONOR_PREFIXES),
    )
    synth_block = set(cats.get("boss_pool_exclude_synthetic_template_ids") or [])
    # T-097：废止 synthetic 精确禁；不再自动塞回 bayle
    cats["boss_pool_exclude_synthetic_template_ids"] = sorted(synth_block)
    display_zh = dict(cats.get("model_prefix_display_zh") or {})
    display_zh.update(M61_BOSS_ZH)
    cats["model_prefix_display_zh"] = display_zh
    cats["donor_origin_by_model_prefix"] = [
        r
        for r in ensure_donor_origin_rules(
            cats.get("donor_origin_by_model_prefix") or [],
            all_dlc_prefixes,
            "dlc",
        )
        if str(r.get("prefix", "")).lower() not in block
    ]
    cats["dlc_trash_definition"] = (
        "DLC 幽影之地捐皮：m61 扫描入库（排除 c5401/c5410/c5450/c5240/c5490 环境生物）；"
        "NpcParam 选行按有效 HP + 优先 20007 倍率包；全图混池"
    )
    CATEGORIES.write_text(json.dumps(cats, ensure_ascii=False, indent=2), encoding="utf-8")

    arch = json.loads(ARCHETYPES.read_text(encoding="utf-8-sig"))
    arch_list = list(arch.get("trash_archetypes") or [])
    dlc_arch_id = "dlc_m61"
    dlc_models = sorted({e["prefix"] for e in trash_entries})
    # Boss 模型不进 trash 原型彩票
    boss_only = {e["prefix"] for e in boss_entries}
    dlc_models = [m for m in dlc_models if m not in boss_only]
    found = False
    for raw in arch_list:
        if str(raw.get("id")) == dlc_arch_id:
            raw["label_zh"] = "DLC幽影（m61入库）"
            raw["models"] = merge_prefix_list(
                [m for m in (raw.get("models") or []) if m.lower() not in boss_set],
                dlc_models,
            )
            found = True
            break
    if not found:
        arch_list.append(
            {
                "id": dlc_arch_id,
                "label_zh": "DLC幽影（m61入库）",
                "models": dlc_models,
            }
        )
    # 也并入已有 archetype，避免单池过窄
    merge_map = {
        "soldier": {
            "c5060", "c5080", "c5090", "c5190", "c5040", "c5180", "c5280", "c5340",
        },
        "crustacean": {"c5440", "c5550", "c5560", "c5590"},
        "wolf": {"c5523", "c5570"},
        "critter": {"c5740", "c5760", "c5761", "c5900", "c5830", "c6290"},
    }
    by_id = {str(a.get("id")): a for a in arch_list}
    for arch_id, models in merge_map.items():
        if arch_id not in by_id:
            continue
        by_id[arch_id]["models"] = merge_prefix_list(
            by_id[arch_id].get("models") or [],
            sorted(m for m in dlc_models if m in models),
        )
    arch["trash_archetypes"] = arch_list
    arch["version"] = int(arch.get("version") or 0) + 1
    ARCHETYPES.write_text(json.dumps(arch, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# m61 DLC 捐皮池入库",
        "",
        f"- 永不捐皮：**{', '.join(sorted(NEVER_DONOR_PREFIXES))}**",
        f"- 排除环境前五：**{', '.join(sorted(M61_EXCLUDE_PREFIXES))}**",
        f"- 小兵池（trash）：**{len(trash_entries)}** 种模型",
        f"- Boss 池（synthetic）：**{len(boss_entries)}** 种模型",
        f"- 跳过（低血/无 npc）：**{len(skipped)}**",
        "",
        "## 小兵池（有效 HP≥1000）",
        "",
        "| 模型 | 中文 | m61槽 | npc | 表HP | 倍率 | 有效HP |",
        "|---|---|---:|---:|---:|---|---:|",
    ]
    for e in trash_entries:
        lines.append(
            f"| {e['prefix']} | {e['zh']} | {e['m61_slots']} | {e['npc']} | {e['table_hp']} | {e['hp_mult_desc']} | {e['effective_hp']} |"
        )
    lines += [
        "",
        "## Boss 池",
        "",
        "| 模型 | 中文 | 类别 | m61槽 | npc | 表HP | 有效HP |",
        "|---|---|---|---:|---:|---:|---:|",
    ]
    for e in boss_entries:
        lines.append(
            f"| {e['prefix']} | {e['zh']} | {e['category']} | {e['m61_slots']} | {e['npc']} | {e['table_hp']} | {e['effective_hp']} |"
        )
    lines += ["", "清单：`m61_dlc_donor_pool.json`", ""]
    OUT_REPORT.write_text("\n".join(lines), encoding="utf-8")

    print(f"wrote {MANIFEST}")
    print(f"wrote {OUT_REPORT}")
    print(f"trash={len(trash_entries)} boss={len(boss_entries)} skipped={len(skipped)}")


if __name__ == "__main__":
    main()
