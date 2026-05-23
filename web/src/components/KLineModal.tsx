// web/src/components/KLineModal.tsx
import { useEffect, useMemo, useState } from "react"
import ReactECharts from "echarts-for-react"
import { useKLineData } from "../hooks/useKLineData"
import type { KLineBar } from "../types"
import type { TimeRange } from "../hooks/useKLineData"

type ChartType    = "candlestick" | "line"
type SubIndicator = "MACD" | "KDJ" | "RSI"

// ── Indicator math ─────────────────────────────────────────────────────────────

function calcMA(closes: number[], n: number): (number | "-")[] {
  return closes.map((_, i) => {
    if (i < n - 1) return "-"
    const sum = closes.slice(i - n + 1, i + 1).reduce((a, b) => a + b, 0)
    return +(sum / n).toFixed(4)
  })
}

function calcEMA(vals: number[], n: number): number[] {
  const k = 2 / (n + 1)
  return vals.reduce<number[]>((acc, v, i) => {
    acc.push(i === 0 ? v : v * k + acc[i - 1] * (1 - k))
    return acc
  }, [])
}

function calcMACD(closes: number[]) {
  const emaFast = calcEMA(closes, 12)
  const emaSlow = calcEMA(closes, 26)
  const dif = emaFast.map((v, i) => +(v - emaSlow[i]).toFixed(4))
  const dea = calcEMA(dif, 9).map((v) => +v.toFixed(4))
  const hist = dif.map((v, i) => +((v - dea[i]) * 2).toFixed(4))
  return { dif, dea, hist }
}

function calcKDJ(highs: number[], lows: number[], closes: number[]) {
  const k: number[] = [], d: number[] = [], j: number[] = []
  closes.forEach((c, i) => {
    const hh = Math.max(...highs.slice(Math.max(0, i - 8), i + 1))
    const ll = Math.min(...lows.slice(Math.max(0, i - 8), i + 1))
    const rsv = hh === ll ? 50 : ((c - ll) / (hh - ll)) * 100
    const pk = k[i - 1] ?? 50
    const pd = d[i - 1] ?? 50
    const ki = +(pk * (2 / 3) + rsv * (1 / 3)).toFixed(2)
    const di = +(pd * (2 / 3) + ki * (1 / 3)).toFixed(2)
    k.push(ki); d.push(di); j.push(+(3 * ki - 2 * di).toFixed(2))
  })
  return { k, d, j }
}

function calcRSI(closes: number[], n: number): (number | "-")[] {
  const out: (number | "-")[] = Array(n - 1).fill("-")
  for (let i = n - 1; i < closes.length; i++) {
    let gains = 0, losses = 0
    for (let s = i - n + 2; s <= i; s++) {
      const diff = closes[s] - closes[s - 1]
      if (diff > 0) gains += diff; else losses -= diff
    }
    const rs = losses === 0 ? Infinity : gains / losses
    out.push(+(100 - 100 / (1 + rs)).toFixed(2))
  }
  return out
}

function calcBoll(closes: number[], n = 20, mult = 2) {
  const upper: (number | "-")[] = []
  const mid: (number | "-")[] = []
  const lower: (number | "-")[] = []
  closes.forEach((_, i) => {
    if (i < n - 1) { upper.push("-"); mid.push("-"); lower.push("-"); return }
    const sl = closes.slice(i - n + 1, i + 1)
    const ma = sl.reduce((a, b) => a + b, 0) / n
    const std = Math.sqrt(sl.reduce((a, b) => a + (b - ma) ** 2, 0) / n)
    upper.push(+(ma + mult * std).toFixed(4))
    mid.push(+ma.toFixed(4))
    lower.push(+(ma - mult * std).toFixed(4))
  })
  return { upper, mid, lower }
}

// ── ECharts option builder ─────────────────────────────────────────────────────

function buildOption(
  data: KLineBar[],
  chartType: ChartType,
  subIndicator: SubIndicator,
  showBoll: boolean,
  tradeDate: string,
) {
  const dates  = data.map((d) => d.date)
  const opens  = data.map((d) => d.open)
  const highs  = data.map((d) => d.high)
  const lows   = data.map((d) => d.low)
  const closes = data.map((d) => d.close)
  const vols   = data.map((d) => d.volume)

  // Candlestick format: [open, close, low, high]
  const candleData = data.map((d) => [d.open, d.close, d.low, d.high])

  const ma5  = calcMA(closes, 5)
  const ma10 = calcMA(closes, 10)
  const ma20 = calcMA(closes, 20)
  const ma60 = calcMA(closes, 60)

  const boll = showBoll ? calcBoll(closes) : null

  let subSeries: object[] = []
  if (subIndicator === "MACD") {
    const { dif, dea, hist } = calcMACD(closes)
    subSeries = [
      { name: "MACD", type: "bar", xAxisIndex: 2, yAxisIndex: 2, data: hist,
        itemStyle: { color: (p: any) => p.value >= 0 ? "#ef4444" : "#4ade80" } },
      { name: "DIF",  type: "line", xAxisIndex: 2, yAxisIndex: 2, data: dif,
        lineStyle: { color: "#4aaeff", width: 1 }, symbol: "none" },
      { name: "DEA",  type: "line", xAxisIndex: 2, yAxisIndex: 2, data: dea,
        lineStyle: { color: "#f97316", width: 1 }, symbol: "none" },
    ]
  } else if (subIndicator === "KDJ") {
    const { k, d, j } = calcKDJ(highs, lows, closes)
    subSeries = [
      { name: "K", type: "line", xAxisIndex: 2, yAxisIndex: 2, data: k,
        lineStyle: { color: "#4aaeff", width: 1 }, symbol: "none" },
      { name: "D", type: "line", xAxisIndex: 2, yAxisIndex: 2, data: d,
        lineStyle: { color: "#f97316", width: 1 }, symbol: "none" },
      { name: "J", type: "line", xAxisIndex: 2, yAxisIndex: 2, data: j,
        lineStyle: { color: "#a78bfa", width: 1 }, symbol: "none" },
    ]
  } else {
    // RSI
    subSeries = [
      { name: "RSI6",  type: "line", xAxisIndex: 2, yAxisIndex: 2, data: calcRSI(closes, 6),
        lineStyle: { color: "#4aaeff", width: 1 }, symbol: "none" },
      { name: "RSI12", type: "line", xAxisIndex: 2, yAxisIndex: 2, data: calcRSI(closes, 12),
        lineStyle: { color: "#f97316", width: 1 }, symbol: "none" },
      { name: "RSI24", type: "line", xAxisIndex: 2, yAxisIndex: 2, data: calcRSI(closes, 24),
        lineStyle: { color: "#a78bfa", width: 1 }, symbol: "none" },
    ]
  }

  const markLine = {
    symbol: "none",
    data: [{ xAxis: tradeDate }],
    lineStyle: { color: "#facc15", type: "dashed", width: 1.5 },
    label: { formatter: "分析日", color: "#facc15", position: "insideStartTop", fontSize: 10 },
  }

  const mainSeries = chartType === "candlestick"
    ? {
        name: "K线", type: "candlestick", xAxisIndex: 0, yAxisIndex: 0, data: candleData,
        itemStyle: { color: "#ef4444", color0: "#4ade80", borderColor: "#ef4444", borderColor0: "#4ade80" },
        markLine,
      }
    : {
        name: "收盘价", type: "line", xAxisIndex: 0, yAxisIndex: 0, data: closes,
        lineStyle: { color: "#4aaeff", width: 1.5 }, symbol: "none",
        markLine,
      }

  const bollSeries = boll
    ? [
        { name: "BOLL上", type: "line", xAxisIndex: 0, yAxisIndex: 0, data: boll.upper,
          lineStyle: { color: "#888", width: 1 }, symbol: "none" },
        { name: "BOLL中", type: "line", xAxisIndex: 0, yAxisIndex: 0, data: boll.mid,
          lineStyle: { color: "#aaa", width: 1, type: "dashed" }, symbol: "none" },
        { name: "BOLL下", type: "line", xAxisIndex: 0, yAxisIndex: 0, data: boll.lower,
          lineStyle: { color: "#888", width: 1 }, symbol: "none" },
      ]
    : []

  const axisStyle = {
    axisLine: { lineStyle: { color: "#2a2a3a" } },
    splitLine: { lineStyle: { color: "#1e1e2e" } },
    axisLabel: { color: "#666", fontSize: 10 },
  }

  return {
    backgroundColor: "#0d0d17",
    animation: false,
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "cross" },
      backgroundColor: "#1e1e2e",
      borderColor: "#2a2a3a",
      textStyle: { color: "#ccc", fontSize: 11 },
    },
    axisPointer: { link: [{ xAxisIndex: "all" }] },
    legend: {
      top: 4, left: "center",
      data: ["MA5", "MA10", "MA20", "MA60"],
      textStyle: { color: "#888", fontSize: 10 },
      itemWidth: 12, itemHeight: 8,
    },
    grid: [
      { left: "6%", right: "1%", top: "6%",  height: "55%" },
      { left: "6%", right: "1%", top: "64%", height: "10%" },
      { left: "6%", right: "1%", top: "77%", height: "18%" },
    ],
    xAxis: [
      { type: "category", data: dates, gridIndex: 0, ...axisStyle, axisLabel: { show: false } },
      { type: "category", data: dates, gridIndex: 1, ...axisStyle, axisLabel: { show: false } },
      { type: "category", data: dates, gridIndex: 2, ...axisStyle },
    ],
    yAxis: [
      { gridIndex: 0, scale: true, ...axisStyle },
      { gridIndex: 1, ...axisStyle },
      { gridIndex: 2, scale: true, ...axisStyle },
    ],
    dataZoom: [
      { type: "inside", xAxisIndex: [0, 1, 2], start: 50, end: 100 },
      {
        type: "slider", xAxisIndex: [0, 1, 2], bottom: 4, height: 16,
        borderColor: "#2a2a3a", textStyle: { color: "#555" },
        fillerColor: "rgba(74,172,255,0.08)", handleStyle: { color: "#4aaeff" },
      },
    ],
    series: [
      mainSeries,
      ...bollSeries,
      { name: "MA5",  type: "line", xAxisIndex: 0, yAxisIndex: 0, data: ma5,
        lineStyle: { color: "#facc15", width: 1 }, symbol: "none" },
      { name: "MA10", type: "line", xAxisIndex: 0, yAxisIndex: 0, data: ma10,
        lineStyle: { color: "#f97316", width: 1 }, symbol: "none" },
      { name: "MA20", type: "line", xAxisIndex: 0, yAxisIndex: 0, data: ma20,
        lineStyle: { color: "#a78bfa", width: 1 }, symbol: "none" },
      { name: "MA60", type: "line", xAxisIndex: 0, yAxisIndex: 0, data: ma60,
        lineStyle: { color: "#34d399", width: 1 }, symbol: "none" },
      {
        name: "成交量", type: "bar", xAxisIndex: 1, yAxisIndex: 1, data: vols,
        itemStyle: {
          color: (p: any) => {
            const bar = data[p.dataIndex]
            return bar.close >= bar.open ? "#ef4444" : "#4ade80"
          },
        },
      },
      ...subSeries,
    ],
  }
}

// ── Skeleton loader ────────────────────────────────────────────────────────────

function ChartSkeleton() {
  return (
    <div className="flex-1 flex flex-col gap-2 p-4 animate-pulse">
      <div className="bg-white/5 rounded h-[58%]" />
      <div className="bg-white/5 rounded h-[12%]" />
      <div className="bg-white/5 rounded h-[20%]" />
    </div>
  )
}

// ── Main component ─────────────────────────────────────────────────────────────

interface KLineModalProps {
  ticker: string
  tradeDate: string
  decision?: string | null
  onClose: () => void
}

const RANGES: TimeRange[] = ["1M", "3M", "6M", "1Y", "2Y"]
const SUB_INDICATORS: SubIndicator[] = ["MACD", "KDJ", "RSI"]

export function KLineModal({ ticker, tradeDate, decision, onClose }: KLineModalProps) {
  const [chartType, setChartType] = useState<ChartType>("candlestick")
  const [range, setRange]         = useState<TimeRange>("1Y")
  const [subInd, setSubInd]       = useState<SubIndicator>("MACD")
  const [showBoll, setShowBoll]   = useState(false)

  const { data, loading, error } = useKLineData(ticker, range)

  // ESC to close
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose() }
    window.addEventListener("keydown", handler)
    return () => window.removeEventListener("keydown", handler)
  }, [onClose])

  const option = useMemo(
    () => (data.length > 0 ? buildOption(data, chartType, subInd, showBoll, tradeDate) : null),
    [data, chartType, subInd, showBoll, tradeDate],
  )

  const decisionColors: Record<string, string> = {
    BUY:  "text-green-400 bg-green-400/10 border-green-400/30",
    SELL: "text-red-400 bg-red-400/10 border-red-400/30",
    HOLD: "text-yellow-400 bg-yellow-400/10 border-yellow-400/30",
  }

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-[#0d0d17]">
      {/* ── Header ── */}
      <div className="bg-[#111827] border-b border-[#2a2a3a] px-4 py-2 flex flex-wrap items-center gap-2 shrink-0">
        {/* Left: ticker + decision */}
        <span className="font-bold text-white text-sm">{ticker}</span>
        {decision && (
          <span className={`text-xs font-semibold px-2 py-0.5 rounded border ${decisionColors[decision] ?? ""}`}>
            {decision}
          </span>
        )}

        {/* Chart type toggle */}
        <div className="flex rounded overflow-hidden border border-[#2a2a3a] ml-2">
          {(["candlestick", "line"] as ChartType[]).map((ct) => (
            <button
              key={ct}
              onClick={() => setChartType(ct)}
              className={`text-xs px-2.5 py-1 transition-colors ${
                chartType === ct ? "bg-accent/20 text-accent" : "text-gray-500 hover:text-gray-300"
              }`}
            >
              {ct === "candlestick" ? "K线" : "折线"}
            </button>
          ))}
        </div>

        {/* Time range tabs */}
        <div className="flex gap-1">
          {RANGES.map((r) => (
            <button
              key={r}
              onClick={() => setRange(r)}
              className={`text-xs px-2.5 py-1 rounded transition-colors ${
                range === r
                  ? "bg-accent/20 text-accent border border-accent/30"
                  : "text-gray-500 hover:text-gray-300 border border-transparent"
              }`}
            >
              {r}
            </button>
          ))}
        </div>

        {/* Sub-indicator + BOLL toggle */}
        <div className="flex gap-1 ml-auto">
          {SUB_INDICATORS.map((s) => (
            <button
              key={s}
              onClick={() => setSubInd(s)}
              className={`text-xs px-2 py-1 rounded border transition-colors ${
                subInd === s
                  ? "border-accent/40 text-accent bg-accent/10"
                  : "border-[#2a2a3a] text-gray-500 hover:text-gray-300"
              }`}
            >
              {s}
            </button>
          ))}
          <button
            onClick={() => setShowBoll((b) => !b)}
            className={`text-xs px-2 py-1 rounded border transition-colors ${
              showBoll
                ? "border-accent/40 text-accent bg-accent/10"
                : "border-[#2a2a3a] text-gray-500 hover:text-gray-300"
            }`}
          >
            BOLL
          </button>
        </div>

        {/* Close */}
        <button
          onClick={onClose}
          className="text-gray-500 hover:text-white transition-colors text-lg px-1 shrink-0"
          aria-label="关闭"
        >
          ✕
        </button>
      </div>

      {/* ── Chart area ── */}
      <div className="flex-1 overflow-hidden">
        {loading && <ChartSkeleton />}

        {/* Full error: no data at all */}
        {!loading && error && !option && (
          <div className="flex items-center justify-center h-full text-gray-500 text-sm">
            <div className="text-center">
              <p className="text-2xl mb-3">📭</p>
              <p>暂无K线数据</p>
              <p className="text-xs text-gray-600 mt-1">{error}</p>
            </div>
          </div>
        )}

        {/* No data, no error */}
        {!loading && !error && !option && (
          <div className="flex items-center justify-center h-full text-gray-500 text-sm">
            <div className="text-center">
              <p className="text-2xl mb-3">📭</p>
              <p>暂无K线数据</p>
            </div>
          </div>
        )}

        {/* Partial error: has data but also a warning — show chart + inline warning */}
        {!loading && error && option && (
          <div className="relative flex-1 h-full">
            <p className="absolute top-1 left-4 text-xs text-yellow-500 z-10">{error}</p>
            <ReactECharts
              option={option}
              style={{ width: "100%", height: "100%" }}
              notMerge={true}
              lazyUpdate={false}
            />
          </div>
        )}

        {!loading && !error && option && (
          <ReactECharts
            option={option}
            style={{ width: "100%", height: "100%" }}
            notMerge={true}
            lazyUpdate={false}
          />
        )}
      </div>
    </div>
  )
}
