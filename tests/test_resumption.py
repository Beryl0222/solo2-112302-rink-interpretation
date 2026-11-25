import unittest

from materials import load_corpus
from penalty_review import parse_corpus, run_pipeline, run_review
from penalty_review.resumption import build_order


class ResumptionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = run_pipeline(load_corpus())
        cls.order = cls.result.order

    def test_stoppage_point(self):
        self.assertEqual((self.order.game, self.order.period), ("m1", 1))
        self.assertEqual(self.order.stoppage, 3 * 60 + 10)

    def test_elapsed_time_is_not_replayed(self):
        line = next(l for l in self.order.lines if l.segment_key == "r1:main")
        # 04:20 起算到 03:10 停表已走 1:10，余 0:50，而不是重置回 2:00。
        self.assertEqual(line.remaining, 50)
        self.assertEqual(line.resume_at, 3 * 60 + 10)
        self.assertEqual(line.expire_at, 2 * 60 + 20)

    def test_undisputed_record_still_processed(self):
        # 同场没有争议的 r2 照常进入恢复单，不受待复核分叉影响。
        line = next(l for l in self.order.lines if l.segment_key == "r2:main")
        self.assertEqual((line.team, line.server_no), ("林岸", 7))
        self.assertEqual(line.remaining, 90)
        self.assertEqual(line.expire_at, 1 * 60 + 40)

    def test_lifted_segment_not_executable(self):
        self.assertIn("r1:supplementary", self.order.lifted)
        self.assertFalse(any(l.segment_key == "r1:supplementary" for l in self.order.lines))

    def test_substitute_server_released_immediately(self):
        released = {(e.team, e.number): e for e in self.order.released_now}
        self.assertIn(("北湾", 12), released)
        self.assertEqual(released[("北湾", 12)].available_at, self.order.stoppage)

    def test_eligibility_schedule(self):
        schedule = {(e.team, e.number): e.available_at for e in self.order.eligibility}
        self.assertEqual(schedule[("北湾", 12)], 3 * 60 + 10)  # 即刻
        self.assertEqual(schedule[("北湾", 7)], 2 * 60 + 20)  # 主罚刑满
        self.assertEqual(schedule[("林岸", 7)], 1 * 60 + 40)

    def test_pending_forks_visible_but_not_executable(self):
        self.assertGreaterEqual(len(self.order.pending), 2)
        clauses = [f.correction.clause for f in self.order.pending]
        self.assertTrue(any("不用坐满" in c for c in clauses))
        self.assertTrue(any("撤销所有处罚" in c for c in clauses))
        # 分叉不出现在可执行行里。
        self.assertEqual(len(self.order.lines), 2)

    def test_issued_interface_retained_with_amendment(self):
        self.assertEqual(self.order.interfaces[0].source_id, "e1")
        note = self.order.interface_notes[0]
        self.assertIn("r1 更正为仅主罚", note)
        self.assertIn("r2 维持原样", note)

    def test_sources_complete(self):
        self.assertEqual(set(self.order.sources),
                         {"m1", "m2", "r1", "r2", "i1", "i2", "c1", "a1", "e1"})


if __name__ == "__main__":
    unittest.main()
