import unittest

from materials import load_corpus
from penalty_review import run_pipeline


class BulletinTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bulletin = run_pipeline(load_corpus()).bulletin
        cls.zh = "\n".join(cls.bulletin.zh_lines)
        cls.en = "\n".join(cls.bulletin.en_lines)

    def test_bulletin_is_bilingual(self):
        self.assertIn("复议后恢复通报", self.zh)
        self.assertIn("Post-review resumption bulletin", self.en)

    def test_only_confirmed_parts_are_executive(self):
        self.assertIn("余 00:50", self.zh)  # 主罚维持的剩余时间
        self.assertIn("00:50 remains", self.en)
        self.assertIn("附加2分钟取消", self.zh)
        self.assertIn("supplementary 2-minute segment", self.en)
        self.assertIn("01:30", self.zh)  # 林岸另一回合不受影响

    def test_pending_scope_visible_to_resuming_party(self):
        self.assertIn("尚不能执行", self.zh)
        self.assertIn("Not yet executable", self.en)
        self.assertIn("7号不用坐满", self.zh)
        self.assertIn("撤销所有处罚", self.zh)
        # 两种语言都列出歧义候选。
        self.assertIn("m1·北湾7号", self.zh)
        self.assertIn("m1 North Bay #7", self.en)

    def test_retained_interfaces_and_sources(self):
        self.assertIn("e1", self.zh)
        self.assertIn("r1 更正为仅主罚", self.zh)
        for source in ("r1", "r2", "i1", "a1", "c1"):
            self.assertIn(source, self.zh)
        self.assertIn("Sources:", self.en)

    def test_team_names_translated(self):
        self.assertIn("North Bay #7", self.en)
        self.assertIn("Forest Shore #7", self.en)
        self.assertIn("North Bay #12", self.en)

    def test_fork_not_presented_as_executable(self):
        # 可执行部分（第一节）不得出现待复核的“不用坐满”。
        executive = self.zh.split("二、尚不能执行")[0]
        self.assertNotIn("不用坐满", executive)


if __name__ == "__main__":
    unittest.main()
