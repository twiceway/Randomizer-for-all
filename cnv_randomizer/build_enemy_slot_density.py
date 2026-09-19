"""Offline spatial clustering for dense enemy slot zones.

Reads enemy_index.json (with pos_x/y/z), clusters participating combat slots
per map_id on an XYZ grid (20m default), assigns 1/2 keep_original + 1/2 dense_pool_1_2
(pool1=trash, pool2=elite; Step2 consumes).

Run:
  python build_enemy_slot_density.py
  python build_enemy_slot_density.py --map-filter m60_43_33
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from paths import SCRIPT_DIR  # frozen-safe
DEFAULT_INDEX = SCRIPT_DIR / "cache" / "enemy_index.json"
DEFAULT_CATEGORIES = SCRIPT_DIR / "enemy_categories.json"
OUT_JSON = SCRIPT_DIR / "cache" / "enemy_slot_density.json"
OUT_META = SCRIPT_DIR / "cache" / "enemy_slot_density.meta.json"
from paths import OUTPUT_REPORTS  # noqa: E402

OUT_REPORT = OUTPUT_REPORTS / "密集槽聚类表.md"

SCHEMA = "enemy_slot_density_v2"
# XYZ 20m 格内 ≥7 槽即成簇；不合并相邻热格；跨度 >30m（含 Y）丢弃
DEFAULT_CELL_SIZE = 20.0
DEFAULT_MIN_CELL_SLOTS = 7
DEFAULT_MIN_CLUSTER_SIZE = 7
DEFAULT_MERGE_GAP_CELLS = 0
DEFAULT_MERGE_ADJACENT_HOT_CELLS = False
DEFAULT_MAX_CLUSTER_SPAN = 20.0
DEFAULT_MAX_CLUSTER_Y_SPAN = 10.0
# 用户确认：海德要塞庭院不算密集（仍全池随机）
DENSITY_SKIP_MAP_IDS = frozenset({"m60_46_36_00", "m60_46_36_10"})


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _file_fingerprint(path: Path) -> str:
    if not path.is_file():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()[:16]


def _import_core():
    sys.path.insert(0, str(SCRIPT_DIR))
    import enemy_randomizer_core as core  # noqa: WPS433

    return core


def _slot_has_position(slot: dict[str, Any]) -> bool:
    for key in ("pos_x", "pos_y", "pos_z"):
        if key not in slot:
            return False
        try:
            float(slot[key])
        except (TypeError, ValueError):
            return False
    return True


def _map_matches(map_id: str, map_filter: str | None) -> bool:
    if not map_filter:
        return True
    needle = map_filter.strip()
    if not needle:
        return True
    return map_id == needle or map_id.startswith(needle)


class _UnionFind:
    def __init__(self, keys: list[tuple[int, int]]) -> None:
        self.parent = {k: k for k in keys}

    def find(self, key: tuple[int, int]) -> tuple[int, int]:
        parent = self.parent[key]
        if parent != key:
            self.parent[key] = self.find(parent)
        return self.parent[key]

    def union(self, a: tuple[int, int], b: tuple[int, int]) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def _centroid_xyz(slots: list[dict[str, Any]]) -> tuple[float, float, float]:
    if not slots:
        return 0.0, 0.0, 0.0
    sx = sum(float(s["pos_x"]) for s in slots)
    sy = sum(float(s["pos_y"]) for s in slots)
    sz = sum(float(s["pos_z"]) for s in slots)
    n = len(slots)
    return sx / n, sy / n, sz / n


def _cluster_span_xz(slots: list[dict[str, Any]]) -> float:
    xs = [float(s["pos_x"]) for s in slots]
    zs = [float(s["pos_z"]) for s in slots]
    return max(max(xs) - min(xs), max(zs) - min(zs))


def _cluster_span_y(slots: list[dict[str, Any]]) -> float:
    ys = [float(s["pos_y"]) for s in slots]
    return max(ys) - min(ys)


def _cluster_within_span_limits(
    slots: list[dict[str, Any]],
    *,
    max_cluster_span: float | None,
    max_cluster_y_span: float | None,
) -> bool:
    if max_cluster_span is not None and _cluster_span_xz(slots) > max_cluster_span:
        return False
    if max_cluster_y_span is not None and _cluster_span_y(slots) > max_cluster_y_span:
        return False
    return True


def _merge_nearby_clusters(
    clusters: list[list[dict[str, Any]]],
    gap_dist: float,
) -> list[list[dict[str, Any]]]:
    if len(clusters) <= 1:
        return clusters
    changed = True
    current = clusters
    while changed:
        changed = False
        merged: list[list[dict[str, Any]]] = []
        used = [False] * len(current)
        for i, group_i in enumerate(current):
            if used[i]:
                continue
            combined = list(group_i)
            used[i] = True
            cxi, cyi, czi = _centroid_xyz(combined)
            for j in range(i + 1, len(current)):
                if used[j]:
                    continue
                cxj, cyj, czj = _centroid_xyz(current[j])
                dx = cxi - cxj
                dy = cyi - cyj
                dz = czi - czj
                if math.sqrt(dx * dx + dy * dy + dz * dz) < gap_dist:
                    combined.extend(current[j])
                    used[j] = True
                    changed = True
            merged.append(combined)
        current = merged
    return current


def _cluster_map_slots(
    slots: list[dict[str, Any]],
    *,
    cell_size: float,
    min_cell_slots: int,
    min_cluster_size: int,
    merge_gap_cells: int,
    merge_adjacent_hot_cells: bool = DEFAULT_MERGE_ADJACENT_HOT_CELLS,
    max_cluster_span: float | None = DEFAULT_MAX_CLUSTER_SPAN,
    max_cluster_y_span: float | None = DEFAULT_MAX_CLUSTER_Y_SPAN,
) -> list[dict[str, Any]]:
    cells: dict[tuple[int, int, int], list[dict[str, Any]]] = defaultdict(list)
    for slot in slots:
        cx = math.floor(float(slot["pos_x"]) / cell_size)
        cy = math.floor(float(slot["pos_y"]) / cell_size)
        cz = math.floor(float(slot["pos_z"]) / cell_size)
        cells[(cx, cy, cz)].append(slot)

    hot_cells = {key for key, members in cells.items() if len(members) >= min_cell_slots}
    if not hot_cells:
        return []

    if merge_adjacent_hot_cells:
        uf = _UnionFind(list(hot_cells))
        for cx, cy, cz in hot_cells:
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for dz in (-1, 0, 1):
                        if dx == 0 and dy == 0 and dz == 0:
                            continue
                        nb = (cx + dx, cy + dy, cz + dz)
                        if nb in hot_cells:
                            uf.union((cx, cy, cz), nb)

        components: dict[tuple[int, int, int], list[dict[str, Any]]] = defaultdict(list)
        for cell in hot_cells:
            root = uf.find(cell)
            components[root].extend(cells[cell])

        gap_dist = merge_gap_cells * cell_size
        merged_groups = _merge_nearby_clusters(list(components.values()), gap_dist)
    else:
        merged_groups = [
            cells[cell_key]
            for cell_key in sorted(hot_cells)
            if len(cells[cell_key]) >= min_cluster_size
        ]

    results: list[dict[str, Any]] = []
    for idx, members in enumerate(merged_groups):
        if len(members) < min_cluster_size:
            continue
        if not _cluster_within_span_limits(
            members,
            max_cluster_span=max_cluster_span,
            max_cluster_y_span=max_cluster_y_span,
        ):
            continue
        members_sorted = sorted(members, key=lambda s: (str(s["map_id"]), str(s["name"])))
        n = len(members_sorted)
        # 密集区：1/2 原位不动；其余第二步只在池1(trash)+池2(elite)抽
        keep_count = n // 2
        cx, cy, cz = _centroid_xyz(members_sorted)
        map_id = str(members_sorted[0]["map_id"])
        cell_keys = sorted(
            {
                (
                    math.floor(float(s["pos_x"]) / cell_size),
                    math.floor(float(s["pos_y"]) / cell_size),
                    math.floor(float(s["pos_z"]) / cell_size),
                )
                for s in members_sorted
            }
        )
        results.append(
            {
                "cluster_id": f"{map_id}:dense{idx:03d}",
                "map_id": map_id,
                "participating_count": n,
                "keep_count": keep_count,
                "randomize_count": n - keep_count,
                "centroid_x": round(cx, 2),
                "centroid_y": round(cy, 2),
                "centroid_z": round(cz, 2),
                "cell_keys": [[int(a), int(b), int(c)] for a, b, c in cell_keys],
                "slots": members_sorted,
                "keep_count_target": keep_count,
            }
        )
    return results


def _participating_slots(
    index: dict[str, Any],
    categories_cfg: dict[str, Any],
    *,
    map_filter: str | None,
) -> list[dict[str, Any]]:
    core = _import_core()
    slots = index.get("slots") or []
    _, skip_mount_keys = core.index_rider_mount_slot_pairs(slots, categories_cfg)
    npc_csv_dir = core.GAME_DIR / "csv"

    out: list[dict[str, Any]] = []
    for slot in slots:
        map_id = str(slot.get("map_id", ""))
        if not _map_matches(map_id, map_filter):
            continue
        if not _slot_has_position(slot):
            continue
        entity = str(slot.get("name", ""))
        if (map_id, entity) in skip_mount_keys:
            continue
        skip = core.resolve_effective_slot_skip(
            None,
            slot,
            categories_cfg=categories_cfg,
            npc_csv_dir=npc_csv_dir,
        )
        if skip is not None:
            continue
        out.append(slot)
    return out


def _assign_slot_policies(cluster_rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    slot_map: dict[str, dict[str, Any]] = {}
    for cluster in cluster_rows:
        cluster_id = str(cluster["cluster_id"])
        members = cluster["slots"]
        keep_count = int(cluster["keep_count_target"])
        for i, slot in enumerate(members):
            key = f"{slot['map_id']}:{slot['name']}"
            keep = i < keep_count
            slot_map[key] = {
                "cluster_id": cluster_id,
                "keep_original": keep,
                "dense_pool_1_2": not keep,
            }
    return slot_map


def _write_report(
    path: Path,
    *,
    params: dict[str, Any],
    clusters: list[dict[str, Any]],
    slot_map: dict[str, dict[str, Any]],
    map_filter: str | None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# 密集槽空间聚类审阅表",
        "",
        f"- 生成时间（UTC）: {datetime.now(timezone.utc).isoformat()}",
        f"- 参数: cell_size={params['cell_size']}, "
        f"min_cell_slots={params['min_cell_slots']}, "
        f"min_cluster_size={params['min_cluster_size']}, "
        f"merge_gap_cells={params['merge_gap_cells']}, "
        f"merge_adjacent_hot_cells={params['merge_adjacent_hot_cells']}, "
        f"max_cluster_span={params['max_cluster_span']}, "
        f"max_cluster_y_span={params.get('max_cluster_y_span')}, "
        f"grid_axes={params.get('grid_axes', 'xyz')}, "
        f"skip_maps={params.get('skip_map_ids', [])}",
    ]
    if map_filter:
        lines.append(f"- map_filter: `{map_filter}`")
    lines.extend(
        [
            f"- 密集簇数: {len(clusters)}",
            f"- 约束槽数: {len(slot_map)}",
            "",
            "## 热点簇（按槽数降序，前 40）",
            "",
            "| 簇 ID | 地图 | 槽数 | keep | randomize | 中心 XYZ |",
            "|-------|------|------|------|-----------|----------|",
        ]
    )
    ranked = sorted(clusters, key=lambda c: int(c["participating_count"]), reverse=True)
    for cluster in ranked[:40]:
        lines.append(
            f"| `{cluster['cluster_id']}` | `{cluster['map_id']}` | "
            f"{cluster['participating_count']} | {cluster['keep_count']} | "
            f"{cluster['randomize_count']} | "
            f"({cluster['centroid_x']}, {cluster.get('centroid_y', 0)}, {cluster['centroid_z']}) |"
        )

    morne_prefixes = ("m60_43_31", "m60_43_32", "m60_43_33", "m60_43_34")
    morne = [
        c for c in clusters if any(str(c["map_id"]).startswith(p) for p in morne_prefixes)
    ]
    lines.extend(["", "## 摩恩城外圈（m60_43_31~34）", ""])
    if not morne:
        lines.append("（无命中簇 — 可调 cell_size / min_cluster_size）")
    else:
        lines.append("| 簇 ID | 地图 | 槽数 | keep | randomize |")
        lines.append("|-------|------|------|------|-----------|")
        for cluster in sorted(morne, key=lambda c: str(c["map_id"])):
            lines.append(
                f"| `{cluster['cluster_id']}` | `{cluster['map_id']}` | "
                f"{cluster['participating_count']} | {cluster['keep_count']} | "
                f"{cluster['randomize_count']} |"
            )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_density(
    *,
    index_path: Path = DEFAULT_INDEX,
    categories_path: Path = DEFAULT_CATEGORIES,
    out_json: Path = OUT_JSON,
    out_meta: Path = OUT_META,
    out_report: Path = OUT_REPORT,
    cell_size: float = DEFAULT_CELL_SIZE,
    min_cell_slots: int = DEFAULT_MIN_CELL_SLOTS,
    min_cluster_size: int = DEFAULT_MIN_CLUSTER_SIZE,
    merge_gap_cells: int = DEFAULT_MERGE_GAP_CELLS,
    merge_adjacent_hot_cells: bool = DEFAULT_MERGE_ADJACENT_HOT_CELLS,
    max_cluster_span: float | None = DEFAULT_MAX_CLUSTER_SPAN,
    max_cluster_y_span: float | None = DEFAULT_MAX_CLUSTER_Y_SPAN,
    skip_map_ids: frozenset[str] | None = None,
    map_filter: str | None = None,
) -> dict[str, Any]:
    if not index_path.is_file():
        raise FileNotFoundError(f"缺少索引: {index_path}")
    raw_index = _load_json(index_path)
    slots = raw_index.get("slots") or []
    if slots and not _slot_has_position(slots[0]):
        raise RuntimeError(
            "enemy_index.json 缺少 pos_x/y/z — 请先 GUI「扫描地图」或重跑 index-export"
        )

    categories_cfg = _load_json(categories_path)
    participating = _participating_slots(raw_index, categories_cfg, map_filter=map_filter)

    by_map: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for slot in participating:
        by_map[str(slot["map_id"])].append(slot)

    skip_ids = skip_map_ids if skip_map_ids is not None else DENSITY_SKIP_MAP_IDS
    cluster_rows: list[dict[str, Any]] = []
    for map_id in sorted(by_map):
        if map_id in skip_ids:
            continue
        cluster_rows.extend(
            _cluster_map_slots(
                by_map[map_id],
                cell_size=cell_size,
                min_cell_slots=min_cell_slots,
                min_cluster_size=min_cluster_size,
                merge_gap_cells=merge_gap_cells,
                merge_adjacent_hot_cells=merge_adjacent_hot_cells,
                max_cluster_span=max_cluster_span,
                max_cluster_y_span=max_cluster_y_span,
            )
        )

    slot_map = _assign_slot_policies(cluster_rows)
    params = {
        "cell_size": cell_size,
        "grid_axes": "xyz",
        "min_cell_slots": min_cell_slots,
        "min_cluster_size": min_cluster_size,
        "merge_gap_cells": merge_gap_cells,
        "merge_adjacent_hot_cells": merge_adjacent_hot_cells,
        "max_cluster_span": max_cluster_span,
        "max_cluster_y_span": max_cluster_y_span,
        "skip_map_ids": sorted(skip_ids),
    }
    index_fp = _file_fingerprint(index_path)
    categories_fp = _file_fingerprint(categories_path)

    clusters_out = []
    for cluster in cluster_rows:
        item = dict(cluster)
        item.pop("slots", None)
        item.pop("keep_count_target", None)
        clusters_out.append(item)

    payload = {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "params": params,
        "index_fingerprint": index_fp,
        "categories_fingerprint": categories_fp,
        "participating_slots": len(participating),
        "cluster_count": len(clusters_out),
        "constrained_slot_count": len(slot_map),
        "clusters": clusters_out,
        "slots": slot_map,
    }
    meta = {
        "schema": SCHEMA,
        "generated_at": payload["generated_at"],
        "index_fingerprint": index_fp,
        "categories_fingerprint": categories_fp,
        "params": params,
        "cluster_count": len(clusters_out),
        "constrained_slot_count": len(slot_map),
    }

    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    out_meta.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_report(
        out_report,
        params=params,
        clusters=cluster_rows,
        slot_map=slot_map,
        map_filter=map_filter,
    )
    return {
        "cluster_count": len(clusters_out),
        "constrained_slot_count": len(slot_map),
        "out_json": out_json,
        "out_meta": out_meta,
        "out_report": out_report,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build enemy_slot_density.json from enemy_index")
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--categories", type=Path, default=DEFAULT_CATEGORIES)
    parser.add_argument("--out-json", type=Path, default=OUT_JSON)
    parser.add_argument("--out-meta", type=Path, default=OUT_META)
    parser.add_argument("--out-report", type=Path, default=OUT_REPORT)
    parser.add_argument("--cell-size", type=float, default=DEFAULT_CELL_SIZE)
    parser.add_argument("--min-cell-slots", type=int, default=DEFAULT_MIN_CELL_SLOTS)
    parser.add_argument("--min-cluster-size", type=int, default=DEFAULT_MIN_CLUSTER_SIZE)
    parser.add_argument("--merge-gap-cells", type=int, default=DEFAULT_MERGE_GAP_CELLS)
    parser.add_argument(
        "--merge-adjacent-hot-cells",
        action=argparse.BooleanOptionalAction,
        default=DEFAULT_MERGE_ADJACENT_HOT_CELLS,
        help="合并相邻热格（默认 false：单格成簇）",
    )
    parser.add_argument(
        "--max-cluster-span",
        type=float,
        default=DEFAULT_MAX_CLUSTER_SPAN,
        help="簇内 XZ 跨度上限（游戏单位）；0 表示不限制",
    )
    parser.add_argument(
        "--max-cluster-y-span",
        type=float,
        default=DEFAULT_MAX_CLUSTER_Y_SPAN,
        help="簇内 Y（高度）跨度上限（游戏单位）；0 表示不限制",
    )
    parser.add_argument("--map-filter", type=str, default=None, help="仅处理匹配前缀的地图（调参）")
    args = parser.parse_args(argv)

    max_span = args.max_cluster_span
    if max_span is not None and max_span <= 0:
        max_span = None
    max_y_span = args.max_cluster_y_span
    if max_y_span is not None and max_y_span <= 0:
        max_y_span = None

    result = build_density(
        index_path=args.index,
        categories_path=args.categories,
        out_json=args.out_json,
        out_meta=args.out_meta,
        out_report=args.out_report,
        cell_size=args.cell_size,
        min_cell_slots=args.min_cell_slots,
        min_cluster_size=args.min_cluster_size,
        merge_gap_cells=args.merge_gap_cells,
        merge_adjacent_hot_cells=args.merge_adjacent_hot_cells,
        max_cluster_span=max_span,
        max_cluster_y_span=max_y_span,
        map_filter=args.map_filter,
    )
    print(
        f"density: clusters={result['cluster_count']} "
        f"constrained_slots={result['constrained_slot_count']}"
    )
    print(f"Wrote {result['out_json']}")
    print(f"Wrote {result['out_meta']}")
    print(f"Wrote {result['out_report']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
