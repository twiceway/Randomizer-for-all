"""把 T063 候选表按黑白名单名称相似度拆成「待审」与「与契约重叠」两节。"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from paths import DONOR_POOL_CONTRACT_DIR

T063_MD = DONOR_POOL_CONTRACT_DIR / "T063_新扫捐皮候选表.md"

ROW_RE = re.compile(
    r"^\|\s*(\d+)\s*\|\s*([^|]+)\|\s*([^|]+)\|\s*([^|]+)\|\s*`([^`]+)`\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*`([^`]+)`\s*\|$"
)


def _load_contract_rows() -> list[dict]:
    rows: list[dict] = []
    for path, source in (
        (DONOR_POOL_CONTRACT_DIR / "捐皮白名单_当前.json", "白名单"),
        (DONOR_POOL_CONTRACT_DIR / "捐皮黑名单_当前.json", "黑名单"),
    ):
        if not path.is_file():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        for pool_rows in (data.get("rows_by_pool") or {}).values():
            for r in pool_rows:
                rows.append(
                    {
                        "source": source,
                        "pool": r.get("pool_zh") or r.get("pool") or "",
                        "name_zh": str(r.get("name_zh") or ""),
                        "name_en": str(r.get("name_en") or ""),
                        "model": str(r.get("model") or "").lower(),
                        "npc": int(r.get("npc") or 0),
                        "reason_zh": str(r.get("reason_zh") or ""),
                    }
                )
    return rows


def _norm_zh(s: str) -> str:
    s = re.sub(r"[「」『』\[\]]", "", s)
    s = re.sub(r"（[^）]*）", "", s)
    s = re.sub(r"\([^)]*\)", "", s)
    s = re.sub(r"[·\-—\s]", "", s)
    return s.strip()


def _norm_en(s: str) -> str:
    s = re.sub(r"\[[^\]]*\]", "", s)
    s = re.sub(r"\([^)]*\)", "", s)
    s = re.sub(r"\s+-\s+.*$", "", s)
    s = re.sub(r"\s+", " ", s).strip().casefold()
    return s


def _en_tokens(s: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", _norm_en(s)) if len(t) >= 4}


def _zh_archetype_core(s: str) -> str:
    """去掉兵种/尺寸后缀，比「圣树小兵」与「圣树士兵」等。"""
    s = _norm_zh(s)
    for suffix in (
        "小兵",
        "士兵",
        "战士",
        "骑士",
        "贵族",
        "魔法师",
        "僧侣",
        "剑士",
    ):
        if s.endswith(suffix) and len(s) > len(suffix) + 1:
            return s[: -len(suffix)]
    return s


def _match_reasons(cand: dict, ref: dict) -> list[str]:
    out: list[str] = []
    src = ref["source"]
    if cand["npc"] and cand["npc"] == ref["npc"]:
        out.append(f"{src}·同npc")
    if cand["model"] and cand["model"] == ref["model"]:
        out.append(f"{src}·同model·`{ref['model']}`")
    czh, rzh = _norm_zh(cand["name_zh"]), _norm_zh(ref["name_zh"])
    if czh and rzh and len(rzh) >= 2:
        if czh == rzh or rzh in czh or (len(czh) >= 2 and czh in rzh):
            out.append(f"{src}·中文≈{ref['name_zh'][:24]}")
    cz_core, rz_core = _zh_archetype_core(cand["name_zh"]), _zh_archetype_core(ref["name_zh"])
    if len(cz_core) >= 2 and cz_core == rz_core and czh != rzh:
        out.append(f"{src}·中文同类≈{ref['name_zh'][:24]}")
    if "哨兵" in cand["name_zh"] and "哨兵" in ref["name_zh"]:
        out.append(f"{src}·中文·哨兵同类≈{ref['name_zh'][:20]}")
    cen, ren = _norm_en(cand["name_en"]), _norm_en(ref["name_en"])
    if cen and ren:
        if cen == ren:
            out.append(f"{src}·英文同名")
        elif len(ren) >= 6 and ren in cen:
            out.append(f"{src}·英文≈{ref['name_en'][:28]}")
        elif len(cen) >= 6 and cen in ren:
            out.append(f"{src}·英文≈{ref['name_en'][:28]}")
    # Godskin / Misbegotten 等英文关键词
    ct, rt = _en_tokens(cand["name_en"]), _en_tokens(ref["name_en"])
    shared = ct & rt
    if shared & {"sentry", "soldier", "foot"} and not out:
        out.append(f"{src}·英文词根{'/'.join(sorted(shared)[:2])}·{ref['name_en'][:22]}")
    if shared & {"godskin", "misbegotten", "miranda", "stray", "skeleton", "golem", "dragon", "jar", "kindred"}:
        if len(shared) >= 1 and not out:
            out.append(f"{src}·词根{'/'.join(sorted(shared)[:3])}·{ref['name_en'][:22]}")
    return out


def _parse_t063_rows(text: str) -> list[dict]:
    rows: list[dict] = []
    seen: set[tuple[str, int]] = set()
    for line in text.splitlines():
        line = line.strip()
        m = ROW_RE.match(line)
        if not m:
            m2 = re.match(
                r"^\|\s*(\d+)\s*\|\s*([^|]+)\|\s*([^|]+)\|\s*([^|]+)\|\s*`([^`]+)`\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*`([^`]+)`\s*\|",
                line,
            )
            if not m2:
                continue
            m = m2
        model = m.group(5).strip().lower()
        npc = int(m.group(6))
        key = (model, npc)
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "seq": int(m.group(1)),
                "cat_zh": m.group(2).strip(),
                "name_zh": m.group(3).strip(),
                "name_en": m.group(4).strip(),
                "model": model,
                "npc": npc,
                "hp": int(m.group(7)),
                "map": m.group(8).strip(),
            }
        )
    return rows


def _render_table(rows: list[dict], *, with_reason: bool = False) -> list[str]:
    if with_reason:
        header = "| 原序号 | 推断池 | 中文名 | 英文名 | model | npc | 有效HP | 示例图 | 重叠说明 |"
        sep = "|---:|:---|:---|:---|:---|---:|---:|:---|:---|"
    else:
        header = "| 序号 | 推断池 | 中文名 | 英文名 | model | npc | 有效HP | 示例图 |"
        sep = "|---:|:---|:---|:---|:---|---:|---:|:---|"
    lines = [header, sep]
    for i, r in enumerate(rows, 1):
        if with_reason:
            lines.append(
                f"| {r.get('orig_seq', i)} | {r['cat_zh']} | {r['name_zh']} | {r['name_en']} "
                f"| `{r['model']}` | {r['npc']} | {r['hp']} | `{r['map']}` | {r.get('overlap', '')} |"
            )
        else:
            lines.append(
                f"| {i} | {r['cat_zh']} | {r['name_zh']} | {r['name_en']} "
                f"| `{r['model']}` | {r['npc']} | {r['hp']} | `{r['map']}` |"
            )
    return lines


def main() -> None:
    text = T063_MD.read_text(encoding="utf-8")
    candidates = _parse_t063_rows(text)
    if not candidates:
        raise SystemExit("未解析到明细行")

    contract = _load_contract_rows()
    pending: list[dict] = []
    overlap: list[dict] = []

    for cand in candidates:
        reasons: list[str] = []
        for ref in contract:
            hit = _match_reasons(cand, ref)
            if hit:
                tag = f"{ref['source']}"
                if ref.get("pool"):
                    tag += f"·{ref['pool']}"
                reasons.extend([f"{h}" for h in hit[:2]])
        # 去重保序
        seen: set[str] = set()
        uniq: list[str] = []
        for r in reasons:
            if r not in seen:
                seen.add(r)
                uniq.append(r)
        if uniq:
            overlap.append({**cand, "orig_seq": cand["seq"], "overlap": "；".join(uniq[:3])})
        else:
            pending.append(cand)

    # 重建 md：保留头部到第一个「## 明细」之前
    head_end = text.find("## 明细")
    if head_end < 0:
        head = ""
    else:
        head = text[:head_end]
    if "名称重叠" not in head:
        head = head.replace(
            "- **保留**：同图多实例、白名单未覆盖的新 model 变体，供审计是否扩池。",
            "- **保留**：同图多实例、白名单未覆盖的新 model 变体，供审计是否扩池。\n"
            "- **名称比对**：与黑白名单 **npc·model·中英文名** 相近者移入下方附录，主表只审真正新皮。",
        )
    # 去掉头部旧的池统计表（避免与拆分后数字矛盾）
    head = re.sub(
        r"\n\| 推断池 \| 种数 \|\n\|:---\|---:\|\n(?:\| [^\n]+\n)+",
        "\n",
        head,
        count=1,
    )

    by_cat_p = Counter(r["cat_zh"] for r in pending)
    by_cat_o = Counter(r["cat_zh"] for r in overlap)

    lines = [
        head.rstrip(),
        "## 明细（待审 · 与黑白名单名称不重叠）",
        "",
        f"**待审种数**：**{len(pending)}**",
        "",
        "| 推断池 | 种数 |",
        "|:---|---:|",
    ]
    for cat, n in sorted(by_cat_p.items(), key=lambda x: (-x[1], x[0])):
        lines.append(f"| {cat} | {n} |")
    lines += ["", *_render_table(pending), ""]
    lines += [
        "## 附录 · 与黑白名单名称重叠（暂不审 · 保留备查）",
        "",
        "下列与 `捐皮白名单_当前` / `捐皮黑名单_当前` **npc·model·中英文名** 相近，主表先剔除；未删行，供核对是否同皮重复。",
        "",
        f"**重叠条数**：**{len(overlap)}**",
        "",
        "| 推断池 | 种数 |",
        "|:---|---:|",
    ]
    for cat, n in sorted(by_cat_o.items(), key=lambda x: (-x[1], x[0])):
        lines.append(f"| {cat} | {n} |")
    lines += ["", *_render_table(overlap, with_reason=True), ""]

    # 更新头部总览
    body = "\n".join(lines)
    body = re.sub(
        r"\*\*候选种数\*\*：\*\*\d+\*\*[^\n]*",
        f"**候选种数**：**{len(candidates)}**（待审 **{len(pending)}** · 与契约重叠 **{len(overlap)}**）（按 model+npc 去重）",
        body,
        count=1,
    )
    T063_MD.write_text(body + "\n", encoding="utf-8")
    print(f"pending={len(pending)} overlap={len(overlap)} total={len(candidates)}")


if __name__ == "__main__":
    main()
