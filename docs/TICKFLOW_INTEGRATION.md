# TickFlow 数据源集成文档

> **创建时间**：2025-06-12
> **相关 Commit**：`cd6a533`, `82e21b4`, `b00d34c`, `b75cff1`

---

## 一、背景与动机

### 1.1 原有问题

生产环境选股漏斗（`sector_data.py`）使用 **East Money 直连** 作为主要数据源获取全市场行情快照。但在阿里云生产服务器上，East Money 对服务器 IP 进行了限流，导致 `stock_zh_a_spot_em` 接口不可用。

后续尝试引入 TickFlow 作为替代数据源，但遭遇了两个关键问题：

| 问题 | 现象 | 日志 |
|------|------|------|
| **批量接口限制** | TickFlow `POST /v1/quotes` 的 `symbols` 参数每批最多 **5 个标的**（非预期的 100） | `标的数量超限: 100 (最大: 5)` |
| **立即触发限流** | 5,526 只 A 股 ÷ 5 = ~1,106 次请求 → 前 10 批成功，之后全部 HTTP 429 | `TickFlow rate limited (HTTP 429)` |
| **错误信息误导** | 失败后显示 `全市场行情快照获取失败 (akshare stock_zh_a_spot_em)`，实际是 TickFlow 失败 | — |
| **无进度可见** | 选股过程黑盒运行，前端无任何反馈 | — |
| **Celery Key 缺失** | TickFlow API Key 只在 `main.py` startup 注入 server 进程，Celery worker 看不到 | `TICKFLOW_API_KEY not set` |

### 1.2 最终方案

改用 TickFlow 的 **标的池（universe）批量行情** 接口，通过 `POST /v1/quotes` 传入 `universes=["CN_Equity_A"]` 参数，**一次性获取整个 A 股市场快照**，仅需 **1 次请求**。

---

## 二、TickFlow API 能力总结

### 2.1 核心端点

| 端点 | 方法 | 用途 | 限制 |
|------|------|------|------|
| `/v1/klines` | GET | 单标的 K 线（日线/分钟线/周月年线） | — |
| `/v1/klines/batch` | GET | 批量 K 线（逗号分隔 symbols） | — |
| `/v1/quotes` | POST | 实时行情快照 | **symbols 最多 5 个**；**universes 无限制** |
| `/v1/universes` | GET | 获取标的池列表 | — |
| `/v1/universes/{id}` | GET | 获取标的池详情（含 symbol 列表） | — |
| `/v1/instruments` | POST | 批量标的元数据（名称、交易所、股本等） | — |
| `/v1/financials/metrics` | GET | 核心财务指标（ROE、EPS、毛利率等） | — |
| `/v1/financials/income` | GET | 利润表 | — |
| `/v1/financials/balance-sheet` | GET | 资产负债表 | — |
| `/v1/financials/cash-flow` | GET | 现金流量表 | — |

### 2.2 认证与限流

- **认证**：每个请求携带 `x-api-key` Header
- **限流**：依赖 API Key 配置，超限返回 `429 Too Many Requests`
- **标的数量限制**：
  - `symbols` 参数：每批最多 **5 个**
  - `universes` 参数：可传入整个标的池 ID，一次性获取池中所有标的行情

### 2.3 Ticker 格式

| 市场 | 代码格式 | 示例 |
|------|---------|------|
| 沪市 A 股 | `{6位代码}.SH` | `600519.SH` |
| 深市 A 股 | `{6位代码}.SZ` | `000001.SZ` |
| 港股 | `{5位代码}.HK` | `00700.HK` |
| 美股 | `{代码}.US` | `AAPL.US` |

### 2.4 实时行情响应结构

```json
{
  "data": [
    {
      "symbol": "600000.SH",
      "region": "CN",
      "last_price": 10.50,
      "prev_close": 10.40,
      "open": 10.42,
      "high": 10.55,
      "low": 10.40,
      "volume": 1000000,
      "amount": 10450000.00,
      "timestamp": 1715664000000,
      "session": "regular",
      "ext": {
        "type": "cn_equity",
        "name": "浦发银行",
        "change_pct": 0.0096,
        "change_amount": 0.10,
        "amplitude": 0.0144,
        "turnover_rate": 0.005
      }
    }
  ]
}
```

---

## 三、代码变更详情

### 3.1 `tradingagents/dataflows/tickflow_data.py`

**新增函数**：`tf_universe_quotes(universe_ids: list[str]) -> dict`

- 通过 `POST /v1/quotes` 传入 `universes` 参数，一次性获取整个标的池的实时行情
- 返回格式与 `tf_batch_quotes` 一致，key 为 6 位代码（如 `"600519"`）
- **这是解决 1,106 次请求 → 1 次请求问题的核心函数**

**修复函数**：`tf_batch_quotes(symbols)`

- 更新 docstring 明确标注：TickFlow 限制 `symbols` 每批最多 5 个
- 引导使用者对全市场快照改用 `tf_universe_quotes`

**新增别名**：`test_tickflow_connection = test_tf_connection`

- 兼容 `server/routers/settings.py` 的导入名

### 3.2 `tradingagents/dataflows/sector_data.py`

**重写 `_spot_tickflow()`**：

```python
# 之前：获取 symbol 列表 → 分 56 页 × 100 个 → 56 次 POST 请求 → 全部 429 限流
# 现在：直接 POST /v1/quotes with universes=["CN_Equity_A"] → 1 次请求

def _spot_tickflow() -> dict:
    from tradingagents.dataflows.tickflow_data import tf_universe_quotes
    logger.info("_spot_tickflow: fetching CN_Equity_A universe via single request…")
    out = tf_universe_quotes(["CN_Equity_A"])
    if out:
        logger.info("_spot_tickflow: %d symbols fetched", len(out))
    return out
```

**清理**：移除了不再使用的 `math`、`random`、`time` 导入以及 `_BATCH_SIZE` 常量。

### 3.3 `tradingagents/dataflows/interface.py`

**将 TickFlow 加入 VENDOR_METHODS 降级链**：

| 方法 | 降级链 |
|------|--------|
| `get_stock_data` | mairui → baostock → **tickflow** → joinquant → akshare → futu → yfinance |
| `get_indicators` | mairui → baostock → **tickflow** → joinquant → akshare → yfinance |
| `get_fundamentals` | mairui → **tickflow** → joinquant → baostock → akshare → futu → yfinance |
| `get_balance_sheet` | **tickflow** → joinquant → baostock → akshare → futu → yfinance |
| `get_cashflow` | **tickflow** → joinquant → baostock → akshare → futu → yfinance |
| `get_income_statement` | **tickflow** → joinquant → baostock → akshare → futu → yfinance |

### 3.4 `server/celery_app.py`

**新增 `_hydrate_db_keys()`**：

- Celery worker 独立于 uvicorn server 进程，不会触发 `main.py` 的 startup 事件
- 在 `celery_app.py` 模块级调用，自动从 DB 读取 `tickflow_api_key` 并注入 `TICKFLOW_API_KEY` 环境变量
- 确保选股 Celery 任务能认证 TickFlow API

### 3.5 `server/screener.py`

**修复误导性错误信息**：
```python
# 之前
raise RuntimeError("全市场行情快照获取失败 (akshare stock_zh_a_spot_em)")

# 现在
raise RuntimeError(
    "全市场行情快照获取失败 — TickFlow / AkShare / JoinQuant 均不可用。"
    "请确认 TickFlow API Key 已配置且可连通。"
)
```

**新增 `progress` 回调参数**：

```python
def run_screening(db, params=None, progress=None):
    def _p(msg):
        if progress: progress(msg)
        logger.info("[screener] %s", msg)

    _p("Step 1/5 — 获取全市场行情快照…")
    spot = sd.get_market_spot()
    _p(f"Step 1/5 — 行情快照获取完成（{len(spot)} 只股票）")
    # ... 后续步骤同理
```

### 3.6 `server/tasks.py`

**`run_screening_task` 新增进度写入**：

```python
def _progress(msg: str):
    """写入进度消息到 DB，前端可通过 GET /screener/runs/{id} 轮询查看。"""
    run.error = msg
    db.commit()
    logger.info("[screening %s] %s", run_id, msg)

_progress("正在获取全市场行情快照（TickFlow → AkShare → JoinQuant）…")
result = run_screening(db, params=run.params, progress=_progress)
_progress(f"筛选完成！{undervalued_count} 个低估板块，{candidate_count} 只候选股")
```

---

## 四、架构对比

### 4.1 修改前

```
sector_data.py
├── get_industry_boards()   → East Money 直连 (HTTP clist API)
├── get_board_constituents() → East Money 直连 (HTTP clist API)
└── get_market_spot()       → East Money 直连 (59 次分页 → 限流)
                               ↓ 失败
                             → AkShare (stock_zh_a_spot_em → 生产 IP 限流)
                               ↓ 失败
                             → JoinQuant (兜底，但免费额度仅 500 次/天)
```

### 4.2 修改后

```
sector_data.py
├── get_industry_boards()   → TickFlow /v1/universes → AkShare (备)
├── get_board_constituents() → TickFlow /v1/universes/{id} → AkShare (备)
└── get_market_spot()       → TickFlow POST /v1/quotes (universes)
                               │  1 次请求获取全市场 ~5,500 只行情
                               ↓ 失败（极少发生）
                             → AkShare (备)
                               ↓ 失败
                             → JoinQuant (备)

interface.py (LLM Agent 数据路由)
├── get_stock_data         → mairui → baostock → tickflow → joinquant → ...
├── get_fundamentals       → mairui → tickflow → joinquant → ...
└── get_balance_sheet      → tickflow → joinquant → ...
```

---

## 五、设置页 UI

设置页已包含 TickFlow 面板（位于聚宽、富途面板下方）：

- **API Key 输入**：可显隐、可覆盖
- **保存**：写入 DB + 注入进程环境变量
- **测试连通性**：调用 `GET /v1/universes` 验证 Key 有效性
- **状态反馈**：显示延迟、标的池数量、错误信息

---

## 六、生产环境配置

### 6.1 已部署服务

| 服务 | 状态 | 说明 |
|------|------|------|
| TickFlow API | ✅ 已配置 Key | 通过设置页保存 |
| Celery Worker | ✅ 自动注入 Key | `celery_app.py` 启动时从 DB 加载 |
| Uvicorn Server | ✅ 自动注入 Key | `main.py` startup 从 DB 加载 |

### 6.2 .env 无需额外配置

TickFlow API Key 通过设置页保存到数据库，启动时自动注入 `TICKFLOW_API_KEY` 环境变量，无需手动修改 `.env`。

---

## 七、参考链接

- TickFlow 官方文档：<https://docs.tickflow.org/zh-Hans>
- TickFlow API Reference（OpenAPI）：<https://docs.tickflow.org/zh-Hans/api-reference/openapi.json>
- 标的池列表：<https://docs.tickflow.org/zh-hans/api-reference/标的池/获取标的池列表.md>
- 批量实时行情：<https://docs.tickflow.org/zh-hans/api-reference/实时行情/批量查询实时行情.md>
