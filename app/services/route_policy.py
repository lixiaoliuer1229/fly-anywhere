"""Route filters shared by scheduled collection and report delivery."""
from pathlib import Path

CANADIAN_AIRPORTS = frozenset(
    code for line in Path(__file__).with_name("canadian_airports.txt").read_text().splitlines()
    if not line.startswith("#") for code in line.split()
)
LONDON_DESTINATIONS = frozenset({"LON", "LHR", "LGW", "STN", "LTN", "LCY", "SEN"})


def is_canadian_route(route):
    return (route.departure_city.strip().upper() in CANADIAN_AIRPORTS
            or route.arrival_city.strip().upper() in CANADIAN_AIRPORTS)


def is_excluded_from_monitoring(route):
    return is_canadian_route(route) or route.arrival_city.strip().upper() in LONDON_DESTINATIONS
