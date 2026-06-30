"""套餐团口令回复模型"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Index, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from common.db.base_class import Base


class XYPackageVenue(Base):
    """可配置套餐回复的门店/品牌。"""

    __tablename__ = "xy_package_venues"
    __table_args__ = (
        Index("idx_pkg_venue_owner_city", "owner_id", "city", "enabled"),
        Index("idx_pkg_venue_brand", "brand", "venue_name"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    owner_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    category: Mapped[str] = mapped_column(String(40), nullable=False, default="洗浴")
    city: Mapped[str] = mapped_column(String(80), nullable=False)
    area: Mapped[str | None] = mapped_column(String(120))
    brand: Mapped[str] = mapped_column(String(120), nullable=False)
    venue_name: Mapped[str] = mapped_column(String(160), nullable=False)
    address_note: Mapped[str | None] = mapped_column(String(255))
    aliases_json: Mapped[list | None] = mapped_column("aliases", JSON)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class XYPackageOffer(Base):
    """门店下的具体套餐与团口令。"""

    __tablename__ = "xy_package_offers"
    __table_args__ = (
        Index("idx_pkg_offer_venue_enabled", "venue_id", "enabled", "sort_order"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    venue_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    package_name: Mapped[str] = mapped_column(String(255), nullable=False)
    keywords_json: Mapped[list | None] = mapped_column("keywords", JSON)
    command_type: Mapped[str] = mapped_column(String(20), nullable=False, default="numeric")
    command_value: Mapped[str] = mapped_column(Text, nullable=False)
    source_text: Mapped[str | None] = mapped_column(Text)
    applicability_note: Mapped[str | None] = mapped_column(String(255))
    protected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class XYItemPackageBinding(Base):
    """商品到套餐门店的绑定。"""

    __tablename__ = "xy_item_package_bindings"
    __table_args__ = (
        Index("idx_pkg_bind_account_item", "account_id", "item_id", unique=True),
        Index("idx_pkg_bind_venue", "venue_id", "enabled"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    owner_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    account_id: Mapped[str] = mapped_column(String(80), nullable=False)
    item_id: Mapped[str] = mapped_column(String(64), nullable=False)
    venue_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    protected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notes: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class XYPackageImportCandidate(Base):
    """素材导入后无法高置信落库的候选项。"""

    __tablename__ = "xy_package_import_candidates"
    __table_args__ = (
        Index("idx_pkg_candidate_owner_status", "owner_id", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    owner_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    parsed_json: Mapped[dict | None] = mapped_column("parsed", JSON)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    reason: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
