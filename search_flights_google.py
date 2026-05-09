"""
Google Flights 航班批量搜索脚本
使用 Playwright 无头浏览器搜索航班价格并存入数据库

用法:
    python search_flights_google.py              # 无头模式（默认）
    python search_flights_google.py --headed     # 有头模式（可看到浏览器）
"""

import asyncio
import argparse
import json
import re
import base64
import urllib.parse
from datetime import datetime

from playwright.async_api import async_playwright, Page


# ============================================================
# 配置
# ============================================================

DEPARTURE_CITIES = ["成都", "广州", "香港", "上海", "南昌"]
ITALY_CITIES = ["罗马", "米兰", "威尼斯", "佛罗伦萨", "那不勒斯",
                "博洛尼亚", "都灵", "巴勒莫", "卡塔尼亚", "巴里", "比萨"]
OUTBOUND_DATES = ["2026-09-24", "2026-09-25"]
RETURN_DATES = ["2026-10-07", "2026-10-08"]


# ============================================================
# Google Flights tfs protobuf 编码
# ============================================================

def encode_varint(value: int) -> bytes:
    result = b''
    while value > 0x7F:
        result += bytes([(value & 0x7F) | 0x80])
        value >>= 7
    result += bytes([value & 0x7F])
    return result


def encode_tag(field_num: int, wire_type: int) -> bytes:
    """Encode a protobuf tag, handling multi-byte tags for field_num > 15."""
    return encode_varint((field_num << 3) | wire_type)


def encode_field_varint(field_num: int, value: int) -> bytes:
    return encode_tag(field_num, 0) + encode_varint(value)


def encode_field_string(field_num: int, s: str) -> bytes:
    encoded = s.encode('utf-8')
    return encode_tag(field_num, 2) + encode_varint(len(encoded)) + encoded


def encode_field_bytes(field_num: int, data: bytes) -> bytes:
    return encode_tag(field_num, 2) + encode_varint(len(data)) + data


def encode_leg(date: str, origin_id: str, dest_id: str) -> bytes:
    inner = (
        encode_field_string(2, date) +
        encode_field_bytes(13, encode_field_varint(1, 3) + encode_field_string(2, origin_id)) +
        encode_field_bytes(14, encode_field_varint(1, 3) + encode_field_string(2, dest_id))
    )
    return encode_field_bytes(3, inner)


def make_tfs(origin_id: str, dest_id: str, out_date: str, ret_date: str) -> bytes:
    return (
        encode_field_varint(1, 0x1c) +           # field 1 = 28 (round trip)
        encode_field_varint(2, 1) +               # field 2 = 1 (adults)
        encode_leg(out_date, origin_id, dest_id) +  # outbound leg
        encode_leg(ret_date, dest_id, origin_id) +  # return leg
        encode_field_varint(8, 1) +
        encode_field_varint(9, 1) +
        encode_field_varint(14, 1) +
        encode_field_bytes(16, encode_field_varint(1, 0xffffffffffffffff)) +
        encode_field_varint(19, 1)
    )


def tfs_to_url(tfs_bytes: bytes) -> str:
    encoded = base64.urlsafe_b64encode(tfs_bytes).decode('ascii')
    return f'https://www.google.com/travel/flights?tfs={encoded}&tfu=KgIIAw&hl=zh-CN&curr=CNY'


# ============================================================
# Playwright helpers
# ============================================================

async def dismiss_popups(page: Page):
    try:
        btns = await page.query_selector_all('button')
        for btn in btns[:20]:
            text = await btn.text_content()
            if text and any(k in text.lower() for k in ['accept', 'agree', '接受', '同意', 'got it', '确定', '仍然继续']):
                await btn.click()
                await asyncio.sleep(0.5)
                break
    except:
        pass


async def get_place_id(page: Page, city_name: str) -> str:
    """Get Google's internal place ID for a city."""
    await page.goto('https://www.google.com/travel/flights?hl=zh-CN&curr=CNY',
                    wait_until='networkidle', timeout=30000)
    await asyncio.sleep(3)
    await dismiss_popups(page)

    # Fill origin
    origin_el = page.locator('[aria-label="从哪里出发？"]')
    await origin_el.click()
    await asyncio.sleep(0.5)
    await page.keyboard.type(city_name, delay=100)
    await asyncio.sleep(3)
    await page.keyboard.press('ArrowDown')
    await asyncio.sleep(0.3)
    await page.keyboard.press('Enter')
    await asyncio.sleep(1)

    # Fill destination (Rome as dummy)
    dest_el = page.locator('[placeholder="要去哪儿？"]')
    await dest_el.click()
    await asyncio.sleep(0.5)
    await page.keyboard.type('罗马', delay=100)
    await asyncio.sleep(3)
    await page.keyboard.press('ArrowDown')
    await asyncio.sleep(0.3)
    await page.keyboard.press('Enter')
    await asyncio.sleep(1)

    # Dates
    dep = page.locator('[placeholder="出发时间"]').first
    await dep.click(force=True)
    await asyncio.sleep(1)
    await page.keyboard.type('9/25/2026', delay=80)
    await asyncio.sleep(1)
    await page.keyboard.press('Enter')
    await asyncio.sleep(2)

    ret = page.locator('[placeholder="返程时间"]').first
    await ret.click(force=True)
    await asyncio.sleep(1)
    await page.keyboard.type('10/7/2026', delay=80)
    await asyncio.sleep(1)
    await page.keyboard.press('Enter')
    await asyncio.sleep(2)

    try:
        await page.locator('button:has-text("完成")').click(timeout=3000)
    except:
        pass
    await asyncio.sleep(1)
    try:
        await page.locator('[aria-label*="搜索"]').first.click()
    except:
        await page.keyboard.press('Enter')

    await asyncio.sleep(5)

    # Extract place ID from URL
    current_url = page.url
    if 'tfs=' in current_url:
        params = urllib.parse.parse_qs(urllib.parse.urlparse(current_url).query)
        tfs_b64 = params.get('tfs', [''])[0]
        try:
            decoded = base64.urlsafe_b64decode(tfs_b64 + '==')
            place_ids = re.findall(rb'/m/[a-z0-9]+', decoded)
            if place_ids:
                return place_ids[0].decode('ascii')
        except:
            pass
    return ""


async def search_single_route(page: Page, tfs_url: str, origin: str, dest: str,
                               out_date: str, ret_date: str) -> list[dict]:
    """Navigate to a tfs URL and extract flight prices."""
    results = []
    try:
        await page.goto(tfs_url, wait_until='networkidle', timeout=45000)
        await asyncio.sleep(12)

        body_text = str(await page.evaluate('document.body.innerText'))

        # If on overview page, click "查看航班"
        if '搜索结果' not in body_text and '查看航班' in body_text:
            try:
                await page.locator('text=查看航班').first.click(timeout=3000)
                await asyncio.sleep(15)
                body_text = str(await page.evaluate('document.body.innerText'))
            except:
                pass

        # Extract flights
        lines = body_text.split('\n')
        for i, line in enumerate(lines):
            price_match = re.search(r'¥([\d,]+)', line.strip())
            if not price_match:
                continue
            try:
                price = float(price_match.group(1).replace(',', ''))
            except:
                continue
            if not (500 < price < 100000):
                continue

            airline, stops, duration = "", "", ""
            for j in range(max(0, i - 5), i):
                prev = lines[j].strip()
                for al in ['卡塔尔航空', '海航', '国航', '东航', '南航', '川航', '深航',
                            '厦航', '春秋航空', '吉祥航空', '土耳其航空', '汉莎航空',
                            '阿联酋航空', '阿提哈德航空', '国泰航空', '新航', '法航',
                            '荷兰皇家航空', '芬兰航空', '瑞士航空', '奥地利航空',
                            'Qatar', 'Emirates', 'Etihad', 'Turkish', 'Lufthansa',
                            'Singapore', 'Cathay', 'Air China', 'China Eastern',
                            'China Southern', 'Sichuan', 'Hainan', 'Xiamen',
                            'Shenzhen', 'KLM', 'Air France', 'Finnair']:
                    if al in prev:
                        airline = al
                        break
                if '直飞' in prev or '直达' in prev:
                    stops = "直飞"
                elif '经停' in prev:
                    m = re.search(r'经停\s*(\d+)\s*次', prev)
                    stops = f"经停{m.group(1)}次" if m else "经停"
                dur_m = re.search(r'(\d+\s*小时\s*\d+\s*分钟|\d+\s*小时|\d+\s*分钟)', prev)
                if dur_m:
                    duration = dur_m.group(1)

            results.append({
                "origin": origin, "destination": dest,
                "outbound_date": out_date, "return_date": ret_date,
                "price": price, "airline": airline,
                "stops": stops, "duration": duration,
            })

        # Fallback: regex on full text
        if not results:
            seen = set()
            for pm in re.findall(r'¥([\d,]+)', body_text):
                try:
                    v = float(pm.replace(',', ''))
                    if 500 < v < 100000 and v not in seen:
                        seen.add(v)
                        results.append({
                            "origin": origin, "destination": dest,
                            "outbound_date": out_date, "return_date": ret_date,
                            "price": v, "airline": "", "stops": "", "duration": "",
                        })
                except:
                    pass
            results = results[:5]

    except Exception as e:
        print(f"      Error: {e}")

    return results


# ============================================================
# Database storage
# ============================================================

def save_to_db(all_results: list[dict]):
    """Save results to MySQL database."""
    try:
        from app.database import SessionLocal, engine, Base
        from app.models import Route, Price
        from datetime import datetime as dt

        Base.metadata.create_all(bind=engine)
        db = SessionLocal()

        count = 0
        for r in all_results:
            # Find or create route
            route = db.query(Route).filter(
                Route.departure_city == r["origin"],
                Route.arrival_city == r["destination"],
            ).first()

            if not route:
                route = Route(
                    departure_city=r["origin"],
                    arrival_city=r["destination"],
                    airline=r.get("airline", ""),
                )
                db.add(route)
                db.flush()

            # Add price record
            price_record = Price(
                route_id=route.id,
                price=r["price"],
                cabin_class="economy",
                source="google_flights",
                scraped_at=dt.now(),
            )
            db.add(price_record)
            count += 1

        db.commit()
        db.close()
        print(f"已存入数据库: {count} 条价格记录")
    except Exception as e:
        print(f"数据库存储失败: {e}")


def save_to_json(all_results: list[dict]):
    with open("flight_results.json", "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    print(f"结果已保存到 flight_results.json")


# ============================================================
# Summary
# ============================================================

def print_summary(all_results: list[dict]):
    if not all_results:
        print("\n未找到任何航班结果。")
        return

    all_results.sort(key=lambda x: x["price"])

    print(f"\n{'='*95}")
    print(f"  找到 {len(all_results)} 个航班，按价格排序（显示前 50）")
    print(f"{'='*95}")

    for i, r in enumerate(all_results[:50], 1):
        print(f"  #{i:2d}  {r['origin']} → {r['destination']}  "
              f"| ¥{r['price']:>8,.0f}  {r.get('airline',''):>12s}  {r.get('stops',''):>8s}  {r.get('duration',''):>14s}  "
              f"去{r['outbound_date']} 回{return_date_short(r['return_date'])}")

    # Best by origin
    print(f"\n{'='*95}")
    print("  各出发城市最低价")
    print(f"{'='*95}")
    best_origin = {}
    for r in all_results:
        if r["origin"] not in best_origin or r["price"] < best_origin[r["origin"]]["price"]:
            best_origin[r["origin"]] = r
    for r in sorted(best_origin.values(), key=lambda x: x["price"]):
        print(f"  {r['origin']} → {r['destination']}: ¥{r['price']:>8,.0f}  "
              f"({r.get('airline','')}, 去{r['outbound_date']}, 回{return_date_short(r['return_date'])})")

    # Best by destination
    print(f"\n{'='*95}")
    print("  各目的地最低价")
    print(f"{'='*95}")
    best_dest = {}
    for r in all_results:
        if r["destination"] not in best_dest or r["price"] < best_dest[r["destination"]]["price"]:
            best_dest[r["destination"]] = r
    for r in sorted(best_dest.values(), key=lambda x: x["price"]):
        print(f"  {r['destination']}: ¥{r['price']:>8,.0f}  ({r['origin']}出发, {r.get('airline','')})")


def return_date_short(d: str) -> str:
    return d[5:]


# ============================================================
# Main
# ============================================================

async def main():
    parser = argparse.ArgumentParser(description="Google Flights 航班批量搜索")
    parser.add_argument("--headed", action="store_true", help="有头模式（显示浏览器窗口）")
    args = parser.parse_args()

    headless = not args.headed

    print("=" * 60)
    print("  Google Flights 航班批量搜索")
    print("=" * 60)
    print(f"出发城市: {', '.join(DEPARTURE_CITIES)}")
    print(f"目的地: {', '.join(ITALY_CITIES)}")
    print(f"去程: {', '.join(OUTBOUND_DATES)}")
    print(f"回程: {', '.join(RETURN_DATES)}")
    print(f"模式: {'有头' if args.headed else '无头'}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=headless,
            args=['--disable-blink-features=AutomationControlled']
        )
        ctx = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            locale='zh-CN',
        )
        await ctx.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
        page = await ctx.new_page()

        # Step 1: Get place IDs
        print("\n--- Step 1: 获取城市 ID ---")
        all_cities = list(set(DEPARTURE_CITIES + ITALY_CITIES))
        place_ids = {}

        for city in all_cities:
            print(f"  获取 {city}...", end="", flush=True)
            pid = await get_place_id(page, city)
            if pid:
                place_ids[city] = pid
                print(f" {pid}")
            else:
                print(f" FAILED")
            await asyncio.sleep(1)

        print(f"\n  成功: {len(place_ids)}/{len(all_cities)}")

        # Step 2: Search flights
        print("\n--- Step 2: 搜索航班 ---")
        all_results = []
        tasks = []

        for origin in DEPARTURE_CITIES:
            for dest in ITALY_CITIES:
                if origin not in place_ids or dest not in place_ids:
                    continue
                for out_date in OUTBOUND_DATES:
                    for ret_date in RETURN_DATES:
                        tfs_bytes = make_tfs(place_ids[origin], place_ids[dest], out_date, ret_date)
                        url = tfs_to_url(tfs_bytes)
                        tasks.append((url, origin, dest, out_date, ret_date))

        for done, (url, origin, dest, out_date, ret_date) in enumerate(tasks, 1):
            label = f"{origin}→{dest} 去{out_date} 回{ret_date}"
            print(f"  [{done}/{len(tasks)}] {label}", end="", flush=True)

            results = await search_single_route(page, url, origin, dest, out_date, ret_date)
            all_results.extend(results)

            if results:
                prices = [r["price"] for r in results]
                print(f" → {len(results)}个, 最低¥{min(prices):,.0f}")
            else:
                print(f" → 无结果")

            await asyncio.sleep(2)

        await page.close()
        await ctx.close()
        await browser.close()

    print_summary(all_results)
    save_to_json(all_results)
    save_to_db(all_results)


if __name__ == "__main__":
    asyncio.run(main())
