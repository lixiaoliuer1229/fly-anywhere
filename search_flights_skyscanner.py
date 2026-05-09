"""
天巡 (Skyscanner) 航班搜索脚本
使用 Playwright 自动化浏览器搜索航班价格

用法:
    python search_flights_skyscanner.py
    python search_flights_skyscanner.py --headless
"""

import asyncio
import argparse
import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime

from playwright.async_api import async_playwright


# 出发城市 (IATA code -> 中文名)
DEPARTURE_CITIES = {
    "CTU": "成都",
    "CAN": "广州",
    "HKG": "香港",
    "PVG": "上海",
    "KHN": "南昌",
}

# 意大利目的地城市
ITALY_CITIES = {
    "ROMA": "罗马",
    "MILA": "米兰",
    "VCE": "威尼斯",
    "FLR": "佛罗伦萨",
    "NAP": "那不勒斯",
    "BLQ": "博洛尼亚",
    "TRN": "都灵",
    "PMO": "巴勒莫",
    "CTA": "卡塔尼亚",
    "BRI": "巴里",
    "PSA": "比萨",
}

# 去程日期 (9/24晚出发 or 9/25出发)
OUTBOUND_DATES = ["2026-09-24", "2026-09-25"]
# 回程日期 (10/7 or 10/8)
RETURN_DATES = ["2026-10-07", "2026-10-08"]


@dataclass
class FlightResult:
    origin: str
    origin_name: str
    destination: str
    destination_name: str
    outbound_date: str
    return_date: str
    price: float
    currency: str
    airline: str
    stops_outbound: int = 0
    stops_return: int = 0
    duration_outbound: str = ""
    duration_return: str = ""


def date_to_yymmdd(date_str: str) -> str:
    """Convert YYYY-MM-DD to YYMMDD for Skyscanner URLs."""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return dt.strftime("%y%m%d")


def build_skyscanner_url(origin: str, destination: str, outbound: str, return_date: str) -> str:
    """Build Skyscanner search URL."""
    d1 = date_to_yymmdd(outbound)
    d2 = date_to_yymmdd(return_date)
    return (
        f"https://www.skyscanner.com/transport/flights/"
        f"{origin.lower()}/{destination.lower()}/{d1}/{d2}/"
        f"?adultsv2=1&cabinclass=economy&childrenv2=&ref=home&rtn=1"
        f"&preferdirects=true&outboundaltsen498=true&inboundaltsenabled=true"
    )


async def extract_flights_from_page(page) -> list[dict]:
    """Extract flight data from a loaded Skyscanner results page."""
    flights = []

    try:
        # Wait for results to load
        await page.wait_for_selector('[class*="FlightResults"]', timeout=15000)
        await asyncio.sleep(3)  # Extra time for all results to render

        # Try to get data from the page's embedded JSON
        flight_data = await page.evaluate("""
            () => {
                const results = [];
                // Look for flight result cards
                const cards = document.querySelectorAll('[class*="UpperTicketBody"], [class*="FlightResult"], [data-testid*="itinerary"]');

                for (const card of cards) {
                    const priceEl = card.querySelector('[class*="Price"], [class*="price"], [data-testid*="price"]');
                    const airlineEl = card.querySelector('[class*="Carrier"], [class*="carrier"], [class*="airline"]');
                    const stopsEl = card.querySelector('[class*="stops"], [class*="Stops"], [class*="duration"]');
                    const durationEl = card.querySelector('[class*="duration"], [class*="Duration"]');

                    if (priceEl) {
                        results.push({
                            price: priceEl.textContent?.trim() || '',
                            airline: airlineEl?.textContent?.trim() || '',
                            stops: stopsEl?.textContent?.trim() || '',
                            duration: durationEl?.textContent?.trim() || '',
                        });
                    }
                }
                return results;
            }
        """)

        if flight_data:
            for fd in flight_data:
                price_text = fd.get("price", "")
                price_match = re.search(r'[\d,]+\.?\d*', price_text.replace(",", ""))
                if price_match:
                    flights.append({
                        "price": float(price_match.group()),
                        "airline": fd.get("airline", ""),
                        "stops": fd.get("stops", ""),
                        "duration": fd.get("duration", ""),
                    })

        # If no results from card parsing, try getting the cheapest price shown
        if not flights:
            cheapest = await page.evaluate("""
                () => {
                    // Try various selectors for the cheapest price
                    const selectors = [
                        '[class*="CheapestPrice"]',
                        '[class*="cheapest"]',
                        '[class*="price"]',
                        '[data-testid*="price"]',
                        'span[class*="Price"]',
                    ];
                    for (const sel of selectors) {
                        const el = document.querySelector(sel);
                        if (el && el.textContent) {
                            const match = el.textContent.match(/[\\d,]+/);
                            if (match) return { price: match[0].replace(',', ''), airline: '', stops: '', duration: '' };
                        }
                    }

                    // Get all text and look for price patterns
                    const body = document.body.innerText;
                    const priceMatches = body.match(/(?:CNY|CN¥|¥|￥)\\s*([\\d,]+)/g);
                    if (priceMatches) {
                        return { price: priceMatches[0].replace(/[^\\d]/g, ''), airline: '', stops: '', duration: '' };
                    }
                    return null;
                }
            """)
            if cheapest and cheapest.get("price"):
                flights.append(cheapest)

    except Exception as e:
        print(f"    提取数据时出错: {e}")

    return flights


async def search_single_route(page, origin: str, dest: str, out_date: str, ret_date: str) -> list[FlightResult]:
    """Search a single route on Skyscanner."""
    origin_name = DEPARTURE_CITIES.get(origin, origin)
    dest_name = ITALY_CITIES.get(dest, dest)

    url = build_skyscanner_url(origin, dest, out_date, ret_date)
    print(f"    搜索: {origin_name}→{dest_name} 去{out_date} 回{ret_date}")

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        # Wait for the page to fully render
        await asyncio.sleep(5)

        # Dismiss any popups/banners
        try:
            close_btns = await page.query_selector_all('[aria-label="Close"], [class*="close"], button:has-text("Accept")')
            for btn in close_btns[:2]:
                await btn.click()
                await asyncio.sleep(0.5)
        except:
            pass

        await asyncio.sleep(2)

        flights_data = await extract_flights_from_page(page)

        results = []
        for fd in flights_data:
            try:
                price = fd.get("price", 0)
                if isinstance(price, str):
                    price = float(price.replace(",", ""))
                if price <= 0:
                    continue

                stops_text = fd.get("stops", "")
                stops_out = 0
                stops_ret = 0
                if "direct" in stops_text.lower() or "直飞" in stops_text:
                    stops_out = 0
                    stops_ret = 0
                elif "stop" in stops_text.lower() or "转" in stops_text:
                    stop_match = re.search(r'(\d)', stops_text)
                    if stop_match:
                        stops_out = int(stop_match.group(1))
                        stops_ret = int(stop_match.group(1))

                results.append(FlightResult(
                    origin=origin,
                    origin_name=origin_name,
                    destination=dest,
                    destination_name=dest_name,
                    outbound_date=out_date,
                    return_date=ret_date,
                    price=price,
                    currency="CNY",
                    airline=fd.get("airline", ""),
                    stops_outbound=stops_out,
                    stops_return=stops_ret,
                    duration_outbound=fd.get("duration", ""),
                    duration_return="",
                ))
            except (ValueError, TypeError):
                continue

        if results:
            print(f"      找到 {len(results)} 个航班，最低 ¥{min(r.price for r in results):,.0f}")
        else:
            print(f"      未找到航班数据")

        return results

    except Exception as e:
        print(f"      搜索出错: {e}")
        return []


async def search_via_api(origin: str, dest: str, out_date: str, ret_date: str) -> list[FlightResult]:
    """Try using Skyscanner's internal API to get flight prices."""
    import httpx

    origin_name = DEPARTURE_CITIES.get(origin, origin)
    dest_name = ITALY_CITIES.get(dest, dest)

    d1 = date_to_yymmdd(out_date)
    d2 = date_to_yymmdd(ret_date)

    url = (
        f"https://www.skyscanner.com/g/browse-view-bff/dataservices/"
        f"browse/v3/bvf/UK/GBP/en-GB/transport/flights/"
        f"{origin.lower()}/{dest.lower()}/{d1}/{d2}/?apikey=8aa374f4e28e4664a27571571571e0be"
    )

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                return parse_api_response(data, origin, dest, out_date, ret_date)
    except:
        pass

    return []


def parse_api_response(data: dict, origin: str, dest: str, out_date: str, ret_date: str) -> list[FlightResult]:
    """Parse Skyscanner API response."""
    results = []
    origin_name = DEPARTURE_CITIES.get(origin, origin)
    dest_name = ITALY_CITIES.get(dest, dest)

    quotes = data.get("Quotes", [])
    carriers = {c["CarrierId"]: c["Name"] for c in data.get("Carriers", [])}

    for quote in quotes:
        price = quote.get("MinPrice", 0)
        if price <= 0:
            continue

        direct = quote.get("Direct", True)
        carrier_ids = quote.get("OutboundLeg", {}).get("CarrierIds", [])
        airline = carriers.get(carrier_ids[0], "Unknown") if carrier_ids else "Unknown"

        results.append(FlightResult(
            origin=origin,
            origin_name=origin_name,
            destination=dest,
            destination_name=dest_name,
            outbound_date=out_date,
            return_date=ret_date,
            price=price,
            currency="CNY",
            airline=airline,
            stops_outbound=0 if direct else 1,
            stops_return=0 if direct else 1,
        ))

    return results


def print_summary(all_results: list[FlightResult]):
    """Print results sorted by price with summary."""
    if not all_results:
        print("\n未找到任何航班结果。")
        return

    all_results.sort(key=lambda x: x.price)

    print(f"\n{'='*90}")
    print(f"  找到 {len(all_results)} 个航班组合，按价格排序")
    print(f"{'='*90}")

    for i, r in enumerate(all_results[:50], 1):
        stops_info = ""
        if r.stops_outbound == 0:
            stops_info = "直飞"
        else:
            stops_info = f"{r.stops_outbound}转"

        print(f"  #{i:2d}  {r.origin_name}({r.origin}) → {r.destination_name}({r.destination})  "
              f"| ¥{r.price:>8,.0f}  {r.airline:>15s}  {stops_info:>4s}  "
              f"去{r.outbound_date} 回{return_date_short(r.return_date)}")

    # Summary by origin city
    print(f"\n{'='*90}")
    print("  各出发城市最低价汇总")
    print(f"{'='*90}")

    best_by_origin = {}
    for r in all_results:
        if r.origin not in best_by_origin or r.price < best_by_origin[r.origin].price:
            best_by_origin[r.origin] = r

    for code in DEPARTURE_CITIES:
        if code in best_by_origin:
            r = best_by_origin[code]
            print(f"  {r.origin_name}({r.origin}) → {r.destination_name}({r.destination}): "
                  f"¥{r.price:>8,.0f}  ({r.airline}, 去{r.outbound_date}, 回{return_date_short(r.return_date)})")

    # Summary by destination
    print(f"\n{'='*90}")
    print("  各目的地最低价汇总")
    print(f"{'='*90}")

    best_by_dest = {}
    for r in all_results:
        if r.destination not in best_by_dest or r.price < best_by_dest[r.destination].price:
            best_by_dest[r.destination] = r

    for r in sorted(best_by_dest.values(), key=lambda x: x.price):
        print(f"  {r.destination_name}({r.destination}): ¥{r.price:>8,.0f}  "
              f"({r.origin_name}出发, {r.airline})")


def return_date_short(d: str) -> str:
    return d[5:]  # MM-DD


async def main():
    parser = argparse.ArgumentParser(description="天巡 (Skyscanner) 航班搜索")
    parser.add_argument("--headless", action="store_true", help="无头模式运行浏览器")
    parser.add_argument("--api-only", action="store_true", help="仅使用API模式（更快但可能被限制）")
    parser.add_argument("--max-concurrent", type=int, default=3, help="最大并发数")
    args = parser.parse_args()

    all_results = []
    total_combos = len(DEPARTURE_CITIES) * len(ITALY_CITIES) * len(OUTBOUND_DATES) * len(RETURN_DATES)

    print(f"开始搜索: {len(DEPARTURE_CITIES)}个出发城市 × {len(ITALY_CITIES)}个意大利城市")
    print(f"去程: {', '.join(OUTBOUND_DATES)}  回程: {', '.join(RETURN_DATES)}")
    print(f"共 {total_combos} 个组合\n")

    # Try API approach first for all combos
    if args.api_only:
        print("使用 API 模式搜索...")
        done = 0
        for origin in DEPARTURE_CITIES:
            for dest in ITALY_CITIES:
                for out_date in OUTBOUND_DATES:
                    for ret_date in RETURN_DATES:
                        done += 1
                        origin_name = DEPARTURE_CITIES[origin]
                        dest_name = ITALY_CITIES[dest]
                        print(f"  [{done}/{total_combos}] {origin_name}→{dest_name} 去{out_date} 回{ret_date}", end="")

                        results = await search_via_api(origin, dest, out_date, ret_date)
                        all_results.extend(results)
                        if results:
                            print(f"  → {len(results)}个, 最低¥{min(r.price for r in results):,.0f}")
                        else:
                            print(f"  → 无结果")

                        await asyncio.sleep(0.3)

        print_summary(all_results)
        save_results(all_results)
        return

    # Use Playwright browser automation
    print("启动浏览器...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=args.headless,
            args=["--disable-blink-features=AutomationControlled"]
        )
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="zh-CN",
        )

        # Create pages for concurrent searches
        pages = []
        for _ in range(args.max_concurrent):
            page = await context.new_page()
            pages.append(page)

        done = 0
        tasks_queue = []

        for origin in DEPARTURE_CITIES:
            for dest in ITALY_CITIES:
                for out_date in OUTBOUND_DATES:
                    for ret_date in RETURN_DATES:
                        tasks_queue.append((origin, dest, out_date, ret_date))

        # Process in batches
        batch_size = args.max_concurrent
        for i in range(0, len(tasks_queue), batch_size):
            batch = tasks_queue[i:i + batch_size]
            batch_tasks = []

            for idx, (origin, dest, out_date, ret_date) in enumerate(batch):
                page = pages[idx % len(pages)]
                batch_tasks.append(search_single_route(page, origin, dest, out_date, ret_date))

            batch_results = await asyncio.gather(*batch_tasks, return_exceptions=True)
            for result in batch_results:
                if isinstance(result, list):
                    all_results.extend(result)
                elif isinstance(result, Exception):
                    print(f"    搜索异常: {result}")

            done += len(batch)
            print(f"  进度: {done}/{total_combos}")
            await asyncio.sleep(1)

        for page in pages:
            await page.close()
        await context.close()
        await browser.close()

    print_summary(all_results)
    save_results(all_results)


def save_results(all_results: list[FlightResult]):
    """Save results to JSON file."""
    results_data = []
    for r in all_results:
        results_data.append({
            "origin": r.origin,
            "origin_name": r.origin_name,
            "destination": r.destination,
            "destination_name": r.destination_name,
            "outbound_date": r.outbound_date,
            "return_date": r.return_date,
            "price": r.price,
            "currency": r.currency,
            "airline": r.airline,
            "stops_outbound": r.stops_outbound,
            "stops_return": r.stops_return,
        })

    with open("flight_results.json", "w", encoding="utf-8") as f:
        json.dump(results_data, f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存到 flight_results.json")


if __name__ == "__main__":
    asyncio.run(main())
