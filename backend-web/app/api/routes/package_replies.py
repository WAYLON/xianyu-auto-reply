from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.api import deps
from common.models.user import User
from common.schemas.common import ApiResponse
from common.services.package_reply_service import BUYER_TEST_MESSAGES, PackageReplyService, parse_package_material
from common.utils.auth_scope import resolve_owner_scope

router = APIRouter(prefix="/package-replies", tags=["套餐回复"])


class VenuePayload(BaseModel):
    id: int | None = None
    category: str = "洗浴"
    city: str
    area: str = ""
    brand: str
    venue_name: str
    address_note: str = ""
    aliases: list[str] = Field(default_factory=list)
    enabled: bool = True


class OfferPayload(BaseModel):
    id: int | None = None
    package_name: str
    keywords: list[str] = Field(default_factory=list)
    command_type: str = "numeric"
    command_value: str
    source_text: str = ""
    applicability_note: str = ""
    protected: bool = True
    enabled: bool = True
    sort_order: int = 100


class MaterialImportPayload(BaseModel):
    venue_id: int | None = None
    raw_text: str


class BindItemPayload(BaseModel):
    account_id: str
    item_id: str
    venue_id: int
    protected: bool = True


class TestMatchPayload(BaseModel):
    account_id: str
    item_id: str | None = None
    message: str


async def get_package_reply_service(session=Depends(deps.get_db_session)) -> PackageReplyService:
    return PackageReplyService(session)


@router.get("/venues")
async def list_venues(
    current_user: User = Depends(deps.get_current_active_user),
    service: PackageReplyService = Depends(get_package_reply_service),
) -> ApiResponse:
    owner_id, _ = resolve_owner_scope(current_user)
    return ApiResponse(success=True, message="获取成功", data=await service.list_venues(owner_id))


@router.post("/venues")
async def save_venue(
    payload: VenuePayload,
    current_user: User = Depends(deps.get_current_active_user),
    service: PackageReplyService = Depends(get_package_reply_service),
) -> ApiResponse:
    owner_id, _ = resolve_owner_scope(current_user)
    venue = await service.upsert_venue(payload.model_dump(), owner_id)
    return ApiResponse(success=True, message="保存成功", data=service.serialize_venue(venue))


@router.get("/venues/{venue_id}/offers")
async def list_offers(
    venue_id: int,
    current_user: User = Depends(deps.get_current_active_user),
    service: PackageReplyService = Depends(get_package_reply_service),
) -> ApiResponse:
    _ = current_user
    return ApiResponse(success=True, message="获取成功", data=await service.get_offers(venue_id))


@router.post("/venues/{venue_id}/offers")
async def save_offer(
    venue_id: int,
    payload: OfferPayload,
    current_user: User = Depends(deps.get_current_active_user),
    service: PackageReplyService = Depends(get_package_reply_service),
) -> ApiResponse:
    _ = current_user
    offer = await service.upsert_offer(venue_id, payload.model_dump())
    return ApiResponse(success=True, message="保存成功", data=service.serialize_offer(offer))


@router.delete("/offers/{offer_id}")
async def delete_offer(
    offer_id: int,
    current_user: User = Depends(deps.get_current_active_user),
    service: PackageReplyService = Depends(get_package_reply_service),
) -> ApiResponse:
    _ = current_user
    ok = await service.delete_offer(offer_id)
    return ApiResponse(success=ok, message="删除成功" if ok else "未找到套餐")


@router.post("/materials/parse")
async def parse_material(payload: MaterialImportPayload, current_user: User = Depends(deps.get_current_active_user)) -> ApiResponse:
    _ = current_user
    return ApiResponse(success=True, message="解析成功", data=parse_package_material(payload.raw_text))


@router.post("/materials/import")
async def import_material(
    payload: MaterialImportPayload,
    current_user: User = Depends(deps.get_current_active_user),
    service: PackageReplyService = Depends(get_package_reply_service),
) -> ApiResponse:
    owner_id, _ = resolve_owner_scope(current_user)
    data = await service.import_material(owner_id, payload.venue_id, payload.raw_text)
    return ApiResponse(success=True, message="导入完成", data=data)


@router.post("/bindings")
async def bind_item(
    payload: BindItemPayload,
    current_user: User = Depends(deps.get_current_active_user),
    service: PackageReplyService = Depends(get_package_reply_service),
) -> ApiResponse:
    owner_id, _ = resolve_owner_scope(current_user)
    binding = await service.bind_item(owner_id, payload.account_id, payload.item_id, payload.venue_id, payload.protected)
    return ApiResponse(success=True, message="绑定成功", data={"id": binding.id})


@router.post("/seed-known")
async def seed_known_commands(
    include_protected_bindings: bool = Query(default=True),
    current_user: User = Depends(deps.get_current_admin_user),
    service: PackageReplyService = Depends(get_package_reply_service),
) -> ApiResponse:
    owner_id, _ = resolve_owner_scope(current_user)
    seeded = await service.seed_known_numeric_commands(owner_id)
    binding_count = await service.seed_bindings_from_protected_items(owner_id) if include_protected_bindings else 0
    return ApiResponse(success=True, message="已导入已知数字口令", data={**seeded, "bindings_created": binding_count})


@router.post("/test-match")
async def test_match(
    payload: TestMatchPayload,
    current_user: User = Depends(deps.get_current_active_user),
    service: PackageReplyService = Depends(get_package_reply_service),
) -> ApiResponse:
    _ = current_user
    return ApiResponse(success=True, message="匹配完成", data=await service.test_match(payload.account_id, payload.item_id, payload.message))


@router.get("/test-messages")
async def test_messages(current_user: User = Depends(deps.get_current_active_user)) -> ApiResponse:
    _ = current_user
    return ApiResponse(success=True, message="获取成功", data=BUYER_TEST_MESSAGES)
