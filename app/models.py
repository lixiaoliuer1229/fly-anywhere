from datetime import datetime

from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Enum
from sqlalchemy.orm import relationship

from app.database import Base


class Route(Base):
    __tablename__ = "routes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    departure_city = Column(String(50), nullable=False, comment="出发城市")
    arrival_city = Column(String(50), nullable=False, comment="到达城市")
    airline = Column(String(100), default="", comment="航空公司")
    created_at = Column(DateTime, default=datetime.now)

    prices = relationship("Price", back_populates="route", cascade="all, delete-orphan")


class Price(Base):
    __tablename__ = "prices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    route_id = Column(Integer, ForeignKey("routes.id"), nullable=False)
    price = Column(Float, nullable=False, comment="价格(元)")
    cabin_class = Column(String(20), default="economy", comment="舱位: economy/business/first")
    source = Column(String(20), nullable=False, comment="数据来源: api/scraper")
    scraped_at = Column(DateTime, default=datetime.now)

    route = relationship("Route", back_populates="prices")
