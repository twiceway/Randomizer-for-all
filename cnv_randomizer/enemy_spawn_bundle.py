"""T-052 spawn map + NpcParam sidecar bundle validation."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

class SpawnBundleError(RuntimeError):
    """spawn map 与 T-052 sidecar（复制清单 / NpcParam）不一致或残缺。"""


def parse_spawn_map_header(spawn_map_path: Path) -> dict[str, Any]:
    """Read `#` 之前 spawn map 头字段（不含数据行）。"""
    header: dict[str, Any] = {}
    try:
        for line in spawn_map_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("# map_id"):
                break
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip()
            if key in {
                "seed",
                "slots",
                "npc_soul_copies",
                "npc_soul_copies_skipped_missing",
                "difficulty_enabled",
            }:
                try:
                    header[key] = int(val)
                except ValueError:
                    header[key] = val
            elif key == "difficulty_user_mult":
                try:
                    header[key] = float(val)
                except ValueError:
                    header[key] = val
            else:
                header[key] = val
    except OSError:
        pass
    return header


def spawn_map_seed_from_path(spawn_map_path: Path) -> int | None:
    """Parse seed from pinned filename or spawn map header."""
    m = re.match(r"cnv_enemy_spawn_map_(\d+)\.txt$", spawn_map_path.name, re.I)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            pass
    try:
        for line in spawn_map_path.read_text(encoding="utf-8").splitlines()[:15]:
            if line.startswith("seed="):
                return int(line.split("=", 1)[1].strip())
    except (OSError, ValueError):
        pass
    return None


def spawn_map_sidecar_paths(spawn_map_path: Path, seed: int | None = None) -> dict[str, Path]:
    """NpcParam copy sidecars pinned to the same seed as the spawn map."""
    resolved_seed = seed if seed is not None else spawn_map_seed_from_path(spawn_map_path)
    parent = spawn_map_path.parent
    if resolved_seed is not None:
        return {
            "copies": parent / f"cnv_npc_soul_copies_{resolved_seed}.json",
            "npc_csv": parent / f"NpcParam_{resolved_seed}.csv",
            "skipped": parent / f"cnv_npc_soul_copies_skipped_{resolved_seed}.txt",
        }
    return {
        "copies": spawn_map_path.with_name("cnv_npc_soul_copies.json"),
        "npc_csv": spawn_map_path.with_name("NpcParam.csv"),
        "skipped": spawn_map_path.with_name("cnv_npc_soul_copies_skipped.txt"),
    }


def resolve_spawn_map_sidecar_paths(spawn_map_path: Path) -> dict[str, Path]:
    """Resolve T-052 sidecars for apply/deploy.

    有 seed（文件名或头字段）时 **禁止** 回退到无 seed 的扁平 json/csv，
    避免「spawn 是 seed A、sidecar 被 seed B 覆盖」的错位。
    """
    header = parse_spawn_map_header(spawn_map_path)
    parent = spawn_map_path.parent
    seed = header.get("seed")
    if not isinstance(seed, int):
        seed = spawn_map_seed_from_path(spawn_map_path)

    if header.get("npc_soul_copies_manifest"):
        copies = parent / str(header["npc_soul_copies_manifest"])
    elif seed is not None:
        copies = parent / f"cnv_npc_soul_copies_{seed}.json"
    else:
        copies = spawn_map_path.with_name("cnv_npc_soul_copies.json")

    if header.get("npc_param_csv"):
        npc_csv = parent / str(header["npc_param_csv"])
    elif seed is not None:
        npc_csv = parent / f"NpcParam_{seed}.csv"
    else:
        npc_csv = spawn_map_path.with_name("NpcParam.csv")

    if seed is not None:
        skipped = parent / f"cnv_npc_soul_copies_skipped_{seed}.txt"
    else:
        skipped = spawn_map_path.with_name("cnv_npc_soul_copies_skipped.txt")

    resolved = {"copies": copies, "npc_csv": npc_csv, "skipped": skipped}
    if seed is not None:
        return resolved

    legacy = {
        "copies": spawn_map_path.with_name("cnv_npc_soul_copies.json"),
        "npc_csv": spawn_map_path.with_name("NpcParam.csv"),
        "skipped": spawn_map_path.with_name("cnv_npc_soul_copies_skipped.txt"),
    }
    return {key: resolved[key] if resolved[key].is_file() else legacy[key] for key in resolved}


def validate_spawn_bundle(
    spawn_map_path: Path,
    *,
    require_copies: bool = True,
) -> None:
    """校验 spawn + T-052 清单语义一致；失败抛 SpawnBundleError。"""
    from npc_soul_copies import NPC_COPY_ID_BASE

    spawn_map_path = Path(spawn_map_path)
    if not spawn_map_path.is_file():
        raise SpawnBundleError(f"spawn map 不存在: {spawn_map_path}")

    header = parse_spawn_map_header(spawn_map_path)
    seed = header.get("seed")
    if not isinstance(seed, int):
        seed = spawn_map_seed_from_path(spawn_map_path)

    sidecars = resolve_spawn_map_sidecar_paths(spawn_map_path)
    copies_json = sidecars["copies"]
    errors: list[str] = []

    expected_count = header.get("npc_soul_copies")
    try:
        expected_count_int = int(expected_count) if expected_count is not None else None
    except (TypeError, ValueError):
        expected_count_int = None

    if require_copies and expected_count_int and expected_count_int > 0 and not copies_json.is_file():
        errors.append(
            f"缺少 T-052 清单 {copies_json.name}（spawn 头 npc_soul_copies={expected_count_int}）"
        )

    if not copies_json.is_file():
        if errors:
            raise SpawnBundleError("spawn bundle 校验失败:\n- " + "\n- ".join(errors))
        return

    try:
        manifest = json.loads(copies_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SpawnBundleError(f"无法读取 {copies_json.name}: {exc}") from exc

    copy_seed = int(manifest.get("seed", -1))
    if isinstance(seed, int) and copy_seed >= 0 and copy_seed != seed:
        errors.append(f"seed 不一致: spawn={seed} copies={copy_seed} ({copies_json.name})")

    manifest_count = len(manifest.get("copies") or [])
    if expected_count_int is not None and expected_count_int != manifest_count:
        errors.append(
            f"复制行数不一致: spawn 头 npc_soul_copies={expected_count_int} "
            f"manifest={manifest_count}"
        )

    header_manifest = header.get("npc_soul_copies_manifest")
    if header_manifest and copies_json.name != str(header_manifest):
        errors.append(f"清单路径不一致: 头={header_manifest} 实际={copies_json.name}")

    copy_by_id: dict[int, dict[str, Any]] = {}
    for spec in manifest.get("copies") or []:
        try:
            copy_by_id[int(spec["copy_id"])] = spec
        except (KeyError, TypeError, ValueError):
            continue

    missing_copy = 0
    donor_mismatch = 0
    missing_sample = ""
    mismatch_sample = ""
    for line in spawn_map_path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#") or "\t" not in line:
            continue
        parts = line.split("\t")
        if len(parts) < 13:
            continue
        try:
            npc_runtime = int(parts[6])
            npc_donor = int(parts[12])
        except ValueError:
            continue
        if npc_runtime < NPC_COPY_ID_BASE:
            continue
        spec = copy_by_id.get(npc_runtime)
        if spec is None:
            missing_copy += 1
            if not missing_sample:
                missing_sample = f"{parts[0]}:{parts[1]} npc={npc_runtime}"
            continue
        try:
            base_npc = int(spec.get("base_npc", 0))
        except (TypeError, ValueError):
            base_npc = 0
        if base_npc != npc_donor:
            donor_mismatch += 1
            if not mismatch_sample:
                mismatch_sample = (
                    f"{parts[0]}:{parts[1]} npc={npc_runtime} "
                    f"donor={npc_donor} manifest_base={base_npc}"
                )

    if missing_copy:
        errors.append(
            f"{missing_copy} 槽 npc 复制 id 在清单中不存在（例: {missing_sample}）"
        )
    if donor_mismatch:
        errors.append(
            f"{donor_mismatch} 槽 npc_donor 与清单 base_npc 不符（例: {mismatch_sample}）"
        )

    if errors:
        raise SpawnBundleError("spawn bundle 校验失败:\n- " + "\n- ".join(errors))


def spawn_deploy_fingerprint(path: Path) -> tuple[int | None, int | None, int]:
    """(seed, slots, file_bytes) for deploy verification."""
    header = parse_spawn_map_header(path)
    seed = header.get("seed") if isinstance(header.get("seed"), int) else spawn_map_seed_from_path(path)
    slots = header.get("slots") if isinstance(header.get("slots"), int) else None
    try:
        size = path.stat().st_size
    except OSError:
        size = -1
    return seed, slots, size


def verify_spawn_deployed(src: Path, dest: Path) -> None:
    """确认游戏 mod/dll 的 spawn 表与刚生成的源文件一致。"""
    src = Path(src)
    dest = Path(dest)
    if not dest.is_file():
        raise OSError(f"部署后目标不存在：{dest}")
    src_seed, src_slots, src_size = spawn_deploy_fingerprint(src)
    dest_seed, dest_slots, dest_size = spawn_deploy_fingerprint(dest)
    if src_seed is not None and dest_seed != src_seed:
        raise OSError(
            f"部署种子不一致：生成 seed={src_seed}，游戏 mod seed={dest_seed}"
        )
    if src_slots is not None and dest_slots != src_slots:
        raise OSError(
            f"部署槽位数不一致：生成 slots={src_slots}，游戏 mod slots={dest_slots}"
        )
    if src_size >= 0 and dest_size >= 0 and src_size != dest_size:
        raise OSError(
            f"部署文件大小不一致：生成 {src_size} 字节，游戏 mod {dest_size} 字节"
        )
