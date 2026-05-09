from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from app.database import engine, Base
from app.routers import flights, prices
from app.services.scheduler import start_scheduler

templates = Jinja2Templates(directory="app/templates")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: create tables and start scheduler
    Base.metadata.create_all(bind=engine)
    start_scheduler()
    yield
    # Shutdown


app = FastAPI(title="机票价格监控", lifespan=lifespan)

app.include_router(flights.router)
app.include_router(prices.router)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})
