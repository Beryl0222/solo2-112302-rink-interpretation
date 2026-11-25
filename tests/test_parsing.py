import unittest

from materials import load_corpus
from penalty_review import Action, Category, Mood, parse_corpus


class ParsingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parsed = parse_corpus(load_corpus())

    def test_roster_learned_from_match_record(self):
        roster = self.parsed.rosters["m1"]
        self.assertEqual(roster.teams["北湾"][7], "岑一")
        self.assertEqual(roster.teams["林岸"][7], "艾诺")
        self.assertEqual(roster.period_length, 20 * 60)

    def test_second_match_inherits_roster(self):
        self.assertEqual(self.parsed.rosters["m2"].teams, self.parsed.rosters["m1"].teams)

    def test_ruling_segments_and_substitute(self):
        main = self.parsed.segments["r1:main"]
        supp = self.parsed.segments["r1:supplementary"]
        self.assertEqual((main.team, main.offender_no, main.duration), ("北湾", 7, 120))
        self.assertEqual(main.category, Category.MAIN)
        self.assertEqual(supp.category, Category.SUPPLEMENTARY)
        self.assertEqual(supp.queue_after, "r1:main")  # 其后接续
        self.assertEqual(supp.server_no, 12)  # 班席由北湾12号代坐后段
        self.assertTrue(supp.substitute)

    def test_separate_play_is_not_supplementary(self):
        # “另小罚”是另一回合的主罚，不是附加段。
        seg = self.parsed.segments["r2:main"]
        self.assertEqual((seg.team, seg.offender_no), ("林岸", 7))
        self.assertEqual(seg.contact_id, "r2")
        self.assertNotEqual(seg.contact_id, self.parsed.segments["r1:main"].contact_id)
        self.assertFalse(any(k.startswith("r2:supplementary") for k in self.parsed.segments))

    def test_interpretation_maps_team_category_action(self):
        items = [c for c in self.parsed.corrections if c.source_id == "i1" and not c.scope_only]
        self.assertEqual(len(items), 2)
        by_action = {c.action: c for c in items}
        self.assertEqual(by_action[Action.UPHOLD].category, Category.MAIN)
        self.assertEqual(by_action[Action.LIFT].category, Category.SUPPLEMENTARY)
        # 英文范围句 "North second bench only" 把队带给同段各句。
        self.assertTrue(all(c.team == "北湾" for c in items))
        self.assertTrue(all(c.mood is Mood.REPORTED for c in items))
        self.assertTrue(all(c.game == "m1" for c in items))

    def test_claim_and_report_coexist_in_one_paragraph(self):
        items = [c for c in self.parsed.corrections if c.source_id == "i2"]
        moods = {c.mood for c in items}
        self.assertIn(Mood.REPORTED, moods)
        self.assertIn(Mood.CLAIMED, moods)
        claim = next(c for c in items if c.mood is Mood.CLAIMED)
        self.assertEqual(claim.action, Action.LIFT)
        self.assertTrue(claim.all_penalties)
        report = next(c for c in items if c.mood is Mood.REPORTED)
        self.assertEqual(report.action, Action.SHORTEN)
        self.assertEqual(report.number, 7)
        self.assertIsNone(report.team)  # 号码跨队重复，句中没有队

    def test_clock_log(self):
        log = self.parsed.clocks["m1"]
        self.assertEqual(log.starts["r1:main"], 4 * 60 + 20)
        self.assertEqual(log.starts["r2:main"], 3 * 60 + 40)
        self.assertEqual(log.stoppage, 3 * 60 + 10)

    def test_appeal_is_confirmed_and_carries_exclusion(self):
        items = [c for c in self.parsed.corrections if c.source_id == "a1"]
        self.assertTrue(all(c.mood is Mood.CONFIRMED for c in items))
        lift = next(c for c in items if c.action is Action.LIFT)
        self.assertEqual((lift.team, lift.category), ("北湾", Category.SUPPLEMENTARY))
        uphold = next(c for c in items if c.action is Action.UPHOLD)
        self.assertEqual(uphold.team, "北湾")  # 同段承袭
        self.assertEqual(self.parsed.exclusions[0].team, "林岸")

    def test_release_interface_retained(self):
        iface = self.parsed.interfaces[0]
        self.assertEqual(iface.source_id, "e1")
        self.assertEqual(iface.ruling_ids, ["r1", "r2"])
        self.assertTrue(iface.provisional)


if __name__ == "__main__":
    unittest.main()
