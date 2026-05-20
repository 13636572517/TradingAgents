# TradingAgents A股/港股 + Web UI 改造设计文档

**日期**：2026-05-20  
**范围**：B 阶段（A股/港股数据接入）+ C 阶段（Web UI 团队工具）合并实施  
**部署策略**：本地 Docker Compose 先跑，成熟后迁移至阿里云 ECS + MySQL

---

## 一、项目目标

将 TradingAgents 从美股命令行工具改造为：
1. **支持 A股（.SS/.SZ）和港股（.HK）**的多 Agent 投研分析
2. **面向非技术团队成员**的 Web UI，浏览器操作，无需命令行

---

## 二、整体架构

```
┌─────────────────────────────────────────────────────┐
│                   用户浏览器                          │
│              React (Vite) 前端                        │
│   侧边导航 | 新建分析 | 报告页 | 历史列表              │
└──────────────────┬──────────────────────────────────┘
                   │  REST API + SSE
┌──────────────────▼──────────────────────────────────┐
│              FastAPI 后端 (server/)                   │
│   /api/analyses  /api/notifications  /api/stream      │
└──────┬──────────────────────────┬────────────────────┘
       │  SQLAlchemy               │  Celery 任务
┌──────▼──────────┐    ┌──────────▼──────────────────┐
│  SQLite (本地)   │    │  Celery Worker               │
│  MySQL  (ECS)   │    │  TradingAgentsGraph.propagate│
└─────────────────┘    └──────────────────────────────┘
                                   │
                        ┌──────────▼──────────┐
                        │  Redis (任务队列)     │
                        └─────────────────────┘
```

### 目录结构

```
TradingAgents/
├── tradingagents/              ← B 阶段：AkShare、情绪、路由
├── server/                     ← 新建：FastAPI 后端
│   ├── main.py
│   ├── models.py
│   ├── database.py
│   ├── routers/
│   │   ├── analyses.py
│   │   └── notifications.py
│   ├── tasks.py                ← Celery 任务
│   └── events.py               ← SSE 进度推送
├── web/                        ← 新建：React 前端
│   ├── src/
│   │   ├── pages/
│   │   ├── components/
│   │   └── api/
│   ├── package.json
│   └── vite.config.ts
├── docker-compose.yml          ← 扩展：server + web + celery + redis
└── .env.example
```

---

## 三、B 阶段：A股/港股数据改造

### 3.1 新增/修改文件

| 优先级 | 类型 | 文件 | 说明 |
|---|---|---|---|
| 高 | 新建 | `tradingagents/dataflows/akshare_data.py` | AkShare 数据层（完整实现见 CN_MARKET_ADAPTATION.md） |
| 高 | 修改 | `tradingagents/dataflows/interface.py` | 注册 akshare vendor；ticker 后缀自动路由 |
| 高 | 修改 | `tradingagents/default_config.py` | 补 A股 benchmark（.SS → 000001.SS，.SZ → 399001.SZ）；加 market_vendor_overrides |
| 高 | 修改 | `tradingagents/agents/analysts/sentiment_analyst.py` | A股/港股用东方财富替代 Reddit/StockTwits |
| 中 | 修改 | `tradingagents/agents/utils/agent_utils.py` | build_instrument_context 增加 A股/港股市场规则 |
| 中 | 修改 | `tradingagents/graph/trading_graph.py` | propagate() 写 current_ticker 到 config |
| 低 | 修改 | `cli/utils.py` | ticker 示例加入 A股/港股 |
| 低 | 修改 | `pyproject.toml` | 添加 akshare>=1.9.0 |

### 3.2 Ticker 格式约定

统一使用 Yahoo Finance 格式：
- A股上海：`600519.SS`（贵州茅台）
- A股深圳：`000001.SZ`（平安银行）
- 港股：`0700.HK`（腾讯）

### 3.3 数据路由规则

- `.SS` / `.SZ` 后缀 → 自动路由到 AkShare
- `.HK` 后缀 → 继续使用 yfinance（覆盖良好）
- 其他 → 原有 yfinance/alpha_vantage 路径，零改动

### 3.4 设计约束

- 美股逻辑零改动，所有改动通过 vendor 路由隔离
- AkShare 是可选依赖，未安装时抛 AkShareError，fallback 到 yfinance
- 情绪分析保持单次 LLM 调用架构

---

## 四、C 阶段：Web UI

### 4.1 数据库模型

```python
# server/models.py
class Analysis(Base):
    __tablename__ = "analyses"

    id           = Column(String(36), primary_key=True, default=uuid4)
    ticker       = Column(String(20), nullable=False)      # e.g. 600519.SS
    ticker_name  = Column(String(100))                     # e.g. 贵州茅台（前端展示用）
    trade_date   = Column(String(10), nullable=False)      # YYYY-MM-DD
    analysts     = Column(JSON, nullable=False)            # ["fundamentals","sentiment","news","market"]
    depth        = Column(Integer, default=1)              # 1=快速 2=标准 3=深度
    status       = Column(String(20), default="pending")   # pending|running|complete|failed
    stage        = Column(String(30))                      # analysts|debate|risk|decision
    result       = Column(JSON)                            # 完整报告各 section
    decision     = Column(String(10))                      # BUY|HOLD|SELL
    error        = Column(Text)
    created_at   = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime)
    seen         = Column(Boolean, default=False)          # 站内通知已读标记
```

### 4.2 API 端点

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/analyses` | 提交新分析任务 |
| GET | `/api/analyses` | 列出所有分析（支持分页） |
| GET | `/api/analyses/{id}` | 获取单个分析详情 |
| DELETE | `/api/analyses/{id}` | 删除分析记录 |
| GET | `/api/analyses/{id}/stream` | SSE 实时进度流 |
| GET | `/api/notifications/count` | 未读通知数 |
| POST | `/api/notifications/read` | 标记全部已读 |

### 4.3 Celery 任务设计

```python
# server/tasks.py
@celery_app.task(bind=True)
def run_analysis(self, analysis_id: str):
    # 1. 更新 status=running
    # 2. 注入进度回调到 TradingAgentsGraph（通过 LangGraph callbacks）
    #    每个大阶段完成时更新 Analysis.stage：
    #    analysts → debate → risk → decision
    # 3. 调用 ta.propagate(ticker, trade_date)
    # 4. 解析结果，写入 Analysis.result + Analysis.decision
    # 5. 更新 status=complete，seen=False（触发通知角标）
```

进度回调通过 LangGraph 的 `on_chain_end` hook 实现，在现有 `AnalystWallTimeTracker` 基础上扩展，写入 Redis key，SSE endpoint 轮询 Redis 推送给前端。

### 4.4 SSE 进度推送

```
GET /api/analyses/{id}/stream

data: {"stage": "analysts", "detail": "基本面分析师运行中", "progress": 25}
data: {"stage": "debate",   "detail": "多空辩论进行中",     "progress": 60}
data: {"stage": "risk",     "detail": "风险评估",           "progress": 80}
data: {"stage": "decision", "detail": "最终决策",           "progress": 95}
data: {"stage": "complete", "decision": "BUY",              "progress": 100}
```

### 4.5 前端页面结构

```
web/src/
├── pages/
│   ├── NewAnalysis.tsx      ← 表单：ticker + date + 分析师 checkboxes + depth
│   ├── History.tsx          ← 历史列表，卡片展示每条分析
│   ├── Report.tsx           ← Banner(BUY/HOLD/SELL) + Tabs(各章节)
│   └── Settings.tsx         ← LLM provider/model 配置（管理员用）
├── components/
│   ├── Sidebar.tsx          ← 固定侧边导航 + 通知角标
│   ├── ProgressTimeline.tsx ← 四阶段时间轴
│   ├── ReportBanner.tsx     ← 顶部 BUY/HOLD/SELL 固定条
│   ├── ReportTabs.tsx       ← Tab 切换各分析师报告
│   ├── AnalystSelector.tsx  ← 分析师 checkbox 组
│   └── TickerInput.tsx      ← 输入框 + 实时股票名称识别
└── api/
    └── client.ts            ← Axios 封装，所有 API 调用
```

### 4.6 UI 设计决策（已确认）

| 页面 | 设计决策 |
|---|---|
| 整体布局 | 侧边图标导航（类 GitHub 风格） |
| 新建分析表单 | 完整版：ticker + date + 4个分析师开关 + 研究深度（快速/标准/深度） |
| 报告阅读页 | 顶部固定 Banner（BUY/HOLD/SELL + 置信度）+ Tab 切换各章节 |
| 进度等待页 | 四阶段时间轴（分析师→辩论→风控→决策） |
| 完成通知 | 站内角标（侧边栏红点），用户回到页面看到 |

---

## 五、部署

### 5.1 本地 Docker Compose

```yaml
# docker-compose.yml 新增 services
services:
  redis:         # 已有或新增
  server:        # FastAPI，port 8000
  celery:        # Celery worker，同 server 镜像，不同 CMD
  web:           # React 构建产物，Nginx 静态托管，port 3000
                 # 或开发模式下 vite dev server，port 5173
```

本地访问：`http://localhost:3000`

### 5.2 本地 → ECS 迁移

仅需修改 `.env`，代码零改动：

```bash
# 本地
DATABASE_URL=sqlite:///./tradingagents.db
REDIS_URL=redis://localhost:6379/0

# ECS
DATABASE_URL=mysql+pymysql://user:pass@localhost/tradingagents
REDIS_URL=redis://localhost:6379/0
```

ECS 上若已有其他应用占用 80 端口，加 Nginx 反向代理：
- `/` → 现有应用
- `/invest/` 或子域名 → TradingAgents Web UI

---

## 六、实施顺序

### 阶段 1：B 阶段数据改造（约 2-3 天）

按 `CN_MARKET_ADAPTATION.md` 顺序执行：
1. `akshare_data.py`（新建）
2. `interface.py`（vendor 路由）
3. `default_config.py`（benchmark + overrides）
4. `trading_graph.py`（current_ticker）
5. `sentiment_analyst.py`（CN 分支）
6. `agent_utils.py`（market context）
7. `cli/utils.py` + `pyproject.toml`

验证：`python -c "from tradingagents.graph.trading_graph import TradingAgentsGraph; ..."`

### 阶段 2：后端 API（约 3-4 天）

1. `server/database.py` + `server/models.py`
2. `server/tasks.py`（Celery task，先不接进度回调）
3. `server/routers/analyses.py`（CRUD endpoints）
4. `server/events.py`（SSE stream）
5. `server/main.py`（组装 app）
6. `docker-compose.yml` 扩展

### 阶段 3：前端（约 4-5 天）

1. Vite + React 脚手架，`web/` 目录
2. 侧边导航 + 路由（react-router）
3. 新建分析表单页
4. 历史列表页
5. 进度时间轴页（SSE 接入）
6. 报告阅读页（Banner + Tabs + Markdown 渲染）
7. 通知角标

### 阶段 4：集成测试 + Docker 打包（约 1-2 天）

1. 端到端测试：提交 600519.SS → 等待完成 → 查看报告
2. Docker Compose 本地跑全套
3. `.env.example` 文档
