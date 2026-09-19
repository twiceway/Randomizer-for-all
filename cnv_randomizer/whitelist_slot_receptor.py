"""T-081 — whitelist donor × map slot receptor buckets (shared export + tests).

T-084 R5：`cache/whitelist_donor_slot_receptor.json` 仅 reports 对账 / 导出审阅；
generate / prep pick **不**加载该缓存（`whitelist_receptor_index` 恒为空）。
`classify_receptor_bucket` 仍供槽位指纹与 MSB compat 用（非反扫表 pick）。
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from _export_slot_initial_state import (
    AERIAL_PREFIXES,
    SCRIPTED_FLYER_PREFIXES,
    _pref,
    apply_slot_class,
)
from donor_msb_compat import (
    compat_cache_fingerprint,
    compat_entry_for_template,
    donor_slot_compat_reject_reason,
    load_donor_slot_compat,
)

from paths import SCRIPT_DIR  # frozen-safe (data/cnv_randomizer)
DEFAULT_RECEPTOR_CACHE = SCRIPT_DIR / "cache" / "whitelist_donor_slot_receptor.json"

BUCKET_SCHEMA = 1
RULE_VERSION = 2
# T-085：产物升格为「历史状态表」；机读首字段 historical_states（= vanilla_supported_buckets）
HISTORICAL_SCHEMA = 1
PRODUCT_NAME = "donor_historical_states"

BUCKET_IDS: tuple[str, ...] = (
    "patrol",
    "script_chr_activate",
    "aerial_slot",
    "sit_squat",
    "collision_perch",
    "ground_stand",
)


def historical_states_from_compat(compat: dict[str, Any] | None) -> list[str]:
    """T-085 历史状态列表 · 真源 = T-080 vanilla_supported_buckets（桶序固定）。"""
    entry = compat or {}
    supported = entry.get("vanilla_supported_buckets") or []
    if not isinstance(supported, list):
        return []
    have = {str(x) for x in supported if str(x).strip()}
    return [bid for bid in BUCKET_IDS if bid in have]


def historical_state_counts_from_compat(
    compat: dict[str, Any] | None,
) -> dict[str, int]:
    """同 model 全图原版各桶出现次数（审计用）。"""
    entry = compat or {}
    totals = entry.get("vanilla_bucket_totals") or {}
    if not isinstance(totals, dict):
        totals = {}
    return {bid: int(totals.get(bid) or 0) for bid in BUCKET_IDS}


def empty_bucket_counts() -> dict[str, dict[str, int]]:
    return {bid: {"total": 0, "allowed": 0, "blocked": 0} for bid in BUCKET_IDS}


def classify_receptor_bucket(slot: dict[str, Any]) -> str:
    """T-081 §3.1 — mutually exclusive bucket for target slot MSB.

    T-089：配对全局不再使用 script_chr_activate（chr_activate 仍供写出飞巡识别）。
    """
    walk = str(slot.get("walk_route") or "").strip()
    if walk:
        return "patrol"
    # T-089：跳过「chr_activate → script_chr_activate」配对分支
    model = str(slot.get("model", ""))
    if _pref(model, AERIAL_PREFIXES) or _pref(model, SCRIPTED_FLYER_PREFIXES):
        return "aerial_slot"
    backup = int(slot.get("backup_anim", -1) or -1)
    if backup > 0:
        return "sit_squat"
    collision = str(slot.get("collision_part") or "").strip()
    if collision:
        return "collision_perch"
    return "ground_stand"


@dataclass
class ScannedSlot:
    bucket_id: str
    pick_eligible: bool
    apply_class: str
    slot: dict[str, Any]


@dataclass
class SlotScanResult:
    slots: list[ScannedSlot] = field(default_factory=list)
    bucket_totals_all_msb: dict[str, int] = field(default_factory=dict)
    bucket_totals_pick_eligible: dict[str, int] = field(default_factory=dict)

    @property
    def all_msb_total(self) -> int:
        return len(self.slots)

    @property
    def pick_eligible_total(self) -> int:
        return sum(1 for s in self.slots if s.pick_eligible)


def scan_map_slots(
    index_slots: list[dict[str, Any]],
    *,
    categories_cfg: dict[str, Any],
    npc_csv_dir: Path,
) -> SlotScanResult:
    import enemy_randomizer_core as core

    result = SlotScanResult()
    bucket_all: Counter[str] = Counter()
    bucket_pick: Counter[str] = Counter()

    for slot in index_slots:
        bucket_id = classify_receptor_bucket(slot)
        policy = core.describe_slot_policy(
            slot,
            categories_cfg,
            npc_csv_dir=npc_csv_dir,
        )
        pick_eligible = policy.get("policy") == "participate"
        result.slots.append(
            ScannedSlot(
                bucket_id=bucket_id,
                pick_eligible=pick_eligible,
                apply_class=apply_slot_class(slot),
                slot=slot,
            )
        )
        bucket_all[bucket_id] += 1
        if pick_eligible:
            bucket_pick[bucket_id] += 1

    result.bucket_totals_all_msb = {bid: int(bucket_all.get(bid, 0)) for bid in BUCKET_IDS}
    result.bucket_totals_pick_eligible = {
        bid: int(bucket_pick.get(bid, 0)) for bid in BUCKET_IDS
    }
    return result


def _aggregate_scope(
    scanned: SlotScanResult,
    template_id: str,
    compat_by_tid: dict[str, dict[str, Any]],
    *,
    pick_eligible_only: bool,
) -> tuple[dict[str, dict[str, int]], list[dict[str, Any]]]:
    buckets = empty_bucket_counts()
    reason_ctr: Counter[str] = Counter()

    for entry in scanned.slots:
        if pick_eligible_only and not entry.pick_eligible:
            continue
        bid = entry.bucket_id
        buckets[bid]["total"] += 1
        reason = donor_slot_compat_reject_reason(
            entry.slot,
            template_id,
            compat_by_tid,
        )
        if reason:
            buckets[bid]["blocked"] += 1
            reason_ctr[reason] += 1
        else:
            buckets[bid]["allowed"] += 1

    blocked_top = [
        {"reason": reason, "count": count}
        for reason, count in reason_ctr.most_common(5)
    ]
    return buckets, blocked_top


def aggregate_donor_receptor(
    scanned: SlotScanResult,
    template_id: str,
    compat_by_tid: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    cache = compat_by_tid if compat_by_tid is not None else load_donor_slot_compat()
    all_msb, blocked_all = _aggregate_scope(
        scanned, template_id, cache, pick_eligible_only=False
    )
    pick_eligible, blocked_pick = _aggregate_scope(
        scanned, template_id, cache, pick_eligible_only=True
    )
    compat = compat_entry_for_template(template_id, cache)
    historical = historical_states_from_compat(compat)
    return {
        # T-085 首字段：配对允许/拒绝只认此并集（矩阵仍另管抽池）
        "historical_states": historical,
        "historical_state_counts": historical_state_counts_from_compat(compat),
        "vanilla_scan_model": str(compat.get("vanilla_scan_model") or ""),
        "vanilla_occurrence_total": int(compat.get("vanilla_occurrence_total") or 0),
        "receptor_all_msb": all_msb,
        "receptor_pick_eligible": pick_eligible,
        "blocked_reason_top_all_msb": blocked_all,
        "blocked_reason_top_pick_eligible": blocked_pick,
        "donor_side": {
            "force_donor_msb": bool(compat.get("force_donor_msb")),
            "compat_patrol_keep": bool(compat.get("compat_patrol_keep", True)),
            "compat_standing_keep": bool(compat.get("compat_standing_keep", True)),
            "donor_pose_label": str(compat.get("donor_pose_label") or ""),
            "donor_walk_route": str(compat.get("donor_walk_route") or "").strip(),
        },
    }


def receptor_fingerprint(
    *,
    whitelist_path: Path,
    index_generated_at: str,
    compat_cache_path: Path | None = None,
) -> str:
    wl_digest = hashlib.sha256(whitelist_path.read_bytes()).hexdigest()[:16]
    compat_fp = compat_cache_fingerprint(cache_path=compat_cache_path)
    return (
        f"wl={wl_digest}|idx={index_generated_at}|compat={compat_fp}"
        f"|rule={RULE_VERSION}|bucket_schema={BUCKET_SCHEMA}"
        f"|historical_schema={HISTORICAL_SCHEMA}"
    )


def donor_allowed_matches_export(
    slot: dict[str, Any],
    template_id: str,
    compat_by_tid: dict[str, dict[str, Any]] | None = None,
) -> bool:
    """Single source: reject_reason is None ↔ allowed."""
    return (
        donor_slot_compat_reject_reason(slot, template_id, compat_by_tid) is None
    )


def slot_scan_summary_dict(scan: SlotScanResult) -> dict[str, Any]:
    return {
        "all_msb_total": scan.all_msb_total,
        "pick_eligible_total": scan.pick_eligible_total,
        "bucket_totals_all_msb": dict(scan.bucket_totals_all_msb),
        "bucket_totals_pick_eligible": dict(scan.bucket_totals_pick_eligible),
    }


_RECEPTOR_PAYLOAD_CACHE: tuple[str, dict[str, Any]] | None = None
_RECEPTOR_INDEX_CACHE: tuple[str, dict[str, dict[str, Any]]] | None = None


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def receptor_fast_reject(donor_row: dict[str, Any], bucket_id: str) -> bool:
    """True when T-081 pre-scan says zero allowed slots in this bucket (pick_eligible)."""
    cell = (donor_row.get("receptor_pick_eligible") or {}).get(bucket_id) or {}
    total = int(cell.get("total") or 0)
    allowed = int(cell.get("allowed") or 0)
    return total > 0 and allowed == 0


def load_whitelist_receptor_payload(
    cache_path: Path | None = None,
) -> dict[str, Any]:
    global _RECEPTOR_PAYLOAD_CACHE
    path = cache_path or DEFAULT_RECEPTOR_CACHE
    if not path.is_file():
        _RECEPTOR_PAYLOAD_CACHE = ("missing", {})
        return {}
    try:
        raw = _load_json(path)
    except (OSError, json.JSONDecodeError):
        _RECEPTOR_PAYLOAD_CACHE = ("bad", {})
        return {}
    fp = str(raw.get("fingerprint") or "bad")
    if _RECEPTOR_PAYLOAD_CACHE is not None and _RECEPTOR_PAYLOAD_CACHE[0] == fp:
        return _RECEPTOR_PAYLOAD_CACHE[1]
    _RECEPTOR_PAYLOAD_CACHE = (fp, raw)
    return raw


def load_whitelist_receptor_index(
    cache_path: Path | None = None,
) -> dict[str, dict[str, Any]]:
    """template_id → donor row from T-081 export."""
    global _RECEPTOR_INDEX_CACHE
    payload = load_whitelist_receptor_payload(cache_path)
    fp = str(payload.get("fingerprint") or "missing")
    if _RECEPTOR_INDEX_CACHE is not None and _RECEPTOR_INDEX_CACHE[0] == fp:
        return _RECEPTOR_INDEX_CACHE[1]
    index: dict[str, dict[str, Any]] = {}
    for row in payload.get("donors") or []:
        tid = str(row.get("template_id") or "").strip()
        if tid:
            index[tid] = row
    _RECEPTOR_INDEX_CACHE = (fp, index)
    return index


def whitelist_receptor_stale_warn(
    cache_path: Path | None = None,
) -> str | None:
    """None if OK; else human-readable warn (pick/prep logs)."""
    from donor_msb_compat import compat_cache_fingerprint

    path = cache_path or DEFAULT_RECEPTOR_CACHE
    if not path.is_file():
        return "缺少白名单槽位反扫缓存，请运行 export_whitelist_donor_slot_receptor.py"
    payload = load_whitelist_receptor_payload(path)
    if not payload:
        return "白名单槽位反扫缓存损坏，请重跑 export_whitelist_donor_slot_receptor.py"
    stored_compat = str(payload.get("compat_fingerprint") or "")
    current_compat = compat_cache_fingerprint()
    if stored_compat and stored_compat != current_compat:
        return (
            "白名单槽位反扫缓存与 donor_slot_compat 不同步"
            f"（cache={stored_compat[:24]}… current={current_compat[:24]}…）"
        )
    return None


def load_index_slots(index_path: Path) -> tuple[list[dict[str, Any]], str]:
    raw = _load_json(index_path)
    generated_at = str(raw.get("generated_at") or "")
    return list(raw.get("slots") or []), generated_at
