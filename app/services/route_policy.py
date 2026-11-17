"""Route filters shared by scheduled collection and report delivery."""
from pathlib import Path

CANADIAN_AIRPORTS = frozenset(
    code for line in Path(__file__).with_name("canadian_airports.txt").read_text().splitlines()
    if not line.startswith("#") for code in line.split()
)
LONDON_DESTINATIONS = frozenset({"LON", "LHR", "LGW", "STN", "LTN", "LCY", "SEN"})
CHENGDU_AIRPORTS = frozenset({"CTU", "TFU"})


def is_canadian_route(route):
    return (route.departure_city.strip().upper() in CANADIAN_AIRPORTS
            or route.arrival_city.strip().upper() in CANADIAN_AIRPORTS)


def is_excluded_from_monitoring(route):
    departure = route.departure_city.strip().upper()
    arrival = route.arrival_city.strip().upper()
    return (
        is_canadian_route(route)
        or arrival in LONDON_DESTINATIONS
        or (departure in CHENGDU_AIRPORTS and arrival == "OSL")
    )
