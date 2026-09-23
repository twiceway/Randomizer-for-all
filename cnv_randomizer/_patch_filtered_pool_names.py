"""批量修正 筛选后捐池表 中文名：英文名优先，回写 npc_param_name_zh.json。"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import enemy_randomizer_core as core  # noqa: E402
from donor_pool_review_name_zh import _load_review_exact, resolve_review_name_zh  # noqa: E402

BASE = Path(r"V:/1_mel/Ringrandom/捐池_原槽表/筛选后捐池表")
REVIEW_JSON = SCRIPT_DIR / "npc_param_name_zh.json"
CATEGORIES = SCRIPT_DIR / "enemy_categories.json"

# model 占位名纠正（无英文名或合成行回退）
MODEL_ZH_FIX: dict[str, str] = {
    "c4660": "守护魔像",
    "c4603": "挖石山妖",
    "c5192": "巨型蜘蛛蝎",
    "c5190": "巨型蜘蛛蝎",
    "c5311": "拷问官",
    "c5312": "拷问官",
    "c5360": "巨兽骷髅",
    "c5390": "山妖",
    "c5391": "山妖骑士",
    "c5580": "尖刺山飞龙",
    "c5630": "巨型小龙虾",
    "c5640": "大螃蟹",
    "c5690": "龙颜喷火兵",
    "c5830": "梅瑟莫士兵",
    "c5651": "梅瑟莫脚注兵",
    "c5080": "血魔",
    "c5081": "血魔首领",
    "c5060": "七鳃鳗",
    "c5061": "大型七鳃鳗",
    "c5090": "墓鸟",
    "c5250": "角战士",
    "c4980": "死之鸟",
    "c6260": "死亡仪式鸟",
    "c5011": "黄金河马",
    "c5010": "黄金河马",
    "c5320": "老将盖乌斯",
    "c5300": "双月骑士蕾菈娜",
    "c5210": "神兽舞狮",
    "c5170": "熔炉魔像",
    "c5070": "死亡骑士",
    "c5790": "守护魔像",
    "c5780": "卢恩熊",
    "c5850": "巨型公羊",
    "c5960": "腐烂树灵",
    "c5970": "掳人少女人偶",
    "c6231": "调香师",
    "c6270": "王室幽魂",
    "c5551": "巨型指虫",
    "c5680": "轮式弩炮",
    "c5260": "魔像铁匠",
    "c5380": "米兰达之花",
    "c5200": "指头之母梅提尔",
    "c5220": "约定之王拉塔恩",
    "c5230": "影树化身",
    "c5130": "穿刺者梅瑟莫",
    "c5120": "恐怖贝勒",
    "c5030": "花蕾圣女萝蜜娜",
    "c5020": "腐败骑士",
    "c5040": "咒刃",
    "c5280": "冬灯",
    "c5160": "火焰骑士",
    "c5270": "壶内脏",
    "c5251": "角萨满",
    "c5330": "圣特里娜",
    "c5350": "蜥蜴眼",
    "c5370": "古龙瑟涅桑克斯",
    "c4720": "初始之王葛孚雷",
    "c5770": "战士荷莱·露",
    "c4630": "卢恩熊",
    "c3150": "黑夜骑兵",
    "c3460": "狮子混种",
    "c3570": "神皮贵族",
    "c3650": "黄金树守卫",
    "c4380": "唤星者",
    "c4810": "黄金树化身",
    "c4600": "山妖",
    "c2500": "熔炉骑士",
    "c3050": "老将尼奥尔",
    "c3252": "禁卫骑士罗蕾塔",
    "c3061": "巨兽骷髅",
    "c4960": "巨型骷髅躯干",
    "c4950": "提比亚唤魂",
}


def patch_categories_model_zh() -> int:
    data = json.loads(CATEGORIES.read_text(encoding="utf-8"))
    mpz = data.setdefault("model_prefix_display_zh", {})
    n = 0
    for model, zh in MODEL_ZH_FIX.items():
        if mpz.get(model) != zh:
            mpz[model] = zh
            n += 1
    CATEGORIES.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return n


def parse_table(path: Path) -> tuple[list[str], list[list[str]], bool]:
    lines = path.read_text(encoding="utf-8").splitlines()
    meta: list[str] = []
    rows: list[list[str]] = []
    pool1 = "_池1_" in path.name
    in_table = False
    for line in lines:
        if line.startswith("| 序号 |"):
            in_table = True
            continue
        if in_table:
            if line.startswith("|") and not line.startswith("| ---"):
                cols = [c.strip() for c in line.split("|")[1:-1]]
                while cols and cols[0].isdigit():
                    cols = cols[1:]
                if cols:
                    rows.append(cols)
            elif rows:
                break
        else:
            meta.append(line)
    return meta, rows, pool1


def write_table(path: Path, meta: list[str], header_lines: list[str], rows: list[list[str]], pool1: bool) -> None:
    body = meta[:]
    # 保留表头前 meta，插入表头
    if not any(l.startswith("| 序号 |") for l in body):
        body.extend(["", *header_lines])
    else:
        # 重建：meta 到第一个表头行
        new_meta: list[str] = []
        for ln in meta:
            new_meta.append(ln)
            if ln.startswith("| 序号 |"):
                break
        else:
            new_meta = meta
        body = new_meta + [header_lines[1]] if len(header_lines) > 1 else new_meta

    # 简化：整文件重写
    pre: list[str] = []
    for ln in path.read_text(encoding="utf-8").splitlines():
        if ln.startswith("| 序号 |"):
            break
        pre.append(ln)
    if pre and not pre[-1].strip():
        pass
    elif pre:
        pre.append("")

    table_lines = [header_lines[0], header_lines[1]]
    for i, r in enumerate(rows, 1):
        table_lines.append(f"| {i} | " + " | ".join(r) + " |")
    path.write_text("\n".join(pre + table_lines + [""]), encoding="utf-8")


def patch_file(path: Path, cfg: dict, review: dict[str, str], new_entries: dict[str, str]) -> tuple[int, int]:
    if "索引" in path.name or path.name == "捐皮池表_1-7.md":
        return 0, 0
    meta, rows, pool1 = parse_table(path)
    if not rows:
        return 0, 0

    if pool1:
        header = [
            "| 序号 | model | 中文名 | 原型类 | npc | 有效HP | HP倍率 | 示例地图 | 示例实体 | MSB槽数 | 分布图数 | 入prep槽 | 合成 | 英文名 |",
            "| ---: | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        zh_idx, en_idx = 1, -1
    else:
        header = [
            "| 序号 | model | 中文名 | npc | 英文名 | 有效HP | HP倍率 | 示例地图 | 示例实体 | MSB槽数 | 分布图数 | 入prep槽 | 合成 |",
            "| ---: | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        zh_idx, en_idx = 1, 3

    changed = 0
    for r in rows:
        if len(r) < 4:
            continue
        model = r[0]
        old_zh = r[zh_idx]
        en = r[en_idx] if en_idx < len(r) else ""
        model_zh = MODEL_ZH_FIX.get(model) or core._model_prefix_zh(model, cfg)
        new_zh = resolve_review_name_zh(en, model_zh, review)
        if not new_zh:
            continue
        if new_zh != old_zh:
            r[zh_idx] = new_zh
            changed += 1
        if en.strip() and new_zh and en.strip() not in review and en.strip() not in new_entries:
            new_entries[en.strip()] = new_zh

    if changed:
        write_table(path, meta, header, rows, pool1)
    return changed, len(rows)


def main() -> None:
    cat_n = patch_categories_model_zh()
    cfg = core._load_json(CATEGORIES)
    review = _load_review_exact()
    new_entries: dict[str, str] = {}

    total_changed = 0
    total_rows = 0
    per_file: list[tuple[str, int]] = []
    for path in sorted(BASE.glob("捐皮池表_*.md")):
        ch, n = patch_file(path, cfg, review, new_entries)
        if ch:
            per_file.append((path.name, ch))
        total_changed += ch
        total_rows += n

    # 回写英译表（仅新增，不覆盖手工项）
    if REVIEW_JSON.is_file():
        raw = json.loads(REVIEW_JSON.read_text(encoding="utf-8"))
        names = raw.setdefault("names", {})
        added = 0
        for en, zh in sorted(new_entries.items()):
            if en not in names:
                names[en] = zh
                added += 1
        raw["description"] = (
            "NpcParam Name 英文→中文（捐皮审阅表用）；"
            "筛选后捐池表审阅优先读本表英译，再回退 model_prefix_display_zh。"
        )
        REVIEW_JSON.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    else:
        added = 0

    print(f"model_prefix fixed: {cat_n}")
    print(f"rows scanned: {total_rows}, zh changed: {total_changed}, en dict +{added}")
    for name, ch in per_file:
        print(f"  {name}: {ch}")


if __name__ == "__main__":
    main()
