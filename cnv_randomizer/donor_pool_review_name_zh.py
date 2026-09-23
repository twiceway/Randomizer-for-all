"""捐皮审阅表中文名：英文名优先解析（筛选后表专用，不 spoiler 拼 model 占位名）。"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from paths import SCRIPT_DIR  # frozen-safe (data/cnv_randomizer)
REVIEW_JSON = SCRIPT_DIR / "npc_param_name_zh.json"

# 英文物种/职业基词（长串优先）
TERM_ZH: list[tuple[str, str]] = [
    ("Full-Grown Fallingstar Beast", "长大坠星兽物"),
    ("Erdtree Burial Watchdog", "黄金树归葬看门犬"),
    ("Ulcerated Tree Spirit", "腐烂树灵"),
    ("Putrid Tree Spirit", "腐败树灵"),
    ("Guardian Golem", "守护魔像"),
    ("Stonedigger Troll", "挖石山妖"),
    ("Grafted Scion", "接肢恶兆贵族"),
    ("Fallingstar Beast", "坠星兽物"),
    ("Giant Land Octopus", "巨型陆章鱼"),
    ("Giant Wormface", "巨型蚯蚓脸"),
    ("Giant Crayfish", "巨型小龙虾"),
    ("Death Rite Bird", "死亡仪式鸟"),
    ("Death Bird", "死之鸟"),
    ("Magma Wyrm", "熔岩土龙"),
    ("Dragon-faced Flamethrower", "龙颜喷火兵"),
    ("Chief Bloodfiend", "血魔首领"),
    ("Golden Hippopotamus", "黄金河马"),
    ("Spider Scorpion", "巨型蜘蛛蝎"),
    ("Horned Warrior", "角战士"),
    ("Giant Beast Skeleton", "巨兽骷髅"),
    ("Jagged Peak Drake", "尖刺山飞龙"),
    ("Messmer Foot Soldier", "梅瑟莫脚注兵"),
    ("Messmer Soldier", "梅瑟莫士兵"),
    ("Divine Beast Dancing Lion", "神兽舞狮"),
    ("Furnace Golem", "熔炉魔像"),
    ("Death Knight", "死亡骑士"),
    ("Inquisitor (Candles)", "拷问官（蜡烛）"),
    ("Inquisitor (Staff)", "拷问官（杖）"),
    ("Inquisitor", "拷问官"),
    ("Fat Inquisitor", "肥胖拷问官"),
    ("Fingercreeper (Large)", "巨型指虫"),
    ("Small Fingercreeper", "小型指虫"),
    ("Fingercreeper", "指虫"),
    ("Wheeled Ballista", "轮式弩炮"),
    ("Abductor Virgin", "掳人少女人偶"),
    ("Royal Revenant", "王室幽魂"),
    ("Godrick - Head and Torso", "接肢葛瑞克（头身）"),
    ("Red Wolf of Radagon Sword", "拉达冈的红狼（剑）"),
    ("Red Wolf of Radagon", "拉达冈的红狼"),
    ("Red Wolf of the Champion", "勇士的红狼"),
    ("Cemetery Shade", "墓地影子"),
    ("Flying Dragon", "飞龙"),
    ("Mimic Tear", "仿身泪滴"),
    ("Giant Ram", "巨型公羊"),
    ("Golem Smith", "魔像铁匠"),
    ("Commander Gaius", "老将盖乌斯"),
    ("Rellana- Twin Moon Knight", "双月骑士蕾菈娜"),
    ("Rellana, Twin Moon Knight", "双月骑士蕾菈娜"),
    ("Sir Gideon Ofnir- the All-Knowing", "百智爵士基甸"),
    ("Sir Gideon Ofnir, the All-Knowing", "百智爵士基甸"),
    ("Promised Consort Radahn", "约定之王拉塔恩"),
    ("Scadutree Avatar", "影树化身"),
    ("Metyr- Mother of Fingers", "指头之母梅提尔"),
    ("Messmer the Impaler", "穿刺者梅瑟莫"),
    ("Bayle the Dread", "恐怖贝勒"),
    ("Romina- Saint of the Bud", "花蕾圣女萝蜜娜"),
    ("Putrescent Knight", "腐败骑士"),
    ("Midra - Human", "米德拉"),
    ("Hoarah Loux", "战士荷莱·露"),
    ("Godfrey, First Elden Lord", "初始之王葛孚雷"),
    ("God-Devouring Serpent", "噬神大蛇"),
    ("Rykard- Lord of Blasphemy", "亵渎君王拉卡德"),
    ("Starscourge Radahn", "碎星将军拉塔恩"),
    ("Godrick the Grafted", "接肢葛瑞克"),
    ("Margit, the Fell Omen", "恶兆妖鬼玛尔基特"),
    ("Margit", "恶兆妖鬼玛尔基特"),
    ("Mohg- the Omen", "鲜血之君蒙格"),
    ("Mohg, Lord of Blood", "鲜血君王蒙格"),
    ("Malenia, Blade of Miquella", "女武神玛莲妮亚"),
    ("Maliketh, the Black Blade", "黑剑玛利喀斯"),
    ("Radagon of the Golden Order", "黄金律法拉达冈"),
    ("Elden Beast", "艾尔登之兽"),
    ("Ancestor Spirit", "祖灵之王"),
    ("Regal Ancestor Spirit", "尊贵祖灵"),
    ("Draconic Tree Sentinel", "龙装大树守卫"),
    ("Tree Sentinel", "大树守卫"),
    ("Crucible Knight Ordovis", "熔炉骑士奥陶琵斯"),
    ("Crucible Knight", "熔炉骑士"),
    ("Banished Knight", "失乡骑士"),
    ("Night's Cavalry", "黑夜骑兵"),
    ("Bloodhound Knight", "猎犬骑士"),
    ("Grave Warden Duelist", "墓土格斗家"),
    ("Crystalian", "结晶人"),
    ("Godskin Noble", "神皮贵族"),
    ("Godskin Apostle", "神皮使徒"),
    ("Godskin Duo", "神皮双人组"),
    ("Albinauric Archer", "白金之子弓手"),
    ("Albinauric Lookout", "白金之子哨兵"),
    ("Elder Albinauric", "白金之子老法师"),
    ("Imprisoned Elder Albinauric", "白金之子老法师（囚禁）"),
    ("Leonine Misbegotten", "狮子混种"),
    ("Misbegotten", "混种怪"),
    ("Demi-Human", "亚人"),
    ("Large Demi-Human", "大亚人"),
    ("Putrid Corpse", "腐败遗体"),
    ("Giant Skeleton", "巨型骷髅"),
    ("Large Skeleton", "大型骷髅"),
    ("Skeleton", "骷髅"),
    ("Spirit Jellyfish", "灵魂水母"),
    ("Land Octopus", "陆生章鱼"),
    ("Giant Ant", "巨蚁"),
    ("Omenkiller", "恶兆猎人"),
    ("Omen", "恶兆之子"),
    ("Wormface", "蚯蚓脸"),
    ("Perfumer", "调香师"),
    ("Depraved Perfumer", "堕落调香师"),
    ("Glintstone Sorcerer", "辉石魔法师"),
    ("Oracle Envoy", "神谕使者"),
    ("Erdtree Guardian", "黄金树守卫"),
    ("Guardian", "黄金树守卫"),
    ("Commoner", "平民"),
    ("Wandering Noble", "流浪贵族"),
    ("Soldier", "士兵"),
    ("Foot Soldier", "脚注兵"),
    ("Knight", "骑士"),
    ("Stray", "野狗"),
    ("Large Stray", "大野狗"),
    ("Wolf", "狼"),
    ("Snail", "蜗牛"),
    ("Spiritcaller Snail", "唤灵蜗牛"),
    ("Tibia Mariner", "提比亚唤魂"),
    ("Giant Skeleton Torso", "巨型骷髅躯干"),
    ("Living Mass", "原生体"),
    ("Putrid Flesh", "腐败血肉"),
    ("Bat Harpy", "蝙蝠妖"),
    ("Operatic Bat", "歌姬蝙蝠"),
    ("Silver Tear", "泪滴"),
    ("Giant Silver Tear", "巨大泪滴"),
    ("Ancestral Follower", "祖灵随从"),
    ("Ancestral Follower Shaman", "祖灵萨满"),
    ("Nox Monk", "诺克斯僧侣"),
    ("Nox Swordstress", "诺克斯剑士"),
    ("Nox Night Maiden", "诺克斯黑夜舞娘"),
    ("Sanguine Noble", "鲜血贵族"),
    ("Albinauric", "白金之子"),
    ("Bloodfiend", "血魔"),
    ("Fire Knight", "火焰骑士"),
    ("Gravebird", "墓鸟"),
    ("Lamprey", "七鳃鳗"),
    ("Winter-Lantern", "冬灯"),
    ("Curseblade", "咒刃"),
    ("Runebear", "卢恩熊"),
    ("Troll Knight", "山妖骑士"),
    ("Troll", "山妖"),
    ("Giant Crab", "大螃蟹"),
    ("Crab", "螃蟹"),
    ("Man-Bat", "人蝠"),
    ("Marionette Soldier", "木偶士兵"),
    ("Shade", "幽影"),
    ("Cemetary Shade", "墓地幽影"),
    ("Catacombs Sorcerer", "地下墓地魔法师"),
    ("Horned Shaman", "角萨满"),
    ("Jar Innards", "壶内脏"),
    ("Kindred of Rot", "腐败眷属"),
    ("Man-Fly", "蝇人"),
    ("Black Knight", "黑骑士"),
    ("Ghostflame Dragon", "鬼焰龙"),
    ("Basilisk", "蜥蜴（石化）"),
    ("Bear", "熊"),
    ("Human", "人类"),
    ("Starcaller", "唤星者"),
    ("Stonedigger", "挖石矿工"),
    ("Glintstone Digger", "辉石矿工"),
    ("Disciple of Rot", "腐败信徒"),
    ("Highwayman", "拦路强盗"),
    ("Vulgar Militia", "流氓斗士"),
    ("Exile Soldier", "流放士兵"),
    ("Large Exile Soldier", "大型流放士兵"),
    ("Commander Niall", "老将尼奥尔"),
    ("Commander O'Neil", "老将奥尼尔"),
    ("Royal Knight Loretta", "禁卫骑士罗蕾塔"),
    ("Redmane Knight", "红狮子骑士"),
    ("Preceptor Miriam", "魔法教授米丽安"),
    ("Rennala- Queen of the Full Moon", "满月女王蕾娜菈"),
    ("Black Knife Assassin", "黑刀刺客"),
    ("Alecto- Black Knife Ringleader", "黑刀之首亚勒科特"),
    ("Astel, Naturalborn of the Void", "黑暗弃子艾丝特尔"),
    ("Naturalborn of the Void", "黑暗弃子"),
    ("Flying Dragon Agheel", "飞龙亚基尔"),
    ("Flying Dragon Greyll", "飞龙桂雷尔"),
    ("Decaying Ekzykes", "「腐败」艾克兹克斯"),
    ("Erdtree Avatar", "黄金树化身"),
    ("Putrid Avatar", "腐败化身"),
    ("Erdtree Burial Watchdog", "黄金树归葬看门犬"),
    ("Leonine Misbegotten", "狮子混种"),
    ("Miranda Sprout", "米兰达芽"),
    ("Miranda Blossom", "米兰达之花"),
    ("Living Jar", "活壶"),
    ("Alexander- Warrior Jar", "战士壶亚历山大"),
    ("Giant Living Mass", "巨大原生体"),
    ("Small Living Mass", "小型原生体"),
    ("Watcher Stones", "辉石监视球"),
    ("Abnormal Stone Cluster", "异常石簇"),
    ("Land Squirt", "陆地喷汁虫"),
    ("Giant Land Squirt", "巨型陆地喷汁虫"),
    ("Direwolf", "恶狼"),
    ("Rotten Dog", "腐败野狗"),
    ("Bloodbane Stray", "血野狗"),
    ("Rotten Stray", "腐败野狗"),
    ("Starved Dog", "饥饿野狗"),
    ("Giant Black Crab", "巨型黑蟹"),
    ("Giant Albinauric Crab", "巨型白金蟹"),
    ("Albinauric Crab", "白金蟹"),
    ("Giant Death Crab", "巨型死亡蟹"),
    ("Death Crab", "死亡蟹"),
    ("Lightning Ball", "闪电球"),
    ("Juvenile Scholar", "幼隶学者"),
    ("Dominula Celebrant", "多米努拉庆祝者"),
    ("Imp", "小恶魔"),
    ("Page", "侍从"),
    ("High Page", "高级侍从"),
    ("Noble's Page", "贵族侍从"),
    ("Perfumer", "调香师"),
]

LOC_ZH: dict[str, str] = {
    "Limgrave": "宁姆格福",
    "Liurnia": "利耶尼亚",
    "Liurnia of the Lakes": "利耶尼亚",
    "Caelid": "盖利德",
    "Altus": "亚坛高原",
    "Altus Plateau": "亚坛高原",
    "Stormveil Castle": "史东薇尔城",
    "Volcano Manor": "火山官邸",
    "Volcano Top": "火山山顶",
    "Mt. Gelmir": "格密尔火山",
    "Weeping Peninsula": "啜泣半岛",
    "Snowfields": "化圣雪原",
    "Forbidden Lands": "禁域",
    "Siofra River": "希芙拉河",
    "Ainsel River": "安瑟尔河",
    "Sellia Tunnel": "瑟利亚坑道",
    "Gael Tunnel": "盖尔坑道",
    "Lava Lake Boss": "熔岩湖·Boss",
    "Boss": "Boss",
    "Unscaled": "未缩放",
    "Boss Village": "恶人村",
    "Ellac River": "埃拉克河",
    "Fog Rift Catacombs Boss": "雾谷地下墓地 Boss",
    "Impalers Catacombs": "钉刺地下墓地",
    "Wyndham Catacombs": "威达姆地下墓地",
    "Minor Erdtree Catacombs": "小黄金树地下墓地",
    "Limgrave Catacombs": "宁姆格福地下墓地",
    "Liurnia Catacombs Boss": "利耶尼亚地下墓地 Boss",
    "Archives": "书斋",
    "Rennala": "蕾娜菈",
    "Ordina": "圣树镇",
    "Shaded Castle": "日荫城",
    "Charo's Hidden Grave": "卡罗隐藏墓地",
    "Southwest Cerulean Coast - Charo's Hidden Grave": "青蓝海岸西南·卡罗隐藏墓地",
    "Duo Mob": "双人组",
    "Golden Wings": "金翼",
    "Rauh": "劳赫",
    "Belurat Boss": "贝鲁尔 Boss",
    "Candles": "蜡烛",
    "Staff": "杖",
    "Hammer": "锤",
    "Small": "小型",
    "Large": "巨型",
    "Giant": "巨型",
}

TAG_RE = re.compile(r"\s*(\[[^\]]+\])")
PAREN_RE = re.compile(r"^(.*?)(\s*\(([^)]*)\))?\s*$")


@lru_cache(maxsize=1)
def _load_review_exact() -> dict[str, str]:
    if not REVIEW_JSON.is_file():
        return {}
    raw = json.loads(REVIEW_JSON.read_text(encoding="utf-8"))
    names = raw.get("names") or {}
    out: dict[str, str] = {}
    for k, v in names.items():
        ks, vs = str(k).strip(), str(v).strip()
        if ks and vs:
            out[ks] = vs
    return out


def _norm_en_key(en: str) -> str:
    return en.replace("é", "e").strip().lower()


def _lookup_exact(en: str, review: dict[str, str]) -> str:
    if en in review:
        return review[en]
    low = _norm_en_key(en)
    for k, v in review.items():
        if _norm_en_key(k) == low:
            return v
    return ""


def _translate_paren(loc: str) -> str:
    loc = loc.strip()
    if not loc:
        return ""
    if loc in LOC_ZH:
        return LOC_ZH[loc]
    # 逐段翻译 "Foo Bar Baz"
    parts = re.split(r"\s*[-·]\s*", loc)
    if len(parts) > 1:
        return "·".join(_translate_paren(p) for p in parts if p.strip())
    for en, zh in sorted(LOC_ZH.items(), key=lambda x: -len(x[0])):
        if loc == en:
            return zh
    return loc


def _translate_tags(s: str) -> str:
    def repl(m: re.Match[str]) -> str:
        tag = m.group(1)
        inner = tag.strip("[]")
        if inner.lower() == "boss":
            return "【Boss】"
        if inner.lower() == "unscaled":
            return "【未缩放】"
        return f"【{inner}】"

    return TAG_RE.sub(repl, s).strip()


def _translate_by_terms(en: str) -> str:
    en = en.strip()
    if not en:
        return ""
    for term, zh in sorted(TERM_ZH, key=lambda x: -len(x[0])):
        if en == term:
            return zh
    # 去尾部 bracket tags，最后拼回中文
    tags = "".join(TAG_RE.findall(en))
    core = TAG_RE.sub("", en).strip()
    m = PAREN_RE.match(core)
    if not m:
        base, paren = core, ""
    else:
        base, _, paren_inner = m.group(1).strip(), m.group(2) or "", (m.group(3) or "").strip()
        paren = _translate_paren(paren_inner) if paren_inner else ""

    zh_base = ""
    for term, zh in sorted(TERM_ZH, key=lambda x: -len(x[0])):
        if base == term or base.startswith(term + " ") or base.startswith(term + "-"):
            rest = base[len(term) :].strip(" -")
            zh_base = zh + (f"（{rest}）" if rest else "")
            break
    if not zh_base:
        for term, zh in sorted(TERM_ZH, key=lambda x: -len(x[0])):
            if term.lower() in base.lower() and len(term) > 8:
                zh_base = zh
                break
    if not zh_base:
        return ""

    if paren:
        zh_base = f"{zh_base}（{paren}）"
    if tags:
        zh_base += _translate_tags(tags)
    return zh_base


def resolve_review_name_zh(
    name_en: str,
    model_zh: str = "",
    review: dict[str, str] | None = None,
) -> str:
    """审阅表用：有英文名则优先英译，否则回退 model 中文。"""
    en = str(name_en or "").strip()
    review = review if review is not None else _load_review_exact()
    if en:
        hit = _lookup_exact(en, review)
        if hit:
            return hit
        hit = _translate_by_terms(en)
        if hit:
            return hit
    return str(model_zh or "").strip()
