"""Daily reference rates; preserve source dates instead of inventing weekend points."""
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy.exc import IntegrityError

from app.models import ExchangeRate

SOURCE_URL = "https://api.frankfurter.dev/v2/rate/CNY/JPY"
MONITORED_QUOTES = ("JPY", "CAD")


class CurrentRateUnavailable(ValueError):
    """The provider has not published a reference rate for today in Shanghai."""


def quote_today():
    return datetime.now(ZoneInfo("Asia/Shanghai")).date()


def fetch_exchange_rate(db, quote="JPY"):
    if quote not in MONITORED_QUOTES:
        raise ValueError("Unsupported currency")
    requested_date = quote_today()
    with httpx.Client(timeout=20) as client:
        response = client.get(f"https://api.frankfurter.dev/v2/rate/CNY/{quote}", params={"date": requested_date.isoformat()})
        if response.status_code == 404:
            raise CurrentRateUnavailable("北京时间当天汇率尚未发布，请稍后重试；历史报价保留原日期。")
        response.raise_for_status()
        data = response.json()
    try:
        rate = Decimal(str(data["rate"]))
        rate_date = date.fromisoformat(data["date"])
        if (data["base"] != "CNY" or data["quote"] != quote
                or not rate.is_finite() or not 0 < rate < 1000000
                or rate_date > requested_date):
            raise ValueError("Invalid reference rate")
    except (KeyError, TypeError, InvalidOperation) as exc:
        raise ValueError("Invalid reference rate response") from exc
    if rate_date != requested_date:
        raise CurrentRateUnavailable("数据源未返回北京时间当天报价；历史报价保留原日期。")
    values = dict(rate=rate, fetched_at=datetime.utcnow())
    row = db.query(ExchangeRate).filter_by(base="CNY", quote=quote, rate_date=rate_date).first()
    if row:
        for key, value in values.items():
            setattr(row, key, value)
    else:
        row = ExchangeRate(base="CNY", quote=quote, rate_date=rate_date, **values)
        db.add(row)
    try:
        db.commit()
    except IntegrityError:
        # Another worker may have saved the same source date concurrently.
        db.rollback()
        row = db.query(ExchangeRate).filter_by(base="CNY", quote=quote, rate_date=rate_date).one()
    db.refresh(row)
    return row


def serialize_rate(row):
    return dict(base=row.base, quote=row.quote, rate=float(row.rate),
                cny_per_100_jpy=float(Decimal(100) / row.rate),
                rate_date=row.rate_date.isoformat(),
                fetched_at=row.fetched_at.isoformat() + "Z", source="Frankfurter",
                source_url=SOURCE_URL)
