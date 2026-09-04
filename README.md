# AI 机票搜索与价格监控

使用 LangChain Agent 调用 Tavily 搜索公开网页中的机票参考价格，同时保留原有的航线价格监控功能。

> Tavily 不是航班库存 API。AI 搜索结果可能是缓存价、起售价或促销价，只能作为参考；实际价格和余票以来源预订页面为准。

## 功能

- 使用自然语言描述行程，由 LangChain Agent 规划并执行 Tavily 联网搜索
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

每次 AI 查询都会记录到 `search_runs`，可确认的结构化结果记录到 `flight_offers`；未来的群消息投递状态由 `notification_deliveries` 保存。数据库结构统一通过 Alembic 迁移管理。

## 后续路线

- 机票数据源按 `SerpApi Google Flights → Amadeus Flight Offers → Tavily` 的优先级接入，并在主数据源额度耗尽或请求失败时自动降级。
- 微信公众号消息推送暂不在当前版本实现。后续将评估公众号类型与认证状态、用户关注与 OpenID 获取方式、模板消息/订阅通知权限、每日定时任务以及投递记录；微信接口限制最终以公众号后台当时开放的能力为准。

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/routes/` | 航线列表 |
| POST | `/api/routes/` | 添加航线 |
| DELETE | `/api/routes/{id}` | 删除航线 |
| GET | `/api/prices/latest` | 最新价格 |
| GET | `/api/prices/{route_id}` | 价格历史 |
| POST | `/api/prices/fetch/{route_id}` | 手动触发抓取 |
| POST | `/api/ai/search` | LangChain + Tavily 自然语言机票搜索 |

## 技术栈

- Python 3.12
- FastAPI + Uvicorn
- LangChain + LangGraph Agent runtime
- Tavily Search + OpenAI/兼容模型
- SQLAlchemy + MySQL
- ECharts
- httpx + BeautifulSoup4
