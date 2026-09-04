from datetime import datetime

from sqlalchemy import Boolean, Column, Date, DateTime, Float, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import relationship

from app.database import Base


class Route(Base):
    __tablename__ = "routes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    departure_city = Column(String(50), nullable=False, comment="出发城市")
    arrival_city = Column(String(50), nullable=False, comment="到达城市")
    airline = Column(String(100), default="", comment="航空公司")
    departure_date = Column(Date, nullable=True, comment="去程日期")
    return_date = Column(Date, nullable=True, comment="返程日期")
    trip_type = Column(String(20), nullable=False, default="one_way")
    adults = Column(Integer, nullable=False, default=1)
    cabin_class = Column(String(20), nullable=False, default="economy")
    target_price = Column(Numeric(12, 2), nullable=True)
    currency = Column(String(3), nullable=False, default="CNY")
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    prices = relationship("Price", back_populates="route", cascade="all, delete-orphan")
    search_runs = relationship("SearchRun", back_populates="route", cascade="all, delete-orphan")
    notifications = relationship("NotificationDelivery", back_populates="route", cascade="all, delete-orphan")


class Price(Base):
    __tablename__ = "prices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    route_id = Column(Integer, ForeignKey("routes.id"), nullable=False)
    price = Column(Float, nullable=False, comment="价格(元)")
    cabin_class = Column(String(20), default="economy", comment="舱位: economy/business/first")
    source = Column(String(20), nullable=False, comment="数据来源: api/scraper")
    scraped_at = Column(DateTime, default=datetime.now)

    route = relationship("Route", back_populates="prices")


class SearchRun(Base):
    __tablename__ = "search_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    route_id = Column(Integer, ForeignKey("routes.id", ondelete="CASCADE"), nullable=True, index=True)
    original_query = Column(Text, nullable=False)
    status = Column(String(20), nullable=False, default="running", index=True)
    summary = Column(Text, nullable=True)
    warning = Column(Text, nullable=True)
    provider = Column(String(30), nullable=False, default="tavily")
    model = Column(String(100), nullable=True)
    started_at = Column(DateTime, nullable=False, default=datetime.now)
    completed_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)

    route = relationship("Route", back_populates="search_runs")
    offers = relationship("FlightOffer", back_populates="search_run", cascade="all, delete-orphan")
    notifications = relationship("NotificationDelivery", back_populates="search_run")


class FlightOffer(Base):
    __tablename__ = "flight_offers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    search_run_id = Column(Integer, ForeignKey("search_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    airline = Column(String(100), nullable=False, default="未知")
    flight_number = Column(String(120), nullable=True)
    departure = Column(String(100), nullable=False)
    arrival = Column(String(100), nullable=False)
    departure_time = Column(String(80), nullable=True)
    arrival_time = Column(String(80), nullable=True)
    price = Column(Numeric(12, 2), nullable=True)
    currency = Column(String(3), nullable=False, default="CNY")
    cabin_class = Column(String(30), nullable=False, default="economy")
    source_title = Column(String(255), nullable=False)
    source_url = Column(Text, nullable=False)
    evidence = Column(Text, nullable=False)
    is_starting_price = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=datetime.now)

    search_run = relationship("SearchRun", back_populates="offers")


class NotificationDelivery(Base):
    __tablename__ = "notification_deliveries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    route_id = Column(Integer, ForeignKey("routes.id", ondelete="CASCADE"), nullable=False, index=True)
    search_run_id = Column(Integer, ForeignKey("search_runs.id", ondelete="SET NULL"), nullable=True, index=True)
    channel_type = Column(String(30), nullable=False, default="wecom_webhook")
    status = Column(String(20), nullable=False, default="pending", index=True)
    message_content = Column(Text, nullable=False)
    idempotency_key = Column(String(120), nullable=False, unique=True)
    sent_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.now)

    route = relationship("Route", back_populates="notifications")
    search_run = relationship("SearchRun", back_populates="notifications")
