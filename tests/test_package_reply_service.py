import unittest
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.services.package_reply_service import (
    build_package_clarification_text,
    build_package_reply_text,
    parse_package_material,
)


class PackageReplyServiceTests(unittest.TestCase):
    def test_parse_full_group_commands_ignores_price_and_link(self):
        raw = """
🎁【九号温泉生活馆榴莲畅吃｜工作日18H/节假日6H+星级海鲜自助】
🎉门市价459元 现价仅需389元
【下单链接】http://dpurl.cn/KfaD7Kqz
【团口令】1来美团，吃得更好，生活更好❤️复制整条信息，打开👉美团👈 http:/💰twYTY5MThjODE💰

🎁【九号温泉生活馆榴莲畅吃｜周日至周四夜间票+夜宵/早餐+过夜费】
🎉门市价518元 现价仅需299元
【下单链接】http://dpurl.cn/tXsDEs7z
【团口令】1来美团，吃得更好，生活更好❤️复制整条信息，打开👉美团👈 http:/💰vhNjVjNDAwZmI💰
"""
        parsed = parse_package_material(raw)
        self.assertEqual(len(parsed), 2)
        self.assertTrue(parsed[0]["package_name"].startswith("九号温泉生活馆榴莲畅吃"))
        self.assertEqual(parsed[0]["command_type"], "group_text")
        self.assertNotIn("dpurl.cn", parsed[0]["command_value"])
        self.assertNotIn("现价", parsed[0]["command_value"])
        self.assertIn("💰twYTY5MThjODE💰", parsed[0]["command_value"])


    def test_parse_numeric_command_requires_command_context(self):
        raw = """
【V汤泉生活馆榴莲畅吃｜工作日单人18H门票】
门市价 571261 元

【V汤泉生活馆榴莲畅吃｜双人工作日18H/节假日8H+娱乐3选1】
美团搜索口令 434389
"""
        parsed = parse_package_material(raw)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["command_value"], "434389")


    def test_reply_template_contains_required_guidance_without_price_or_link(self):
        venue = SimpleNamespace(city="北京", venue_name="九号温泉生活馆")
        offer = SimpleNamespace(command_type="numeric", command_value="930174", package_name="温泉6月专场")
        reply = build_package_reply_text(offer, venue)
        self.assertIn("温泉6月专场", reply)
        self.assertIn("930174", reply)
        self.assertIn("美团搜索 86886 领红包", reply)
        self.assertIn("比自己在美团直接买更便宜", reply)
        self.assertIn("价格实时浮动", reply)
        self.assertNotIn("http", reply.lower())
        self.assertNotIn("现价", reply)

    def test_clarification_template_keeps_package_guardrails(self):
        venue = SimpleNamespace(city="北京", venue_name="九号温泉生活馆")
        reply = build_package_clarification_text(venue)
        self.assertIn("北京九号温泉生活馆", reply)
        self.assertIn("美团搜索 86886 领红包", reply)
        self.assertIn("比自己在美团直接买更便宜", reply)
        self.assertIn("价格实时浮动", reply)
        self.assertNotIn("http", reply.lower())
        self.assertNotIn("现价", reply)


if __name__ == "__main__":
    unittest.main()
