"""Daily reference rates; preserve source dates instead of inventing weekend points."""
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

import httpx
from sqlalchemy.exc import IntegrityError

from app.models import ExchangeRate

SOURCE_URL = "https://api.frankfurter.dev/v2/rate/CNY/JPY"


def fetch_exchange_rate(db):
    with httpx.Client(timeout=20) as client:
        response = client.get(SOURCE_URL)
        response.raise_for_status()
        data = response.json()
    try:
        rate = Decimal(str(data["rate"]))
        rate_date = date.fromisoformat(data["date"])
        if (data["base"] != "CNY" or data["quote"] != "JPY"
                or not rate.is_finite() or not 0 < rate < 1000000
                or rate_date > datetime.now(timezone.utc).date()):
            raise ValueError("Invalid reference rate")
    except (KeyError, TypeError, InvalidOperation) as exc:
        raise ValueError("Invalid reference rate response") from exc
    values = dict(rate=rate, fetched_at=datetime.utcnow())
    row = db.query(ExchangeRate).filter_by(base="CNY", quote="JPY", rate_date=rate_date).first()
    if row:
        for key, value in values.items():
            setattr(row, key, value)
    else:
        row = ExchangeRate(base="CNY", quote="JPY", rate_date=rate_date, **values)
        db.add(row)
    try:
        db.commit()
    except IntegrityError:
        # Another worker may have saved the same source date concurrently.
        db.rollback()
        row = db.query(ExchangeRate).filter_by(base="CNY", quote="JPY", rate_date=rate_date).one()
    db.refresh(row)
    return row


def serialize_rate(row):
    return dict(base=row.base, quote=row.quote, rate=float(row.rate),
                cny_per_100_jpy=float(Decimal(100) / row.rate),
                rate_date=row.rate_date.isoformat(),
                fetched_at=row.fetched_at.isoformat() + "Z", source="Frankfurter",
                source_url=SOURCE_URL)
