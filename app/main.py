from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from starlette.requests import Request

from app.database import engine
from app.routers import ai_search, flights, prices
from app.services.scheduler import start_scheduler

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 数据库结构由 Alembic 管理，避免 create_all 掩盖缺失迁移。
    start_scheduler()
    yield
    # Shutdown


app = FastAPI(title="AI 机票搜索与价格监控", lifespan=lifespan)

app.include_router(flights.router)
app.include_router(prices.router)
app.include_router(ai_search.router)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/healthz", include_in_schema=False)
def healthz():
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return {"status": "ok"}
