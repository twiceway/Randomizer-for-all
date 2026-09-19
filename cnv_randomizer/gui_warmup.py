"""Background preload for GUI idle time (index / prep / pickup CSV)."""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Callable

_warmup_started = False
_warmup_lock = threading.Lock()


def start_background_warmup(
    *,
    game_dir: Path | None,
    cfg: dict[str, Any] | None = None,
    log_fn: Callable[[str], None] | None = None,
) -> bool:
    """Daemon thread: preload heavy read-only caches before user clicks generate."""
    global _warmup_started
    with _warmup_lock:
        if _warmup_started:
            return False
        _warmup_started = True

    def _log(msg: str) -> None:
        if log_fn is not None:
            try:
                log_fn(msg)
            except Exception:
                pass

    def _worker() -> None:
        from mod_install import is_mod_installed
        from paths import resolve_game_dir

        t0 = time.perf_counter()
        stats: dict[str, str] = {}
        try:
            gdir = game_dir or resolve_game_dir()
        except Exception as exc:
            _log(f"warmup_skip game_dir={exc}")
            return
        if not gdir.is_dir() or not is_mod_installed(gdir):
            _log("warmup_skip mod_not_installed")
            return

        try:
            from enemy_index_pipeline import load_enemy_index

            load_enemy_index()
            stats["index"] = "ok"
        except Exception as exc:
            stats["index"] = f"err:{exc}"

        try:
            from enemy_slot_prep import load_slot_prep, load_slot_prep_if_valid, prep_meta

            dlc_mode = str((cfg or {}).get("enemy_gui", {}).get("dlc_pool_mode", "mixed"))
            meta = prep_meta(dlc_pool_mode=dlc_mode)
            prep_path = load_slot_prep_if_valid(meta=meta)
            if prep_path is None:
                load_slot_prep(meta=meta)
            stats["prep"] = "ok"
        except Exception as exc:
            stats["prep"] = f"err:{exc}"

        try:
            from cnv_randomizer_core import _load_pickup_csv_bundle

            csv_dir = gdir / "csv"
            if csv_dir.is_dir():
                _load_pickup_csv_bundle(csv_dir)
                stats["items_csv"] = "ok"
            else:
                stats["items_csv"] = "missing"
        except Exception as exc:
            stats["items_csv"] = f"err:{exc}"

        try:
            from donor_msb_compat import load_donor_slot_compat
            from enemy_randomizer_core import DEFAULT_CATEGORIES_PATH, load_archetype_index
            import json

            load_donor_slot_compat()
            if DEFAULT_CATEGORIES_PATH.is_file():
                cats = json.loads(DEFAULT_CATEGORIES_PATH.read_text(encoding="utf-8-sig"))
                load_archetype_index(cats)
            stats["compat"] = "ok"
        except Exception as exc:
            stats["compat"] = f"err:{exc}"

        elapsed = round(time.perf_counter() - t0, 1)
        _log(
            "warmup_done "
            f"index={stats.get('index', 'skip')} "
            f"prep={stats.get('prep', 'skip')} "
            f"items_csv={stats.get('items_csv', 'skip')} "
            f"compat={stats.get('compat', 'skip')} "
            f"elapsed={elapsed}s"
        )

    threading.Thread(target=_worker, name="cnv-gui-warmup", daemon=True).start()
    return True
