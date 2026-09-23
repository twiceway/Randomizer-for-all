"""T-084 B3 — spawn map I/O, audit, spoiler (extracted from enemy_randomizer_core)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from enemy_category_rules import (
    is_dlc_trash_donor_model,
    is_risky_assignment,
    resolve_src_category,
    slot_physique_bucket,
    _model_has_prefix,
)
from enemy_donor_pick import _SlotPickPlan, normalize_row_weights
from enemy_rune_soul import load_npc_soul_map
from enemy_slot_rules import describe_slot_policy
from enemy_spawn_bundle import (
    parse_spawn_map_header,
    resolve_spawn_map_sidecar_paths,
    spawn_map_seed_from_path,
    spawn_map_sidecar_paths,
    validate_spawn_bundle,
    verify_spawn_deployed,
)
from paths import GAME_DIR, DEFAULT_ENEMY_SPAWN_MAP

NPC_DISPLAY_NAME_CACHE: dict[int, str] | None = None


MAP_DISPLAY_NAME_CACHE: dict[str, str] | None = None


def write_map_spawn_audit(
    *,
    map_id: str,
    seed: int,
    index: dict[str, Any],
    categories_cfg: dict[str, Any],
    pick_plans: list[_SlotPickPlan],
    assignments: list[dict[str, Any]],
    warnings: list[str],
    out_path: Path,
    npc_csv_dir: Path | None = None,
    prep: dict[str, Any] | None = None,
) -> Path:
    """单图 spawn 漏行审计（T-076 史东薇尔前哨真机用）。"""
    from enemy_slot_prep import prep_slots_for_map

    pick_keys = {(p.map_id, p.entity_name) for p in pick_plans}
    spawn_keys: set[tuple[str, str]] = set()
    suppress_keys: set[tuple[str, str]] = set()
    for row in assignments:
        key = (str(row.get("map_id", "")), str(row.get("entity_name", "")))
        spawn_keys.add(key)
        tid = str(row.get("template_id", ""))
        if tid.startswith("cnv:suppress"):
            suppress_keys.add(key)

    warn_by_key: dict[tuple[str, str], list[str]] = {}
    for w in warnings:
        for prefix in (
            "empty pool ",
            "physique_empty ",
            "blocked_mount_donor ",
            "no_mount_pair_pool ",
        ):
            if not w.startswith(prefix):
                continue
            body = w[len(prefix):]
            colon = body.find(":")
            if colon <= 0:
                continue
            key = (body[:colon], body[colon + 1:].split()[0])
            warn_by_key.setdefault(key, []).append(w.strip())

    prep_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    if prep:
        for row in prep_slots_for_map(prep, map_id):
            prep_by_key[(str(row.get("m", "")), str(row.get("n", "")))] = row

    base = npc_csv_dir or (GAME_DIR / "csv")
    lines: list[str] = [
        f"# map_spawn_audit map={map_id} seed={seed}",
        "# 列：实体名 | 模型 | 体态 | 放置 | 角色 | 策略 | pick | spawn | 状态 | 说明",
        "",
    ]
    missing_spawn: list[str] = []
    missing_pick: list[str] = []
    ok_count = 0
    skip_count = 0

    for slot in sorted(
        index.get("slots", []),
        key=lambda s: str(s.get("name", "")),
    ):
        if str(slot.get("map_id", "")) != map_id:
            continue
        entity = str(slot.get("name", ""))
        model = str(slot.get("model", ""))
        key = (map_id, entity)
        physique = slot_physique_bucket(slot, categories_cfg)
        pol = describe_slot_policy(
            slot,
            categories_cfg,
            npc_csv_dir=base,
            prep_row=prep_by_key.get(key),
            spawn_keys=spawn_keys,
        )
        placement = pol["placement"]
        slot_role = pol["slot_role"]
        policy = pol["policy"]
        in_pick = key in pick_keys
        in_spawn = key in spawn_keys
        in_suppress = key in suppress_keys

        if policy != "participate":
            status = "SKIP"
            note = pol.get("effective_skip") or ",".join(pol.get("rule_ids") or [])
            skip_count += 1
        elif in_suppress:
            status = "SUPPRESS"
            note = "装饰沉底"
        elif in_spawn and not in_suppress:
            status = "OK_SPAWN"
            note = ""
            ok_count += 1
        elif in_pick and not in_spawn:
            status = "MISSING_SPAWN"
            note = "; ".join(warn_by_key.get(key, [])) or "pick有行spawn无(查blocked_mount)"
            missing_spawn.append(entity)
        elif not in_pick:
            status = "MISSING_PICK"
            note = "; ".join(warn_by_key.get(key, [])) or "未进pick(空池/skip/quota)"
            missing_pick.append(entity)
        else:
            status = "OTHER"
            note = ""

        lines.append(
            f"{entity}\t{model}\t{physique}\t{placement}\t{slot_role}\t"
            f"{policy}\t{in_pick}\t{in_spawn}\t{status}\t{note}"
        )

    lines.extend(
        [
            "",
            f"# 汇总 participate_ok_spawn={ok_count} skip={skip_count} "
            f"missing_pick={len(missing_pick)} missing_spawn={len(missing_spawn)} "
            f"spawn_total={len(spawn_keys)} pick_total={len(pick_keys)}",
        ]
    )
    if missing_pick:
        lines.append("# MISSING_PICK 实体:")
        lines.extend(f"  - {e}" for e in sorted(missing_pick))
    if missing_spawn:
        lines.append("# MISSING_SPAWN 实体:")
        lines.extend(f"  - {e}" for e in sorted(missing_spawn))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_path


def prune_stale_flat_sidecars(directory: Path, seed: int) -> None:
    """Remove legacy flat sidecars in staging (seed-pinned names are authoritative)."""
    for name in ("cnv_npc_soul_copies.json", "NpcParam.csv", "cnv_npc_soul_copies_skipped.txt"):
        path = directory / name
        if not path.is_file():
            continue
        try:
            if name.endswith(".json"):
                file_seed = int(json.loads(path.read_text(encoding="utf-8")).get("seed", -1))
                if file_seed >= 0 and file_seed != seed:
                    path.unlink()
            else:
                path.unlink()
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            pass


def write_spawn_map(
    path: Path,
    seed: int,
    assignments: list[dict[str, Any]],
    mob_drop_mode: str,
    *,
    difficulty: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    from enemy_randomizer_core import DEFAULT_CATEGORIES_PATH
    """Write spawn map. Returns T-052 NpcParam copy specs (may be empty)."""
    from enemy_difficulty import load_difficulty_cfg, normalize_difficulty_settings
    from npc_soul_copies import (
        DEFAULT_NPC_CSV,
        available_npc_ids_for_copies,
        build_npc_param_copy_csv,
        plan_npc_param_patches,
        write_npc_copy_manifest,
    )

    sidecars = spawn_map_sidecar_paths(path, seed)
    soul_map = load_npc_soul_map()
    available = available_npc_ids_for_copies(DEFAULT_NPC_CSV)
    diff_settings = normalize_difficulty_settings({"difficulty": difficulty or {}})
    copies, skipped_missing = plan_npc_param_patches(
        assignments,
        soul_map,
        available_npc_ids=available,
        difficulty=diff_settings,
    )
    from npc_think_copies import plan_think_copies

    categories_cfg = None
    if DEFAULT_CATEGORIES_PATH.is_file():
        try:
            categories_cfg = json.loads(DEFAULT_CATEGORIES_PATH.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            categories_cfg = None
    think_copies = plan_think_copies(
        assignments,
        categories_cfg=categories_cfg,
        difficulty_cfg=load_difficulty_cfg(),
        difficulty=diff_settings,
    )
    lines = [
        "# CNV enemy spawn map — MSB apply; T-052 npc=runtime (copy or donor)",
        f"seed={seed}",
        f"mob_drop_mode={mob_drop_mode}",
        f"difficulty_enabled={int(diff_settings.get('enabled', True))}",
        f"difficulty_user_mult={diff_settings.get('user_mult', 1.0)}",
        f"slots={len(assignments)}",
        f"npc_soul_copies={len(copies)}",
        f"npc_think_copies={len(think_copies)}",
        f"npc_soul_copies_skipped_missing={len(skipped_missing)}",
        f"npc_soul_copies_manifest={sidecars['copies'].name}",
        f"npc_param_csv={sidecars['npc_csv'].name}",
        "# map_id\tentity_name\tsrc_cat\ttgt_cat\ttemplate_id\tmodel\tnpc\tthink\tchara\trune_amount\tengine_soul\trune_delta\tnpc_donor\tplacement\twalk_route\tbackup_anim\tpos_x\tpos_y\tpos_z",
    ]
    for row in sorted(assignments, key=lambda r: (r["map_id"], r["entity_name"])):
        npc_runtime = int(row["npc"])
        npc_donor = int(row.get("npc_donor") or npc_runtime)
        rune_amount = int(row["rune_amount"])
        engine_soul = int(soul_map.get(npc_donor, 0) or 0)
        if engine_soul < 0:
            engine_soul = 0
        rune_delta = max(0, rune_amount - engine_soul)
        lines.append(
            "\t".join(
                [
                    str(row["map_id"]),
                    str(row["entity_name"]),
                    str(row["src_cat"]),
                    str(row["tgt_cat"]),
                    str(row["template_id"]),
                    str(row["model"]),
                    str(npc_runtime),
                    str(row["think"]),
                    str(row["chara"]),
                    str(rune_amount),
                    str(engine_soul),
                    str(rune_delta),
                    str(npc_donor),
                    str(row.get("placement_kind") or "ground"),
                    str(row.get("walk_route") or ""),
                    str(row.get("backup_anim", -1)),
                    str(row.get("pos_x", "")),
                    str(row.get("pos_y", "")),
                    str(row.get("pos_z", "")),
                ]
            )
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    write_npc_copy_manifest(
        sidecars["copies"],
        seed,
        copies,
        difficulty=diff_settings,
        think_copies=think_copies,
    )
    out_csv = sidecars["npc_csv"]
    built = build_npc_param_copy_csv(copies, out_csv=out_csv)
    if built is None and out_csv.is_file():
        out_csv.unlink()
    if skipped_missing:
        # Surface in spoiler via caller: attach on assignments meta for warnings.
        sidecars["skipped"].write_text(
            "\n".join(str(x) for x in skipped_missing) + "\n",
            encoding="utf-8",
        )
    validate_spawn_bundle(path)
    return copies


def pin_spawn_map_for_apply(spawn_path: Path, seed: int) -> Path:
    """Seed-specific copy so MSB apply is not clobbered by later output/runtime writes."""
    staging_dir = spawn_path.parent / ".apply_staging"
    staging_dir.mkdir(parents=True, exist_ok=True)
    pinned = staging_dir / f"cnv_enemy_spawn_map_{seed}.txt"
    pinned.write_bytes(spawn_path.read_bytes())
    sidecars = spawn_map_sidecar_paths(pinned, seed)
    for key in ("copies", "npc_csv", "skipped"):
        side = spawn_map_sidecar_paths(spawn_path, seed)[key]
        if side.is_file():
            sidecars[key].write_bytes(side.read_bytes())
    return pinned


def deploy_enemy_spawn_map(
    src: Path,
    dest: Path | None = None,
) -> Path:
    from enemy_spawn_bundle import verify_spawn_deployed

    validate_spawn_bundle(src)
    dest_path = Path(dest) if dest is not None else Path(DEFAULT_ENEMY_SPAWN_MAP)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dest_path.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    sidecars = resolve_spawn_map_sidecar_paths(src)
    flat_names = {
        "copies": "cnv_npc_soul_copies.json",
        "npc_csv": "NpcParam.csv",
        "skipped": "cnv_npc_soul_copies_skipped.txt",
    }
    for key, flat_name in flat_names.items():
        side = sidecars[key]
        if side.is_file():
            (dest_path.parent / flat_name).write_bytes(side.read_bytes())
    seed = spawn_map_seed_from_path(src)
    if seed is None:
        header = parse_spawn_map_header(src)
        raw_seed = header.get("seed")
        seed = int(raw_seed) if isinstance(raw_seed, int) else None
    if seed is not None:
        pinned = {
            "copies": f"cnv_npc_soul_copies_{seed}.json",
            "npc_csv": f"NpcParam_{seed}.csv",
        }
        for key, pinned_name in pinned.items():
            side = sidecars[key]
            if side.is_file():
                (dest_path.parent / pinned_name).write_bytes(side.read_bytes())
    verify_spawn_deployed(src, dest_path)
    return dest_path


def write_risk_report(
    path: Path,
    seed: int,
    assignments: list[dict[str, Any]],
    categories_cfg: dict[str, Any],
) -> None:
    """Per-map risky donor lines for crash triage (should be empty after filters)."""
    risky: list[tuple[str, str, str, dict[str, Any]]] = []
    for row in assignments:
        tag = is_risky_assignment(row, categories_cfg)
        if tag:
            risky.append((str(row["map_id"]), str(row["entity_name"]), tag, row))

    lines = [
        f"# cnv_enemy_spawn_map_risk seed={seed}",
        f"risky_assignments={len(risky)}",
        "# map_id entity_name risk_tag template_id model npc think",
    ]
    for map_id, entity_name, tag, row in sorted(risky, key=lambda r: (r[0], r[1])):
        lines.append(
            f"{map_id} {entity_name} {tag} {row.get('template_id')} "
            f"{row.get('model')} {row.get('npc')} {row.get('think')}"
        )
    gatefront = [r for r in risky if r[0] == "m60_42_37_00"]
    if gatefront:
        lines.append("")
        lines.append(f"# gatefront m60_42_37_00 risky={len(gatefront)}")
        for map_id, entity_name, tag, row in gatefront:
            lines.append(
                f"  {entity_name} {tag} -> {row.get('model')} npc={row.get('npc')} think={row.get('think')}"
            )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _dsms_paramdex_paths(*parts: str) -> list[Path]:
    roots = (
        GAME_DIR / "tools" / "DSMSPortable" / "Assets",
        GAME_DIR / "tools" / "DSMSPortable" / "app" / "Assets",
    )
    return [root.joinpath(*parts) for root in roots]


def load_npc_display_names() -> dict[int, str]:
    """NpcParam ID → 英文显示名（DSMS Paramdex）；无则空 dict。"""
    global NPC_DISPLAY_NAME_CACHE
    if NPC_DISPLAY_NAME_CACHE is not None:
        return NPC_DISPLAY_NAME_CACHE
    names: dict[int, str] = {}
    for path in _dsms_paramdex_paths("Paramdex", "ER", "Names", "NpcParam.txt"):
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(maxsplit=1)
            if len(parts) != 2:
                continue
            try:
                names[int(parts[0])] = parts[1].strip()
            except ValueError:
                continue
        break
    NPC_DISPLAY_NAME_CACHE = names
    return names


def load_map_display_names(categories_cfg: dict[str, Any]) -> dict[str, str]:
    """map_id → 中文/英文地名。"""
    global MAP_DISPLAY_NAME_CACHE
    if MAP_DISPLAY_NAME_CACHE is not None:
        return MAP_DISPLAY_NAME_CACHE
    names: dict[str, str] = dict(categories_cfg.get("map_id_display_zh") or {})
    for path in _dsms_paramdex_paths("Aliases", "ER", "MapNames.txt"):
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(maxsplit=1)
            if len(parts) != 2:
                continue
            map_id, label = parts[0], parts[1]
            if map_id not in names:
                names[map_id] = label
        break
    MAP_DISPLAY_NAME_CACHE = names
    return names


def _format_category_zh(cat_id: str) -> str:
    from enemy_randomizer_core import CATEGORY_DISPLAY_ZH, CATEGORY_NUM
    num = CATEGORY_NUM.get(cat_id, "?")
    label = CATEGORY_DISPLAY_ZH.get(cat_id, cat_id)
    return f"{num}{label}"


def resolve_model_display_zh(
    model: str,
    npc: int,
    *,
    categories_cfg: dict[str, Any],
    npc_names: dict[int, str],
) -> str:
    from enemy_randomizer_core import BOSS_SOURCE_CATEGORIES
    """优先 NpcParam 英文名，其次 model 前缀中文表，最后模型代码。"""
    try:
        npc_id = int(npc)
    except (TypeError, ValueError):
        npc_id = 0
    prefix_zh = _model_prefix_zh(model, categories_cfg)
    if npc_id and npc_id in npc_names:
        en = npc_names[npc_id]
        src_cat = resolve_src_category(model, categories_cfg)
        if prefix_zh and src_cat in BOSS_SOURCE_CATEGORIES:
            return prefix_zh
        if prefix_zh and prefix_zh not in en:
            return f"{prefix_zh}（{en}）"
        return en
    if prefix_zh:
        return prefix_zh
    return f"未知模型 {model}"


def _model_prefix_zh(model: str, categories_cfg: dict[str, Any]) -> str:
    model = (model or "").lower()
    table = categories_cfg.get("model_prefix_display_zh") or {}
    best = ""
    best_len = -1
    for prefix, zh in table.items():
        p = str(prefix).lower()
        if model.startswith(p) and len(p) > best_len:
            best = str(zh)
            best_len = len(p)
    return best


def _donor_origin_tag(model: str, categories_cfg: dict[str, Any]) -> str:
    if is_dlc_trash_donor_model(model, categories_cfg):
        return "DLC小怪"
    if _model_has_prefix(
        model, categories_cfg.get("dlc_boss_model_prefixes") or []
    ):
        return "DLC Boss"
    if _model_has_prefix(
        model, categories_cfg.get("cnv_boss_model_prefixes") or []
    ):
        return "CNV"
    return "本体"


def write_spoiler_zh(
    path: Path,
    seed: int,
    assignments: list[dict[str, Any]],
    categories_cfg: dict[str, Any],
    *,
    mob_drop_mode: str,
    category_weights: dict[str, dict[str, float]] | None = None,
) -> None:
    """中文可读对照表，便于不进游戏核对随机结果。"""
    from enemy_randomizer_core import CATEGORY_DISPLAY_ZH, CATEGORY_NUM, CATEGORY_ORDER
    npc_names = load_npc_display_names()
    map_names = load_map_display_names(categories_cfg)
    legend = "  ".join(
        f"{CATEGORY_NUM[c]}={CATEGORY_DISPLAY_ZH[c]}" for c in CATEGORY_ORDER
    )
    lines = [
        "敌人随机对照表（中文）",
        f"种子：{seed}",
        f"替换槽位：{len(assignments)} 个",
        f"击杀卢恩模式：{mob_drop_mode}",
        "",
        "捐皮说明：三层彩票 — ① 矩阵抽目标大类 ② 1池原型等权+按桶内model数微调（见 trash_archetype_pick）",
        "  ③ 原型内 model 均匀→template 均匀。2~7 池每 model 一票。圣甲虫/商人/灵庙槽保持原位。",
        "  例外：5 池红灵不分二级，池内模板全局均匀抽。",
        "  4→4 黑夜骑兵：骑手+灵马成套抽卡（一次抽一对，分别装到 _900x 配对槽）。",
        "",
        f"类别：{legend}",
    ]
    if category_weights:
        lines.append("")
        lines.append("【生成时概率矩阵】每行=原类别，数字=目标类别编号:权重%")
        for src in CATEGORY_ORDER:
            row = category_weights.get(src) or {}
            if not row:
                lines.append(f"  {CATEGORY_NUM.get(src, '?')}{CATEGORY_DISPLAY_ZH.get(src, src)} → （不随机）")
                continue
            norm = normalize_row_weights({k: float(v) for k, v in row.items()})
            parts = [
                f"{CATEGORY_NUM[tgt]}:{norm[tgt] * 100:.1f}%"
                for tgt in CATEGORY_ORDER
                if tgt in norm
            ]
            lines.append(
                f"  {CATEGORY_NUM.get(src, '?')}{CATEGORY_DISPLAY_ZH.get(src, src)} → "
                + " ".join(parts)
            )
    lines.append("")
    lines.append("地图\t槽位名\t原→目标\t原型\t来源\t模型\t怪物名称\t卢恩")
    for row in sorted(assignments, key=lambda r: (r["map_id"], r["entity_name"])):
        map_id = str(row["map_id"])
        map_label = map_names.get(map_id, map_id)
        model = str(row.get("model", ""))
        try:
            npc = int(row.get("npc", 0))
        except (TypeError, ValueError):
            npc = 0
        name_zh = resolve_model_display_zh(
            model, npc, categories_cfg=categories_cfg, npc_names=npc_names
        )
        src = _format_category_zh(str(row.get("src_cat", "")))
        tgt = _format_category_zh(str(row.get("tgt_cat", "")))
        arch = str(row.get("archetype_zh") or row.get("archetype_id") or "")
        pair_id = str(row.get("mount_pair_id") or "")
        if pair_id:
            arch = f"{arch} [{pair_id}]" if arch else pair_id
        origin = _donor_origin_tag(model, categories_cfg)
        rune = row.get("rune_amount", 0)
        lines.append(
            "\t".join(
                [
                    map_label,
                    str(row.get("entity_name", "")),
                    f"{src}→{tgt}",
                    arch,
                    origin,
                    model,
                    name_zh,
                    str(rune),
                ]
            )
        )
    models = sorted({str(r.get("model", "")) for r in assignments})
    dlc_models = sorted(
        m
        for m in models
        if is_dlc_trash_donor_model(m, categories_cfg)
        or _model_has_prefix(m, categories_cfg.get("dlc_boss_model_prefixes") or [])
    )
    lines.extend(
        [
            "",
            f"模型种类：{len(models)}",
        ]
    )
    if dlc_models:
        dlc_labels = [
            f"{m}={_model_prefix_zh(m, categories_cfg) or m}" for m in dlc_models
        ]
        lines.append(f"含 DLC 模型：{', '.join(dlc_labels)}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_spoiler(
    path: Path,
    seed: int,
    assignments: list[dict[str, Any]],
    warnings: list[str],
) -> None:
    lines = [f"# spoiler_enemies seed={seed}", f"replaced={len(assignments)}", ""]
    for row in assignments:
        lines.append(
            f"{row['map_id']}\t{row['entity_name']}\t{row['src_cat']}→{row['tgt_cat']}\t"
            f"{row['model']}\tnpc={row['npc']}\trune={row['rune_amount']}"
        )
    if warnings:
        lines.append("")
        lines.append("# warnings")
        lines.extend(warnings[:50])
        if len(warnings) > 50:
            lines.append(f"... and {len(warnings) - 50} more")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

