from datetime import datetime
from pydantic import BaseModel


class RouteCreate(BaseModel):
    departure_city: str
    arrival_city: str
    airline: str = ""


class RouteOut(BaseModel):
    id: int
    departure_city: str
    arrival_city: str
    airline: str
    created_at: datetime

    class Config:
        from_attributes = True


class PriceCreate(BaseModel):
    price: float
    cabin_class: str = "economy"
    source: str


class PriceOut(BaseModel):
    id: int
    route_id: int
    price: float
    cabin_class: str
    source: str
    scraped_at: datetime

    class Config:
        from_attributes = True
