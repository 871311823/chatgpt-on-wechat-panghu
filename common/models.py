# encoding:utf-8

from datetime import datetime
from typing import Optional

from sqlalchemy import String, Integer, DateTime, ForeignKey, Numeric, Text, Boolean, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from common.db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wework_user_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    nickname: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    timezone: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Expense(Base):
    __tablename__ = "expenses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    amount: Mapped[Numeric] = mapped_column(Numeric(10, 2))
    currency: Mapped[str] = mapped_column(String(8), default="CNY")
    category: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    merchant: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    note: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    spent_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    source_msg_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    image_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ocr_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped[User] = relationship(backref="expenses")

    __table_args__ = (
        Index("idx_expenses_user_spent", "user_id", "spent_at"),
        Index("idx_expenses_user_cat", "user_id", "category"),
    )


class Todo(Base):
    __tablename__ = "todos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(128))
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    due_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    remind_at: Mapped[Optional[datetime]] = mapped_column(DateTime, index=True)
    repeat_rule: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)  # cron表达式，如 "0 18 * * *"
    reminded: Mapped[bool] = mapped_column(Boolean, default=False)
    remind_count: Mapped[int] = mapped_column(Integer, default=0)  # 提醒次数计数
    last_remind_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)  # 上次提醒时间
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)  # 完成时间
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    user: Mapped[User] = relationship(backref="todos")


