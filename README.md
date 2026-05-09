# 机票价格监控系统

追踪机票价格波动，找到最佳购票时机。

## 功能

- 支持指定固定航线，定时抓取价格
- 两种数据源：第三方 API（AviationStack / Amadeus）+ 爬虫
- MySQL 存储价格历史
- Web 页面展示价格波动图表（ECharts）
- 程序内定时循环抓取

## 快速开始

### 1. 安装依赖

```bash
cd fly-anywhere
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env` 填入你的数据库连接信息和 API Key：

```
DATABASE_URL=mysql+pymysql://user:password@localhost/dbname
API_KEY=your_api_key_here
SCRAPE_INTERVAL_HOURS=12
```

### 3. 启动服务

```bash
uvicorn app.main:app --reload
```

访问 `http://localhost:8000`

## 使用说明

1. 在页面输入出发/到达城市 IATA 代码（如 PEK、SHA）添加航线
2. 点击"添加"后，通过 API 手动触发首次抓取
3. 配置 `API_KEY` 后，定时器会自动按设定频率抓取
4. ECharts 图表展示价格波动趋势

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/routes/` | 航线列表 |
| POST | `/api/routes/` | 添加航线 |
| DELETE | `/api/routes/{id}` | 删除航线 |
| GET | `/api/prices/latest` | 最新价格 |
| GET | `/api/prices/{route_id}` | 价格历史 |
| POST | `/api/prices/fetch/{route_id}` | 手动触发抓取 |

## 技术栈

- Python 3.12
- FastAPI + Uvicorn
- SQLAlchemy + MySQL
- ECharts
- httpx + BeautifulSoup4
