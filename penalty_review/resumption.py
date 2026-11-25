"""比赛恢复记录：按给定停表时点生成可执行恢复单。

原则：
- 异议只成立于附加罚时，主罚先前走过的时间不重播；
- 恢复单保留仍有约束的判罚，重新确定后续起算与可上场人员；
- 待复核分叉只登记为“尚不能执行的范围”，不写入可执行行。
"""
from __future__ import annotations

from .models import (
    Eligibility,
    ResumptionLine,
    ResumptionOrder,
    ReviewResult,
    SegmentStatus,
)
from .parsing import ParsedCorpus


def build_order(parsed: ParsedCorpus, review: ReviewResult) -> ResumptionOrder:
    game, stoppage = review.game, review.stoppage
    log = parsed.clocks[game]
    order = ResumptionOrder(game=game, period=review.period, stoppage=stoppage)

    segments = [s for s in parsed.segments.values() if s.game == game]
    lines_by_key: dict[str, ResumptionLine] = {}

    for seg in sorted(segments, key=lambda s: s.key):
        if seg.status is SegmentStatus.LIFTED:
            order.lifted.append(seg.key)
            continue
        if seg.status is SegmentStatus.ACTIVE:
            elapsed = log.starts[seg.key] - stoppage
            remaining = seg.duration - elapsed  # 已走时间不重播，只算剩余
            line = ResumptionLine(seg.key, seg.team, seg.server_no, seg.category,
                                  remaining, resume_at=stoppage, expire_at=stoppage - remaining)
        else:  # 仍有约束的排队段：接在前一段刑满之后起算
            prev = lines_by_key.get(seg.queue_after or "")
            resume = prev.expire_at if prev else stoppage
            line = ResumptionLine(seg.key, seg.team, seg.server_no, seg.category,
                                  seg.duration, resume_at=resume, expire_at=resume - seg.duration)
        lines_by_key[seg.key] = line
        order.lines.append(line)

    _released(parsed, order, segments, lines_by_key)
    _eligibility(parsed, order, lines_by_key)
    order.pending = list(review.forks)
    order.interfaces = list(parsed.interfaces)
    order.interface_notes = _interface_notes(parsed, game)
    order.sources = _sources(parsed, review)
    return order


def _released(parsed, order, segments, lines_by_key) -> None:
    """被撤销段的服罚人若没有其他仍有约束的段，即刻恢复上场资格。"""
    serving = {(l.team, l.server_no) for l in lines_by_key.values()}
    for seg in segments:
        if seg.status is not SegmentStatus.LIFTED:
            continue
        if (seg.team, seg.server_no) not in serving:
            order.released_now.append(Eligibility(
                seg.team, seg.server_no, available_at=order.stoppage,
                note=f"{seg.key} 撤销，即刻可上场",
            ))


def _eligibility(parsed, order, lines_by_key) -> None:
    roster = parsed.rosters.get(order.game)
    entries = list(order.released_now)
    for line in lines_by_key.values():
        entries.append(Eligibility(line.team, line.server_no, line.expire_at, note="刑满可上场"))
    # 同一人取最晚（倒数钟读数最小）的可上场时点。
    latest: dict[tuple[str, int], Eligibility] = {}
    for e in entries:
        key = (e.team, e.number)
        if key not in latest or e.available_at < latest[key].available_at:
            latest[key] = e
    order.eligibility = sorted(latest.values(), key=lambda e: -e.available_at)


def _interface_notes(parsed: ParsedCorpus, game: str) -> list[str]:
    notes = []
    for iface in parsed.interfaces:
        parts = []
        for rid in iface.ruling_ids:
            segs = [s for s in parsed.segments.values() if s.ruling_id == rid and s.game == game]
            if not segs:
                parts.append(f"{rid} 维持原样")
                continue
            lifted = [s for s in segs if s.status is SegmentStatus.LIFTED]
            mains_standing = [s for s in segs if s.category.value == "main"
                              and s.status is not SegmentStatus.LIFTED]
            if lifted and mains_standing and all(s.category.value != "main" for s in lifted):
                parts.append(f"{rid} 更正为仅主罚")
            elif lifted:
                parts.append(f"{rid} 含更正")
            else:
                parts.append(f"{rid} 维持原样")
        kind = "临时服罚单" if iface.provisional else "服罚单"
        notes.append(f"{iface.source_id}（记分席{kind}）继续留存：" + "；".join(parts))
    return notes


def _sources(parsed: ParsedCorpus, review: ReviewResult) -> list[str]:
    ids = {r.source_id for r in parsed.rosters.values()}
    ids |= {s.source_id for s in parsed.segments.values()}
    ids |= {c.source_id for c in review.effective}
    ids |= {f.correction.source_id for f in review.forks}
    ids |= {log.source_id for log in parsed.clocks.values()}
    ids |= {i.source_id for i in parsed.interfaces}
    ids |= {e.source_id for e in parsed.exclusions}
    return sorted(ids)
