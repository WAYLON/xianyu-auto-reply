import unittest
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.services.package_reply_service import (
    PackageReplyMatch,
    PackageReplyService,
    build_package_clarification_text,
    build_package_reply_text,
    contains_match_token,
    message_implies_regular_single_ticket,
    parse_package_intent,
    parse_offer_index_requests,
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
            "7月4号可以用吗",
            "明天2号去多少钱",
        ]
        for message in cases:
            with self.subTest(message=message):
                self.assertIsNone(parse_offer_index_request(message))

    def test_parse_offer_index_requests_accepts_multi_price_question(self):
        self.assertEqual(parse_offer_index_requests("你好，6和8多少钱"), [6, 8])
        self.assertEqual(parse_offer_index_requests("6、8号多少钱"), [6, 8])
        self.assertEqual(parse_offer_index_requests("7月4号多少钱"), [])

    def test_parse_package_intent_extracts_bath_constraints(self):
        intent = parse_package_intent("明天工作日单人18H不过夜多少钱")
        self.assertEqual(intent.day_type, "workday")
        self.assertEqual(intent.ticket_kind, "single")
        self.assertEqual(intent.duration_hours, 18)
        self.assertFalse(intent.overnight)
        self.assertTrue(intent.asks_price)

    def test_parse_package_intent_does_not_treat_not_including_overnight_fee_as_overnight(self):
        intent = parse_package_intent("水之梦【工作日】16小时单人门票+免费四餐（不含过夜费）")
        self.assertFalse(intent.overnight)

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
        self.assertTrue(contains_match_token("24H周末及节假日单人门票", "24小时"))

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
        self.assertIn("使用规则和库存以确认时为准", reply)
        self.assertNotIn("http", reply.lower())
        self.assertNotIn("现价", reply)
        self.assertNotIn("门市价", reply)
        self.assertNotIn("价格", reply)

    def test_clarification_template_keeps_package_guardrails(self):
        venue = SimpleNamespace(city="北京", venue_name="九号温泉生活馆")
        reply = build_package_clarification_text(venue)
        self.assertIn("北京九号温泉生活馆", reply)
        self.assertIn("美团搜索 86886 领红包", reply)
        self.assertIn("比自己在美团直接买更便宜", reply)
        self.assertIn("使用规则和库存以确认时为准", reply)
        self.assertNotIn("http", reply.lower())
        self.assertNotIn("现价", reply)
        self.assertNotIn("门市价", reply)
        self.assertNotIn("价格", reply)

    def test_overnight_reply_prefers_actual_night_ticket(self):
        service = PackageReplyService(SimpleNamespace())
        venue = SimpleNamespace(city="武汉", venue_name="水之梦")
        offers = [
            SimpleNamespace(
                package_name="水之梦【工作日】16小时单人门票+免费四餐（不含过夜费）",
                command_type="group_text",
                command_value="普通口令",
            ),
            SimpleNamespace(
                package_name="水之梦【晚9-次11点14H夜间门票】宵夜+早餐+过夜费",
                command_type="group_text",
                command_value="夜票口令",
            ),
        ]
        intent = parse_package_intent("夜票过夜")
        reply = service._build_overnight_reply("夜票过夜", intent, venue, offers)
        self.assertIsNotNone(reply)
        self.assertIn("夜间门票", reply)
        self.assertNotIn("不含过夜费", reply)

    def test_direct_multi_index_reply_omits_price_wording(self):
        service = PackageReplyService(SimpleNamespace())
        venue = SimpleNamespace(city="武汉", venue_name="水之梦")
        offers = [
            SimpleNamespace(package_name=f"{idx}号套餐", command_type="group_text", command_value=f"口令{idx}")
            for idx in range(1, 9)
        ]
        match = service._match_direct_command_or_index("6和8多少钱", venue, offers)
        self.assertIsNotNone(match)
        self.assertEqual(match.reason, "direct_offer_indexes")
        self.assertIn("6号套餐", match.custom_reply)
        self.assertIn("8号套餐", match.custom_reply)
        self.assertNotIn("价格", match.custom_reply)
        self.assertNotIn("现价", match.custom_reply)

    def test_short_alias_can_infer_venue(self):
        service = PackageReplyService(SimpleNamespace())
        venues = [
            SimpleNamespace(city="佛山", area=None, brand="乾沣", venue_name="乾沣汤泉生活", address_note=None, aliases_json=["乾沣"]),
            SimpleNamespace(city="武汉", area=None, brand="水之梦", venue_name="水之梦", address_note=None, aliases_json=["水之梦"]),
        ]
        venue = service._match_venue_by_text("乾沣周末24H单人", venues)
        self.assertEqual(venue.venue_name, "乾沣汤泉生活")

    def test_bound_item_venue_is_not_overridden_by_message_venue(self):
        service = PackageReplyService(SimpleNamespace())
        venue = SimpleNamespace(id=1, enabled=True, city="北京", venue_name="水裹+合生汇店")
        offer = SimpleNamespace(
            package_name="水裹+【躺平计划】工作日单人8小时浴资票",
            command_type="group_text",
            command_value="合生汇口令",
            keywords_json=[],
        )

        async def fake_get(_model, _id):
            return venue

        class FakeScalars:
            def __init__(self, value):
                self.value = value

            def first(self):
                return self.value

            def all(self):
                return self.value

        class FakeResult:
            def __init__(self, value):
                self.value = value

            def scalars(self):
                return FakeScalars(self.value)

        async def fake_execute(_stmt):
            if not getattr(fake_execute, "called", False):
                fake_execute.called = True
                return FakeResult(SimpleNamespace(venue_id=1))
            return FakeResult([offer])

        service.session.get = fake_get
        service.session.execute = fake_execute
        async def fake_ai_match(*_args, **_kwargs):
            return None

        service._match_offer_with_ai = fake_ai_match
        match = self.run_async(service.match_for_message("account", "item", "北京水裹四惠工作日单人"))
        self.assertIsInstance(match, PackageReplyMatch)
        self.assertEqual(match.venue.venue_name, "水裹+合生汇店")

    def run_async(self, coro):
        import asyncio

        return asyncio.run(coro)


if __name__ == "__main__":
    unittest.main()
