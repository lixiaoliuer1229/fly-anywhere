"""Route filters shared by scheduled collection and report delivery."""

CANADIAN_AIRPORTS = {
    "YVR", "YYZ", "YUL", "YOW", "YEG", "YYC", "YHZ", "YQB",
    "YWG", "YXE", "YQR", "YYJ", "YKF", "YHM", "YTZ",
}


def is_canadian_route(route):
    return (route.departure_city.upper() in CANADIAN_AIRPORTS
            or route.arrival_city.upper() in CANADIAN_AIRPORTS)
