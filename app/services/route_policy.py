"""Route filters shared by scheduled collection and report delivery."""
from pathlib import Path

CANADIAN_AIRPORTS = frozenset(
    code for line in Path(__file__).with_name("canadian_airports.txt").read_text().splitlines()
    if not line.startswith("#") for code in line.split()
)


def is_canadian_route(route):
    return (route.departure_city.strip().upper() in CANADIAN_AIRPORTS
            or route.arrival_city.strip().upper() in CANADIAN_AIRPORTS)
