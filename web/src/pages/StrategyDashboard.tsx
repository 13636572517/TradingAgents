// web/src/pages/StrategyDashboard.tsx
import { useEffect, useState, useCallback, useRef } from "react"
import { useNavigate } from "react-router-dom"
import { api } from "../api/client"
import type { Strategy } from "../types"

const POLL_INTERVAL_MS = 5 * 60 * 1000   // 5 minutes

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmt(n: number | null | undefined, digits = 3): string {
  if (n == null) return "—"
  return n.toFixed(digits)
}

function pct(a: number | null, b: number | null): string {
  if (a == null || b == null || b === 0) return "—"
  const v = ((a - b) / b) * 100
  return (v >= 0 ? "+" : "") + v.toFixed(2) + "%"
}

function dirLabel(d: string | null) {
  if (d === "BUY")  return { text: "买入", cls: "bg-buy/20 text-buy border border-buy/40" }
  if (d === "SELL") return { text: "卖出", cls: "bg-sell/20 text-sell border border-sell/40" }
  return { text: "持有", cls: "bg-hold/20 text-hold border border-hold/40" }
}

function statusLabel(s: string) {
  if (s === "active")  return { text: "监控中", cls: "text-buy" }
  if (s === "expired") return { text: "已过期", cls: "text-gray-500" }
  return { text: "已关闭", cls: "text-gray-600" }
}

function stopLossAlert(entry: number | null, current: number | null, stop: number | null, dir: string | null) {
  if (!entry || !current || !stop) return null
  const isBuy = dir === "BUY" || dir === "HOLD"
  if (isBuy) {
    const gap = ((current - stop) / current) * 100
    if (current <= stop) return { level: "hit",  text: "⚠ 已触及止损", cls: "text-red-400" }
    if (gap < 3)          return { level: "near", text: `⚡ 距止损 ${gap.toFixed(1)}%`, cls: "text-orange-400" }
  } else {
    const gap = ((stop - current) / current) * 100
    if (current >= stop) return { level: "hit",  text: "⚠ 已触及止损", cls: "text-red-400" }
    if (gap < 3)         return { level: "near", text: `⚡ 距止损 ${gap.toFixed(1)}%`, cls: "text-orange-400" }
  }
  return null
}

function targetAlert(entry: number | null, current: number | null, target: number | null, dir: string | null) {
  if (!entry || !current || !target) return null
  const isBuy = dir === "BUY" || dir === "HOLD"
  if (isBuy && current >= target)  return { text: "✓ 已达目标价", cls: "text-buy" }
  if (!isBuy && current <= target) return { text: "✓ 已达目标价", cls: "text-buy" }
  return null
}

// Progress bar: shows current price position between stop_loss and target_price
function PriceBar({ entry, current, stop, target, dir }: {
  entry: number | null; current: number | null
  stop: number | null; target: number | null; dir: string | null
}) {
  if (!entry || !current) return null
  const isBuy = dir === "BUY" || dir === "HOLD"

  const lo = stop  != null ? Math.min(stop,  current, entry) * 0.995 : Math.min(current, entry) * 0.97
  const hi = target != null ? Math.max(target, current, entry) * 1.005 : Math.max(current, entry) * 1.03
  const range = hi - lo
  if (range <= 0) return null

  const pos     = ((current - lo) / range) * 100
  const entryP  = ((entry   - lo) / range) * 100
  const stopP   = stop   != null ? ((stop   - lo) / range) * 100 : null
  const targetP = target != null ? ((target - lo) / range) * 100 : null

  const barColor = isBuy ? "bg-buy" : "bg-sell"
  const overShoot = isBuy
    ? (target != null && current > target)
    : (target != null && current < target)
  const underStop = isBuy
    ? (stop != null && current < stop)
    : (stop != null && current > stop)

  return (
    <div className="relative h-5 mt-2 mb-1">
      {/* track */}
      <div className="absolute inset-y-1/2 -translate-y-1/2 left-0 right-0 h-1 bg-white/10 rounded-full" />
      {/* fill to current */}
      <div
        className={`absolute inset-y-1/2 -translate-y-1/2 h-1 rounded-full ${overShoot ? "bg-buy" : underStop ? "bg-red-500" : barColor} opacity-60`}
        style={{ left: `${Math.min(entryP, pos)}%`, width: `${Math.abs(pos - entryP)}%` }}
      />
      {/* stop marker */}
      {stopP != null && (
        <div className="absolute inset-y-0 flex flex-col items-center" style={{ left: `${stopP}%` }}>
          <div className="w-0.5 h-full bg-red-500/70" />
          <span className="absolute -bottom-4 text-[9px] text-red-400 whitespace-nowrap -translate-x-1/2">
            {fmt(stop, 2)}
          </span>
        </div>
      )}
      {/* target marker */}
      {targetP != null && (
        <div className="absolute inset-y-0 flex flex-col items-center" style={{ left: `${targetP}%` }}>
          <div className="w-0.5 h-full bg-buy/70" />
          <span className="absolute -bottom-4 text-[9px] text-buy whitespace-nowrap -translate-x-1/2">
            {fmt(target, 2)}
          </span>
        </div>
      )}
      {/* entry marker */}
      <div
        className="absolute inset-y-0 flex flex-col items-center"
        style={{ left: `${entryP}%` }}
      >
        <div className="w-0.5 h-full bg-gray-400/50" />
      </div>
      {/* current price dot */}
      <div
        className={`absolute top-1/2 -translate-y-1/2 -translate-x-1/2 w-3 h-3 rounded-full border-2 border-bg ${overShoot ? "bg-buy" : underStop ? "bg-red-500" : "bg-white"}`}
        style={{ left: `${Math.max(0, Math.min(100, pos))}%` }}
      />
    </div>
  )
}

// ── Confidence badge ──────────────────────────────────────────────────────────

function ConfidenceBadge({ confidence, method }: { confidence: string | null; method: string | null }) {
  if (method === "ai") {
    const map: Record<string, string> = {
      high:   "text-buy bg-buy/10 border-buy/30",
      medium: "text-yellow-400 bg-yellow-400/10 border-yellow-400/30",
      low:    "text-orange-400 bg-orange-400/10 border-orange-400/30",
    }
    const cls = confidence ? (map[confidence] ?? map.medium) : map.medium
    const label = confidence === "high" ? "AI高置信" : confidence === "low" ? "AI低置信" : "AI提取"
    return <span className={`text-[9px] px-1 py-0.5 rounded border ${cls}`}>{label}</span>
  }
  return <span className="text-[9px] px-1 py-0.5 rounded border text-gray-600 border-gray-700">正则</span>
}

// ── Strategy Card ─────────────────────────────────────────────────────────────

function StrategyCard({ s, onClose, onClick, onReExtract, reExtracting }: {
  s: Strategy
  onClose: () => void
  onClick: () => void
  onReExtract: () => void
  reExtracting: boolean
}) {
  const dir = dirLabel(s.direction)
  const sts = statusLabel(s.status)
  const slAlert = stopLossAlert(s.entry_price, s.current_price, s.stop_loss, s.direction)
  const tgtAlert = targetAlert(s.entry_price, s.current_price, s.target_price, s.direction)

  const priceChange = pct(s.current_price, s.entry_price)
  const isUp = s.current_price != null && s.entry_price != null && s.current_price > s.entry_price

  return (
    <div className={`bg-surface border rounded-lg p-4 flex flex-col gap-3 transition-colors hover:border-accent/40 ${
      slAlert?.level === "hit" ? "border-red-500/60" :
      slAlert?.level === "near" ? "border-orange-400/50" :
      tgtAlert ? "border-buy/50" :
      "border-border"
    }`}>
      {/* Header row */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <button onClick={onClick} className="font-bold text-white hover:text-accent truncate">
            {s.ticker}
          </button>
          {s.ticker_name && (
            <span className="text-xs text-gray-500 truncate">{s.ticker_name}</span>
          )}
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          <ConfidenceBadge confidence={s.confidence} method={s.extraction_method} />
          <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${dir.cls}`}>{dir.text}</span>
          <span className={`text-[10px] ${sts.cls}`}>{sts.text}</span>
        </div>
      </div>

      {/* Price row */}
      <div className="grid grid-cols-3 gap-2 text-sm">
        <div>
          <div className="text-gray-500 text-xs mb-0.5">入场价</div>
          <div className="text-white font-mono">{fmt(s.entry_price, 3)}</div>
        </div>
        <div>
          <div className="text-gray-500 text-xs mb-0.5">当前价</div>
          <div className={`font-mono font-semibold ${s.current_price == null ? "text-gray-500" : isUp ? "text-buy" : "text-sell"}`}>
            {fmt(s.current_price, 3)}
          </div>
        </div>
        <div>
          <div className="text-gray-500 text-xs mb-0.5">涨跌</div>
          <div className={`font-mono text-sm ${isUp ? "text-buy" : "text-sell"}`}>{priceChange}</div>
        </div>
      </div>

      {/* Progress bar */}
      <PriceBar
        entry={s.entry_price}
        current={s.current_price}
        stop={s.stop_loss}
        target={s.target_price}
        dir={s.direction}
      />
      <div className="h-4" /> {/* spacer for label overflow */}

      {/* Stop-loss / target details */}
      <div className="grid grid-cols-2 gap-2 text-xs">
        <div className="bg-red-500/5 border border-red-500/20 rounded px-2 py-1.5">
          <div className="text-gray-500 mb-0.5">止损价</div>
          <div className="text-red-400 font-mono">{fmt(s.stop_loss, 3)}</div>
          {s.stop_loss_basis && (
            <div className="text-gray-600 text-[10px]">{s.stop_loss_basis}</div>
          )}
          {s.stop_loss != null && s.current_price != null && (
            <div className="text-gray-600 text-[10px] mt-0.5">
              距止损 {pct(s.current_price, s.stop_loss)}
            </div>
          )}
        </div>
        <div className="bg-buy/5 border border-buy/20 rounded px-2 py-1.5">
          <div className="text-gray-500 mb-0.5">目标价</div>
          <div className="text-buy font-mono">{fmt(s.target_price, 3)}</div>
          {s.target_price_basis && (
            <div className="text-gray-600 text-[10px]">{s.target_price_basis}</div>
          )}
          {s.target_price != null && s.current_price != null && (
            <div className="text-gray-600 text-[10px] mt-0.5">
              距目标 {pct(s.target_price, s.current_price)}
            </div>
          )}
        </div>
      </div>

      {/* AI extraction note */}
      {s.extraction_note && (
        <div className="text-[10px] text-gray-500 bg-white/3 rounded px-2 py-1.5 leading-relaxed">
          💡 {s.extraction_note}
        </div>
      )}

      {/* Alert banners */}
      {(slAlert || tgtAlert) && (
        <div className="flex flex-wrap gap-1">
          {slAlert && <span className={`text-xs font-medium ${slAlert.cls}`}>{slAlert.text}</span>}
          {tgtAlert && <span className={`text-xs font-medium ${tgtAlert.cls}`}>{tgtAlert.text}</span>}
        </div>
      )}

      {/* Footer */}
      <div className="flex items-center justify-between text-[10px] text-gray-600 pt-1 border-t border-border/50">
        <div className="flex gap-2 flex-wrap">
          <span>分析日 {s.trade_date}</span>
          {s.position_size  && <span>仓位 {s.position_size}</span>}
          {s.time_horizon   && <span>{s.time_horizon}</span>}
        </div>
        <div className="flex gap-2">
          <button
            onClick={(e) => { e.stopPropagation(); onReExtract() }}
            disabled={reExtracting}
            className="text-gray-600 hover:text-accent transition-colors disabled:opacity-40"
            title="用AI重新提取止损/目标价"
          >
            {reExtracting ? "提取中…" : "AI重提"}
          </button>
          {s.status === "active" && (
            <button
              onClick={(e) => { e.stopPropagation(); onClose() }}
              className="text-gray-600 hover:text-red-400 transition-colors"
              title="关闭策略"
            >
              关闭
            </button>
          )}
        </div>
      </div>

      {s.price_updated_at && (
        <div className="text-[9px] text-gray-700">
          价格更新：{new Date(s.price_updated_at).toLocaleString("zh-CN")}
        </div>
      )}
    </div>
  )
}

// ── Main Page ──────────────────────────────────────────────────────────────────

export default function StrategyDashboard() {
  const navigate = useNavigate()
  const [strategies, setStrategies] = useState<Strategy[]>([])
  const [loading, setLoading]     = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [backfilling, setBackfilling] = useState(false)
  const [backfillMsg, setBackfillMsg] = useState<string | null>(null)
  const [filter, setFilter] = useState<"all" | "active" | "BUY" | "SELL" | "HOLD">("active")
  const [reExtractingId, setReExtractingId] = useState<string | null>(null)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const load = useCallback(async () => {
    try {
      const data = await api.getStrategies()
      setStrategies(data)
    } catch { /* silent */ }
    finally { setLoading(false) }
  }, [])

  const handleRefresh = async () => {
    setRefreshing(true)
    try {
      const data = await api.refreshStrategyPrices()
      setStrategies(data)
    } catch { /* silent */ }
    finally { setRefreshing(false) }
  }

  const handleBackfill = async () => {
    setBackfilling(true)
    setBackfillMsg(null)
    try {
      const r = await api.backfillStrategies()
      setBackfillMsg(`回填完成：新增 ${r.created}，跳过 ${r.skipped}，失败 ${r.failed}`)
      await load()
    } catch {
      setBackfillMsg("回填失败")
    } finally {
      setBackfilling(false)
    }
  }

  const handleClose = async (id: string) => {
    try {
      const updated = await api.closeStrategy(id)
      setStrategies((prev) => prev.map((s) => s.id === id ? updated : s))
    } catch { /* silent */ }
  }

  const handleReExtract = async (id: string) => {
    setReExtractingId(id)
    try {
      const updated = await api.reExtractStrategy(id)
      setStrategies((prev) => prev.map((s) => s.id === id ? updated : s))
    } catch (e: any) {
      alert(e?.response?.data?.detail ?? "AI重新提取失败")
    } finally {
      setReExtractingId(null)
    }
  }

  // Initial load + 5-min poll while page is visible
  useEffect(() => {
    load()
    const startPoll = () => {
      intervalRef.current = setInterval(() => {
        if (!document.hidden) handleRefresh()
      }, POLL_INTERVAL_MS)
    }
    startPoll()
    const onVisibility = () => {
      if (document.hidden) {
        if (intervalRef.current) clearInterval(intervalRef.current)
      } else {
        handleRefresh()
        startPoll()
      }
    }
    document.addEventListener("visibilitychange", onVisibility)
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current)
      document.removeEventListener("visibilitychange", onVisibility)
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const filtered = strategies.filter((s) => {
    if (filter === "active") return s.status === "active"
    if (filter === "all")    return true
    return s.direction === filter
  })

  const counts = {
    active: strategies.filter((s) => s.status === "active").length,
    buy:    strategies.filter((s) => s.status === "active" && s.direction === "BUY").length,
    sell:   strategies.filter((s) => s.status === "active" && s.direction === "SELL").length,
    hold:   strategies.filter((s) => s.status === "active" && s.direction === "HOLD").length,
    expired:strategies.filter((s) => s.status === "expired").length,
  }

  return (
    <div className="max-w-5xl mx-auto px-4 py-8">
      {/* Header */}
      <div className="flex items-center justify-between mb-6 flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-white">策略看板</h1>
          <p className="text-gray-500 text-sm mt-1">从历史分析报告提取交易策略，结合实时价格监控止盈止损</p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={handleBackfill}
            disabled={backfilling}
            className="text-xs px-3 py-1.5 rounded border border-border text-gray-400 hover:border-accent hover:text-accent disabled:opacity-40 transition-colors"
            title="提取所有历史分析报告的策略"
          >
            {backfilling ? "回填中…" : "↺ 回填历史"}
          </button>
          <button
            onClick={handleRefresh}
            disabled={refreshing}
            className="text-xs px-3 py-1.5 rounded border border-border text-gray-400 hover:border-accent hover:text-accent disabled:opacity-40 transition-colors"
          >
            {refreshing ? "更新中…" : "⟳ 刷新价格"}
          </button>
        </div>
      </div>

      {backfillMsg && (
        <div className="mb-4 text-sm text-accent bg-accent/10 border border-accent/30 rounded px-3 py-2">
          {backfillMsg}
        </div>
      )}

      {/* Stats bar */}
      <div className="grid grid-cols-4 gap-3 mb-6">
        {[
          { label: "监控中", value: counts.active,  cls: "text-white" },
          { label: "买入",   value: counts.buy,     cls: "text-buy" },
          { label: "卖出",   value: counts.sell,    cls: "text-sell" },
          { label: "已过期", value: counts.expired, cls: "text-gray-500" },
        ].map((item) => (
          <div key={item.label} className="bg-surface border border-border rounded-lg p-3 text-center">
            <div className={`text-2xl font-bold ${item.cls}`}>{item.value}</div>
            <div className="text-xs text-gray-500 mt-0.5">{item.label}</div>
          </div>
        ))}
      </div>

      {/* Filter tabs */}
      <div className="flex gap-1 mb-5 flex-wrap">
        {(["active", "all", "BUY", "SELL", "HOLD"] as const).map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`text-xs px-3 py-1.5 rounded-full border transition-colors ${
              filter === f
                ? "border-accent text-accent bg-accent/10"
                : "border-border text-gray-500 hover:border-accent/50 hover:text-gray-300"
            }`}
          >
            {{ active: "监控中", all: "全部", BUY: "买入", SELL: "卖出", HOLD: "持有" }[f]}
          </button>
        ))}
      </div>

      {/* Cards grid */}
      {loading ? (
        <div className="text-center text-gray-500 py-16">加载中…</div>
      ) : filtered.length === 0 ? (
        <div className="text-center text-gray-500 py-16">
          <div className="text-4xl mb-3">📋</div>
          <div>暂无策略记录</div>
          {strategies.length === 0 && (
            <button
              onClick={handleBackfill}
              className="mt-4 text-sm text-accent hover:underline"
            >
              点击"回填历史"从已有分析报告中提取策略
            </button>
          )}
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {filtered.map((s) => (
            <StrategyCard
              key={s.id}
              s={s}
              onClose={() => handleClose(s.id)}
              onClick={() => navigate(`/report/${s.analysis_id}`)}
              onReExtract={() => handleReExtract(s.id)}
              reExtracting={reExtractingId === s.id}
            />
          ))}
        </div>
      )}

      <p className="text-[10px] text-gray-700 mt-8 text-center">
        价格每 5 分钟自动刷新（停留在本页时） · 止损/目标价由 AI 决策报告自动提取，仅供参考，不构成投资建议
      </p>
    </div>
  )
}
