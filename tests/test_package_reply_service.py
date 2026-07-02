import unittest
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.services.package_reply_service import (
    build_package_clarification_text,
    build_package_reply_text,
    contains_match_token,
    message_implies_regular_single_ticket,
    parse_package_intent,
    parse_offer_index_request,
    parse_package_material,
    should_skip_package_reply,
)


class PackageReplyServiceTests(unittest.TestCase):
    def test_parse_offer_index_request_accepts_buyer_index_phrases(self):
        cases = {
            "第1个": 1,
            "第二个": 2,
            "选3": 3,
            "要第4个": 4,
            "我要4号": 4,
            "发第5款": 5,
            "6号套餐": 6,
            "套餐第7": 7,
            "咨询套餐8": 8,
            "明天2号套餐多少钱": 2,
            "四": 4,
        }
        for message, expected in cases.items():
            with self.subTest(message=message):
                self.assertEqual(parse_offer_index_request(message), expected)

    def test_parse_offer_index_request_ignores_date_and_headcount(self):
        cases = [
            "7月2号周四18小时双人怎么买",
            "我要4个人",
            "要4张",
            "8小时多少钱",
            "明天2号去多少钱",
        ]
        for message in cases:
            with self.subTest(message=message):
                self.assertIsNone(parse_offer_index_request(message))

    def test_parse_package_intent_extracts_bath_constraints(self):
        intent = parse_package_intent("明天工作日单人18H不过夜多少钱")
        self.assertEqual(intent.day_type, "workday")
        self.assertEqual(intent.ticket_kind, "single")
        self.assertEqual(intent.duration_hours, 18)
        self.assertFalse(intent.overnight)
        self.assertTrue(intent.asks_price)

    def test_skip_package_reply_keeps_idle_messages_quiet(self):
        self.assertTrue(should_skip_package_reply("好的"))
        self.assertTrue(should_skip_package_reply("不用了谢谢"))
        self.assertFalse(should_skip_package_reply("工作日单人8h"))

    def test_regular_single_ticket_detects_headcount_without_double_ticket(self):
        self.assertTrue(message_implies_regular_single_ticket("3个人今天去"))
        self.assertFalse(message_implies_regular_single_ticket("双人今天去"))

    def test_contains_match_token_accepts_common_day_and_duration_aliases(self):
        self.assertTrue(contains_match_token("周末节假日6H票", "节假日"))
        self.assertTrue(contains_match_token("平日16小时票", "工作日"))
        self.assertTrue(contains_match_token("单人16H门票", "16小时"))

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

    def test_parse_nested_package_title_keeps_full_title(self):
        raw = """
🎁【水裹·汤泉【躺平计划】工作日单人门票(16H)】
🎉门市价299元 现价仅需298元
【下单链接】http://dpurl.cn/chzMsnVz
【团口令】1来美团，吃得更好，生活更好❤️复制整条信息，打开👉美团👈 http:/💰s0OTJmNzAwNzg💰

1来美团，吃得更好，生活更好❤️复制整条信息，打开👉美团👈 http:/💰orphan💰
"""
        parsed = parse_package_material(raw)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["package_name"], "水裹·汤泉【躺平计划】工作日单人门票(16H)")
        self.assertEqual(parsed[0]["command_type"], "group_text")
        self.assertIn("s0OTJmNzAwNzg", parsed[0]["command_value"])
        self.assertNotIn("orphan", parsed[0]["command_value"])

    def test_parse_inline_adjacent_titles(self):
        raw = """
🎁【水裹+早餐畅享（周五至周六）夜间门票+过夜费+自助早餐】
🎉门市价637元 现价仅需399元
【下单链接】http://dpurl.cn/TAJig4Nz
【团口令】1来美团，吃得更好，生活更好❤️复制整条信息，打开👉美团👈 http:/💰qsMzg2N2Y3YWI💰 🎁【水裹+【躺平计划】工作日单人8小时浴资票】
🎉门市价379元 现价仅需378元
【下单链接】http://dpurl.cn/otNhm9Qz
【团口令】1来美团，吃得更好，生活更好❤️复制整条信息，打开👉美团👈 http:/💰r0ZTEwYTA0ZjA💰
"""
        parsed = parse_package_material(raw)
        self.assertEqual(len(parsed), 2)
        self.assertEqual(parsed[0]["package_name"], "水裹+早餐畅享（周五至周六）夜间门票+过夜费+自助早餐")
        self.assertEqual(parsed[1]["package_name"], "水裹+【躺平计划】工作日单人8小时浴资票")
        self.assertIn("qsMzg2N2Y3YWI", parsed[0]["command_value"])
        self.assertIn("r0ZTEwYTA0ZjA", parsed[1]["command_value"])
        self.assertNotIn("dpurl.cn", parsed[0]["command_value"])

    def test_parse_ignores_separator_line_after_command(self):
        raw = """
🎁【九号温泉生活馆学生享｜平日18H/假日6H+娱乐三选一+榴莲畅吃】
【团口令】1来美团，吃得更好，生活更好❤️复制整条信息，打开👉美团👈 http:/💰wfZTc1ZDJlOGI💰
｜
"""
        parsed = parse_package_material(raw)
        self.assertEqual(len(parsed), 1)
        self.assertIn("wfZTc1ZDJlOGI", parsed[0]["command_value"])
        self.assertNotIn("｜", parsed[0]["command_value"])

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
