"""Send one history report after each scheduled fetch, using authenticated TLS SMTP."""
from datetime import datetime, timedelta
from email.message import EmailMessage
from io import BytesIO
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
    # sparse history uses dots, no data uses an explicit empty state. PNG for email.
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.dates import AutoDateLocator, ConciseDateFormatter

    currencies = sorted({row.currency for row in rows})
    fig = Figure(figsize=(10, 3.8 * max(1, len(currencies))), layout="constrained")
    FigureCanvasAgg(fig)
    axes = fig.subplots(max(1, len(currencies)), 1, squeeze=False).ravel()
    fig.suptitle(f"{route.departure_city} → {route.arrival_city} | {route.departure_date} / {route.return_date}")
    for ax, currency in zip(axes, currencies):
        points = [r for r in rows if r.currency == currency]
        ax.plot([r.started_at for r in points], [float(r.price) for r in points],
                marker="o", linestyle="-" if len(points) >= 8 else "None", color="#2563eb")
        ax.set_title(f"Minimum observed reference price | last 90 days | {len(points)} searches", fontsize=10)
        ax.set_ylabel(currency)
        ax.set_xlabel("Search date")
        dates = [r.started_at for r in points]
        padding = max(timedelta(hours=12), (max(dates) - min(dates)) / 20)
        ax.set_xlim(min(dates) - padding, max(dates) + padding)
        locator = AutoDateLocator()
        ax.xaxis.set_major_locator(locator)
        ax.xaxis.set_major_formatter(ConciseDateFormatter(locator))
        ax.grid(axis="y", color="#e5e7eb")
        ax.spines[["top", "right"]].set_visible(False)
    if not currencies:
        axes[0].text(.5, .5, "No priced results in the last 90 days", ha="center", transform=axes[0].transAxes)
        axes[0].set_axis_off()
    output = BytesIO()
    fig.savefig(output, format="png", dpi=150)
    return output.getvalue()


def build_report(db, routes):
    message = EmailMessage()
    message["Subject"] = f"机票价格走势图 · {datetime.now():%Y-%m-%d}"
    message["From"] = settings.SMTP_FROM or settings.SMTP_USERNAME
    message["To"] = settings.EMAIL_TO
    lines = ["本轮机票查询已结束，最近 90 天价格图见附件。", "每个点为一次成功查询的最低参考报价（含起售价）；不同币种分开显示。",
             "数据来自已保存的搜索结果，非实时成交价；数据源变化可能影响可比性。少于 8 次记录时仅显示散点。", ""]
    charts = []
    for route in routes:
        latest = (db.query(SearchRun).filter(SearchRun.route_id == route.id)
                  .order_by(SearchRun.started_at.desc()).first())
        lines.append(f"{route.departure_city} → {route.arrival_city} ({route.departure_date} / {route.return_date})")
        lines.append(f"最近查询：{latest.started_at}，状态：{latest.status}" if latest else "暂无查询记录")
        if latest and latest.warning:
            lines.append(f"提示：{latest.warning}")
        charts.append((f"route-{route.id}-trend.png", render_chart(route, price_history(db, route.id))))
    message.set_content("\n".join(lines))
    for name, image in charts:
        message.add_attachment(image, maintype="image", subtype="png", filename=name)
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
