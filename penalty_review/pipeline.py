"""端到端流程：语料 -> 解析 -> 复议 -> 恢复单 -> 双语通报。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .bulletin import build_bulletin
from .models import Bulletin, ResumptionOrder, ReviewResult
from .parsing import ParsedCorpus, parse_corpus
from .resumption import build_order
from .review import run_review


@dataclass
class PipelineResult:
    parsed: ParsedCorpus
    review: ReviewResult
    order: ResumptionOrder
    bulletin: Bulletin


def run_pipeline(data: dict, game: Optional[str] = None) -> PipelineResult:
    parsed = parse_corpus(data)
    review = run_review(parsed, game=game)
    order = build_order(parsed, review)
    bulletin = build_bulletin(order, review, parsed)
    return PipelineResult(parsed, review, order, bulletin)
