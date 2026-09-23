"""Sanitize NpcThinkParam picks for cross-model donor swaps (vision / infinite chase)."""

from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path
from typing import Any

from paths import GAME_DIR

DEFAULT_FIELD_THINK_ID = 30_200_000
THINK_COPY_ID_BASE = 890_000_000
THINK_FAMILY_EXEMPT_MODELS = frozenset({"c0000"})

_DEFAULT_CSV_DIR_STR: str | None = None


def resolve_think_csv_dir_str(csv_dir: Path | str | None = None) -> str:
    """Stable str key for _load_think_rows (avoid per-call LazyGamePath / Path churn)."""
    if csv_dir is not None:
        return str(Path(csv_dir))
    global _DEFAULT_CSV_DIR_STR
    if _DEFAULT_CSV_DIR_STR is None:
        _DEFAULT_CSV_DIR_STR = str(GAME_DIR / "csv")
    return _DEFAULT_CSV_DIR_STR


def warm_think_csv_cache(csv_dir: Path | str | None = None) -> None:
    """Eager-load NpcThinkParam rows once per process (scan-phase hot path)."""
    _load_think_rows(resolve_think_csv_dir_str(csv_dir))


def _default_sanitize_cfg() -> dict[str, Any]:
    return {
        "enabled": True,
        "max_eye_dist": 35,
        "max_search_eye_dist": 25,
        "max_sight_forget_time": 20.0,
        "max_backhome_dist": 45,
        "max_backhome_battle_dist": 80,
        "max_ear_dist": 5.0,
        "max_nose_dist": 25,
        "default_field_think_id": DEFAULT_FIELD_THINK_ID,
        "preserve_think_prefixes": ["4200", "4260"],
        "explicit_remap": {
            "31810933": 31810000,
            "31810932": 31810000,
        },
    }


def think_sanitize_config(categories_cfg: dict[str, Any] | None) -> dict[str, Any]:
    raw = (categories_cfg or {}).get("donor_think_sanitize") or {}
    cfg = _default_sanitize_cfg()
    cfg.update(
        {
            k: v
            for k, v in raw.items()
            if k not in ("explicit_remap", "preserve_think_prefixes")
        }
    )
    remap = dict(cfg.get("explicit_remap") or {})
    remap.update({str(k): int(v) for k, v in (raw.get("explicit_remap") or {}).items()})
    cfg["explicit_remap"] = remap
    prefixes = list(cfg.get("preserve_think_prefixes") or [])
    prefixes.extend(str(p) for p in (raw.get("preserve_think_prefixes") or []))
    cfg["preserve_think_prefixes"] = prefixes
    return cfg


def is_preserved_think(think_id: int, categories_cfg: dict[str, Any] | None = None) -> bool:
    """True when think id matches preserve_think_prefixes (e.g. 4260* watchdog)."""
    cfg = think_sanitize_config(categories_cfg)
    return _is_preserved_think(think_id, cfg)


def _is_preserved_think(think_id: int, cfg: dict[str, Any]) -> bool:
    key = str(int(think_id))
    for prefix in cfg.get("preserve_think_prefixes") or []:
        if key.startswith(str(prefix)):
            return True
    return False


@lru_cache(maxsize=4)
def _load_think_rows(csv_dir: str) -> dict[int, dict[str, str]]:
    path = Path(csv_dir) / "NpcThinkParam.csv"
    if not path.is_file():
        return {}
    rows: dict[int, dict[str, str]] = {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            try:
                rows[int(row["ID"])] = row
            except (KeyError, TypeError, ValueError):
                continue
    return rows


def _fval(row: dict[str, str], key: str, default: float = 0.0) -> float:
    try:
        return float(row.get(key) or default)
    except (TypeError, ValueError):
        return default


def is_extreme_think(
    think_id: int,
    cfg: dict[str, Any],
    *,
    csv_dir: Path | str | None = None,
) -> bool:
    """True when AI row exceeds field-mob vision / chase leash (summon/Boss scripts)."""
    if think_id <= 0:
        return True
    if _is_preserved_think(think_id, cfg):
        return False
    base = resolve_think_csv_dir_str(csv_dir)
    row = _load_think_rows(base).get(int(think_id))
    if not row:
        return True
    if _fval(row, "eye_dist") > float(cfg["max_eye_dist"]):
        return True
    if _fval(row, "searchEye_dist") > float(cfg["max_search_eye_dist"]):
        return True
    if _fval(row, "SightTargetForgetTime") > float(cfg["max_sight_forget_time"]):
        return True
    if _fval(row, "maxBackhomeDist") > float(cfg["max_backhome_dist"]):
        return True
    if _fval(row, "backhomeBattleDist") > float(cfg["max_backhome_battle_dist"]):
        return True
    if _fval(row, "ear_dist") > float(cfg["max_ear_dist"]):
        return True
    if _fval(row, "nose_dist") > float(cfg["max_nose_dist"]):
        return True
    return False


def _apply_remap(think_id: int, cfg: dict[str, Any]) -> int:
    remap = cfg.get("explicit_remap") or {}
    if think_id in remap:
        return int(remap[think_id])
    key = str(think_id)
    if key in remap:
        return int(remap[key])
    return think_id


def _first_sane_think(
    candidates: list[int],
    cfg: dict[str, Any],
    *,
    csv_dir: Path | str | None = None,
) -> int | None:
    seen: set[int] = set()
    for raw in candidates:
        if raw <= 0:
            continue
        tid = _apply_remap(int(raw), cfg)
        if tid in seen:
            continue
        seen.add(tid)
        if not is_extreme_think(tid, cfg, csv_dir=csv_dir):
            return tid
    return None


def infer_think_from_npc(npc: int) -> int:
    """MSB 常见：think 与 npc 同族，末两位常为 00。"""
    if npc <= 0:
        return 0
    if npc % 100 == 0:
        return npc
    return (npc // 100) * 100


def is_runtime_think_copy_id(think_id: int) -> bool:
    return int(think_id) >= THINK_COPY_ID_BASE


def think_param_has_id(think_id: int, *, csv_dir: Path | str | None = None) -> bool:
    """True when NpcThinkParam has this id. Empty CSV → fail-open（本机无表时不拦）。"""
    if think_id <= 0:
        return False
    if is_runtime_think_copy_id(think_id):
        return True
    base = resolve_think_csv_dir_str(csv_dir)
    rows = _load_think_rows(base)
    if not rows:
        return True
    return int(think_id) in rows


def first_existing_think_for_model(
    model: str,
    *,
    csv_dir: Path | str | None = None,
) -> int:
    """同皮编号族里第一个有行的 think；优先 *0000。无表则 0。"""
    model_l = str(model or "").strip().lower()
    if not model_l:
        return 0
    base = resolve_think_csv_dir_str(csv_dir)
    rows = _load_think_rows(base)
    if not rows:
        return 0
    hits = [
        i
        for i in rows
        if i > 0
        and not is_runtime_think_copy_id(i)
        and think_matches_model_family(model_l, i)
    ]
    if not hits:
        return 0
    zeros = [i for i in hits if i % 10_000 == 0]
    return min(zeros) if zeros else min(hits)


def think_matches_model_family(
    model: str,
    think_id: int,
    *,
    exempt_models: frozenset[str] | None = None,
) -> bool:
    """T-083：spawn 写入 think 编号族须与皮 model 一致（890M 复制行 / c0000 占位除外）。"""
    if think_id <= 0:
        return True
    if is_runtime_think_copy_id(think_id):
        return True
    model_l = str(model or "").strip().lower()
    if not model_l:
        return True
    exempt = exempt_models if exempt_models is not None else THINK_FAMILY_EXEMPT_MODELS
    if model_l in exempt:
        return True
    m = model_l.lstrip("c")
    if not m:
        return True
    ts = str(int(think_id))
    return ts.startswith(m) or (len(m) == 4 and ts.startswith(m[:3]))


def resolve_safe_think(
    *,
    donor_think: int,
    npc: int,
    categories_cfg: dict[str, Any] | None = None,
    csv_dir: Path | str | None = None,
) -> int:
    """Pick a field-mob-safe NpcThink id for cross-model donor swaps."""
    cfg = think_sanitize_config(categories_cfg)
    if not cfg.get("enabled", True):
        if donor_think > 0:
            return donor_think
        return infer_think_from_npc(npc)

    inferred = infer_think_from_npc(npc)
    default_id = int(cfg.get("default_field_think_id") or DEFAULT_FIELD_THINK_ID)
    picked = _first_sane_think(
        [donor_think, inferred, default_id],
        cfg,
        csv_dir=csv_dir,
    )
    if picked is not None:
        return picked
    return inferred or donor_think or default_id
