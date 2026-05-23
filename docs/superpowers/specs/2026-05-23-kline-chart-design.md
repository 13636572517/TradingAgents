# K线图弹窗 Implementation Design

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在每份分析报告的右上角添加"K线图"按钮，点击后弹出全屏模态窗口，展示该股票的蜡烛图/折线图及基本技术分析指标。

**Architecture:** FastAPI 新增 `/api/kline/{ticker}` 端点，通过多层数据源降级链拉取 OHLCV 数据返回 JSON；前端使用 ECharts（via echarts-for-react）在全屏 Modal 中渲染图表，支持 K线/折线切换、时间范围选择、技术指标切换，以及分析基准日期标记线。

**Tech Stack:** Python / FastAPI / AkShare / BaoStock / JoinQuant / yfinance（后端）；React / TypeScript / ECharts / echarts-for-react / Tailwind CSS（前端）

---

## 1. 文件结构

### 新建文件

| 文件 | 职责 |
|------|------|
| `server/routes/kline.py` | FastAPI 路由：拉取 OHLCV 数据，多源降级，返回统一 JSON |
| `web/src/components/KLineModal.tsx` | 全屏 Modal 组件：ECharts 图表 + 控件 |
| `web/src/hooks/useKLineData.ts` | 数据拉取 hook：调用 `/api/kline`，管理 loading/error/cache |

### 修改文件

| 文件 | 修改内容 |
|------|---------|
| `server/app.py` | 注册 `kline` 路由（`app.include_router`） |
| `web/src/pages/Report.tsx` | 顶部状态栏添加"📈 K线图"按钮，控制 Modal 开关 |
| `web/package.json` | 新增 `echarts`、`echarts-for-react` 依赖 |

---

## 2. 后端 API

### 端点

```
GET /api/kline/{ticker}?range=1Y
```

**参数：**
- `ticker`：股票代码，如 `601985.SS`、`00700.HK`、`AAPL`
- `range`：时间范围，枚举值 `1M | 3M | 6M | 1Y | 2Y`，默认 `1Y`

**响应结构：**

```json
{
  "ticker": "601985.SS",
  "range": "1Y",
  "data": [
    {
      "date": "2025-01-02",
      "open": 7.50,
      "high": 7.65,
      "low": 7.45,
      "close": 7.60,
      "volume": 12345678
    }
  ],
  "error": null
}
```

当所有数据源均失败时：`data: []`，`error: "K线数据暂时不可用：<原因>"`。

### 数据源降级链

**A股（ticker 以 `.SS` 或 `.SZ` 结尾，含 ETF）：**

1. AkShare `stock_zh_a_hist`（东方财富，稳定性最佳）
2. BaoStock `query_history_k_data_plus`（已集成，日线完整）
3. JoinQuant `get_price`（已集成，注意数据截止日限制）
4. yfinance（带 `.SS`/`.SZ` 后缀，覆盖面有限）
5. 兜底：返回 `error` 字段，`data: []`

**港股（ticker 以 `.HK` 结尾）：**

1. AkShare `stock_hk_hist`
2. yfinance
3. 兜底：返回 `error`

**美股 / 其他：**

1. yfinance（覆盖最全）
2. AkShare `stock_us_hist`
3. 兜底：返回 `error`

### 日期范围计算

| range | 往前取 N 个自然日 |
|-------|----------------|
| 1M | 45 天 |
| 3M | 130 天 |
| 6M | 260 天 |
| 1Y | 375 天（默认） |
| 2Y | 750 天 |

返回数据按 `date` 升序排列，只含有实际交易日（周末/节假日自动跳过）。

### 缓存

响应头加 `Cache-Control: public, max-age=3600`（日线数据当天不变，缓存1小时即可）。后端无需持久化缓存，浏览器缓存已足够。

---

## 3. 前端组件

### KLineModal.tsx

**Props：**

```typescript
interface KLineModalProps {
  ticker: string       // 股票代码
  tradeDate: string    // 分析基准日期（yyyy-mm-dd），用于标记线
  decision?: string    // BUY / SELL / HOLD，展示在标题栏
  onClose: () => void
}
```

**内部状态：**

```typescript
type ChartType = 'candlestick' | 'line'
type TimeRange = '1M' | '3M' | '6M' | '1Y' | '2Y'
type SubIndicator = 'MACD' | 'KDJ' | 'RSI'

const [chartType, setChartType] = useState<ChartType>('candlestick')
const [range, setRange] = useState<TimeRange>('1Y')
const [subIndicator, setSubIndicator] = useState<SubIndicator>('MACD')
const [showBoll, setShowBoll] = useState(false)
```

**布局（从上到下）：**

```
┌─────────────────────────────────────────────────────────────────┐
│ [ticker] [公司名] [BUY]  [K线|折线]  [1M|3M|6M|1Y|2Y]          │
│                          [MACD|KDJ|RSI] [BOLL]  [✕]             │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  主图（60% 高度）                                                  │
│  ECharts 蜡烛图 or 折线图                                          │
│  + MA5(黄) / MA10(橙) / MA20(紫) / MA60(绿) 叠加均线              │
│  + 布林带上中下轨（showBoll=true 时叠加）                           │
│  + 黄色虚线标记 tradeDate                                          │
│                                                                   │
├─────────────────────────────────────────────────────────────────┤
│  成交量（15% 高度）                                                │
│  红跌绿涨柱状图                                                    │
├─────────────────────────────────────────────────────────────────┤
│  副图（25% 高度）                                                  │
│  MACD: DIF线 + DEA线 + 能量柱                                     │
│  KDJ: K线 + D线 + J线                                             │
│  RSI: RSI6 + RSI12 + RSI24                                        │
└─────────────────────────────────────────────────────────────────┘
```

**三图联动：** 使用 ECharts `dataZoom` 组件同步，`axisPointer` 共享十字准线。

**加载状态：** 显示骨架屏（三个灰色矩形块对应三图区域）。

**错误状态：** 显示居中提示"暂无K线数据：\<error message\>"，不崩溃弹窗。

### useKLineData.ts

```typescript
function useKLineData(ticker: string, range: TimeRange) {
  // 返回 { data, loading, error }
  // 内部用 Map<`${ticker}-${range}`, data> 做内存缓存
  // 切换 range 时优先从缓存取，缓存命中则无需重新请求
}
```

### Report.tsx 改动

在 `AnalysisWorkspace` 顶部状态栏（`bg-surface` div）右侧，紧邻"停止分析"按钮位置添加：

```tsx
{/* K线图按钮 — 始终显示（运行中和完成后均可查看） */}
<button
  onClick={() => setShowKLine(true)}
  className="shrink-0 text-xs px-3 py-1 rounded border border-accent/40
             text-accent hover:bg-accent/10 transition-colors"
>
  📈 K线图
</button>
{showKLine && (
  <KLineModal
    ticker={analysis.ticker}
    tradeDate={analysis.trade_date}
    decision={analysis.decision}
    onClose={() => setShowKLine(false)}
  />
)}
```

---

## 4. 错误处理与边界情况

| 情况 | 处理方式 |
|------|---------|
| 所有数据源超时/失败 | 返回 `{data:[], error:"..."}` → 前端显示友好提示 |
| 股票代码无效/退市 | 同上 |
| 分析日期早于数据范围 | `tradeDate` 标记线仍渲染，只是落在图表左边界外，ECharts 自动忽略越界标记 |
| ETF | A股链路正常支持（AkShare 有 `fund_etf_hist_em` 专属接口） |
| 网络慢时切换 range | useKLineData 取消上一个未完成的请求（AbortController） |
| 弹窗打开时 ESC 键 | 监听 `keydown` 事件关闭弹窗 |

---

## 5. 不在本次范围内

- 画线工具（趋势线、支撑阻力线）
- 实时行情（实时 tick 推送）
- 分时图（当日分钟线）
- 多股对比
- 图表截图/导出
