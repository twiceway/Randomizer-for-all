"""DLC donor pool helpers — combat HP + m61 manifest."""

from __future__ import annotations

import csv
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from paths import SCRIPT_DIR  # frozen-safe (data/cnv_randomizer)
DEFAULT_MANIFEST = SCRIPT_DIR / "m61_dlc_donor_pool.json"
DEFAULT_GAME_CSV = Path(r"V:/games/Elden Ring/Game/csv")

M61_EXCLUDE_PREFIXES = frozenset({"c5401", "c5410", "c5450", "c5240", "c5490"})
SKIP_PREFIXES = frozenset({"c0000", "c1000", "c3661"})
# 用户 2026-07-31：狂龙贝勒体型过大，永不捐皮；c6201 DLC 圣甲虫原位不捐
NEVER_DONOR_PREFIXES = frozenset({
    "c5120",
    "c6201",
    "c5230",
    "c5390",
    "c5391",
    "c5392",
    "c4500",
    "c4501",
    "c4502",
    "c4503",
    "c4504",
    "c4505",
    "c4510",
    "c4511",
    "c4520",
    "c4530",
    "c4690",
    "c5370",
    "c5580",
    "c5581",
    "c5661",
    "c5662",
})
MIN_TRASH_COMBAT_HP = 1000
MIN_BOSS_COMBAT_HP = 500
BOSS_TARGET_CATEGORIES = frozenset(
    {"major_boss", "minor_boss", "evergaol", "cnv_special", "night"}
)
# m61 实地 Boss：检测器漏判时强制归类（2~7 池 category）
FORCE_M61_BOSS_CATEGORY: dict[str, str] = {
    "c5210": "minor_boss",  # 神兽舞狮
    "c5300": "minor_boss",  # 双月骑士蕾菈娜
    "c5320": "evergaol",  # 老将盖乌斯
    "c5030": "major_boss",  # 花蕾圣女萝蜜娜
    "c5370": "evergaol",  # 古龙瑟涅桑克斯
    "c5661": "evergaol",  # 腐烂灵龙
    "c5580": "minor_boss",  # 咒剑士拉比卡士
    "c5690": "minor_boss",  # 孤牢骑士
    "c5850": "minor_boss",  # 哀恸者
    "c6310": "evergaol",  # 黄金河马
}
M61_BOSS_ZH: dict[str, str] = {
    "c5210": "神兽舞狮",
    "c5300": "双月骑士蕾菈娜",
    "c5320": "老将盖乌斯",
    "c5030": "花蕾圣女萝蜜娜",
    "c5370": "古龙瑟涅桑克斯",
    "c5661": "腐烂灵龙",
    "c5580": "咒剑士拉比卡士",
    "c5690": "孤牢骑士",
    "c5850": "哀恸者",
    "c6310": "黄金河马",
}


_SP_HP_RATES_BY_CSV: dict[str, dict[str, float]] = {}
_DEFAULT_SP_HP_RATES: dict[str, float] | None = None


def load_sp_hp_rates(csv_dir: str | Path | None = None) -> dict[str, float]:
    global _DEFAULT_SP_HP_RATES
    if csv_dir is None and _DEFAULT_SP_HP_RATES is not None:
        return _DEFAULT_SP_HP_RATES
    base = Path(csv_dir) if csv_dir else DEFAULT_GAME_CSV
    if hasattr(base, "_resolved"):
        try:
            base = base._resolved()
        except FileNotFoundError:
            pass
    key = str(base)
    cached = _SP_HP_RATES_BY_CSV.get(key)
    if cached is not None:
        if csv_dir is None:
            _DEFAULT_SP_HP_RATES = cached
        return cached
    rates: dict[str, float] = {}
    path = base / "SpEffectParam.csv"
    if not path.is_file():
        _SP_HP_RATES_BY_CSV[key] = rates
        if csv_dir is None:
            _DEFAULT_SP_HP_RATES = rates
        return rates
    with path.open(encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            sid = str(row.get("ID") or "").strip()
            if not sid:
                continue
            try:
                rate = float(row.get("maxHpRate") or 1.0)
            except (TypeError, ValueError):
                rate = 1.0
            if rate != 1.0:
                rates[sid] = rate
    _SP_HP_RATES_BY_CSV[key] = rates
    if csv_dir is None:
        _DEFAULT_SP_HP_RATES = rates
    return rates


def model_prefix_from_npc(npc: int) -> str:
    if npc <= 0:
        return ""
    return f"c{npc // 10000}"


def combat_hp_detailed(
    npc_row: dict[str, str] | None,
    sp_rates: dict[str, float] | None = None,
) -> tuple[int, float, list[tuple[str, float]]]:
    if not npc_row:
        return 0, 1.0, []
    sp_rates = sp_rates if sp_rates is not None else load_sp_hp_rates()
    try:
        base = int(npc_row.get("hp") or 0)
    except (TypeError, ValueError):
        base = 0
    if base <= 0:
        return 0, 1.0, []
    mult = 1.0
    parts: list[tuple[str, float]] = []
    for key, val in npc_row.items():
        if not key.startswith("spEffectID"):
            continue
        sid = str(val or "").strip()
        if sid in ("", "0", "-1"):
            continue
        rate = sp_rates.get(sid)
        if rate is None or rate == 1.0:
            continue
        mult *= rate
        parts.append((sid, rate))
    parts.sort(key=lambda x: -x[1])
    return max(1, int(round(base * mult))), mult, parts


def fmt_hp_mult(parts: list[tuple[str, float]], total: float) -> str:
    if not parts:
        return "×1"
    if len(parts) == 1:
        sid, rate = parts[0]
        return f"{sid}×{rate:g}"
    head = "×".join(f"{sid}×{r:g}" for sid, r in parts[:2])
    if len(parts) > 2:
        head += f"…({len(parts)}项)"
    return f"{head}→×{total:.3g}"


def _model_family_id(model: str) -> int:
    prefix = str(model or "").lower()
    if not prefix.startswith("c") or len(prefix) < 5:
        return 0
    try:
        return int(prefix[1:5])
    except (TypeError, ValueError):
        return 0


def _npc_in_model_family(nid: int, family: int) -> bool:
    if family <= 0:
        return False
    if str(nid).startswith(str(family)):
        return True
    bucket = nid // 10000
    return bucket in (family, family + 1)


def _family_hp_fallback(
    family: int,
    npc_by_id: dict[int, dict[str, str]],
    sp_rates: dict[str, float],
) -> tuple[int, str, int] | None:
    """NpcParam 无此行时，用同 model 族最高有效 HP 代理（合成/自定义 npc id）。"""
    if family <= 0:
        return None
    families = [family]
    # c5392 等：4 位族号无缩放同伴时，回退到 539x 三位词干扫邻近皮
    if family >= 1000:
        stem = family // 10
        if stem > 0 and stem not in families:
            families.append(stem)
    best_eff = -1
    best_mult = ""
    best_nid = 0
    for fam in families:
        for nid, row in npc_by_id.items():
            if not _npc_in_model_family(nid, fam):
                continue
            eff, mult, parts = combat_hp_detailed(row, sp_rates)
            if eff <= 0 or eff <= best_eff:
                continue
            if mult <= 1.0:
                continue
            best_eff = eff
            best_mult = fmt_hp_mult(parts, mult)
            best_nid = nid
    if best_eff <= 0:
        return None
    return best_eff, f"{best_mult}~族{best_nid}", best_nid


def _same_base_hp_peer_fallback(
    npc: int,
    row: dict[str, str],
    model: str,
    npc_by_id: dict[int, dict[str, str]],
    sp_rates: dict[str, float],
) -> tuple[int, str, int] | None:
    """NpcParam 模板行（×1）：同 model 族 + 同基础 hp 的已缩放 npc 作审阅参考。"""
    try:
        base = int(row.get("hp") or 0)
    except (TypeError, ValueError):
        return None
    if base <= 0:
        return None
    family = _model_family_id(model)
    best_eff = -1
    best_mult = ""
    best_nid = 0
    for nid, peer in npc_by_id.items():
        if nid == npc:
            continue
        if family and not _npc_in_model_family(nid, family):
            continue
        try:
            if int(peer.get("hp") or 0) != base:
                continue
        except (TypeError, ValueError):
            continue
        eff, mult, parts = combat_hp_detailed(peer, sp_rates)
        if mult <= 1.0 or eff <= base:
            continue
        if eff > best_eff:
            best_eff = eff
            best_mult = fmt_hp_mult(parts, mult)
            best_nid = nid
    if best_eff <= 0:
        return None
    return best_eff, f"{best_mult}~同底{best_nid}", best_nid


# Boss 捐皮选行：×1 模板壳 → 同族已缩放 Boss 行（isSoulGetByBoss 仅 Boss 池允许）
DLC_BOSS_DONOR_NPC_PREFER: dict[str, int] = {
    "c6310": 63101093,  # 黄金河马；勿用 63100000（坠星兽 Base ×1 ≈3154）
    "c4370": 31810052,  # 拉达冈的红狼（合成 c4370 壳无 NpcParam 行）
    "c5011": 50100098,  # 黄金河马 Boss 行；勿用 50110000（×1 壳 1408）
    "c5320": 53200089,  # 肥胖拷问官已缩放；勿用 53200000（×1 壳 576）
    "c5193": 51920100,  # DLC 蜘蛛蝎壳；原版墓地蜘蛛蝎 Gravesite ~9700
}
# 百智爵士玩家壳 523240070（法魂剧情·1血）→ 合成百智皮 gideon_c5380（仅审阅 HP 代理；壳本身 exclude_slot+never_donor）
REVIEW_HP_PROXY_NPC: dict[int, int] = {
    523240070: 53800084,
    43700200: 31810052,  # 旧壳号遗留；现网白名单/合成模板已钉 31810052
    49800001: 49800000,  # 旧旁号遗留；现网白名单已钉 49800000
    51930094: 51920100,  # synthetic DLC c5193 蜘蛛蝎壳
    # synthetic_boss_templates 配置 npc 无 NpcParam 行 → T-052 复制基座
    48000010: 48000068,
    47300041: 47300040,
    52100080: 52100088,
    21300050: 21300033,
    45200010: 45200072,
    45100010: 45100072,
    35600010: 35600030,
    47200050: 47200070,
    46000030: 46000010,
    21000010: 21000034,
}


def resolve_valid_donor_npc(
    npc: int,
    model: str,
    npc_by_id: dict[int, dict[str, str]],
) -> int:
    """合成壳 npc 不在 NpcParam 时，解析为可克隆的实战行（卢恩 copy 前置）。"""
    try:
        nid = int(npc or 0)
    except (TypeError, ValueError):
        return 0
    if nid <= 0:
        return 0
    if nid in npc_by_id:
        return nid
    proxy = REVIEW_HP_PROXY_NPC.get(nid)
    if proxy and proxy in npc_by_id:
        return int(proxy)
    model_l = str(model or "").lower()
    pinned = DLC_BOSS_DONOR_NPC_PREFER.get(model_l)
    if pinned and pinned in npc_by_id:
        return int(pinned)
    prefix = model_l[1:] if model_l.startswith("c") and model_l[1:].isdigit() else ""
    if not prefix:
        return nid
    fam = int(prefix)
    candidates = [
        cand
        for cand in npc_by_id
        if cand // 1000 == fam or str(cand).startswith(prefix)
    ]
    if not candidates:
        return nid

    def _score(cand: int) -> tuple[int, int, int, int]:
        row = npc_by_id.get(cand) or {}
        try:
            gs = int(row.get("getSoul") or 0)
        except (TypeError, ValueError):
            gs = 0
        sp = sum(
            1
            for key, val in row.items()
            if key.startswith("spEffectID")
            and str(val or "0") not in ("0", "-1", "")
        )
        return (1 if gs > 0 else 0, sp, gs, -cand)

    return int(max(candidates, key=_score))


def is_synthetic_donor_template(tpl: dict[str, Any]) -> bool:
    return str(tpl.get("template_id") or "").startswith("synthetic:")


def build_vanilla_donor_npc_by_model(
    templates: list[dict[str, Any]],
    *,
    npc_by_id: dict[int, dict[str, str]],
    sp_rates: dict[str, float] | None = None,
) -> dict[str, dict[str, Any]]:
    """Per model: mean combat HP over map-scanned (non-synthetic) donor npc variants."""
    sp_rates = sp_rates if sp_rates is not None else load_sp_hp_rates()
    buckets: dict[str, dict[int, int]] = {}
    for tpl in templates:
        if is_synthetic_donor_template(tpl):
            continue
        model = str(tpl.get("model") or "").lower()
        if not model:
            continue
        try:
            npc = int(tpl.get("npc", 0) or 0)
        except (TypeError, ValueError):
            continue
        if npc <= 0:
            continue
        row = npc_by_id.get(npc)
        if not row:
            continue
        eff, mult, _parts = combat_hp_detailed(row, sp_rates)
        if eff <= 0 or mult <= 1.0:
            continue
        buckets.setdefault(model, {})[npc] = eff

    out: dict[str, dict[str, Any]] = {}
    for model, npc_eff in buckets.items():
        if not npc_eff:
            continue
        effs = list(npc_eff.values())
        avg = round(sum(effs) / len(effs))
        best_npc = min(npc_eff.keys(), key=lambda n: (abs(npc_eff[n] - avg), n))
        out[model] = {
            "npc": best_npc,
            "effective_hp": avg,
            "variant_count": len(npc_eff),
        }
    return out


def resolve_synthetic_template_donor_npc(
    tpl: dict[str, Any],
    vanilla_by_model: dict[str, dict[str, Any]],
    *,
    npc_by_id: dict[int, dict[str, str]] | None = None,
) -> int:
    """Synthetic 捐皮：npc 用原版地图皮均值代表行；无地图皮 / 法魂自定义(cnv) 保留配置 npc。"""
    try:
        cfg_npc = int(tpl.get("npc", 0) or 0)
    except (TypeError, ValueError):
        cfg_npc = 0
    if not is_synthetic_donor_template(tpl):
        out = cfg_npc
    else:
        tags = tpl.get("template_tags") or {}
        origin = str(tags.get("donor_origin") or tpl.get("donor_origin") or "")
        model = str(tpl.get("model") or "").lower()
        if origin == "cnv":
            out = cfg_npc
        else:
            hit = vanilla_by_model.get(model)
            out = int(hit["npc"]) if hit else cfg_npc
    if npc_by_id is not None:
        return resolve_valid_donor_npc(
            out,
            str(tpl.get("model") or ""),
            npc_by_id,
        )
    return out


def npc_effective_hp_for_review(
    npc: int,
    row: dict[str, str] | None,
    *,
    model: str = "",
    sp_rates: dict[str, float] | None = None,
    npc_by_id: dict[int, dict[str, str]] | None = None,
) -> dict[str, Any]:
    """捐皮审阅表：一律从 NpcParam 估算有效 HP（含 isSoulGetByBoss 行）。"""
    sp_rates = sp_rates if sp_rates is not None else load_sp_hp_rates()
    proxy_src = REVIEW_HP_PROXY_NPC.get(int(npc))
    if proxy_src and npc_by_id:
        prow = npc_by_id.get(proxy_src)
        if prow:
            peff, pmult, pparts = combat_hp_detailed(prow, sp_rates)
            if peff > 0:
                return {
                    "npc": npc,
                    "table_hp": int((row or {}).get("hp") or 0),
                    "effective_hp": peff,
                    "hp_mult_desc": f"{fmt_hp_mult(pparts, pmult)}~捐皮{proxy_src}",
                    "proxy_npc": proxy_src,
                }
    model_l = str(model or "").lower()
    pinned = DLC_BOSS_DONOR_NPC_PREFER.get(model_l)
    if pinned and npc_by_id and pinned != int(npc):
        prow = npc_by_id.get(pinned)
        if prow:
            peff, pmult, pparts = combat_hp_detailed(prow, sp_rates)
            _, shell_mult, _ = combat_hp_detailed(row or {}, sp_rates) if row else (0, 0.0, [])
            if peff > 0 and (not row or shell_mult <= 1.0):
                return {
                    "npc": npc,
                    "table_hp": int((row or {}).get("hp") or 0),
                    "effective_hp": peff,
                    "hp_mult_desc": f"{fmt_hp_mult(pparts, pmult)}~Boss行{pinned}",
                    "proxy_npc": pinned,
                }
    if row:
        eff, mult, parts = combat_hp_detailed(row, sp_rates)
        mult_desc = fmt_hp_mult(parts, mult) if eff > 0 else ""
        # ×1 模板，或削弱倍率（如百智壳 ×0.1）→ 同底/同族回填
        if mult <= 1.0 and npc_by_id:
            peer = _same_base_hp_peer_fallback(npc, row, model, npc_by_id, sp_rates)
            if peer:
                eff, mult_desc, proxy_nid = peer
                return {
                    "npc": npc,
                    "table_hp": int(row.get("hp") or 0),
                    "effective_hp": eff,
                    "hp_mult_desc": mult_desc,
                    "proxy_npc": proxy_nid,
                }
            # 同底找不到时：用同 model 族最高已缩放 HP（去重后模板行常丢同伴）
            fam = _family_hp_fallback(_model_family_id(model), npc_by_id, sp_rates)
            if fam and fam[0] > eff:
                feff, fmult, fnid = fam
                return {
                    "npc": npc,
                    "table_hp": int(row.get("hp") or 0),
                    "effective_hp": feff,
                    "hp_mult_desc": fmult,
                    "proxy_npc": fnid,
                }
        return {
            "npc": npc,
            "table_hp": int(row.get("hp") or 0),
            "effective_hp": eff,
            "hp_mult_desc": mult_desc,
        }
    if npc_by_id:
        fb = _family_hp_fallback(_model_family_id(model), npc_by_id, sp_rates)
        if fb:
            eff, mult_desc, proxy_nid = fb
            return {
                "npc": npc,
                "table_hp": 0,
                "effective_hp": eff,
                "hp_mult_desc": mult_desc,
                "proxy_npc": proxy_nid,
            }
    return {"npc": npc, "effective_hp": 0, "hp_mult_desc": ""}


@lru_cache(maxsize=4)
def donor_review_npc_rows(csv_dir: str) -> dict[int, dict[str, str]]:
    from boss_npc_detect import load_npc_rows

    return load_npc_rows(Path(csv_dir))


@lru_cache(maxsize=16384)
def review_effective_hp_cached(npc: int, model: str, csv_dir: str) -> int:
    """按 npc+model 缓存审阅有效 HP（捐皮禁捐/升格/export 共用）。"""
    npc_rows = donor_review_npc_rows(csv_dir)
    hp_pick = npc_effective_hp_for_review(
        npc,
        npc_rows.get(npc),
        model=model,
        sp_rates=load_sp_hp_rates(),
        npc_by_id=npc_rows,
    )
    return int(hp_pick.get("effective_hp") or 0)


def donor_min_effective_hp_threshold(categories_cfg: dict[str, Any]) -> int | None:
    if "donor_min_effective_hp" not in categories_cfg:
        return None
    try:
        v = int(categories_cfg.get("donor_min_effective_hp"))
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def is_below_min_donor_effective_hp(
    tpl: dict[str, Any],
    categories_cfg: dict[str, Any],
    *,
    npc_rows: dict[int, dict[str, str]] | None = None,
    sp_rates: dict[str, float] | None = None,
    csv_dir: str | Path | None = None,
) -> bool:
    """审阅有效 HP 低于 ``donor_min_effective_hp`` 时禁捐（101 → ≤100 禁捐）。"""
    threshold = donor_min_effective_hp_threshold(categories_cfg)
    if threshold is None:
        return False
    try:
        npc = int(tpl.get("npc", 0) or 0)
    except (TypeError, ValueError):
        return False
    if npc <= 0:
        return False
    model = str(tpl.get("model", ""))
    base = Path(csv_dir) if csv_dir else DEFAULT_GAME_CSV
    csv_key = str(base.resolve())
    eff = review_effective_hp_cached(npc, model.lower(), csv_key)
    return eff < threshold


def npc_row_to_pick(
    npc: int,
    row: dict[str, str],
    *,
    sp_rates: dict[str, float] | None = None,
    min_effective_hp: int = 0,
    allow_boss_soul_row: bool = False,
) -> dict[str, Any] | None:
    sp_rates = sp_rates if sp_rates is not None else load_sp_hp_rates()
    if str(row.get("isSoulGetByBoss") or "") == "1" and not allow_boss_soul_row:
        return None
    eff, mult, parts = combat_hp_detailed(row, sp_rates)
    if eff < min_effective_hp:
        return None
    return {
        "npc": npc,
        "table_hp": int(row.get("hp") or 0),
        "effective_hp": eff,
        "hp_mult": round(mult, 4),
        "hp_mult_desc": fmt_hp_mult(parts, mult),
    }


def pick_dlc_donor_npc(
    prefix: str,
    npc_by_id: dict[int, dict[str, str]],
    *,
    sp_rates: dict[str, float] | None = None,
    min_effective_hp: int = 0,
    prefer_npcs: list[int] | None = None,
    for_boss_pool: bool = False,
) -> dict[str, Any] | None:
    """Pick npc row with CNV 20007 bundle preferred, else highest effective HP."""
    sp_rates = sp_rates if sp_rates is not None else load_sp_hp_rates()
    prefix_l = str(prefix).lower()
    if prefix_l in NEVER_DONOR_PREFIXES:
        return None
    allow_boss = for_boss_pool
    prefer_chain = list(prefer_npcs or [])
    pinned = DLC_BOSS_DONOR_NPC_PREFER.get(prefix_l)
    if for_boss_pool and pinned and pinned not in prefer_chain:
        prefer_chain.insert(0, pinned)
    for nid in prefer_chain:
        row = npc_by_id.get(int(nid))
        if row is None:
            continue
        pick = npc_row_to_pick(
            int(nid),
            row,
            sp_rates=sp_rates,
            min_effective_hp=min_effective_hp,
            allow_boss_soul_row=allow_boss,
        )
        if pick:
            return pick
    try:
        family = int(prefix_l[1:5])
    except (TypeError, ValueError):
        return None
    best: dict[str, Any] | None = None
    best_score = (-1, -1)
    for npc, row in npc_by_id.items():
        if npc // 10000 != family:
            continue
        pick = npc_row_to_pick(
            npc,
            row,
            sp_rates=sp_rates,
            min_effective_hp=min_effective_hp,
            allow_boss_soul_row=allow_boss,
        )
        if not pick:
            continue
        has_cnv = "20007" in pick["hp_mult_desc"]
        score = (1 if has_cnv else 0, int(pick["effective_hp"]))
        if score > best_score:
            best_score = score
            best = pick
    return best


def load_m61_dlc_manifest(path: Path | None = None) -> dict[str, Any]:
    path = path or DEFAULT_MANIFEST
    if not path.is_file():
        return {"version": 0, "trash": [], "boss": []}
    return json.loads(path.read_text(encoding="utf-8-sig"))


def manifest_fingerprint(path: Path | None = None) -> str:
    path = path or DEFAULT_MANIFEST
    if not path.is_file():
        return "missing"
    try:
        data = load_m61_dlc_manifest(path)
    except (OSError, json.JSONDecodeError):
        return "invalid"
    blob = json.dumps(
        {
            "version": data.get("version"),
            "trash_n": len(data.get("trash") or []),
            "boss_n": len(data.get("boss") or []),
        },
        sort_keys=True,
    )
    import hashlib

    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
