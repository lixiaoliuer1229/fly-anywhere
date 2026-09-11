# AI 机票搜索与价格监控

使用 LangChain Agent 调用 Tavily 搜索公开网页中的机票参考价格，同时保留原有的航线价格监控功能。

> Tavily 不是航班库存 API。AI 搜索结果可能是缓存价、起售价或促销价，只能作为参考；实际价格和余票以来源预订页面为准。

## 功能

- 使用自然语言描述行程，由 LangChain 提取结构化条件并查询机票价格
- 数据源自动降级顺序：SerpApi Google Flights → Amadeus Flight Offers → Tavily
- 将网页信息整理为航班、价格、币种、时间和来源链接等结构化数据
- 对无法被来源确认的价格不做猜测，并在页面显示风险提示
- 支持指定固定航线，定时抓取价格（原有功能）
- 两种数据源：第三方 API（AviationStack / Amadeus）+ 爬虫
- MySQL 存储价格历史
- Web 页面展示价格波动图表（ECharts）
- 程序内定时循环抓取

## 快速开始

### Docker 部署（推荐）

服务器需要 Docker 与 Docker Compose。复制环境变量文件并填写真实密钥：

```bash
cp .env.example .env
docker compose up -d --build
docker compose ps
curl http://127.0.0.1:18000/healthz
```

Compose 会启动应用和 MySQL 8.4，数据库数据保存在命名卷中；应用每次启动前会自动执行 Alembic 迁移。默认仅绑定服务器的 `127.0.0.1:18000`，不会直接暴露到公网。需要公网访问时，应通过已有 Nginx/Caddy 配置域名、HTTPS 和反向代理，而不是直接开放应用端口。

常用维护命令：

```bash
docker compose logs -f app
docker compose restart app
docker compose pull
docker compose up -d --build
```

`.env` 不会进入 Docker 镜像，也已被 Git 忽略。生产环境必须使用独立强密码，并限制该文件权限（例如 `chmod 600 .env`）。

### 1. 安装依赖

```bash
cd fly-anywhere
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`，至少配置一种模型和 Tavily。OpenAI 示例：

```
DATABASE_URL=mysql+pymysql://user:password@localhost/fly_anywhere
OPENAI_API_KEY=your_openai_api_key
AI_PROVIDER=openai
AI_MODEL=gpt-4.1-mini
TAVILY_API_KEY=tvly-your_tavily_api_key
```

Anthropic 或 Anthropic 兼容服务示例：

```text
AI_PROVIDER=anthropic
ANTHROPIC_API_KEY=your_anthropic_api_key
ANTHROPIC_BASE_URL=
ANTHROPIC_MODEL=claude-sonnet-4-6
TAVILY_API_KEY=tvly-your_tavily_api_key
```

原有定时监控所需的 `API_KEY`、`API_SECRET` 等配置见 `.env.example`。`.env` 已被 Git 忽略，不得把真实密钥写入 `.env.example` 或其他受版本控制的文件。

### 3. 启动服务

```bash
alembic upgrade head
uvicorn app.main:app --reload
```

访问 `http://localhost:8000`

## 使用说明

在页面顶部用自然语言输入完整行程，例如：

```text
2026 年 9 月 10 日北京飞东京，1 人单程经济舱
```

AI 会搜索公开网页并展示可追溯的参考结果。输入越完整，结果越有意义。页面下方仍可使用原有航线监控与价格趋势功能。

每次 AI 查询都会记录到 `search_runs`，可确认的结构化结果记录到 `flight_offers`。数据库结构统一通过 Alembic 迁移管理。

## 后续路线

- 机票数据源已按 `SerpApi Google Flights → Amadeus Flight Offers → Tavily` 的优先级接入，并在密钥未配置、额度耗尽、请求失败或无结果时自动降级。SerpApi 和 Amadeus 密钥需要分别在 `.env` 中配置。
- Amadeus 官方已提示 Self-Service 门户停止面向新用户提供；本项目仍保留 Flight Offers 适配器，供已有有效凭据的账号使用。若没有存量 Amadeus 凭据，该层会被跳过。
- 已增加人民币 / 日元汇率监控：每日定时获取参考汇率并保存历史记录，在数据看板展示双向换算和走势图。

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/routes/` | 航线列表 |
| POST | `/api/routes/` | 添加航线 |
| DELETE | `/api/routes/{id}` | 删除航线 |
| GET | `/api/prices/latest` | 最新价格 |
| GET | `/api/prices/{route_id}` | 价格历史 |
| POST | `/api/prices/fetch/{route_id}` | 手动触发抓取 |
| POST | `/api/ai/search` | LangChain 自然语言机票搜索与多数据源自动降级 |

## 技术栈

- Python 3.12
- FastAPI + Uvicorn
- LangChain + LangGraph Agent runtime
- Tavily Search + OpenAI/兼容模型
- SQLAlchemy + MySQL
- ECharts
- httpx + BeautifulSoup4

## 用户登录

首次执行数据库迁移会自动创建初始账号 `admin`，密码使用项目所有者指定的初始密码（代码中仅保存哈希）。若该账号已存在，迁移不会覆盖其密码。首次访问会进入登录页，也可点击“注册账号”创建其他账号。账号为 3–64 位字母、数字、下划线或短横线，不区分大小写；密码为 8–128 个字符。注册成功自动登录，页面顶部可退出。

账号和加盐 scrypt 密码哈希存入 `users` 表，不保存明文密码。登录会话有效期为 7 天，数据库 `user_sessions` 仅保存令牌哈希；退出后立即失效。现有页面及业务 API 需要登录，航线、查询历史和价格数据由所有登录用户共享。当前允许自主注册，不包含角色权限或找回密码。

更新后先运行 `alembic upgrade head`（Docker 启动时自动执行）。HTTPS 部署请设置 `AUTH_COOKIE_SECURE=true`；反向代理需正确传递请求协议和 Host，以便同源请求校验。

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/auth/register` | JSON 账号密码注册：`username`、`password` |
| POST | `/api/auth/login` | JSON 账号密码登录，设置 HttpOnly Cookie |
| GET | `/api/auth/me` | 获取当前登录账号 |
| POST | `/api/auth/logout` | 撤销当前会话并退出 |

验证：`.venv/bin/python -m unittest discover -s tests`（使用隔离的 SQLite 数据库）。

## 每日邮件走势图

将 `.env` 中 `EMAIL_ENABLED=true`，`EMAIL_TO` 设为收件邮箱，多个地址使用英文逗号分隔。配置发件账号的
`SMTP_HOST`、`SMTP_PORT`、`SMTP_USERNAME`、`SMTP_PASSWORD`（SMTP 授权码）；
`SMTP_FROM` 默认使用发件账号。默认使用 465 端口的 TLS；其他服务如需 STARTTLS，
设置 `SMTP_SSL=false` 并使用服务商指定端口。收件 QQ 邮箱不必与发件账号相同。

`SCRAPE_DAILY_TIME=09:30`、`SCRAPE_TIMEZONE=Asia/Shanghai` 表示每天北京时间
上午 9:30 开始查询。重启后仍按下一次 9:30 执行，停机期间错过的任务不补跑，需保持服务运行。每轮全部航线查询结束后发送一封邮件，正文展示各航线
最近 90 天正文内嵌 PNG 走势图，不添加独立下载附件。每个点是一次成功查询的最低参考报价（含起售价），按币种分图；
观测点以折线连接，单条记录仅显示一个点，无报价显示空状态，邮件正文标记最新查询状态与时间。
邮件失败不影响价格保存，错误写入应用日志；当前不自动重试邮件。
修改后重新安装依赖并重启，Docker 使用 `docker compose up -d --build`。

## 人民币 / 日元汇率监控

执行 `alembic upgrade head` 并重启应用后，在「数据看板」查看人民币 / 日元汇率。
点击「立即获取汇率」保存首个观测点；之后按 `SCRAPE_DAILY_TIME` 和 `SCRAPE_TIMEZONE`
每天自动更新（默认北京时间 09:30），没有监控航线也会获取汇率。

数据来自 [Frankfurter](https://frankfurter.dev/) 的每日参考汇率 API，无需新增密钥。
显示 1 CNY 兑换的 JPY，以及 100 JPY 折合的 CNY；非银行实时买入/卖出价。
按来源报价日期保存，同一天重复获取会更新该日记录，周末沿用旧报价时不会生成虚假新点。
看板展示最近 90 个已采集报价日，区分报价日期与获取时间。获取失败保留历史数据。
汇率走势与航班信息合并到同一封每日邮件，沿用现有 EMAIL / SMTP 配置；阈值提醒尚未启用。

- `GET /api/exchange-rates?limit=90`：最新汇率与历史，limit 范围 1–1000。
- `POST /api/exchange-rates/fetch`：手动获取并保存汇率。

以上接口均需要登录，数据由登录用户共享。

每日邮件同时包含人民币 / 日元最近 90 天已采集报价的正文内嵌走势图、双向换算、来源报价日期和最近获取时间。
本轮汇率获取失败会明确提示并展示已有历史；无数据时显示空状态。即使未配置航线，也会发送汇率日报。
邮件仍在当天全部采集结束后发送一次，不单独发送汇率邮件。
