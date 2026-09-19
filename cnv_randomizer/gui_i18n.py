# -*- coding: utf-8 -*-
"""GUI language strings — plain words for players (zh / en)."""

from __future__ import annotations

from typing import Any

# Default until GUI loads config
_UI_LANG = "zh"

STRINGS: dict[str, dict[str, str]] = {
    "zh": {
        "app_title": "Randomizer for all — 换怪 / 换地上物品",
        "lang_label": "语言",
        "seed": "种子",
        "random_seed": "随机种子",
        "auto_new_seed": "每次生成换新种子",
        "save_settings": "保存设置",
        "generate": "开始生成",
        "test_generate": "测试生成（只出表）",
        "open_output": "打开结果文件夹",
        "ready": "就绪",
        "page_items": "随机物品",
        "page_enemies": "随机怪物",
        "tab_install": "安装mod到游戏",
        "tab_items": "物品",
        "tab_enemies": "怪物",
        "hint_release": "点「开始生成」才会写进游戏。勾选「每次生成换新种子」可避免结果总一样。",
        "hint_maintainer": "「测试生成」只出对照表、不改游戏地图；真机请用「开始生成」。勾选「每次生成换新种子」可避免结果总一样。",
        "gen_will": "本次将生成：",
        "gen_none": "本次将生成：（无 — 请勾选页签上的随机物品/随机怪物）",
        "boot_log": (
            "Randomizer for all · 当前只支持法魂 Convergence 3.0（原版和其它大型模组以后再加）。\n"
            "先到「安装到游戏」页接好，再点「开始生成」。\n"
            "地上物品：箱子、尸体等掉落会打乱。\n"
            "怪物：野外和副本里的怪会换皮；请先在怪物页「扫描游戏地图」。\n"
            "生成后会自动装进游戏；完全退出游戏再进才会生效。\n"
        ),
        "maintainer_on": "开发者工具：已开启（试验台 / 只出表 / 其它调试按钮）",
        "saved": "已保存",
        "saved_to": "当前设置已写入：\n{path}",
        # install
        "install_req_er": "需求法环版本：{ver}",
        "install_req_cnv": "需求法魂版本：{ver}",
        "install_intro": (
            "把本模组接到你的游戏（拷贝必要文件、改启动配置）。\n"
            "这不是安装本软件本身；「开始生成」是另一步。\n"
            "Randomizer for all · 当前只支持法魂 Convergence 3.0。"
        ),
        "install_game_dir": "游戏文件夹（Game）：",
        "browse": "浏览…",
        "install_force": "版本提示时仍强制接入（仅排查用）",
        "install_detect": "检测",
        "install_run": "安装本模组到游戏",
        "install_uninstall": "卸下本模组接线",
        "install_open": "打开游戏文件夹",
        "install_log_title": "检测 / 预览 / 结果：",
        "install_pick_title": "选择游戏文件夹（里面有 eldenring.exe）",
        "install_status_ok": "状态：已装（可以开始生成）",
        "install_status_need": "状态：未装 — 开始生成会被拦住",
        "install_status_ok_saved": "状态：已装（记住的目录：{path}）",
        "install_status_none": "状态：未选择游戏文件夹 / 未装",
        "install_need_dir": "请先选择有效的游戏文件夹（Game）。",
        "install_blocked": "现在不能安装",
        "install_ver_warn": "版本注意",
        "install_ver_force_hint": "\n\n若仍要试，请勾选「版本提示时仍强制接入」后再点安装。",
        "install_confirm_title": "确认安装本模组到游戏",
        "install_confirm_body": "将写入 / 确认以下变更：\n\n{preview}",
        "install_force_prefix": "【强制安装】\n{warnings}\n\n",
        "install_done_title": "安装完成",
        "install_done_body": (
            "本模组已接到游戏（改的是法魂原来的启动配置，没有另做启动器）。\n\n"
            "接下来：\n"
            "1. 在本软件点「开始生成」。\n"
            "2. 生成结束后，请完全退出游戏（任务栏也要退出）。\n"
            "3. 用法魂原来的方式再进游戏——常见是双击 Game 目录里的\n"
            "   Start_Convergence_ME3.bat（你平时用法魂进游戏的那个也可以）。\n\n"
            "不要直接开 eldenring.exe；要用带 ME3 / 法魂的启动方式，随机才会生效。\n\n"
            "想手动接线 / 自写 bat：地上拾取 dll 是 "
            "Game\\mod\\dll\\cnv_pickup_hook.dll"
            "（靠 me3\\convergence.me3 里的 natives 加载，不是 bat 直接加载）；"
            "细节见解压目录 README_安装_中文.txt。"
        ),
        "install_launch_hint": (
            "怎么进游戏：完全退出后，双击 Game 目录里的 Start_Convergence_ME3.bat"
            "（或你平时用法魂进游戏的那个）。不要直接开 eldenring.exe。"
        ),
        "install_fail_title": "安装失败",
        "uninstall_title": "卸下接线",
        "uninstall_body": (
            "将撤下启动配置里本模组的标记，并删除拾取相关文件。\n"
            "不会删除已经生成的换怪地图。\n继续？"
        ),
        "uninstall_ok": "已卸下",
        "uninstall_fail": "卸下失败",
        "install_gate_title": "还没接到游戏",
        "install_gate_body": (
            "请先打开「安装到游戏」页，选好游戏文件夹，点「安装本模组到游戏」。\n"
            "没接好时不能开始生成。"
        ),
        "notice": "提示",
        "ok": "好的",
        "error": "出错",
        "warn": "注意",
        # items
        "items_strict_frame": "区域混合程度（仅地上物品）",
        "items_strict_label": "本区 / 全区混合",
        "items_strict_0": "0 = 尽量只用本区物品",
        "items_strict_1": "1 = 全区混合",
        "items_cats_frame": "要参与随机的物品种类",
        "items_region_frame": "各地区物品池",
        "items_col_region": "区域",
        "items_col_slots": "捡取点",
        "items_col_local": "本区物品",
        "items_col_pool": "可用池",
        "items_region_count": "共 {n} 个区域",
        "items_region_hint": "整张地图一池；可用池会随混合程度变化。",
        "items_refresh": "刷新地区统计",
        "items_spoiler": "打开物品对照表（生成后）",
        "items_total_row": "合计（混合 {strict:.2f}）",
        "items_goods_frame": "道具种类（不勾选=保持原样；野外光柱采集不随机）",
        "items_select_all": "全选",
        "items_select_none": "全不选",
        "items_preset_pillar": "光柱常用",
        "items_preset_safe": "保守（不含强化石）",
        "items_dlc_frame": "资料片",
        "items_dlc_check": "幽影之地（资料片）物品也参与随机（关掉后资料片区域地上物品不参与）",
        "goods_quest": "任务",
        "goods_important": "重要道具",
        "goods_upgrade": "强化材料",
        "goods_craft": "杂项",
        "items_spoiler_empty": "还没有对照表，请先生成地上物品随机。",
        "items_gen_fail": "物品生成失败",
        "items_deploy_fail": "物品写入游戏失败",
        "items_need_gen": "请先生成随机表。",
        "items_deploy_done_title": "写入完成",
        "items_deploy_done": "已写入：\n{path}\n\n完全退出游戏再进才会生效。",
        "items_summary": "物品：种子 {seed}，改动 {lots} 个捡取点，已写入游戏。",
        "log_items": "—— 物品 ——",
        "log_seed": "种子: {seed}",
        "log_lots": "改动捡取点: {n}",
        "log_slots_kept": "保持原样: {n}",
        "log_pool": "道具池大小: {n}",
        "log_unique": "唯一物品: {covered} / 池内 {pool}",
        "log_strict": "区域混合: {strict:.2f}",
        "log_map": "结果表: {path}",
        "log_deployed": "已写入游戏: {path}",
        "cat_weapon": "武器",
        "cat_armor": "护甲",
        "cat_magic": "法术（祷告·骨灰·战灰）",
        "cat_talisman": "护符（不进池）",
        "cat_ash": "战灰（已并入法术）",
        # enemies
        "enemy_scan": "扫描游戏地图",
        "enemy_restore": "恢复原版怪物",
        "enemy_spoiler": "查看替换列表",
        "enemy_stats": "可替换怪物数：—    已扫描地图：—    上次生成：—",
        "enemy_stats_fmt": "可替换怪物数：{slots}    已扫描地图：{maps}    上次生成：{last}",
        "enemy_weights_frame": "怪物替换概率（%）",
        "enemy_preset_same": "保持同类",
        "enemy_preset_avg": "平均分配",
        "enemy_preset_weak": "范例：小怪变强怪",
        "enemy_preset_smooth": "流畅（少首领）",
        "enemy_preset_fill": "补齐每行到 100%",
        "enemy_preset_clear": "清空",
        "enemy_weights_hint": (
            "首领类合计建议不超过约 15%；大体型、龙类、飞龙、重要剧情人物不参与随机。列号："
        ),
        "enemy_col_from": "原本是",
        "enemy_col_to": "会变成（%）",
        "enemy_col_sum": "合计",
        "enemy_edit_hint": "提示：只改概率最大的格子来凑满 100%。绿色=100%，橙色=未满，红色=超过 100%。",
        "enemy_options": "选项",
        "enemy_rune_title": "击败后得到的卢恩",
        "enemy_rune_keep": "沿用原位置的卢恩量",
        "enemy_rune_donor": "按换上的怪默认卢恩量",
        "enemy_diff_title": "怪物难度",
        "enemy_diff_auto": "按地图自动对齐（周目由游戏自己处理）",
        "enemy_diff_mult": "难度倍率",
        "enemy_diff_mult_hint": "（在自动对齐上再乘）",
        "enemy_diff_guide": "推荐：0.25 新手 · 0.5 正常 · 0.75 困难 · ≥1 地狱",
        "enemy_diff_band_novice": "新手",
        "enemy_diff_band_normal": "正常",
        "enemy_diff_band_hard": "困难",
        "enemy_diff_band_hell": "地狱",
        "enemy_map_filter": "只生成这一张图（留空=全部地图）",
        "enemy_map_filter_hint": "  留空 = 全部地图",
        "enemy_trash": "路边小怪",
        "enemy_elite": "精英",
        "enemy_minor_boss": "洞穴/副本首领",
        "enemy_evergaol": "场地首领",
        "enemy_night": "红灵",
        "enemy_major_boss": "主线大首领",
        "include_dlc": "包含资料片内容",
        "enemy_need_weights": "请至少为一个「原本是」类别填写大于 0 的概率。",
        "enemy_need_scan": "还没扫描地图。请先点「扫描游戏地图」再生成。",
        "enemy_bad_seed": "种子必须是整数。",
        "enemy_scan_fail": "扫描失败",
        "enemy_restore_none": "当前已是原版怪物，无需恢复。",
        "enemy_restore_ask_title": "确认恢复",
        "enemy_restore_ask": "将删除已装上的随机怪物，恢复为法魂原版怪物。\n是否继续？",
        "enemy_spoiler_empty": "请先生成一次，再查看替换列表。",
        "enemy_summary": "怪物：种子 {seed}，替换 {slots} 处 → 写入 {patched} 处 / {maps} 张地图",
        "install_log_dir": "目录: {path}",
        "install_log_er": "法环: {detail}",
        "install_log_cnv": "法魂: {detail}",
        "install_log_signals": "迹象: {signals}",
        "install_log_proc_none": "进程: 未检测到法环启动器在跑",
        "install_log_preview": "--- 预览 ---",
        "install_log_installed": "已装判定: {yes}",
        "yes": "是",
        "no": "否",
        # maintainer (hidden in release)
        "maint_lab": "门前试验台",
        "maint_offline": "离线表入库",
        "maint_f6f7": "调试快捷键索引",
        "maint_reexport": "重建可换怪缓存",
    },
    "en": {
        "app_title": "Randomizer for all — enemies & world pickups",
        "lang_label": "Language",
        "seed": "Seed",
        "random_seed": "New random seed",
        "auto_new_seed": "New seed every generate",
        "save_settings": "Save settings",
        "generate": "Generate",
        "test_generate": "Test generate (lists only)",
        "open_output": "Open results folder",
        "ready": "Ready",
        "page_items": "Randomize items",
        "page_enemies": "Randomize enemies",
        "tab_install": "Install mod into game",
        "tab_items": "Items",
        "tab_enemies": "Enemies",
        "hint_release": 'Click "Generate" to write into the game. Turn on "New seed every generate" so results stay fresh.',
        "hint_maintainer": 'Test generate only writes lists, not game maps. For real play use "Generate".',
        "gen_will": "This run will include: ",
        "gen_none": "This run will include: (nothing — tick Randomize items/enemies on the tabs)",
        "boot_log": (
            "Randomizer for all · Convergence 3.0 only for now (vanilla / other big mods later).\n"
            'Use "Install into game" first, then "Generate".\n'
            "Pickups: chests, corpses, and similar world loot get shuffled.\n"
            'Enemies: open-world and dungeon foes change; scan maps on the Enemies tab first.\n'
            "After generate, fully quit the game and launch again.\n"
        ),
        "maintainer_on": "Dev tools: on (lab / list-only generate / debug buttons)",
        "saved": "Saved",
        "saved_to": "Settings saved to:\n{path}",
        "install_req_er": "Required Elden Ring: {ver}",
        "install_req_cnv": "Required Convergence: {ver}",
        "install_intro": (
            "Connect this mod to your game (copy files and update the launcher config).\n"
            'This does not install the app itself; "Generate" is a separate step.\n'
            "Randomizer for all · Convergence 3.0 only for now."
        ),
        "install_game_dir": "Game folder:",
        "browse": "Browse…",
        "install_force": "Force install even if version warnings appear",
        "install_detect": "Check",
        "install_run": "Install mod into game",
        "install_uninstall": "Remove mod wiring",
        "install_open": "Open game folder",
        "install_log_title": "Check / preview / results:",
        "install_pick_title": "Pick the Game folder (contains eldenring.exe)",
        "install_status_ok": "Status: installed (you can Generate)",
        "install_status_need": "Status: not installed — Generate is blocked",
        "install_status_ok_saved": "Status: installed (saved folder: {path})",
        "install_status_none": "Status: no game folder / not installed",
        "install_need_dir": "Please pick a valid Game folder first.",
        "install_blocked": "Cannot install now",
        "install_ver_warn": "Version notice",
        "install_ver_force_hint": '\n\nTo try anyway, tick "Force install…" and click Install again.',
        "install_confirm_title": "Confirm install into game",
        "install_confirm_body": "These changes will be written / confirmed:\n\n{preview}",
        "install_force_prefix": "[Forced install]\n{warnings}\n\n",
        "install_done_title": "Install complete",
        "install_done_body": (
            "The mod is connected to your game "
            "(it updates Convergence/ME3 config; it does not add a new launcher).\n\n"
            "Next:\n"
            '1. Click "Generate" in this app.\n'
            "2. When generate finishes, fully quit the game (also from the taskbar).\n"
            "3. Launch the same way you normally start Convergence — often\n"
            "   Start_Convergence_ME3.bat in the Game folder.\n\n"
            "Do not start eldenring.exe alone; use the Convergence/ME3 launch path "
            "or the randomizer will not load.\n\n"
            "Manual wiring / custom .bat: pickup DLL is "
            "Game\\mod\\dll\\cnv_pickup_hook.dll "
            "(loaded via natives in me3\\convergence.me3, not by the .bat). "
            "See README_Install_EN.txt in the unzipped folder."
        ),
        "install_launch_hint": (
            "How to launch: fully quit, then run Start_Convergence_ME3.bat in the Game folder "
            "(or your usual Convergence launcher). Do not start eldenring.exe alone."
        ),
        "install_fail_title": "Install failed",
        "uninstall_title": "Remove wiring",
        "uninstall_body": (
            "This removes this mod's launcher entries and pickup files.\n"
            "Generated enemy map overlays are kept.\nContinue?"
        ),
        "uninstall_ok": "Removed",
        "uninstall_fail": "Remove failed",
        "install_gate_title": "Not installed yet",
        "install_gate_body": (
            'Open "Install into game", pick your Game folder, then Install.\n'
            "Generate stays blocked until that is done."
        ),
        "notice": "Notice",
        "ok": "OK",
        "error": "Error",
        "warn": "Notice",
        "items_strict_frame": "Area mix (pickups only)",
        "items_strict_label": "Local / global mix",
        "items_strict_0": "0 = prefer this area's items",
        "items_strict_1": "1 = mix everywhere",
        "items_cats_frame": "Item types to randomize",
        "items_region_frame": "Pools by area",
        "items_col_region": "Area",
        "items_col_slots": "Pickups",
        "items_col_local": "Local items",
        "items_col_pool": "Usable pool",
        "items_region_count": "{n} areas",
        "items_region_hint": "One world pool; usable size changes with mix.",
        "items_refresh": "Refresh area stats",
        "items_spoiler": "Open pickup list (after generate)",
        "items_total_row": "Total (mix {strict:.2f})",
        "items_goods_frame": "Goods types (unticked = stay original; glowing field harvest stays fixed)",
        "items_select_all": "Select all",
        "items_select_none": "Select none",
        "items_preset_pillar": "Common harvest set",
        "items_preset_safe": "Safe (no upgrade stones)",
        "items_dlc_frame": "DLC",
        "items_dlc_check": "Also randomize Shadow of the Erdtree pickups (off = DLC areas stay original)",
        "goods_quest": "Quest",
        "goods_important": "Key goods",
        "goods_upgrade": "Upgrade materials",
        "goods_craft": "Misc goods",
        "items_spoiler_empty": "No pickup list yet — generate pickups first.",
        "items_gen_fail": "Pickup generate failed",
        "items_deploy_fail": "Failed to write pickups into the game",
        "items_need_gen": "Generate a random table first.",
        "items_deploy_done_title": "Write complete",
        "items_deploy_done": "Wrote:\n{path}\n\nFully quit and relaunch the game to apply.",
        "items_summary": "Pickups: seed {seed}, changed {lots} spots, written into the game.",
        "log_items": "—— Pickups ——",
        "log_seed": "Seed: {seed}",
        "log_lots": "Changed pickups: {n}",
        "log_slots_kept": "Left original: {n}",
        "log_pool": "Goods pool size: {n}",
        "log_unique": "Uniques: {covered} / pool {pool}",
        "log_strict": "Area mix: {strict:.2f}",
        "log_map": "Result table: {path}",
        "log_deployed": "Written into game: {path}",
        "cat_weapon": "Weapons",
        "cat_armor": "Armor",
        "cat_magic": "Spells (incantations · ashes · ashes of war)",
        "cat_talisman": "Talismans (not in pool)",
        "cat_ash": "Ashes of war (merged into spells)",
        "enemy_scan": "Scan game maps",
        "enemy_restore": "Restore original enemies",
        "enemy_spoiler": "Open swap list",
        "enemy_stats": "Swappable foes: —    Maps scanned: —    Last generate: —",
        "enemy_stats_fmt": "Swappable foes: {slots}    Maps scanned: {maps}    Last generate: {last}",
        "enemy_weights_frame": "Enemy swap chances (%)",
        "enemy_preset_same": "Keep same type",
        "enemy_preset_avg": "Even split",
        "enemy_preset_weak": "Example: weak → strong",
        "enemy_preset_smooth": "Smooth (fewer bosses)",
        "enemy_preset_fill": "Fill each row to 100%",
        "enemy_preset_clear": "Clear",
        "enemy_weights_hint": (
            "Boss-type columns: keep total around ≤15%. Huge foes, dragons, and key story characters stay fixed. Columns: "
        ),
        "enemy_col_from": "Was",
        "enemy_col_to": "Becomes (%)",
        "enemy_col_sum": "Total",
        "enemy_edit_hint": "Tip: nudge the biggest cell to reach 100%. Green=100%, orange=under, red=over.",
        "enemy_options": "Options",
        "enemy_rune_title": "Runes on kill",
        "enemy_rune_keep": "Keep the spot's original rune amount",
        "enemy_rune_donor": "Use the new foe's default runes",
        "enemy_diff_title": "Enemy difficulty",
        "enemy_diff_auto": "Auto-match by map (NG+ stays with the game)",
        "enemy_diff_mult": "Difficulty multiplier",
        "enemy_diff_mult_hint": "(extra multiply on top of auto-match)",
        "enemy_diff_guide": "Guide: 0.25 novice · 0.5 normal · 0.75 hard · ≥1 hell",
        "enemy_diff_band_novice": "Novice",
        "enemy_diff_band_normal": "Normal",
        "enemy_diff_band_hard": "Hard",
        "enemy_diff_band_hell": "Hell",
        "enemy_map_filter": "Only this map (leave blank = all maps)",
        "enemy_map_filter_hint": "  Blank = all maps",
        "enemy_trash": "Regular foes",
        "enemy_elite": "Elites",
        "enemy_minor_boss": "Cave / dungeon bosses",
        "enemy_evergaol": "Arena bosses",
        "enemy_night": "Invaders",
        "enemy_major_boss": "Story bosses",
        "include_dlc": "Include DLC content",
        "enemy_need_weights": 'Fill at least one "Was" row with a chance above 0.',
        "enemy_need_scan": 'Maps not scanned yet. Click "Scan game maps" first.',
        "enemy_bad_seed": "Seed must be a whole number.",
        "enemy_scan_fail": "Scan failed",
        "enemy_restore_none": "Already original enemies — nothing to restore.",
        "enemy_restore_ask_title": "Confirm restore",
        "enemy_restore_ask": "This deletes installed randomized enemies and restores Convergence originals.\nContinue?",
        "enemy_spoiler_empty": "Generate once first, then open the swap list.",
        "enemy_summary": "Enemies: seed {seed}, swapped {slots} → wrote {patched} / {maps} maps",
        "install_log_dir": "Folder: {path}",
        "install_log_er": "Elden Ring: {detail}",
        "install_log_cnv": "Convergence: {detail}",
        "install_log_signals": "Signals: {signals}",
        "install_log_proc_none": "Process: game / launcher not running",
        "install_log_preview": "--- Preview ---",
        "install_log_installed": "Installed: {yes}",
        "yes": "yes",
        "no": "no",
        "maint_lab": "Gatefront lab",
        "maint_offline": "Offline table import",
        "maint_f6f7": "Debug hotkey index",
        "maint_reexport": "Rebuild foe cache",
    },
}

_EQUIP_KEYS = {
    "weapon": "cat_weapon",
    "armor": "cat_armor",
    "magic": "cat_magic",
    "talisman": "cat_talisman",
    "ash": "cat_ash",
}
_ENEMY_KEYS = {
    "trash": "enemy_trash",
    "elite": "enemy_elite",
    "minor_boss": "enemy_minor_boss",
    "evergaol": "enemy_evergaol",
    "night": "enemy_night",
    "major_boss": "enemy_major_boss",
}


def get_ui_lang() -> str:
    return _UI_LANG if _UI_LANG in STRINGS else "zh"


def set_ui_lang(lang: str) -> str:
    global _UI_LANG
    _UI_LANG = lang if lang in STRINGS else "zh"
    return _UI_LANG


def t(key: str, **kwargs: Any) -> str:
    lang = get_ui_lang()
    text = STRINGS.get(lang, STRINGS["zh"]).get(key) or STRINGS["zh"].get(key) or key
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, ValueError):
            return text
    return text


def equip_label(cat: str) -> str:
    key = _EQUIP_KEYS.get(cat)
    return t(key) if key else cat


def enemy_pool_label(cat: str) -> str:
    key = _ENEMY_KEYS.get(cat)
    return t(key) if key else cat


def category_labels_map() -> dict[str, str]:
    return {k: equip_label(k) for k in _EQUIP_KEYS}


def enemy_category_labels_map() -> dict[str, str]:
    return {k: enemy_pool_label(k) for k in _ENEMY_KEYS}
