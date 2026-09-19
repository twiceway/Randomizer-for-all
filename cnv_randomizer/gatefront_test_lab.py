"""关卡前方真机试验台 — 只改指定槽，快速 apply。

用法：
  python gatefront_test_lab.py init          # 一次性生成基线（~7s）
  python gatefront_test_lab.py dog-list      # 按英文名列出 DLC 流浪狗（一条一 npc）
  python gatefront_test_lab.py apply         # 读 gatefront_test_lab.json → 写盘
  python gatefront_test_lab.py explain 880000017   # 叠层编号 → 英文名
  python gatefront_test_lab.py quad-table      # 四足分批表（每组15）写 test_lab/
  python gatefront_test_lab.py apply-quad --batch 1   # 四足表 · 写到 c4070 四足槽
  python gatefront_test_lab.py apply-quad-human --batch 1  # 四足皮 → F6 人形 mark 槽
  python gatefront_test_lab.py fly-table       # 飞行分批表（每组 14）写 test_lab/
  python gatefront_test_lab.py apply-fly --batch 1   # 飞行皮 → F6 标定 14 槽
  python gatefront_test_lab.py apply-crow            # 14 槽多种大乌鸦轮询
  python gatefront_test_lab_gui.py             # GUI：选组/波 → 写盘（或 GATEFRONT_QUAD_GUI.bat）

认狗看 NpcParam 英文名（Stray / Braided Stray），不用整段编号；一次只测 dog_key 一只。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from paths import SCRIPT_DIR  # frozen-safe
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from enemy_apply_runner import run_enemy_apply
from enemy_randomizer_core import (
    _load_json,
    spawn_map_sidecar_paths,
    write_spawn_map,
)
from gatefront_dog_catalog import (
    GATEFRONT_MARKED_TEST_SLOTS,
    GRACE_SUPPRESS_SLOT,
    QUADRUPED_LINEUP_SLOTS,
    SOLDIER_SLOT_INVALID_FOR_APPEARANCE,
    WAGON_TEST_SLOTS,
    build_all_dog_lineup_specs,
    build_dog_catalog,
    build_gatefront_vanilla_soldier_specs,
    build_quadruped_dog_lineup_specs,
    build_ruins_blocker_fix_specs,
    build_gatefront_blocker_fix_specs,
    dog_lineup_slots,
    format_dog_list,
    get_dog_entry,
    quad_batch_count,
    quadruped_lineup_slots,
    resolve_runtime_npc_label,
)

MAP_ID = "m60_42_37_00"
DEFAULT_SEED = 976847321
DEFAULT_CONFIG = SCRIPT_DIR / "gatefront_test_lab.json"
BASELINE_DIR = SCRIPT_DIR / "test_lab" / "gatefront_baseline"
OUT_DIR = SCRIPT_DIR / "output" / "runtime" / "_gatefront_lab"
DONOR_CHARA = -1

# 真机测试槽真源：gatefront_dog_catalog.GATEFRONT_MARKED_TEST_SLOTS


def _think_from_npc(npc: int) -> int:
    return (npc // 100) * 100


def _model_from_template(template: str) -> str:
    entity = template.split(":", 1)[-1]
    m = re.match(r"(c\d+)", entity, re.I)
    if not m:
        raise ValueError(f"cannot parse model from template={template!r}")
    return m.group(1).lower()


def _inject_missing_marked_slots(
    assignments: list[dict[str, Any]],
    slot_names: tuple[str, ...] | list[str],
) -> list[str]:
    """随机化 skip 的 F6 标定槽，从 enemy_index 注入占位行以便 MSB apply。"""
    by_name = {str(r["entity_name"]): r for r in assignments}
    missing = [s for s in slot_names if s not in by_name]
    if not missing:
        return []

    from enemy_randomizer_core import load_enemy_index

    index_by_key = {
        (str(s.get("map_id")), str(s.get("name"))): s
        for s in load_enemy_index().get("slots") or []
    }
    injected: list[str] = []
    for entity_name in missing:
        slot = index_by_key.get((MAP_ID, entity_name))
        if not slot:
            continue
        walk = str(slot.get("walk_route") or "")
        placement = "patrol" if walk else "ground"
        npc = int(slot.get("npc") or 0)
        assignments.append(
            {
                "map_id": MAP_ID,
                "entity_name": entity_name,
                "src_cat": str(slot.get("src_cat") or "trash"),
                "tgt_cat": "trash",
                "template_id": f"lab_inject:{entity_name}",
                "model": str(slot.get("model") or ""),
                "npc": npc,
                "think": int(slot.get("think") or (npc // 100) * 100),
                "chara": -1,
                "rune_amount": 674,
                "npc_donor": npc,
                "placement_kind": placement,
                "walk_route": walk,
                "backup_anim": int(slot.get("backup_anim", -1)),
                "pos_x": float(slot.get("pos_x", 0)),
                "pos_y": float(slot.get("pos_y", 0)),
                "pos_z": float(slot.get("pos_z", 0)),
            }
        )
        injected.append(entity_name)
    return injected


def _parse_spawn_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#") or "=" in line and "\t" not in line:
            continue
        parts = line.split("\t")
        if len(parts) < 13:
            continue
        rows.append(
            {
                "map_id": parts[0],
                "entity_name": parts[1],
                "src_cat": parts[2],
                "tgt_cat": parts[3],
                "template_id": parts[4],
                "model": parts[5],
                "npc": int(parts[6]),
                "think": int(parts[7]),
                "chara": int(parts[8]),
                "rune_amount": int(parts[9]),
                "npc_donor": int(parts[12]),
            }
        )
    return rows


def _baseline_spawn_path(seed: int) -> Path:
    return BASELINE_DIR / ".apply_staging" / f"cnv_enemy_spawn_map_{seed}.txt"


def _load_config(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"missing config: {path}")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _build_index_assignments(map_id: str) -> list[dict[str, Any]]:
    """从 enemy_index 导出原版槽行（不随机化）。"""
    from enemy_randomizer_core import load_enemy_index

    out: list[dict[str, Any]] = []
    for slot in load_enemy_index().get("slots") or []:
        if str(slot.get("map_id") or "") != map_id:
            continue
        entity_name = str(slot.get("name") or "")
        if not entity_name:
            continue
        walk = str(slot.get("walk_route") or "")
        npc = int(slot.get("npc") or 0)
        model = str(slot.get("model") or "")
        out.append(
            {
                "map_id": map_id,
                "entity_name": entity_name,
                "src_cat": str(slot.get("src_cat") or "trash"),
                "tgt_cat": "trash",
                "template_id": f"vanilla:{map_id}:{entity_name}",
                "model": model,
                "npc": npc,
                "think": int(slot.get("think") or (npc // 100) * 100),
                "chara": int(slot.get("chara", -1)),
                "rune_amount": 674,
                "npc_donor": npc,
                "placement_kind": "patrol" if walk else "ground",
                "walk_route": walk,
                "backup_anim": int(slot.get("backup_anim", -1)),
                "pos_x": float(slot.get("pos_x", 0)),
                "pos_y": float(slot.get("pos_y", 0)),
                "pos_z": float(slot.get("pos_z", 0)),
            }
        )
    return out


def _lineup_donor_key(spec: dict[str, Any]) -> str:
    return str(spec.get("fly_key") or spec.get("quad_key") or "")


def _merge_quad_lineup_specs(
    cfg: dict[str, Any],
    baseline_rows: list[dict[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    from gatefront_quad_catalog import build_quad_apply_specs

    quad_specs, _ = build_quad_apply_specs(
        int(cfg.get("quad_batch", 1)),
        vanilla_npc=bool(cfg.get("vanilla_npc", True)),
        write_target="mark_slot",
    )
    donor_slots = {s for s, sp in quad_specs.items() if _lineup_donor_key(sp)}
    merged = build_gatefront_vanilla_soldier_specs(
        baseline_rows or [],
        exclude=donor_slots,
        vanilla_npc=bool(cfg.get("vanilla_npc", True)),
    )
    for slot, spec in quad_specs.items():
        if _lineup_donor_key(spec):
            merged[slot] = spec
        elif slot == GRACE_SUPPRESS_SLOT and spec.get("suppress"):
            merged[slot] = spec
    return merged


def _merge_fly_lineup_specs(
    cfg: dict[str, Any],
    baseline_rows: list[dict[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    from gatefront_fly_catalog import build_fly_apply_specs

    fly_specs, _ = build_fly_apply_specs(
        int(cfg.get("fly_batch", 1)),
        vanilla_npc=bool(cfg.get("vanilla_npc", True)),
        write_target="mark_slot",
        # T-078：试验台验冻住默认忽略 T-080，否则死之鸟写不上蝙蝠巡逻槽
        ignore_slot_compat=bool(cfg.get("ignore_slot_compat", True)),
    )
    donor_slots = {s for s, sp in fly_specs.items() if _lineup_donor_key(sp)}
    merged = build_gatefront_vanilla_soldier_specs(
        baseline_rows or [],
        exclude=donor_slots,
        vanilla_npc=bool(cfg.get("vanilla_npc", True)),
    )
    for slot, spec in fly_specs.items():
        if _lineup_donor_key(spec):
            merged[slot] = spec
        elif slot == GRACE_SUPPRESS_SLOT and spec.get("suppress"):
            merged[slot] = spec
    return merged


def _pick_night_lab_donors(n: int) -> list[dict[str, Any]]:
    """从现网 spawn 抽 n 个互异 c0000 红灵捐皮（优先含猎死人 D）。"""
    from enemy_randomizer_core import load_enemy_index

    prefer_npc = 533190020
    spawn = SCRIPT_DIR / "output" / "runtime" / "cnv_enemy_spawn_map.txt"
    if not spawn.is_file():
        spawn = Path(r"V:\games\Elden Ring\Game\mod\dll\cnv_enemy_spawn_map.txt")
    think_unwrap: dict[int, int] = {}
    copies_path = SCRIPT_DIR / "output" / "runtime" / "cnv_npc_soul_copies.json"
    if copies_path.is_file():
        try:
            payload = json.loads(copies_path.read_text(encoding="utf-8"))
            for t in payload.get("think_copies") or []:
                think_unwrap[int(t["copy_id"])] = int(t["base_think"])
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            think_unwrap = {}

    chara_by_npc: dict[int, int] = {}
    think_by_npc: dict[int, int] = {}
    template_by_npc: dict[int, str] = {}
    for tpl in load_enemy_index().get("templates") or []:
        try:
            npc = int(tpl.get("npc") or 0)
        except (TypeError, ValueError):
            continue
        if npc <= 0:
            continue
        model = str(tpl.get("model") or "").lower()
        if model != "c0000":
            continue
        tid = str(tpl.get("template_id") or tpl.get("id") or "")
        if tid and npc not in template_by_npc:
            template_by_npc[npc] = tid
        try:
            ch = int(tpl.get("chara") or tpl.get("chara_init") or -1)
        except (TypeError, ValueError):
            ch = -1
        if ch > 0 and npc not in chara_by_npc:
            chara_by_npc[npc] = ch
        try:
            th = int(tpl.get("think") or 0)
        except (TypeError, ValueError):
            th = 0
        if th > 0 and npc not in think_by_npc:
            think_by_npc[npc] = th

    ordered: list[dict[str, Any]] = []
    seen: set[int] = set()

    def _push(npc: int, template: str, chara: int, think: int, label: str) -> None:
        if npc in seen or npc <= 0:
            return
        if not template:
            template = template_by_npc.get(npc) or ""
        if not template:
            return
        if think <= 0:
            think = think_by_npc.get(npc) or _think_from_npc(npc)
        if think >= 890_000_000:
            think = think_unwrap.get(think) or think_by_npc.get(npc) or _think_from_npc(npc)
        if chara <= 0:
            chara = chara_by_npc.get(npc) or -1
        seen.add(npc)
        ordered.append(
            {
                "npc": npc,
                "template": template,
                "model": "c0000",
                "think": int(think),
                "chara": int(chara),
                "label": label or f"night:{npc}",
            }
        )

    if spawn.is_file():
        for ln in spawn.read_text(encoding="utf-8").splitlines():
            if not ln.startswith("m") or "\tnight\t" not in ln:
                continue
            p = ln.split("\t")
            if len(p) < 13 or p[5] != "c0000":
                continue
            try:
                donor = int(p[12])
                chara = int(p[8]) if p[8].lstrip("-").isdigit() else -1
            except ValueError:
                continue
            # npc_donor 偶发写成 1 等垃圾；跳过，改走 index 模板
            if donor < 10_000:
                continue
            # 禁止用 spawn 里的 think 列：试验台反复 apply 后常是 890M，
            # unwrap 会塌成第一条 night 复制底本（曾全员挂 20108500/battleGoal=201000 → 只看不打）。
            # 红灵 lab 一律走 index / npc 推算的捐皮 Think（人形 battleGoal=29999）。
            _push(donor, p[4], chara, 0, p[4])
            if len(ordered) >= n * 3:
                break

    # 猎死人 D 优先放第 1 槽（方便赐福点对照）
    if prefer_npc in template_by_npc:
        if prefer_npc not in seen:
            _push(
                prefer_npc,
                template_by_npc[prefer_npc],
                chara_by_npc.get(prefer_npc, 23194),
                think_by_npc.get(prefer_npc, 533190000),
                "D-Hunter",
            )
        ordered = [d for d in ordered if d["npc"] == prefer_npc] + [
            d for d in ordered if d["npc"] != prefer_npc
        ]

    # 再钉一次 Think：防止早先污染路径残留；且必须是人形战斗脑 29999
    from enemy_think_difficulty import GAME_DIR, _load_think_rows

    think_rows = _load_think_rows(str(GAME_DIR / "csv"))

    def _is_human_red_think(th: int) -> bool:
        if th <= 1 or th >= 890_000_000:
            return False
        row = think_rows.get(int(th)) or {}
        return str(row.get("battleGoalID") or "") == "29999"

    def _resolve_human_think(npc: int) -> int:
        floored = (int(npc) // 1000) * 1000
        candidates = [
            think_by_npc.get(npc) or 0,
            _think_from_npc(npc),
            *[floored + k for k in range(0, 1000, 100)],
        ]
        for raw in candidates:
            try:
                th = int(raw or 0)
            except (TypeError, ValueError):
                continue
            if th >= 890_000_000:
                th = int(think_unwrap.get(th) or 0)
            if _is_human_red_think(th):
                return th
        return 0

    if len(ordered) < n * 3:
        for npc, tid in template_by_npc.items():
            _push(npc, tid, chara_by_npc.get(npc, -1), 0, tid)
            if len(ordered) >= n * 3:
                break

    fixed: list[dict[str, Any]] = []
    for d in ordered:
        th = _resolve_human_think(int(d["npc"]))
        if not th:
            continue
        out = dict(d)
        out["think"] = int(th)
        fixed.append(out)

    if len(fixed) < n:
        raise RuntimeError(
            f"night lab human-think donors insufficient: have {len(fixed)}, need {n}"
        )
    return fixed[:n]


def build_night_apply_specs() -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """门前试验 17 物理槽 → 全挂 c0000 红灵（tgt_cat=night，走 Think 钳制复制行）。

    飞行 17 note 会撞同一物理槽；本函数先取 note 序去重，不足 17 再用马车旁士兵槽补满，
    保证 17 个互异写盘槽各挂一只红灵。
    """
    from gatefront_dog_catalog import WAGON_TEST_SLOTS
    from gatefront_fly_catalog import FLY_BATCH_SIZE, load_gatefront_fly_write_lineup

    lineup = load_gatefront_fly_write_lineup()
    unique_marks: list[dict[str, Any]] = []
    seen: set[str] = set()
    for mark in lineup:
        slot = str(mark["slot"])
        if not slot or slot in seen or slot == GRACE_SUPPRESS_SLOT:
            continue
        seen.add(slot)
        unique_marks.append(mark)
    # 补满 17：马车旁士兵槽（同图、试验台常用）
    note_i = 100
    for slot in WAGON_TEST_SLOTS:
        if len(unique_marks) >= FLY_BATCH_SIZE:
            break
        if slot in seen or slot == GRACE_SUPPRESS_SLOT:
            continue
        seen.add(slot)
        note_i += 1
        unique_marks.append({"note": note_i, "slot": slot, "world_est": []})
    if len(unique_marks) < FLY_BATCH_SIZE:
        raise RuntimeError(
            f"night lab unique slots insufficient: have {len(unique_marks)}, need {FLY_BATCH_SIZE}"
        )
    unique_marks = unique_marks[:FLY_BATCH_SIZE]
    donors = _pick_night_lab_donors(FLY_BATCH_SIZE)
    specs: dict[str, dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []
    for i, mark in enumerate(unique_marks):
        slot = str(mark["slot"])
        d = donors[i]
        row = {
            "idx": i + 1,
            "note": int(mark.get("note") or 0),
            "mark_slot": slot,
            "test_slot": slot,
            "npc": d["npc"],
            "model": d["model"],
            "english": d["label"],
            "template": d["template"],
        }
        rows.append(row)
        specs[slot] = {
            "label": d["label"],
            "template": d["template"],
            "npc": d["npc"],
            "think": d["think"],
            "chara": d["chara"],
            "model": "c0000",
            "tgt_cat": "night",
            "vanilla_npc": False,
            "force_ground": True,
        }
    return specs, rows


def _merge_night_lineup_specs(
    cfg: dict[str, Any],
    baseline_rows: list[dict[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    night_specs, _ = build_night_apply_specs()
    donor_slots = {s for s, sp in night_specs.items() if _lineup_donor_key(sp)}
    merged = build_gatefront_vanilla_soldier_specs(
        baseline_rows or [],
        exclude=donor_slots | {GRACE_SUPPRESS_SLOT},
        vanilla_npc=True,
    )
    merged[GRACE_SUPPRESS_SLOT] = {"suppress": True, "label": "grace"}
    for slot, spec in night_specs.items():
        merged[slot] = spec
    return merged


def _merge_crow_lineup_specs(
    cfg: dict[str, Any],
    baseline_rows: list[dict[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    from gatefront_fly_catalog import build_crow_apply_specs

    crow_specs, _ = build_crow_apply_specs(
        vanilla_npc=bool(cfg.get("vanilla_npc", True)),
    )
    donor_slots = {s for s, sp in crow_specs.items() if _lineup_donor_key(sp)}
    merged = build_gatefront_vanilla_soldier_specs(
        baseline_rows or [],
        exclude=donor_slots,
        vanilla_npc=bool(cfg.get("vanilla_npc", True)),
    )
    for slot, spec in crow_specs.items():
        if _lineup_donor_key(spec):
            merged[slot] = spec
        elif slot == GRACE_SUPPRESS_SLOT and spec.get("suppress"):
            merged[slot] = spec
    return merged


def _slot_specs_from_config(
    cfg: dict[str, Any],
    *,
    baseline_rows: list[dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    mode = str(cfg.get("mode") or "").strip().lower()
    if mode == "fix_blockers":
        rows = baseline_rows or []
        return build_gatefront_blocker_fix_specs(
            rows,
            vanilla_npc=bool(cfg.get("vanilla_npc", True)),
        )
    if mode in ("quad_lineup", "quad_lineup_human"):
        return _merge_quad_lineup_specs(cfg, baseline_rows)
    if mode == "fly_lineup":
        return _merge_fly_lineup_specs(cfg, baseline_rows)
    if mode == "fly_crow":
        return _merge_crow_lineup_specs(cfg, baseline_rows)
    if mode == "night_lineup":
        return _merge_night_lineup_specs(cfg, baseline_rows)
    if mode == "quad_lineup_c4070":
        from gatefront_quad_catalog import build_quad_apply_specs

        specs, _ = build_quad_apply_specs(
            int(cfg.get("quad_batch", 1)),
            vanilla_npc=bool(cfg.get("vanilla_npc", True)),
            write_target="c4070",
        )
        return specs
    if mode == "quad_dogs":
        batch = int(cfg.get("quad_batch", 1))
        specs, _, _, _ = build_quadruped_dog_lineup_specs(
            batch=batch,
            vanilla_npc=bool(cfg.get("vanilla_npc", True)),
        )
        return specs
    if mode == "all_dogs" or bool(cfg.get("all_dogs")):
        return build_all_dog_lineup_specs(
            vanilla_npc=bool(cfg.get("vanilla_npc", True)),
        )
    dog_key = str(cfg.get("dog_key") or "").strip()
    if dog_key:
        lab_slot = str(cfg.get("lab_slot") or GATEFRONT_MARKED_TEST_SLOTS[0])
        entry = get_dog_entry(dog_key)
        out[lab_slot] = {
            "label": entry["english"],
            "template": entry["template"],
            "npc": entry["npc"],
            "think": entry["think"],
            "model": entry["model"],
            "vanilla_npc": bool(cfg.get("vanilla_npc", True)),
        }
        if bool(cfg.get("suppress_marked_rest", cfg.get("suppress_wagon_rest", True))):
            for slot in GATEFRONT_MARKED_TEST_SLOTS:
                if slot != lab_slot:
                    out[slot] = {"suppress": True}
    raw = cfg.get("slots") or {}
    if not isinstance(raw, dict):
        raise ValueError("config.slots must be an object")
    for slot, spec in raw.items():
        if not isinstance(spec, dict):
            raise ValueError(f"slot {slot}: spec must be object")
        out[str(slot)] = spec
    return out


def _apply_slot_spec(row: dict[str, Any], spec: dict[str, Any]) -> None:
    if spec.get("suppress"):
        row["tgt_cat"] = "decorative"
        row["template_id"] = "cnv:suppress_decorative"
        row["npc"] = 0
        row["think"] = 0
        row["chara"] = -1
        row["rune_amount"] = 0
        row["npc_donor"] = 0
        return

    template = str(spec.get("template") or "").strip()
    npc = spec.get("npc")
    if not template:
        raise ValueError(f"slot {row['entity_name']}: template required")
    if npc is None:
        raise ValueError(f"slot {row['entity_name']}: npc required")

    npc_i = int(npc)
    think_i = int(spec["think"]) if spec.get("think") is not None else _think_from_npc(npc_i)
    model = str(spec.get("model") or _model_from_template(template))

    row["template_id"] = template
    row["model"] = model
    row["npc"] = npc_i
    row["think"] = think_i
    if spec.get("chara") is not None:
        row["chara"] = int(spec["chara"])
    else:
        row["chara"] = DONOR_CHARA
    row["npc_donor"] = npc_i
    if spec.get("tgt_cat"):
        row["tgt_cat"] = str(spec["tgt_cat"])
    if spec.get("force_ground"):
        row["placement_kind"] = "ground"
        row["walk_route"] = ""
        row["backup_anim"] = -1
    for key in ("pos_x", "pos_y", "pos_z"):
        if key in spec:
            row[key] = float(spec[key])
    if any(k in spec for k in ("pos_x", "pos_y", "pos_z")):
        row["placement_kind"] = "ground"
        row["walk_route"] = ""
        row["backup_anim"] = -1


def _force_vanilla_npc_on_slots(path: Path, slot_names: set[str]) -> None:
    """探针：狗槽用原版 npc，叠层显示 5525xxxx 而非 8800000xx。"""
    lines: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#") and "\t" in line:
            parts = line.split("\t")
            if len(parts) >= 13 and parts[1] in slot_names:
                npc = int(parts[12]) if parts[12].isdigit() else int(parts[6])
                parts[6] = str(npc)
                parts[7] = str((npc // 100) * 100)
                parts[12] = str(npc)
                line = "\t".join(parts)
        lines.append(line)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def cmd_init(seed: int) -> int:
    """生成关卡前方原版士兵基线（不走随机种子）。"""
    BASELINE_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[init] vanilla soldier baseline map={MAP_ID} (no randomize)")
    assignments = _build_index_assignments(MAP_ID)
    injected = _inject_missing_marked_slots(assignments, GATEFRONT_MARKED_TEST_SLOTS)
    if injected:
        print(f"[init] injected index slots: {', '.join(injected)}")

    specs = build_gatefront_vanilla_soldier_specs(
        assignments,
        exclude=set(),
        vanilla_npc=True,
    )
    by_name = {str(r["entity_name"]): r for r in assignments}
    for slot, spec in specs.items():
        row = by_name.get(slot)
        if row:
            _apply_slot_spec(row, spec)

    staging = BASELINE_DIR / ".apply_staging" / f"cnv_enemy_spawn_map_{seed}.txt"
    staging.parent.mkdir(parents=True, exist_ok=True)
    main_cfg = _load_json(SCRIPT_DIR / "config.json")
    mob_drop_mode = str(main_cfg.get("enemy", {}).get("mob_drop_mode", "donor_default"))
    write_spawn_map(
        staging,
        seed,
        assignments,
        mob_drop_mode,
        difficulty=main_cfg.get("enemy", {}).get("difficulty"),
    )
    flat = BASELINE_DIR / "cnv_enemy_spawn_map.txt"
    flat.write_bytes(staging.read_bytes())
    sidecars = spawn_map_sidecar_paths(staging, seed)
    for key in ("copies", "npc_csv", "skipped"):
        src = sidecars[key]
        if src.is_file():
            (BASELINE_DIR / src.name).write_bytes(src.read_bytes())

    rows = _parse_spawn_rows(staging)
    meta = {
        "map_id": MAP_ID,
        "seed": seed,
        "vanilla_baseline": True,
        "slots": len(rows),
        "marked_slots": list(GATEFRONT_MARKED_TEST_SLOTS),
        "wagon_slots": [s for s in WAGON_TEST_SLOTS if any(r["entity_name"] == s for r in rows)],
    }
    (BASELINE_DIR / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"[init] ok rows={len(rows)} soldier baseline · marked={len(meta['marked_slots'])}")
    print(f"  baseline -> {staging}")
    return 0


def cmd_list(seed: int, cfg_path: Path) -> int:
    baseline = _baseline_spawn_path(seed)
    if not baseline.is_file():
        print("baseline missing — run: python gatefront_test_lab.py init")
        return 1
    rows = {r["entity_name"]: r for r in _parse_spawn_rows(baseline)}
    cfg = _load_config(cfg_path) if cfg_path.is_file() else {"slots": {}}
    specs = _slot_specs_from_config(cfg)
    print(f"map={MAP_ID} seed={seed}  F6 标定测试槽（{len(GATEFRONT_MARKED_TEST_SLOTS)} 个唯一槽）：")
    for slot in GATEFRONT_MARKED_TEST_SLOTS:
        base = rows.get(slot)
        if not base:
            print(f"  {slot}  (not in baseline)")
            continue
        spec = specs.get(slot, {})
        label = spec.get("label") or ""
        if spec.get("suppress"):
            cur = "suppress"
        elif spec.get("npc"):
            cur = f"npc={spec.get('npc')} model={spec.get('model') or _model_from_template(str(spec.get('template')))}"
        else:
            cur = f"baseline npc={base['npc']} model={base['model']}"
        tag = f" [{label}]" if label else ""
        print(f"  {slot}{tag}  ->  {cur}")
    return 0


def cmd_dog_list() -> int:
    build_dog_catalog(refresh=True)
    print(format_dog_list())
    return 0


def cmd_explain(npc_arg: str, seed: int) -> int:
    try:
        npc = int(npc_arg)
    except ValueError:
        print(f"ERROR: need npc id, got {npc_arg!r}")
        return 1
    copies = OUT_DIR / f"cnv_npc_soul_copies_{seed}.json"
    if not copies.is_file():
        copies = SCRIPT_DIR / "output" / "runtime" / f"cnv_npc_soul_copies_{seed}.json"
    print(resolve_runtime_npc_label(npc, copies if copies.is_file() else None))
    return 0


def _write_legend(
    out_dir: Path,
    patched: dict[str, dict[str, Any]],
    *,
    quad_batch: int | None = None,
    quad_total_batches: int | None = None,
    fly_batch: int | None = None,
    fly_total_batches: int | None = None,
    crow_uniform: bool = False,
    legend_suffix: str = "",
) -> None:
    lines = [
        f"# 关卡前方试验台（seed 见 spawn map 头）",
    ]
    if fly_batch is not None:
        lines.append(
            f"# {'大乌鸦混搭 ×14' if crow_uniform else f'飞行认外观 · 组 {fly_batch}/{fly_total_batches}'} · 每组 17 捐皮一次写盘"
        )
        lines.append("# 写盘目标：F6 note2～15 + 3 蝙蝠巡逻（c4200_9000/9001/9002）")
        lines.append("# 其余槽：固定原版士兵（试验台不走随机种子）")
        lines.append("# note1 赐福不写")
    elif quad_batch is not None:
        lines.append(
            f"# 四足认外观 · 组 {quad_batch}/{quad_total_batches} · 每组 14 捐皮一次写盘"
        )
        lines.append("# 写盘目标：F6 标定 mark_slot（note2～15 各 1 张四足皮）")
        lines.append("# 其余槽：固定原版士兵（试验台不走随机种子）")
        lines.append("# F6 note 2～15 见 gatefront_marked_slots.json；note1 赐福不写")
    else:
        lines.append(f"# 只改了下列槽；其余保持 init 基线")
    lines.append("# 冻住/外观：F7 锁敌，记下 slot + npc + 会不会动")
    lines.append("")
    if fly_batch is not None:
        slot_order = list(GATEFRONT_MARKED_TEST_SLOTS)
    elif quad_batch:
        slot_order = list(GATEFRONT_MARKED_TEST_SLOTS) + list(quadruped_lineup_slots())
    else:
        slot_order = list(dog_lineup_slots())
    seen: set[str] = set()
    for slot in slot_order:
        if slot in seen:
            continue
        seen.add(slot)
        if slot not in patched:
            continue
        spec = patched[slot]
        if spec.get("suppress"):
            lines.append(f"## {slot}  suppress")
            lines.append("")
            continue
        label = spec.get("label") or slot
        template = spec.get("template", "")
        npc = spec.get("npc", "")
        model = spec.get("model") or _model_from_template(str(template))
        dog_key = spec.get("dog_key") or ""
        quad_key = spec.get("quad_key") or ""
        fly_key = spec.get("fly_key") or ""
        note = spec.get("note")
        bucket = spec.get("visual_bucket_soldier") or ""
        lines.append(f"## {label}")
        lines.append(f"  slot={slot}")
        if note is not None:
            lines.append(f"  note={note}")
        lines.append(f"  model={model}  npc={npc}  template={template}")
        pos_x = spec.get("pos_x")
        if pos_x is not None:
            lines.append(
                f"  msb_pos=({pos_x:.1f}, {float(spec.get('pos_y', 0)):.1f}, {float(spec.get('pos_z', 0)):.1f})"
            )
        if bucket:
            lines.append(f"  士兵槽对照皮={bucket}（四足槽请肉眼重新认）")
        if dog_key:
            lines.append(f"  dog_key={dog_key}")
        if quad_key:
            lines.append(f"  quad_key={quad_key}")
        if fly_key:
            lines.append(f"  fly_key={fly_key}")
        cycle = spec.get("donor_cycle")
        if cycle:
            lines.append(f"  donor_cycle={cycle}")
        physique = spec.get("physique_bucket") or ""
        pose = spec.get("donor_pose_label") or ""
        if physique or pose:
            lines.append(f"  donor_physique={physique}  donor_pose={pose}")
        slot_pose = spec.get("slot_pose_label") or ""
        backup = spec.get("slot_backup_anim")
        apply_cls = spec.get("slot_apply_class") or ""
        if slot_pose or backup is not None or apply_cls:
            lines.append(
                f"  slot_apply={apply_cls}  slot_pose={slot_pose}  slot_backup={backup}"
            )
        if spec.get("write_target") == "human_mark" and spec.get("quad_write_slot"):
            lines.append(f"  (四足对照槽 {spec.get('quad_write_slot')})")
        lines.append("")
    if crow_uniform:
        legend_name = "gatefront_crow_legend.txt"
    elif fly_batch is not None:
        legend_name = f"gatefront_fly_legend_b{fly_batch}.txt"
    elif quad_batch is not None:
        tag = f"_human" if legend_suffix == "human" else ""
        legend_name = f"gatefront_quad_legend_b{quad_batch}{tag}.txt"
    else:
        legend_name = "gatefront_lab_legend.txt"
    (out_dir / legend_name).write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def cmd_apply(
    seed: int,
    cfg_path: Path,
    *,
    skip_apply: bool,
    cli_overrides: dict[str, dict[str, Any]] | None = None,
) -> int:
    baseline = _baseline_spawn_path(seed)
    if not baseline.is_file():
        print("baseline missing — run: python gatefront_test_lab.py init")
        return 1

    cfg = _load_config(cfg_path)
    cfg_seed = int(cfg.get("seed", seed))
    if cfg_seed != seed:
        seed = cfg_seed
    mode = str(cfg.get("mode") or "").strip().lower()
    quad_batch: int | None = None
    quad_total_batches: int | None = None
    fly_batch: int | None = None
    fly_total_batches: int | None = None
    crow_uniform: bool = False
    legend_suffix = ""
    if mode in ("quad_lineup", "quad_lineup_human"):
        from gatefront_quad_catalog import build_quad_lineup_batches

        quad_batch = int(cfg.get("quad_batch", 1))
        quad_total_batches = int(
            build_quad_lineup_batches().get("total_batches") or quad_batch_count()
        )
        legend_suffix = ""
    elif mode == "fly_lineup":
        from gatefront_fly_catalog import build_fly_lineup_batches, fly_batch_count

        fly_batch = int(cfg.get("fly_batch", 1))
        fly_total_batches = int(
            build_fly_lineup_batches().get("total_batches") or fly_batch_count()
        )
    elif mode == "fly_crow":
        crow_uniform = True
        fly_batch = 1
        fly_total_batches = 1
    elif mode == "night_lineup":
        fly_batch = 1
        fly_total_batches = 1
        legend_suffix = "night_clamp"
    elif mode == "quad_dogs":
        quad_batch = int(cfg.get("quad_batch", 1))
        quad_total_batches = quad_batch_count()

    assignments = _parse_spawn_rows(baseline)
    inject_slots = list(GATEFRONT_MARKED_TEST_SLOTS)
    if mode == "quad_lineup_c4070":
        inject_slots = list(dict.fromkeys(inject_slots + list(QUADRUPED_LINEUP_SLOTS)))
    elif mode == "night_lineup":
        night_specs, _ = build_night_apply_specs()
        inject_slots = list(dict.fromkeys(inject_slots + list(night_specs.keys())))
    injected = _inject_missing_marked_slots(assignments, inject_slots)
    if injected:
        print(f"[apply] injected skipped marked slots: {', '.join(injected)}")
    specs = _slot_specs_from_config(cfg, baseline_rows=assignments)
    if cli_overrides:
        specs.update(cli_overrides)

    by_name = {str(r["entity_name"]): r for r in assignments}
    patched: dict[str, dict[str, Any]] = {}
    missing: list[str] = []

    for slot, spec in specs.items():
        row = by_name.get(slot)
        if not row:
            missing.append(slot)
            continue
        _apply_slot_spec(row, spec)
        patched[slot] = spec

    if missing:
        if patched:
            print(f"WARN: slots not in baseline (skipped): {', '.join(missing)}")
        else:
            print(f"ERROR: slots not in baseline: {', '.join(missing)}")
            return 1
    if not patched:
        print("ERROR: no slots in config")
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    staging = OUT_DIR / ".apply_staging" / f"cnv_enemy_spawn_map_{seed}.txt"
    staging.parent.mkdir(parents=True, exist_ok=True)
    staging.write_bytes(baseline.read_bytes())

    main_cfg = _load_json(SCRIPT_DIR / "config.json")
    mob_drop_mode = str(main_cfg.get("enemy", {}).get("mob_drop_mode", "donor_default"))
    write_spawn_map(
        staging,
        seed,
        assignments,
        mob_drop_mode,
        difficulty=main_cfg.get("enemy", {}).get("difficulty"),
    )
    vanilla_slots = {
        slot
        for slot, spec in patched.items()
        if not spec.get("suppress") and spec.get("vanilla_npc", True)
    }
    if vanilla_slots:
        _force_vanilla_npc_on_slots(staging, vanilla_slots)

    flat = OUT_DIR / "cnv_enemy_spawn_map.txt"
    flat.write_bytes(staging.read_bytes())
    sidecars = spawn_map_sidecar_paths(staging, seed)
    for key in ("copies", "npc_csv", "skipped"):
        src = sidecars[key]
        if src.is_file():
            (OUT_DIR / src.name).write_bytes(src.read_bytes())

    runtime_dir = SCRIPT_DIR / "output" / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    (runtime_dir / flat.name).write_bytes(flat.read_bytes())
    for key in ("copies", "npc_csv", "skipped"):
        src = sidecars[key]
        if src.is_file():
            (runtime_dir / src.name).write_bytes(src.read_bytes())

    _write_legend(
        OUT_DIR,
        patched,
        quad_batch=quad_batch,
        quad_total_batches=quad_total_batches,
        fly_batch=fly_batch,
        fly_total_batches=fly_total_batches,
        legend_suffix=legend_suffix,
        crow_uniform=crow_uniform,
    )
    if crow_uniform:
        kind = "fly crow ×14 mark_slot"
    elif fly_batch is not None:
        kind = f"fly batch {fly_batch}/{fly_total_batches} mark_slot"
    elif quad_batch is not None:
        kind = f"quad batch {quad_batch}/{quad_total_batches} mark_slot"
    else:
        kind = "baseline"
    print(f"[apply] patched {len(patched)} slots ({kind})")
    if mode in ("quad_lineup", "quad_lineup_human", "fly_lineup", "fly_crow", "night_lineup"):
        slot_iter = list(GATEFRONT_MARKED_TEST_SLOTS)
    elif quad_batch:
        slot_iter = quadruped_lineup_slots()
    else:
        slot_iter = dog_lineup_slots()
    for slot in slot_iter:
        if slot in patched:
            spec = patched[slot]
            if spec.get("suppress"):
                print(f"  {slot} -> suppress")
            else:
                print(
                    f"  {slot} -> npc={spec.get('npc')} "
                    f"model={spec.get('model') or _model_from_template(str(spec.get('template')))}"
                )
    print(f"  bundle -> {OUT_DIR}")
    if crow_uniform:
        legend_file = "gatefront_crow_legend.txt"
    elif fly_batch is not None:
        legend_file = f"gatefront_fly_legend_b{fly_batch}.txt"
    elif quad_batch is not None:
        legend_file = f"gatefront_quad_legend_b{quad_batch}.txt"
    else:
        legend_file = "gatefront_lab_legend.txt"
    print(f"  legend -> {OUT_DIR / legend_file}")

    if skip_apply:
        print("[apply] skip apply (--skip-apply)")
        return 0

    from npc_soul_copies import patch_regulation_npc_copies

    if sidecars["copies"].is_file():
        reg_msg = patch_regulation_npc_copies(sidecars["copies"])
        print(f"regulation: {reg_msg}")

    result = run_enemy_apply(staging, map_filter=MAP_ID)
    print(
        f"apply maps_written={result.maps_written} "
        f"slots_patched={result.slots_patched} "
        f"write_failed={result.maps_write_failed}"
    )
    if result.maps_write_failed:
        for sample in result.apply_fail_samples[:5]:
            print(f"  {sample}")
        return 1

    from enemy_randomizer_core import deploy_enemy_spawn_map

    deployed = deploy_enemy_spawn_map(flat)
    print(f"deploy spawn map -> {deployed}")
    print("真机：完全退出游戏 → 重进 → 关卡前方赐福 → F7 锁敌看编号")
    return 0


def cmd_quad_table(*, refresh: bool = False) -> int:
    from gatefront_quad_catalog import (
        QUAD_BATCHES_CACHE,
        QUAD_CATALOG_CACHE,
        QUAD_TABLE_PATH,
        format_quad_batch_summary,
        write_quad_lineup_table,
    )

    path = write_quad_lineup_table(refresh=refresh)
    print(format_quad_batch_summary())
    print(f"  catalog -> {QUAD_CATALOG_CACHE}")
    print(f"  batches -> {QUAD_BATCHES_CACHE}")
    print(f"  table   -> {path}")
    return 0


def cmd_quad_list() -> int:
    from gatefront_quad_catalog import format_quad_batch_summary

    print(format_quad_batch_summary())
    return 0


def cmd_fly_table(*, refresh: bool = False) -> int:
    from gatefront_fly_catalog import (
        FLY_BATCHES_CACHE,
        FLY_CATALOG_CACHE,
        FLY_TABLE_PATH,
        format_fly_batch_summary,
        write_fly_lineup_table,
    )

    path = write_fly_lineup_table(refresh=refresh)
    print(format_fly_batch_summary())
    print(f"  catalog -> {FLY_CATALOG_CACHE}")
    print(f"  batches -> {FLY_BATCHES_CACHE}")
    print(f"  table   -> {path}")
    return 0


def cmd_fly_list() -> int:
    from gatefront_fly_catalog import format_fly_batch_summary

    print(format_fly_batch_summary())
    return 0


def run_apply_night(
    *,
    seed: int = DEFAULT_SEED,
    config: Path = DEFAULT_CONFIG,
    skip_apply: bool = False,
) -> int:
    """门前 17 写盘槽全挂 c0000 红灵，验 night_think_clamp（含张角/一起冲/呼叫）。"""
    from gatefront_fly_catalog import FLY_BATCH_SIZE

    specs, batch_rows = build_night_apply_specs()
    cfg = _load_config(config)
    cfg["mode"] = "night_lineup"
    cfg["vanilla_npc"] = False
    cfg["seed"] = int(cfg.get("seed", seed))
    config.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"[night] {len(batch_rows)} 只红灵 → {len(specs)} 个互异门前槽（满额 {FLY_BATCH_SIZE}）· "
        f"tgt_cat=night · Think 士兵级钳制（含张角/一起冲/呼叫）"
    )
    for row in batch_rows:
        slot = str(row["mark_slot"])
        sp = specs[slot]
        print(
            f"  idx {row['idx']:>2} note {row['note']:>2} {slot} -> npc={row['npc']} "
            f"{row.get('english') or row['model']} chara={sp.get('chara')}"
        )
    return cmd_apply(int(cfg["seed"]), config, skip_apply=skip_apply)


def run_apply_fly(
    batch: int,
    *,
    seed: int = DEFAULT_SEED,
    config: Path = DEFAULT_CONFIG,
    skip_apply: bool = False,
    force_compat_break: bool = True,
) -> int:
    """飞行认外观写盘：17 槽（note2～15 + 3 蝙蝠巡逻）各 1 张白名单飞行皮。

    默认 force_compat_break=True：试验台要能把死之鸟等写上蝙蝠巡逻槽验冻住。
    """
    from gatefront_fly_catalog import (
        FLY_BATCH_SIZE,
        build_fly_apply_specs,
        build_fly_lineup_batches,
        fly_batch_count,
    )

    total = int(build_fly_lineup_batches().get("total_batches") or fly_batch_count())
    if batch < 1 or batch > total:
        print(f"ERROR: fly batch {batch} out of range 1..{total}")
        return 1

    specs, batch_rows = build_fly_apply_specs(
        batch,
        vanilla_npc=True,
        write_target="mark_slot",
        ignore_slot_compat=force_compat_break,
    )
    cfg = _load_config(config)
    cfg["mode"] = "fly_lineup"
    cfg["fly_batch"] = int(batch)
    cfg["vanilla_npc"] = True
    cfg["ignore_slot_compat"] = bool(force_compat_break)
    cfg["seed"] = int(cfg.get("seed", seed))
    config.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    active = [
        r
        for r in batch_rows
        if not specs.get(str(r["mark_slot"]), {}).get("suppress")
    ]
    print(
        f"[fly] 组 {batch}/{total} · {len(batch_rows)} 条飞行皮 → 17 写盘槽 · "
        f"本组写 {len(active)} 行（满额 {FLY_BATCH_SIZE} = note2～15 + 3 蝙蝠巡逻）"
    )
    for row in batch_rows:
        slot = str(row["mark_slot"])
        if specs.get(slot, {}).get("suppress"):
            continue
        sp = specs[slot]
        cycle = int(row.get("donor_cycle") or 0)
        cycle_tag = f" ×{cycle + 1}" if cycle else ""
        print(
            f"  idx {row['idx']:>2} note {row['note']:>2} {slot} -> npc={row['npc']} "
            f"{row.get('english') or row['model']}{cycle_tag}  "
            f"slot_backup={sp.get('slot_backup_anim')} donor_pose={sp.get('donor_pose_label')}"
        )
    return cmd_apply(
        int(cfg["seed"]),
        config,
        skip_apply=skip_apply,
    )


def run_apply_crow(
    *,
    seed: int = DEFAULT_SEED,
    config: Path = DEFAULT_CONFIG,
    skip_apply: bool = False,
    force_compat_break: bool = False,
) -> int:
    """14 个 F6 mark 槽轮询多种大乌鸦（c4560、c4561）。"""
    from gatefront_fly_catalog import build_crow_apply_specs, ordered_giant_crow_entries

    specs, batch_rows = build_crow_apply_specs(
        vanilla_npc=True,
        ignore_slot_compat=force_compat_break,
    )
    crow_variants = ordered_giant_crow_entries(refresh=True)
    cfg = _load_config(config)
    cfg["mode"] = "fly_crow"
    cfg["vanilla_npc"] = True
    cfg["seed"] = int(cfg.get("seed", seed))
    config.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    active = [
        r
        for r in batch_rows
        if not specs.get(str(r["mark_slot"]), {}).get("suppress")
    ]
    unique_npc = sorted({int(r["npc"]) for r in active})
    print(
        f"[crow] 大乌鸦 {len(crow_variants)} 种轮询 · npc {unique_npc} · {len(batch_rows)} 行 → F6 标定槽 · "
        f"本组写 {len(active)} 行（满额 14 = note2～15）"
    )
    for row in batch_rows:
        slot = str(row["mark_slot"])
        if specs.get(slot, {}).get("suppress"):
            continue
        sp = specs[slot]
        print(
            f"  idx {row['idx']:>2} note {row['note']:>2} {slot} -> npc={row['npc']} "
            f"{row.get('english') or row['model']}  "
            f"slot_apply={sp.get('slot_apply_class')} donor_pose={sp.get('donor_pose_label')}"
        )
    return cmd_apply(
        int(cfg["seed"]),
        config,
        skip_apply=skip_apply,
    )


def run_apply_quad(
    batch: int,
    *,
    seed: int = DEFAULT_SEED,
    config: Path = DEFAULT_CONFIG,
    skip_apply: bool = False,
) -> int:
    """四足认外观写盘：F6 标定 14 槽各 1 张白名单四足皮。"""
    from gatefront_quad_catalog import build_quad_apply_specs, build_quad_lineup_batches

    total = int(build_quad_lineup_batches().get("total_batches") or quad_batch_count())
    if batch < 1 or batch > total:
        print(f"ERROR: quad batch {batch} out of range 1..{total}")
        return 1

    specs, batch_rows = build_quad_apply_specs(batch, vanilla_npc=True, write_target="mark_slot")
    cfg = _load_config(config)
    cfg["mode"] = "quad_lineup"
    cfg["quad_batch"] = int(batch)
    cfg.pop("quad_wave", None)
    cfg["vanilla_npc"] = True
    cfg["seed"] = int(cfg.get("seed", seed))
    config.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    active = [
        r
        for r in batch_rows
        if not specs.get(str(r["mark_slot"]), {}).get("suppress")
    ]
    print(
        f"[quad] 组 {batch}/{total} · {len(batch_rows)} 条四足皮 → F6 标定槽 · "
        f"本组写 {len(active)} 行（满额 14 = note2～15）"
    )
    for row in batch_rows:
        slot = str(row["mark_slot"])
        if specs.get(slot, {}).get("suppress"):
            continue
        sp = specs[slot]
        print(
            f"  idx {row['idx']:>2} note {row['note']:>2} {slot} -> npc={row['npc']} "
            f"{row.get('english') or row['model']}  "
            f"slot_backup={sp.get('slot_backup_anim')} donor_pose={sp.get('donor_pose_label')}"
        )
    return cmd_apply(
        int(cfg["seed"]),
        config,
        skip_apply=skip_apply,
    )


def run_apply_quad_human(
    batch: int,
    *,
    seed: int = DEFAULT_SEED,
    config: Path = DEFAULT_CONFIG,
    skip_apply: bool = False,
) -> int:
    """兼容旧 CLI；与 run_apply_quad 相同。"""
    return run_apply_quad(
        batch,
        seed=seed,
        config=config,
        skip_apply=skip_apply,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="关卡前方真机试验台")
    parser.add_argument(
        "command",
        nargs="?",
        choices=("init", "apply", "apply-all-dogs", "apply-quad", "apply-quad-human", "apply-quad-dogs", "apply-fly", "apply-crow", "apply-night", "fix-ruins-blockers", "list", "dog-list", "quad-table", "quad-list", "fly-table", "fly-list", "explain"),
        default="apply",
        help="apply-quad=四足 | apply-fly=飞行 | apply-crow=14槽大乌鸦 | apply-night=17槽红灵钳制验",
    )
    parser.add_argument("--batch", type=int, default=1, help="四足/飞行组号")
    parser.add_argument("explain_npc", nargs="?", help="explain 子命令用的 npc 编号")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--skip-apply", action="store_true")
    parser.add_argument(
        "--force-compat-break",
        action="store_true",
        help="试验台故意打破 T-080 槽皮匹配（验冻住用）",
    )
    parser.add_argument("--slot", action="append", default=[], help="CLI 覆盖单个槽")
    parser.add_argument("--npc", type=int, action="append", default=[])
    parser.add_argument("--template", action="append", default=[])
    parser.add_argument("--label", action="append", default=[])
    parser.add_argument("--dog-key", type=str, default="", help="catalog 里的狗 key，一次测一只")
    args = parser.parse_args()

    cli_overrides: dict[str, dict[str, Any]] | None = None
    if args.slot:
        if len(args.npc) != len(args.slot) or len(args.template) != len(args.slot):
            print("ERROR: --slot --npc --template 数量须一致")
            return 1
        cli_overrides = {}
        for i, slot in enumerate(args.slot):
            spec: dict[str, Any] = {
                "template": args.template[i],
                "npc": args.npc[i],
            }
            if i < len(args.label) and args.label[i]:
                spec["label"] = args.label[i]
            cli_overrides[slot] = spec

    if args.command == "init":
        return cmd_init(args.seed)
    if args.command == "dog-list":
        return cmd_dog_list()
    if args.command == "quad-table":
        return cmd_quad_table(refresh=True)
    if args.command == "quad-list":
        return cmd_quad_list()
    if args.command == "fly-table":
        return cmd_fly_table(refresh=True)
    if args.command == "fly-list":
        return cmd_fly_list()
    if args.command == "apply-all-dogs":
        cfg = _load_config(args.config)
        cfg["mode"] = "all_dogs"
        cfg["suppress_wagon_rest"] = False
        args.config.write_text(
            json.dumps(cfg, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return cmd_apply(args.seed, args.config, skip_apply=args.skip_apply)
    if args.command == "fix-ruins-blockers":
        cfg = _load_config(args.config)
        cfg["mode"] = "fix_blockers"
        cfg["vanilla_npc"] = True
        args.config.write_text(
            json.dumps(cfg, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        fix_specs = build_gatefront_blocker_fix_specs(
            _parse_spawn_rows(_baseline_spawn_path(args.seed)),
            vanilla_npc=True,
        )
        print(
            "[fix] electric orb + ruins blockers -> lockable soldiers "
            "(tgt_cat=trash, no pos override): "
            + ", ".join(
                f"{slot}(npc={fix_specs[slot]['npc']})" for slot in fix_specs
            )
        )
        return cmd_apply(args.seed, args.config, skip_apply=args.skip_apply)
    if args.command == "apply-quad":
        return run_apply_quad(
            int(args.batch),
            seed=args.seed,
            config=args.config,
            skip_apply=args.skip_apply,
        )
    if args.command == "apply-quad-human":
        return run_apply_quad_human(
            int(args.batch),
            seed=args.seed,
            config=args.config,
            skip_apply=args.skip_apply,
        )
    if args.command == "apply-fly":
        return run_apply_fly(
            int(args.batch),
            seed=args.seed,
            config=args.config,
            skip_apply=args.skip_apply,
            force_compat_break=bool(args.force_compat_break),
        )
    if args.command == "apply-night":
        return run_apply_night(
            seed=args.seed,
            config=args.config,
            skip_apply=args.skip_apply,
        )
    if args.command == "apply-crow":
        return run_apply_crow(
            seed=args.seed,
            config=args.config,
            skip_apply=args.skip_apply,
            force_compat_break=bool(args.force_compat_break),
        )
    if args.command == "apply-quad-dogs":
        cfg = _load_config(args.config)
        cfg["mode"] = "quad_dogs"
        cfg["quad_batch"] = int(args.batch)
        cfg["vanilla_npc"] = True
        args.config.write_text(
            json.dumps(cfg, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        total = quad_batch_count()
        print(f"[quad] batch {args.batch}/{total} · slots={len(QUADRUPED_LINEUP_SLOTS)} · soldier c4311 excluded")
        return cmd_apply(args.seed, args.config, skip_apply=args.skip_apply)
    if args.command == "explain":
        if not args.explain_npc:
            print("用法: python gatefront_test_lab.py explain 880000017")
            return 1
        return cmd_explain(args.explain_npc, args.seed)
    if args.command == "list":
        return cmd_list(args.seed, args.config)
    if args.dog_key:
        try:
            entry = get_dog_entry(args.dog_key)
        except KeyError as exc:
            print(exc)
            return 1
        lab_slot = str(_load_config(args.config).get("lab_slot") or GATEFRONT_MARKED_TEST_SLOTS[0])
        if cli_overrides is None:
            cli_overrides = {}
        cli_overrides[lab_slot] = {
            "label": entry["english"],
            "template": entry["template"],
            "npc": entry["npc"],
            "think": entry["think"],
            "model": entry["model"],
            "vanilla_npc": True,
        }
    return cmd_apply(
        args.seed,
        args.config,
        skip_apply=args.skip_apply,
        cli_overrides=cli_overrides,
    )


if __name__ == "__main__":
    raise SystemExit(main())
