"""对外双语通报：只反映裁决真正成立的部分，留存已发界面与出处。"""
from __future__ import annotations

from typing import Optional

from . import lexicon as L
from .models import Bulletin, Category, ResumptionOrder, ReviewResult
from .parsing import ParsedCorpus


def _zh_player(team: str, number: int, name: Optional[str]) -> str:
    return f"{team}{number}号（{name}）" if name else f"{team}{number}号"


def _en_player(team: str, number: int, name: Optional[str]) -> str:
    base = f"{L.TEAM_EN.get(team, team)} #{number}"
    return f"{base} ({name})" if name else base


def build_bulletin(order: ResumptionOrder, review: ReviewResult, parsed: ParsedCorpus) -> Bulletin:
    roster = parsed.rosters.get(order.game)

    def name_of(team, number):
        return roster.name_of(team, number) if roster else None

    zh = [f"【复议后恢复通报】{order.game} 第{L.PERIOD_ZH[order.period]}节 · 停表 {L.format_clock(order.stoppage)}"]
    en = [f"[Post-review resumption bulletin] {order.game} · Period {order.period} · "
          f"clock stopped {L.format_clock(order.stoppage)}"]

    zh.append("一、成立并执行：")
    en.append("1. Confirmed and executable:")
    n = 1
    for line in order.lines:
        seg = parsed.segments[line.segment_key]
        elapsed = seg.duration - line.remaining
        player_zh = _zh_player(line.team, line.server_no, name_of(line.team, line.server_no))
        player_en = _en_player(line.team, line.server_no, name_of(line.team, line.server_no))
        kind_zh = L.KIND_ZH[seg.kind.value]
        if seg.upheld:
            zh.append(f"{n}. {player_zh}主罚{kind_zh}维持：停表前已走 {L.format_clock(elapsed)} 不重播，"
                      f"余 {L.format_clock(line.remaining)}，{L.format_clock(line.resume_at)} 恢复计时，"
                      f"{L.format_clock(line.expire_at)} 刑满。")
            en.append(f"{n}. {player_en}: primary {seg.kind.value} stands — "
                      f"{L.format_clock(elapsed)} already served is not replayed; "
                      f"{L.format_clock(line.remaining)} remains; resumes {L.format_clock(line.resume_at)}, "
                      f"expires {L.format_clock(line.expire_at)}.")
        else:
            zh.append(f"{n}. {player_zh}主罚{kind_zh}未受影响，继续执行：余 {L.format_clock(line.remaining)}，"
                      f"{L.format_clock(line.resume_at)} 恢复计时，{L.format_clock(line.expire_at)} 刑满。")
            en.append(f"{n}. {player_en}: primary {seg.kind.value} unaffected — "
                      f"{L.format_clock(line.remaining)} remains; resumes {L.format_clock(line.resume_at)}, "
                      f"expires {L.format_clock(line.expire_at)}.")
        n += 1
    for key in order.lifted:
        seg = parsed.segments[key]
        player_zh = _zh_player(seg.team, seg.offender_no, name_of(seg.team, seg.offender_no))
        player_en = _en_player(seg.team, seg.offender_no, name_of(seg.team, seg.offender_no))
        zh.append(f"{n}. {player_zh}同次接触的附加{seg.duration // 60}分钟取消：排队后续段不再起算。")
        en.append(f"{n}. {player_en}: the supplementary {seg.duration // 60}-minute segment of the "
                  f"same contact is lifted; the queued follow-up will not start.")
        n += 1
    for e in order.released_now:
        zh.append(f"{n}. {_zh_player(e.team, e.number, name_of(e.team, e.number))}（替代服罚人）即刻恢复上场资格。")
        en.append(f"{n}. {_en_player(e.team, e.number, name_of(e.team, e.number))} "
                  f"(substitute server) is eligible immediately.")
        n += 1
    if order.eligibility:
        zh.append("可上场时点：" + "；".join(
            f"{_zh_player(e.team, e.number, name_of(e.team, e.number))} "
            f"{'即刻' if e.available_at == order.stoppage else L.format_clock(e.available_at)}"
            for e in order.eligibility))
        en.append("Eligible: " + "; ".join(
            f"{_en_player(e.team, e.number, name_of(e.team, e.number))} "
            f"{'immediately' if e.available_at == order.stoppage else 'at ' + L.format_clock(e.available_at)}"
            for e in order.eligibility))

    zh.append("二、尚不能执行（待复核分叉）：")
    en.append("2. Not yet executable (pending review):")
    if order.pending:
        for fork in order.pending:
            cands_zh = "、".join(f"{g}·{t}{num}号" for g, t, num in fork.candidates) or "—"
            cands_en = ", ".join(f"{g} {L.TEAM_EN.get(t, t)} #{num}" for g, t, num in fork.candidates) or "—"
            zh.append(f"- 「{fork.correction.clause}」：{'；'.join(fork.reasons)}。候选：{cands_zh}")
            en.append(f"- \"{fork.correction.clause}\": {'; '.join(fork.reasons)}. Candidates: {cands_en}")
    else:
        zh.append("- 无")
        en.append("- None")

    zh.append("三、已发界面留存：")
    en.append("3. Retained issued interfaces:")
    for note in order.interface_notes:
        zh.append(f"- {note}")
        en.append(f"- {note}")
    if not order.interface_notes:
        zh.append("- 无")
        en.append("- None")

    zh.append("四、出处与核对：")
    en.append("4. Sources and checks:")
    zh.append("- 出处：" + "、".join(order.sources))
    en.append("- Sources: " + ", ".join(order.sources))
    for note in review.alignment_notes:
        zh.append(f"- {note}")
        en.append(f"- {note}")

    return Bulletin(zh_lines=zh, en_lines=en)
