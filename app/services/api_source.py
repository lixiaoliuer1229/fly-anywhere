from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class FlightPrice:
    price: float
    airline: str
    cabin_class: str = "economy"
    source: str = "api"


class DataSource(ABC):
    @abstractmethod
    async def fetch_prices(self, departure: str, arrival: str, date: str = "") -> list[FlightPrice]:
        """Fetch flight prices for a route."""
        pass


class AviationStackSource(DataSource):
    """AviationStack API data source."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "http://api.aviationstack.com/v1"

    async def fetch_prices(self, departure: str, arrival: str, date: str = "") -> list[FlightPrice]:
        import httpx

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.base_url}/flights",
                params={
                    "access_key": self.api_key,
                    "dep_iata": departure,
                    "arr_iata": arrival,
                },
                timeout=30,
            )
            data = resp.json()

        results = []
        for flight in data.get("data", []):
            price = flight.get("price", 0)
            if price:
                results.append(FlightPrice(
                    price=float(price),
                    airline=flight.get("airline", {}).get("name", "Unknown"),
                    source="aviationstack",
                ))
        return results


class AmadeusSource(DataSource):
    """Amadeus API data source."""

    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = "https://api.amadeus.com/v2"
        self._token = ""

    async def _get_token(self):
        import httpx

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.amadeus.com/v1/security/oauth2/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.api_key,
                    "client_secret": self.api_secret,
                },
            )
            self._token = resp.json()["access_token"]

    async def fetch_prices(self, departure: str, arrival: str, date: str = "") -> list[FlightPrice]:
        import httpx

        if not self._token:
            await self._get_token()

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.base_url}/shopping/flight-offers",
                headers={"Authorization": f"Bearer {self._token}"},
                params={
                    "originLocationCode": departure,
                    "destinationLocationCode": arrival,
                    "departureDate": date,
                    "adults": 1,
                    "max": 10,
                },
                timeout=30,
            )
            data = resp.json()

        results = []
        for offer in data.get("data", []):
            price = float(offer["price"]["total"])
            airline = offer["validatingAirlineCodes"][0] if offer.get("validatingAirlineCodes") else "Unknown"
            results.append(FlightPrice(
                price=price,
                airline=airline,
                source="amadeus",
            ))
        return results
