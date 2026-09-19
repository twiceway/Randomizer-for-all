"""Patch 有效HP / HP倍率 in donor-pool markdown tables (pools 1-7)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import enemy_randomizer_core as core  # noqa: E402
from boss_npc_detect import load_npc_rows  # noqa: E402
from dlc_donor_pool import load_sp_hp_rates, npc_effective_hp_for_review  # noqa: E402

REPO = SCRIPT_DIR.parent
DONOR_ROOT = REPO / "捐池_原槽表"
FILTERED = DONOR_ROOT / "筛选后捐池表"
EXCLUDE_DIR = DONOR_ROOT / "筛选后槽表"
POOL_MD = re.compile(r"捐皮池表_池([1-7])")


def _header_indices(header_line: str) -> dict[str, int] | None:
    parts = [p.strip() for p in header_line.split("|")]
    if len(parts) < 3 or parts[1] not in ("序号", "序號"):
        return None
    idx: dict[str, int] = {}
    for i, name in enumerate(parts):
        if name in ("model", "npc", "有效HP", "HP倍率"):
            idx[name] = i
    if "npc" not in idx or "有效HP" not in idx:
        return None
    return idx


def _target_pool(path: Path) -> int | None:
    m = POOL_MD.search(path.name)
    if m:
        return int(m.group(1))
    if path.name == "捐皮池表_1-7.md":
        return 0
    return None


def patch_file(path: Path, npc_rows: dict, sp_rates: dict, *, pool_min: int = 2) -> tuple[int, int]:
    pool = _target_pool(path)
    if pool is None or (pool_min > 0 and pool != 0 and pool < pool_min):
        return 0, 0
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    header_idx: dict[str, int] | None = None
    changed = 0
    scanned = 0
    out: list[str] = []
    for line in lines:
        if header_idx is None and line.startswith("|") and "序号" in line.split("|")[1]:
            header_idx = _header_indices(line)
            out.append(line)
            continue
        if header_idx is None or not line.startswith("|"):
            out.append(line)
            continue
        parts = line.split("|")
        if len(parts) <= max(header_idx.values()):
            out.append(line)
            continue
        try:
            int(parts[1].strip())
        except ValueError:
            out.append(line)
            continue
        npc_raw = parts[header_idx["npc"]].strip()
        try:
            npc = int(npc_raw)
        except ValueError:
            out.append(line)
            continue
        model = parts[header_idx["model"]].strip() if "model" in header_idx else ""
        scanned += 1
        hp_info = npc_effective_hp_for_review(
            npc,
            npc_rows.get(npc),
            model=model,
            sp_rates=sp_rates,
            npc_by_id=npc_rows,
        )
        new_hp = str(int(hp_info.get("effective_hp") or 0))
        new_mult = str(hp_info.get("hp_mult_desc") or "")
        old_hp = parts[header_idx["有效HP"]].strip()
        mult_i = header_idx.get("HP倍率")
        old_mult = parts[mult_i].strip() if mult_i is not None else ""
        if old_hp != new_hp or (mult_i is not None and old_mult != new_mult):
            parts[header_idx["有效HP"]] = f" {new_hp} "
            if mult_i is not None:
                parts[mult_i] = f" {new_mult} "
            changed += 1
            line = "|".join(parts)
        out.append(line)
    if changed:
        path.write_text("\n".join(out) + ("\n" if text.endswith("\n") else ""), encoding="utf-8")
    return scanned, changed


def main() -> None:
    npc_csv_dir = core.GAME_DIR / "csv"
    npc_rows = load_npc_rows(npc_csv_dir)
    sp_rates = load_sp_hp_rates(str(npc_csv_dir))
    targets: list[Path] = []
    for d in (FILTERED, DONOR_ROOT, EXCLUDE_DIR):
        if not d.is_dir():
            continue
        for path in sorted(d.glob("*.md")):
            if path.name.endswith("索引.md"):
                continue
            if _target_pool(path) is not None:
                targets.append(path)
    # 筛选后全池（含池1）；去重后留下的模板×1 行需靠同底 peer 回填
    total_changed = 0
    filtered_targets = [p for p in targets if "筛选后" in str(p)]
    for path in filtered_targets:
        scanned, changed = patch_file(path, npc_rows, sp_rates, pool_min=1)
        if changed:
            rel = path.relative_to(REPO)
            print(f"{rel}: {changed}/{scanned} rows updated")
            total_changed += changed
    print(f"done: {total_changed} row(s) patched in filtered pool tables ({len(filtered_targets)} files)")


if __name__ == "__main__":
    main()
