"""
天巡 成都→米兰 单日航班搜索
搜索一对日期并存入数据库
"""

import asyncio
import re
import sys
from datetime import datetime

from playwright.async_api import async_playwright


# 配置
ORIGIN = "CTU"
ORIGIN_NAME = "成都"
DEST = "MILA"
DEST_NAME = "米兰"

# 搜索一对日期
OUTBOUND_DATE = "2026-09-25"
RETURN_DATE = "2026-10-07"


def date_to_yymmdd(date_str: str) -> str:
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return dt.strftime("%y%m%d")


def build_url(origin: str, dest: str, outbound: str, return_date: str) -> str:
    d1 = date_to_yymmdd(outbound)
    d2 = date_to_yymmdd(return_date)
    return (
        f"https://www.tianxun.com/transport/flights/"
        f"{origin.lower()}/{dest.lower()}/{d1}/{d2}/"
        f"?adultsv2=1&cabinclass=economy&childrenv2=&ref=home&rtn=1"
    )


async def dismiss_popups(page):
    try:
        # Cookie consent / close buttons
        for selector in [
            'button:has-text("Accept")',
            'button:has-text("接受")',
            'button:has-text("同意")',
            'button:has-text("OK")',
            'button:has-text("Got it")',
            '[aria-label="Close"]',
            '[class*="close"]',
        ]:
            try:
                btn = page.locator(selector).first
                if await btn.is_visible(timeout=1500):
                    await btn.click()
                    await asyncio.sleep(0.5)
            except:
                pass
    except:
        pass


async def extract_flights(page) -> list[dict]:
    """Extract flight results from the page text."""
    flights = []

    try:
        # Wait for results
        await page.wait_for_load_state("networkidle", timeout=40000)
        await asyncio.sleep(8)

        body_text = await page.evaluate("document.body.innerText")

        # Debug: save page text
        with open("debug_page.txt", "w", encoding="utf-8") as f:
            f.write(body_text)
        print(f"    [debug] 页面文本已保存到 debug_page.txt ({len(body_text)} chars)")

        # Try to find price patterns
        # Tianxun uses CN¥ or ¥
        price_pattern = re.compile(r'(?:CN¥|¥|￥)\s*([\d,]+)')
        prices_found = price_pattern.findall(body_text)

        if prices_found:
            seen = set()
            for pm in prices_found:
                try:
                    price = float(pm.replace(",", ""))
                    if 500 < price < 100000 and price not in seen:
                        seen.add(price)
                        flights.append({
                            "price": price,
                            "airline": "",
                            "stops": "",
                            "duration": "",
                        })
                except:
                    pass

        # Also try extracting from structured elements
        flight_data = await page.evaluate("""
            () => {
                const results = [];
                // Various selectors for flight cards
                const cards = document.querySelectorAll(
                    '[class*="UpperTicketBody"], [class*="FlightResult"], ' +
                    '[data-testid*="itinerary"], [class*="resultInner"], ' +
                    '[class*="FlightsTicket"]'
                );
                for (const card of cards) {
                    const priceEl = card.querySelector(
                        '[class*="Price"], [class*="price"], [data-testid*="price"], ' +
                        '[class*="priceText"], [class*="PriceText"]'
                    );
                    const airlineEl = card.querySelector(
                        '[class*="Carrier"], [class*="carrier"], [class*="airline"], ' +
                        '[class*="carrierText"]'
                    );
                    if (priceEl) {
                        results.push({
                            price: priceEl.textContent?.trim() || '',
                            airline: airlineEl?.textContent?.trim() || '',
                        });
                    }
                }
                return results;
            }
        """)

        if flight_data:
            print(f"    [debug] 结构化数据: {len(flight_data)} 条")
            for fd in flight_data:
                price_text = fd.get("price", "")
                m = re.search(r'[\d,]+', price_text.replace(",", ""))
                if m:
                    price = float(m.group())
                    if 500 < price < 100000:
                        flights.append({
                            "price": price,
                            "airline": fd.get("airline", ""),
                            "stops": "",
                            "duration": "",
                        })

    except Exception as e:
        print(f"    提取出错: {e}")

    # Dedupe by price
    seen = set()
    unique = []
    for f in flights:
        if f["price"] not in seen:
            seen.add(f["price"])
            unique.append(f)
    return unique


async def save_to_db(flights: list[dict]):
    """Save flights to database."""
    from app.database import SessionLocal, engine, Base
    from app.models import Route, Price

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    try:
        # Find or create route
        route = db.query(Route).filter(
            Route.departure_city == ORIGIN_NAME,
            Route.arrival_city == DEST_NAME,
        ).first()

        if not route:
            route = Route(
                departure_city=ORIGIN_NAME,
                arrival_city=DEST_NAME,
                airline="",
            )
            db.add(route)
            db.flush()

        count = 0
        for f in flights:
            price_record = Price(
                route_id=route.id,
                price=f["price"],
                cabin_class="economy",
                source="tianxun",
                scraped_at=datetime.now(),
            )
            db.add(price_record)
            count += 1

        db.commit()
        print(f"已存入数据库: {count} 条价格记录 (route_id={route.id})")
    except Exception as e:
        print(f"数据库存储失败: {e}")
        db.rollback()
    finally:
        db.close()


async def main():
    url = build_url(ORIGIN, DEST, OUTBOUND_DATE, RETURN_DATE)
    print(f"天巡航班搜索: {ORIGIN_NAME} → {DEST_NAME}")
    print(f"去程: {OUTBOUND_DATE}  回程: {RETURN_DATE}")
    print(f"URL: {url}\n")

    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            locale="zh-CN",
        )
        page = await context.new_page()

        print("正在加载页面...")
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        except Exception as e:
            print(f"页面加载超时，继续尝试: {e}")

        await asyncio.sleep(3)
        await dismiss_popups(page)
        await asyncio.sleep(2)

        # Check if we need to click "view flights" or similar
        body = await page.evaluate("document.body.innerText")
        if "查看航班" in body or "View flights" in body:
            print("发现'查看航班'按钮，点击中...")
            try:
                await page.locator("text=查看航班").first.click(timeout=5000)
                await asyncio.sleep(5)
            except:
                pass

        print("正在提取航班数据...")
        flights = await extract_flights(page)

        # Take a screenshot for debugging
        await page.screenshot(path="debug_screenshot.png", full_page=True)
        print("[debug] 截图已保存到 debug_screenshot.png")

        await page.close()
        await context.close()
        await browser.close()

    if flights:
        flights.sort(key=lambda x: x["price"])
        print(f"\n找到 {len(flights)} 个航班:")
        print("-" * 60)
        for i, f in enumerate(flights[:20], 1):
            info = f"{f.get('airline', '')}  {f.get('stops', '')}  {f.get('duration', '')}"
            print(f"  #{i:2d}  ¥{f['price']:>8,.0f}  {info}")
        print("-" * 60)

        # Save to database
        await save_to_db(flights)
    else:
        print("\n未找到航班数据，请检查 debug_screenshot.png 和 debug_page.txt")


if __name__ == "__main__":
    asyncio.run(main())
