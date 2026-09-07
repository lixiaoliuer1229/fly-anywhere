from datetime import date

from app.database import SessionLocal
from app.models import Route


MONITORED_ROUTES = (
    ("CTU", "YVR", date(2027, 2, 5), date(2027, 2, 11), 6008),
    ("CTU", "OSL", date(2027, 2, 4), date(2027, 2, 11), 7292),
    ("CTU", "LHR", date(2027, 2, 5), date(2027, 2, 11), 7400),
)


def configure() -> None:
    db = SessionLocal()
    try:
        db.query(Route).update({Route.enabled: False}, synchronize_session=False)
        for departure, arrival, departure_date, return_date, target_price in MONITORED_ROUTES:
            route = db.query(Route).filter(
                Route.departure_city == departure,
                Route.arrival_city == arrival,
                Route.departure_date == departure_date,
                Route.return_date == return_date,
            ).first()
            if route is None:
                route = Route(
                    departure_city=departure,
                    arrival_city=arrival,
                    departure_date=departure_date,
                    return_date=return_date,
                )
                db.add(route)
            route.trip_type = "round_trip"
            route.adults = 1
            route.cabin_class = "economy"
            route.currency = "CNY"
            route.target_price = target_price
            route.enabled = True
        db.commit()
        enabled = db.query(Route).filter(Route.enabled.is_(True)).all()
        for route in enabled:
            print(
                f"{route.departure_city}->{route.arrival_city} "
                f"{route.departure_date}~{route.return_date} target={route.target_price}"
            )
    finally:
        db.close()


if __name__ == "__main__":
    configure()
