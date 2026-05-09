from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Route
from app.schemas import RouteCreate, RouteOut

router = APIRouter(prefix="/api/routes", tags=["routes"])


@router.get("/", response_model=list[RouteOut])
def list_routes(db: Session = Depends(get_db)):
    return db.query(Route).all()


@router.post("/", response_model=RouteOut)
def create_route(data: RouteCreate, db: Session = Depends(get_db)):
    route = Route(**data.model_dump())
    db.add(route)
    db.commit()
    db.refresh(route)
    return route


@router.delete("/{route_id}")
def delete_route(route_id: int, db: Session = Depends(get_db)):
    route = db.query(Route).filter(Route.id == route_id).first()
    if not route:
        return {"error": "Route not found"}
    db.delete(route)
    db.commit()
    return {"ok": True}
