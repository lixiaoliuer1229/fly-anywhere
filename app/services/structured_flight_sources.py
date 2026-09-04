from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

import httpx

from app.config import settings
from app.schemas import FlightOffer, FlightSearchCriteria, FlightSearchResult


class FlightSourceError(RuntimeError):
    """当前数据源失败，应继续尝试下一个数据源。"""


class StructuredFlightSource(ABC):
    name: str

    @abstractmethod
    async def search(self, criteria: FlightSearchCriteria) -> FlightSearchResult:
        pass


def _ipv4_client(timeout: float = 45) -> httpx.AsyncClient:
    """公网服务器没有可用 IPv6 路由，显式绑定 IPv4 避免连接失败。"""
    transport = httpx.AsyncHTTPTransport(local_address="0.0.0.0")
    return httpx.AsyncClient(timeout=timeout, transport=transport)


def _travel_class(value: str) -> int:
    normalized = value.lower().replace(" ", "_")
    return {"economy": 1, "premium_economy": 2, "business": 3, "first": 4}.get(normalized, 1)


class SerpApiGoogleFlightsSource(StructuredFlightSource):
    name = "serpapi_google_flights"

    async def search(self, criteria: FlightSearchCriteria) -> FlightSearchResult:
        params: dict[str, str | int] = {
            "engine": "google_flights",
            "api_key": settings.SERPAPI_API_KEY,
            "departure_id": criteria.departure_iata,
            "arrival_id": criteria.arrival_iata,
            "outbound_date": criteria.departure_date.isoformat(),
            "type": 1 if criteria.return_date else 2,
            "travel_class": _travel_class(criteria.cabin_class),
            "adults": criteria.adults,
            "currency": criteria.currency,
            "hl": "zh-cn",
            "gl": "cn",
        }
        if criteria.return_date:
            params["return_date"] = criteria.return_date.isoformat()

        async with _ipv4_client() as client:
            response = await client.get("https://serpapi.com/search.json", params=params)
        if response.status_code >= 400:
            raise FlightSourceError(f"SerpApi HTTP {response.status_code}")
        data = response.json()
        if data.get("error"):
            raise FlightSourceError(f"SerpApi: {data['error']}")

        metadata = data.get("search_metadata", {})
        source_url = metadata.get("google_flights_url") or metadata.get("json_endpoint")
        source_url = source_url or "https://www.google.com/travel/flights"
        offers: list[FlightOffer] = []
        for item in (data.get("best_flights", []) + data.get("other_flights", []))[:10]:
            legs = item.get("flights") or []
            if not legs or item.get("price") is None:
                continue
            first, last = legs[0], legs[-1]
            departure = first.get("departure_airport", {})
            arrival = last.get("arrival_airport", {})
            airlines = list(dict.fromkeys(leg.get("airline", "未知") for leg in legs))
            numbers = [leg.get("flight_number") for leg in legs if leg.get("flight_number")]
            offers.append(FlightOffer(
                airline=" / ".join(airlines),
                flight_number=" / ".join(numbers) or None,
                departure=departure.get("id", criteria.departure_iata),
                arrival=arrival.get("id", criteria.arrival_iata),
                departure_time=departure.get("time"),
                arrival_time=arrival.get("time"),
                price=float(item["price"]),
                currency=criteria.currency,
                cabin_class=criteria.cabin_class,
                source_title="Google Flights（SerpApi）",
                source_url=source_url,
                evidence=f"SerpApi Google Flights 返回该行程报价；共 {len(legs)} 个航段。",
            ))
        if not offers:
            raise FlightSourceError("SerpApi 未返回可展示报价")
        return FlightSearchResult(
            summary=f"SerpApi Google Flights 返回 {len(offers)} 条报价。",
            offers=offers,
            searched_at=datetime.now(),
            warning="Google Flights 聚合参考价；实际价格、税费和余票以进入预订页后的结果为准。",
            provider=self.name,
        )


class AmadeusFlightOffersSource(StructuredFlightSource):
    name = "amadeus_flight_offers"

    async def _token(self, client: httpx.AsyncClient) -> str:
        response = await client.post(
            f"{settings.AMADEUS_BASE_URL.rstrip('/')}/v1/security/oauth2/token",
            data={
                "grant_type": "client_credentials",
                "client_id": settings.AMADEUS_API_KEY,
                "client_secret": settings.AMADEUS_API_SECRET,
            },
        )
        if response.status_code >= 400:
            raise FlightSourceError(f"Amadeus 授权失败：HTTP {response.status_code}")
        token = response.json().get("access_token")
        if not token:
            raise FlightSourceError("Amadeus 授权响应缺少 access_token")
        return token

    async def search(self, criteria: FlightSearchCriteria) -> FlightSearchResult:
        async with _ipv4_client() as client:
            token = await self._token(client)
            params: dict[str, str | int] = {
                "originLocationCode": criteria.departure_iata,
                "destinationLocationCode": criteria.arrival_iata,
                "departureDate": criteria.departure_date.isoformat(),
                "adults": criteria.adults,
                "travelClass": criteria.cabin_class.upper(),
                "currencyCode": criteria.currency,
                "max": 10,
            }
            if criteria.return_date:
                params["returnDate"] = criteria.return_date.isoformat()
            response = await client.get(
                f"{settings.AMADEUS_BASE_URL.rstrip('/')}/v2/shopping/flight-offers",
                headers={"Authorization": f"Bearer {token}"},
                params=params,
            )
        if response.status_code >= 400:
            raise FlightSourceError(f"Amadeus Flight Offers HTTP {response.status_code}")
        offers: list[FlightOffer] = []
        for item in response.json().get("data", [])[:10]:
            itineraries = item.get("itineraries") or []
            segments = itineraries[0].get("segments", []) if itineraries else []
            if not segments:
                continue
            first, last = segments[0], segments[-1]
            carriers = item.get("validatingAirlineCodes") or [first.get("carrierCode", "未知")]
            total = item.get("price", {}).get("grandTotal") or item.get("price", {}).get("total")
            if total is None:
                continue
            offers.append(FlightOffer(
                airline=carriers[0],
                flight_number=f"{first.get('carrierCode', '')}{first.get('number', '')}" or None,
                departure=first.get("departure", {}).get("iataCode", criteria.departure_iata),
                arrival=last.get("arrival", {}).get("iataCode", criteria.arrival_iata),
                departure_time=first.get("departure", {}).get("at"),
                arrival_time=last.get("arrival", {}).get("at"),
                price=float(total),
                currency=item.get("price", {}).get("currency", criteria.currency),
                cabin_class=criteria.cabin_class,
                source_title="Amadeus Flight Offers Search",
                source_url="https://www.amadeus.com/en",
                evidence=f"Amadeus Flight Offers Search 返回可售报价；去程共 {len(segments)} 个航段。",
            ))
        if not offers:
            raise FlightSourceError("Amadeus 未返回可展示报价")
        return FlightSearchResult(
            summary=f"Amadeus Flight Offers 返回 {len(offers)} 条报价。",
            offers=offers,
            searched_at=datetime.now(),
            warning="Amadeus 返回搜索时点的报价；下单前仍需再次确认价格与余票。",
            provider=self.name,
        )
