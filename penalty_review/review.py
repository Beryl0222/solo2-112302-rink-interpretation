"""复议席：核对确认、消除或保留分叉、判定影响范围。

规则：
- 口译转述（REPORTED）要有确认意见印证才生效；领队申请（CLAIMED）不生效。
- 能确认裁决但对象歧义未消除时，保留分叉，不写入可执行恢复单。
- 同一停表点前后的句子，按记分席的节次与倒数时钟核对是否在说
  同一次接触、补判，还是另一场的记录。
"""
from __future__ import annotations

from typing import Optional

from . import lexicon as L
from .models import (
    Action,
    Correction,
    Fork,
    Impact,
    Mood,
    ReviewResult,
    Scope,
    Segment,
    SegmentStatus,
)
from .parsing import ParsedCorpus


def run_review(parsed: ParsedCorpus, game: Optional[str] = None) -> ReviewResult:
    corrections = [c for c in parsed.corrections if not c.scope_only and c.action]
    confirmed = [c for c in corrections if c.mood is Mood.CONFIRMED]
    if game is None:
        games = sorted({c.game for c in confirmed if c.game})
        game = games[0] if games else next(iter(parsed.clocks))
    log = parsed.clocks[game]
    result = ReviewResult(game=game, period=log.period, stoppage=log.stoppage)

    effective = _confirm(corrections, confirmed, result)
    effective = _resolve_or_fork(effective, parsed, result)
    result.effective = effective
    _apply(effective, parsed, result)
    _set_statuses(parsed, game, log)
    result.impacts = _impacts(parsed, game, log)
    result.alignment_notes = _alignment(parsed, game, log)
    result.untouched_notes = _untouched(parsed, game, effective)
    return result


def _compatible(confirmed: Correction, reported: Correction) -> bool:
    if confirmed.game != reported.game:
        return False
    if confirmed.action != reported.action or confirmed.category != reported.category:
        return False
    if reported.team and confirmed.team and reported.team != confirmed.team:
        return False
    if reported.number and confirmed.number and reported.number != confirmed.number:
        return False
    return True


def _confirm(corrections, confirmed, result: ReviewResult) -> list[Correction]:
    effective: list[Correction] = list(confirmed)
    for c in corrections:
        if c.mood is Mood.CONFIRMED:
            continue
        if c.mood is Mood.CLAIMED:
            result.forks.append(Fork(c, reasons=["仅为领队申请，未获裁判确认"]))
            continue
        match = next((k for k in confirmed if _compatible(k, c)), None)
        if match:
            result.corroborations.append((c, match))
            effective.append(c)
        else:
            result.forks.append(Fork(c, reasons=["口译转述未获裁判确认"]))
    return effective


def _resolvability(c: Correction, parsed: ParsedCorpus) -> tuple[list[str], list]:
    """检查对象是否唯一确定；返回（问题列表, 候选列表）。可唯一确定时回填。"""
    problems, candidates = [], []
    if c.game is None:
        problems.append("缺少场次/节次/时钟锚点")
    if c.number is not None and c.team is None:
        games = [c.game] if c.game else sorted(parsed.rosters)
        for g in games:
            roster = parsed.rosters.get(g)
            if not roster:
                continue
            for team in roster.teams_with_number(c.number):
                candidates.append((g, team, c.number))
        if len(candidates) > 1:
            problems.append("对象歧义：号码跨队或跨场重复")
        elif not candidates:
            problems.append("号码不在名册")
        else:
            c.game, c.team = candidates[0][0], candidates[0][1]
    if c.team is None and c.number is None and not c.all_penalties:
        problems.append("缺少处罚对象")
    return problems, candidates


def _resolve_or_fork(effective, parsed, result: ReviewResult) -> list[Correction]:
    """确认与可解析是两道关：任一不过都进分叉，不进可执行恢复单。"""
    still = []
    for c in effective:
        problems, candidates = _resolvability(c, parsed)
        if problems:
            reasons = (["裁决已确认，但对象歧义未消除"] if c.mood is Mood.CONFIRMED else []) + problems
            result.forks.append(Fork(c, reasons=reasons, candidates=candidates))
        else:
            still.append(c)
    for fork in result.forks:
        problems, candidates = _resolvability(fork.correction, parsed)
        for p in problems:
            if p not in fork.reasons:
                fork.reasons.append(p)
        if not fork.candidates:
            fork.candidates = candidates
    return still


def _select_segments(parsed: ParsedCorpus, c: Correction, game: str) -> list[Segment]:
    target_game = c.game or game
    out = []
    for seg in parsed.segments.values():
        if seg.game != target_game:
            continue
        if c.team and seg.team != c.team:
            continue
        if c.category and seg.category != c.category:
            continue
        if c.number and seg.offender_no != c.number:
            continue
        out.append(seg)
    return out


def _apply(effective, parsed, result: ReviewResult) -> None:
    seen = set()
    for c in effective:
        if c.action is Action.SHORTEN:
            # “不用坐满”即便成立，也要复议席给出新的起算时点才能执行。
            result.forks.append(Fork(c, reasons=["缩短幅度与新起算时点未定，待复议席定时"]))
            continue
        signature = (c.game, c.team, c.category, c.action)
        if signature in seen:
            continue
        seen.add(signature)
        for seg in _select_segments(parsed, c, result.game):
            if c.action is Action.LIFT:
                seg.status = SegmentStatus.LIFTED
            elif c.action is Action.UPHOLD:
                seg.upheld = True


def _set_statuses(parsed: ParsedCorpus, game: str, log) -> None:
    for seg in parsed.segments.values():
        if seg.game != game or seg.status is SegmentStatus.LIFTED:
            continue
        start = log.starts.get(seg.key)
        # 倒数钟：起算点读数大于停表点，说明该段在停表前已开始计时。
        seg.status = SegmentStatus.ACTIVE if (start is not None and start > log.stoppage) else SegmentStatus.QUEUED


def _elapsed(seg: Segment, log) -> int:
    return log.starts[seg.key] - log.stoppage


def _impacts(parsed: ParsedCorpus, game: str, log) -> list[Impact]:
    """同时判断三类影响面：计时中的主罚、排队的后续罚、替代服罚人。"""
    segments = [s for s in parsed.segments.values() if s.game == game]
    lifted = [s for s in segments if s.status is SegmentStatus.LIFTED]
    impacts: list[Impact] = []

    main_entries = []
    for seg in segments:
        if seg.category.value != "main":
            continue
        if seg.status is SegmentStatus.ACTIVE and seg.upheld:
            elapsed = _elapsed(seg, log)
            main_entries.append(Impact(
                Scope.MAIN_IN_PROGRESS, False,
                f"{seg.key} 主罚维持：停表前已走 {L.format_clock(elapsed)} 不重播，"
                f"余 {L.format_clock(seg.duration - elapsed)}",
            ))
        elif seg.status is SegmentStatus.LIFTED and seg.key in log.starts:
            main_entries.append(Impact(Scope.MAIN_IN_PROGRESS, True, f"{seg.key} 计时中的主罚被撤销"))
    impacts.extend(main_entries or [Impact(Scope.MAIN_IN_PROGRESS, False, "无涉及段")])

    queued = [s for s in lifted if s.queue_after]
    impacts.extend(
        Impact(Scope.QUEUED_FOLLOW_UP, True, f"{s.key} 排队后续段取消，不再起算") for s in queued
    )
    if not queued:
        impacts.append(Impact(Scope.QUEUED_FOLLOW_UP, False, "无涉及段"))

    substitutes = [s for s in lifted if s.substitute]
    impacts.extend(
        Impact(Scope.SUBSTITUTE_SERVER, True, f"替代服罚人 {s.team}{s.server_no}号 释放，即刻可上场")
        for s in substitutes
    )
    if not substitutes:
        impacts.append(Impact(Scope.SUBSTITUTE_SERVER, False, "无涉及段"))
    return impacts


def _alignment(parsed: ParsedCorpus, game: str, log) -> list[str]:
    """按节次与倒数时钟核对停表点前后的句子说的是哪一次接触。"""
    notes = []
    for src, g, period, clock in parsed.stoppage_anchors:
        if g != game or period != log.period:
            notes.append(f"{src} 的锚点（{g} 第{period}节）不属于本场本节的停表窗口")
            continue
        if clock == log.stoppage:
            notes.append(f"{src} 停表锚点与记分席 {log.source_id} 一致（第{L.PERIOD_ZH[period]}节 {L.format_clock(clock)}）")
        else:
            notes.append(
                f"{src} 停表锚点 {L.format_clock(clock)} 与记分席 {log.source_id} "
                f"{L.format_clock(log.stoppage)} 不一致，按记分席为准"
            )
    window = sorted(
        {s.ruling_id: s.announced_at for s in parsed.segments.values() if s.game == game}.items(),
        key=lambda kv: -kv[1],
    )
    if window:
        notes.append("同一停表窗口内的判词：" + "、".join(f"{rid}({L.format_clock(t)})" for rid, t in window))
    for g in sorted(parsed.rosters):
        if g != game:
            notes.append(f"{g} 为另一场记录，本次更正不涉及")
    return notes


def _untouched(parsed: ParsedCorpus, game: str, effective) -> list[str]:
    touched = {seg.key for c in effective for seg in _select_segments(parsed, c, game)}
    notes = []
    for seg in parsed.segments.values():
        if seg.game == game and seg.key not in touched:
            notes.append(f"{seg.key}（{seg.team}，接触 {seg.contact_id}）未受本次更正影响，按原计时继续")
    for excl in parsed.exclusions:
        if not any(c.team == excl.team for c in effective):
            notes.append(f"按 {excl.source_id} 要求：{excl.team} 另一回合未并入本次更正")
    return notes
