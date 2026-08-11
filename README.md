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

编辑 `.env`，至少配置模型和 Tavily：

```
DATABASE_URL=mysql+pymysql://user:password@localhost/fly_anywhere
OPENAI_API_KEY=your_openai_api_key
AI_MODEL=gpt-4.1-mini
TAVILY_API_KEY=tvly-your_tavily_api_key
```

如果使用 OpenAI 兼容服务，可额外设置 `OPENAI_BASE_URL`。原有定时监控所需的 `API_KEY`、`API_SECRET` 等配置见 `.env.example`。

### 3. 启动服务

```bash
uvicorn app.main:app --reload
```

访问 `http://localhost:8000`

## 使用说明

在页面顶部用自然语言输入完整行程，例如：

```text
2026 年 9 月 10 日北京飞东京，1 人单程经济舱
```

AI 会搜索公开网页并展示可追溯的参考结果。输入越完整，结果越有意义。页面下方仍可使用原有航线监控与价格趋势功能。

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
