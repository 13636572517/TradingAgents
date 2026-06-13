// web/src/pages/StockDetail.tsx
import { useEffect, useMemo, useState } from "react"
import { useNavigate, useParams } from "react-router-dom"
import { api } from "../api/client"
import type { StockDetail, StockDetailKline } from "../types"

type Tab = "balance" | "income" | "cashflow"

function fmtNum(v: unknown, digits = 2, suffix = ""): string {
  if (v === null || v === undefined || v === "") return "—"
  const n = typeof v === "number" ? v : Number(v)
  if (!isFinite(n)) return "—"
  return `${n.toFixed(digits)}${suffix}`
}
function fmtYi(v: unknown): string {
  if (v === null || v === undefined || v === "") return "—"
  const n = typeof v === "number" ? v : Number(v)
  if (!isFinite(n)) return "—"
  if (Math.abs(n) >= 1e8) return `${(n / 1e8).toFixed(2)}亿`
  if (Math.abs(n) >= 1e4) return `${(n / 1e4).toFixed(2)}万`
  return n.toFixed(0)
}
function fmtPct(v: unknown, digits = 2): string {
  if (v === null || v === undefined || v === "") return "—"
  const n = typeof v === "number" ? v : Number(v)
  if (!isFinite(n)) return "—"
  return `${n > 0 ? "+" : ""}${n.toFixed(digits)}%`
}
function pctClass(v: number | null | undefined): string {
  if (v === null || v === undefined || v === 0) return "text-gray-400"
  return v > 0 ? "text-red-400" : "text-green-400"
}

// Simple SVG sparkline for the K-line preview, with a price scale and a
// hover crosshair/tooltip showing the exact date + close price.
function KlineSpark({ bars }: { bars: StockDetailKline[] }) {
  const [hoverIdx, setHoverIdx] = useState<number | null>(null)

  if (bars.length < 2) return <div className="text-xs text-gray-500">K线数据不足</div>

  const closes = bars.map((b) => b.close ?? 0)
  const min = Math.min(...closes)
  const max = Math.max(...closes)
  const range = max - min || 1
  const w = 600, h = 120, pad = 4
  const step = (w - pad * 2) / (closes.length - 1)
  const points = closes.map((c, i) => {
    const x = pad + i * step
    const y = pad + (1 - (c - min) / range) * (h - pad * 2)
    return { x, y }
  })
  const pointsStr = points.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ")
  const first = closes[0], last = closes[closes.length - 1]
  const upTrend = last >= first
  const color = upTrend ? "#f87171" : "#4ade80"

  const handleMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect()
    const relX = (e.clientX - rect.left) / rect.width
    const idx = Math.max(0, Math.min(closes.length - 1, Math.round(relX * (closes.length - 1))))
    setHoverIdx(idx)
  }

  const hover = hoverIdx !== null ? { bar: bars[hoverIdx], pt: points[hoverIdx] } : null
  const tooltipRight = hover ? hover.pt.x > w / 2 : false

  return (
    <div className="relative">
      <div className="absolute left-1 top-0 text-[10px] text-gray-500 font-mono pointer-events-none">{max.toFixed(2)}</div>
      <div className="absolute left-1 bottom-0 text-[10px] text-gray-500 font-mono pointer-events-none">{min.toFixed(2)}</div>
      <svg
        viewBox={`0 0 ${w} ${h}`}
        className="w-full cursor-crosshair"
        preserveAspectRatio="none"
        onMouseMove={handleMove}
        onMouseLeave={() => setHoverIdx(null)}
      >
        <polyline points={pointsStr} fill="none" stroke={color} strokeWidth="1.5" />
        {hover && (
          <>
            <line x1={hover.pt.x} x2={hover.pt.x} y1={pad} y2={h - pad}
                  stroke="#6b7280" strokeWidth="0.75" strokeDasharray="3,3" />
            <circle cx={hover.pt.x} cy={hover.pt.y} r="2.5" fill={color} />
          </>
        )}
      </svg>
      {hover && (
        <div
          className="absolute top-1 text-[10px] font-mono bg-bg/95 border border-border rounded px-1.5 py-1 pointer-events-none whitespace-nowrap"
          style={tooltipRight ? { right: 0 } : { left: 0 }}
        >
          <div className="text-gray-500">{hover.bar.date}</div>
          <div className="text-gray-200">{(hover.bar.close ?? 0).toFixed(2)}</div>
        </div>
      )}
    </div>
  )
}

function MetricsRow({ label, v, format = "num" }:
  { label: string; v: unknown; format?: "num" | "pct" | "yi" }) {
  let val: string
  if (format === "pct") val = fmtPct(v)
  else if (format === "yi") val = fmtYi(v)
  else val = fmtNum(v)
  return (
    <div className="flex justify-between py-1 text-xs">
      <span className="text-gray-500">{label}</span>
      <span className="font-mono text-gray-200">{val}</span>
    </div>
  )
}

export default function StockDetail() {
  const { ticker = "" } = useParams()
  const navigate = useNavigate()
  const [data, setData] = useState<StockDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [tab, setTab] = useState<Tab>("balance")
  const [analyzing, setAnalyzing] = useState(false)

  useEffect(() => {
    let cancelled = false
    setLoading(true); setError(null)
    api.getStockDetail(ticker)
      .then((d) => { if (!cancelled) setData(d) })
      .catch((e) => { if (!cancelled) setError(e?.response?.data?.detail ?? "加载失败") })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [ticker])

  const handleAnalyze = async () => {
    if (!data) return
    setAnalyzing(true)
    try {
      const today = new Date().toISOString().slice(0, 10)
      const a = await api.createAnalysis({
        ticker: data.ticker, trade_date: today,
        analysts: ["fundamentals", "market", "news", "social"], depth: 1,
      })
      navigate(`/report/${a.id}`)
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? "分析启动失败")
    } finally {
      setAnalyzing(false)
    }
  }

  const statementRecords = useMemo(() => {
    if (!data) return []
    return data[tab] ?? []
  }, [data, tab])

  // Build the union of keys across statement rows for the table header, but
  // drop noisy / non-numeric metadata cols so the table stays readable.
  const statementColumns = useMemo(() => {
    const drop = new Set(["symbol", "name", "report_date", "report_type", "currency"])
    const cols: string[] = []
    const seen = new Set<string>()
    for (const r of statementRecords) {
      for (const k of Object.keys(r)) {
        if (drop.has(k) || seen.has(k)) continue
        seen.add(k); cols.push(k)
      }
    }
    // Show period_end first
    cols.sort((a, b) => (a === "period_end" ? -1 : b === "period_end" ? 1 : 0))
    return cols
  }, [statementRecords])

  if (loading) {
    return <div className="max-w-6xl mx-auto px-4 py-12 text-center text-sm text-gray-500">加载中…</div>
  }
  if (error && !data) {
    return (
      <div className="max-w-6xl mx-auto px-4 py-6">
        <button onClick={() => navigate(-1)} className="text-xs text-gray-500 hover:text-gray-300 mb-3">
          ← 返回
        </button>
        <div className="text-sm text-red-400 bg-red-950/30 border border-red-900/50 rounded px-3 py-3">
          {error}
        </div>
      </div>
    )
  }
  if (!data) return null

  const q = data.quote
  return (
    <div className="max-w-6xl mx-auto px-4 py-6">
      <button onClick={() => navigate(-1)} className="text-xs text-gray-500 hover:text-gray-300 mb-3">
        ← 返回
      </button>

      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-4 mb-5">
        <div>
          <h1 className="text-2xl font-semibold text-gray-100">
            {q?.name || "—"}
            <span className="ml-2 font-mono text-base text-gray-500">{q?.code || data.ticker}</span>
            <span className="ml-2 text-xs text-gray-600">{data.tf_code}</span>
          </h1>
          {data.last_screening && (
            <p className="mt-1 text-xs text-gray-500">
              最近入选：
              <button
                onClick={() => navigate(`/screener/runs/${data.last_screening!.run_id}/boards/${data.last_screening!.board_level}/${encodeURIComponent(data.last_screening!.board_name)}`)}
                className="text-accent hover:underline"
              >
                {data.last_screening.board_name} (SW{data.last_screening.board_level})
              </button>
              {data.last_screening.score != null && <span className="ml-2">综合评分 {data.last_screening.score.toFixed(1)}</span>}
              {data.last_screening.reason && <span className="ml-2 text-gray-600">· {data.last_screening.reason}</span>}
            </p>
          )}
        </div>
        <div className="flex flex-col items-end">
          <div className="flex items-baseline gap-3">
            <span className="text-3xl font-mono text-gray-100">{fmtNum(q?.last_price)}</span>
            <span className={`text-sm font-mono ${pctClass(q?.change_pct)}`}>
              {fmtPct(q?.change_pct)}
            </span>
          </div>
          <button
            onClick={handleAnalyze}
            disabled={analyzing}
            className="mt-2 text-xs px-3 py-1 rounded bg-accent/20 text-accent hover:bg-accent/30 disabled:opacity-50"
          >
            {analyzing ? "提交中…" : "发起深度分析"}
          </button>
        </div>
      </div>

      {error && (
        <div className="mb-3 text-xs text-red-400 bg-red-950/30 border border-red-900/50 rounded px-3 py-2">
          {error}
        </div>
      )}
      {data.errors.length > 0 && (
        <div className="mb-3 text-[11px] text-amber-400/80 bg-amber-950/20 border border-amber-900/30 rounded px-3 py-2">
          数据部分缺失：{data.errors.join(" · ")}
        </div>
      )}

      {/* Top row: quote + K-line */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 mb-3">
        <div className="rounded border border-border bg-surface p-3">
          <h2 className="text-xs uppercase tracking-wider text-gray-500 mb-2">实时行情</h2>
          <div className="grid grid-cols-2 gap-x-4">
            <MetricsRow label="开盘"  v={q?.open} />
            <MetricsRow label="昨收"  v={q?.prev_close} />
            <MetricsRow label="最高"  v={q?.high} />
            <MetricsRow label="最低"  v={q?.low} />
            <MetricsRow label="成交量" v={q?.volume} format="yi" />
            <MetricsRow label="成交额" v={q?.amount} format="yi" />
            <MetricsRow label="换手率" v={q?.turnover_rate ? (q.turnover_rate as number) * 100 : null} format="pct" />
            <MetricsRow label="振幅"   v={q?.amplitude ? (q.amplitude as number) * 100 : null} format="pct" />
            <MetricsRow label="PE"     v={q?.pe} />
            <MetricsRow label="PB"     v={q?.pb} />
            <MetricsRow label="总市值"  v={q?.total_mktcap} format="yi" />
            <MetricsRow label="流通市值" v={q?.float_mktcap} format="yi" />
          </div>
        </div>
        <div className="rounded border border-border bg-surface p-3">
          <h2 className="text-xs uppercase tracking-wider text-gray-500 mb-2">
            近 {data.klines.length} 个交易日走势
          </h2>
          <KlineSpark bars={data.klines} />
          {data.klines.length > 0 && (
            <div className="flex justify-between text-[10px] text-gray-600 mt-1 font-mono">
              <span>{data.klines[0].date}</span>
              <span>{data.klines[data.klines.length - 1].date}</span>
            </div>
          )}
        </div>
      </div>

      {/* Metrics history */}
      <div className="rounded border border-border bg-surface p-3 mb-3">
        <h2 className="text-xs uppercase tracking-wider text-gray-500 mb-2">财务指标（最近 {data.metrics.length} 期）</h2>
        {data.metrics.length === 0 ? (
          <p className="text-xs text-gray-500">暂无数据</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="text-gray-500">
                <tr>
                  <th className="text-left font-medium py-1 pr-3">报告期</th>
                  <th className="text-right font-medium py-1 px-2">ROE</th>
                  <th className="text-right font-medium py-1 px-2">ROA</th>
                  <th className="text-right font-medium py-1 px-2">净利率</th>
                  <th className="text-right font-medium py-1 px-2">毛利率</th>
                  <th className="text-right font-medium py-1 px-2">EPS</th>
                  <th className="text-right font-medium py-1 px-2">BPS</th>
                  <th className="text-right font-medium py-1 px-2">营收同比</th>
                  <th className="text-right font-medium py-1 px-2">净利同比</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/50">
                {data.metrics.map((m, i) => (
                  <tr key={i} className="text-gray-300">
                    <td className="py-1 pr-3 font-mono text-gray-400">{String(m.period_end ?? "—")}</td>
                    <td className="text-right font-mono py-1 px-2">{fmtPct((m.roe as number) * 100)}</td>
                    <td className="text-right font-mono py-1 px-2">{fmtPct((m.roa as number) * 100)}</td>
                    <td className="text-right font-mono py-1 px-2">{fmtPct((m.net_margin as number) * 100)}</td>
                    <td className="text-right font-mono py-1 px-2">{fmtPct((m.gross_margin as number) * 100)}</td>
                    <td className="text-right font-mono py-1 px-2">{fmtNum(m.eps_basic)}</td>
                    <td className="text-right font-mono py-1 px-2">{fmtNum(m.bps)}</td>
                    <td className="text-right font-mono py-1 px-2">{fmtPct((m.revenue_yoy as number) * 100)}</td>
                    <td className="text-right font-mono py-1 px-2">{fmtPct((m.net_income_yoy as number) * 100)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Statements */}
      <div className="rounded border border-border bg-surface p-3 mb-3">
        <div className="flex items-center gap-2 mb-2">
          <h2 className="text-xs uppercase tracking-wider text-gray-500">三大报表</h2>
          <div className="flex gap-1 ml-2">
            {([
              ["balance", "资产负债表"],
              ["income", "利润表"],
              ["cashflow", "现金流量表"],
            ] as [Tab, string][]).map(([k, label]) => (
              <button
                key={k}
                onClick={() => setTab(k)}
                className={`text-[11px] px-2 py-0.5 rounded ${tab === k
                  ? "bg-accent/20 text-accent"
                  : "text-gray-500 hover:text-gray-300"}`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
        {statementRecords.length === 0 ? (
          <p className="text-xs text-gray-500">暂无数据</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="text-gray-500">
                <tr>
                  {statementColumns.map((c) => (
                    <th key={c} className="text-right font-medium py-1 px-2 whitespace-nowrap">{c}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-border/50">
                {statementRecords.map((rec, i) => (
                  <tr key={i} className="text-gray-300">
                    {statementColumns.map((c) => {
                      const v = (rec as Record<string, unknown>)[c]
                      const isPeriod = c === "period_end"
                      return (
                        <td key={c} className={`py-1 px-2 font-mono whitespace-nowrap ${isPeriod ? "text-gray-400 text-left" : "text-right"}`}>
                          {typeof v === "number" ? fmtYi(v) : (v == null ? "—" : String(v))}
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Past analyses */}
      {data.past_analyses.length > 0 && (
        <div className="rounded border border-border bg-surface p-3">
          <h2 className="text-xs uppercase tracking-wider text-gray-500 mb-2">历史分析</h2>
          <ul className="text-xs divide-y divide-border/50">
            {data.past_analyses.map((a) => (
              <li key={a.id} className="py-1.5 flex justify-between">
                <span className="text-gray-400">
                  {a.trade_date} <span className="text-gray-600">· 深度 {a.depth}</span>
                </span>
                <button onClick={() => navigate(`/report/${a.id}`)} className="text-accent hover:underline">查看 →</button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
