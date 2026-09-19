"""关卡前方认狗 · 按 NpcParam 英文名筛 DLC 犬（不用整段编号糊上去）。

白名单：英文名含 Stray / Braided Stray / Bloodbane Stray
黑名单：Watchdog · Wolf · Starved · Rotten · Giant · Azula 等
"""
from __future__ import annotations

import csv
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from paths import SCRIPT_DIR  # frozen-safe
M61_SLOTS = SCRIPT_DIR.parent / "reports" / "_m61_slots.jsonl"
CATALOG_CACHE = SCRIPT_DIR / "test_lab" / "gatefront_dog_catalog.json"

# 英文名黑名单（子串命中即排除）
ENGLISH_NAME_EXCLUDE: tuple[str, ...] = (
    "Watchdog",
    "Wolf",
    "Ballista",
    "Rotten",
    "Giant",
    "Starved",
    "Azula",
    "Monstrous",
    "Mushroom",
    "Gowry",
    "Caimar",
    "Summon",
)

# 四足犬模前缀（体态桶，只作二次校验）
DOG_MODEL_PREFIXES: tuple[str, ...] = tuple(f"c552{i}" for i in range(8))

# 马车旁旧试验槽（已由 F6 标定槽取代，保留兼容）
WAGON_TEST_SLOTS: tuple[str, ...] = (
    "c4311_9000",
    "c4311_9001",
    "c4311_9002",
    "c4311_9004",
    "c4311_9005",
    "c4311_9006",
    "c4311_9008",
    "c4311_9009",
    "c4311_9010",
    "c4311_9011",
    "c4311_9012",
    "c4311_9013",
    "c4311_9014",
    "c4311_9015",
    "c4311_9018",
    "c4311_9019",
    "c4311_9020",
    "c4311_9021",
    "c4311_9022",
)

# 关卡前方 · F6 真机标定测试槽（2026-08-13，15 次标记 → 6 个唯一槽）
# + 2026-08-19：3 个蝙蝠巡逻槽（飞巡；非挂靠；不占 note2～15 分批行）
GATEFRONT_MARKED_SLOTS_PATH = SCRIPT_DIR / "test_lab" / "gatefront_marked_slots.json"
GATEFRONT_BAT_TEST_SLOTS: tuple[str, ...] = (
    "c4200_9000",
    "c4200_9001",
    "c4200_9002",
)
# note1～15 唯一物理槽（含赐福）；认狗/分批写盘仍只用这些，不含蝙蝠
GATEFRONT_CORE_MARKED_TEST_SLOTS: tuple[str, ...] = (
    "c1000_9002",
    "c4311_9008",
    "c4311_9002",
    "c4311_9005",
    "c4351_9000",
    "c4311_9014",
)
# init / inject / keep：核心标定 + 3 蝙蝠巡逻槽
GATEFRONT_MARKED_TEST_SLOTS: tuple[str, ...] = (
    *GATEFRONT_CORE_MARKED_TEST_SLOTS,
    *GATEFRONT_BAT_TEST_SLOTS,
)

DOG_LINEUP_SLOTS: tuple[str, ...] = GATEFRONT_CORE_MARKED_TEST_SLOTS

# 士兵槽（c4311）真机已证：外观并成 3 种皮，禁止用于认辫毛/长毛
SOLDIER_SLOT_INVALID_FOR_APPEARANCE: tuple[str, ...] = tuple(
    slot for slot in GATEFRONT_MARKED_TEST_SLOTS if slot.startswith("c4311_")
)

# 关卡前方 · 原生四足战斗槽（赐福→马车沿途 c4070 狼/狗位）
QUADRUPED_LINEUP_SLOTS: tuple[str, ...] = (
    "c4070_9000",
    "c4070_9001",
    "c4070_9015",
    "c4070_9016",
    "c4070_9017",
    "c4070_9018",
    "c4070_9019",
    "c4070_9020",
    "c4070_9021",
)

# 废墟周边「电球/锁不上」干扰槽
# c4311_9015 MSB≈(87,97,55) 废墟中央吹号士兵（与 c4070_9000 同点）
# c4311_9004 MSB≈(72,99,69) 随机成囚牢电球 c5780；F6 站废墟内约 12m
GATEFRONT_MAP_ID = "m60_42_37_00"
GRACE_SUPPRESS_SLOT = "c1000_9002"
DECORATIVE_SLOT_PREFIXES: tuple[str, ...] = ("c0100",)

RUINS_BLOCKER_FIX_MODEL = "c4311"
RUINS_BLOCKER_FIXES: tuple[tuple[str, int, str], ...] = (
    ("c4311_9015", 43112110, "m60_42_37_00:c4311_9015"),
    ("c4311_9004", 43110010, "m60_42_37_00:c4311_9001"),
)
RUINS_BLOCKER_SLOTS: tuple[str, ...] = tuple(slot for slot, _, _ in RUINS_BLOCKER_FIXES)
SOLDIER_FIX_DEFAULT_NPC = 43110010
SOLDIER_FIX_DEFAULT_TEMPLATE = "m60_42_37_00:c4311_9001"


def _gatefront_vanilla_npc_by_slot() -> dict[str, int]:
    from enemy_randomizer_core import load_enemy_index

    out: dict[str, int] = {}
    index = load_enemy_index()
    for slot in index.get("slots") or []:
        if str(slot.get("map_id") or "") != GATEFRONT_MAP_ID:
            continue
        name = str(slot.get("name") or "")
        npc = int(slot.get("npc") or 0)
        if name and npc > 0:
            out[name] = npc
    return out


def _soldier_npc_for_slot(slot: str) -> int:
    for name, npc, _ in RUINS_BLOCKER_FIXES:
        if name == slot:
            return npc
    vanilla = _gatefront_vanilla_npc_by_slot().get(slot)
    if vanilla and str(vanilla).startswith("4311"):
        return vanilla
    return SOLDIER_FIX_DEFAULT_NPC


def _soldier_template_for_slot(slot: str) -> str:
    for name, _, template in RUINS_BLOCKER_FIXES:
        if name == slot:
            return template
    if slot.startswith("c4311"):
        return f"{GATEFRONT_MAP_ID}:{slot}"
    return SOLDIER_FIX_DEFAULT_TEMPLATE


def _is_electric_orb_spawn_row(row: dict[str, Any]) -> bool:
    model = str(row.get("model") or "")
    template = str(row.get("template_id") or "")
    tgt = str(row.get("tgt_cat") or "")
    donor = int(row.get("npc_donor") or row.get("npc") or 0)
    if model == "c5780" or "c5780" in template:
        return True
    if 57800000 <= donor <= 57899999:
        return True
    if tgt == "evergaol" and "5780" in template:
        return True
    return False


def _soldier_fix_spec(
    slot: str,
    *,
    label: str,
    vanilla_npc: bool,
) -> dict[str, Any]:
    npc = _soldier_npc_for_slot(slot)
    return {
        "label": label,
        "template": _soldier_template_for_slot(slot),
        "npc": npc,
        "think": (npc // 100) * 100,
        "model": RUINS_BLOCKER_FIX_MODEL,
        "tgt_cat": "trash",
        "force_ground": True,
        "vanilla_npc": vanilla_npc,
    }


def build_electric_orb_fix_specs(
    rows: list[dict[str, Any]],
    *,
    map_id: str = GATEFRONT_MAP_ID,
    vanilla_npc: bool = True,
) -> dict[str, dict[str, Any]]:
    specs: dict[str, dict[str, Any]] = {}
    for row in rows:
        if str(row.get("map_id") or "") != map_id:
            continue
        if not _is_electric_orb_spawn_row(row):
            continue
        slot = str(row.get("entity_name") or "")
        if not slot:
            continue
        specs[slot] = _soldier_fix_spec(
            slot,
            label="electric_orb_fix",
            vanilla_npc=vanilla_npc,
        )
    return specs


def build_ruins_blocker_fix_specs(*, vanilla_npc: bool = True) -> dict[str, dict[str, Any]]:
    specs: dict[str, dict[str, Any]] = {}
    for slot, _, _ in RUINS_BLOCKER_FIXES:
        specs[slot] = _soldier_fix_spec(
            slot,
            label="ruins_blocker_fix",
            vanilla_npc=vanilla_npc,
        )
    return specs


def build_gatefront_vanilla_soldier_specs(
    assignments: list[dict[str, Any]],
    *,
    exclude: set[str] | frozenset[str] | None = None,
    vanilla_npc: bool = True,
    suppress_grace: bool = True,
) -> dict[str, dict[str, Any]]:
    """关卡前方试验台：除 exclude 外全图固定原版士兵（便于肉眼认四足捐皮）。"""
    exclude_set = set(exclude or ())
    specs: dict[str, dict[str, Any]] = {}
    for row in assignments:
        if str(row.get("map_id") or "") != GATEFRONT_MAP_ID:
            continue
        slot = str(row.get("entity_name") or "")
        if not slot or slot in exclude_set:
            continue
        if any(slot.startswith(p) for p in DECORATIVE_SLOT_PREFIXES):
            specs[slot] = {"suppress": True}
            continue
        specs[slot] = _soldier_fix_spec(
            slot,
            label="vanilla_soldier",
            vanilla_npc=vanilla_npc,
        )
    if suppress_grace and GRACE_SUPPRESS_SLOT not in exclude_set:
        specs[GRACE_SUPPRESS_SLOT] = {"suppress": True}
    return specs


def build_gatefront_blocker_fix_specs(
    rows: list[dict[str, Any]],
    *,
    vanilla_npc: bool = True,
) -> dict[str, dict[str, Any]]:
    specs = build_ruins_blocker_fix_specs(vanilla_npc=vanilla_npc)
    specs.update(build_electric_orb_fix_specs(rows, vanilla_npc=vanilla_npc))
    return specs


def _npc_csv_path() -> Path:
    from paths import GAME_DIR

    p = GAME_DIR / "csv" / "NpcParam.csv"
    if p.is_file():
        return p
    raise FileNotFoundError(f"NpcParam.csv not found: {p}")


@lru_cache(maxsize=1)
def load_npc_english_names() -> dict[int, str]:
    out: dict[int, str] = {}
    with _npc_csv_path().open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            try:
                nid = int(row.get("ID") or row.get("id") or 0)
            except (TypeError, ValueError):
                continue
            name = str(row.get("Name") or row.get("name") or "").strip()
            if name:
                out[nid] = name
    return out


def is_stray_dog_english(name: str) -> bool:
    """是否战斗流浪狗（看英文名，不看编号段）。"""
    if not name:
        return False
    if any(tok in name for tok in ENGLISH_NAME_EXCLUDE):
        return False
    if name == "Stray" or name.startswith("Stray ("):
        return True
    if name == "Braided Stray" or name.startswith("Braided Stray"):
        return True
    if name == "Bloodbane Stray" or name.startswith("Bloodbane Stray"):
        return True
    return False


def is_braided_stray_english(name: str) -> bool:
    return name == "Braided Stray" or name.startswith("Braided Stray")


def _slug_key(english: str, npc: int, template: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", english.lower()).strip("_")
    map_part = template.split(":", 1)[0].replace("_", "")
    return f"{slug}_{npc}_{map_part}"


def _load_m61_slot_rows() -> list[dict[str, Any]]:
    if not M61_SLOTS.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in M61_SLOTS.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rows.append(json.loads(line))
    return rows


def build_dog_catalog(*, refresh: bool = False) -> dict[str, dict[str, Any]]:
    if not refresh and CATALOG_CACHE.is_file():
        try:
            cached = json.loads(CATALOG_CACHE.read_text(encoding="utf-8-sig"))
            if isinstance(cached.get("entries"), dict) and cached["entries"]:
                return cached["entries"]
        except (OSError, json.JSONDecodeError):
            pass

    names = load_npc_english_names()
    seen_npc: set[int] = set()
    entries: dict[str, dict[str, Any]] = {}

    for row in _load_m61_slot_rows():
        model = str(row.get("model") or "").lower()
        if not any(model.startswith(p) for p in DOG_MODEL_PREFIXES):
            continue
        npc = int(row.get("npc") or 0)
        if npc <= 0 or npc in seen_npc:
            continue
        english = names.get(npc, "")
        if not is_stray_dog_english(english):
            continue
        seen_npc.add(npc)
        msb_map = str(row.get("map") or "")
        entity = str(row.get("name") or "")
        template = f"{msb_map}:{entity}"
        key = _slug_key(english, npc, template)
        entries[key] = {
            "key": key,
            "english": english,
            "npc": npc,
            "think": int(row.get("think") or (npc // 100) * 100),
            "model": model,
            "template": template,
            "long_hair_candidate": is_braided_stray_english(english),
            "source_msb": msb_map,
        }

    CATALOG_CACHE.parent.mkdir(parents=True, exist_ok=True)
    CATALOG_CACHE.write_text(
        json.dumps(
            {
                "schema": "gatefront_dog_catalog_v1",
                "filter": "english_stray_whitelist",
                "entries": entries,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return entries


def get_dog_entry(key: str) -> dict[str, Any]:
    catalog = build_dog_catalog()
    if key not in catalog:
        keys = ", ".join(sorted(catalog)[:8])
        raise KeyError(f"unknown dog_key={key!r}; try dog-list (sample: {keys})")
    return catalog[key]


def resolve_runtime_npc_label(npc: int, copies_path: Path | None = None) -> str:
    """叠层里 8800000xx → 英文名 + 原版 npc。"""
    names = load_npc_english_names()
    if 880_000_000 <= npc < 881_000_000 and copies_path and copies_path.is_file():
        try:
            data = json.loads(copies_path.read_text(encoding="utf-8-sig"))
            for item in data.get("copies") or []:
                if int(item.get("copy_id") or 0) == npc:
                    base = int(item.get("base_npc") or 0)
                    en = names.get(base, "?")
                    return f"copy={npc} base_npc={base} english={en!r}"
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass
    en = names.get(npc, "")
    if en:
        return f"npc={npc} english={en!r}"
    return f"npc={npc}"


def dog_lineup_slots() -> tuple[str, ...]:
    return GATEFRONT_MARKED_TEST_SLOTS


def quadruped_lineup_slots() -> tuple[str, ...]:
    return QUADRUPED_LINEUP_SLOTS


def visual_bucket_for_model(model: str) -> str:
    """士兵槽真机归纳的 3 桶（四足槽上可能不同，仅作对照）。"""
    m = str(model or "").lower()
    if m.startswith("c5520"):
        return "着火"
    if m.startswith("c5522"):
        return "黑狗"
    return "白秃"


def ordered_dog_catalog_entries() -> list[dict[str, Any]]:
    catalog = build_dog_catalog()
    return sorted(
        catalog.values(),
        key=lambda e: (
            0 if e["long_hair_candidate"] else 1,
            0 if e["english"] == "Stray" else 1 if e["english"] == "Bloodbane Stray" else 2,
            int(e["npc"]),
        ),
    )


# 真机四角标点（HUD pos local + 所在图）→ 统一铺到 m60_42_37_00 四足槽
QUAD_SPAWN_CORNERS: tuple[dict[str, Any], ...] = (
    {"map": "m60_42_37_00", "lx": 3.1, "ly": -2.4, "lz": 19.5},
    {"map": "m60_42_38_00", "lx": 13.3, "ly": -3.6, "lz": 4.3},
    {"map": "m60_43_37_00", "lx": 1.2, "ly": -3.3, "lz": -4.9},
    {"map": "m60_42_37_00", "lx": -31.5, "ly": 5.0, "lz": -27.9},
)
QUAD_SPAWN_TARGET_MAP = "m60_42_37_00"
QUAD_SPAWN_TILE = (42, 37)
QUAD_SPAWN_TILE_SIZE = 256
# 由赐福旁真机标定：unified local → MSB（关卡前方 c4070 槽）
_QUAD_MSB_OFFSET = (118.6, 152.0, 84.6)


def _parse_map_tile(map_id: str) -> tuple[int, int]:
    parts = str(map_id or "").split("_")
    if len(parts) < 4:
        raise ValueError(f"bad map_id={map_id!r}")
    return int(parts[1]), int(parts[2])


def _corner_unified_local(corner: dict[str, Any]) -> tuple[float, float, float]:
    bx, by = _parse_map_tile(str(corner["map"]))
    tx, ty = QUAD_SPAWN_TILE
    return (
        (bx - tx) * QUAD_SPAWN_TILE_SIZE + float(corner["lx"]),
        float(corner["ly"]),
        (by - ty) * QUAD_SPAWN_TILE_SIZE + float(corner["lz"]),
    )


def _unified_to_msb(ux: float, uy: float, uz: float) -> tuple[float, float, float]:
    ox, oy, oz = _QUAD_MSB_OFFSET
    return (ux + ox, uy + oy, uz + oz)


def layout_quad_spawn_positions(count: int) -> list[dict[str, float]]:
    """在四足认狗区铺网格，返回 MSB pos_x/y/z。"""
    if count <= 0:
        return []
    unified = [_corner_unified_local(c) for c in QUAD_SPAWN_CORNERS]
    xs = [p[0] for p in unified]
    zs = [p[2] for p in unified]
    min_x, max_x = min(xs), max(xs)
    min_z, max_z = min(zs), max(zs)
    avg_y = sum(p[1] for p in unified) / len(unified)
    cols = 3 if count >= 9 else max(1, int(round(count**0.5)))
    rows = (count + cols - 1) // cols
    out: list[dict[str, float]] = []
    for i in range(count):
        r, c = divmod(i, cols)
        tx = (c + 0.5) / cols if cols > 1 else 0.5
        tz = (r + 0.5) / rows if rows > 1 else 0.5
        ux = min_x + tx * (max_x - min_x)
        uz = min_z + tz * (max_z - min_z)
        px, py, pz = _unified_to_msb(ux, avg_y, uz)
        out.append({"pos_x": px, "pos_y": py, "pos_z": pz})
    return out


def quad_batch_count() -> int:
    n = len(ordered_dog_catalog_entries())
    size = len(QUADRUPED_LINEUP_SLOTS)
    return (n + size - 1) // size if size else 0


def build_quadruped_dog_lineup_specs(
    *,
    batch: int = 1,
    vanilla_npc: bool = True,
) -> tuple[dict[str, dict[str, Any]], int, int, int]:
    """四足槽认外观：每批最多 9 只，士兵槽不碰。"""
    if batch < 1:
        raise ValueError("quad batch must be >= 1")
    ordered = ordered_dog_catalog_entries()
    size = len(QUADRUPED_LINEUP_SLOTS)
    total_batches = quad_batch_count()
    if batch > total_batches:
        raise ValueError(f"quad batch {batch} > total {total_batches}")
    start = (batch - 1) * size
    chunk = ordered[start : start + size]
    positions = layout_quad_spawn_positions(len(chunk))
    specs: dict[str, dict[str, Any]] = {}
    for slot, entry, pos in zip(QUADRUPED_LINEUP_SLOTS[: len(chunk)], chunk, positions):
        specs[slot] = {
            "label": f"{entry['english']} #{entry['npc']}",
            "template": entry["template"],
            "npc": entry["npc"],
            "think": entry["think"],
            "model": entry["model"],
            "vanilla_npc": vanilla_npc,
            "dog_key": entry["key"],
            "visual_bucket_soldier": visual_bucket_for_model(str(entry["model"])),
            "slot_kind": "quadruped",
            **pos,
        }
    return specs, batch, len(chunk), total_batches


def build_all_dog_lineup_specs(*, vanilla_npc: bool = True) -> dict[str, dict[str, Any]]:
    """每种英文名白名单狗占一个槽；不 suppress 其它槽。"""
    catalog = build_dog_catalog()
    ordered = sorted(
        catalog.values(),
        key=lambda e: (
            0 if e["long_hair_candidate"] else 1,
            0 if e["english"] == "Stray" else 1 if e["english"] == "Bloodbane Stray" else 2,
            int(e["npc"]),
        ),
    )
    slots = dog_lineup_slots()
    if len(ordered) > len(slots):
        raise RuntimeError(f"dog catalog {len(ordered)} > lineup slots {len(slots)}")
    specs: dict[str, dict[str, Any]] = {}
    for slot, entry in zip(slots, ordered):
        specs[slot] = {
            "label": f"{entry['english']} #{entry['npc']}",
            "template": entry["template"],
            "npc": entry["npc"],
            "think": entry["think"],
            "model": entry["model"],
            "vanilla_npc": vanilla_npc,
            "dog_key": entry["key"],
        }
    return specs


def format_dog_list() -> str:
    catalog = build_dog_catalog()
    ordered = ordered_dog_catalog_entries()
    lines = [
        "# DLC 流浪狗目录（英文名白名单 · 每条独立 npc，非编号段）",
        "# long_hair=英文名 Braided Stray，即辫毛/长毛卷毛候选",
        "# 士兵槽 c4311 已排除（外观并 3 皮）；四足槽见 quad batch",
        "",
        f"{'KEY':<42} {'ENGLISH':<22} {'NPC':>10}  {'BATCH':>5}  TEMPLATE",
        "-" * 118,
    ]
    size = len(QUADRUPED_LINEUP_SLOTS)
    for i, e in enumerate(ordered):
        key = e["key"]
        batch_no = i // size + 1
        mark = "*" if e["long_hair_candidate"] else " "
        lines.append(
            f"{mark}{key:<41} {e['english']:<22} {e['npc']:>10}  {batch_no:>5}  {e['template']}"
        )
    lines.append("")
    lines.append(f"共 {len(catalog)} 条（* = Braided Stray 长毛候选）")
    return "\n".join(lines)
