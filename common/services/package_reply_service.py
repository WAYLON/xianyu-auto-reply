"""套餐团口令解析、配置与自动回复匹配服务。"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from loguru import logger
from sqlalchemy import delete, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from common.models.package_reply import (
    XYItemPackageBinding,
    XYPackageImportCandidate,
    XYPackageOffer,
    XYPackageVenue,
)
from common.models.xy_account import XYAccount
from common.models.xy_catalog_item import XYCatalogItem
from common.services.ai_provider_service import build_openai_url, clean_ai_text, normalize_ai_provider_type


NUMERIC_COMMAND_CONTEXT = re.compile(r"(美团搜索|搜索口令|数字口令|团口令|口令)\D{0,12}(\d{6})")
FULL_COMMAND_CONTEXT = re.compile(r"【团口令】\s*(.+?)(?=\n\s*\n|\n\s*🎁|$)", re.S)
TITLE_LINE_PATTERN = re.compile(r"^\s*(?:🎁)?【(.{4,220})】\s*$")
PRICE_OR_LINK_LINE = re.compile(r"(门市价|现价|下单链接|http://|https://|dpurl\.cn)", re.I)
MATERIAL_NOISE_LINE = re.compile(r"^[｜|\\-—_\\s]+$")
MATERIAL_FIELD_TITLES = {"下单链接", "团口令", "搜索口令", "美团搜索", "数字口令"}
DIRECT_COMMAND_PATTERN = re.compile(r"(?<!\d)(\d{6})(?!\d)")


KNOWN_NUMERIC_COMMANDS: list[dict[str, Any]] = [
    {"city": "北京", "brand": "水裹", "venue_name": "水裹汤泉", "package_name": "水裹·汤泉｜躺平计划 工作日单人门票(16H)", "command_value": "894162", "aliases": ["水裹", "水裹汤泉"]},
    {"city": "北京", "brand": "九号", "venue_name": "九号温泉生活馆", "package_name": "九号温泉生活馆榴莲畅吃｜工作日18H/节假日6H+星级海鲜自助", "command_value": "497273", "aliases": ["九号", "九号汤泉", "九号温泉"]},
    {"city": "北京", "brand": "九号", "venue_name": "九号温泉生活馆", "package_name": "温泉6月专场 团建海鲜自助+室外温泉+榴莲畅吃", "command_value": "930174", "aliases": ["九号", "九号汤泉", "九号温泉"]},
    {"city": "北京", "brand": "V汤泉", "venue_name": "V汤泉生活馆四惠店", "package_name": "V汤泉生活馆榴莲畅吃｜双人工作日18H/节假日8H+娱乐3选1", "command_value": "434389", "aliases": ["V汤泉", "V生活", "v汤泉", "四惠店"]},
    {"city": "北京", "brand": "V汤泉", "venue_name": "V汤泉生活馆四惠店", "package_name": "V汤泉生活馆榴莲畅吃｜工作日单人18H门票", "command_value": "571261", "aliases": ["V汤泉", "V生活", "v汤泉", "四惠店"]},
    {"city": "北京", "brand": "海德", "venue_name": "海德温泉生活馆朝阳大悦城店", "package_name": "海德温泉生活馆 工作日18H单人门票+豪华海鲜自助+榴莲自由", "command_value": "270108", "aliases": ["海德", "海德温泉", "朝阳大悦城"]},
    {"city": "北京", "brand": "海德", "venue_name": "海德汤泉望京店", "package_name": "海德汤泉生活 周一至周五16H单人门票+肉食自助+水果饮料", "command_value": "459276", "aliases": ["海德", "海德汤泉", "望京"]},
    {"city": "沈阳", "brand": "沐里沐外", "venue_name": "沐里沐外温泉洗浴浑南店", "package_name": "浑南店 工作日成人门票", "command_value": "134317", "aliases": ["沐里沐外", "浑南店"]},
    {"city": "沈阳", "brand": "沐里沐外", "venue_name": "沐里沐外温泉洗浴浑南店", "package_name": "浑南店 工作日门票+自助", "command_value": "698718", "aliases": ["沐里沐外", "浑南店"]},
    {"city": "沈阳", "brand": "沐里沐外", "venue_name": "沐里沐外温泉洗浴龙之梦店", "package_name": "龙之梦店 工作日成人门票", "command_value": "587704", "aliases": ["沐里沐外", "龙之梦店"]},
    {"city": "沈阳", "brand": "沐里沐外", "venue_name": "沐里沐外温泉洗浴龙之梦店", "package_name": "龙之梦店 工作日门票+自助", "command_value": "517343", "aliases": ["沐里沐外", "龙之梦店"]},
    {"city": "上海", "brand": "游沐日记", "venue_name": "游沐日记", "package_name": "游沐日记通用套餐A", "command_value": "123148", "aliases": ["游沐日记", "游牧日记"]},
    {"city": "上海", "brand": "游沐日记", "venue_name": "游沐日记", "package_name": "游沐日记通用套餐B", "command_value": "123147", "aliases": ["游沐日记", "游牧日记"]},
]


BUYER_TEST_MESSAGES = [
    "周末18h的多少啊",
    "今天过夜双人",
    "过夜也是这个价格吗",
    "明天2号套餐多少钱",
    "怎么买啊",
    "今天的夜票多少钱",
    "咨询套餐4",
    "您好，请问7月2日周四18小时双人+正餐，北京九号汤泉票怎么买呀？",
    "节假日18h多少钱",
    "明天皇庭广场店单人和双人多少？",
    "这家店能用吗",
    "深圳壹方天地今天能用吗",
    "A档方庄店两个人多少钱",
]


@dataclass
class PackageReplyMatch:
    offer: XYPackageOffer | None
    venue: XYPackageVenue | None
    confidence: float
    reason: str
    need_clarification: bool = False
    custom_reply: str | None = None


@dataclass(frozen=True)
class PackageIntent:
    day_type: str | None = None  # workday / holiday / weekend
    duration_hours: int | None = None
    overnight: bool | None = None
    ticket_kind: str | None = None  # single / double / family / child / student
    party_count: int | None = None
    asks_price: bool = False

    @property
    def has_specific_constraints(self) -> bool:
        return any(
            value is not None
            for value in [self.day_type, self.duration_hours, self.overnight, self.ticket_kind, self.party_count]
        )


def normalize_text(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()


CHINESE_NUMBER_MAP = {
    "一": 1,
    "二": 2,
    "两": 2,
    "俩": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


def parse_count_token(value: str) -> int | None:
    value = normalize_text(value)
    if value.isdigit():
        return int(value)
    if value in CHINESE_NUMBER_MAP:
        return CHINESE_NUMBER_MAP[value]
    if value.startswith("十") and len(value) == 2:
        return 10 + CHINESE_NUMBER_MAP.get(value[1], 0)
    if len(value) == 2 and value.endswith("十"):
        return CHINESE_NUMBER_MAP.get(value[0], 0) * 10
    if len(value) == 3 and value[1] == "十":
        return CHINESE_NUMBER_MAP.get(value[0], 0) * 10 + CHINESE_NUMBER_MAP.get(value[2], 0)
    return None


def parse_package_intent(value: Any) -> PackageIntent:
    normalized = normalize_text(value)

    day_type = None
    if any(word in normalized for word in ["工作日", "平日", "周一", "周二", "周三", "周四"]):
        day_type = "workday"
    if any(word in normalized for word in ["节假日", "假日", "周末"]):
        day_type = "holiday"
    if any(word in normalized for word in ["周六", "周日"]):
        day_type = "weekend"
    if "周五" in normalized and any(word in normalized for word in ["晚上", "夜", "过夜"]):
        day_type = "weekend"
    if day_type is None:
        day_type = infer_relative_day_type(normalized)

    duration_hours = None
    duration_match = re.search(r"(?<!\d)(6|8|12|16|18|24)(?:h|小时|时)", normalized)
    if duration_match:
        duration_hours = int(duration_match.group(1))
    elif "十八小时" in normalized:
        duration_hours = 18
    elif "十六小时" in normalized:
        duration_hours = 16
    elif "六小时" in normalized:
        duration_hours = 6

    overnight = None
    if any(word in normalized for word in ["不过夜", "不含过夜费", "不住", "不留宿", "当天走", "当天回", "不要过夜"]):
        overnight = False
    elif any(word in normalized for word in ["过夜", "夜场", "夜票", "夜间", "午夜", "晚上", "晚上去", "早上走", "夜宵"]):
        overnight = True

    ticket_kind = None
    if any(word in normalized for word in ["学生"]):
        ticket_kind = "student"
    elif any(word in normalized for word in ["儿童", "孩子", "小孩", "1.3米", "一米三", "九岁"]):
        ticket_kind = "child"
    elif any(word in normalized for word in ["亲子", "1大1小", "一大一小"]):
        ticket_kind = "family"
    elif any(word in normalized for word in ["双人", "两人票", "2人票", "俩人票", "两个人", "2个人"]):
        ticket_kind = "double"
    elif any(word in normalized for word in ["单人", "成人", "大人"]):
        ticket_kind = "single"

    party_count = None
    count_match = re.search(r"([一二两俩三四五六七八九十\d]+)(?:张|位|人|个大人|个人)", normalized)
    if count_match:
        party_count = parse_count_token(count_match.group(1))
        if party_count and party_count >= 3 and ticket_kind is None:
            ticket_kind = "single"

    asks_price = any(word in normalized for word in ["多少", "价格", "多少钱", "几钱", "报价"])

    return PackageIntent(
        day_type=day_type,
        duration_hours=duration_hours,
        overnight=overnight,
        ticket_kind=ticket_kind,
        party_count=party_count,
        asks_price=asks_price,
    )


def offer_label_from_intent(intent: PackageIntent) -> str:
    parts = []
    if intent.day_type == "workday":
        parts.append("工作日")
    elif intent.day_type == "holiday":
        parts.append("节假日")
    elif intent.day_type == "weekend":
        parts.append("周末")
    if intent.duration_hours:
        parts.append(f"{intent.duration_hours}H")
    if intent.overnight is True:
        parts.append("过夜/夜场")
    elif intent.overnight is False:
        parts.append("不过夜")
    kind_names = {
        "single": "单人",
        "double": "双人",
        "family": "亲子",
        "child": "儿童",
        "student": "学生",
    }
    if intent.ticket_kind:
        parts.append(kind_names.get(intent.ticket_kind, intent.ticket_kind))
    return "".join(parts) or "对应"


def compatible_day_type(wanted: str | None, offered: str | None) -> bool:
    if not wanted or not offered:
        return False
    if wanted == offered:
        return True
    return {wanted, offered} <= {"weekend", "holiday"}


def infer_relative_day_type(normalized: str) -> str | None:
    offset: int | None = None
    if "大后天" in normalized:
        offset = 3
    elif "后天" in normalized:
        offset = 2
    elif "明天" in normalized:
        offset = 1
    elif "今天" in normalized:
        offset = 0
    if offset is None:
        return None
    target = datetime.now(ZoneInfo("Asia/Shanghai")).date() + timedelta(days=offset)
    return "weekend" if target.weekday() >= 5 else "workday"


def day_type_terms(day_type: str | None) -> list[str]:
    if day_type == "workday":
        return ["工作日", "平日", "周一", "周二", "周三", "周四", "周五"]
    if day_type == "weekend":
        return ["周末", "周六", "周日", "节假日", "假日"]
    if day_type == "holiday":
        return ["节假日", "假日", "周末", "周六", "周日"]
    return []


def offer_mentions_day_type(text_value: str, day_type: str | None) -> bool:
    normalized = normalize_text(text_value)
    return any(normalize_text(term) in normalized for term in day_type_terms(day_type))


def segment_crosses_other_day_type(segment: str, day_type: str | None) -> bool:
    segment_value = normalize_text(segment)
    allowed = {normalize_text(term) for term in day_type_terms(day_type)}
    for other_day_type in ["workday", "weekend", "holiday"]:
        if other_day_type == day_type:
            continue
        for term in day_type_terms(other_day_type):
            term_value = normalize_text(term)
            if term_value and term_value not in allowed and term_value in segment_value:
                return True
    return False


def offer_duration_for_day(text_value: str, day_type: str | None) -> int | None:
    if not day_type:
        return None
    normalized = normalize_text(text_value)
    for term in day_type_terms(day_type):
        term_value = normalize_text(term)
        pattern = rf"{re.escape(term_value)}(.{{0,16}}?)(?<!\d)(6|8|12|16|18|24)(?:h|小时|时)"
        for match in re.finditer(pattern, normalized):
            if not segment_crosses_other_day_type(match.group(1), day_type):
                return int(match.group(2))
    return None


def offer_has_day_duration(text_value: str, day_type: str | None, duration_hours: int | None) -> bool:
    if not day_type or not duration_hours:
        return False
    return offer_duration_for_day(text_value, day_type) == duration_hours


def offer_has_conflicting_duration_for_day(text_value: str, day_type: str | None, duration_hours: int | None) -> bool:
    if not day_type or not duration_hours:
        return False
    offered_duration = offer_duration_for_day(text_value, day_type)
    return offered_duration is not None and offered_duration != duration_hours


def contains_match_token(text_value: str, token: str) -> bool:
    normalized = normalize_text(text_value)
    token_value = normalize_text(token)
    if token_value == "工作日":
        return any(word in normalized for word in ["工作日", "平日"])
    if token_value == "节假日":
        return any(word in normalized for word in ["节假日", "假日", "周末"])
    if token_value in {"6h", "6小时"}:
        return bool(re.search(r"(?<!\d)6(?:h|小时)", normalized))
    if token_value in {"8h", "8小时"}:
        return bool(re.search(r"(?<!\d)8(?:h|小时)", normalized))
    if token_value in {"16h", "16小时"}:
        return bool(re.search(r"(?<!\d)16(?:h|小时)", normalized))
    if token_value in {"18h", "18小时"}:
        return bool(re.search(r"(?<!\d)18(?:h|小时)", normalized))
    if token_value in {"24h", "24小时"}:
        return bool(re.search(r"(?<!\d)24(?:h|小时)", normalized))
    return bool(token_value and token_value in normalized)


def message_implies_regular_single_ticket(normalized_message: str) -> bool:
    """买家说三张/几位成人时，默认是普通单人成人票数量，不再继续追问单人/双人。"""
    if any(word in normalized_message for word in ["双人", "两人票", "2人票", "亲子", "儿童", "学生"]):
        return False
    return bool(
        re.search(r"[一二两三四五六七八九十\d]+(?:张|位|个人|个|人)", normalized_message)
        or any(word in normalized_message for word in ["成人", "大人"])
    )


def message_rejects_overnight(normalized_message: str) -> bool:
    return any(word in normalized_message for word in ["不过夜", "不住", "不留宿", "当天走", "当天回", "不要过夜"])


def message_mentions_daytime_duration(normalized_message: str) -> bool:
    return any(word in normalized_message for word in ["18h", "18小时", "18时", "十八小时", "白天票", "白天"])


def should_skip_package_reply(message: str) -> bool:
    normalized = normalize_text(message)
    if not normalized:
        return True
    skip_exact = {"好的", "好", "嗯", "嗯嗯", "没事", "谢谢", "在", "在吗", "人呢", "你好", "您好", "回答问题", "会发你团口令", "现在", "？", "?"}
    if re.fullmatch(r"\d{2,4}", normalized):
        return True
    if normalized in skip_exact:
        return True
    skip_fragments = ["买了别人的", "不用了", "不需要", "算了", "下次", "谢谢", "没便宜"]
    return any(fragment in normalized for fragment in skip_fragments)


def parse_offer_index_request(message: str) -> int | None:
    indexes = parse_offer_index_requests(message)
    return indexes[0] if len(indexes) == 1 else None


def parse_offer_index_requests(message: str) -> list[int]:
    normalized = normalize_text(message)
    number_token = r"[一二两俩三四五六七八九十\d]+"
    single_index_token = r"[一二两俩三四五六七八九]"
    blocked_suffix = r"(?![个人张位小时h月点:：])"
    if re.search(r"\d{1,2}月\d{1,2}号?", normalized):
        return []
    if any(word in normalized for word in ["多少钱", "多少", "价格", "报价", "几钱"]):
        normalized_price = re.sub(r"^(?:你好|您好)[,，。！!、]*", "", normalized)
        multi = re.fullmatch(
            rf"(?:你好|您好|请问)?({number_token})(?:号)?(?:和|跟|与|、|,|，|\+|＋|/)+({number_token})(?:号)?(?:的)?(?:多少钱|多少|价格|报价|几钱)?[?？]?",
            normalized_price,
        )
        if multi:
            indexes = [parse_count_token(value) for value in multi.groups()]
            return [value for value in indexes if value is not None]
        numbered_price = re.fullmatch(
            rf"(?:你好|您好|请问)?({number_token})(?:号|号套餐|套餐)?(?:的)?(?:多少钱|多少|价格|报价|几钱)[?？]?",
            normalized_price,
        )
        if numbered_price:
            value = parse_count_token(numbered_price.group(1))
            return [value] if value is not None else []
    patterns = [
        rf"(?:咨询|要|发|选|挑|给我|我要|来|看|定|拍)?套餐第?({number_token}){blocked_suffix}",
        rf"套餐第({number_token}){blocked_suffix}",
        rf"第({number_token})(?:个|款|项|种|号|套|套餐)?{blocked_suffix}",
        rf"(?:咨询|要|想要|发|选|挑|给我|我要|来|看|定|拍)第?({number_token})(?:个|款|项|种|号|套|套餐)?{blocked_suffix}",
        rf"(?<!月)({number_token})号套餐",
        rf"^({number_token})号$",
        r"^([1-9])$",
        rf"^({single_index_token})$",
    ]
    for pattern in patterns:
        match = re.search(pattern, normalized)
        if match:
            value = parse_count_token(match.group(1))
            return [value] if value is not None else []
    return []


def extract_keywords(package_name: str) -> list[str]:
    seeds = re.split(r"[｜|/、，,＋+\s【】\[\]（）()·]+", package_name)
    keywords = []
    for seed in seeds:
        word = seed.strip()
        if len(word) >= 2 and not re.fullmatch(r"\d+(?:\.\d+)?元?", word):
            keywords.append(word)
    return list(dict.fromkeys(keywords))[:20]


def parse_package_material(raw_text: str) -> list[dict[str, Any]]:
    """从粘贴素材里解析套餐名和口令，忽略价格与下单链接。"""
    text_value = re.sub(r"\s*(🎁【)", r"\n\1", str(raw_text or "")).strip()
    if not text_value:
        return []

    titles: list[tuple[int, int, str]] = []
    offset = 0
    for line in text_value.splitlines(keepends=True):
        stripped = line.strip()
        match = TITLE_LINE_PATTERN.match(stripped)
        if match:
            title = match.group(1).strip()
            if title not in MATERIAL_FIELD_TITLES:
                title_start = offset + line.find(stripped)
                titles.append((title_start, title_start + len(stripped), title))
        offset += len(line)
    if not titles:
        return []

    entries: list[dict[str, Any]] = []
    for index, (start, end, title) in enumerate(titles):
        next_start = titles[index + 1][0] if index + 1 < len(titles) else len(text_value)
        block = text_value[start:next_start].strip()
        full_match = FULL_COMMAND_CONTEXT.search(block)
        numeric_match = NUMERIC_COMMAND_CONTEXT.search(block)
        command_value = ""
        command_type = "numeric"
        if full_match:
            cleaned_lines = [
                line.strip()
                for line in full_match.group(1).splitlines()
                if line.strip() and not PRICE_OR_LINK_LINE.search(line) and not MATERIAL_NOISE_LINE.fullmatch(line.strip())
            ]
            command_value = "\n".join(cleaned_lines).strip()
            command_type = "group_text"
        elif numeric_match:
            command_value = numeric_match.group(2)
        if not command_value:
            continue
        entries.append(
            {
                "package_name": title,
                "command_type": command_type,
                "command_value": command_value,
                "keywords": extract_keywords(title),
                "source_text": block,
            }
        )
    return entries


def build_package_reply_text(offer: XYPackageOffer, venue: XYPackageVenue) -> str:
    command = (offer.command_value or "").strip()
    if offer.command_type == "numeric":
        command_line = f"美团搜索口令：{command}"
    else:
        command_line = f"团口令：\n{command}"
    return (
        f"可以的，给您匹配到：{venue.city}{venue.venue_name}\n"
        f"套餐：{offer.package_name}\n"
        f"{command_line}\n\n"
        "先打开美团搜索 86886 领红包，再复制上面的口令去购买。\n"
        "这个一定会比自己在美团直接买更便宜。\n"
        "使用规则和库存以确认时为准，确认后再拍/购买。"
    )


def build_package_clarification_text(venue: XYPackageVenue) -> str:
    return (
        f"{venue.city}{venue.venue_name}这边有多个套餐，我先帮您确认一下：\n"
        "您要的是工作日/节假日、单人/双人、18H/过夜，还是儿童/学生票？\n\n"
        "先打开美团搜索 86886 领红包，确认套餐后我发对应口令。\n"
        "会比自己在美团直接买更便宜。\n"
        "使用规则和库存以确认时为准，确认后再拍/购买。"
    )


class PackageReplyService:
    """套餐回复配置与匹配。"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_venues(self, owner_id: int | None = None) -> list[dict[str, Any]]:
        stmt = select(XYPackageVenue).order_by(XYPackageVenue.city, XYPackageVenue.brand, XYPackageVenue.venue_name)
        if owner_id is not None:
            stmt = stmt.where(or_(XYPackageVenue.owner_id == owner_id, XYPackageVenue.owner_id.is_(None)))
        rows = (await self.session.execute(stmt)).scalars().all()
        venue_ids = [row.id for row in rows]
        offer_counts: dict[int, int] = {}
        binding_counts: dict[int, int] = {}
        if venue_ids:
            offer_rows = await self.session.execute(
                select(XYPackageOffer.venue_id, func.count().label("cnt"))
                .where(XYPackageOffer.venue_id.in_(venue_ids))
                .group_by(XYPackageOffer.venue_id)
            )
            offer_counts = {int(row.venue_id): int(row.cnt) for row in offer_rows}
            bind_rows = await self.session.execute(
                select(XYItemPackageBinding.venue_id, func.count().label("cnt"))
                .where(XYItemPackageBinding.venue_id.in_(venue_ids))
                .group_by(XYItemPackageBinding.venue_id)
            )
            binding_counts = {int(row.venue_id): int(row.cnt) for row in bind_rows}
        return [self.serialize_venue(row, offer_counts.get(row.id, 0), binding_counts.get(row.id, 0)) for row in rows]

    async def get_offers(self, venue_id: int) -> list[dict[str, Any]]:
        stmt = select(XYPackageOffer).where(XYPackageOffer.venue_id == venue_id).order_by(XYPackageOffer.sort_order, XYPackageOffer.id)
        rows = (await self.session.execute(stmt)).scalars().all()
        return [self.serialize_offer(row) for row in rows]

    async def upsert_venue(self, payload: dict[str, Any], owner_id: int | None) -> XYPackageVenue:
        venue_id = int(payload.get("id") or 0)
        venue = await self.session.get(XYPackageVenue, venue_id) if venue_id else None
        if not venue:
            venue = XYPackageVenue(owner_id=owner_id)
            self.session.add(venue)
        venue.category = str(payload.get("category") or "洗浴").strip() or "洗浴"
        venue.city = str(payload.get("city") or "").strip()
        venue.area = str(payload.get("area") or "").strip() or None
        venue.brand = str(payload.get("brand") or "").strip()
        venue.venue_name = str(payload.get("venue_name") or "").strip()
        venue.address_note = str(payload.get("address_note") or "").strip() or None
        venue.aliases_json = self._normalize_list(payload.get("aliases"))
        venue.enabled = bool(payload.get("enabled", True))
        await self.session.commit()
        await self.session.refresh(venue)
        return venue

    async def upsert_offer(self, venue_id: int, payload: dict[str, Any]) -> XYPackageOffer:
        offer_id = int(payload.get("id") or 0)
        offer = await self.session.get(XYPackageOffer, offer_id) if offer_id else None
        if not offer:
            offer = XYPackageOffer(venue_id=venue_id)
            self.session.add(offer)
        offer.venue_id = venue_id
        offer.package_name = str(payload.get("package_name") or "").strip()
        offer.keywords_json = self._normalize_list(payload.get("keywords")) or extract_keywords(offer.package_name)
        offer.command_type = str(payload.get("command_type") or "numeric").strip() or "numeric"
        offer.command_value = str(payload.get("command_value") or "").strip()
        offer.source_text = str(payload.get("source_text") or "").strip() or None
        offer.applicability_note = str(payload.get("applicability_note") or "").strip() or None
        offer.protected = bool(payload.get("protected", True))
        offer.enabled = bool(payload.get("enabled", True))
        offer.sort_order = int(payload.get("sort_order") or 100)
        await self.session.commit()
        await self.session.refresh(offer)
        return offer

    async def delete_offer(self, offer_id: int) -> bool:
        result = await self.session.execute(delete(XYPackageOffer).where(XYPackageOffer.id == offer_id))
        await self.session.commit()
        return bool(result.rowcount)

    async def bind_item(self, owner_id: int | None, account_id: str, item_id: str, venue_id: int, protected: bool = True) -> XYItemPackageBinding:
        stmt = select(XYItemPackageBinding).where(
            XYItemPackageBinding.account_id == account_id,
            XYItemPackageBinding.item_id == item_id,
        )
        binding = (await self.session.execute(stmt)).scalars().first()
        if not binding:
            binding = XYItemPackageBinding(account_id=account_id, item_id=item_id, owner_id=owner_id)
            self.session.add(binding)
        binding.venue_id = venue_id
        binding.protected = protected
        binding.enabled = True
        await self.session.commit()
        await self.session.refresh(binding)
        return binding

    async def import_material(self, owner_id: int | None, venue_id: int | None, raw_text: str) -> dict[str, Any]:
        parsed = parse_package_material(raw_text)
        imported: list[dict[str, Any]] = []
        if not parsed:
            candidate = XYPackageImportCandidate(
                owner_id=owner_id,
                raw_text=raw_text,
                parsed_json={},
                status="pending",
                reason="未识别到套餐名和明确口令",
            )
            self.session.add(candidate)
            await self.session.commit()
            return {"imported": [], "candidates": [candidate.id]}
        if not venue_id:
            candidate = XYPackageImportCandidate(
                owner_id=owner_id,
                raw_text=raw_text,
                parsed_json={"entries": parsed},
                status="pending",
                reason="需要先选择门店后才能落库",
            )
            self.session.add(candidate)
            await self.session.commit()
            return {"imported": [], "candidates": [candidate.id], "parsed": parsed}
        for entry in parsed:
            offer = await self.upsert_offer(venue_id, entry)
            imported.append(self.serialize_offer(offer))
        return {"imported": imported, "candidates": [], "parsed": parsed}

    async def seed_known_numeric_commands(self, owner_id: int | None = None) -> dict[str, int]:
        venue_cache: dict[tuple[str, str, str], XYPackageVenue] = {}
        created_offers = 0
        created_venues = 0
        for item in KNOWN_NUMERIC_COMMANDS:
            key = (item["city"], item["brand"], item["venue_name"])
            venue = venue_cache.get(key)
            if venue is None:
                venue = await self._find_or_create_venue(item, owner_id)
                venue_cache[key] = venue
                created_venues += 1
            stmt = select(XYPackageOffer).where(
                XYPackageOffer.venue_id == venue.id,
                XYPackageOffer.command_value == item["command_value"],
            )
            offer = (await self.session.execute(stmt)).scalars().first()
            if not offer:
                offer = XYPackageOffer(
                    venue_id=venue.id,
                    package_name=item["package_name"],
                    keywords_json=extract_keywords(item["package_name"]),
                    command_type="numeric",
                    command_value=item["command_value"],
                    protected=True,
                    enabled=True,
                )
                self.session.add(offer)
                created_offers += 1
        await self.session.commit()
        return {"venues_seen": created_venues, "offers_created": created_offers}

    async def seed_bindings_from_protected_items(self, owner_id: int | None = None) -> int:
        protected_exists = await self._table_exists("xy_protected_items")
        if not protected_exists:
            return 0
        rows = await self.session.execute(
            text(
                """
                SELECT p.account_id, p.item_id, c.title
                FROM xy_protected_items p
                LEFT JOIN xy_accounts a ON a.account_id = p.account_id
                LEFT JOIN xy_catalog_items c ON c.account_id = a.id AND c.item_id = p.item_id
                WHERE p.item_id IS NOT NULL
                """
            )
        )
        count = 0
        venues = (await self.session.execute(select(XYPackageVenue))).scalars().all()
        for row in rows:
            venue = self._match_venue_by_text(str(row.title or ""), venues)
            if not venue:
                continue
            await self.bind_item(owner_id, str(row.account_id), str(row.item_id), venue.id, protected=True)
            count += 1
        return count

    async def match_for_message(self, account_id: str, item_id: str | None, message: str) -> PackageReplyMatch:
        binding: XYItemPackageBinding | None = None
        if item_id:
            stmt = select(XYItemPackageBinding).where(
                XYItemPackageBinding.account_id == account_id,
                XYItemPackageBinding.item_id == item_id,
                XYItemPackageBinding.enabled.is_(True),
            )
            binding = (await self.session.execute(stmt)).scalars().first()
        venue: XYPackageVenue | None = None
        if binding:
            venue = await self.session.get(XYPackageVenue, binding.venue_id)
        if not venue:
            venue = await self._infer_venue(account_id, item_id, message)
        if not venue or not venue.enabled:
            return PackageReplyMatch(None, None, 0, "no_venue", True)
        if should_skip_package_reply(message):
            return PackageReplyMatch(None, venue, 0, "no_package_intent", False)
        offers = (await self.session.execute(
            select(XYPackageOffer).where(
                XYPackageOffer.venue_id == venue.id,
                XYPackageOffer.enabled.is_(True),
            ).order_by(XYPackageOffer.sort_order, XYPackageOffer.id)
        )).scalars().all()
        if not offers:
            return PackageReplyMatch(None, venue, 0, "no_offer", True)

        direct_match = self._match_direct_command_or_index(message, venue, offers)
        if direct_match:
            return direct_match

        ai_match = await self._match_offer_with_ai(account_id, message, venue, offers)
        ai_match_safe = bool(
            ai_match
            and ai_match.confidence >= 0.62
            and not ai_match.need_clarification
            and ai_match.offer
            and self._ai_offer_passes_hard_constraints(message, ai_match.offer)
        )
        if ai_match_safe:
            return ai_match

        intent_match = self._match_offer_by_intent(message, venue, offers)
        if intent_match and (intent_match.custom_reply or intent_match.confidence >= 0.74):
            return intent_match

        custom_reply = self._build_direct_options_reply(message, venue, offers)
        if custom_reply:
            return PackageReplyMatch(None, venue, 0.84, "direct_venue_options", False, custom_reply)

        heuristic = self._match_offer_heuristic(message, venue, offers)
        if heuristic.confidence >= 0.72 or len(offers) == 1:
            return heuristic

        return PackageReplyMatch(None, venue, heuristic.confidence, "need_clarification", True)

    async def build_reply_for_message(self, account_id: str, item_id: str | None, message: str) -> str | None:
        match = await self.match_for_message(account_id, item_id, message)
        if match.custom_reply and match.venue and not match.need_clarification:
            return match.custom_reply
        if match.offer and match.venue and not match.need_clarification:
            return build_package_reply_text(match.offer, match.venue)
        if match.venue and match.need_clarification:
            return build_package_clarification_text(match.venue)
        return None

    async def test_match(self, account_id: str, item_id: str | None, message: str) -> dict[str, Any]:
        match = await self.match_for_message(account_id, item_id, message)
        return {
            "matched": bool(match.offer or match.custom_reply),
            "need_clarification": match.need_clarification,
            "confidence": match.confidence,
            "reason": match.reason,
            "venue": self.serialize_venue(match.venue) if match.venue else None,
            "offer": self.serialize_offer(match.offer) if match.offer else None,
            "reply": (
                match.custom_reply
                if match.custom_reply
                else
                build_package_reply_text(match.offer, match.venue)
                if match.offer and match.venue
                else build_package_clarification_text(match.venue)
                if match.venue and match.need_clarification
                else ""
            ),
        }

    def _build_direct_options_reply(
        self,
        message: str,
        venue: XYPackageVenue,
        offers: list[XYPackageOffer],
    ) -> str | None:
        normalized = normalize_text(message)
        venue_text = normalize_text(venue.venue_name)
        if "海德汤泉望京" not in venue_text or not message_mentions_daytime_duration(normalized):
            return None

        daytime_offers = [
            offer for offer in offers
            if contains_match_token(offer.package_name, "16h")
            and contains_match_token(offer.package_name, "单人")
            and not any(
                contains_match_token(offer.package_name, token)
                for token in ["夜间", "夜场", "夜票", "过夜", "过夜费", "夜宵", "早餐", "午夜", "双人", "儿童", "学生"]
            )
        ]
        if not daytime_offers:
            return None

        def offer_rank(offer: XYPackageOffer) -> int:
            if any(contains_match_token(offer.package_name, token) for token in ["工作日", "周一", "周二", "周三", "周四", "周五"]):
                return 0
            if any(contains_match_token(offer.package_name, token) for token in ["节假日", "周末", "周六", "周日"]):
                return 1
            return 2

        lines = ["可以，望京店白天票发您这个："]
        for offer in sorted(daytime_offers, key=offer_rank)[:2]:
            lines.append("")
            lines.append(f"{offer.package_name}：")
            lines.append((offer.command_value or "").strip())
        lines.append("")
        lines.append("先打开美团搜索 86886 领红包，再按使用日期选对应口令下单。")
        return "\n".join(line for line in lines if line is not None)

    def _match_offer_by_intent(
        self,
        message: str,
        venue: XYPackageVenue,
        offers: list[XYPackageOffer],
    ) -> PackageReplyMatch | None:
        intent = parse_package_intent(message)
        if not intent.has_specific_constraints:
            return None

        overnight_reply = self._build_overnight_reply(message, intent, venue, offers)
        if overnight_reply:
            return PackageReplyMatch(None, venue, 0.8, "structured_overnight", False, overnight_reply)

        party_reply = self._build_party_count_reply(message, intent, venue, offers)
        if party_reply:
            return PackageReplyMatch(None, venue, 0.78, "structured_party_count", False, party_reply)

        ticket_kind_reply = self._build_ticket_kind_reply(intent, venue, offers)
        if ticket_kind_reply:
            return PackageReplyMatch(None, venue, 0.82, "structured_ticket_kind", False, ticket_kind_reply)

        day_price_reply = self._build_day_price_reply(intent, venue, offers)
        if day_price_reply:
            return PackageReplyMatch(None, venue, 0.8, "structured_day_price", False, day_price_reply)

        day_duration_reply = self._build_day_duration_near_reply(intent, venue, offers)
        if day_duration_reply:
            return PackageReplyMatch(None, venue, 0.78, "structured_day_duration_near", False, day_duration_reply)

        scored: list[tuple[float, int, XYPackageOffer, PackageIntent]] = []
        for offer in offers:
            offer_intent = parse_package_intent(offer.package_name)
            score = 0.0
            conflicts = 0

            if intent.day_type:
                if intent.duration_hours and offer_has_day_duration(offer.package_name, intent.day_type, intent.duration_hours):
                    score += 0.28
                elif offer_mentions_day_type(offer.package_name, intent.day_type):
                    score += 0.28
                elif compatible_day_type(intent.day_type, offer_intent.day_type):
                    score += 0.28
                elif offer_intent.day_type:
                    score -= 0.45
                    conflicts += 1

            if intent.duration_hours:
                if offer_intent.duration_hours == intent.duration_hours:
                    score += 0.32
                elif offer_intent.duration_hours:
                    if intent.duration_hours == 18 and offer_intent.duration_hours == 16 and "望京" in normalize_text(venue.venue_name):
                        score += 0.08
                    else:
                        score -= 0.36
                        conflicts += 1

            if intent.day_type and intent.duration_hours:
                if offer_has_day_duration(offer.package_name, intent.day_type, intent.duration_hours):
                    score += 0.25
                elif offer_has_conflicting_duration_for_day(offer.package_name, intent.day_type, intent.duration_hours):
                    score -= 0.55
                    conflicts += 1

            if intent.overnight is not None:
                if offer_intent.overnight == intent.overnight:
                    score += 0.3
                elif offer_intent.overnight is not None:
                    score -= 0.55
                    conflicts += 1
                elif intent.overnight is False:
                    score += 0.08

            if intent.ticket_kind:
                if offer_intent.ticket_kind == intent.ticket_kind:
                    score += 0.3
                elif intent.ticket_kind == "single" and offer_intent.ticket_kind is None:
                    score += 0.08
                elif offer_intent.ticket_kind:
                    score -= 0.5
                    conflicts += 1

            if intent.party_count and intent.party_count >= 3:
                if offer_intent.ticket_kind in {"double", "family", "child", "student"}:
                    score -= 0.42
                    conflicts += 1
                else:
                    score += 0.12

            if intent.asks_price:
                score += 0.05

            if score > 0:
                scored.append((score, conflicts, offer, offer_intent))

        if not scored:
            return None

        scored.sort(key=lambda item: (item[0], -item[1]), reverse=True)
        best_score, best_conflicts, best_offer, _ = scored[0]
        second_score = scored[1][0] if len(scored) > 1 else 0.0
        has_enough_signal = best_score >= 0.62 and (best_score - second_score >= 0.18 or best_score >= 0.82)

        if best_conflicts == 0 and has_enough_signal:
            confidence = min(0.98, 0.58 + best_score * 0.32)
            return PackageReplyMatch(best_offer, venue, confidence, "structured_intent")

        relevant = [offer for score, conflicts, offer, _ in scored if conflicts == 0 and score >= 0.45]
        if intent.duration_hours and len(relevant) >= 2:
            label = offer_label_from_intent(intent)
            lines = [f"可以，{venue.venue_name}{label}相关的发您这几个："]
            for offer in relevant[:3]:
                lines.append("")
                lines.append(f"{offer.package_name}：")
                lines.append((offer.command_value or "").strip())
            lines.append("")
            lines.append("先打开美团搜索 86886 领红包，再按使用日期选对应口令下单。")
            return PackageReplyMatch(None, venue, 0.78, "structured_intent_options", False, "\n".join(lines))

        if intent.day_type and intent.duration_hours and scored:
            label = offer_label_from_intent(intent)
            near_offers = []
            for score, _, offer, offer_intent in scored:
                if score <= 0:
                    continue
                same_kind = not intent.ticket_kind or offer_intent.ticket_kind == intent.ticket_kind
                if same_kind:
                    near_offers.append(offer)
            if near_offers:
                lines = [f"这个没有完全一致的{label}套餐，当前相近可用的发您："]
                for offer in near_offers[:2]:
                    lines.append("")
                    lines.append(f"{offer.package_name}：")
                    lines.append((offer.command_value or "").strip())
                lines.append("")
                lines.append("先打开美团搜索 86886 领红包，再按实际使用日期和页面规则下单。")
                return PackageReplyMatch(None, venue, 0.72, "structured_intent_near_options", False, "\n".join(lines))

        return None

    def _build_ticket_kind_reply(
        self,
        intent: PackageIntent,
        venue: XYPackageVenue,
        offers: list[XYPackageOffer],
    ) -> str | None:
        if not intent.ticket_kind or intent.day_type or intent.duration_hours or intent.overnight is not None or intent.party_count:
            return None
        candidates = []
        for offer in offers:
            offer_intent = parse_package_intent(offer.package_name)
            if offer_intent.ticket_kind == intent.ticket_kind:
                candidates.append(offer)
        if not candidates:
            return None
        offer = candidates[0]
        command = (offer.command_value or "").strip()
        command_line = f"美团搜索口令：{command}" if offer.command_type == "numeric" else f"团口令：\n{command}"
        return (
            f"可以，{offer_label_from_intent(intent)}票按这个：\n"
            f"{offer.package_name}\n"
            f"{command_line}\n\n"
            "先打开美团搜索 86886 领红包，再按实际使用日期和页面规则下单。"
        )

    def _build_day_price_reply(
        self,
        intent: PackageIntent,
        venue: XYPackageVenue,
        offers: list[XYPackageOffer],
    ) -> str | None:
        if not intent.day_type or not intent.asks_price:
            return None
        if intent.duration_hours or intent.overnight is not None or intent.ticket_kind or intent.party_count:
            return None
        candidates = [
            offer
            for offer in offers
            if offer_mentions_day_type(offer.package_name, intent.day_type)
            and not any(
                contains_match_token(offer.package_name, token)
                for token in ["夜间", "夜场", "夜票", "过夜", "过夜费", "夜宵", "早餐", "午夜", "双人", "儿童", "学生", "亲子"]
            )
        ]
        if not candidates:
            return None
        offer = candidates[0]
        command = (offer.command_value or "").strip()
        command_line = f"美团搜索口令：{command}" if offer.command_type == "numeric" else f"团口令：\n{command}"
        day_label = "工作日" if intent.day_type == "workday" else "周末/节假日"
        return (
            f"{day_label}按这个套餐：\n"
            f"{offer.package_name}\n"
            f"{command_line}\n\n"
            "先打开美团搜索 86886 领红包，再按上面口令下单。"
        )

    def _build_party_count_reply(
        self,
        message: str,
        intent: PackageIntent,
        venue: XYPackageVenue,
        offers: list[XYPackageOffer],
    ) -> str | None:
        if not intent.party_count or intent.duration_hours or intent.overnight is not None:
            return None
        candidates = [
            offer
            for offer in offers
            if not any(
                contains_match_token(offer.package_name, token)
                for token in ["夜间", "夜场", "夜票", "过夜", "过夜费", "夜宵", "早餐", "午夜", "双人", "儿童", "学生", "亲子"]
            )
        ]
        if not candidates:
            return None
        if contains_match_token(message, "自助"):
            candidates.sort(key=lambda offer: 0 if contains_match_token(offer.package_name, "自助") else 1)
        offer = candidates[0]
        command = (offer.command_value or "").strip()
        command_line = f"美团搜索口令：{command}" if offer.command_type == "numeric" else f"团口令：\n{command}"
        return (
            f"{intent.party_count}位按单人票分别下单，先发您这个：\n"
            f"{offer.package_name}\n"
            f"{command_line}\n\n"
            "先打开美团搜索 86886 领红包，再按实际使用日期和页面规则下单。"
        )

    def _build_overnight_reply(
        self,
        message: str,
        intent: PackageIntent,
        venue: XYPackageVenue,
        offers: list[XYPackageOffer],
    ) -> str | None:
        if intent.overnight is not True:
            return None
        normalized_message = normalize_text(message)
        weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        last_weekday_pos, last_weekday = max(
            ((normalized_message.rfind(weekday), weekday) for weekday in weekdays),
            default=(-1, ""),
        )
        if last_weekday_pos < 0:
            last_weekday = ""
        candidates = []
        for offer in offers:
            offer_intent = parse_package_intent(offer.package_name)
            if offer_intent.overnight is not True:
                continue
            score = 0
            if intent.day_type:
                if offer_mentions_day_type(offer.package_name, intent.day_type):
                    score += 3
                elif compatible_day_type(intent.day_type, offer_intent.day_type):
                    score += 2
                elif offer_intent.day_type:
                    score -= 3
            offer_text = normalize_text(offer.package_name)
            for weekday in ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]:
                if weekday in normalized_message:
                    if weekday in offer_text:
                        score += 3
                    else:
                        score -= 2
            if last_weekday:
                if last_weekday in offer_text:
                    score += 5
                else:
                    score -= 3
            if intent.ticket_kind and offer_intent.ticket_kind == intent.ticket_kind:
                score += 1
            candidates.append((score, offer))
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0], reverse=True)
        if candidates[0][0] < 0:
            return None
        offer = candidates[0][1]
        command = (offer.command_value or "").strip()
        command_line = f"美团搜索口令：{command}" if offer.command_type == "numeric" else f"团口令：\n{command}"
        return (
            f"夜票/过夜按这个套餐：\n"
            f"{offer.package_name}\n"
            f"{command_line}\n\n"
            "先打开美团搜索 86886 领红包，再按实际使用日期和页面规则下单。"
        )

    def _build_day_duration_near_reply(
        self,
        intent: PackageIntent,
        venue: XYPackageVenue,
        offers: list[XYPackageOffer],
    ) -> str | None:
        if not intent.day_type or not intent.duration_hours:
            return None
        if any(offer_has_day_duration(offer.package_name, intent.day_type, intent.duration_hours) for offer in offers):
            return None
        alternatives: list[tuple[int, XYPackageOffer]] = []
        for offer in offers:
            offered_duration = offer_duration_for_day(offer.package_name, intent.day_type)
            if offered_duration is None or offered_duration == intent.duration_hours:
                continue
            offer_intent = parse_package_intent(offer.package_name)
            if intent.ticket_kind and offer_intent.ticket_kind not in {None, intent.ticket_kind}:
                continue
            alternatives.append((offered_duration, offer))
        if not alternatives:
            return None
        offered_duration, offer = alternatives[0]
        requested_label = offer_label_from_intent(intent)
        day_label = "工作日" if intent.day_type == "workday" else "周末/节假日"
        command = (offer.command_value or "").strip()
        command_line = f"美团搜索口令：{command}" if offer.command_type == "numeric" else f"团口令：\n{command}"
        return (
            f"没有完全一致的{requested_label}，{day_label}是{offered_duration}小时这个：\n"
            f"{offer.package_name}\n"
            f"{command_line}\n\n"
            "先打开美团搜索 86886 领红包，再按实际使用日期和页面规则下单。"
        )

    def _match_direct_command_or_index(
        self,
        message: str,
        venue: XYPackageVenue,
        offers: list[XYPackageOffer],
    ) -> PackageReplyMatch | None:
        for command in DIRECT_COMMAND_PATTERN.findall(normalize_text(message)):
            for offer in offers:
                if command in normalize_text(offer.command_value):
                    return PackageReplyMatch(offer, venue, 0.96, "direct_command")
        offer_indexes = parse_offer_index_requests(message)
        if len(offer_indexes) > 1:
            selected: list[tuple[int, XYPackageOffer]] = []
            seen: set[int] = set()
            for offer_index in offer_indexes:
                if offer_index in seen or not (1 <= offer_index <= len(offers)):
                    continue
                seen.add(offer_index)
                selected.append((offer_index, offers[offer_index - 1]))
            if selected:
                lines = [f"{venue.city}{venue.venue_name}给您发对应套餐口令："]
                for offer_index, offer in selected:
                    command = (offer.command_value or "").strip()
                    command_line = f"美团搜索口令：{command}" if offer.command_type == "numeric" else f"团口令：\n{command}"
                    lines.append("")
                    lines.append(f"{offer_index}号套餐：{offer.package_name}")
                    lines.append(command_line)
                lines.append("")
                lines.append("先打开美团搜索 86886 领红包，再按对应口令下单。")
                lines.append("使用规则和库存以确认时为准，确认后再拍/购买。")
                return PackageReplyMatch(None, venue, 0.9, "direct_offer_indexes", False, "\n".join(lines))
        offer_index = parse_offer_index_request(message)
        if offer_index and 1 <= offer_index <= len(offers):
            return PackageReplyMatch(offers[offer_index - 1], venue, 0.82, "direct_offer_index")
        return None

    def _match_offer_heuristic(self, message: str, venue: XYPackageVenue, offers: list[XYPackageOffer]) -> PackageReplyMatch:
        normalized = normalize_text(message)
        generic_buy = any(word in normalized for word in ["怎么买", "能用吗", "可以用吗", "怎么拍", "咨询", "美团搜", "美团怎么搜", "怎么下单"])
        wants_regular_single = message_implies_regular_single_ticket(normalized)
        rejects_overnight = message_rejects_overnight(normalized)
        if contains_match_token(message, "工作日") and wants_regular_single and rejects_overnight:
            for offer in offers:
                if (
                    contains_match_token(offer.package_name, "工作日")
                    and not any(contains_match_token(offer.package_name, token) for token in ["双人", "亲子", "儿童", "学生"])
                    and not any(
                        contains_match_token(offer.package_name, token)
                        for token in ["夜间", "夜场", "夜票", "过夜", "过夜费", "夜宵", "早餐"]
                    )
                ):
                    return PackageReplyMatch(offer, venue, 0.84, "regular_workday_single_ticket")
        best_offer: XYPackageOffer | None = None
        best_score = 0.0
        for offer in offers:
            score = 0.0
            matched_strong_tokens = 0
            conflict_count = 0
            keywords = list(offer.keywords_json or []) + extract_keywords(offer.package_name)
            for keyword in keywords:
                key = normalize_text(keyword)
                if key and key in normalized:
                    score += min(0.28, 0.08 + len(key) * 0.018)
            package_text = normalize_text(offer.package_name)
            if "闲时" in normalized:
                if "闲时" in package_text:
                    score += 0.45
                    matched_strong_tokens += 1
                else:
                    score -= 0.7
                    conflict_count += 1
            for token in [
                "单人", "双人", "亲子", "1大1小", "成人", "儿童", "学生", "工作日", "节假日", "周末",
                "周一", "周二", "周三", "周四", "周五", "周六", "周日",
                "全天", "门票", "浴资", "夜", "夜票", "夜间", "过夜", "过夜费", "午夜", "服务费", "早餐", "自助",
                "6h", "6小时", "8h", "8小时", "16h", "16小时", "18h", "18小时", "24h", "24小时",
                "海鲜", "榴莲", "榴莲自由", "躺平计划", "早餐畅享", "龙之梦", "浑南",
                "搓澡", "护理", "施丹兰", "消费券", "免门票",
            ]:
                if contains_match_token(message, token) and contains_match_token(offer.package_name, token):
                    score += 0.16
                    matched_strong_tokens += 1

            if wants_regular_single:
                if any(contains_match_token(offer.package_name, token) for token in ["双人", "亲子", "儿童", "学生"]):
                    score -= 0.55
                    conflict_count += 1
                else:
                    score += 0.18
                    matched_strong_tokens += 1
            if rejects_overnight:
                if any(
                    contains_match_token(offer.package_name, token)
                    for token in ["夜间", "夜场", "夜票", "过夜", "过夜费", "夜宵", "早餐"]
                ):
                    score -= 0.65
                    conflict_count += 1
                else:
                    score += 0.18
                    matched_strong_tokens += 1
            conflict_pairs = [
                ("工作日", "节假日"),
                ("工作日", "周末"),
                ("工作日", "周六"),
                ("工作日", "周日"),
                ("8h", "18h"),
                ("8小时", "18小时"),
                ("单人", "双人"),
                ("周五", "周日"),
                ("周六", "周日"),
                ("周五", "周四"),
                ("周六", "周四"),
            ]
            for wanted, conflicting in conflict_pairs:
                if (
                    contains_match_token(message, wanted)
                    and not contains_match_token(offer.package_name, wanted)
                    and contains_match_token(offer.package_name, conflicting)
                ):
                    score -= 0.32
                    conflict_count += 1
                if (
                    contains_match_token(message, conflicting)
                    and not contains_match_token(offer.package_name, conflicting)
                    and contains_match_token(offer.package_name, wanted)
                ):
                    score -= 0.32
                    conflict_count += 1
            for required_token in ["学生", "双人", "亲子", "1大1小", "单人", "成人", "儿童"]:
                if contains_match_token(message, required_token) and not contains_match_token(offer.package_name, required_token):
                    score -= 0.45
                    conflict_count += 1
            if conflict_count == 0 and matched_strong_tokens >= 3 and score >= 0.5:
                score = max(score, 0.76)
            elif conflict_count == 0 and matched_strong_tokens >= 2 and score >= 0.3:
                score = max(score, 0.73)
            for optional_addon in ["榴莲", "海鲜", "自助", "娱乐"]:
                if not contains_match_token(message, optional_addon) and contains_match_token(offer.package_name, optional_addon):
                    score -= 0.12
            for numeric_marker in re.findall(r"\d{2,4}", normalize_text(message)):
                if numeric_marker in package_text:
                    score += 0.24
            number_match = re.search(r"(?:套餐|咨询)?\s*([1-9])", normalized)
            if number_match and (f"{number_match.group(1)}" in package_text or f"{number_match.group(1)}️⃣" in offer.package_name):
                score += 0.35
            if generic_buy:
                score += 0.18
            if score > best_score:
                best_score = score
                best_offer = offer
        if generic_buy and offers and (not best_offer or best_score < 0.72):
            return PackageReplyMatch(offers[0], venue, 0.76, "generic_single_or_first")
        if best_offer:
            return PackageReplyMatch(best_offer, venue, min(best_score, 0.98), "heuristic")
        return PackageReplyMatch(None, venue, 0, "no_offer_match", True)

    async def _match_offer_with_ai(
        self,
        account_id: str,
        message: str,
        venue: XYPackageVenue,
        offers: list[XYPackageOffer],
    ) -> PackageReplyMatch | None:
        settings = await self._get_package_ai_settings(account_id)
        api_key = settings.get("api_key") or os.getenv("PACKAGE_REPLY_AI_API_KEY") or os.getenv("SILICONFLOW_API_KEY")
        if not api_key:
            return None
        base_url = settings.get("base_url") or os.getenv("PACKAGE_REPLY_AI_BASE_URL", "https://api.siliconflow.com/v1")
        model = settings.get("model_name") or os.getenv("PACKAGE_REPLY_AI_MODEL", "zai-org/GLM-5.2")
        offers_payload = [
            {
                "index": index,
                "id": offer.id,
                "package_name": offer.package_name,
                "keywords": offer.keywords_json or [],
            }
            for index, offer in enumerate(offers, start=1)
        ]
        today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
        prompt = (
            "你是闲鱼客服套餐匹配器。根据买家一句话，从 offers 里选择一个最匹配的 offer_id。"
            "入口选择套餐必须优先理解买家的真实话术，包括“第几个/几号/选几”、工作日/周末/节假日、"
            "明天/后天、单人/双人/儿童/学生、8H/18H/24H、过夜/夜票/搓澡/自助/榴莲等信息。"
            "如果买家说序号，例如“第4个”“4号”“选三”，按 offers 的 index 选择对应套餐。"
            "如果买家已给出足够条件能唯一匹配套餐，不要再追问，直接返回对应 offer_id。"
            "今天日期按 Asia/Shanghai 计算，明天/后天要先换算成工作日或周末。"
            "如果买家说的时长和日型没有完全一致，但同一套餐标题明确写了该日型的可用时长，可以选择这个相近套餐。"
            "不要编造套餐、价格、链接；不要选择 offers 以外的套餐。无法判断门店或套餐时返回 need_clarification=true。"
            "输出 JSON: {\"offer_id\": number|null, \"confidence\": 0-1, \"need_clarification\": boolean, \"reason\": string}。\n"
            f"今天: {today.isoformat()} 周{['一','二','三','四','五','六','日'][today.weekday()]}\n"
            f"门店: {venue.city} {venue.venue_name}\n买家消息: {message}\noffers: {json.dumps(offers_payload, ensure_ascii=False)}"
        )
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.post(
                    build_openai_url(base_url, "chat/completions"),
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0,
                    },
                )
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"]
            data = self._loads_json_object(content)
            offer_id = int(data.get("offer_id") or 0)
            offer = next((candidate for candidate in offers if candidate.id == offer_id), None)
            if not offer:
                return None
            return PackageReplyMatch(
                offer,
                venue,
                float(data.get("confidence") or 0),
                f"ai:{data.get('reason') or ''}",
                bool(data.get("need_clarification")),
            )
        except Exception as exc:
            logger.warning(f"套餐AI匹配失败，回退启发式: {exc}")
            return None

    async def _get_package_ai_settings(self, account_id: str) -> dict[str, str]:
        account = (
            await self.session.execute(select(XYAccount).where(XYAccount.account_id == account_id))
        ).scalars().first()
        raw = (account.metadata_json or {}).get("ai_reply_settings") if account else {}
        if not raw:
            return {}
        provider_type = normalize_ai_provider_type(
            raw.get("provider_type"),
            raw.get("base_url"),
            raw.get("model_name"),
        )
        if provider_type != "openai_compatible":
            logger.info(f"套餐AI匹配暂仅复用OpenAI兼容配置，当前账号配置为 {provider_type}，回退规则匹配")
            return {}
        return {
            "api_key": clean_ai_text(raw.get("api_key")),
            "base_url": clean_ai_text(raw.get("base_url")),
            "model_name": clean_ai_text(raw.get("model_name")),
        }

    def _ai_offer_passes_hard_constraints(self, message: str, offer: XYPackageOffer) -> bool:
        intent = parse_package_intent(message)
        if intent.day_type and intent.duration_hours:
            offered_duration = offer_duration_for_day(offer.package_name, intent.day_type)
            if offered_duration is not None and offered_duration != intent.duration_hours:
                return False
        if intent.overnight is not None:
            offer_intent = parse_package_intent(offer.package_name)
            if offer_intent.overnight is not None and offer_intent.overnight != intent.overnight:
                return False
        if intent.ticket_kind:
            offer_intent = parse_package_intent(offer.package_name)
            if offer_intent.ticket_kind and offer_intent.ticket_kind != intent.ticket_kind:
                return False
        return True

    async def _infer_venue(self, account_id: str, item_id: str | None, message: str) -> XYPackageVenue | None:
        venues = (await self.session.execute(select(XYPackageVenue).where(XYPackageVenue.enabled.is_(True)))).scalars().all()
        text_parts = [message]
        if item_id:
            item_stmt = (
                select(XYCatalogItem.title)
                .join(XYAccount, XYCatalogItem.account_pk == XYAccount.id)
                .where(XYAccount.account_id == account_id, XYCatalogItem.item_id == item_id)
            )
            title = (await self.session.execute(item_stmt)).scalar_one_or_none()
            if title:
                text_parts.append(str(title))
        return self._match_venue_by_text(" ".join(text_parts), venues)

    async def _infer_venue_from_text(self, text_value: str) -> XYPackageVenue | None:
        if not text_value:
            return None
        venues = (await self.session.execute(select(XYPackageVenue).where(XYPackageVenue.enabled.is_(True)))).scalars().all()
        return self._match_venue_by_text(text_value, venues)

    def _match_venue_by_text(self, text_value: str, venues: list[XYPackageVenue]) -> XYPackageVenue | None:
        normalized = normalize_text(text_value)
        best: tuple[float, XYPackageVenue] | None = None
        for venue in venues:
            score = 0.0
            strong_candidates = [venue.brand, venue.venue_name, *(venue.aliases_json or [])]
            candidates = [venue.city, venue.area, venue.address_note, *strong_candidates]
            for candidate in candidates:
                key = normalize_text(candidate)
                if key and key in normalized:
                    score += 0.25 + min(len(key) * 0.02, 0.25)
            for candidate in strong_candidates:
                key = normalize_text(candidate)
                if len(key) >= 2 and key in normalized:
                    score = max(score, 0.5 + min(len(key) * 0.03, 0.18))
            if best is None or score > best[0]:
                best = (score, venue)
        return best[1] if best and best[0] >= 0.35 else None

    async def _find_or_create_venue(self, item: dict[str, Any], owner_id: int | None) -> XYPackageVenue:
        stmt = select(XYPackageVenue).where(
            XYPackageVenue.city == item["city"],
            XYPackageVenue.brand == item["brand"],
            XYPackageVenue.venue_name == item["venue_name"],
        )
        venue = (await self.session.execute(stmt)).scalars().first()
        if venue:
            return venue
        venue = XYPackageVenue(
            owner_id=owner_id,
            category="洗浴",
            city=item["city"],
            brand=item["brand"],
            venue_name=item["venue_name"],
            aliases_json=item.get("aliases") or [],
            enabled=True,
        )
        self.session.add(venue)
        await self.session.flush()
        return venue

    async def _table_exists(self, table_name: str) -> bool:
        result = await self.session.execute(
            text("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = DATABASE() AND table_name = :table"),
            {"table": table_name},
        )
        return bool(result.scalar())

    @staticmethod
    def _normalize_list(value: Any) -> list[str]:
        if isinstance(value, str):
            items = re.split(r"[\n,，、]+", value)
        elif isinstance(value, list):
            items = value
        else:
            items = []
        return [str(item).strip() for item in items if str(item).strip()]

    @staticmethod
    def _loads_json_object(content: str) -> dict[str, Any]:
        raw = str(content or "").strip()
        fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.S)
        if fenced:
            raw = fenced.group(1)
        elif "{" in raw and "}" in raw:
            raw = raw[raw.find("{"): raw.rfind("}") + 1]
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}

    @staticmethod
    def serialize_venue(venue: XYPackageVenue | None, offer_count: int = 0, binding_count: int = 0) -> dict[str, Any]:
        if not venue:
            return {}
        return {
            "id": venue.id,
            "owner_id": venue.owner_id,
            "category": venue.category,
            "city": venue.city,
            "area": venue.area or "",
            "brand": venue.brand,
            "venue_name": venue.venue_name,
            "address_note": venue.address_note or "",
            "aliases": venue.aliases_json or [],
            "enabled": venue.enabled,
            "offer_count": offer_count,
            "binding_count": binding_count,
        }

    @staticmethod
    def serialize_offer(offer: XYPackageOffer | None) -> dict[str, Any]:
        if not offer:
            return {}
        return {
            "id": offer.id,
            "venue_id": offer.venue_id,
            "package_name": offer.package_name,
            "keywords": offer.keywords_json or [],
            "command_type": offer.command_type,
            "command_value": offer.command_value,
            "source_text": offer.source_text or "",
            "applicability_note": offer.applicability_note or "",
            "protected": offer.protected,
            "enabled": offer.enabled,
            "sort_order": offer.sort_order,
        }
