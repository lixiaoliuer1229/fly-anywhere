import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import ExchangeRate
from app.services.exchange_rates import fetch_exchange_rate, serialize_rate

router = APIRouter(prefix="/api/exchange-rates", tags=["exchange-rates"])
logger = logging.getLogger(__name__)


@router.get("")
def history(limit: int = Query(90, ge=1, le=1000), db: Session = Depends(get_db)):
    rows = db.query(ExchangeRate).filter_by(base="CNY", quote="JPY").order_by(ExchangeRate.rate_date.desc()).limit(limit).all()
    return {"base": "CNY", "quote": "JPY", "latest": serialize_rate(rows[0]) if rows else None,
            "points": [serialize_rate(row) for row in reversed(rows)],
            "schedule": f"每天 {settings.SCRAPE_DAILY_TIME}（{settings.SCRAPE_TIMEZONE}）",
            "note": "每日参考汇率，非银行实时兑换价；节假日可能沿用最近发布值。"}


@router.post("/fetch")
def fetch(db: Session = Depends(get_db)):
    try:
        return serialize_rate(fetch_exchange_rate(db))
    except Exception:
        db.rollback()
        logger.exception("Exchange rate fetch failed")
        raise HTTPException(502, "汇率更新失败，请稍后重试；已保存的历史数据仍可查看。")
