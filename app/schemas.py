from datetime import datetime
from pydantic import BaseModel, Field, HttpUrl, field_validator


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


class FlightSearchRequest(BaseModel):
    query: str = Field(
        min_length=3,
        max_length=500,
        description="自然语言机票查询，例如：9 月 10 日北京到东京，单程经济舱",
    )

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str) -> str:
        return " ".join(value.split())


class FlightOffer(BaseModel):
    airline: str = "未知"
    flight_number: str | None = None
    departure: str
    arrival: str
    departure_time: str | None = None
    arrival_time: str | None = None
    price: float | None = Field(default=None, ge=0)
    currency: str = "CNY"
    cabin_class: str = "经济舱"
    source_title: str
    source_url: HttpUrl
    evidence: str = Field(description="来源页面中支持该价格的简短摘要，不得编造")


class FlightSearchResult(BaseModel):
    summary: str
    offers: list[FlightOffer] = Field(default_factory=list)
    searched_at: datetime = Field(default_factory=datetime.now)
    warning: str = "网页搜索参考价，可能含缓存或起售价；实际价格和余票以预订页面为准。"
