"""把语料记录解析为结构化对象。

解析分两步：先读场次（match）建立名册，再处理判词、口译、时钟摘录、
复议来文与已发界面。所有多语说法来自 lexicon 词表。

关键约定：
- 每条决定意见都带决定语气（Mood）：判词与“复议原话”是确认，
  口译是转述，领队提出的是申请；同一段里可以混着出现，逐句判定。
- 口译中新出现的姓名只登记为“未登记姓名”，绝不用来改写裁判原文。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from . import lexicon as L
from .models import (
    Action,
    Category,
    ClockLog,
    Correction,
    Exclusion,
    Interface,
    Kind,
    Mood,
    Roster,
    Segment,
)

GAME_RE = re.compile(r"\b(m\d+)\b")
PERIOD_RE = re.compile(r"第([一二三四1-4])节")
TEAM_NUM_RE = re.compile(r"([A-Za-z一-龥]+?)队?\s*(\d{1,2})\s*号")
NUMBER_ZH_RE = re.compile(r"(\d{1,2})\s*号")
NUMBER_EN_RE = re.compile(r"#(\d{1,2})")
ROSTER_RE = re.compile(r"([A-Za-z一-龥]+?)队?\s*(\d{1,2})\s*号\s*为\s*([A-Za-z一-龥]+)")
DURATION_RE = re.compile(r"([零一二两三四五六七八九十\d]+)\s*分钟")
SUBSTITUTE_RE = re.compile(r"班席由\s*([A-Za-z一-龥]+?)队?\s*(\d{1,2})\s*号\s*代坐\s*(后段|前段)")
CLAIM_QUOTE_RE = re.compile(r"领队(?:提出|申请|要求)\s*[“\"](.+?)[”\"]")
EXCLUSION_RE = re.compile(r"不要把\s*(.+?)\s*(?:另一回合)?\s*算进去")
START_RE = re.compile(r"(\d{1,2}:\d{2})\s*起算\s*(r\d+)(?:\s*(主罚|附加))?")
STOP_RE = re.compile(r"(\d{1,2}:\d{2})\s*停止计时")
RULING_REF_RE = re.compile(r"r\d+")
NAME_PAREN_RE = re.compile(r"（([一-龥]{2,3})）")
NAME_ZHI_RE = re.compile(r"为\s*([一-龥]{2,3})")

RULING_SENT_SPLIT = re.compile(r"[。；]")
CLAUSE_SPLIT = re.compile(r"[。；;，,.!！]")


@dataclass
class ParsedCorpus:
    """全部记录解析后的结构化结果。"""

    rosters: dict[str, Roster] = field(default_factory=dict)
    segments: dict[str, Segment] = field(default_factory=dict)
    clocks: dict[str, ClockLog] = field(default_factory=dict)
    corrections: list[Correction] = field(default_factory=list)
    exclusions: list[Exclusion] = field(default_factory=list)
    interfaces: list[Interface] = field(default_factory=list)
    stoppage_anchors: list[tuple[str, str, int, int]] = field(default_factory=list)
    unresolved_names: list[tuple[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    aliases: dict[str, str] = field(default_factory=dict)


def parse_corpus(data: dict) -> ParsedCorpus:
    """解析 load_corpus() 读出的全部记录。"""
    parsed = ParsedCorpus()
    records = data["records"]
    for rec in records:  # 先建名册，后面的解析要用队名
        if rec["kind"] == "match":
            _parse_match(rec, parsed)
    parsed.aliases = _build_aliases(parsed.rosters)
    for rec in records:
        kind = rec["kind"]
        if kind == "match":
            continue
        if kind == "ruling":
            _parse_ruling(rec, parsed)
        elif kind == "interpretation":
            _parse_interpretation(rec, parsed)
        elif kind == "clock":
            _parse_clock(rec, parsed)
        elif kind == "appeal":
            _parse_appeal(rec, parsed)
        elif kind == "release":
            _parse_release(rec, parsed)
        else:
            parsed.warnings.append(f"未知记录类别：{kind}（{rec['id']}）")
    return parsed


def _build_aliases(rosters: dict[str, Roster]) -> dict[str, str]:
    aliases = dict(L.TEAM_ALIASES)
    for roster in rosters.values():
        for team in roster.teams:
            aliases[team] = team
            aliases[team + "队"] = team
    return aliases


def _split_header(text: str) -> tuple[str, str]:
    parts = re.split(r"[|｜]", text, maxsplit=1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return "", text.strip()


def _game_of(head: str) -> Optional[str]:
    m = GAME_RE.search(head)
    return m.group(1) if m else None


def _period_of(head: str) -> Optional[int]:
    m = PERIOD_RE.search(head)
    if not m:
        return None
    token = m.group(1)
    return int(token) if token.isdigit() else L.PERIOD_WORDS[token]


def _canonical_team(token: str, aliases: dict[str, str]) -> Optional[str]:
    """把句中抓到的队名片段归一到规范队名，允许“由北湾”这类前缀。"""
    token = token.strip()
    for i in range(len(token)):
        sub = token[i:]
        for cand in (sub, sub[:-1] if sub.endswith("队") else sub + "队", sub.lower()):
            if cand in aliases:
                return aliases[cand]
    return None


def _find_team(text: str, aliases: dict[str, str]) -> Optional[str]:
    for alias in sorted(aliases, key=len, reverse=True):
        if re.search(r"[a-z]", alias):
            if re.search(rf"\b{re.escape(alias)}\b", text, re.IGNORECASE):
                return aliases[alias]
        elif alias in text:
            return aliases[alias]
    return None


def _find_team_number(text: str, aliases: dict[str, str]) -> tuple[Optional[str], Optional[int]]:
    for m in TEAM_NUM_RE.finditer(text):
        team = _canonical_team(m.group(1), aliases)
        if team:
            return team, int(m.group(2))
    return None, None


def _find_number(text: str) -> Optional[int]:
    m = NUMBER_ZH_RE.search(text) or NUMBER_EN_RE.search(text)
    return int(m.group(1)) if m else None


def _find_duration(text: str) -> Optional[int]:
    m = DURATION_RE.search(text)
    return L.cn_number(m.group(1)) * 60 if m else None


def _find_kind(text: str) -> Kind:
    low = text.lower()
    for word, kind in L.PENALTY_KIND_WORDS.items():
        if word in text or word in low:
            return Kind(kind)
    return Kind.MINOR


def _detect_action(text: str) -> Optional[Action]:
    low = text.lower()
    for word in L.SHORTEN_WORDS:
        if word in text or word in low:
            return Action.SHORTEN
    for word in L.LIFT_WORDS:
        if word in text or word in low:
            return Action.LIFT
    for word in L.UPHOLD_WORDS:
        if word in text or word in low:
            return Action.UPHOLD
    return None


def _detect_category(text: str) -> Optional[Category]:
    low = text.lower()
    for word in L.SUPPLEMENTARY_WORDS:
        if word in text or word in low:
            return Category.SUPPLEMENTARY
    for word in L.MAIN_WORDS:
        if word in text or word in low:
            return Category.MAIN
    return None


def _parse_match(rec: dict, parsed: ParsedCorpus) -> None:
    _, body = _split_header(rec["text"])
    roster = Roster(game=rec["id"], source_id=rec["id"])
    if "同两队" in body:
        # 第二场沿用前一场的两队与号码。
        previous = list(parsed.rosters.values())
        if previous:
            roster.teams = {team: dict(nums) for team, nums in previous[-1].teams.items()}
            roster.period_length = previous[-1].period_length
    for m in ROSTER_RE.finditer(body):
        team = _canonical_team(m.group(1), L.TEAM_ALIASES) or m.group(1).rstrip("队")
        roster.teams.setdefault(team, {})[int(m.group(2))] = m.group(3)
    clock = re.search(r"节内时钟从\s*(\d{1,2}:\d{2})\s*倒数", body)
    if clock:
        roster.period_length = L.parse_clock(clock.group(1))
    parsed.rosters[roster.game] = roster


def _parse_ruling(rec: dict, parsed: ParsedCorpus) -> None:
    head, body = _split_header(rec["text"])
    game, period = _game_of(head), _period_of(head)
    announced = L.parse_clock(head)
    if not (game and period and announced is not None):
        parsed.warnings.append(f"判词缺少场次/节次/时钟：{rec['id']}")
        return
    rid = rec["id"]
    made: list[Segment] = []
    for sentence in RULING_SENT_SPLIT.split(body):
        sentence = sentence.strip()
        if not sentence:
            continue
        sub = SUBSTITUTE_RE.search(sentence)
        if sub:
            _apply_substitute(rec, sub, made, parsed)
            continue
        if any(w in sentence for w in ("附加", "追加")):
            made.append(_make_segment(rec, game, period, announced, sentence, made, parsed,
                                      Category.SUPPLEMENTARY))
            continue
        team, number = _find_team_number(sentence, parsed.aliases)
        if team and number is not None:
            made.append(_make_segment(rec, game, period, announced, sentence, made, parsed,
                                      Category.MAIN, team, number))
            continue
        parsed.warnings.append(f"判词句子未解析：{rec['id']}「{sentence}」")
    for seg in made:
        parsed.segments[seg.key] = seg


def _make_segment(rec, game, period, announced, sentence, made, parsed,
                  category, team=None, number=None) -> Segment:
    rid = rec["id"]
    if category is Category.SUPPLEMENTARY:
        # 附加段承袭前一段的球队与对象，排在其后接续起算。
        prev = made[-1] if made else None
        team = team or (prev.team if prev else None)
        number = number if number is not None else (prev.offender_no if prev else None)
        index = sum(1 for s in made if s.category is Category.SUPPLEMENTARY) + 1
        key = f"{rid}:supplementary" if index == 1 else f"{rid}:supplementary{index}"
    else:
        key = f"{rid}:main"
    seg = Segment(
        key=key,
        ruling_id=rid,
        game=game,
        period=period,
        announced_at=announced,
        team=team,
        offender_no=number,
        server_no=number,
        category=category,
        kind=_find_kind(sentence),
        duration=_find_duration(sentence) or 120,
        queue_after=made[-1].key if (category is Category.SUPPLEMENTARY and made) else None,
        contact_id=rid,
        source_id=rid,
    )
    return seg


def _apply_substitute(rec, sub, made, parsed) -> None:
    team = _canonical_team(sub.group(1), parsed.aliases)
    number = int(sub.group(2))
    which = Category.SUPPLEMENTARY if sub.group(3) == "后段" else Category.MAIN
    for seg in reversed(made):
        if seg.category is which:
            seg.server_no = number
            return
    parsed.warnings.append(f"代坐指定找不到对应段：{rec['id']}")


def _parse_interpretation(rec: dict, parsed: ParsedCorpus) -> None:
    head, body = _split_header(rec["text"])
    game, period = _game_of(head), _period_of(head)
    if game and period and "停表" in head:
        clock = L.parse_clock(head)
        if clock is not None:
            parsed.stoppage_anchors.append((rec["id"], game, period, clock))
    items = _clauses_to_corrections(rec, body, game, Mood.REPORTED, parsed)
    _apply_scope(items)
    parsed.corrections.extend(items)


def _parse_appeal(rec: dict, parsed: ParsedCorpus) -> None:
    head, body = _split_header(rec["text"])
    game = _game_of(head)
    items = []
    for clause in CLAUSE_SPLIT.split(body):
        clause = clause.strip()
        if not clause:
            continue
        excl = EXCLUSION_RE.search(clause)
        if excl:
            team = _canonical_team(excl.group(1), parsed.aliases)
            if team:
                parsed.exclusions.append(Exclusion(rec["id"], team, clause))
            continue
        correction = _clause_to_correction(rec, clause, game, Mood.CONFIRMED, parsed)
        if "那次接触" in clause:
            correction.contact_hint = "那次接触"
        items.append(correction)
    # 同一段来文里只出现一个队时，其余句承袭该队（如“原小罚仍有效”）。
    teams = {c.team for c in items if c.team}
    if len(teams) == 1:
        team = teams.pop()
        for c in items:
            if c.team is None:
                c.team = team
    parsed.corrections.extend(items)


def _clauses_to_corrections(rec, body, game, mood, parsed) -> list[Correction]:
    items = []
    for clause in CLAUSE_SPLIT.split(body):
        clause = clause.strip()
        if not clause:
            continue
        items.append(_clause_to_correction(rec, clause, game, mood, parsed))
    return items


def _clause_to_correction(rec, clause, game, mood, parsed) -> Correction:
    """逐句生成决定意见；同一段里申请与确认可以并存。"""
    text, actual_mood = clause, mood
    quote = CLAIM_QUOTE_RE.search(clause)
    if quote:
        text, actual_mood = quote.group(1), Mood.CLAIMED
    elif any(marker in clause for marker in L.CLAIM_MARKERS):
        actual_mood = Mood.CLAIMED
    team = _find_team(text, parsed.aliases)
    action = _detect_action(text)
    correction = Correction(
        source_id=rec["id"],
        action=action,
        mood=actual_mood,
        game=game,
        team=team,
        number=_find_number(text),
        category=_detect_category(text),
        clause=clause,
        all_penalties=any(w in text for w in L.ALL_PENALTIES_WORDS),
        scope_only=action is None and team is not None,
    )
    _register_name_mentions(rec, clause, game, parsed)
    return correction


def _register_name_mentions(rec, clause, game, parsed) -> None:
    """口译/来文里的姓名只核对名册；新姓名登记留存，不改写裁判原文。"""
    names = [m.group(1) for m in NAME_PAREN_RE.finditer(clause)]
    names += [m.group(1) for m in NAME_ZHI_RE.finditer(clause)]
    for name in names:
        games = [game] if game else list(parsed.rosters)
        known = any(
            name in roster.teams.get(team, {}).values()
            for g in games
            for roster in [parsed.rosters.get(g)]
            if roster
            for team in roster.teams
        )
        if not known:
            parsed.unresolved_names.append((rec["id"], name))


def _apply_scope(items: list[Correction]) -> None:
    """范围句（有队无动作，如 "North second bench only"）把队带给同段其他句。"""
    scope_teams = {c.team for c in items if c.scope_only}
    if len(scope_teams) == 1:
        team = scope_teams.pop()
        for c in items:
            if c.team is None and not c.scope_only:
                c.team = team


def _parse_clock(rec: dict, parsed: ParsedCorpus) -> None:
    head, body = _split_header(rec["text"])
    game, period = _game_of(head), _period_of(head)
    if not (game and period):
        parsed.warnings.append(f"时钟摘录缺少场次/节次：{rec['id']}")
        return
    log = ClockLog(game=game, period=period, source_id=rec["id"])
    for m in START_RE.finditer(body):
        category = "supplementary" if m.group(3) == "附加" else "main"
        log.starts[f"{m.group(2)}:{category}"] = L.parse_clock(m.group(1))
    stop = STOP_RE.search(body)
    if stop:
        log.stoppage = L.parse_clock(stop.group(1))
    if "暂停未消耗" in body:
        log.notes.append("暂停未消耗场上时钟")
    parsed.clocks[game] = log


def _parse_release(rec: dict, parsed: ParsedCorpus) -> None:
    _, body = _split_header(rec["text"])
    parsed.interfaces.append(Interface(
        source_id=rec["id"],
        ruling_ids=RULING_REF_RE.findall(body),
        provisional="临时" in body,
        note=body,
    ))
