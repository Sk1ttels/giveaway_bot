from sqlalchemy import String, Integer, DateTime, Boolean, ForeignKey, UniqueConstraint, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime
from .db import Base

class Giveaway(Base):
    __tablename__ = "giveaways"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    winners_count: Mapped[int] = mapped_column(Integer, default=1)
    channel_username: Mapped[str] = mapped_column(String(128), default="")  # optional: @channel
    ends_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class Participant(Base):
    __tablename__ = "participants"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    giveaway_id: Mapped[int] = mapped_column(ForeignKey("giveaways.id"))
    user_id: Mapped[int] = mapped_column(Integer)  # telegram user id
    username: Mapped[str] = mapped_column(String(128), default="")
    first_name: Mapped[str] = mapped_column(String(128), default="")
    tickets: Mapped[int] = mapped_column(Integer, default=1)
    invited_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("giveaway_id", "user_id", name="uq_participant"),)

class Referral(Base):
    __tablename__ = "referrals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    giveaway_id: Mapped[int] = mapped_column(ForeignKey("giveaways.id"))
    inviter_id: Mapped[int] = mapped_column(Integer)
    invited_id: Mapped[int] = mapped_column(Integer)

    __table_args__ = (UniqueConstraint("giveaway_id", "invited_id", name="uq_invited_once"),)

class PromoCode(Base):
    __tablename__ = "promocodes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    giveaway_id: Mapped[int] = mapped_column(ForeignKey("giveaways.id"))
    code: Mapped[str] = mapped_column(String(64))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    max_uses: Mapped[int] = mapped_column(Integer, default=1)  # 1 = одноразовий
    uses: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (UniqueConstraint("giveaway_id", "code", name="uq_code"),)

class PromoUse(Base):
    __tablename__ = "promouses"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    giveaway_id: Mapped[int] = mapped_column(Integer)
    user_id: Mapped[int] = mapped_column(Integer)
    code: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("giveaway_id", "user_id", "code", name="uq_user_code"),)
