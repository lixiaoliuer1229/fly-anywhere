"""
天巡 成都→米兰 单日航班搜索
先打开浏览器让用户手动登录，等待后再抓取数据
"""

import asyncio
import re
from datetime import datetime

from playwright.async_api import async_playwright

# 配置
ORIGIN = "CTU"
ORIGIN_NAME = "成都"
DEST = "MILA"
DEST_NAME = "米兰"

OUTBOUND_DATE = "2026-09-25"
RETURN_DATE = "2026-10-07"

WAIT_SECONDS = 60  # 等待用户手动登录的时间

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


async def extract_flights(page) -> list[dict]:
    """从页面提取航班数据"""
    flights = []

    try:
        await page.wait_for_load_state("networkidle", timeout=30000)
        await asyncio.sleep(5)

        body_text = await page.evaluate("document.body.innerText")

        with open("debug_page.txt", "w", encoding="utf-8") as f:
            f.write(body_text)
        print(f"    [debug] 页面文本已保存到 debug_page.txt ({len(body_text)} chars)")

        # 提取价格
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

        # 结构化提取
        flight_data = await page.evaluate("""
            () => {
                const results = [];
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

    # 去重
    seen = set()
    unique = []
    for f in flights:
        if f["price"] not in seen:
            seen.add(f["price"])
            unique.append(f)
    return unique


async def save_to_db(flights: list[dict]):
    """存入数据库"""
    from app.database import SessionLocal, engine, Base
    from app.models import Route, Price

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    try:
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
        # 使用独立的浏览器实例（不用 Chrome 用户目录，避免冲突）
        browser = await p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            locale="zh-CN",
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
        page = await context.new_page()

        print("正在打开页面...")
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        except Exception as e:
            print(f"页面加载超时，继续: {e}")

        await asyncio.sleep(3)
        await dismiss_popups(page)

        print(f"\n{'='*50}")
        print(f"浏览器已打开，请手动完成登录/验证操作")
        print(f"等待 {WAIT_SECONDS} 秒后自动开始抓取数据...")
        print(f"{'='*50}\n")

        # 等待用户手动操作
        for i in range(WAIT_SECONDS):
            remaining = WAIT_SECONDS - i
            if remaining % 10 == 0:
                print(f"  还剩 {remaining} 秒...")
            await asyncio.sleep(1)

        print("\n正在截取当前页面...")
        await page.screenshot(path="debug_screenshot.png", full_page=True)
        print("[debug] 截图已保存到 debug_screenshot.png")

        print("正在提取航班数据...")
        flights = await extract_flights(page)

        await page.close()
        await browser.close()

    if flights:
        flights.sort(key=lambda x: x["price"])
        print(f"\n找到 {len(flights)} 个航班:")
        print("-" * 60)
        for i, f in enumerate(flights[:20], 1):
            info = f"{f.get('airline', '')}  {f.get('stops', '')}  {f.get('duration', '')}"
            print(f"  #{i:2d}  ¥{f['price']:>8,.0f}  {info}")
        print("-" * 60)

        await save_to_db(flights)
    else:
        print("\n未找到航班数据，请检查 debug_screenshot.png 和 debug_page.txt")


if __name__ == "__main__":
    asyncio.run(main())