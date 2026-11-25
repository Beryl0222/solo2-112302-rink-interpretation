"""复议席业务对象：名册、判罚段、更正、分叉、影响、恢复单与通报。

时钟一律用“节内剩余秒数”表示（倒数钟），例如第一节 04:20 记为 260。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Category(str, Enum):
    """处罚类别。"""

    MAIN = "main"  # 主罚
    SUPPLEMENTARY = "supplementary"  # 附加罚


class Kind(str, Enum):
    """罚种。"""

    MINOR = "minor"  # 小罚
    MAJOR = "major"  # 大罚


class Action(str, Enum):
    """决定动作。"""

    LIFT = "lift"  # 撤掉/取消
    UPHOLD = "uphold"  # 维持/仍有效
    SHORTEN = "shorten"  # 不用坐满


class Mood(str, Enum):
    """决定语气：区分裁判确认、口译转述与领队申请。"""

    CONFIRMED = "confirmed"  # 裁判确认 / 复议裁决
    REPORTED = "reported"  # 口译转述
    CLAIMED = "claimed"  # 领队申请


class Scope(str, Enum):
    """更正影响范围的三类对象。"""

    MAIN_IN_PROGRESS = "main_in_progress"  # 已经开始计时的主罚
    QUEUED_FOLLOW_UP = "queued_follow_up"  # 同一人排队的后续罚
    SUBSTITUTE_SERVER = "substitute_server"  # 替代服罚人


class SegmentStatus(str, Enum):
    QUEUED = "queued"  # 排队等待起算
    ACTIVE = "active"  # 计时中
    LIFTED = "lifted"  # 已撤销
    COMPLETED = "completed"  # 已坐满


@dataclass
class Roster:
    """一场比赛的队名册：team -> {number: name}。"""

    game: str
    source_id: str
    teams: dict[str, dict[int, str]] = field(default_factory=dict)
    period_length: int = 20 * 60

    def name_of(self, team: str, number: int) -> Optional[str]:
        return self.teams.get(team, {}).get(number)

    def teams_with_number(self, number: int) -> list[str]:
        return [team for team, nums in self.teams.items() if number in nums]


@dataclass
class Segment:
    """一条判罚中的一个计时段（主罚段或附加段）。"""

    key: str  # 例如 "r1:main"
    ruling_id: str
    game: str
    period: int
    announced_at: int  # 宣判时的场上钟（剩余秒）
    team: str
    offender_no: int
    server_no: int  # 实际坐罚席的号码；替代服罚时与 offender_no 不同
    category: Category
    kind: Kind
    duration: int  # 秒
    queue_after: Optional[str] = None  # 接续的前一段 key
    contact_id: str = ""  # 同一次接触的归组标识
    status: SegmentStatus = SegmentStatus.QUEUED
    upheld: bool = False  # 经复议确认维持
    source_id: str = ""

    @property
    def substitute(self) -> bool:
        return self.server_no != self.offender_no


@dataclass
class Correction:
    """一条决定意见（可来自判词、口译或复议来文）。"""

    source_id: str
    action: Optional[Action]
    mood: Mood
    game: Optional[str] = None
    team: Optional[str] = None
    number: Optional[int] = None
    category: Optional[Category] = None
    clause: str = ""  # 原句，留存出处
    all_penalties: bool = False  # “撤销所有处罚”一类全称说法
    scope_only: bool = False  # 仅作范围限定（如 "North second bench only"）
    contact_hint: Optional[str] = None  # “那次接触”等指代


@dataclass
class Fork:
    """待复核分叉：能确认裁决但对象歧义未消除，或尚未获确认。"""

    correction: Correction
    reasons: list[str] = field(default_factory=list)
    candidates: list[tuple[str, str, int]] = field(default_factory=list)  # (game, team, number)


@dataclass
class Impact:
    scope: Scope
    affected: bool
    detail: str


@dataclass
class Exclusion:
    """复议来文中的排除要求（不要把另一回合算进去）。"""

    source_id: str
    team: str
    note: str


@dataclass
class Interface:
    """已经签发的界面（如记分席临时服罚单），复议后仍须留存。"""

    source_id: str
    ruling_ids: list[str]
    provisional: bool
    note: str


@dataclass
class ClockLog:
    """记分席时间摘录：起算点与停表点。"""

    game: str
    period: int
    source_id: str
    starts: dict[str, int] = field(default_factory=dict)  # segment key -> 起算时钟
    stoppage: Optional[int] = None
    notes: list[str] = field(default_factory=list)


@dataclass
class ReviewResult:
    game: str
    period: int
    stoppage: int
    effective: list[Correction] = field(default_factory=list)
    corroborations: list[tuple[Correction, Correction]] = field(default_factory=list)
    forks: list[Fork] = field(default_factory=list)
    impacts: list[Impact] = field(default_factory=list)
    alignment_notes: list[str] = field(default_factory=list)
    untouched_notes: list[str] = field(default_factory=list)


@dataclass
class ResumptionLine:
    """恢复单中可执行的一行。"""

    segment_key: str
    team: str
    server_no: int
    category: Category
    remaining: int  # 停表时点剩余秒数
    resume_at: int  # 恢复计时点
    expire_at: int  # 刑满点


@dataclass
class Eligibility:
    team: str
    number: int
    available_at: int  # 可上场时点（剩余秒）；等于停表点表示立即可上场
    note: str = ""


@dataclass
class ResumptionOrder:
    """比赛恢复记录：只含已确认且对象无歧义的可执行行。"""

    game: str
    period: int
    stoppage: int
    lines: list[ResumptionLine] = field(default_factory=list)
    lifted: list[str] = field(default_factory=list)  # 已撤销的段（留存，不执行）
    released_now: list[Eligibility] = field(default_factory=list)
    eligibility: list[Eligibility] = field(default_factory=list)
    pending: list[Fork] = field(default_factory=list)  # 尚不能执行的范围
    interfaces: list[Interface] = field(default_factory=list)
    interface_notes: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)


@dataclass
class Bulletin:
    """对外双语通报。"""

    zh_lines: list[str] = field(default_factory=list)
    en_lines: list[str] = field(default_factory=list)

    def render(self) -> str:
        return "\n".join(self.zh_lines) + "\n\n" + "\n".join(self.en_lines)
