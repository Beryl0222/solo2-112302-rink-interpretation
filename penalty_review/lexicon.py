"""多语词表与基础文本工具。

词表按本次邀请赛登记：队名别名、罚种、处罚类别、决定动词与语气标记。
解析器只查这里的登记，不内置硬编码说法；新增队伍或新说法时在此补充。
"""
from __future__ import annotations

import re
from typing import Optional

CN_DIGITS = {
    "零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}


def cn_number(text: str) -> int:
    """把中文数字（含“十”“两”）或阿拉伯数字转成 int。"""
    text = text.strip()
    if text.isdigit():
        return int(text)
    if "十" in text:
        left, _, right = text.partition("十")
        tens = CN_DIGITS[left] if left else 1
        ones = CN_DIGITS[right] if right else 0
        return tens * 10 + ones
    return CN_DIGITS[text]


PERIOD_WORDS = {"一": 1, "二": 2, "三": 3, "四": 4}
PERIOD_ZH = {1: "一", 2: "二", 3: "三", 4: "四"}

# 队名别名（本会登记）：别名 -> 规范队名。英文别名小写登记。
TEAM_ALIASES = {
    "北湾": "北湾",
    "北湾队": "北湾",
    "north": "北湾",
    "north bay": "北湾",
    "林岸": "林岸",
    "林岸队": "林岸",
    "forest shore": "林岸",
    "forest": "林岸",
    "shore": "林岸",
}

# 对外通报用的队名译法。
TEAM_EN = {"北湾": "North Bay", "林岸": "Forest Shore"}

PENALTY_KIND_WORDS = {"小罚": "minor", "大罚": "major", "minor": "minor", "major": "major"}
KIND_ZH = {"minor": "小罚", "major": "大罚"}

# 处罚类别说法。注意：“另小罚”不是附加，必须出现“附加/追加”才算附加段。
SUPPLEMENTARY_WORDS = ("附加", "追加", "added", "additional", "supplementary", "second")
MAIN_WORDS = ("主罚", "原小罚", "原判", "first", "primary", "original")

# 决定动词。
LIFT_WORDS = ("撤掉", "撤销", "取消", "废除", "lift", "rescind", "cancel", "drop", "withdraw")
UPHOLD_WORDS = ("维持", "仍有效", "保持", "keep", "stand", "stands", "uphold")
SHORTEN_WORDS = ("不用坐满", "不必坐满", "无需坐满", "need not serve full", "not serve full")

# 语气标记：出现即说明该句只是领队申请，不是裁判确认。
CLAIM_MARKERS = ("领队提出", "领队申请", "领队要求", "claims", "claimed", "request")

# 替代服罚/班席说法。
BENCH_WORDS = ("班席", "代坐", "bench", "substitute")

ALL_PENALTIES_WORDS = ("所有处罚", "全部处罚", "所有", "全部")

CLOCK_RE = re.compile(r"(\d{1,2}):(\d{2})")


def parse_clock(text: str) -> Optional[int]:
    """从文本里取第一个 MM:SS 时钟，转成剩余秒数。"""
    m = CLOCK_RE.search(text)
    if not m:
        return None
    return int(m.group(1)) * 60 + int(m.group(2))


def format_clock(seconds: int) -> str:
    return f"{seconds // 60:02d}:{seconds % 60:02d}"
