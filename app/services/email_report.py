"""Send one history report after each scheduled fetch, using authenticated TLS SMTP."""
from datetime import datetime, timedelta
from email.message import EmailMessage
from io import BytesIO
from html import escape
from pathlib import Path
from email.utils import make_msgid
import smtplib
import ssl

from sqlalchemy import func

from app.config import settings
from app.models import FlightOffer, SearchRun


def price_history(db, route_id):
    """Each point is a run's minimum observed price; never mix currencies."""
    return (db.query(SearchRun.started_at, FlightOffer.currency,
                     func.min(FlightOffer.price).label("price"))
            .join(FlightOffer, FlightOffer.search_run_id == SearchRun.id)
            .filter(SearchRun.route_id == route_id, SearchRun.status == "completed",
                    SearchRun.started_at >= datetime.now() - timedelta(days=90),
                    FlightOffer.price.isnot(None))
            .group_by(SearchRun.id, SearchRun.started_at, FlightOffer.currency)
            .order_by(SearchRun.started_at).all())


def render_chart(route, rows):
    # Contract: 90-day observed minimum per search, separate currency panels;
    # Connect observations when available; no data uses an explicit empty state.
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.dates import AutoDateLocator, DateFormatter
    from matplotlib.font_manager import FontProperties
    from matplotlib.text import Text

    font = FontProperties(fname=str(Path(__file__).resolve().parents[1] / "assets/fonts/NotoSansSC-Regular.otf"))

    currencies = sorted({row.currency for row in rows})
    fig = Figure(figsize=(10, 3.8 * max(1, len(currencies))), layout="constrained")
    FigureCanvasAgg(fig)
    axes = fig.subplots(max(1, len(currencies)), 1, squeeze=False).ravel()
    fig.suptitle(f"{route_label(route)}价格走势\n去程：{route.departure_date}　返程：{route.return_date}", fontsize=16)
    for ax, currency in zip(axes, currencies):
        points = [r for r in rows if r.currency == currency]
        ax.plot([r.started_at for r in points], [float(r.price) for r in points],
                marker="o", linestyle="-", color="#2563eb")
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
        axes[0].text(.5, .5, "最近 90 天暂无有效报价", ha="center", transform=axes[0].transAxes)
        axes[0].set_axis_off()
    for text in fig.findobj(Text):
        text.set_fontproperties(font)
    output = BytesIO()
    fig.savefig(output, format="png", dpi=150)
    return output.getvalue()


def route_label(route):
    cities = {"CTU": "成都双流", "TFU": "成都天府", "YVR": "温哥华", "OSL": "奥斯陆", "LHR": "伦敦希思罗", "MIL": "米兰"}
    return f"{cities.get(route.departure_city, route.departure_city)} → {cities.get(route.arrival_city, route.arrival_city)}"


def build_report(db, routes):
    message = EmailMessage()
    message["Subject"] = f"机票价格走势图 · {datetime.now():%Y-%m-%d}"
    message["From"] = settings.SMTP_FROM or settings.SMTP_USERNAME
    message["To"] = settings.EMAIL_TO
    introduction = "以下为最近 90 天已保存的机票参考报价。每个点表示一次成功查询的最低价（含起售价），连线仅连接观测点，不代表期间连续报价。不同币种分别绘制，实际价格以预订页面为准。"
    lines = ["机票价格走势图", introduction]
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
    message.set_content("\n".join(lines) + "\n请使用支持 HTML 的邮件客户端查看正文走势图。")
    message.add_alternative('<!doctype html><html lang="zh-CN"><body style="font-family:sans-serif;color:#222;margin:24px">'
                            '<h1 style="font-size:24px">机票价格走势图</h1>'
                            f'<p style="line-height:1.7">{escape(introduction)}</p>'
                            + "".join(sections) + '</body></html>', subtype="html")
    html_part = message.get_payload()[-1]
    for cid, image in images:
        html_part.add_related(image, maintype="image", subtype="png", cid=cid, disposition="inline")
    return message


def send_price_report(db, routes):
    if not settings.EMAIL_ENABLED:
        return False
    if not all((settings.EMAIL_TO, settings.SMTP_HOST, settings.SMTP_USERNAME, settings.SMTP_PASSWORD)):
        print("Email report skipped: configure EMAIL_TO, SMTP_HOST, SMTP_USERNAME and SMTP_PASSWORD.")
        return False
    message = build_report(db, routes)
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
