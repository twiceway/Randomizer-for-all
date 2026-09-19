"""导出「目标难度曲线」矩阵 → reports/敌人难度成长审计.md §7

用户上限（NG+7 · T9）：
  有效血（葛瑞克参照）150000
  韧性 200%
  攻击倍率 150%
  击杀卢恩 1000%
中间值：线性插值；地图档权重 0.35 · 周目权重 0.65（压低 T1→T9 陡度）。
"""

from __future__ import annotations

from pathlib import Path

REPORT = Path(__file__).resolve().parents[1] / "reports" / "敌人难度成长审计.md"
MARKER = "## 7. 目标难度曲线（用户上限 · 线性插值）"

# 进度：0@T1·一周目 → 1@T9·NG+7；周目权重大 → T1-9 涨得慢
W_TIER = 0.35
W_NG = 0.65

# 上限（相对 T1·一周目 = 100%，血量用葛瑞克绝对锚）
CAP_POISE = 2.0  # 200%
CAP_ATK = 1.5  # 150%
CAP_RUNE = 10.0  # 1000%
CAP_HP_GODRICK = 150_000

# T1·一周目 锚点（目标曲线起点，不用现网 lift 后虚高值）
# 葛瑞克：基血5500×1.05×T1区域≈3.34 → ~1.93万；取整 2.0 万作可读起点
HP0_GODRICK = 20_000
# 混种：基血531×1.05×3.34 → ~1860；与现网 T1 一周目接近
HP0_TRASH = 1_860
# 卢恩起点
RUNE0_GODRICK = 20_000
RUNE0_TRASH = 416


def progress(tier: int, ng: int) -> float:
    u = (tier - 1) / 8.0
    v = ng / 7.0
    return W_TIER * u + W_NG * v


def lerp_factor(cap: float, tier: int, ng: int) -> float:
    """T1·一周目 = 1.0；T9·NG+7 = cap。"""
    return 1.0 + (cap - 1.0) * progress(tier, ng)


def matrix(cell_fn) -> str:
    headers = ["一周目", "NG+1", "NG+2", "NG+3", "NG+4", "NG+5", "NG+6", "NG+7"]
    lines = [
        "| 地图档 | " + " | ".join(headers) + " |",
        "|--------|" + "|".join(["--------:"] * 8) + "|",
    ]
    for t in range(1, 10):
        label = f"T{t}" + ("（=T8顶）" if t == 9 else "")
        cells = [cell_fn(t, ng) for ng in range(8)]
        lines.append("| **" + label + "** | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def num(x: float) -> str:
    return f"{int(round(x))}"


def build() -> str:
    # 验收：T9 NG7
    assert abs(progress(9, 7) - 1.0) < 1e-9
    assert abs(lerp_factor(CAP_ATK, 9, 7) - CAP_ATK) < 1e-9
    hp_max = HP0_GODRICK * lerp_factor(CAP_HP_GODRICK / HP0_GODRICK, 9, 7)
    assert abs(hp_max - CAP_HP_GODRICK) < 1.0

    hp_cap_ratio = CAP_HP_GODRICK / HP0_GODRICK  # 7.5×

    parts = [
        MARKER,
        "",
        "**状态**：口径已接线（2026-08-08）· `enemy_difficulty.target_progression_curve`  ",
        "**上限（你拍的）**：NG+7 · T9 → 有效血 **15 万**（葛瑞克参照）· 韧 **200%** · 攻 **150%** · 卢恩 **1000%**  ",
        "**插值**：`进度 = 0.35×(档-1)/8 + 0.65×周目/7`；倍率 = `1 + (上限-1)×进度`  ",
        "**为何 0.35/0.65**：你嫌 T1→T9 太陡，所以地图档只占约三成，周目约占六成半。",
        "",
        "### 怎么读",
        "",
        "- **% 表**：相对 **T1 · 一周目 = 100%**（该怪自己的起点）。",
        "- **血量表**：葛瑞克绝对血；混种用**同一相对倍率**（不是 15 万）。",
        "- 现网葛瑞克 T9·NG7 ≈ **60 万**（区域倍 × T-062 lift 叠高）；目标压到 **15 万**。",
        "",
        "### 进度样例（一眼看权重）",
        "",
        "| 点 | 进度 | 相对 T1·一周目 |",
        "|----|------|----------------|",
        f"| T1 · 一周目 | {progress(1,0):.0%} | 起点 |",
        f"| T9 · 一周目 | {progress(9,0):.0%} | 只涨地图档 |",
        f"| T1 · NG+7 | {progress(1,7):.0%} | 只涨周目 |",
        f"| T9 · NG+7 | {progress(9,7):.0%} | **上限** |",
        "",
        "---",
        "",
        "## A′. 混种小怪 · 目标",
        "",
        f"起点：有效血 **{HP0_TRASH}** · 卢恩 **{RUNE0_TRASH}**（T1·一周目 = 100%）",
        "",
        "### 混种 · 目标表1 · 有效血",
        "",
        matrix(lambda t, n: num(HP0_TRASH * lerp_factor(hp_cap_ratio, t, n))),
        "",
        "### 混种 · 目标表4 · 韧性（相对%）",
        "",
        matrix(lambda t, n: pct(lerp_factor(CAP_POISE, t, n))),
        "",
        "### 混种 · 目标表5 · 攻击倍率（相对%）",
        "",
        matrix(lambda t, n: pct(lerp_factor(CAP_ATK, t, n))),
        "",
        "### 混种 · 目标表7 · 击杀卢恩",
        "",
        matrix(lambda t, n: num(RUNE0_TRASH * lerp_factor(CAP_RUNE, t, n))),
        "",
        "---",
        "",
        "## B′. 接肢葛瑞克 · 目标",
        "",
        f"起点：有效血 **{HP0_GODRICK}** · 卢恩 **{RUNE0_GODRICK}**（T1·一周目 = 100%）  ",
        f"上限：T9·NG+7 有效血 **{CAP_HP_GODRICK}**（={hp_cap_ratio:.1f}× 起点）",
        "",
        "### 葛瑞克 · 目标表1 · 有效血",
        "",
        matrix(lambda t, n: num(HP0_GODRICK * lerp_factor(hp_cap_ratio, t, n))),
        "",
        "### 葛瑞克 · 目标表4 · 韧性（相对%）",
        "",
        matrix(lambda t, n: pct(lerp_factor(CAP_POISE, t, n))),
        "",
        "### 葛瑞克 · 目标表5 · 攻击倍率（相对%）",
        "",
        matrix(lambda t, n: pct(lerp_factor(CAP_ATK, t, n))),
        "",
        "### 葛瑞克 · 目标表7 · 击杀卢恩",
        "",
        matrix(lambda t, n: num(RUNE0_GODRICK * lerp_factor(CAP_RUNE, t, n))),
        "",
        "---",
        "",
        "### 实现备忘（确认前不改码）",
        "",
        "| 项 | 现网问题 | 目标落地思路（待拍板） |",
        "|----|----------|------------------------|",
        "| 有效血 60万→15万 | T-062 对 `major_boss` lift 过大 + 区域倍偏陡 | ① Boss 池降/关 lift ② 压 T1→T9 血倍曲线 ③ 仍可叠引擎 ClearCount |",
        "| 韧性→200% | 表现在锚点/复制行；两示例基韧常为 0 | 按进度线性抬 `defFlickPower` 或韧锚点 |",
        "| 攻击→150% | 引擎 NG7 已约 ×1.45；小怪另加 sp | 总倍率封顶约 1.5；少叠 mod 加攻 |",
        "| 卢恩→1000% | 现只随地图档，**不随周目** | 复制行卢恩按同一进度式涨到 10× |",
        "",
        "*生成：`python cnv_randomizer/_export_target_difficulty_curves.py`*",
        "",
    ]
    return "\n".join(parts)


def main() -> None:
    text = REPORT.read_text(encoding="utf-8")
    section = build()
    if MARKER in text:
        head = text.split(MARKER, 1)[0].rstrip()
        out = head + "\n\n" + section + "\n"
    else:
        out = text.rstrip() + "\n\n" + section + "\n"
    REPORT.write_text(out, encoding="utf-8")
    print(f"Wrote {MARKER} → {REPORT}")
    # 打印关键验收点
    print(
        "Godrick T9 NG7 HP",
        round(HP0_GODRICK * lerp_factor(CAP_HP_GODRICK / HP0_GODRICK, 9, 7)),
    )
    print("Atk T9 NG7", f"{lerp_factor(CAP_ATK, 9, 7)*100:.0f}%")
    print("Rune T9 NG7 Godrick", round(RUNE0_GODRICK * lerp_factor(CAP_RUNE, 9, 7)))
    print("Poise T9 NG7", f"{lerp_factor(CAP_POISE, 9, 7)*100:.0f}%")
    print("Godrick T9 NG0 HP", round(HP0_GODRICK * lerp_factor(CAP_HP_GODRICK / HP0_GODRICK, 9, 0)))
    print("Godrick T1 NG7 HP", round(HP0_GODRICK * lerp_factor(CAP_HP_GODRICK / HP0_GODRICK, 1, 7)))


if __name__ == "__main__":
    main()
