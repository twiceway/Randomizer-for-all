"""T-052: duplicate NpcParam rows with getSoul for roadside Boss skins (428-style)."""



from __future__ import annotations



import csv

import json

import shutil

import subprocess

from pathlib import Path

from typing import Any



from paths import GAME_DIR, OUTPUT_RUNTIME, REPO_ROOT, SCRIPT_DIR, subprocess_no_window_kwargs


DEFAULT_NPC_CSV = GAME_DIR / "csv" / "NpcParam.csv"

DEFAULT_REGULATION = GAME_DIR / "mod" / "regulation.bin"

_CATEGORIES_PATH = SCRIPT_DIR / "enemy_categories.json"


# Dedicated free range (CNV NpcParam has no rows here).

NPC_COPY_ID_BASE = 880_000_000

NPC_COPY_ID_LIMIT = 881_000_000

# CNV synthetic landed Radahn donor (NpcSoulPatch clones 47300040 + phase-2 spawn fx).

RADAHN_LANDED_NPC_ID = 47_300_041

RADAHN_BASE_NPC_ID = 47_300_040

RADAHN_LANDED_SPAWN_FX = (13_902, 13_904, 13_928)



DEFAULT_NPC_CSV = GAME_DIR / "csv" / "NpcParam.csv"

DEFAULT_REGULATION = GAME_DIR / "mod" / "regulation.bin"

_CATEGORIES_PATH = SCRIPT_DIR / "enemy_categories.json"


def _unified_team_type_settings() -> tuple[bool, int]:
    """T-061：方案 B — 复制行统一 teamType，避免捐皮阵营互殴。"""
    if not _CATEGORIES_PATH.is_file():
        return False, 0
    try:
        cfg = json.loads(_CATEGORIES_PATH.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return False, 0
    block = cfg.get("npc_copy_unified_team_type") or {}
    if not isinstance(block, dict):
        return False, 0
    enabled = bool(block.get("enabled", False))
    try:
        team = int(block.get("team_type", 0) or 0)
    except (TypeError, ValueError):
        team = 0
    return enabled, team


def _donor_team_type(donor_row: dict[str, str]) -> int:
    try:
        return int(donor_row.get("teamType") or 0)
    except (TypeError, ValueError):
        return 0


def _apply_unified_team_type_patch(
    patch: dict[str, Any] | None,
    donor_row: dict[str, str],
    *,
    soul_out: int,
) -> dict[str, Any] | None:
    unified_enabled, unified_team = _unified_team_type_settings()
    if not unified_enabled:
        return patch
    if _donor_team_type(donor_row) == unified_team:
        return patch
    out = dict(patch or {})
    if "get_soul" not in out:
        out["get_soul"] = soul_out
    out["team_type"] = unified_team
    return out



NPC_SOUL_PATCH_DIR = REPO_ROOT / "cnv_enemy_poc" / "NpcSoulPatch"

SOULSFORMATS_DIR = REPO_ROOT / "cnv_enemy_poc" / "_sfnext"

NPC_SOUL_PATCH_EXE = (

    NPC_SOUL_PATCH_DIR / "bin" / "Release" / "net8.0" / "NpcSoulPatch.exe"

)





def _load_npc_rows(npc_csv: Path) -> dict[int, dict[str, str]]:

    if not npc_csv.is_file():

        raise FileNotFoundError(f"NpcParam.csv missing: {npc_csv}")

    by_id: dict[int, dict[str, str]] = {}

    with npc_csv.open(encoding="utf-8-sig", newline="") as f:

        for row in csv.DictReader(f):

            try:

                nid = int(row["ID"])

            except (KeyError, TypeError, ValueError):

                continue

            by_id[nid] = row

    return by_id





def _radahn_landed_npc_row(by_id: dict[int, dict[str, str]]) -> dict[str, str] | None:
    """Audit CSV row for landed Radahn when regulation row is not in stock NpcParam.csv."""
    src = by_id.get(RADAHN_BASE_NPC_ID)
    if src is None:
        return None
    row = dict(src)
    row["ID"] = str(RADAHN_LANDED_NPC_ID)
    name = (src.get("Name") or "").strip()
    row["Name"] = f"{name}（已落地）[cnv]" if name else "Radahn landed [cnv]"
    row["spEffectID14"] = str(RADAHN_LANDED_SPAWN_FX[0])
    row["spEffectID15"] = str(RADAHN_LANDED_SPAWN_FX[1])
    row["spEffectID17"] = str(RADAHN_LANDED_SPAWN_FX[2])
    return row



def available_npc_ids_for_copies(npc_csv: Path | None = None) -> set[int]:
    npc_csv = npc_csv or DEFAULT_NPC_CSV
    available = set(_load_npc_rows(npc_csv).keys())
    available.add(RADAHN_LANDED_NPC_ID)
    return available


def plan_npc_param_patches(

    assignments: list[dict[str, Any]],

    soul_map: dict[int, int],

    *,

    available_npc_ids: set[int] | None = None,

    npc_by_id: dict[int, dict[str, str]] | None = None,

    difficulty: dict[str, Any] | None = None,

) -> tuple[list[dict[str, Any]], list[int]]:

    """Mutate assignments: npc → runtime copy id when soul/difficulty patch needed."""

    from enemy_difficulty import (
        compute_assignment_patch,
        load_difficulty_cfg,
        normalize_difficulty_settings,
        npc_base_hp,
        patch_fingerprint,
        scale_rune_by_assignment_hp,
        scale_rune_by_target_curve,
        target_progression_enabled,
    )
    from enemy_randomizer_core import red_spirit_rune_tier_only

    skipped_missing: list[int] = []

    if npc_by_id is None:

        npc_by_id = _load_npc_rows(DEFAULT_NPC_CSV)

    difficulty = normalize_difficulty_settings({"difficulty": difficulty or {}})
    difficulty_cfg = load_difficulty_cfg()
    use_target_curve = target_progression_enabled(difficulty_cfg)
    tier_only_fn = red_spirit_rune_tier_only

    needed: dict[tuple[int, str], dict[str, Any]] = {}

    row_patch: dict[int, tuple[int, str]] = {}

    for row in assignments:

        try:

            base = int(row.get("npc") or 0)

        except (TypeError, ValueError):

            base = 0

        from dlc_donor_pool import resolve_valid_donor_npc

        resolved = resolve_valid_donor_npc(
            base,
            str(row.get("model") or ""),
            npc_by_id,
        )
        if resolved > 0:
            base = resolved

        try:

            amount = int(row.get("rune_amount") or 0)

        except (TypeError, ValueError):

            amount = 0

        row["npc_donor"] = base

        row["npc_copy"] = False

        row.pop("hp_floor", None)

        row.pop("difficulty_tier", None)

        if base <= 0:

            continue

        engine = int(soul_map.get(base, 0) or 0)

        if engine < 0:

            engine = 0

        row["_engine_soul"] = engine

        donor_row = npc_by_id.get(base)

        if donor_row is None:

            if amount > 0:

                skipped_missing.append(base)

            continue

        if use_target_curve:
            if amount > 0:
                amount = scale_rune_by_target_curve(
                    amount,
                    row,
                    difficulty=difficulty,
                    difficulty_cfg=difficulty_cfg,
                )
        else:
            amount = scale_rune_by_assignment_hp(
                amount,
                row,
                donor_row,
                difficulty=difficulty,
                npc_by_id=npc_by_id,
                difficulty_cfg=difficulty_cfg,
            )
        row["rune_amount"] = amount

        tier_only = tier_only_fn(
            str(row.get("tgt_cat") or ""),
            str(row.get("model") or ""),
        )
        if tier_only:
            soul_out = int(amount) if amount > 0 else 0
        else:
            soul_out = amount if amount > engine and amount > 0 else engine

        patch = compute_assignment_patch(

            row,

            donor_row,

            soul_out=soul_out,

            difficulty=difficulty,

            npc_by_id=npc_by_id,

            difficulty_cfg=difficulty_cfg,

        )

        if patch is None and difficulty.get("enabled", True) and donor_row is not None:
            from enemy_difficulty import (
                rebind_region_sp_effects,
                resolve_slot_progression_tier,
            )

            map_id = str(row.get("map_id") or "")
            slot_tier = resolve_slot_progression_tier(map_id)
            sp_overrides = rebind_region_sp_effects(donor_row, slot_tier)
            if sp_overrides:
                patch = {
                    "get_soul": soul_out,
                    "slot_tier": slot_tier,
                    "slot_map_id": map_id,
                    "sp_effect_overrides": {
                        str(k): int(v) for k, v in sorted(sp_overrides.items())
                    },
                }

        if patch is None and amount > engine and amount > 0:

            patch = {"get_soul": soul_out}

        patch = _apply_unified_team_type_patch(
            patch, donor_row, soul_out=soul_out
        )

        if patch is not None:
            baked = int(row.get("rune_amount") or 0)
            gs = int(patch.get("get_soul") or 0)
            if baked > 0:
                patch["get_soul"] = baked
                row["rune_amount"] = baked
            elif gs > 0:
                row["rune_amount"] = gs
            elif soul_out > 0:
                patch["get_soul"] = int(soul_out)
                row["rune_amount"] = int(soul_out)
            elif engine > 0 and not tier_only:
                patch["get_soul"] = int(engine)
                row["rune_amount"] = int(engine)

        if patch is None:

            continue

        if available_npc_ids is not None and base not in available_npc_ids:

            skipped_missing.append(base)

            continue

        fp = patch_fingerprint(base, patch)

        needed[(base, fp)] = patch

        row_patch[id(row)] = (base, fp)



    keys = sorted(needed.keys())

    if len(keys) > (NPC_COPY_ID_LIMIT - NPC_COPY_ID_BASE):

        raise RuntimeError(

            f"T-052 npc copy overflow: need {len(keys)} ids in "

            f"[{NPC_COPY_ID_BASE}, {NPC_COPY_ID_LIMIT})"

        )

    copy_ids = {k: NPC_COPY_ID_BASE + i for i, k in enumerate(keys)}



    for row in assignments:

        key = row_patch.get(id(row))

        if not key:

            continue

        row["npc"] = copy_ids[key]

        row["npc_copy"] = True

        patch = needed[key]

        if patch.get("hp") is not None:

            row["hp_floor"] = patch["hp"]

        if patch.get("slot_tier") is not None:

            row["difficulty_tier"] = patch["slot_tier"]



    copies: list[dict[str, Any]] = []

    for (base, fp), patch in sorted(needed.items(), key=lambda x: copy_ids[x[0]]):

        spec: dict[str, Any] = {

            "copy_id": copy_ids[(base, fp)],

            "base_npc": base,

            "get_soul": int(patch.get("get_soul", 0)),

        }

        if patch.get("hp") is not None:

            spec["hp"] = int(patch["hp"])

        if patch.get("defFlickPower") is not None:

            spec["defFlickPower"] = int(patch["defFlickPower"])

        if patch.get("sp_effect_overrides"):
            # NpcSoulPatch requires JSON ints (string "7070" was silently dropped).
            spec["sp_effect_overrides"] = {
                str(slot): int(sp_id)
                for slot, sp_id in dict(patch["sp_effect_overrides"]).items()
            }

        if patch.get("team_type") is not None:

            spec["team_type"] = int(patch["team_type"])

        if patch.get("slot_tier") is not None:

            spec["slot_tier"] = patch["slot_tier"]

        if patch.get("adaptive_lift") is not None:

            spec["adaptive_lift"] = float(patch["adaptive_lift"])

            spec["donor_eff_hp"] = int(patch.get("donor_eff_hp") or 0)

            spec["anchor_eff_hp"] = int(patch.get("anchor_eff_hp") or 0)

        if patch.get("attack_sp"):

            spec["attack_sp"] = dict(patch["attack_sp"])

        copies.append(spec)

    return copies, sorted(set(skipped_missing))





def plan_npc_soul_copies(

    assignments: list[dict[str, Any]],

    soul_map: dict[int, int],

    *,

    available_npc_ids: set[int] | None = None,

    npc_by_id: dict[int, dict[str, str]] | None = None,

    difficulty: dict[str, Any] | None = None,

) -> tuple[list[dict[str, Any]], list[int]]:

    return plan_npc_param_patches(

        assignments,

        soul_map,

        available_npc_ids=available_npc_ids,

        npc_by_id=npc_by_id,

        difficulty=difficulty,

    )





def write_npc_copy_manifest(

    path: Path,

    seed: int,

    copies: list[dict[str, Any]],

    *,

    difficulty: dict[str, Any] | None = None,

    think_copies: list[dict[str, Any]] | None = None,

) -> None:

    path.parent.mkdir(parents=True, exist_ok=True)

    payload: dict[str, Any] = {

        "schema": "cnv_npc_soul_copies_v2",

        "seed": seed,

        "id_base": NPC_COPY_ID_BASE,

        "think_id_base": 890_000_000,

        "copies": copies,

    }

    if think_copies:
        payload["think_copies"] = think_copies

    if difficulty is not None:

        payload["difficulty"] = difficulty

    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")





def build_npc_param_copy_csv(

    copies: list[dict[str, Any]],

    *,

    npc_csv: Path | None = None,

    out_csv: Path | None = None,

) -> Path | None:

    """Build NpcParam.csv of new rows (audit / Smithbox fallback). None if no copies."""

    if not copies:

        return None

    npc_csv = npc_csv or DEFAULT_NPC_CSV

    out_csv = out_csv or (OUTPUT_RUNTIME / "NpcParam.csv")

    by_id = _load_npc_rows(npc_csv)

    with npc_csv.open(encoding="utf-8-sig", newline="") as f:

        fieldnames = list(csv.DictReader(f).fieldnames or [])

    if not fieldnames or "ID" not in fieldnames:

        raise RuntimeError(f"bad NpcParam.csv header: {npc_csv}")



    out_rows: list[dict[str, str]] = []

    missing: list[int] = []

    for spec in copies:

        base = int(spec["base_npc"])

        src = by_id.get(base)
        if src is None and base == RADAHN_LANDED_NPC_ID:
            src = _radahn_landed_npc_row(by_id)

        if src is None:

            missing.append(base)

            continue

        row = {k: src.get(k, "") for k in fieldnames}

        row["ID"] = str(int(spec["copy_id"]))

        row["getSoul"] = str(int(spec["get_soul"]))

        hp_override = spec.get("hp")

        if hp_override is not None:

            row["hp"] = str(int(hp_override))

        poise_override = spec.get("defFlickPower")

        if poise_override is not None and "defFlickPower" in row:

            row["defFlickPower"] = str(int(poise_override))

        sp_overrides = spec.get("sp_effect_overrides") or {}

        for slot, sp_id in sp_overrides.items():

            if slot in row:

                row[slot] = str(int(sp_id))

        if "isSoulGetByBoss" in row:

            row["isSoulGetByBoss"] = "0"

        if "disableRespawn" in row:

            row["disableRespawn"] = "0"

        if "disableInitializeDead" in row:

            row["disableInitializeDead"] = "0"

        team_override = spec.get("team_type")

        if team_override is not None and "teamType" in row:

            row["teamType"] = str(int(team_override))

        name = (src.get("Name") or "").strip()

        row["Name"] = f"{name} [cnv soul {spec['get_soul']}]" if name else f"cnv_soul_{spec['copy_id']}"

        out_rows.append(row)



    if missing:

        raise RuntimeError(

            "T-052 missing base NpcParam rows in CSV: "

            + ", ".join(str(x) for x in missing[:12])

            + ("…" if len(missing) > 12 else "")

        )

    if not out_rows:

        return None



    out_csv.parent.mkdir(parents=True, exist_ok=True)

    with out_csv.open("w", encoding="utf-8-sig", newline="") as f:

        writer = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")

        writer.writeheader()

        writer.writerows(out_rows)

    return out_csv





def _ensure_soulsformats() -> None:

    csproj = SOULSFORMATS_DIR / "SoulsFormats" / "SoulsFormats.csproj"

    if csproj.is_file():

        return

    SOULSFORMATS_DIR.parent.mkdir(parents=True, exist_ok=True)

    proc = subprocess.run(

        [

            "git",

            "clone",

            "--depth",

            "1",

            "https://github.com/soulsmods/SoulsFormats.git",

            str(SOULSFORMATS_DIR),

        ],

        capture_output=True,

        text=True,

        encoding="utf-8",

        errors="replace",

        **subprocess_no_window_kwargs(),

    )

    if proc.returncode != 0 or not csproj.is_file():

        raise RuntimeError(

            "T-052 needs SoulsFormats clone at "

            f"{SOULSFORMATS_DIR} (git clone failed):\n"

            + (proc.stdout or "")

            + "\n"

            + (proc.stderr or "")

        )

    # Prefer net8 so hosts without net9 runtime can build.

    text = csproj.read_text(encoding="utf-8")

    if "net9.0" in text:

        csproj.write_text(text.replace("net9.0", "net8.0"), encoding="utf-8")





def ensure_npc_soul_patch_built() -> Path:
    """Build NpcSoulPatch.exe if missing or Program.cs newer than exe."""
    csproj = NPC_SOUL_PATCH_DIR / "NpcSoulPatch.csproj"
    program_cs = NPC_SOUL_PATCH_DIR / "Program.cs"
    need_build = not NPC_SOUL_PATCH_EXE.is_file()
    if not need_build and program_cs.is_file():
        need_build = program_cs.stat().st_mtime > NPC_SOUL_PATCH_EXE.stat().st_mtime
    if not need_build:
        return NPC_SOUL_PATCH_EXE

    _ensure_soulsformats()
    if not csproj.is_file():
        raise FileNotFoundError(f"NpcSoulPatch project missing: {NPC_SOUL_PATCH_DIR}")

    proc = subprocess.run(
        ["dotnet", "build", "NpcSoulPatch.csproj", "-c", "Release"],
        cwd=str(NPC_SOUL_PATCH_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        **subprocess_no_window_kwargs(),
    )
    if proc.returncode != 0 or not NPC_SOUL_PATCH_EXE.is_file():
        raise RuntimeError(
            "NpcSoulPatch build failed:\n"
            + (proc.stdout or "")
            + "\n"
            + (proc.stderr or "")
        )
    return NPC_SOUL_PATCH_EXE





def regulation_patch_key_path(copies_manifest: Path) -> Path:
    return copies_manifest.with_name(f"{copies_manifest.name}.regpatch.key")


def _regulation_patch_fingerprint(
    copies_manifest: Path,
    regulation: Path,
) -> str:
    import hashlib

    digest = hashlib.sha256()
    if copies_manifest.is_file():
        digest.update(copies_manifest.read_bytes())
    if regulation.is_file():
        st = regulation.stat()
        digest.update(
            f"|{st.st_size}|{int(st.st_mtime_ns)}".encode("utf-8")
        )
    return digest.hexdigest()[:16]


def regulation_patch_unchanged(
    copies_manifest: Path,
    *,
    regulation: Path | None = None,
) -> bool:
    regulation = regulation or DEFAULT_REGULATION
    key_path = regulation_patch_key_path(copies_manifest)
    if not key_path.is_file() or not copies_manifest.is_file():
        return False
    try:
        want = _regulation_patch_fingerprint(copies_manifest, regulation)
        return key_path.read_text(encoding="utf-8").strip() == want
    except OSError:
        return False


def stamp_regulation_patch_fingerprint(
    copies_manifest: Path,
    *,
    regulation: Path | None = None,
) -> None:
    regulation = regulation or DEFAULT_REGULATION
    key_path = regulation_patch_key_path(copies_manifest)
    try:
        key_path.write_text(
            _regulation_patch_fingerprint(copies_manifest, regulation),
            encoding="utf-8",
        )
    except OSError:
        pass


def patch_regulation_npc_copies(

    copies_manifest: Path | None,

    *,

    regulation: Path | None = None,

    clear_only: bool = False,

) -> str:

    """Apply T-052 NpcParam copies into mod regulation.bin via NpcSoulPatch.



    ``copies_manifest`` is ``cnv_npc_soul_copies.json``. Pass None + clear_only

    to wipe the 880M id band without adding rows.

    """

    regulation = regulation or DEFAULT_REGULATION

    if not regulation.is_file():

        raise FileNotFoundError(f"regulation.bin not found: {regulation}")



    exe = ensure_npc_soul_patch_built()

    cmd = [str(exe), "--regulation", str(regulation.resolve())]

    if clear_only or copies_manifest is None:

        cmd.append("--clear-only")

    else:

        if not copies_manifest.is_file():

            raise FileNotFoundError(f"copies manifest missing: {copies_manifest}")

        # Empty copies → still clear stale band.

        try:

            payload = json.loads(copies_manifest.read_text(encoding="utf-8"))

            n = len(payload.get("copies") or [])

            n_think = len(payload.get("think_copies") or [])

        except (OSError, json.JSONDecodeError):

            n = -1

            n_think = -1

        if n == 0 and n_think == 0:

            cmd.append("--clear-only")

        else:

            cmd.extend(["--copies", str(copies_manifest.resolve())])



    proc = subprocess.run(

        cmd,

        cwd=str(exe.parent),

        capture_output=True,

        text=True,

        encoding="utf-8",

        errors="replace",

        **subprocess_no_window_kwargs(),

    )

    if proc.returncode != 0:

        raise RuntimeError(

            "NpcSoulPatch failed:\n"

            + (proc.stdout or "")

            + "\n"

            + (proc.stderr or "")

        )

    tail = (proc.stdout or "").strip().splitlines()

    status = tail[-1] if tail else "ok"

    if not clear_only and copies_manifest is not None and copies_manifest.is_file():
        stamp_regulation_patch_fingerprint(copies_manifest, regulation=regulation)

    return f"npc_copies_patched regulation={regulation} {status}"


def ensure_radahn_phase1_assets(
    *,
    regulation: Path | None = None,
    game_dir: Path | None = None,
) -> str:
    """Patch shared Radahn AI 473000 in-place (disable meteor); drop legacy 473090."""
    regulation = regulation or DEFAULT_REGULATION
    game_dir = game_dir or GAME_DIR
    exe = ensure_npc_soul_patch_built()
    cmd = [
        str(exe),
        "--ensure-radahn-phase1",
        "--regulation",
        str(regulation.resolve()),
        "--game-dir",
        str(Path(game_dir).resolve()),
    ]
    proc = subprocess.run(
        cmd,
        cwd=str(exe.parent),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        raise RuntimeError(
            "NpcSoulPatch radahn-phase1 failed:\n"
            + (proc.stdout or "")
            + "\n"
            + (proc.stderr or "")
        )
    tail = (proc.stdout or "").strip().splitlines()
    return tail[-1] if tail else "ok"


