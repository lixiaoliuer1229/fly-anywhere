from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from starlette.requests import Request

from app.database import engine
from app.routers import ai_search, flights, prices, auth, exchange_rates
from app.routers.auth import current_user
from app.services.scheduler import start_scheduler

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 数据库结构由 Alembic 管理，避免 create_all 掩盖缺失迁移。
    start_scheduler()
    yield
    # Shutdown


app = FastAPI(title="AI 机票搜索与价格监控", lifespan=lifespan)

app.include_router(auth.router)
app.include_router(exchange_rates.router, dependencies=[Depends(current_user)])
app.include_router(flights.router, dependencies=[Depends(current_user)])
app.include_router(prices.router, dependencies=[Depends(current_user)])
app.include_router(ai_search.router, dependencies=[Depends(current_user)])


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, user=Depends(current_user)):
    return templates.TemplateResponse("index.html", {"request": request, "user": user}, headers={"Cache-Control": "no-store"})


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, user=Depends(current_user)):
    return templates.TemplateResponse("dashboard.html", {"request": request, "user": user}, headers={"Cache-Control": "no-store"})


@app.get("/healthz", include_in_schema=False)
def healthz():
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return {"status": "ok"}


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    if exc.status_code == 401 and request.url.path in {"/", "/dashboard"}:
        return RedirectResponse("/login", status_code=303)
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})
