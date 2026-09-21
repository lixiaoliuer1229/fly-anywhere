"""Send one history report after each scheduled fetch, using authenticated TLS SMTP."""
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from io import BytesIO
from html import escape
from pathlib import Path
from email.utils import make_msgid, getaddresses
import smtplib
import ssl

from sqlalchemy import func

from app.config import settings
from app.models import FlightOffer, SearchRun, ExchangeRate
from app.services.exchange_rates import MONITORED_QUOTES

CURRENCY_NAMES = {"JPY": "日元", "CAD": "加元"}


def price_history(db, route_id):
    """Each point is a run's minimum observed CNY price."""
    return (db.query(SearchRun.started_at, FlightOffer.currency,
                     func.min(FlightOffer.price).label("price"))
            .join(FlightOffer, FlightOffer.search_run_id == SearchRun.id)
            .filter(SearchRun.route_id == route_id, SearchRun.status == "completed",
                    SearchRun.started_at >= datetime.now() - timedelta(days=90),
                    FlightOffer.price.isnot(None), FlightOffer.currency == "CNY")
            .group_by(SearchRun.id, SearchRun.started_at, FlightOffer.currency)
            .order_by(SearchRun.started_at).all())


def render_chart(route, rows):
    # Contract: 90-day observed CNY minimum per search;
    # Connect observations when available; no data uses an explicit empty state.
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.dates import AutoDateLocator, DateFormatter
    from matplotlib.font_manager import FontProperties
    from matplotlib.text import Text

    font = FontProperties(fname=str(Path(__file__).resolve().parents[1] / "assets/fonts/NotoSansSC-Regular.otf"))

    rows = [row for row in rows if row.currency == "CNY"]
    currencies = sorted({row.currency for row in rows})
    fig = Figure(figsize=(10, 3.8 * max(1, len(currencies))), layout="constrained")
    FigureCanvasAgg(fig)
    axes = fig.subplots(max(1, len(currencies)), 1, squeeze=False).ravel()
    fig.suptitle(f"{route_label(route)}价格走势\n去程：{route.departure_date}　返程：{route.return_date}", fontsize=16)
    for ax, currency in zip(axes, currencies):
        points = [r for r in rows if r.currency == currency]
        ax.plot([r.started_at for r in points], [float(r.price) for r in points],
                marker="o", linestyle="-", color="#2563eb")
        for index, point in enumerate(points):
            label = f"{point.price:,.2f}".rstrip("0").rstrip(".")
            above = index % 2 == 0
            ax.annotate(label, (point.started_at, float(point.price)),
                        xytext=(0, 10 if above else -12), textcoords="offset points",
                        ha="center", va="bottom" if above else "top", fontsize=9,
                        color="#1d4ed8", annotation_clip=False,
                        bbox=dict(facecolor="white", edgecolor="none", alpha=.85, pad=1))
        ax.margins(y=.18)
        ax.set_title(f"近 90 天每次查询的最低参考价 · 共 {len(points)} 个观测点", fontsize=10)
        ax.set_ylabel("价格（" + {"CNY": "人民币元", "USD": "美元", "CAD": "加元", "GBP": "英镑", "EUR": "欧元", "NOK": "挪威克朗"}.get(currency, currency) + "）")
        ax.set_xlabel("查询时间")
        dates = [r.started_at for r in points]
        padding = max(timedelta(hours=12), (max(dates) - min(dates)) / 20)
        ax.set_xlim(min(dates) - padding, max(dates) + padding)
        locator = AutoDateLocator()
        ax.xaxis.set_major_locator(locator)
        ax.xaxis.set_major_formatter(DateFormatter("%m月%d日\n%H:%M"))
        ax.grid(axis="y", color="#e5e7eb")
        ax.spines[["top", "right"]].set_visible(False)
    if not currencies:
        axes[0].text(.5, .5, "最近 90 天暂无有效人民币报价", ha="center", transform=axes[0].transAxes)
        axes[0].set_axis_off()
    for text in fig.findobj(Text):
        size = text.get_fontsize()
        text.set_fontproperties(font)
        text.set_fontsize(size)
    output = BytesIO()
    fig.savefig(output, format="png", dpi=150)
    return output.getvalue()


def exchange_history(db, quote="JPY"):
    return (db.query(ExchangeRate).filter(
        ExchangeRate.base == "CNY", ExchangeRate.quote == quote,
        ExchangeRate.rate_date >= (datetime.now(timezone.utc) - timedelta(days=90)).date())
        .order_by(ExchangeRate.rate_date).all())


def render_exchange_chart(rows, quote="JPY"):
    currency_name = CURRENCY_NAMES[quote]
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.dates import DayLocator, DateFormatter
    from matplotlib.font_manager import FontProperties
    from matplotlib.text import Text

    font = FontProperties(fname=str(Path(__file__).resolve().parents[1] / "assets/fonts/NotoSansSC-Regular.otf"))
    fig = Figure(figsize=(10, 3.8), layout="constrained")
    FigureCanvasAgg(fig)
    ax = fig.subplots()
    ax.set_title(f"人民币 / {currency_name} · 最近 90 天参考汇率走势")
    if rows:
        dates = [datetime.combine(row.rate_date, datetime.min.time()) for row in rows]
        ax.plot(dates, [float(row.rate) for row in rows], marker="o", color="#2563eb")
        for index, (observed_at, row) in enumerate(zip(dates, rows)):
            above = index % 2 == 0
            ax.annotate(f"{row.rate:.4f}", (observed_at, float(row.rate)),
                        xytext=(0, 10 if above else -12), textcoords="offset points",
                        ha="center", va="bottom" if above else "top", fontsize=9,
                        color="#1d4ed8", annotation_clip=False,
                        bbox=dict(facecolor="white", edgecolor="none", alpha=.85, pad=1))
        ax.margins(y=.18)
        padding = max(timedelta(hours=12), (max(dates) - min(dates)) / 20)
        ax.set_xlim(min(dates) - padding, max(dates) + padding)
        ax.xaxis.set_major_locator(DayLocator(interval=max(1, ((max(dates) - min(dates)).days + 6) // 7)))
        ax.xaxis.set_major_formatter(DateFormatter("%m月%d日"))
        ax.set_xlabel("来源报价日期")
        ax.set_ylabel(f"{currency_name} / 1 人民币")
        ax.grid(axis="y", color="#e5e7eb")
        ax.spines[["top", "right"]].set_visible(False)
    else:
        ax.text(.5, .5, "最近 90 天暂无汇率记录", ha="center", transform=ax.transAxes)
        ax.set_axis_off()
    for text in fig.findobj(Text):
        size = text.get_fontsize()
        text.set_fontproperties(font)
        text.set_fontsize(size)
    output = BytesIO()
    fig.savefig(output, format="png", dpi=150)
    return output.getvalue()


def route_label(route):
    cities = {"CTU": "成都双流", "TFU": "成都天府", "YVR": "温哥华", "OSL": "奥斯陆", "LHR": "伦敦希思罗", "MIL": "米兰", "PVG": "上海浦东", "FCO": "罗马 Fiumicino"}
    return f"{cities.get(route.departure_city, route.departure_city)} → {cities.get(route.arrival_city, route.arrival_city)}"


def build_report(db, routes, exchange_status=None, *, recipient=None, include_exchange=True, exchange_quotes=None):
    message = EmailMessage()
    title = "机票与汇率走势日报" if include_exchange else "机票走势日报"
    message["Subject"] = f"{title} · {datetime.now():%Y-%m-%d}"
    message["From"] = settings.SMTP_FROM or settings.SMTP_USERNAME
    message["To"] = settings.EMAIL_TO if recipient is None else recipient
    introduction = "以下仅展示最近 90 天已保存的人民币机票参考报价。每个点表示一次成功查询的人民币最低价（含起售价），连线仅连接观测点，不代表期间连续报价。实际价格以预订页面为准。"
    lines = [title, introduction]
    sections = []
    images = []
    statuses = {"completed": "已完成", "failed": "失败", "running": "查询中"}
    for route in routes:
        latest = (db.query(SearchRun).filter(SearchRun.route_id == route.id)
                  .order_by(SearchRun.started_at.desc()).first())
        heading = f"{route_label(route)}（{route.departure_date} 至 {route.return_date}）"
        status = (f"最近查询：{latest.started_at}，状态：{statuses.get(latest.status, latest.status)}"
                  if latest else "暂无查询记录")
        warning = f"提示：{latest.warning}" if latest and latest.warning else ""
        lines.extend([heading, status, warning])
        cid = make_msgid(domain="fly-anywhere.local")
        images.append((cid, render_chart(route, price_history(db, route.id))))
        sections.append(f'<h2 style="font-size:18px;margin-top:28px">{escape(heading)}</h2>'
                        f'<p style="color:#555">{escape(status)}</p>'
                        f'<p>{escape(warning)}</p>'
                        f'<img src="cid:{cid[1:-1]}" alt="{escape(heading)}价格走势图" '
                        'style="display:block;width:100%;max-width:900px;height:auto;border:0">')
    if include_exchange:
        for quote in (MONITORED_QUOTES if exchange_quotes is None else exchange_quotes):
            currency_name = CURRENCY_NAMES[quote]
            pair_status = exchange_status.get(quote) if isinstance(exchange_status, dict) else exchange_status
            rows = exchange_history(db, quote)
            latest_rate = (db.query(ExchangeRate).filter(ExchangeRate.base == "CNY", ExchangeRate.quote == quote)
                           .order_by(ExchangeRate.rate_date.desc()).first())
            fx_summary = (f"1 人民币 = {latest_rate.rate:.4f} {currency_name}；100 {currency_name} = {100 / latest_rate.rate:.4f} 人民币。"
                          f"报价日期：{latest_rate.rate_date}；最近获取：{latest_rate.fetched_at} UTC。"
                          if latest_rate else "暂无汇率记录。")
            fx_status = {"unavailable": "北京时间当天汇率尚未发布，以下为已保存历史数据，并非当天行情。", True: "本轮已获取北京时间当天参考汇率。", False: "本轮汇率获取失败，以下为已保存历史数据。"}.get(pair_status, "以下为已保存汇率数据。")
            fx_note = "数据来源：Frankfurter。每日参考汇率，非银行实时兑换价；节假日可能沿用最近报价，曲线按来源报价日期绘制。"
            lines.extend([f"人民币 / {currency_name}汇率", fx_status, fx_summary, fx_note])
            cid = make_msgid(domain="fly-anywhere.local")
            images.append((cid, render_exchange_chart(rows, quote)))
            sections.append(f'<h2 style="font-size:18px;margin-top:28px">人民币 / {currency_name}汇率</h2>'
                            f'<p>{escape(fx_status)}</p><p>{escape(fx_summary)}</p><p>{escape(fx_note)}</p>'
                            f'<img src="cid:{cid[1:-1]}" alt="人民币兑{currency_name}近90天参考汇率走势图" '
                            'style="display:block;width:100%;max-width:900px;height:auto;border:0">')
    message.set_content("\n".join(lines) + "\n请使用支持 HTML 的邮件客户端查看正文走势图。")
    message.add_alternative('<!doctype html><html lang="zh-CN"><body style="font-family:sans-serif;color:#222;margin:24px">'
                            f'<h1 style="font-size:24px">{escape(title)}</h1>'
                            f'<p style="line-height:1.7">{escape(introduction)}</p>'
                            + "".join(sections) + '</body></html>', subtype="html")
    html_part = message.get_payload()[-1]
    for cid, image in images:
        html_part.add_related(image, maintype="image", subtype="png", cid=cid, disposition="inline")
    return message


def send_price_report(db, routes, exchange_status=None, *, recipient=None, include_exchange=True, exchange_quotes=None):
    if not settings.EMAIL_ENABLED:
        return False
    destination = settings.EMAIL_TO if recipient is None else recipient
    if not all((destination, settings.SMTP_HOST, settings.SMTP_USERNAME, settings.SMTP_PASSWORD)):
        print("Email report skipped: configure EMAIL_TO, SMTP_HOST, SMTP_USERNAME and SMTP_PASSWORD.")
        return False
    message = build_report(db, routes, exchange_status=exchange_status,
                           recipient=destination, include_exchange=include_exchange, exchange_quotes=exchange_quotes)
    context = ssl.create_default_context()
    if settings.SMTP_SSL:
        client = smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, timeout=30, context=context)
    else:
        client = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=30)
    with client as smtp:
        if not settings.SMTP_SSL:
            smtp.starttls(context=context)
        smtp.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
        smtp.send_message(message)
    print("Price report accepted by SMTP server.")
    return True


def send_scheduled_reports(db, routes, exchange_status=None):
    """Merge routes shared by all default recipients into their existing report."""
    default_routes = []
    exclusive = {}
    default_addresses = {address.lower() for _, address in getaddresses([settings.EMAIL_TO]) if address}
    for route in routes:
        recipient = (getattr(route, "report_recipient", None) or "").strip()
        if recipient:
            addresses = [address for _, address in getaddresses([recipient]) if address]
            if default_addresses and default_addresses.issubset({address.lower() for address in addresses}):
                default_routes.append(route)
                addresses = [address for address in addresses if address.lower() not in default_addresses]
            if addresses:
                exclusive.setdefault(",".join(addresses), []).append(route)
        else:
            default_routes.append(route)
    deliveries = [(default_routes, {})]
    exchange_addresses = {address.lower() for _, address in getaddresses([settings.EMAIL_EXCHANGE_RECIPIENTS]) if address}
    for recipient, items in exclusive.items():
        groups = {}
        for _, address in getaddresses([recipient]):
            groups.setdefault(address.lower() in exchange_addresses, []).append(address)
        for include_exchange, addresses in groups.items():
            options = {"recipient": ",".join(addresses), "include_exchange": include_exchange}
            if include_exchange:
                options["exchange_quotes"] = ("JPY",)
            deliveries.append((items, options))
    results = []
    for items, options in deliveries:
        try:
            results.append(send_price_report(db, items, exchange_status=exchange_status, **options))
        except Exception as exc:
            print(f"Email report failed ({type(exc).__name__}); other recipients will still be processed.")
            results.append(False)
    return results
