import copy
import unittest

from materials import load_corpus
from penalty_review import Action, Mood, Scope, SegmentStatus, parse_corpus, run_review


class ReviewTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parsed = parse_corpus(load_corpus())
        cls.review = run_review(cls.parsed)

    def test_report_corroborated_by_confirmation(self):
        pairs = self.review.corroborations
        self.assertEqual(len(pairs), 2)
        self.assertTrue(all(r.mood is Mood.REPORTED and k.mood is Mood.CONFIRMED for r, k in pairs))
        self.assertTrue(all(r.source_id == "i1" and k.source_id == "a1" for r, k in pairs))

    def test_confirmed_correction_applied(self):
        supp = self.parsed.segments["r1:supplementary"]
        main = self.parsed.segments["r1:main"]
        self.assertEqual(supp.status, SegmentStatus.LIFTED)
        self.assertTrue(main.upheld)
        self.assertEqual(main.status, SegmentStatus.ACTIVE)

    def test_ambiguous_number_keeps_fork_not_execution(self):
        fork = next(f for f in self.review.forks if f.correction.action is Action.SHORTEN)
        self.assertIn("对象歧义：号码跨队或跨场重复", fork.reasons)
        # 两个队、两场都有 7 号，歧义跨队也跨场。
        self.assertEqual(len(fork.candidates), 4)
        self.assertIn(("m1", "北湾", 7), fork.candidates)
        self.assertIn(("m1", "林岸", 7), fork.candidates)
        # 分叉不改变任何判罚段。
        self.assertEqual(self.parsed.segments["r1:main"].status, SegmentStatus.ACTIVE)
        self.assertEqual(self.parsed.segments["r2:main"].status, SegmentStatus.ACTIVE)

    def test_leader_claim_is_not_effective(self):
        claim_fork = next(f for f in self.review.forks if f.correction.mood is Mood.CLAIMED)
        self.assertIn("仅为领队申请，未获裁判确认", claim_fork.reasons)
        self.assertFalse(any(c.mood is Mood.CLAIMED for c in self.review.effective))

    def test_impact_covers_three_scopes(self):
        scopes = {i.scope: i for i in self.review.impacts}
        self.assertEqual(set(scopes), {Scope.MAIN_IN_PROGRESS, Scope.QUEUED_FOLLOW_UP, Scope.SUBSTITUTE_SERVER})
        self.assertFalse(scopes[Scope.MAIN_IN_PROGRESS].affected)  # 主罚维持
        self.assertIn("不重播", scopes[Scope.MAIN_IN_PROGRESS].detail)
        self.assertTrue(scopes[Scope.QUEUED_FOLLOW_UP].affected)  # 排队后续段取消
        self.assertTrue(scopes[Scope.SUBSTITUTE_SERVER].affected)  # 替代服罚人释放
        self.assertIn("北湾12号", scopes[Scope.SUBSTITUTE_SERVER].detail)

    def test_stoppage_alignment_by_clock(self):
        notes = self.review.alignment_notes
        self.assertTrue(any("i1" in n and "一致" in n for n in notes))
        self.assertTrue(any("r1(04:20)" in n and "r2(03:40)" in n for n in notes))
        self.assertTrue(any("m2" in n and "另一场" in n for n in notes))

    def test_other_play_and_other_game_untouched(self):
        notes = self.review.untouched_notes
        self.assertTrue(any("r2:main" in n for n in notes))
        self.assertTrue(any("林岸" in n and "未并入" in n for n in notes))

    def test_confirmed_but_ambiguous_still_forks(self):
        data = copy.deepcopy(load_corpus())
        data["records"].append({
            "kind": "appeal", "id": "a9",
            "text": "m1 复议原话|7号不用坐满。",
        })
        parsed = parse_corpus(data)
        review = run_review(parsed)
        fork = next(f for f in review.forks if f.correction.source_id == "a9")
        self.assertIn("裁决已确认，但对象歧义未消除", fork.reasons)
        self.assertEqual({c[1] for c in fork.candidates}, {"北湾", "林岸"})
        # 没有写入任何可执行变更。
        self.assertEqual(parsed.segments["r1:main"].status, SegmentStatus.ACTIVE)
        self.assertEqual(parsed.segments["r2:main"].status, SegmentStatus.ACTIVE)

    def test_new_name_in_interpretation_cannot_rewrite_ruling(self):
        data = copy.deepcopy(load_corpus())
        data["records"].append({
            "kind": "interpretation", "id": "i9",
            "text": "m1 第一节停表 03:10|北湾7号（王某）不用坐满。",
        })
        parsed = parse_corpus(data)
        run_review(parsed)
        self.assertIn(("i9", "王某"), parsed.unresolved_names)
        # 名册与裁判原文都不被口译新姓名改写。
        self.assertEqual(parsed.rosters["m1"].teams["北湾"][7], "岑一")
        self.assertEqual(parsed.segments["r1:main"].server_no, 7)
        self.assertEqual(parsed.segments["r1:main"].offender_no, 7)


if __name__ == "__main__":
    unittest.main()
