"""套餐团口令解析、配置与自动回复匹配服务。"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any

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
from common.services.ai_provider_service import build_openai_url


NUMERIC_COMMAND_CONTEXT = re.compile(r"(美团搜索|搜索口令|数字口令|团口令|口令)\D{0,12}(\d{6})")
FULL_COMMAND_CONTEXT = re.compile(r"【团口令】\s*(.+?)(?=\n\s*\n|\n\s*🎁|$)", re.S)
TITLE_LINE_PATTERN = re.compile(r"^\s*(?:🎁)?【(.{4,220})】\s*$")
PRICE_OR_LINK_LINE = re.compile(r"(门市价|现价|下单链接|http://|https://|dpurl\.cn)", re.I)
MATERIAL_NOISE_LINE = re.compile(r"^[｜|\\-—_\\s]+$")
MATERIAL_FIELD_TITLES = {"下单链接", "团口令", "搜索口令", "美团搜索", "数字口令"}


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


def normalize_text(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()


def contains_match_token(text_value: str, token: str) -> bool:
    normalized = normalize_text(text_value)
    token_value = normalize_text(token)
    if token_value in {"8h", "8小时"}:
        return bool(re.search(r"(?<!\d)8(?:h|小时)", normalized))
    if token_value in {"16h", "16小时"}:
        return bool(re.search(r"(?<!\d)16(?:h|小时)", normalized))
    if token_value in {"18h", "18小时"}:
        return bool(re.search(r"(?<!\d)18(?:h|小时)", normalized))
    return bool(token_value and token_value in normalized)


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
        "价格实时浮动，确认套餐和日期后再拍/购买。"
    )


def build_package_clarification_text(venue: XYPackageVenue) -> str:
    return (
        f"{venue.city}{venue.venue_name}这边有多个套餐，我先帮您确认一下：\n"
        "您要的是工作日/节假日、单人/双人、18H/过夜，还是儿童/学生票？\n\n"
        "先打开美团搜索 86886 领红包，确认套餐后我发对应口令。\n"
        "会比自己在美团直接买更便宜。\n"
        "价格实时浮动，确认套餐和日期后再拍/购买。"
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
        offers = (await self.session.execute(
            select(XYPackageOffer).where(
                XYPackageOffer.venue_id == venue.id,
                XYPackageOffer.enabled.is_(True),
            ).order_by(XYPackageOffer.sort_order, XYPackageOffer.id)
        )).scalars().all()
        if not offers:
            return PackageReplyMatch(None, venue, 0, "no_offer", True)

        heuristic = self._match_offer_heuristic(message, venue, offers)
        if heuristic.confidence >= 0.72 or len(offers) == 1:
            return heuristic

        ai_match = await self._match_offer_with_ai(message, venue, offers)
        if ai_match and ai_match.confidence >= 0.7:
            return ai_match
        return PackageReplyMatch(None, venue, heuristic.confidence, "need_clarification", True)

    async def build_reply_for_message(self, account_id: str, item_id: str | None, message: str) -> str | None:
        match = await self.match_for_message(account_id, item_id, message)
        if match.offer and match.venue and not match.need_clarification:
            return build_package_reply_text(match.offer, match.venue)
        if match.venue and match.need_clarification:
            return build_package_clarification_text(match.venue)
        return None

    async def test_match(self, account_id: str, item_id: str | None, message: str) -> dict[str, Any]:
        match = await self.match_for_message(account_id, item_id, message)
        return {
            "matched": bool(match.offer),
            "need_clarification": match.need_clarification,
            "confidence": match.confidence,
            "reason": match.reason,
            "venue": self.serialize_venue(match.venue) if match.venue else None,
            "offer": self.serialize_offer(match.offer) if match.offer else None,
            "reply": (
                build_package_reply_text(match.offer, match.venue)
                if match.offer and match.venue
                else build_package_clarification_text(match.venue)
                if match.venue and match.need_clarification
                else ""
            ),
        }

    def _match_offer_heuristic(self, message: str, venue: XYPackageVenue, offers: list[XYPackageOffer]) -> PackageReplyMatch:
        normalized = normalize_text(message)
        generic_buy = any(word in normalized for word in ["怎么买", "能用吗", "可以用吗", "怎么拍", "咨询"])
        best_offer: XYPackageOffer | None = None
        best_score = 0.0
        for offer in offers:
            score = 0.0
            matched_strong_tokens = 0
            keywords = list(offer.keywords_json or []) + extract_keywords(offer.package_name)
            for keyword in keywords:
                key = normalize_text(keyword)
                if key and key in normalized:
                    score += min(0.28, 0.08 + len(key) * 0.018)
            package_text = normalize_text(offer.package_name)
            for token in [
                "单人", "双人", "成人", "儿童", "学生", "工作日", "节假日", "周末",
                "周一", "周二", "周三", "周四", "周五", "周六", "周日",
                "夜", "夜间", "过夜", "过夜费", "午夜", "服务费", "早餐", "自助",
                "8h", "8小时", "16h", "16小时", "18h", "18小时",
                "海鲜", "榴莲", "搓澡", "护理", "施丹兰", "消费券", "免门票",
            ]:
                if contains_match_token(message, token) and contains_match_token(offer.package_name, token):
                    score += 0.16
                    matched_strong_tokens += 1
            if matched_strong_tokens >= 3:
                score = max(score, 0.76)
            conflict_pairs = [
                ("工作日", "节假日"),
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
                if (
                    contains_match_token(message, conflicting)
                    and not contains_match_token(offer.package_name, conflicting)
                    and contains_match_token(offer.package_name, wanted)
                ):
                    score -= 0.32
            for required_token in ["学生", "双人", "单人", "成人", "儿童"]:
                if contains_match_token(message, required_token) and not contains_match_token(offer.package_name, required_token):
                    score -= 0.45
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
        if not best_offer and generic_buy and offers:
            return PackageReplyMatch(offers[0], venue, 0.76, "generic_single_or_first")
        if best_offer:
            return PackageReplyMatch(best_offer, venue, min(best_score, 0.98), "heuristic")
        return PackageReplyMatch(None, venue, 0, "no_offer_match", True)

    async def _match_offer_with_ai(self, message: str, venue: XYPackageVenue, offers: list[XYPackageOffer]) -> PackageReplyMatch | None:
        api_key = os.getenv("PACKAGE_REPLY_AI_API_KEY") or os.getenv("SILICONFLOW_API_KEY")
        if not api_key:
            return None
        base_url = os.getenv("PACKAGE_REPLY_AI_BASE_URL", "https://api.siliconflow.com/v1")
        model = os.getenv("PACKAGE_REPLY_AI_MODEL", "zai-org/GLM-5.2")
        offers_payload = [
            {"id": offer.id, "package_name": offer.package_name, "keywords": offer.keywords_json or []}
            for offer in offers
        ]
        prompt = (
            "你是闲鱼客服套餐匹配器。只从 offers 里选择一个最匹配的 offer_id。"
            "不要编造套餐、价格、链接。无法确定时返回 need_clarification=true。"
            "输出 JSON: {\"offer_id\": number|null, \"confidence\": 0-1, \"need_clarification\": boolean, \"reason\": string}。\n"
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

    def _match_venue_by_text(self, text_value: str, venues: list[XYPackageVenue]) -> XYPackageVenue | None:
        normalized = normalize_text(text_value)
        best: tuple[float, XYPackageVenue] | None = None
        for venue in venues:
            score = 0.0
            candidates = [venue.city, venue.area, venue.brand, venue.venue_name, venue.address_note, *(venue.aliases_json or [])]
            for candidate in candidates:
                key = normalize_text(candidate)
                if key and key in normalized:
                    score += 0.25 + min(len(key) * 0.02, 0.25)
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
