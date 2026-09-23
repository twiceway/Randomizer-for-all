"""T-084 R1 — shared helpers for bundle / slot_tags / compat export scripts."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from paths import SCRIPT_DIR  # frozen-safe (data/cnv_randomizer)
INDEX_PATH = SCRIPT_DIR / "cache" / "enemy_index.json"
WHITELIST_PATH = (
    SCRIPT_DIR.parent / "捐皮契约" / "捐皮白名单_当前.json"
)
RULE_VERSION = 1


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def file_fingerprint(path: Path) -> str:
    if not path.is_file():
        return "missing"
    data = path.read_bytes()
    return hashlib.sha256(data).hexdigest()[:16]


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def load_enemy_index(path: Path | None = None) -> dict[str, Any]:
    path = path or INDEX_PATH
    if not path.is_file():
        raise FileNotFoundError(f"missing enemy index: {path}")
    return load_json(path)


def slot_key(slot: dict[str, Any]) -> str:
    return f"{slot.get('map_id', '')}:{slot.get('name', '')}"


def split_slot_key(key: str) -> tuple[str, str]:
    if ":" in key:
        map_id, name = key.split(":", 1)
        return map_id, name
    return "", key


def build_slot_lookup(slots: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (str(s.get("map_id", "")), str(s.get("name", ""))): s for s in slots
    }


def export_meta(
    *,
    extra_fingerprints: dict[str, str] | None = None,
) -> dict[str, Any]:
    fps = {
        "enemy_index": file_fingerprint(INDEX_PATH),
        "whitelist": file_fingerprint(WHITELIST_PATH),
    }
    if extra_fingerprints:
        fps.update(extra_fingerprints)
    return {
        "rule_version": RULE_VERSION,
        "generated_at": utc_now_iso(),
        "inputs_fingerprint": fps,
    }


def write_cache_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def iter_whitelist_bundle_rows(
    index: dict[str, Any],
    categories_cfg: dict[str, Any],
) -> list[dict[str, Any]]:
    """One bundle row per contract whitelist entry with resolved template."""
    from gatefront_quad_catalog import (
        _resolve_whitelist_donor_template,
        iter_contract_whitelist_rows,
        load_npc_english_names,
    )
    from _export_donor_msb_state import donor_row

    catalog = list(index.get("templates") or [])
    slot_lookup = build_slot_lookup(list(index.get("slots") or []))
    names = load_npc_english_names()
    rows: list[dict[str, Any]] = []
    for wl in iter_contract_whitelist_rows():
        tpl = _resolve_whitelist_donor_template(wl, catalog, categories_cfg)
        try:
            npc = int(wl.get("npc") or 0)
        except (TypeError, ValueError):
            npc = 0
        base = {
            "pool": int(wl.get("pool") or 0),
            "category": str(wl.get("category") or ""),
            "npc": npc,
            "model": str(wl.get("model") or "").lower(),
            "name_en": str(wl.get("name_en") or "").strip(),
            "name_zh": str(wl.get("name_zh") or ""),
        }
        if tpl is None:
            rows.append(
                {
                    **base,
                    "bundle_id": "",
                    "resolve_ok": False,
                }
            )
            continue
        dr = donor_row(tpl, slot_lookup)
        tid = str(dr.get("template_id") or "")
        rows.append(
            {
                **base,
                "name_en": base["name_en"] or names.get(npc, ""),
                "bundle_id": tid,
                "resolve_ok": bool(tid),
                "template": tpl,
                "donor_row": dr,
            }
        )
    return rows
