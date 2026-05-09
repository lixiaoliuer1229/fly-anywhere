"""
航班搜索脚本 - 搜索从中国城市到意大利城市的往返航班
使用 Amadeus Flight Offers Search API

用法:
    python search_flights.py
    python search_flights.py --api-key YOUR_KEY --api-secret YOUR_SECRET
"""

import asyncio
import argparse
import json
from dataclasses import dataclass, field
from datetime import datetime

import httpx


# 出发城市
DEPARTURE_CITIES = {
    "CTU": "成都",
    "CAN": "广州",
    "HKG": "香港",
    "PVG": "上海",
    "KHN": "南昌",
}

# 意大利目的地城市
ITALY_CITIES = {
    "FCO": "罗马",
    "MXP": "米兰",
    "VCE": "威尼斯",
    "FLR": "佛罗伦萨",
    "NAP": "那不勒斯",
    "BLQ": "博洛尼亚",
    "TRN": "都灵",
    "PMO": "巴勒莫",
    "CTA": "卡塔尼亚",
    "BRI": "巴里",
    "PSA": "比萨",
    "CAG": "卡利亚里",
}

# 去程日期 (9/24晚出发 or 9/25出发)
OUTBOUND_DATES = ["2026-09-24", "2026-09-25"]
# 回程日期 (10/7 or 10/8)
RETURN_DATES = ["2026-10-07", "2026-10-08"]


@dataclass
class FlightOffer:
    origin: str
    origin_name: str
    destination: str
    destination_name: str
    outbound_date: str
    return_date: str
    price_total: float
    currency: str
    airline: str
    outbound_segments: list = field(default_factory=list)
    return_segments: list = field(default_factory=list)
    duration_outbound: str = ""
    duration_return: str = ""
    stops_outbound: int = 0
    stops_return: int = 0


class AmadeusClient:
    BASE_URL = "https://api.amadeus.com"

    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self._token = ""
        self._client = httpx.AsyncClient(timeout=30)

    async def authenticate(self):
        resp = await self._client.post(
            f"{self.BASE_URL}/v1/security/oauth2/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self.api_key,
                "client_secret": self.api_secret,
            },
        )
        resp.raise_for_status()
        self._token = resp.json()["access_token"]
        print("Amadeus API 认证成功")

    async def search_flights(
        self, origin: str, destination: str, outbound_date: str, return_date: str
    ) -> list[FlightOffer]:
        resp = await self._client.get(
            f"{self.BASE_URL}/v2/shopping/flight-offers",
            headers={"Authorization": f"Bearer {self._token}"},
            params={
                "originLocationCode": origin,
                "destinationLocationCode": destination,
                "departureDate": outbound_date,
                "returnDate": return_date,
                "adults": 1,
                "max": 5,
                "currencyCode": "CNY",
            },
        )

        if resp.status_code == 429:
            print("  API 限流，等待后重试...")
            await asyncio.sleep(2)
            return await self.search_flights(origin, destination, outbound_date, return_date)

        if resp.status_code != 200:
            print(f"  查询失败 ({resp.status_code}): {resp.text[:200]}")
            return []

        data = resp.json()
        offers = []

        for item in data.get("data", []):
            price = float(item["price"]["total"])
            currency = item["price"].get("currency", "CNY")
            airline_codes = item.get("validatingAirlineCodes", [])
            airline = airline_codes[0] if airline_codes else "Unknown"

            itineraries = item.get("itineraries", [])
            outbound_segs = []
            return_segs = []
            duration_out = ""
            duration_ret = ""
            stops_out = 0
            stops_ret = 0

            if len(itineraries) >= 1:
                out = itineraries[0]
                duration_out = out.get("duration", "")
                segments = out.get("segments", [])
                stops_out = max(0, len(segments) - 1)
                for seg in segments:
                    dep = seg.get("departure", {})
                    arr = seg.get("arrival", {})
                    outbound_segs.append({
                        "from": dep.get("iataCode", ""),
                        "to": arr.get("iataCode", ""),
                        "departure": dep.get("at", ""),
                        "arrival": arr.get("at", ""),
                        "carrier": seg.get("carrierCode", ""),
                        "flight_no": seg.get("number", ""),
                    })

            if len(itineraries) >= 2:
                ret = itineraries[1]
                duration_ret = ret.get("duration", "")
                segments = ret.get("segments", [])
                stops_ret = max(0, len(segments) - 1)
                for seg in segments:
                    dep = seg.get("departure", {})
                    arr = seg.get("arrival", {})
                    return_segs.append({
                        "from": dep.get("iataCode", ""),
                        "to": arr.get("iataCode", ""),
                        "departure": dep.get("at", ""),
                        "arrival": arr.get("at", ""),
                        "carrier": seg.get("carrierCode", ""),
                        "flight_no": seg.get("number", ""),
                    })

            offers.append(FlightOffer(
                origin=origin,
                origin_name=DEPARTURE_CITIES.get(origin, origin),
                destination=destination,
                destination_name=ITALY_CITIES.get(destination, destination),
                outbound_date=outbound_date,
                return_date=return_date,
                price_total=price,
                currency=currency,
                airline=airline,
                outbound_segments=outbound_segs,
                return_segments=return_segs,
                duration_outbound=duration_out,
                duration_return=duration_ret,
                stops_outbound=stops_out,
                stops_return=stops_ret,
            ))

        return offers

    async def close(self):
        await self._client.aclose()


def format_duration(iso_duration: str) -> str:
    """Convert PT12H30M to '12h30m'"""
    if not iso_duration:
        return ""
    d = iso_duration.replace("PT", "")
    d = d.lower().replace("h", "h ").replace("m", "m")
    return d.strip()


def format_time(iso_str: str) -> str:
    """Extract time portion from ISO datetime"""
    if not iso_str:
        return ""
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.strftime("%m/%d %H:%M")
    except:
        return iso_str[:16]


def print_results(all_offers: list[FlightOffer], top_n: int = 30):
    if not all_offers:
        print("\n未找到任何航班结果。")
        return

    all_offers.sort(key=lambda x: x.price_total)

    print(f"\n{'='*100}")
    print(f"  找到 {len(all_offers)} 个航班组合，按价格排序（显示前 {min(top_n, len(all_offers))} 个）")
    print(f"{'='*100}")

    for i, offer in enumerate(all_offers[:top_n], 1):
        print(f"\n{'─'*100}")
        print(f"  #{i}  {offer.origin_name}({offer.origin}) → {offer.destination_name}({offer.destination})")
        print(f"  💰 价格: {offer.currency} {offer.price_total:,.0f}")
        print(f"  ✈️  航司: {offer.airline}")
        print()
        print(f"  去程: {offer.outbound_date}  "
              f"时长: {format_duration(offer.duration_outbound)}  "
              f"中转: {offer.stops_outbound}次")
        for seg in offer.outbound_segments:
            print(f"    {seg['carrier']}{seg['flight_no']}  "
                  f"{seg['from']} → {seg['to']}  "
                  f"{format_time(seg['departure'])} → {format_time(seg['arrival'])}")

        print(f"  回程: {offer.return_date}  "
              f"时长: {format_duration(offer.duration_return)}  "
              f"中转: {offer.stops_return}次")
        for seg in offer.return_segments:
            print(f"    {seg['carrier']}{seg['flight_no']}  "
                  f"{seg['from']} → {seg['to']}  "
                  f"{format_time(seg['departure'])} → {format_time(seg['arrival'])}")

    # 按出发城市分组统计最便宜
    print(f"\n{'='*100}")
    print("  各出发城市最低价汇总")
    print(f"{'='*100}")
    best_by_origin = {}
    for offer in all_offers:
        if offer.origin not in best_by_origin:
            best_by_origin[offer.origin] = offer
    for code, offer in sorted(best_by_origin.items(), key=lambda x: x[1].price_total):
        print(f"  {offer.origin_name}({offer.origin}) → {offer.destination_name}({offer.destination}): "
              f"CNY {offer.price_total:,.0f}  ({offer.airline}, 去{offer.outbound_date}, 回{return_date_label(offer.return_date)})")


def return_date_label(d: str) -> str:
    return d


async def main():
    parser = argparse.ArgumentParser(description="搜索中国城市到意大利的往返航班")
    parser.add_argument("--api-key", help="Amadeus API Key")
    parser.add_argument("--api-secret", help="Amadeus API Secret")
    args = parser.parse_args()

    api_key = args.api_key
    api_secret = args.api_secret

    if not api_key or not api_secret:
        try:
            from app.config import settings
            api_key = api_key or settings.API_KEY
            api_secret = api_secret or settings.API_SECRET
        except:
            pass

    if not api_key or not api_secret:
        print("错误: 需要 Amadeus API Key 和 Secret")
        print("用法: python search_flights.py --api-key YOUR_KEY --api-secret YOUR_SECRET")
        print("或在 .env 中配置:")
        print("  API_KEY=你的key")
        print("  API_SECRET=你的secret")
        return

    client = AmadeusClient(api_key, api_secret)

    try:
        await client.authenticate()

        all_offers = []
        total_combos = len(DEPARTURE_CITIES) * len(ITALY_CITIES) * len(OUTBOUND_DATES) * len(RETURN_DATES)
        done = 0

        for origin_code, origin_name in DEPARTURE_CITIES.items():
            for dest_code, dest_name in ITALY_CITIES.items():
                for out_date in OUTBOUND_DATES:
                    for ret_date in RETURN_DATES:
                        done += 1
                        label = f"{origin_name}→{dest_name} 去{out_date} 回{ret_date}"
                        print(f"  [{done}/{total_combos}] 搜索: {label}", end="", flush=True)

                        offers = await client.search_flights(origin_code, dest_code, out_date, ret_date)
                        all_offers.extend(offers)
                        print(f"  找到 {len(offers)} 个")

                        # 避免 API 限流
                        await asyncio.sleep(0.5)

        print_results(all_offers)

        # 保存完整结果到 JSON
        results = []
        for o in all_offers:
            results.append({
                "origin": o.origin,
                "origin_name": o.origin_name,
                "destination": o.destination,
                "destination_name": o.destination_name,
                "outbound_date": o.outbound_date,
                "return_date": o.return_date,
                "price": o.price_total,
                "currency": o.currency,
                "airline": o.airline,
                "stops_outbound": o.stops_outbound,
                "stops_return": o.stops_return,
                "duration_outbound": o.duration_outbound,
                "duration_return": o.duration_return,
            })
        with open("flight_results.json", "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"\n完整结果已保存到 flight_results.json")

    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
